#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""日本語関数型プログラミング言語「する」のインタプリタ(プロトタイプ)

使い方:
    python3 suru.py ファイル.suru     # ファイルを実行(トップレベルの式の値を表示)
    python3 suru.py                   # 対話モード(REPL)
"""
from __future__ import annotations

__version__ = "0.11.0"

import contextlib
import re
import math
import os
import stat
import struct
import sys
import unicodedata
import dataclasses
from dataclasses import dataclass, field
from typing import Any

if sys.platform == "win32":
    fcntl = None
else:
    import fcntl


def _lock_fd(fd: int, lock: bool) -> None:
    """ファイルを、ほかの人が書かないように止める(lock)・止めるのをやめる。Windows では名前つきの通路がないので何もしない"""
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX if lock else fcntl.LOCK_UN)

# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------


_POS_SRC: str | None = None  # 読み込んだファイルを解析している間は、そのファイルの道(Pos.src に入れる)
SOURCES: dict[str, str] = {}  # 読み込んだファイルの道 → 中身(エラーの行を見せるため)
# ライブラリのファイル(同梱の lib/ と依存のもの、そこから読み込んだもの)の道。それ以外は自分のプログラム(#154)
LIBRARY_SRCS: set[str] = set()


class Pos(int):
    """行番号。int として使えるが、何文字目か(col)と、読み込んだファイルの中ならその道(src)も覚えている"""

    col: int | None
    src: str | None

    def __new__(cls, line: int, col: int | None = None) -> "Pos":
        obj = int.__new__(cls, line)
        obj.col = col
        obj.src = _POS_SRC
        return obj


def _file_of(line: Any) -> str:
    """読み込んだファイルの中の位置なら「「部品.suru」の」(本体のファイルなら「」)"""
    src = getattr(line, "src", None)
    return f"「{os.path.basename(src)}」の" if src else ""


def _where(line: int | None) -> str:
    col = getattr(line, "col", None)
    return f"{line}行目 {col}文字目" if col else f"{line}行目"


# 自分のプログラムから、ライブラリの関数を呼んでいる場所(#154。スレッドごと)。
# ライブラリの中で実行時エラーになったら、この場所をエラーの位置にして、ライブラリの位置は添えるだけにする
_CALL = __import__("threading").local()


def call_pos() -> Any:
    return getattr(_CALL, "pos", None)


def in_library(line: Any) -> bool:
    """ライブラリのファイルの中の位置か"""
    return getattr(line, "src", None) in LIBRARY_SRCS


def is_user_pos(line: Any) -> bool:
    """自分のプログラム(本体と、ライブラリでない読み込んだファイル)の位置か"""
    return bool(line) and getattr(line, "src", None) not in LIBRARY_SRCS


class SuruError(Exception):
    """「する」の実行時・構文エラー"""

    def __init__(self, message: str, line: int | None = None):
        self.lib_where = ""  # ライブラリの中の位置(「(「標準.suru」の43行目)」)。line は自分のプログラムの呼んだ場所
        if line and in_library(line):
            cp = call_pos()
            if cp:
                self.lib_where = f"({_file_of(line)}{_where(line)})"
                line = cp
        self.line = line
        self.col = getattr(line, "col", None)
        self.message = message
        super().__init__(f"{_file_of(line)}{_where(line)}: {message}{self.lib_where}" if line else message)


def module_error(e: Any, name: str, path: str, line: Any) -> "SuruError":
    """読み込んだファイルの中のエラー e を、読み込む行(line)のエラーにする。
    元のエラー(いちばん内側のファイルのもの)は origin に (道, エラー) で残す(--json で使う)"""
    err = SuruError(f"「{name}{SOURCE_SUFFIX}」の{_where(e.line) if e.line else ''}: {e.message}", line)
    err.origin = getattr(e, "origin", None) or (getattr(e.line, "src", None) or path, e)
    return err


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def error_json(e: "SuruError", kind: str = "実行", path: str = "") -> str:
    """--json のときのエラーの1行の JSON。kind は e に印(e.kind)があればそちら(構文・型・実行・コンパイル)。
    点検の知らせ(lib/点検.suru の 知らせJSON化する)と同じ形"""
    import json

    kind = getattr(e, "kind", None) or kind
    origin = getattr(e, "origin", None)
    if origin:  # 読み込んだファイルの中のエラーなら、そのファイルの位置を出す
        path, e = origin
    line = e.line
    src = getattr(line, "src", None)
    return json.dumps(
        {
            "file": src or path or None,
            "line": int(line) if line else None,
            "column": e.col or None,
            "kind": kind,
            "rule": None,
            "message": e.message + getattr(e, "lib_where", ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def format_error(e: "SuruError", source: str | None = None) -> str:
    """エラーの文と、分かれば該当する行と位置の印(^)を返す"""
    out = f"エラー: {e}"
    src = getattr(e.line, "src", None)
    if src:
        source = SOURCES.get(src)
    lines = source.splitlines() if source is not None else []
    if e.line and 0 < e.line <= len(lines):
        text = lines[e.line - 1].replace("\t", "    ")
        out += f"\n  {text}"
        if e.col:
            raw = lines[e.line - 1][: e.col - 1].replace("\t", "    ")
            out += "\n  " + " " * _display_width(raw) + "^"
    return out


# ---------------------------------------------------------------------------
# 字句解析
# ---------------------------------------------------------------------------

SPACES = {" ", "　", "\t"}
INDENT_WIDTH = {" ": 1, "　": 2, "\t": 4}  # 全角スペースは半角2つ分として数える
COMMENT_STARTS = ("#", "＃", "※")
OPEN_PARENS = {"(", "（"}
CLOSE_PARENS = {")", "）"}

# 記号は NFKC 正規化した上で判定する(全角の＋－＊／＜＞＝も使える)
OPERATORS = {
    "+": "+", "-": "-", "−": "-", "*": "*", "×": "*", "/": "/", "÷": "/",
    "%": "%", "^": "^", "**": "^",
    "==": "==", "=": "==", "!=": "!=", "≠": "!=",
    "<": "<", ">": ">", "<=": "<=", "≦": "<=", "≤": "<=", ">=": ">=", "≧": ">=", "≥": ">=",
}

KW_TO = "と"          # リストを作る: 1 と 2 と 3
KW_TOWA = "とは"      # 定義
KW_NO = "の"          # 性質: リスト の 先頭
KW_GA = "が"          # 等しい: リスト が 空
KW_IF = "もし"
KW_THEN = "ならば"
KW_ELSE = "そうでなければ"
KW_LAMBDA = "受け取って"  # 無名関数: x を 受け取って x * 2 を 返すこと
KW_RETURN = "返すこと"
KW_EMPTY = "空"
KW_PROVISO = "ただし"  # 局所定義を前の定義に付け足す: … 。ただし、合計とは、a+b。
KW_KA = "か"          # 選択肢の型: 図形 とは 半径 の 円 か 幅 と 高 の 長方形
KW_WA = "は"          # 名前つきの組: 横 は 3 で 縦 は 4 の 点 / 性質の実装: 点 は 比較可能
KW_TOIU = "という"    # 性質の定義: 比較可能 という 性質 とは …
KW_KUMI = "組"        # 組の定義: 点 とは 横 と 縦 の 組
KW_SEISHITSU = "性質"
KW_SOREKARA = "それから"  # 前の文に続けて行う: 「やあ」を表示する。それから、「またね」を表示する。
KW_KATSU = "かつ"      # 真偽の「かつ」、パターンの条件: 半径 の 円 かつ 半径 > 10 ならば …
KW_MATAHA = "または"   # 真偽の「または」
DESU = "です"       # 文末の飾り: 「p とは 3 と 4 の 点 です。」の「です」は読み捨てる
KW_HENSU = "返す"    # 関数の型の宣言の終わりの飾り: 「数 を 階乗する は 数 を 返す」の「を 返す」は読み捨てる
KW_HENSU_POLITE = "返します"
RESERVED_MARKS = {"・": "中黒「・」"}
MODULE_MARK = "内"  # 読み込んだファイルの中の名前: 数学内の円周率
MODULE_SEP = MODULE_MARK + "の"
KW_IMPORT = "読み込む"  # 「数学」 を 読み込む
KW_IMPORT_POLITE = "読み込みます"
KW_IMPORT_TE = "読み込んで"  # 「数学」 を 読み込んで 使う: 前置きなしで使う
KW_USE = "使う"
KW_USE_POLITE = "使います"
SOURCE_SUFFIX = ".suru"
KW_MAIN_THREAD = "主スレッドで"  # 外部の「SDL3」 を 主スレッドで 読み込む
KW_EXTERN = "外部の"  # 外部の「m」 を 読み込む / x を 余弦にする とは 外部の「cos」
KW_IJOU = "以上"  # 「以下の手順です」と「もし 値 が」の場合分けを閉じる言葉
KW_IKA = "以下の手順"  # 「挨拶する とは 以下の手順です」+ 文 + 「以上」
KW_IKA_IO = "以下の入出力手順"
IKA_WORDS = {KW_IKA: "手順", KW_IKA_IO: "入出力手順"}
# 外部の関数のまとまり: 「以下は外部の入出力動作です」+ 1行に1つの関数 + 「以上です」(#174)。
# 文の頭なので「以下は」と書きます。「以下の外部の…」も同じ意味で書けます(0.9.0 の書き方)
KW_IKA_EXT_IO = "以下は外部の入出力動作"
KW_IKA_EXT = "以下は外部の関数"
KW_IKA_EXT_IO_NO = "以下の外部の入出力動作"
KW_IKA_EXT_NO = "以下の外部の関数"
# 他の言語に出す関数のまとまり: 「以下は外部に出す関数です」+ 1行に1つ「二倍する は 「nibai」」+ 「以上です」(#208)
KW_IKA_EXPORT = "以下は外部に出す関数"
EXT_IO_WORDS = (KW_IKA_EXT_IO, KW_IKA_EXT_IO_NO)
EXT_BLOCK_WORDS = (KW_IKA_EXT_IO, KW_IKA_EXT, KW_IKA_EXT_IO_NO, KW_IKA_EXT_NO)
# 同じファイルの試験(#193): 「以下は「二倍」の試験です」+ 手順の文 + 「以上です」。通常の実行とビルドでは捨てる
TEST_HEAD_OPEN = "以下は「"
TEST_HEAD_CLOSE = "」の試験"
TEST_LIB = "試験"  # 試験のまとまりがあれば、「試験」 を 読み込んで 使う(書かなくてよい)
# 例(#193): 「例えば （2 を 二倍する） は 4 です」。すぐ上の定義の例で、試験のときに確かめる
KW_EXAMPLE = "例えば"


def test_head(name: str) -> str:
    """試験のまとまりの頭の言葉(「以下は「二倍」の試験」)"""
    return TEST_HEAD_OPEN + name + TEST_HEAD_CLOSE


def is_test_head(tok: "Token | None") -> bool:
    return (tok is not None and tok.kind == "KW" and isinstance(tok.value, str)
            and tok.value.startswith(TEST_HEAD_OPEN) and tok.value.endswith(TEST_HEAD_CLOSE))


def test_head_name(tok: "Token") -> str:
    return tok.value[len(TEST_HEAD_OPEN):-len(TEST_HEAD_CLOSE)]

KEYWORDS = {
    KW_TO, KW_TOWA, KW_NO, KW_GA, KW_IF, KW_THEN, KW_ELSE, KW_LAMBDA, KW_RETURN, KW_PROVISO,
    KW_KA, KW_WA, KW_TOIU, KW_KUMI, KW_SEISHITSU, KW_SOREKARA, KW_KATSU, KW_MATAHA, DESU, KW_HENSU, KW_HENSU_POLITE,
    KW_IMPORT, KW_IMPORT_POLITE, KW_IMPORT_TE, KW_USE, KW_USE_POLITE, KW_IJOU, KW_IKA, KW_IKA_IO,
    KW_IKA_EXT_IO, KW_IKA_EXT, KW_IKA_EXT_IO_NO, KW_IKA_EXT_NO, KW_IKA_EXPORT,
}
KANJI_KEYWORDS = {KW_KUMI, KW_SEISHITSU, KW_IJOU}
CONTINUATION_KEYWORDS = {KW_THEN, KW_ELSE}
# 書き方を案内するエラー(#155)
EACH_LAMBDA_MESSAGE = ("「それぞれ」の後には「…する」で終わる関数の名前を書きます"
                       "(無名関数を使うときは「xs を （x を 受け取って … を 返すこと） で 写像する」と書きます)")
MATCH_CALL_MESSAGE = ("「もし 値 が」の場合分けで値に呼び出しを書くときは、括弧で囲んでください"
                      "(「もし （s を JSON解析する） が」のように書きます)")
PROVISO_INDENT_MESSAGE = "「ただし」は、付け足す定義の行と同じ字下げで書いてください(字下げした行は前の行の続きとして読みます)"  # 行頭に来たら前の文の続きとみなす

# 引数を区別する格助詞。長いものから順に照合する(「より」「から」を先に)
PARTICLES = ("より", "から", "を", "に", "で", "へ")
WO = "を"

# 句読点の書き方: 「。」は文の終わり、「、」は区切り(スペースと同じ)
PERIOD = "。"
COMMA = "、"
# ひらがなを含む名前を囲む括弧(「」は文字列なので『』を使う)
NAME_OPEN, NAME_CLOSE = "『", "』"
# 将来の書き方のために予約している記号

SURU = "する"       # 終止形: パイプラインの終わり
SHITE = "して"      # 連用形: 結果を次の関数の「を」へ渡す
KOTO = "すること"   # 名詞化: 関数そのもの(値)
SHITEKARA = "してから"  # 前の動作を行ってから、その結果を次の関数の「を」へ渡す(バインド)
SHITA = "した"      # 「入力した 結果」: 手順の中で動作を行い、その結果を値として使う
DEARU = "である"    # 述語(真偽を返す関数): n が 偶数である
DENAI = "でない"    # 述語の否定: n が 偶数でない
DEARUKOTO = "であること"  # 述語そのもの(値): 偶数であること
GA = "が"           # 述語の主語の助詞
# 丁寧語: 「三倍します」は「三倍する」、「三倍しまして」は「三倍して」と同じに読む
POLITE_FORMS = {"します": SURU, "しまして": SHITE, "しましてから": SHITEKARA}

# 予約語ではなく、決まった位置でだけ特別な意味になる言葉
RESULT = "結果"     # 「入力 の 結果 を 数値にする」「入力した 結果」
CONTENT = "中身"    # 「安全除算した 中身」: 成功(有)なら中の値、失敗(無)ならその失敗を返す(Rust の ?)
TEJUN = "手順"      # 「手順（文。文。…）」: 文を順に行う
TEJUN_IO = "入出力手順"  # 動作(IO)だけの手順。型の検査で値が動作かを確かめる
HOLE = "\0前の結果"  # 「してから」の後ろの関数に渡す値(内部の名前)

PROPERTIES = {"先頭", "残り", "最後", "長さ", "それぞれ"}


@dataclass
class Token:
    kind: str  # NUM STR OP LP RP WORD KW PART CALL PERIOD SEP(「、」や行の切れ目。場合分けの区切り)
    value: Any
    line: int
    form: str = ""  # CALL のとき "する" / "して" / "すること"
    quoted: bool = False  # 『』で囲んだ名前
    negated: bool = False  # 「…でない」
    qualified: bool = False  # 読み込んだファイルの型か形の名前に、そのファイルの前置きを付けたもの(「部品内の点」)

    def __repr__(self) -> str:
        return f"{self.kind}:{self.value}{('/' + self.form) if self.form else ''}"


def _is_hiragana(c: str) -> bool:
    return "ぁ" <= c <= "ゟ"


def _is_all_hiragana(word: str) -> bool:
    return bool(word) and all(_is_hiragana(c) for c in word)


def hiragana_function_error(stem: str, line: int) -> SuruError:
    return SuruError(
        f"「{stem}する」のように、ひらがなだけの関数名は使えません。"
        f"「する」の前に漢字かカタカナを入れてください(例:「{stem}」→「変換」「ヘンカン」)",
        line,
    )


def hiragana_name_error(name: str, line: int) -> SuruError:
    return SuruError(
        f"ひらがなだけの名前「{name}」は使えません(助詞と区別できないため)。"
        f"漢字かカタカナを使うか、{NAME_OPEN}{name}{NAME_CLOSE} のように{NAME_OPEN}{NAME_CLOSE}で囲んでください",
        line,
    )


def call_token(stem: str, form: str, line: int) -> Token:
    """呼び出しのトークン。述語(である/でない/であること)は「…である」という名前の関数にする"""
    if form in (DEARU, DENAI):
        return Token("CALL", stem + DEARU, line, SURU, negated=form == DENAI)
    if form == DEARUKOTO:
        return Token("CALL", stem + DEARU, line, KOTO)
    return Token("CALL", stem + SURU, line, POLITE_FORMS.get(form, form))


def is_predicate(name: str) -> bool:
    return name.endswith(DEARU)


def _classify_call(word: str, line: int) -> Token | None:
    # 「しまして」は「して」で終わるので、丁寧語の形を先に照合する
    for form in (DEARUKOTO, DEARU, DENAI, KOTO, SURU, "しましてから", SHITEKARA, "しまして", SHITE, "します", SHITA):
        if word.endswith(form) and len(word) > len(form):
            stem = word[: -len(form)]
            if _is_all_hiragana(stem):
                raise hiragana_function_error(stem, line)
            return call_token(stem, form, line)
    return None


def _classify(word: str, line: int, quoted: bool = False) -> list[Token]:
    if quoted:
        # 『』で囲んだ部分は分けない。後ろに「する」などが続けば関数名
        call = _classify_call(word, line)
        return [call] if call is not None else [Token("WORD", word, line, quoted=True)]
    norm = unicodedata.normalize("NFKC", word)
    if norm in OPERATORS or word in OPERATORS:
        return [Token("OP", OPERATORS.get(norm, OPERATORS.get(word)), line)]
    for conv in (int, float):
        try:
            return [Token("NUM", conv(norm), line)]
        except ValueError:
            pass
    if word in PARTICLES:
        return [Token("PART", word, line)]
    if word in KEYWORDS:
        return [Token("KW", word, line)]
    if word.endswith(DESU) and len(word) > len(DESU):
        # 「点です」「5です」: 後ろの「です」を分ける
        return _classify(word[: -len(DESU)], line) + [Token("KW", DESU, line)]
    if word in ("真", "偽"):
        return [Token("NUM", word == "真", line)]
    if word == KW_EMPTY:
        return [Token("NUM", (), line)]
    # 「を加算する」「で除算する」「を返すこと」のように助詞が関数名にくっついていたら分ける。
    # ただし助詞の直後がひらがなのとき(「へんかんする」など)は分けない。
    for p in PARTICLES:
        rest = word[len(p):]
        if word.startswith(p) and rest and not _is_hiragana(rest[0]):
            if rest in (KW_RETURN, KW_HENSU, KW_HENSU_POLITE):
                return [Token("PART", p, line), Token("KW", rest, line)]
            call = _classify_call(rest, line)
            if call is not None:
                return [Token("PART", p, line), call]
    call = _classify_call(word, line)
    if call is not None:
        return [call]
    return [Token("WORD", word, line)]


def tokenize_line(text: str, line: int) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(text)
    buf = ""
    start = 0
    quoted = False

    def flush() -> None:
        nonlocal buf, quoted
        if buf:
            tokens.extend(_classify(buf, Pos(line, start + 1), quoted))
            buf = ""
        quoted = False

    while i < n:
        c = text[i]
        here = Pos(line, i + 1)
        if not buf and c not in SPACES:
            start = i
        if c in SPACES:
            flush()
        elif c in COMMENT_STARTS and not buf:
            break
        elif c == "「":
            flush()
            j = find_string_close(text, i)
            if j < 0:
                raise SuruError("文字列の「に対応する」がありません", here)
            tokens.append(Token("STR", text[i + 1 : j], here))
            i = j
        elif c == NAME_OPEN:
            j = _find_name_close(text, i, here)
            buf += text[i + 1 : j]
            quoted = True
            i = j
        elif c in OPEN_PARENS:
            flush()
            tokens.append(Token("LP", "(", here))
        elif c in CLOSE_PARENS:
            flush()
            tokens.append(Token("RP", ")", here))
        elif c in RESERVED_MARKS:
            raise SuruError(f"{RESERVED_MARKS[c]}は将来の書き方のために予約されています(文字列の中では使えます)", here)
        elif c in (QUASI_OPEN, QUASI_CLOSE):
            raise SuruError("「【】」は「以下は【道】です」のような準クォートの頭にだけ書けます(文字列の中では使えます)", here)
        else:
            buf += c
        i += 1
    flush()
    return drop_desu(join_ika(tokens))


def join_module_names(tokens: list[Token], modules: set) -> list[Token]:
    """「数学内の円周率」「数学内の二乗する」: 読み込んだファイルの名前に「内の」が続けば、
    その後の名前と合わせて1つの名前にする(「数学」を読み込んでいなければ、ふつうの「数学内」)"""
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        name = tokens[i + 2] if i + 2 < len(tokens) else None
        if (t.kind == "WORD" and t.value.endswith(MODULE_MARK) and t.value[: -len(MODULE_MARK)] in modules
                and nxt is not None and nxt.kind == "KW" and nxt.value == KW_NO):
            if name is None or name.kind not in ("WORD", "CALL"):
                raise SuruError(f"「{t.value}の」の後には、読み込んだファイルの中の名前を書いてください", t.line)
            out.append(Token(name.kind, t.value + "の" + name.value, t.line, name.form, name.quoted, name.negated))
            i += 3
            continue
        if (t.kind == "WORD" and t.value.endswith(MODULE_SEP) and t.value[: -len(MODULE_SEP)] in modules
                and nxt is not None and nxt.kind in ("WORD", "CALL")):
            # 空白の書き方の「数学内の 円周率」
            out.append(Token(nxt.kind, t.value + nxt.value, t.line, nxt.form, nxt.quoted, nxt.negated))
            i += 2
            continue
        out.append(t)
        i += 1
    return out


def join_ika(tokens: list[Token]) -> list[Token]:
    """「以下の手順」「以下 の 手順」「以下の入出力手順」を1つの言葉にする。
    「以下は外部の入出力動作」「以下 は 外部 の 入出力動作」「以下は外部の関数」も(「以下の外部の…」も)"""
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        # 「以下は「二倍」の試験です」「以下 は 「二倍」 の 試験 です」(#193)
        if (t.kind == "WORD" and not t.quoted and t.value == "以下は" and i + 2 < len(tokens)
                and tokens[i + 1].kind == "STR" and tokens[i + 2].kind == "WORD" and not tokens[i + 2].quoted
                and tokens[i + 2].value in ("の試験", "の試験です")):
            out.append(Token("KW", test_head(tokens[i + 1].value), t.line))
            i += 3
            continue
        if (t.kind == "WORD" and not t.quoted and t.value == "以下" and i + 4 < len(tokens) and is_kw(tokens[i + 1], KW_WA)
                and tokens[i + 2].kind == "STR" and (is_kw(tokens[i + 3], KW_NO) or is_part(tokens[i + 3], KW_NO))
                and tokens[i + 4].kind == "WORD" and not tokens[i + 4].quoted and tokens[i + 4].value == "試験"):
            out.append(Token("KW", test_head(tokens[i + 2].value), t.line))
            i += 5
            continue
        if t.kind == "WORD" and not t.quoted and (t.value in IKA_WORDS or t.value in EXT_BLOCK_WORDS or t.value == KW_IKA_EXPORT):
            out.append(Token("KW", t.value, t.line))
            i += 1
            continue
        # 「以下 は 外部 に 出す 関数」「以下 は 外部に出す関数」(#208)
        if (t.kind == "WORD" and not t.quoted and t.value == "以下" and i + 2 < len(tokens) and is_kw(tokens[i + 1], KW_WA)
                and _plain_word(tokens[i + 2], "外部に出す関数")):
            out.append(Token("KW", KW_IKA_EXPORT, t.line))
            i += 3
            continue
        if (t.kind == "WORD" and not t.quoted and t.value == "以下" and i + 5 < len(tokens) and is_kw(tokens[i + 1], KW_WA)
                and _plain_word(tokens[i + 2], "外部") and tokens[i + 3].kind == "PART" and tokens[i + 3].value == "に"
                and _plain_word(tokens[i + 4], "出す") and _plain_word(tokens[i + 5], "関数")):
            out.append(Token("KW", KW_IKA_EXPORT, t.line))
            i += 6
            continue
        if (t.kind == "WORD" and not t.quoted and t.value == "以下" and i + 4 < len(tokens)
                and (is_kw(tokens[i + 1], KW_NO) or is_kw(tokens[i + 1], KW_WA))
                and tokens[i + 2].kind == "WORD" and not tokens[i + 2].quoted and tokens[i + 2].value == "外部"
                and is_kw(tokens[i + 3], KW_NO) and tokens[i + 4].kind == "WORD" and not tokens[i + 4].quoted
                and f"以下{tokens[i + 1].value}外部の{tokens[i + 4].value}" in EXT_BLOCK_WORDS):
            out.append(Token("KW", f"以下{tokens[i + 1].value}外部の{tokens[i + 4].value}", t.line))
            i += 5
            continue
        if (t.kind == "WORD" and not t.quoted and t.value == "以下" and i + 2 < len(tokens) and is_kw(tokens[i + 1], KW_NO)
                and tokens[i + 2].kind == "WORD" and not tokens[i + 2].quoted
                and "以下の" + tokens[i + 2].value in IKA_WORDS):
            out.append(Token("KW", "以下の" + tokens[i + 2].value, t.line))
            i += 3
            continue
        out.append(t)
        i += 1
    return out


def _plain_word(t: Token, s: str) -> bool:
    return t.kind == "WORD" and not t.quoted and t.value == s


def drop_desu(tokens: list[Token]) -> list[Token]:
    """文末の飾りの「です」を取り除く。「。」「、」「）」「そうでなければ」の前か、行の終わりにだけ書ける"""
    out = []
    for i, t in enumerate(tokens):
        if t.kind == "KW" and t.value == DESU:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is None or nxt.kind in ("PERIOD", "SEP", "RP") or is_kw(nxt, KW_ELSE):
                continue
            raise SuruError("「です」は文の終わり(「。」の前)にだけ書けます", t.line)
        out.append(t)
    return out


def find_string_close(text: str, i: int) -> int:
    """text[i] の「に対応する」の位置(なければ -1)。文字列の中の「」は入れ子として数える
    (「失敗: 「abc」は数にできません」は1つの文字列)"""
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "「":
            depth += 1
        elif c == "」":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _find_name_close(text: str, i: int, line: int) -> int:
    j = text.find(NAME_CLOSE, i + 1)
    if j < 0:
        raise SuruError(f"名前の{NAME_OPEN}に対応する{NAME_CLOSE}がありません", line)
    if j == i + 1:
        raise SuruError(f"{NAME_OPEN}{NAME_CLOSE}の中に名前がありません", line)
    return j


# --- 句読点の書き方(空白なしで詰めて書く) ------------------------------------
#
# 「。」か「、」を含む行は、文字の種類の境目で単語を切る:
#   ・漢字・カタカナ・英字の並び → 名前(数字は英字の後ならば名前の続き)
#   ・数字 → 数、記号 → 演算子
#   ・ひらがなの並び → 助詞・キーワード・「する/して/すること」に分ける
# 文は「。」まで続く(改行をまたいでもよい)。

OPERATOR_CHARS = {c for op in OPERATORS for c in unicodedata.normalize("NFKC", op)} | set(OPERATORS)
# 漢字とひらがなが混ざった決まった言葉(名前の切り出しより先に照合する)
# 「外部に出す関数」は句読点の書き方の「以下は外部に出す関数です。」(#208)
MIXED_WORDS = ("受け取って", "返すこと", KW_HENSU_POLITE, KW_HENSU, "長さ", "残り", KW_IMPORT_POLITE, KW_IMPORT, KW_IMPORT_TE, KW_USE_POLITE, KW_USE,
               "外部に出す関数")
# ひらがなを含む組み込み関数の名前(「する」の前の部分)。名前として切り出す
MIXED_NAMES = ("畳み込み",)
# ひらがなの並びを分けるときの辞書。長いものから順に照合する
HIRAGANA_WORDS = sorted(
    set(PARTICLES)
    | {KW_TO, KW_TOWA, KW_NO, KW_GA, KW_IF, KW_THEN, KW_ELSE, KW_PROVISO, KW_KA, KW_WA, KW_TOIU, KW_SOREKARA, KW_KATSU, KW_MATAHA}
    | {"それぞれ", KOTO, SURU, SHITEKARA, SHITE, SHITA, DEARUKOTO, DEARU, DENAI, DESU}
    | set(POLITE_FORMS),
    key=len,
    reverse=True,
)
CALL_FORMS = (KOTO, SURU, SHITEKARA, SHITE, SHITA, DEARUKOTO, DEARU, DENAI, *POLITE_FORMS)


def _nfkc(c: str) -> str:
    n = unicodedata.normalize("NFKC", c)
    return n if len(n) == 1 else c


def _char_class(c: str) -> str:
    if _is_hiragana(c):
        return "HIRA"
    n = _nfkc(c)
    if n.isascii() and n.isdigit():
        return "DIGIT"
    if c in OPERATOR_CHARS or n in OPERATOR_CHARS:
        return "OP"
    if n.isalpha() or n == "_":
        return "NAME"
    return "OTHER"


def _mixed_word_at(text: str, i: int) -> str | None:
    for w in MIXED_WORDS + MIXED_NAMES:
        if text.startswith(w, i):
            return w
    return None


def _split_operators(text: str, line: int) -> list[Token]:
    norm = unicodedata.normalize("NFKC", text)
    out = []
    i = 0
    while i < len(norm):
        for size in (2, 1):
            op = norm[i : i + size]
            if len(op) == size and op in OPERATORS:
                out.append(Token("OP", OPERATORS[op], line))
                i += size
                break
        else:
            raise SuruError(f"演算子「{norm[i:]}」が分かりません", line)
    return out


def _decompose(text: str) -> list[str] | None:
    """ひらがなの並びを辞書の言葉に分ける。長い言葉から試し、読めなければ短い言葉でやり直す"""
    if not text:
        return []
    for w in HIRAGANA_WORDS:
        if text.startswith(w):
            rest = _decompose(text[len(w):])
            if rest is not None:
                return [w] + rest
    return None


def _split_hiragana(text: str, line: int, after_name: bool, after_value: bool) -> list[str]:
    words = _decompose(text)
    if words is not None:
        return words
    # 読めないひらがなを、前の助詞と後ろの「とは」「する」などから切り出してエラーにする
    start = 0
    if after_value:
        lead = next((w for w in HIRAGANA_WORDS if text.startswith(w) and w not in CALL_FORMS), "")
        start = len(lead)
    # 名前の後に直接来にくい「か」「は」「という」から始まる切り方は避ける(「するめいか」を1語に)
    ends = [e for e in range(start + 1, len(text) + 1) if _decompose(text[e:]) is not None]
    end = next((e for e in ends if not text[e:].startswith((KW_KA, KW_WA, KW_TOIU))), ends[0])
    unknown, rest = text[start:end], text[end:]
    if after_name and start == 0:
        raise SuruError(
            f"名前にひらがな「{unknown}」が混ざっています。ひらがなを含む名前は "
            f"{NAME_OPEN}割った数に{NAME_CLOSE}する のように{NAME_OPEN}{NAME_CLOSE}で囲んでください",
            line,
        )
    if rest.startswith(CALL_FORMS):
        raise hiragana_function_error(unknown, line)
    raise hiragana_name_error(unknown, line)


def _hiragana_word_token(w: str, line: int) -> Token:
    if w in PARTICLES:
        return Token("PART", w, line)
    if w in KEYWORDS:
        return Token("KW", w, line)
    if w == "それぞれ":
        return Token("WORD", w, line)
    raise SuruError(f"「{w}」の前に関数名(漢字かカタカナ)が必要です", line)


def segment_run(pieces: list[tuple[str, bool, int]], line: int) -> list[Token]:
    """空白で区切られた1つの並び(『』で囲んだ部分を含む)を単語に分ける"""
    # 1. 文字の種類で切る
    parts: list[tuple[str, str]] = []  # (種類, 文字列)
    cols: list[int] = []  # 各部分が何文字目から始まるか
    for text, quoted, col in pieces:
        if quoted:
            parts.append(("QNAME", text))
            cols.append(col)
            continue
        i = 0
        while i < len(text):
            mixed = _mixed_word_at(text, i)
            cols.append(col + i)
            if mixed:
                parts.append(("NAME" if mixed in MIXED_NAMES else "MIXED", mixed))
                i += len(mixed)
                continue
            cls = _char_class(text[i])
            if cls == "OTHER":
                raise SuruError(f"「{text[i]}」は使えない文字です", Pos(line, col + i))
            j = i + 1
            if cls == "NAME":
                while j < len(text) and not _mixed_word_at(text, j):
                    k = _char_class(text[j])
                    # 数字は英字の後ならば名前の続き(x1 など)
                    if k == "NAME" or (k == "DIGIT" and _nfkc(text[j - 1]).isascii()):
                        j += 1
                    else:
                        break
            elif cls == "DIGIT":
                while j < len(text) and (
                    _char_class(text[j]) == "DIGIT"
                    or (_nfkc(text[j]) == "." and j + 1 < len(text) and _char_class(text[j + 1]) == "DIGIT")
                ):
                    j += 1
            else:
                while j < len(text) and _char_class(text[j]) == cls and not _mixed_word_at(text, j):
                    j += 1
            parts.append((cls, text[i:j]))
            i = j

    # 2. 単語にする。ひらがなの「する/して/すること」は直前の名前とつなげて関数名にする
    tokens: list[Token] = []
    for idx, (cls, text) in enumerate(parts):
        here = Pos(line, cols[idx])
        if cls in ("NAME", "QNAME"):
            if cls == "NAME" and text in ("真", "偽"):
                tokens.append(Token("NUM", text == "真", here))
            elif cls == "NAME" and text == KW_EMPTY:
                tokens.append(Token("NUM", (), here))
            elif cls == "NAME" and text in KANJI_KEYWORDS:
                tokens.append(Token("KW", text, here))
            else:
                tokens.append(Token("WORD", text, here, quoted=cls == "QNAME"))
        elif cls == "MIXED":
            kind = "KW" if text in KEYWORDS else "WORD"
            tokens.append(Token(kind, text, here))
        elif cls == "DIGIT":
            norm = unicodedata.normalize("NFKC", text)
            tokens.append(Token("NUM", float(norm) if "." in norm else int(norm), here))
        elif cls == "OP":
            tokens.extend(_split_operators(text, here))
        else:  # HIRA
            words = _split_hiragana(text, here, idx > 0 and parts[idx - 1][0] in ("NAME", "QNAME"), idx > 0)
            k = next((n for n, w in enumerate(words) if w in CALL_FORMS), None)
            if k is not None:
                # 「三倍にする」「絶対値にする」: 「する」の前のひらがなは関数名の一部
                stem = "".join(words[:k])
                prev = parts[idx - 1] if idx > 0 else None
                if prev is None or prev[0] not in ("NAME", "QNAME"):
                    if stem:
                        raise hiragana_function_error(stem, here)
                    raise SuruError(f"「{words[k]}」の前に関数名(漢字かカタカナ)が必要です", here)
                name_tok = tokens.pop()
                if _is_all_hiragana(name_tok.value + stem):
                    raise hiragana_function_error(name_tok.value + stem, here)
                tokens.append(call_token(name_tok.value + stem, words[k], name_tok.line))
                words = words[k + 1 :]
            for w in words:
                if w in CALL_FORMS:
                    raise SuruError(f"「{w}」の前に関数名(漢字かカタカナ)が必要です", here)
                tokens.append(_hiragana_word_token(w, here))
    return tokens


def tokenize_punct_line(text: str, line: int) -> list[Token]:
    """句読点の書き方の1行を字句解析する。「。」は PERIOD トークンになる"""
    tokens: list[Token] = []
    run: list[tuple[str, bool, int]] = []
    buf = ""
    start = 0
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal buf
        if buf:
            run.append((buf, False, start + 1))
            buf = ""
        if run:
            tokens.extend(segment_run(run, here))
            run.clear()

    while i < n:
        c = text[i]
        here = Pos(line, i + 1)
        if not buf and c not in SPACES and c != NAME_OPEN:
            start = i
        if c in SPACES:
            flush()
        elif c == COMMA:
            flush()
            tokens.append(Token("SEP", COMMA, here))
        elif c in COMMENT_STARTS and not buf and not run:
            break
        elif c == "「":
            flush()
            j = find_string_close(text, i)
            if j < 0:
                raise SuruError("文字列の「に対応する」がありません", here)
            tokens.append(Token("STR", text[i + 1 : j], here))
            i = j
        elif c == NAME_OPEN:
            j = _find_name_close(text, i, here)
            if buf:
                run.append((buf, False, start + 1))
                buf = ""
            run.append((text[i + 1 : j], True, i + 1))
            i = j
        elif c in OPEN_PARENS:
            flush()
            tokens.append(Token("LP", "(", here))
        elif c in CLOSE_PARENS:
            flush()
            tokens.append(Token("RP", ")", here))
        elif c == PERIOD:
            flush()
            tokens.append(Token("PERIOD", PERIOD, here))
        elif c in RESERVED_MARKS:
            raise SuruError(f"{RESERVED_MARKS[c]}は将来の書き方のために予約されています(文字列の中では使えます)", here)
        elif c in (QUASI_OPEN, QUASI_CLOSE):
            raise SuruError("「【】」は「以下は【道】です」のような準クォートの頭にだけ書けます(文字列の中では使えます)", here)
        else:
            buf += c
        i += 1
    flush()
    return join_ika(tokens)


def is_punct_line(text: str) -> bool:
    """文字列・名前・コメントの外に「。」か「、」があるか"""
    i, n = 0, len(text)
    at_token_start = True
    while i < n:
        c = text[i]
        if c in ("「", NAME_OPEN):
            j = find_string_close(text, i) if c == "「" else text.find(NAME_CLOSE, i + 1)
            if j < 0:
                return False
            i = j
        elif c in COMMENT_STARTS and at_token_start:
            return False
        elif c in (PERIOD, COMMA):
            return True
        at_token_start = c in SPACES or c in OPEN_PARENS or c in CLOSE_PARENS
        i += 1
    return False


@dataclass
class Line:
    indent: int
    tokens: list[Token]
    number: int
    closed: bool = False  # 「。」で終わった文(後ろの深い行を続きとみなさない)
    # 準クォート「以下は【道】です … 以上です」の中身(字下げを除いた文字列)。tokens の最後が QUASI の字句
    quasi: str | None = None
    quasi_end: int = 0  # 準クォートの「以上」の行の番号
    # 導出「会員 は 【JSON】 と 【表】 を 導出する」の【】の名前(tokens は DERIVE の字句1つで、値は型の名前)
    derive: list[str] | None = None


# --- 準クォート(#192): 「以下は【道】です」+ 中身 + 「以上です」。中身はライブラリの「道展開する」で する に展開する ---
QUASI_OPEN, QUASI_CLOSE = "【", "】"
_QUASI_TOP = re.compile(r"^以下[ \t　]*は[ \t　]*【([^【】 \t　]+)】[ \t　]*(?:です)?[ \t　]*。?[ \t　]*(?:#.*)?$")
_QUASI_EXPR = re.compile(r"^(.*?[^ \t　])[ \t　]*とは[ \t　]*以下[ \t　]*の[ \t　]*【([^【】 \t　]+)】[ \t　]*(?:です)?[ \t　]*。?[ \t　]*(?:#.*)?$")
_QUASI_END = re.compile(r"^以上[ \t　]*(?:です)?[ \t　]*。?[ \t　]*(?:#.*)?$")
QUASI_UNCLOSED = "を閉じる「以上です」がありません"  # 対話モードは、このエラーなら続きの行を待つ
QUASI_SUFFIX = "展開する"  # 【道】の展開の関数は「道展開する」
QUASI_MAX_DEPTH = 20  # 展開したコードの中の準クォートを展開する深さの上限
# 導出(#192): 「会員 は 【JSON】 と 【表】 を 導出する」。【JSON】の導出の関数は「JSON導出する」
DERIVE_SUFFIX = "導出する"
DERIVE_LIB = "導出"  # 導出の関数が受け取る型の記述(型記述・形記述・欄記述・型式)を定義した lib のファイル
_DERIVE = re.compile(r"^([^ \t　【】「」『』()（）#]+)[ \t　]*は[ \t　]*(【[^【】 \t　]+】(?:[ \t　]*と[ \t　]*【[^【】 \t　]+】)*)"
                     r"[ \t　]*を[ \t　]*導出(?:する|します)[ \t　]*。?[ \t　]*(?:#.*)?$")


def _indent_of(raw: str) -> tuple[int, int]:
    """行の字下げの幅と、字下げの文字数"""
    width = 0
    for i, c in enumerate(raw):
        if c not in INDENT_WIDTH:
            return width, i
        width += INDENT_WIDTH[c]
    return width, len(raw)


def _quasi_header(raw: str) -> tuple[str, str | None] | None:
    """準クォートの頭の行なら (名前, 式の形の「x とは」の部分 か None)"""
    text = raw.strip()
    if QUASI_OPEN not in text:
        return None
    m = _QUASI_TOP.match(text)
    if m:
        return m.group(1), None
    m = _QUASI_EXPR.match(text)
    # 「x とは」の前に注釈の字があれば、注釈の中に書いたもの(準クォートではない)
    if m and "「" not in m.group(1) and not any(c in m.group(1) for c in COMMENT_STARTS):
        return m.group(2), m.group(1)
    return None


def _quasi_block(raws: list[str], k: int, indent: int, name: str) -> tuple[str, int]:
    """頭の行 k の後ろの中身(字下げを除いて改行でつないだもの)と、「以上」の行の位置"""
    body: list[str] = []
    j = k + 1
    while j < len(raws):
        raw = raws[j]
        if raw.strip():
            width, _ = _indent_of(raw)
            if width <= indent:
                if _QUASI_END.match(raw.strip()) and width == indent:
                    break
                raise SuruError(f"「以下は【{name}】です」の中身は頭より深く字下げして、頭と同じ字下げの「以上です」で閉じてください",
                                Pos(j + 1))
        body.append(raw)
        j += 1
    else:
        raise SuruError(f"「以下は【{name}】です」{QUASI_UNCLOSED}", Pos(k + 1))
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    if not body:
        raise SuruError(f"「以下は【{name}】です」と「以上です」の間に中身がありません", Pos(k + 1))
    least = min(_indent_of(b)[0] for b in body if b.strip())
    out = []
    for b in body:
        width, n = 0, 0
        while n < len(b) and b[n] in INDENT_WIDTH and width + INDENT_WIDTH[b[n]] <= least:
            width += INDENT_WIDTH[b[n]]
            n += 1
        out.append(b[n:].rstrip())
    return "\n".join(out), j


def _depth_zero_periods(tokens: list[Token]) -> list[int]:
    depth = 0
    out = []
    for i, t in enumerate(tokens):
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        elif t.kind == "PERIOD" and depth <= 0:
            out.append(i)
    return out


def split_sentences(tokens: list[Token]) -> list[list[Token]]:
    """括弧の外の「。」で文に分ける(最後の「。」の後ろは捨てる)"""
    out, start = [], 0
    for i in _depth_zero_periods(tokens):
        if i > start:
            out.append(tokens[start:i])
        start = i + 1
    return out


def strip_seps(tokens: list[Token]) -> list[Token]:
    """前後の区切り(「、」)を取り除く"""
    i, j = 0, len(tokens)
    while i < j and tokens[i].kind == "SEP":
        i += 1
    while j > i and tokens[j - 1].kind == "SEP":
        j -= 1
    return tokens[i:j]


def nosep(tokens: list[Token]) -> list[Token]:
    return [t for t in tokens if t.kind != "SEP"]


def _opens_punct(raws: list[str], k: int) -> bool:
    """「手順（」のように開き括弧で終わる行は、次の行が句読点の書き方ならそれに合わせる"""
    text = raws[k].split("#")[0].rstrip()
    if not text or text[-1] not in OPEN_PARENS:
        return False
    nxt = next((r for r in raws[k + 1 :] if r.strip()), None)
    return nxt is not None and is_punct_line(nxt)


def split_lines(source: str, at: int | None = None) -> list[Line]:
    """行に分ける。at を渡すと、すべての行の番号をそれにする(準クォートを展開したコードは、頭の行を指す)"""
    lines = []
    raws = source.splitlines()
    k = 0
    if at is not None:
        lines = split_lines(source)
        for ln in lines:  # 展開したコードの位置は、準クォートの頭の行(何文字目かは示さない)
            ln.number = Pos(at)
            for t in ln.tokens:
                t.line = Pos(at)
            ln.quasi_end = 0
        return lines
    while k < len(raws):
        raw, number = raws[k], k + 1
        indent = 0
        for c in raw:
            if c in INDENT_WIDTH:
                indent += INDENT_WIDTH[c]
            else:
                break
        derive = _DERIVE.match(raw.strip())
        if derive is not None:
            names = re.findall(r"【([^【】]+)】", derive.group(2))
            lines.append(Line(indent, [Token("DERIVE", derive.group(1), number)], Pos(number), derive=names))
            k += 1
            continue
        head = _quasi_header(raw)
        if head is not None:
            name, before = head
            body, k = _quasi_block(raws, k, indent, name)
            toks = tokenize_line(before, number) if before is not None else []
            if before is not None:
                toks.append(Token("KW", KW_TOWA, number))  # 「x とは」の「とは」(before は「とは」の前)
            toks.append(Token("QUASI", name, number))
            lines.append(Line(indent, toks, Pos(number), quasi=body, quasi_end=k + 1))
            k += 1
            continue
        if not is_punct_line(raw) and not _opens_punct(raws, k):
            tokens = tokenize_line(raw, number)
            if tokens:
                lines.append(Line(indent, tokens, Pos(number)))
            k += 1
            continue
        # 句読点の書き方: 「。」で文が終わるまで次の行も読む
        tokens = tokenize_punct_line(raw, number)
        while True:
            ends = _depth_zero_periods(tokens)
            if not tokens or (ends and ends[-1] == len(tokens) - 1):
                break
            k += 1
            if k >= len(raws):
                first = tokens[(ends[-1] + 1) if ends else 0]
                raise SuruError("文の終わりに「。」が必要です(句読点の書き方では文を「。」で終えます)", first.line)
            tokens += tokenize_punct_line(raws[k], k + 1)
        for sentence in split_sentences(drop_desu(tokens)):
            sentence = strip_seps(sentence)
            if sentence:
                lines.append(Line(indent, sentence, sentence[0].line, closed=True))
        k += 1
    return lines


# ---------------------------------------------------------------------------
# 構文木
# ---------------------------------------------------------------------------


@dataclass
class Num:
    value: Any
    line: int = field(default=0, compare=False)


@dataclass
class Str:
    value: str
    line: int = field(default=0, compare=False)


@dataclass
class Var:
    name: str
    line: int
    quoted: bool = field(default=False, compare=False)


@dataclass
class ListLit:
    """「1 と 2 と 3」"""

    items: list


@dataclass
class Prop:
    """「リスト の 先頭」"""

    target: Any
    name: str
    line: int


@dataclass
class Each:
    """「リスト の それぞれ」。呼び出しの引数に置くと、その呼び出しを要素ごとに行う"""

    target: Any
    line: int


@dataclass
class BinOp:
    op: str
    left: Any
    right: Any
    line: int


@dataclass
class Neg:
    operand: Any


@dataclass
class Not:
    """「…でない」"""

    operand: Any
    line: int


@dataclass
class Call:
    name: str
    args: dict  # 助詞 → 式
    line: int


@dataclass
class Ref:
    """「三倍すること」「1 を 加算すること」: 関数の値(引数が足りなければ部分適用)"""

    name: str
    args: dict
    line: int


@dataclass
class Lambda:
    params: list  # [(助詞, パターン)]。パターンは名前か名前のリスト
    body: Any
    line: int


@dataclass
class If:
    cond: Any
    then: Any
    other: Any


@dataclass
class Define:
    name: str
    params: list  # [(助詞, パターン)]
    body: Any  # 式 または Block
    is_function: bool
    line: int
    test: str = ""  # 試験のまとまりか例なら、試験の名前(「二倍」「二倍するの例」)。名前で呼べず、通常の実行とビルドでは捨てる
    example: Any = None  # 例なら (実際の式, 期待の式)


@dataclass
class Block:
    statements: list  # Define と式。最後は式


@dataclass
class Proviso:
    """「ただし、合計とは、a+b。」: 直前の定義に付け足す局所定義
    (性質の定義の後なら「ただし、x を 文字列化する。」のような関数の宣言も書ける)"""

    define: Define | None
    line: int
    sig: tuple | None = None  # (関数名, 引数)


# --- 動作(副作用) ---


@dataclass
class Chain:
    """「入力してから、表示する」: call の動作を行い、その結果を cont の中の HOLE に入れる"""

    call: Any
    cont: Any
    line: int


@dataclass(eq=False)
class Run:
    """「入力した 結果」: 手順の中で動作を行った結果。
    unwrap なら「…した 中身」: 成功(有)なら中の値、失敗(無)なら一番内側の関数か手順がその失敗を返す"""

    call: Any
    line: int
    unwrap: bool = False
    fn: str = ""  # 「した 中身」を書いた関数の名前(失敗の経路に使う)


@dataclass
class Do:
    """「手順（文。文。…）」「…。それから、…。」: 文を順に行う"""

    statements: list
    line: int
    sequel: bool = False  # 「それから」で作った並び
    io: bool = False  # 「入出力手順」: 値は動作でなければならない


@dataclass
class Sequel:
    """「それから、…」の文(前の文に付け足す)"""

    expr: Any
    line: int


# --- 組・選択肢の型 ---


@dataclass
class TypeDef:
    """「点 とは 横 と 縦 の 組」「図形 とは 半径 の 円 か 幅 と 高 の 長方形」"""

    name: str
    ctors: list  # [(形の名前, [フィールド名])]
    line: int
    # 「番号 は 数 で 名前 は 文字列 の 組」と型を書いたとき: フィールド名 → 型の字句(書かなければ None)
    field_types: dict | None = None


@dataclass
class Construct:
    """「3 と 4 の 点」"""

    ctor: str
    items: list
    line: int


@dataclass
class NamedConstruct:
    """「横 は 3 で 縦 は 4 の 点」"""

    ctor: str
    fields: list  # [(フィールド名, 式)]
    line: int


@dataclass
class Update:
    """「横 は 10 の p」: p の 横 だけを変えた新しい組"""

    target: Any
    fields: list
    line: int


@dataclass
class Field:
    """「p の 横」"""

    target: Any
    name: str
    line: int


# --- パターンマッチ ---


@dataclass
class PBind:
    """新しい変数に結びつける"""

    name: str


@dataclass
class PSeq:
    """決まった長さのリストを要素ごとに調べる(場合ごとの関数定義の「a と b を」や、複数の引数)"""

    items: list


@dataclass
class PValue:
    """値と等しいか調べる(「空」「0」、すでにある変数など)"""

    expr: Any


@dataclass
class PCtor:
    """「半径 の 円」「x と y の 点」「赤」"""

    ctor: str
    items: list
    line: int


@dataclass
class PNamed:
    """「先頭 は x で 残り は 他」「横 は a の 点」"""

    fields: list  # [(フィールド名, パターン)]
    ctor: str | None
    line: int


@dataclass
class Match:
    """「もし 形 が 半径 の 円 ならば … 幅 と 高 の 長方形 ならば …」"""

    subject: Any
    cases: list  # [(パターン, 条件か None, 式)]
    default: Any
    line: int
    fname: str = ""  # 場合ごとの関数定義から作ったときの関数名


# --- 性質(型クラス) ---


@dataclass
class TraitDecl:
    """「比較可能 という 性質 とは」+ 関数の宣言と既定の実装"""

    name: str
    sigs: list  # [(関数名, 引数)]
    defaults: list  # [Define]
    line: int


@dataclass
class TraitImpl:
    """「点 は 比較可能」+ その型での関数の定義"""

    type_name: str
    trait: str
    defs: list  # [Define]
    line: int


@dataclass
class TypeSig:
    """型の宣言(型注釈)。「数 を 階乗する は 数」「税率 は 数」。実行には使わず、型の検査で使う。
    params は関数なら [(助詞, 型)]、値なら None。型は TypeName / TypeFun / TypeVarName"""

    name: str
    params: list | None
    result: Any
    line: int


@dataclass
class TypeName:
    """「数」「数 の リスト」「（数 と 文字列） の 点」"""

    name: str
    args: list


@dataclass
class TypeFun:
    """「（数 を 受け取って 数 を 返すこと）」"""

    params: list  # [(助詞, 型)]
    result: Any


@dataclass
class TypeVarName:
    """「甲」「乙」: どんな型でもよい(同じ宣言の中では同じ型)"""

    name: str


@dataclass
class Module:
    """読み込んだファイル。program は一番外の文(定義だけ)"""

    name: str  # 「数学・円周率」の「数学」
    path: str
    program: list
    private: frozenset = frozenset()  # 「… は 非公開とする」で外から見えない名前
    source: str = field(default="", repr=False, compare=False)  # ファイルの中身(コンパイルした実行ファイルのエラーの表示に使う)


@dataclass
class Import:
    """「「数学」 を 読み込む」: 数学.suru の定義を「数学・名前」で使えるようにする"""

    module: Module
    line: int
    open: bool = False  # 「読み込んで 使う」: 中の名前を前置きなしでも使う
    auto: bool = False  # 書かずに自動で読み込んだ基本(成否・有無)
    test: bool = False  # 試験のまとまりのために自動で読み込んだ「試験」(通常のビルドでは捨てる)


@dataclass
class ExternLib:
    """「外部の「m」 を 読み込む」: C の呼び出し規約で呼べるライブラリ(.so / .dylib)を使う"""

    name: str  # 書いたとおり(「m」「./libあれ.so」)
    path: str  # 短い名前(「m」)か、ファイルなら絶対パス
    line: int
    main_thread: bool = False  # 「外部の「m」 を 主スレッドで 読み込む」


@dataclass
class Extern:
    """「x を 余弦にする とは 外部の「cos」」の本体。型の宣言から引数と値の C の型を決める。
    params は定義の引数の順に C の型(FFI_TYPES の値)、result は値の C の型、action は値が動作か"""

    symbol: str
    line: int
    libs: list = field(default_factory=list)  # このファイルの ExternLib.path
    params: list = field(default_factory=list)
    result: str = ""
    action: bool = False
    main_thread: bool = False  # 主スレッドで呼ぶ(同じファイルに「… を 主スレッドで 読み込む」がある)
    pointer: str = ""  # 「外部の（f）」なら、関数の番地を持つ引数の名前(C には渡さない)
    # 「外部の「f」（a と 0 と b）」なら、C に渡す引数の並び: ("引数", 定義の引数の番号) か ("定数", 整数)。
    # 読んだときは ("名前", 名前) で、_attach_externs が番号にする。空なら定義の引数の順
    cargs: list = field(default_factory=list)


@dataclass
class Export:
    """「以下は外部に出す関数です」の中の1行「二倍する は 「nibai」」: 関数を他の言語から呼べる C の関数として出す(#208)。
    params は定義の引数の順に C の型(FFI_TYPES の値)、result は値の C の型(void も)、action は値が動作か(_attach_exports が入れる)"""

    name: str
    symbol: str
    line: int
    params: list = field(default_factory=list)
    result: str = ""
    action: bool = False


@dataclass
class Visibility:
    """「確保する と 解放する は 非公開とする」: 読み込んだ側から見えるか"""

    names: list
    public: bool
    line: int


VIS_PUBLIC = "公開とする"
VIS_PRIVATE = "非公開とする"

TOP_LEVEL_ONLY = (TypeDef, TraitDecl, TraitImpl, TypeSig, Import, ExternLib, Visibility, Export)
TYPE_VAR_NAMES = "甲乙丙丁戊己庚辛壬癸"
# 小数・整数・単精度は数の別名(外部の関数の宣言で C の double・int・float を表す)。番地は C のポインタ
# 無は外部の関数の値がないこと(C の void。する では 0)。バイト列は変更できないバイトの並び
BUILTIN_TYPES = ("数", "文字列", "真偽", "リスト", "関数", "動作", "小数", "整数", "番地", "バイト列", "無", "入出力動作", "単精度", "C形")
# 外部の関数に渡せる型 → C の型の名前(バイト列は引数だけ、無は値だけ)
FFI_TYPES = {"数": "i64", "小数": "f64", "整数": "i32", "真偽": "bool", "文字列": "str", "番地": "ptr",
             "バイト列": "bytes", "無": "void", "単精度": "f32"}


class ParseContext:
    """構文解析で使う、定義済みの型と形の名前(「3 と 4 の 点」を読むために先に集める)"""

    def __init__(self, ctors: dict | None = None, types: dict | None = None, base_dir: str = ".",
                 modules: dict | None = None, path: str = ""):
        self.ctors: dict[str, tuple[str, list]] = dict(ctors or {})  # 形 → (型, フィールド名)
        self.types: dict[str, list] = dict(types or {})  # 型 → [形]
        # フィールドの型を書いた型 → {フィールド名: 型の書き方(TypeName など)}(「番号 は 数 で … の 組」)
        self.field_types: dict[str, dict] = {}
        self.base_dir = base_dir  # 「「数学」 を 読み込む」で探すフォルダ
        self.modules: dict[str, Any] = dict(modules or {})  # 読み込んだファイル(絶対パス → Module。読み込み中は None)
        self.packages: dict[str, str] | None = None  # プロジェクトの依存(名前 → フォルダ)。None なら初めて読み込むときに探す
        self.path = os.path.abspath(path) if path else ""  # 解析しているファイル(自分と同じ名前のファイルを読み込むときに飛ばす)
        self.in_prelude = False  # 基本.suru そのものを読んでいる(基本を自動で読み込まない)
        # 読み込んだファイル(lib/ のものを除く)を解析しているときは「部品内の」。そのファイルの型と形の名前に付ける
        self.qualify = ""
        # 対話モード: 前の入力で読み込んだファイル(準クォートと導出の関数を探す)と、前の入力の型の定義の行(新しい順)
        self.session_modules: list = []
        self.session_nodes: list = []

    def copy(self) -> "ParseContext":
        c = ParseContext(self.ctors, self.types, self.base_dir, self.modules)
        c.packages = self.packages
        c.path = self.path
        c.field_types = dict(self.field_types)
        c.session_modules = self.session_modules
        c.session_nodes = self.session_nodes
        return c

    def resolve_field_types(self, tds: list) -> None:
        """フィールドの型を書いた型の、型の字句を読む(型の定義をすべて集めてから。後ろで定義する型も書ける)"""
        for td in tds:
            if td.field_types is None:
                continue
            self.field_types[td.name] = {f: parse_type_all(toks, td.line) for f, toks in td.field_types.items()}

    def add(self, td: TypeDef) -> None:
        if td.name in self.types or td.name in BUILTIN_TYPES:
            raise SuruError(f"型「{td.name}」は既に定義されています", td.line)
        names = [c for c, _ in td.ctors]
        for c, fields in td.ctors:
            if names.count(c) > 1:
                raise SuruError(f"形「{c}」が2回書かれています", td.line)
            if c in self.ctors:
                raise SuruError(f"形「{c}」は既に型「{self.ctors[c][0]}」で使われています", td.line)
            for f in fields:
                if f in names or f == td.name or f in self.ctors or f in self.types:
                    raise SuruError(f"フィールド名「{f}」は型や形の名前と同じにできません", td.line)
        self.types[td.name] = names
        for c, fields in td.ctors:
            self.ctors[c] = (td.name, list(fields))


_CTX = ParseContext()  # 解析中のプログラムの型(parse_program が設定する)


def is_ctor(tok: "Token | None") -> bool:
    return tok is not None and tok.kind == "WORD" and tok.value in _CTX.ctors


def is_nullary(name: str) -> bool:
    return name in _CTX.ctors and not _CTX.ctors[name][1]


# ---------------------------------------------------------------------------
# レイアウト(オフサイドルール)
# ---------------------------------------------------------------------------


@dataclass
class Node:
    line: Line
    children: list["Node"] = field(default_factory=list)


def build_layout(lines: list[Line]) -> list[Node]:
    """インデントに従って行を木構造にまとめる"""
    lines = expand_externs(lines)
    pos = 0

    def block(min_indent: int) -> list[Node]:
        nonlocal pos
        nodes: list[Node] = []
        if pos >= len(lines):
            return nodes
        indent = lines[pos].indent
        while pos < len(lines):
            ln = lines[pos]
            if ln.indent < indent:
                if ln.indent >= min_indent:
                    raise SuruError("インデントがそろっていません", ln.number)
                break
            if ln.indent > indent:
                raise SuruError("予期しないインデントです", ln.number)
            pos += 1
            node = Node(ln)
            if (not ln.closed or opens_ika(ln)) and pos < len(lines) and lines[pos].indent > indent:
                node.children = block(indent + 1)
            # 行頭が ならば/そうでなければ の行は前の文の続き。
            # 「… ならば 以下の手順です」の後は、深い行の「以上」で閉じていれば続ける(#190)
            first = ln.tokens[0]
            if (nodes and not ln.closed and not nodes[-1].line.closed and first.kind == "KW" and first.value in CONTINUATION_KEYWORDS
                    and (not opens_ika(nodes[-1].line) or ika_closed_deep(nodes[-1]))):
                prev = nodes[-1]
                prev.children.append(node)
            else:
                nodes.append(node)
        return nodes

    top = block(0)
    if lines and lines[0].indent != 0:
        raise SuruError("最初の行はインデントできません", lines[0].number)
    return close_ijou(top)


def opens_ika(ln: Line) -> bool:
    """「… とは 以下の手順です」で終わる行か(「以下は「二倍」の試験です」だけの行も)"""
    toks = nosep(ln.tokens)
    return bool(toks) and toks[-1].kind == "KW" and (toks[-1].value in IKA_WORDS or is_test_head(toks[-1]) and len(toks) == 1)


def opens_ext_block(ln: Line) -> bool:
    """「以下は外部の入出力動作です」「以下は外部の関数です」(「以下の外部の…」も)だけの行か"""
    toks = nosep(ln.tokens)
    return len(toks) == 1 and toks[0].kind == "KW" and toks[0].value in EXT_BLOCK_WORDS


def ika_closed_deep(n: Node) -> bool:
    """「以下の手順です」の行で、深い行の「以上」で既に閉じているか(その後の続きの行は式の続き)"""
    return any(is_ijou(c.line) for c in n.children)


def is_ijou(ln: Line) -> bool:
    """「以上」だけの行(文)か"""
    toks = nosep(ln.tokens)
    return len(toks) == 1 and is_kw(toks[0], KW_IJOU)


def opens_case(ln: Line) -> bool:
    """「もし 値 が」で終わる行か(次の深い行が場合)"""
    toks = nosep(ln.tokens)
    return len(toks) > 1 and is_kw(toks[-1], KW_GA) and any(is_kw(t, KW_IF) for t in toks)


def _ijou_then_more(n: Node) -> None:
    """「以上」の後に同じ深さで文が続くなら、そう知らせる(場合分けを閉じる「以上」は場合と同じ深い行にあるので、ここには来ない)"""
    kids = n.children
    for k in range(len(kids) - 1):
        if is_ijou(kids[k].line):
            raise SuruError(f"「{KW_IJOU}」の後に文があります(手順の文は「{KW_IJOU}」の前に書きます)",
                            kids[k + 1].line.number)


def _ika_missing(n: Node) -> SuruError:
    word = nosep(n.line.tokens)[-1].value
    return SuruError(f"「{word}です」を閉じる「{KW_IJOU}」がありません(手順の最後の文の後に「{KW_IJOU}」だけの行を書きます)",
                     n.line.number)


def close_ijou(nodes: list[Node]) -> list[Node]:
    """「以下の手順です」の行に、「以上」までの文を深い行としてまとめる(「以上」の行は取り除く)。
    文は深い行か、同じ字下げで続く行(句読点の書き方では続く文)。「以上」は最後の深い行か、頭と同じ字下げの行"""
    out: list[Node] = []
    i = 0
    while i < len(nodes):
        n, i = _close_one(nodes, i)
        out.append(n)
    return out


def _close_one(nodes: list[Node], i: int) -> tuple[Node, int]:
    n = nodes[i]
    i += 1
    n.children = close_ijou(n.children)
    if not opens_ika(n.line):
        return n, i
    j = next((k for k, c in enumerate(n.children) if is_ijou(c.line)), None)
    if j is not None and j < len(n.children) - 1 and not is_test_head(nosep(n.line.tokens)[-1]) and all(
            nosep(c.line.tokens)[0].kind == "KW" and nosep(c.line.tokens)[0].value in CONTINUATION_KEYWORDS
            for c in n.children[j + 1:]):
        # 「もし … ならば 以下の手順です」+ 深い行 + 「以上」の後に「そうでなければ …」(#190):
        # 手順の文を DO の字句にして行に入れ、続きの行を深い行として残す
        body, rest = n.children[:j], n.children[j + 1:]
        if not body:
            word = nosep(n.line.tokens)[-1].value
            raise SuruError(f"「{word}です」と「{KW_IJOU}」の間に文がありません", n.line.number)
        toks = n.line.tokens
        k = max(x for x, t in enumerate(toks) if t.kind == "KW" and t.value in IKA_WORDS)
        do = Token("DO", body, toks[k].line, toks[k].value)
        n.line = Line(n.line.indent, list(toks[:k]) + [do] + list(toks[k + 1:]), n.line.number, n.line.closed)
        n.children = rest
        return n, i
    if n.children:
        if is_ijou(n.children[-1].line):
            n.children.pop()
        elif i < len(nodes) and is_ijou(nodes[i].line):
            i += 1
        else:
            _ijou_then_more(n)
            raise _ika_missing(n)
    else:
        body: list[Node] = []
        while i < len(nodes) and not is_ijou(nodes[i].line):
            m, i = _close_one(nodes, i)
            body.append(m)
        if i >= len(nodes):
            raise _ika_missing(n)
        i += 1
        n.children = body
    if not n.children:
        word = nosep(n.line.tokens)[-1].value
        raise SuruError(f"「{word}です」と「{KW_IJOU}」の間に文がありません", n.line.number)
    return n, i


# ---------------------------------------------------------------------------
# 外部の関数を1行で書く(#173)・外部の関数のまとまり(#174)
# 字下げの木にする前に、型の宣言の行と定義の行の2行(今までの書き方)に直す
# ---------------------------------------------------------------------------

EXT_ONE_LINE_EXAMPLE = "「n を 確保する とは 外部の「SDL_malloc」 で 数 を 受け取って 番地 を 返す 入出力動作です」"
EXT_BLOCK_LINE_HELP = ("1行に1つ、「数 を 確保する は 「SDL_malloc」 で 番地 を 返します」か、"
                       "名前を付けて「r を 読取する とは 「SDL_RenderReadPixels」（r と 0） で 番地 を 受け取って 番地 を 返します」の形で書きます")


def _top_level_indexes(tokens: list[Token], pred) -> list[int]:
    """括弧の外で pred に合う字句の位置"""
    depth = 0
    out = []
    for i, t in enumerate(tokens):
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        elif depth == 0 and pred(t):
            out.append(i)
    return out


def _top_particles(tokens: list[Token]) -> list[Token]:
    return [tokens[i] for i in _top_level_indexes(tokens, lambda t: t.kind == "PART")]


def _close_paren(tokens: list[Token], k: int) -> int:
    """tokens[k] の「（」に対応する「）」の次の位置(なければ -1)"""
    depth = 0
    for i in range(k, len(tokens)):
        if tokens[i].kind == "LP":
            depth += 1
        elif tokens[i].kind == "RP":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _ext_name(head: list[Token]) -> Token | None:
    calls = [head[i] for i in _top_level_indexes(head, lambda t: t.kind == "CALL")]
    return calls[-1] if calls else None


def _io_result(res: list[Token], word: str) -> list[Token]:
    """まとまり「以下は外部の入出力動作です」の値の型「番地 を 返します」を「番地 を 返す 入出力動作」にする"""
    line = res[0].line
    if len(res) >= 2 and res[-2].kind == "PART" and res[-2].value == "を" and is_kw(res[-1], KW_HENSU) or (
            len(res) >= 2 and res[-2].kind == "PART" and res[-2].value == "を" and is_kw(res[-1], KW_HENSU_POLITE)):
        res = res[:-2]
    if not res:
        raise SuruError("値の型がありません(「番地 を 返します」のように書きます)", line)
    if res[-1].kind == "WORD" and not res[-1].quoted and res[-1].value in ("動作", "入出力動作"):
        raise SuruError(f"「{word}です」の中では、値の型に「{res[-1].value}」を書きません(「番地 を 返します」のように書きます)",
                        res[-1].line)
    return res + [Token("PART", "を", line), Token("KW", KW_HENSU, line), Token("WORD", "入出力動作", line)]


def _typed_extern(ln: Line, head: list[Token], towa: Token, ext: list[Token], typ: list[Token],
                  word: str | None) -> list[Line]:
    """「頭 とは 外部の「f」 で 型」を、型の宣言の行と定義の行にする。word はまとまりの言葉(まとまりの外なら None)"""
    name = _ext_name(head)
    if name is None:
        raise SuruError(f"型を後ろに書けるのは関数の定義だけです({EXT_ONE_LINE_EXAMPLE})", head[0].line if head else towa.line)
    if not typ:
        raise SuruError(f"「で」の後に型を書きます({EXT_ONE_LINE_EXAMPLE})", towa.line)
    lam = _top_level_indexes(typ, lambda t: is_kw(t, KW_LAMBDA))
    args, res = (typ[:lam[0]], typ[lam[0] + 1:]) if lam else ([], typ)
    want = [t.value for t in _top_particles(head)]
    got = [t.value for t in _top_particles(args)]
    if want != got or (args and args[-1].kind != "PART"):
        order = "・".join(want) if want else "なし"
        raise SuruError(f"「{name.value}」の型の引数は、定義と同じ助詞を同じ順に書き、最後に「受け取って」を書きます"
                        f"(定義の助詞: {order})", (typ[0] if typ else towa).line)
    if not res:
        raise SuruError(f"「受け取って」の後に値の型を書きます({EXT_ONE_LINE_EXAMPLE})", typ[-1].line)
    if word in EXT_IO_WORDS:
        res = _io_result(res, word)
    sig = args + [name, Token("KW", KW_WA, name.line)] + res
    return [Line(0, sig, ln.number, ln.closed), Line(0, head + [towa] + ext, ln.number, ln.closed)]


def _ext_split(after: list[Token]) -> tuple[list[Token], list[Token]] | None:
    """「「f」（…） で 型」を「「f」（…）」と型に分ける(合わなければ None)。番地で呼ぶ「（f）」も(#189)"""
    k = 1
    if len(after) >= 4 and after[0].kind == "LP" and after[1].kind == "WORD" and after[2].kind == "RP":
        k = 3
    elif len(after) < 2 or after[0].kind != "STR":
        return None
    elif after[k].kind == "LP":
        k = _close_paren(after, k)
        if k < 0:
            return None
    if k >= len(after) or not (after[k].kind == "PART" and after[k].value == "で"):
        return None
    return after[:k], after[k + 1:]


def _extern_one_line(ln: Line) -> list[Line] | None:
    """「n を 確保する とは 外部の「SDL_malloc」 で 数 を 受け取って 番地 を 返す 入出力動作です」(#173)"""
    toks = nosep(ln.tokens)
    towa = find_top_level(toks, KW_TOWA)
    if towa is None:
        return None
    after = toks[towa + 1:]
    if not (after and after[0].kind == "WORD" and after[0].value == KW_EXTERN and not after[0].quoted):
        return None
    parts = _ext_split(after[1:])
    if parts is None:
        return None
    return _typed_extern(ln, toks[:towa], toks[towa], [after[0]] + parts[0], parts[1], None)


def _extern_block_line(ln: Line, word: str) -> list[Line]:
    """まとまりの中の1行を、型の宣言の行と定義の行にする"""
    toks = nosep(ln.tokens)
    towa = find_top_level(toks, KW_TOWA)
    if towa is not None:
        # 名前を付けた定義の形: 「r を 読取する とは 「f」（r と 0） で 番地 を 受け取って 番地 を 返します」
        after = toks[towa + 1:]
        ext = Token("WORD", KW_EXTERN, toks[towa].line)
        if after and after[0].kind == "WORD" and after[0].value == KW_EXTERN and not after[0].quoted:
            ext, after = after[0], after[1:]
        parts = _ext_split(after)
        if parts is None:
            raise SuruError(f"「{word}です」の中には、{EXT_BLOCK_LINE_HELP}", ln.number)
        return _typed_extern(ln, toks[:towa], toks[towa], [ext] + parts[0], parts[1], word)
    wa = _top_level_indexes(toks, lambda t: is_kw(t, KW_WA))
    if not wa:
        raise SuruError(f"「{word}です」の中には、{EXT_BLOCK_LINE_HELP}", ln.number)
    before, after = toks[:wa[0]], toks[wa[0] + 1:]
    name = _ext_name(before)
    if name is None or len(after) < 3 or after[0].kind != "STR" or not (after[1].kind == "PART" and after[1].value == "で"):
        if name is not None and len(after) >= 3 and after[0].kind == "LP" and after[1].kind == "WORD" and after[2].kind == "RP":
            raise SuruError(f"番地で呼ぶ「（{after[1].value}）」は、名前を付けた定義の形で書きます"
                            f"(「p を f で 呼出する とは （f） で 番地 を 番地 で 受け取って 無 を 返します」)", after[0].line)
        if name is not None and len(after) >= 2 and after[0].kind == "STR" and after[1].kind == "LP":
            raise SuruError("C に渡す引数を並べて書くときは、名前を付けた定義の形で書きます"
                            "(「r を 読取する とは 「SDL_RenderReadPixels」（r と 0） で 番地 を 受け取って 番地 を 返します」)",
                            after[1].line)
        raise SuruError(f"「{word}です」の中には、{EXT_BLOCK_LINE_HELP}", ln.number)
    res = after[2:]
    if word in EXT_IO_WORDS:
        res = _io_result(res, word)
    # 定義の引数の名前は使わないので、「引数1」「引数2」… にする
    head: list[Token] = []
    for k, p in enumerate(_top_particles(before[:before.index(name)])):
        head += [Token("WORD", f"引数{k + 1}", p.line), p]
    head.append(name)
    sig = before + [toks[wa[0]]] + res
    define = head + [Token("KW", KW_TOWA, name.line), Token("WORD", KW_EXTERN, after[0].line), after[0]]
    return [Line(0, sig, ln.number, ln.closed), Line(0, define, ln.number, ln.closed)]


# 「以下は外部に出す関数です」の中の1行を直した文の頭の印(書けない字を含むので、書いたものとはぶつからない)
KW_EXPORT_MARK = "\x00外部に出す"
EXPORT_LINE_HELP = "1行に1つ、「二倍する は 「nibai」」のように、このファイルの関数の名前と C の名前を書きます"


def opens_export_block(ln: Line) -> bool:
    """「以下は外部に出す関数です」だけの行か(#208)"""
    toks = nosep(ln.tokens)
    return len(toks) == 1 and is_kw(toks[0], KW_IKA_EXPORT)


def _export_block(lines: list[Line], i: int) -> tuple[list[Line], int]:
    """「以下は外部に出す関数です」から「以上です」までを、1行ずつ「印 名前 「C の名前」」の文にする(#208)。
    i は頭の行の位置。直した行と、「以上」の次の位置を返す(Go 版の exportBlock と同じ)"""
    ln = lines[i]
    word = KW_IKA_EXPORT
    if ln.indent:
        raise SuruError(f"「{word}です」は一番外(字下げなし)に書きます", ln.number)
    i += 1
    out: list[Line] = []
    names: dict[str, int] = {}
    syms: dict[str, int] = {}
    deep = i < len(lines) and lines[i].indent > 0
    while i < len(lines) and not is_ijou(lines[i]):
        b = lines[i]
        if deep and b.indent == 0:
            break
        ts = nosep(b.tokens)
        if ts and ts[-1].kind == "PERIOD":
            ts = ts[:-1]
        if len(ts) != 3 or not is_kw(ts[1], KW_WA) or ts[2].kind != "STR":
            raise SuruError(f"「{word}です」の中には、{EXPORT_LINE_HELP}", b.number)
        if ts[0].kind != "CALL":
            raise SuruError(f"「{ts[0].value}」は関数ではないので、外部に出せません(出せるのは「…する」の関数です)", ts[0].line)
        name, sym = ts[0].value, ts[2].value
        if name in names:
            raise SuruError(f"「{name}」がまとまりの中で2回書かれています({names[name]}行目と{b.number}行目)", b.number)
        if sym in syms:
            raise SuruError(f"C の名前「{sym}」がまとまりの中で2回書かれています({syms[sym]}行目と{b.number}行目)", b.number)
        names[name] = b.number
        syms[sym] = b.number
        out.append(Line(0, [Token("KW", KW_EXPORT_MARK, ts[0].line), ts[0], ts[2]], b.number, b.closed))
        i += 1
    if i >= len(lines) or not is_ijou(lines[i]):
        raise SuruError(f"「{word}です」を閉じる「{KW_IJOU}」がありません(最後の関数の行の後に「{KW_IJOU}」だけの行を書きます)",
                        ln.number)
    if not out:
        raise SuruError(f"「{word}です」と「{KW_IJOU}」の間に関数がありません", ln.number)
    return out, i + 1


def expand_externs(lines: list[Line]) -> list[Line]:
    """外部の関数の1行の書き方とまとまりを、型の宣言と定義の2行ずつにする(一番外だけ)。
    他の言語に出す関数のまとまり(#208)は、1行ずつの文にする"""
    out: list[Line] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        toks = nosep(ln.tokens)
        if opens_export_block(ln):
            got, i = _export_block(lines, i)
            out.extend(got)
            continue
        if opens_ext_block(ln):
            word = toks[0].value
            if ln.indent:
                raise SuruError(f"「{word}です」は一番外(字下げなし)に書きます", ln.number)
            i += 1
            names: dict[str, int] = {}
            count = 0
            deep = i < len(lines) and lines[i].indent > 0
            while i < len(lines) and not is_ijou(lines[i]):
                b = lines[i]
                if deep and b.indent == 0:
                    break  # 深い行のまとまりの後に、頭と同じ字下げの行: 「以上」を書き忘れた
                pair = _extern_block_line(b, word)
                d = nosep(pair[1].tokens)
                name = d[find_top_level(d, KW_TOWA) - 1].value
                if name in names:
                    raise SuruError(f"「{name}」がまとまりの中で2回書かれています({names[name]}行目と{b.number}行目)", b.number)
                names[name] = b.number
                out.extend(pair)
                count += 1
                i += 1
            if i >= len(lines) or not is_ijou(lines[i]):
                raise SuruError(f"「{word}です」を閉じる「{KW_IJOU}」がありません(最後の関数の行の後に「{KW_IJOU}」だけの行を書きます)",
                                ln.number)
            if count == 0:
                raise SuruError(f"「{word}です」と「{KW_IJOU}」の間に関数がありません", ln.number)
            i += 1
            continue
        if ln.indent == 0:
            pair = _extern_one_line(ln)
            if pair is not None:
                out.extend(pair)
                i += 1
                continue
        out.append(ln)
        i += 1
    return out


def flatten(node: Node) -> list[Token]:
    """行とその深い行を1つのトークン列にする。行の切れ目には区切り(SEP)を入れる(場合分けで使う)"""
    return _with_children(node.line.tokens, node.children)


# ---------------------------------------------------------------------------
# 構文解析
# ---------------------------------------------------------------------------


def is_kw(tok: Token | None, value: str) -> bool:
    return tok is not None and tok.kind == "KW" and tok.value == value


def is_part(tok: Token | None, value: str | None = None) -> bool:
    return tok is not None and tok.kind == "PART" and (value is None or tok.value == value)


def merge_piped(args: dict, piped: Any, key: str = WO) -> dict:
    """「して」の結果を「を」(述語なら「が」)に入れる。既にあれば、前に並べてリストにする"""
    args = dict(args)
    if key in args:
        given = args[key]
        items = given.items if isinstance(given, ListLit) else [given]
        args[key] = ListLit([piped] + items)
    else:
        args = {key: piped, **args}
    return args


def to_pattern(node: Any, line: int) -> str | list[str]:
    """引数の名前: 「a」または「a と b」(リストを分解して受け取る)"""
    for v in node.items if isinstance(node, ListLit) else [node]:
        if isinstance(v, Var) and not v.quoted and _is_all_hiragana(v.name) and v.name != "それぞれ":
            raise hiragana_name_error(v.name, v.line)
    if isinstance(node, Var):
        return node.name
    if isinstance(node, ListLit) and all(isinstance(i, Var) for i in node.items):
        return [i.name for i in node.items]
    raise SuruError("引数の名前には名前か「名前 と 名前」しか書けません", line)


def check_params(params: list, line: int) -> None:
    seen: set[str] = set()
    for _, pat in params:
        for name in [pat] if isinstance(pat, str) else pat:
            if name in seen:
                raise SuruError(f"引数名「{name}」が重複しています", line)
            seen.add(name)


def pattern_binders(pat: Any) -> list[str]:
    if isinstance(pat, PBind):
        return [pat.name]
    if isinstance(pat, (PCtor, PSeq)):
        return [n for p in pat.items for n in pattern_binders(p)]
    if isinstance(pat, PNamed):
        return [n for _, p in pat.fields for n in pattern_binders(p)]
    return []


def check_pattern(pat: Any, line: int) -> None:
    """パターンの形の数・フィールド名・変数の重複を調べる"""
    names = pattern_binders(pat)
    for n in names:
        if names.count(n) > 1:
            raise SuruError(f"パターンの中で名前「{n}」が2回使われています", line)

    def walk(p: Any) -> None:
        if isinstance(p, PCtor):
            fields = _CTX.ctors[p.ctor][1]
            if len(p.items) != len(fields):
                raise SuruError(
                    f"「{p.ctor}」のパターンには{len(fields)}個の名前が必要です(書かれているのは{len(p.items)}個)", line
                )
            for q in p.items:
                walk(q)
        elif isinstance(p, PSeq):
            for q in p.items:
                walk(q)
        elif isinstance(p, PNamed):
            for f, q in p.fields:
                if p.ctor is not None and f not in _CTX.ctors[p.ctor][1]:
                    raise SuruError(f"「{p.ctor}」には「{f}」というフィールドがありません", line)
                walk(q)

    walk(pat)


def check_exhaustive(cases: list, line: int, fname: str = "") -> None:
    """選択肢の型の場合分けで、書かれていない形があればエラーにする"""
    names = set()
    for pat, guard, _ in cases:
        if guard is not None:
            continue  # 条件つきの場合は、形がそろっているかの数に入れない
        if isinstance(pat, PCtor):
            names.add(pat.ctor)
        elif isinstance(pat, PNamed) and pat.ctor:
            names.add(pat.ctor)
        elif isinstance(pat, PValue) and isinstance(pat.expr, Var) and is_nullary(pat.expr.name):
            names.add(pat.expr.name)
        else:
            return
    types = {_CTX.ctors[n][0] for n in names}
    if len(types) != 1:
        return
    missing = [c for c in _CTX.types[types.pop()] if c not in names]
    if missing and fname:
        raise SuruError(f"「{fname}」に「{'」「'.join(missing)}」の場合の定義がありません", line)
    if missing:
        raise SuruError(
            f"「{'」「'.join(missing)}」の場合がありません(すべての形を書くか、最後に「そうでなければ …」を書いてください)",
            line,
        )


class ExprParser:
    """1つの式(トークン列)を解析する"""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0
        # 場合分けの本体を読んでいる間は、区切り(「、」や行の切れ目)で値を終える
        self.stop_sep = False
        self.in_named = False  # 「横 は 値 …」の値を読んでいる
        self.no_logic = False  # パターンを読んでいる間は「かつ」を条件の始まりとして残す
        self.case_indents: list[list[int]] = []  # 読んでいる場合分けの、場合の行の字下げ(外側から。分からなければ -1)

    def _skip(self, i: int) -> int:
        while i < len(self.tokens) and self.tokens[i].kind == "SEP":
            i += 1
        return i

    def peek(self, k: int = 0) -> Token | None:
        """区切り(SEP)を飛ばして k 個先のトークン"""
        i = self._skip(self.pos)
        for _ in range(k):
            i = self._skip(i + 1)
        return self.tokens[i] if i < len(self.tokens) else None

    def next(self) -> Token:
        i = self._skip(self.pos)
        if i >= len(self.tokens):
            last = self.tokens[-1].line if self.tokens else None
            raise SuruError("式が途中で終わっています", last)
        self.pos = i + 1
        return self.tokens[i]

    def sep_here(self) -> bool:
        """直前に読んだトークンの後に区切りがあるか"""
        return self.pos < len(self.tokens) and self.tokens[self.pos].kind == "SEP"

    def sep_stop(self) -> bool:
        return self.stop_sep and self.sep_here()

    def last_line(self) -> int | None:
        if not self.tokens:
            return None
        return self.tokens[min(self.pos, len(self.tokens) - 1)].line

    def parse_all(self) -> Any:
        expr = self.expr()
        tok = self.peek()
        if tok is not None:
            if tok.kind == "RP":
                raise SuruError("対応する「(」のない「)」があります", tok.line)
            if is_kw(tok, KW_IJOU):
                raise SuruError(f"対応する「もし 値 が」の場合分けか「以下の手順です」のない「{KW_IJOU}」があります", tok.line)
            if is_kw(tok, KW_PROVISO) and self.sep_indent(self.pos) >= 0:
                raise SuruError(PROVISO_INDENT_MESSAGE, tok.line)  # 字下げした行の頭の「ただし」
            raise SuruError(f"余分な「{tok.value}」があります", tok.line)
        return expr

    # 式 := もし 式 ならば 式 そうでなければ 式 | パイプライン
    def expr(self) -> Any:
        if is_kw(self.peek(), KW_IF):
            if_tok = self.next()
            start = self.pos
            match = self.match_rest(if_tok.line)
            if match is not None:
                return match
            self.pos = start
            cond = self.expr()
            tok = self.next()
            if not is_kw(tok, KW_THEN):
                if is_kw(tok, KW_GA) and isinstance(cond, Call):
                    raise SuruError(MATCH_CALL_MESSAGE, tok.line)
                raise SuruError("「もし」の後に「ならば」が必要です", tok.line)
            then = self.expr()
            tok = self.next()
            if not is_kw(tok, KW_ELSE):
                raise SuruError("「ならば」の後に「そうでなければ」が必要です", tok.line)
            other = self.expr()
            return If(cond, then, other)
        return self.logic_chain()

    # 述語の呼び出しどうしを「かつ」「または」でつなぐ: n が 正である かつ n が 偶数でない
    def logic_chain(self) -> Any:
        left = self.and_chain()
        while is_kw(self.peek(), KW_MATAHA) and not self.sep_stop() and not self.no_logic:
            tok = self.next()
            left = BinOp(KW_MATAHA, left, self.and_chain(), tok.line)
        return left

    def and_chain(self) -> Any:
        left = self.pipeline()
        while is_kw(self.peek(), KW_KATSU) and not self.sep_stop() and not self.no_logic:
            tok = self.next()
            left = BinOp(KW_KATSU, left, self.pipeline(), tok.line)
        return left

    def call_ahead(self, k: int, stops: tuple) -> bool:
        """k 個先から、次の stops の言葉までに呼び出しがあるか(あれば「かつ」は呼び出しの外でつなぐ)"""
        i = self._skip(self.pos)
        for _ in range(k):
            i = self._skip(i + 1)
        depth = 0
        while i < len(self.tokens):
            t = self.tokens[i]
            if t.kind == "LP":
                depth += 1
            elif t.kind == "RP":
                depth -= 1
                if depth < 0:
                    return False
            elif depth == 0:
                if t.kind == "PERIOD" or (t.kind == "KW" and t.value in stops + (KW_THEN, KW_ELSE, KW_TOWA)):
                    return False
                if t.kind == "SEP" and self.stop_sep:
                    return False
                if t.kind == "CALL":
                    return True
            i += 1
        return False

    # パイプライン := 区間 { 区間 }
    # 区間 := { 値 助詞 } 呼び出し(…して | …する | …すること)
    # 「…して」の結果は次の区間の「を」に入る。
    # 「…してから」の後ろは、前の動作の結果を受け取る続き(バインド)。
    # 「…した 結果」は、その呼び出しを手順の中で行った結果の値。
    def pipeline(self, piped: Any = None, has_piped: bool = False) -> Any:
        while True:
            args: dict = {}
            while True:
                tok = self.peek()
                if tok is None or tok.kind in ("RP", "PERIOD") or (tok.kind == "KW" and tok.value in CONTINUATION_KEYWORDS):
                    break
                if tok.kind == "CALL" and tok.form == SHITA:
                    self.next()
                    res = self.peek()
                    if res is None or res.kind != "WORD" or res.value not in (RESULT, CONTENT):
                        raise SuruError(f"「{tok.value[:-len(SURU)]}した」の後には「結果」か「中身」を書いてください", tok.line)
                    self.next()
                    if has_piped:
                        args = merge_piped(args, piped)
                    value: Any = Run(Call(tok.value, args, tok.line), tok.line, res.value == CONTENT)
                    args, piped, has_piped = {}, None, False
                elif tok.kind == "CALL" and tok.form != KOTO:
                    break
                elif tok.kind == "CALL":  # …すること
                    self.next()
                    if not is_part(self.peek()):
                        # 区間の最後の「こと」は、前に並んだ引数を受け取る(部分適用)
                        if has_piped:
                            args = merge_piped(args, piped, GA if is_predicate(tok.value) else WO)
                        return Ref(tok.value, args, tok.line)
                    # 後ろに助詞が続く「こと」は外側の呼び出しの引数(関数そのもの)
                    value = Ref(tok.value, {}, tok.line)
                elif is_kw(tok, KW_LAMBDA):
                    self.next()
                    if has_piped:
                        raise SuruError("「して」の後に「受け取って」は書けません", tok.line)
                    value = self.lambda_rest(args, tok.line)
                    args = {}
                else:
                    value = self.list_expr()
                part = self.peek()
                if is_kw(part, KW_GA) and self.predicate_ahead(1):
                    # 「n が 偶数である」: 述語の前の「が」は主語の助詞
                    part = Token("PART", GA, part.line)
                if is_part(part):
                    if part.value == WO and is_kw(self.peek(1), KW_RETURN):
                        # 「… を 返すこと」: 無名関数の本体の終わり
                        if args or has_piped:
                            raise SuruError("「返すこと」の前には値を1つだけ書いてください", part.line)
                        return value
                    self.next()
                    if part.value in args:
                        raise SuruError(f"助詞「{part.value}」が1つの呼び出しで2回使われています", part.line)
                    args[part.value] = value
                    continue
                # 助詞の付かない値
                if args or has_piped:
                    line = part.line if part else self.last_line()
                    if isinstance(value, Lambda) and any(isinstance(v, Each) for v in args.values()):
                        raise SuruError(EACH_LAMBDA_MESSAGE, line)
                    raise SuruError("値の後に助詞(を・に・で・から・へ・より)か「…する」が必要です", line)
                return value
            tok = self.peek()
            if tok is None or tok.kind != "CALL":
                line = tok.line if tok else self.last_line()
                if has_piped:
                    raise SuruError("「して」の後は「…する」で終わる必要があります", line)
                if args:
                    raise SuruError("助詞の後に「…する」が必要です", line)
                raise SuruError("式がありません", line)
            self.next()
            if has_piped:
                args = merge_piped(args, piped, GA if is_predicate(tok.value) else WO)
            piped = Call(tok.value, args, tok.line)
            has_piped = True
            if tok.form == SURU:
                return Not(piped, tok.line) if tok.negated else piped
            if tok.form == SHITEKARA:
                # 残りは前の動作の結果を「を」に受け取る続き
                cont = self.pipeline(Var(HOLE, tok.line), True)
                return Chain(piped, cont, tok.line)
            if tok.form == SHITA:
                raise SuruError("「した」の後には「結果」か「中身」を書いてください", tok.line)

    # --- パターンマッチ ---------------------------------------------------
    # もし 値 が パターン ならば 式 { 区切り パターン ならば 式 } [ そうでなければ 式 ]
    def sep_indent(self, i: int) -> int:
        """i から続く区切りのうち、行の切れ目の区切りの字下げ(なければ -1)"""
        d = -1
        while i < len(self.tokens) and self.tokens[i].kind == "SEP":
            if isinstance(self.tokens[i].value, int):
                d = self.tokens[i].value
            i += 1
        return d

    def outer_case_here(self, mine: int) -> bool:
        """次が、外側の場合分けの場合と同じか浅い字下げの行か(この場合分けより浅いときだけ)"""
        d = self.sep_indent(self.pos)
        if d < 0 or mine < 0 or d >= mine:
            return False
        return any(0 <= o[0] and d <= o[0] for o in self.case_indents[:-1])

    def match_rest(self, line: int) -> Match | None:
        """「もし」の後が「値 が パターン ならば」なら場合分けとして読む。違えば None"""
        try:
            items = [self.additive()]
            while is_kw(self.peek(), KW_TO):
                self.next()
                items.append(self.additive())
            subject = items[0] if len(items) == 1 else ListLit(items)
            if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)):
                no = self.next()
                subject = Construct(self.next().value, items, no.line)
            if not is_kw(self.peek(), KW_GA):
                return None
            self.next()
            first_pat = self.pos
            pat = self.pattern()
            guard = self.guard()
        except SuruError:
            return None
        if not is_kw(self.peek(), KW_THEN):
            return None
        cases: list = []
        default = None
        here = [self.sep_indent(first_pat)]
        self.case_indents.append(here)
        try:
            while True:
                check_pattern(pat, self.peek().line)
                self.next()  # ならば
                cases.append((pat, guard, self.case_body()))
                tok = self.peek()
                if is_kw(tok, KW_IJOU):
                    self.next()  # 「以上」: この場合分けを閉じる
                    break
                if self.outer_case_here(here[0]):
                    break  # 外側の場合分けの字下げの行: この場合分けはここまで
                if is_kw(tok, KW_ELSE):
                    self.next()
                    default = self.case_body()
                    if is_kw(self.peek(), KW_IJOU):
                        self.next()
                    break
                if tok is None or tok.kind in ("RP", "PERIOD") or not self.sep_here():
                    break
                if here[0] < 0:
                    here[0] = self.sep_indent(self.pos)
                pat = self.pattern()
                guard = self.guard()
                tok = self.peek()
                if not is_kw(tok, KW_THEN):
                    raise SuruError("場合の後に「ならば」が必要です", tok.line if tok else self.last_line())
        finally:
            self.case_indents.pop()
        if default is None:
            check_exhaustive(cases, line)
        return Match(subject, cases, default, line)

    def case_body(self) -> Any:
        save = self.stop_sep
        self.stop_sep = True
        try:
            return self.expr()
        finally:
            self.stop_sep = save

    def _compares_at(self, k: int) -> bool:
        t = self.peek(k)
        return is_kw(t, KW_GA) or (t is not None and t.kind == "OP" and t.value in ("==", "!=", "<", ">", "<=", ">="))

    def at_named(self) -> bool:
        t0, t1 = self.peek(), self.peek(1)
        return t0 is not None and t0.kind == "WORD" and is_kw(t1, KW_WA)

    def pattern(self) -> Any:
        if self.at_named():
            return self.named_pattern()
        p = self.try_ctor_pattern()
        if p is not None:
            return p
        save = self.no_logic
        self.no_logic = True
        try:
            return PValue(self.list_expr())
        finally:
            self.no_logic = save

    def guard(self) -> Any:
        """パターンの後の「かつ 条件」。なければ None"""
        if not is_kw(self.peek(), KW_KATSU):
            return None
        self.next()
        save = self.no_logic
        self.no_logic = False
        try:
            return self.logic_chain()
        finally:
            self.no_logic = save

    def param_pattern(self) -> Any:
        """場合ごとの関数定義の引数のパターン。名前だけなら新しい変数、「a と b」は要素ごと"""
        if self.at_named():
            return self.named_pattern()
        p = self.try_ctor_pattern()
        if p is not None:
            return p
        items = [self.pattern_item()]
        while is_kw(self.peek(), KW_TO):
            self.next()
            items.append(self.pattern_item())
        return items[0] if len(items) == 1 else PSeq(items)

    def try_ctor_pattern(self) -> Any:
        """「x と y の 点」「赤」。形の名前で終わらなければ None(位置は戻す)"""
        start = self.pos
        try:
            items = [self.pattern_item()]
            while is_kw(self.peek(), KW_TO):
                self.next()
                items.append(self.pattern_item())
        except SuruError:
            self.pos = start
            return None
        if (is_kw(self.peek(), KW_NO) or is_kw(self.peek(), KW_TOIU)) and is_ctor(self.peek(1)):
            # 「s の JSON文字列」「s という JSON文字列」(パターンでは「という」も書ける)
            no = self.next()
            return PCtor(self.next().value, items, no.line)
        if len(items) == 1 and isinstance(items[0], PCtor):
            return items[0]
        self.pos = start
        return None

    def pattern_item(self) -> Any:
        tok = self.next()
        if tok.kind == "WORD":
            if is_nullary(tok.value):
                return PCtor(tok.value, [], tok.line)
            if not tok.quoted and _is_all_hiragana(tok.value):
                raise hiragana_name_error(tok.value, tok.line)
            return PBind(tok.value)
        if tok.kind in ("NUM", "STR"):
            return PValue(Num(tok.value) if tok.kind == "NUM" else Str(tok.value))
        if tok.kind == "OP" and tok.value == "-" and self.peek() is not None and self.peek().kind == "NUM":
            return PValue(Num(-self.next().value))
        if tok.kind == "LP":
            save = self.stop_sep
            self.stop_sep = False
            inner = self.pattern()
            self.stop_sep = save
            close = self.next()
            if close.kind != "RP":
                raise SuruError("「)」が必要です", close.line)
            return inner
        raise SuruError(f"パターンに「{tok.value}」は書けません", tok.line)

    def named_pattern(self) -> PNamed:
        line = self.peek().line
        fields = []
        while True:
            name = self.next()
            self.next()  # は
            if any(f == name.value for f, _ in fields):
                raise SuruError(f"「{name.value}」が2回書かれています", name.line)
            fields.append((name.value, self.pattern_item()))
            if self.named_continues():
                self.next()
                continue
            break
        ctor = None
        if (is_kw(self.peek(), KW_NO) or is_kw(self.peek(), KW_TOIU)) and is_ctor(self.peek(1)):
            self.next()
            ctor = self.next().value
        return PNamed(fields, ctor, line)

    def named_continues(self) -> bool:
        """「横 は 3 で 縦 は …」の「で」の後に「名前 は」が続くか"""
        t2 = self.peek(2)
        return is_part(self.peek(), "で") and self.peek(1) is not None and self.peek(1).kind == "WORD" and is_kw(t2, KW_WA)

    # --- 組を作る ---------------------------------------------------------
    def named_construct(self) -> Any:
        """「横 は 3 で 縦 は 4 の 点」/「横 は 10 の p」(更新)"""
        line = self.peek().line
        fields: list = []
        while True:
            name = self.next()
            self.next()  # は
            if any(f == name.value for f, _ in fields):
                raise SuruError(f"「{name.value}」が2回書かれています", name.line)
            self.in_named = True
            try:
                value = self.comparison()
            finally:
                self.in_named = False
            fields.append((name.value, value))
            if self.named_continues():
                self.next()
                continue
            break
        last_name, last = fields[-1]
        if not is_kw(self.peek(), KW_NO) and isinstance(last, Field):
            # 「横 は 10 の p」: 最後の「の p」は更新する組
            fields[-1] = (last_name, last.target)
            return Update(Var(last.name, last.line), fields, line)
        if not is_kw(self.peek(), KW_NO):
            raise SuruError("「名前 は 値」の後に「の 型名」が必要です(例: 横 は 3 で 縦 は 4 の 点)", line)
        self.next()
        tok = self.peek()
        if is_ctor(tok):
            self.next()
            return NamedConstruct(tok.value, fields, line)
        return Update(self.atom(), fields, line)

    def lambda_rest(self, args: dict, line: int) -> Lambda:
        """「x を 受け取って 本体 を 返すこと」の「受け取って」より後ろ"""
        params = [(p, to_pattern(node, line)) for p, node in args.items()]
        check_params(params, line)
        body = self.expr()
        tok = self.peek()
        if tok is None:
            raise SuruError("「受け取って」の後は「… を 返すこと」で終わる必要があります", self.last_line())
        self.next()
        if not is_part(tok, WO) or not is_kw(self.peek(), KW_RETURN):
            raise SuruError("「受け取って」の後は「… を 返すこと」で終わる必要があります", tok.line)
        self.next()
        return Lambda(params, body, line)

    # 値 := 比較 { と 比較 }  (2つ以上ならリスト)
    # 「… の 型名」は、と で並べた値の全体にかかる: 3 と 4 の 点 → （3 と 4） の 点
    def list_expr(self) -> Any:
        if self.at_named():
            return self.named_construct()
        items = [self.logic()]
        while is_kw(self.peek(), KW_TO) and not self.sep_stop():
            self.next()
            items.append(self.logic())
        if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)) and not self.sep_stop():
            no = self.next()
            node = Construct(self.next().value, items, no.line)
            if is_kw(self.peek(), KW_TO):
                raise SuruError(
                    "組を「と」で並べるときは、（1 と 2 の 点） と （3 と 4 の 点） のように括弧で囲んでください",
                    no.line,
                )
            return node
        return items[0] if len(items) == 1 else ListLit(items)

    # 論理 := 論理積 { または 論理積 }、論理積 := 比較 { かつ 比較 }
    def logic(self) -> Any:
        left = self.conjunction()
        while is_kw(self.peek(), KW_MATAHA) and not self.sep_stop() and not self.no_logic \
                and not self.call_ahead(1, (KW_MATAHA,)):
            tok = self.next()
            left = BinOp(KW_MATAHA, left, self.conjunction(), tok.line)
        return left

    def conjunction(self) -> Any:
        left = self.comparison()
        while is_kw(self.peek(), KW_KATSU) and not self.sep_stop() and not self.no_logic \
                and not self.call_ahead(1, (KW_KATSU, KW_MATAHA)):
            tok = self.next()
            left = BinOp(KW_KATSU, left, self.comparison(), tok.line)
        return left

    def predicate_ahead(self, k: int) -> bool:
        """k 個先から読んで、この呼び出しの終わりが述語(…である/でない)か"""
        i = self._skip(self.pos)
        for _ in range(k):
            i = self._skip(i + 1)
        depth = 0
        while i < len(self.tokens):
            t = self.tokens[i]
            if t.kind == "LP":
                depth += 1
            elif t.kind == "RP":
                depth -= 1
                if depth < 0:
                    return False
            elif depth == 0:
                if t.kind == "PERIOD" or (t.kind == "KW" and t.value in (KW_THEN, KW_ELSE, KW_GA, KW_TOWA, KW_KATSU, KW_MATAHA)):
                    return False
                if t.kind == "SEP" and self.stop_sep:
                    return False
                if t.kind == "CALL":
                    if t.form == KOTO and i + 1 < len(self.tokens) and self.tokens[i + 1].kind == "PART":
                        i += 1  # 「偶数であること で 全部真である」: 引数に渡す関数の値は飛ばす
                        continue
                    return is_predicate(t.value) and t.form == SURU
            i += 1
        return False

    def comparison(self) -> Any:
        left = self.additive()
        if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)) and self._compares_at(2):
            # 「（3 と 4） の 点 が …」
            no = self.next()
            left = Construct(self.next().value, [left], no.line)
        tok = self.peek()
        if self.sep_stop():
            return left
        if is_kw(tok, KW_GA) and not self.predicate_ahead(1):
            self.next()
            right = self.additive()
            if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)):
                no = self.next()
                right = Construct(self.next().value, [right], no.line)
            return BinOp("==", left, right, tok.line)
        if tok is not None and tok.kind == "OP" and tok.value in ("==", "!=", "<", ">", "<=", ">="):
            self.next()
            right = self.additive()
            return BinOp(tok.value, left, right, tok.line)
        return left

    def additive(self) -> Any:
        left = self.term()
        while (tok := self.peek()) is not None and tok.kind == "OP" and tok.value in ("+", "-") and not self.sep_stop():
            self.next()
            left = BinOp(tok.value, left, self.term(), tok.line)
        return left

    def term(self) -> Any:
        left = self.unary()
        while (tok := self.peek()) is not None and tok.kind == "OP" and tok.value in ("*", "/", "%") and not self.sep_stop():
            self.next()
            left = BinOp(tok.value, left, self.unary(), tok.line)
        return left

    def unary(self) -> Any:
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value == "-":
            self.next()
            return Neg(self.unary())
        return self.power()

    def power(self) -> Any:
        base = self.postfix()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value == "^" and not self.sep_stop():
            self.next()
            return BinOp("^", base, self.unary(), tok.line)  # 右結合
        return base

    # 「リスト の 残り の 先頭」
    def postfix(self) -> Any:
        node = self.atom()
        while is_kw(self.peek(), KW_NO) and not self.sep_stop():
            nxt = self.peek(1)
            if is_ctor(nxt) or (self.in_named and nxt is not None and nxt.kind == "LP"):
                break  # 「… の 型名」は list_expr で、「横 は 10 の （…）」は named_construct で読む
            no = self.next()
            name = self.next()
            if name.kind != "WORD":
                raise SuruError(
                    f"「の」の後には {'・'.join(sorted(PROPERTIES))} かフィールドの名前を書いてください", no.line
                )
            if name.value == "それぞれ":
                node = Each(node, no.line)
            elif name.value in PROPERTIES:
                node = Prop(node, name.value, no.line)
            else:
                node = Field(node, name.value, no.line)
        return node

    def paren_block(self, open_tok: Token) -> Any:
        """括弧の中に「。」か「とは」があれば文の並び(ブロック)として読む: （合計とは、a+b。合計/2）"""
        depth, i, is_block = 0, self.pos, False
        while i < len(self.tokens):
            t = self.tokens[i]
            if t.kind == "LP":
                depth += 1
            elif t.kind == "RP":
                if depth == 0:
                    break
                depth -= 1
            elif depth == 0 and (t.kind == "PERIOD" or is_kw(t, KW_TOWA)):
                is_block = True
            i += 1
        else:
            raise SuruError("「(」に対応する「)」がありません", open_tok.line)
        if not is_block:
            return None
        inner = self.tokens[self.pos : i]
        self.pos = i + 1
        sentences = split_sentences(inner + [Token("PERIOD", PERIOD, open_tok.line)])
        if not sentences:
            raise SuruError("括弧の中に式がありません", open_tok.line)
        nodes = [Node(Line(0, s, s[0].line, closed=True)) for s in sentences]
        return parse_block(nodes)

    def paren_do(self, open_tok: Token) -> Do:
        """「手順（文。文。…）」: 括弧の中の文を順に行う"""
        depth, i = 0, self.pos
        while i < len(self.tokens):
            t = self.tokens[i]
            if t.kind == "LP":
                depth += 1
            elif t.kind == "RP":
                if depth == 0:
                    break
                depth -= 1
            i += 1
        else:
            raise SuruError("「(」に対応する「)」がありません", open_tok.line)
        inner = self.tokens[self.pos : i]
        self.pos = i + 1
        sentences = [strip_seps(x) for x in split_sentences(inner + [Token("PERIOD", PERIOD, open_tok.line)])]
        sentences = [x for x in sentences if x]
        if not sentences:
            raise SuruError("手順の中に文がありません", open_tok.line)
        return parse_do([Node(Line(0, x, x[0].line, closed=True)) for x in sentences], open_tok.line)

    def atom(self) -> Any:
        tok = self.next()
        if tok.kind == "NUM":
            return Num(tok.value, tok.line)
        if tok.kind == "STR":
            return Str(tok.value, tok.line)
        if tok.kind == "DO":
            # 「以下の手順です」+ 文 + 「以上」
            do = parse_do(tok.value, tok.line)
            do.io = tok.form == KW_IKA_IO
            return do
        if tok.kind == "WORD":
            nxt = self.tokens[self.pos] if self.pos < len(self.tokens) else None
            if tok.value in (TEJUN, TEJUN_IO) and not tok.quoted and nxt is not None and nxt.kind == "LP":
                self.next()
                do = self.paren_do(nxt)
                do.io = tok.value == TEJUN_IO
                return do
            return Var(tok.value, tok.line, tok.quoted)
        if tok.kind == "LP":
            block = self.paren_block(tok)
            if block is not None:
                return block
            save = self.stop_sep
            self.stop_sep = False
            inner = self.expr()
            self.stop_sep = save
            close = self.next()
            if close.kind != "RP":
                raise SuruError("「)」が必要です", close.line)
            return inner
        if tok.kind == "CALL" and tok.form == KOTO:
            return Ref(tok.value, {}, tok.line)
        raise SuruError(f"ここに「{tok.value}」は書けません", tok.line)


def parse_definition_head(tokens: list[Token], line: int) -> tuple[str, list, bool]:
    """「a を b で 除算する」→ ("除算する", [("を", "a"), ("で", "b")], True)、「x」→ ("x", [], False)"""
    tokens = nosep(tokens)
    if not tokens:
        raise SuruError("「とは」の前に定義する名前が必要です", line)
    last = tokens[-1]
    if last.kind == "CALL" and is_predicate(last.value):
        if last.negated:
            raise SuruError("述語は「…である」の形で定義してください(「…でない」は自動で使えます)", last.line)
        tokens = [Token("PART", GA, t.line) if is_kw(t, KW_GA) else t for t in tokens]
    for t in tokens:
        if t.kind == "WORD" and not t.quoted and _is_all_hiragana(t.value) and t.value != "それぞれ":
            raise hiragana_name_error(t.value, t.line)
    if last.kind == "WORD" and len(tokens) == 1:
        return last.value, [], False  # 値の定義: 「税率 とは 0.1」
    if last.kind != "CALL" or last.form != SURU:
        raise not_suru_error(last)
    if any(_is_pattern_token(t) for t in tokens[:-1]):
        return last.value, parse_pattern_head(tokens[:-1], line), True
    params: list = []
    names: list[str] = []
    for t in tokens[:-1]:
        if t.kind == "WORD":
            if names and not is_kw(prev, KW_TO):
                raise SuruError("引数名の後には助詞(を・に・で・から・へ・より)が必要です", t.line)
            names.append(t.value)
        elif is_kw(t, KW_TO):
            if not names or prev.kind != "WORD":
                raise SuruError("「と」の前に引数名が必要です", t.line)
        elif t.kind == "PART":
            if not names or prev.kind != "WORD":
                raise SuruError(f"助詞「{t.value}」の前に引数名が必要です", t.line)
            if any(p == t.value for p, _ in params):
                raise SuruError(f"助詞「{t.value}」が2回使われています(1つの関数で各助詞は1回まで)", t.line)
            params.append((t.value, names[0] if len(names) == 1 else names))
            names = []
        else:
            raise SuruError(f"引数名に「{t.value}」は使えません", t.line)
        prev = t
    if names:
        raise SuruError("引数名の後には助詞(を・に・で・から・へ・より)が必要です", line)
    check_params(params, line)
    return last.value, params, True


def _is_pattern_token(t: Token) -> bool:
    """引数に値や形を書いた定義(場合ごとの関数定義)かどうか"""
    if t.kind in ("NUM", "STR", "LP", "RP", "OP"):
        return True
    if t.kind == "KW" and t.value in (KW_NO, KW_WA):
        return True
    return t.kind == "WORD" and is_nullary(t.value)


def parse_pattern_head(tokens: list[Token], line: int) -> list:
    """「0 を」「先頭 は x で 残り は 他 を」「（半径 の 円） を」のような引数を [(助詞, パターン)] にする"""
    segments: list = []
    cur: list[Token] = []
    depth = 0
    for k, t in enumerate(tokens):
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        named_and = (
            is_part(t, "で") and k + 2 < len(tokens) and tokens[k + 1].kind == "WORD" and is_kw(tokens[k + 2], KW_WA)
        )
        if t.kind == "PART" and depth == 0 and not named_and:
            if not cur:
                raise SuruError(f"助詞「{t.value}」の前に引数が必要です", t.line)
            if any(p == t.value for p, _ in segments):
                raise SuruError(f"助詞「{t.value}」が2回使われています(1つの関数で各助詞は1回まで)", t.line)
            segments.append((t.value, cur))
            cur = []
        else:
            cur.append(t)
    if cur:
        raise SuruError("引数の後には助詞(を・に・で・から・へ・より)が必要です", cur[-1].line)
    params = []
    for part, seg in segments:
        parser = ExprParser(seg)
        pat = parser.param_pattern()
        rest = parser.peek()
        if rest is not None:
            raise SuruError(f"引数のパターンに「{rest.value}」は書けません", rest.line)
        params.append((part, pat))
    check_pattern(PSeq([p for _, p in params]), line)
    return params


def _is_simple_param(pat: Any) -> bool:
    return isinstance(pat, str) or (isinstance(pat, list) and all(isinstance(x, str) for x in pat))


def _param_to_pattern(pat: Any) -> Any:
    if isinstance(pat, str):
        return PBind(pat)
    if isinstance(pat, list):
        return PSeq([_param_to_pattern(x) for x in pat])
    return pat


def _matches_anything(pat: Any) -> bool:
    return isinstance(pat, PBind)


def combine_clauses(group: list) -> "Define":
    """同じ関数の場合ごとの定義を、引数のパターンマッチ1つにまとめる"""
    first = group[0]
    name = first.name
    order = [p for p, _ in first.params]
    for d in group[1:]:
        if sorted(p for p, _ in d.params) != sorted(order):
            raise SuruError(
                f"「{name}」の定義ごとに助詞が違います(場合ごとに定義するときは、どれも同じ助詞で書いてください。"
                f"{first.line}行目は「{'・'.join(order) or 'なし'}」)",
                d.line,
            )
    slot = {p: f"（{p}）" for p in order}
    cases = []
    for k, d in enumerate(group):
        pats = {p: _param_to_pattern(x) for p, x in d.params}
        items = [pats[p] for p in order]
        pat = items[0] if len(items) == 1 else PSeq(items)
        if k + 1 < len(group) and all(_matches_anything(x) for x in items):
            raise SuruError(
                f"「{name}」のこの定義はどんな値にも当てはまるので、{group[k + 1].line}行目からの定義が使われません"
                "(決まった値や形の場合を先に書いてください)",
                d.line,
            )
        cases.append((pat, None, d.body))
    if len(order) == 1:
        subject: Any = Var(slot[order[0]], first.line)
        check_exhaustive(cases, first.line, name)
    else:
        subject = ListLit([Var(slot[p], first.line) for p in order])
    body = Match(subject, cases, None, first.line, fname=name)
    return Define(name, [(p, slot[p]) for p in order], body, True, first.line)


def merge_clauses(statements: list) -> list:
    """続けて書いた同じ名前の関数定義をまとめる。離れた場所で同じ関数を定義し直すとエラー"""
    out: list = []
    seen: dict[str, int] = {}
    i = 0
    while i < len(statements):
        s = statements[i]
        if not (isinstance(s, Define) and s.is_function):
            out.append(s)
            i += 1
            continue
        j = i + 1
        while j < len(statements) and isinstance(statements[j], Define) and statements[j].is_function \
                and statements[j].name == s.name:
            j += 1
        group = statements[i:j]
        if s.name in seen:
            raise SuruError(
                f"「{s.name}」は{seen[s.name]}行目でも定義されています(場合ごとに定義するときは続けて書いてください)", s.line
            )
        seen[s.name] = s.line
        if len(group) == 1 and all(_is_simple_param(p) for _, p in s.params):
            out.append(s)
        else:
            out.append(combine_clauses(group))
        i = j
    return out


def find_top_level(tokens: list[Token], value: str) -> int | None:
    depth = 0
    for i, t in enumerate(tokens):
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        elif depth == 0 and is_kw(t, value):
            return i
    return None


def _index_of(raw: list[Token], tok: Token) -> int:
    return next(i for i, t in enumerate(raw) if t is tok)


def _with_children(tokens: list[Token], children: list[Node]) -> list[Token]:
    """行のトークンに深い行を続ける。「以下の手順です」で終わる行なら、深い行(手順の文)を1つの DO トークンにする"""
    toks = nosep(tokens)
    if children and toks and toks[-1].kind == "KW" and toks[-1].value in IKA_WORDS:
        k = len(tokens) - 1 - tokens[::-1].index(toks[-1])
        return list(tokens[:k]) + [Token("DO", children, toks[-1].line, toks[-1].value)] + list(tokens[k + 1 :])
    out = list(tokens)
    for c in children:
        out.append(Token("SEP", c.line.indent, c.line.number))
        out.extend(flatten(c))
    return out


def parse_statement(node: Node) -> Any:
    raw = node.line.tokens
    tokens = nosep(raw)
    if len(tokens) == 1 and is_kw(tokens[0], KW_IJOU):
        raise SuruError(f"対応する「以下の手順です」のない「{KW_IJOU}」があります", tokens[0].line)
    if any(is_test_head(t) for t in tokens):
        return parse_test_block(node, tokens)
    if tokens[0].kind == "WORD" and not tokens[0].quoted and tokens[0].value == KW_EXAMPLE:
        return parse_example(node)
    if is_kw(tokens[0], KW_SOREKARA):
        rest = raw[_index_of(raw, tokens[0]) + 1 :]
        inner_node = Node(Line(node.line.indent, rest, node.line.number, node.line.closed), node.children)
        if not nosep(flatten(inner_node)):
            raise SuruError("「それから」の後に文が必要です", tokens[0].line)
        stmt = parse_statement(inner_node)
        if isinstance(stmt, (Define, Proviso, Sequel) + TOP_LEVEL_ONLY):
            raise SuruError("「それから」の後には行うこと(式)を書いてください", tokens[0].line)
        return Sequel(stmt, tokens[0].line)
    if is_kw(tokens[0], KW_PROVISO):
        rest = raw[_index_of(raw, tokens[0]) + 1 :]
        if not nosep(rest):
            raise SuruError("「ただし」の後に定義が必要です", tokens[0].line)
        inner_node = Node(Line(node.line.indent, rest, node.line.number, node.line.closed), node.children)
        if find_top_level(nosep(rest), KW_TOWA) is None:
            # 性質の関数の宣言: 「ただし、x を 文字列化する。」
            head = nosep(flatten(inner_node))
            if head[-1].kind != "CALL" or head[-1].form != SURU:
                raise SuruError("「ただし」の後には「…とは」の定義を書いてください", tokens[0].line)
            name, params, _ = parse_definition_head(head, node.line.number)
            return Proviso(None, tokens[0].line, sig=(name, params))
        inner = parse_statement(inner_node)
        if not isinstance(inner, Define):
            raise SuruError("「ただし」の後には「…とは」の定義を書いてください", tokens[0].line)
        return Proviso(inner, tokens[0].line)
    vis = try_parse_visibility(nosep(flatten(node)))
    if vis is not None:
        return vis
    if is_kw(tokens[0], KW_EXPORT_MARK):
        return Export(tokens[1].value, tokens[2].value, tokens[0].line)
    typedef = try_parse_typedef(node)
    if typedef is not None:
        return typedef
    towa = find_top_level(tokens, KW_TOWA)
    if towa is None:
        sig = try_parse_type_sig(nosep(flatten(node)))
        if sig is not None:
            return sig
        if len(tokens) == 3 and tokens[0].kind == "WORD" and is_kw(tokens[1], KW_WA) and tokens[2].kind == "WORD":
            return parse_trait_impl(node, tokens)
        return ExprParser(flatten(node)).parse_all()
    head = tokens[:towa]
    after = raw[_index_of(raw, tokens[towa]) + 1 :]
    if len(head) == 3 and head[0].kind == "WORD" and is_kw(head[1], KW_TOIU) and is_kw(head[2], KW_SEISHITSU):
        return parse_trait_decl(node, head[0], after)
    name, params, is_function = parse_definition_head(head, node.line.number)
    if MODULE_SEP in name and not head[0].qualified:
        raise SuruError(f"「{name}」: 読み込んだファイルの中の名前は定義できません", head[0].line)
    after_t = nosep(after)
    if len(after_t) == 1 and after_t[0].kind == "KW" and after_t[0].value in IKA_WORDS:
        # 「挨拶する とは 以下の手順です」+ 文 + 「以上」(文は close_ijou が深い行にまとめた)
        do = parse_do(node.children, node.line.number)
        do.io = after_t[0].value == KW_IKA_IO
        return Define(name, params, do, is_function, node.line.number)
    if (len(after_t) == 1 and after_t[0].kind == "WORD" and after_t[0].value in (TEJUN, TEJUN_IO)
            and not after_t[0].quoted and node.children):
        # 「挨拶する とは 手順」+ 深い行: 深い行を順に行う(「入出力手順」なら動作だけ)
        do = parse_do(node.children, node.line.number)
        do.io = after_t[0].value == TEJUN_IO
        return Define(name, params, do, is_function, node.line.number)
    if (len(after_t) == 2 and after_t[0].kind == "WORD" and after_t[0].value == KW_EXTERN and not after_t[0].quoted
            and after_t[1].kind == "STR" and not node.children):
        # 「x を 余弦にする とは 外部の「cos」」: C の関数を呼ぶ
        sym = after_t[1].value
        if not sym.isascii() or not (sym[:1].isalpha() or sym[:1] == "_") or not all(c.isalnum() or c == "_" for c in sym):
            raise SuruError(f"「{sym}」は C の関数の名前ではありません", after_t[1].line)
        if sym.startswith(("rt_", "suru_")):
            raise SuruError(f"「{sym}」は「する」の実行時が使う名前なので、外部の関数にできません", after_t[1].line)
        return Define(name, params, Extern(sym, after_t[1].line), is_function, node.line.number)
    if (len(after_t) >= 5 and after_t[0].kind == "WORD" and after_t[0].value == KW_EXTERN and not after_t[0].quoted
            and after_t[1].kind == "STR" and after_t[2].kind == "LP" and after_t[-1].kind == "RP" and not node.children):
        # 「… とは 外部の「pcre2_match_8」（c と s と n と o と 0 と md と 0）」: C に渡す引数を並べて書く
        sym = after_t[1].value
        if not sym.isascii() or not (sym[:1].isalpha() or sym[:1] == "_") or not all(c.isalnum() or c == "_" for c in sym):
            raise SuruError(f"「{sym}」は C の関数の名前ではありません", after_t[1].line)
        if sym.startswith(("rt_", "suru_")):
            raise SuruError(f"「{sym}」は「する」の実行時が使う名前なので、外部の関数にできません", after_t[1].line)
        return Define(name, params, Extern(sym, after_t[1].line, cargs=_parse_extern_args(after_t[3:-1], after_t[2])),
                      is_function, node.line.number)
    if (len(after_t) == 4 and after_t[0].kind == "WORD" and after_t[0].value == KW_EXTERN and not after_t[0].quoted
            and after_t[1].kind == "LP" and after_t[2].kind == "WORD" and after_t[3].kind == "RP" and not node.children):
        # 「x を f で 呼ぶ とは 外部の（f）」: 引数 f の番地にある C の関数を呼ぶ
        return Define(name, params, Extern("", after_t[2].line, pointer=after_t[2].value), is_function, node.line.number)
    if nosep(after):
        # 同じ行に本体がある: 深い行はその続き
        body: Any = ExprParser(_with_children(after, node.children)).parse_all()
    else:
        if not node.children:
            raise SuruError("「とは」の後に本体が必要です", node.line.number)
        body = parse_block(node.children)
    return Define(name, params, body, is_function, node.line.number)


TEST_PREFIX = "《試験》"  # 試験のまとまりの、中だけで使う名前の頭(書いて呼べない名前にする)
EXAMPLE_PREFIX = "《例》"


def parse_test_block(node: Node, tokens: list[Token]) -> Define:
    """「以下は「二倍」の試験です」+ 手順の文 + 「以上です」(#193)。引数のない手順の定義にする"""
    head = tokens[0]
    if len(tokens) != 1 or not is_test_head(head):
        t = next(t for t in tokens if is_test_head(t))
        raise SuruError(f"「{t.value}です」は1行に、それだけを書きます(手順の文は次の行から書き、最後に「{KW_IJOU}です」)", t.line)
    if node.line.indent:
        raise SuruError(f"「{head.value}です」は一番外(字下げなし)に書いてください", head.line)
    name = test_head_name(head)
    if not name.strip():
        raise SuruError("試験の名前を「」の中に書いてください(「以下は「二倍」の試験です」)", head.line)
    do = parse_do(node.children, node.line.number)
    return Define(TEST_PREFIX + name, [], do, True, node.line.number, test=name)


def parse_example(node: Node) -> Define:
    """「例えば （2 を 二倍する） は 4 です」(#193)。実際 = 期待 を確かめる、引数のない定義にする"""
    raw = flatten(node)
    tokens = nosep(raw)
    word = tokens[0]
    usage = f"「{KW_EXAMPLE} （2 を 二倍する） は 4 です」のように、「{KW_EXAMPLE} 式 は 期待する値」と書きます"
    if node.line.indent:
        raise SuruError(f"「{KW_EXAMPLE}」の例は一番外(字下げなし)に、定義のすぐ下に書いてください", word.line)
    rest = tokens[1:]
    wa = find_top_level(rest, KW_WA)
    if wa is None or wa == 0 or wa == len(rest) - 1:
        raise SuruError(usage, word.line)
    actual = ExprParser(rest[:wa]).parse_all()
    expected = ExprParser(rest[wa + 1:]).parse_all()
    body = BinOp("==", actual, expected, word.line)
    return Define(f"{EXAMPLE_PREFIX}{node.line.number}", [], body, True, node.line.number, test="例",
                  example=(actual, expected))


def is_test_define(s: Any) -> bool:
    return isinstance(s, Define) and bool(s.test)


def drop_tests(program: list) -> list:
    """試験のまとまりと例、それらのために読み込んだ「試験」を除く(通常のビルドと、読み込んだファイル)"""
    return [s for s in program if not is_test_define(s) and not (isinstance(s, Import) and s.test)]


def name_examples(statements: list) -> None:
    """例の名前を、すぐ上の定義の名前から決める(「二倍するの例」)。同じ名前の試験のまとまりが2つあればエラー"""
    prev = ""
    seen: dict[str, int] = {}
    for s in statements:
        if not isinstance(s, Define):
            continue
        if s.example is not None:
            s.test = f"{prev}の例" if prev else "例"
        elif s.test:
            if s.test in seen:
                raise SuruError(f"「{s.test}」の試験は{seen[s.test]}行目にもあります(試験の名前は1つずつ違うものにしてください)", s.line)
            seen[s.test] = s.line
        else:
            prev = s.name


def _is_type_word(tok: Token) -> bool:
    return tok.kind == "WORD" and (
        tok.value in BUILTIN_TYPES or tok.value in _CTX.types or (len(tok.value) == 1 and tok.value in TYPE_VAR_NAMES)
    )


RETURNS_ONLY_FUN = "「を 返す」は関数の型の宣言の終わりにだけ書けます(「数 を 階乗する は 数 を 返す」)"


def drop_returns(right: list[Token]) -> tuple[list[Token], bool]:
    """型の宣言の「は」より後ろの終わりの飾り「を 返す」「を 返します」を取り除く"""
    if len(right) >= 3 and right[-2].kind == "PART" and right[-2].value == WO and right[-1].kind == "KW" \
            and right[-1].value in (KW_HENSU, KW_HENSU_POLITE):
        return right[:-2], True
    return right, False


def action_returning(tokens: list[Token]) -> list[Token]:
    """型の宣言の中の「数 を 返す 動作」を「数 の 動作」にする(「入出力動作」も)"""
    out: list[Token] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if (t.kind == "PART" and t.value == WO and i + 2 < len(tokens) and is_kw(tokens[i + 1], KW_HENSU)
                and tokens[i + 2].kind == "WORD" and tokens[i + 2].value in (ACTION_TYPE, ACTION_ALIAS)
                and not tokens[i + 2].quoted):
            out.append(Token("KW", KW_NO, t.line))
            out.append(tokens[i + 2])
            i += 3
            continue
        out.append(t)
        i += 1
    return out


ACTION_TYPE = "動作"
ACTION_ALIAS = "入出力動作"


def try_parse_type_sig(tokens: list[Token]) -> TypeSig | None:
    """「数 を 階乗する は 数」「税率 は 数」なら型の宣言を返す(そうでなければ None)"""
    ha = find_top_level(tokens, KW_WA)
    if ha is None or ha == 0 or ha == len(tokens) - 1:
        return None
    left, right = tokens[:ha], tokens[ha + 1 :]
    line = tokens[0].line
    last = left[-1]
    right, returns = drop_returns(right)
    left, right = action_returning(left), action_returning(right)
    if last.kind == "CALL" and last.form == SURU and not last.negated:
        # 関数: 「型 助詞 型 助詞 … 名前する は 型」(後ろに「を 返す」を付けてもよい)
        params = []
        i = 0
        while i < len(left) - 1:
            t, i = parse_param_type(left, i, len(left) - 1)
            if i >= len(left) - 1 or not (left[i].kind == "PART" or is_kw(left[i], GA)):
                raise SuruError("型の宣言では、引数の型の後に助詞を書いてください(「数 を 階乗する は 数」)", line)
            params.append((left[i].value, t))
            i += 1
        name = last.value
        if any(p == q for k, (p, _) in enumerate(params) for q, _ in params[:k]):
            raise SuruError(f"「{name}」の型の宣言で同じ助詞が2回使われています", line)
        return TypeSig(name, params, parse_type_all(right, line), line)
    if (last.kind in ("WORD", "CALL") and len(left) >= 2 and (left[-2].kind == "PART" or is_kw(left[-2], GA))
            and _parses_as_type(right, line)):
        # 「数 で 流す は 数 を 返す 入出力動作」: 関数の型の宣言のつもりで、名前が「する」で終わっていない
        raise not_suru_error(last)
    if len(left) == 1 and left[0].kind == "WORD" and right and (_is_type_word(right[0]) or right[0].kind == "LP"):
        # 値: 「税率 は 数」(「点 は 比較可能」は性質の実装)
        if len(right) == 1 and not _is_type_word(right[0]):
            return None
        if returns:
            raise SuruError(RETURNS_ONLY_FUN, line)
        return TypeSig(_check_name(left[0]), None, parse_type_all(right, line), line)
    return None


TUPLE_TYPE = "と"  # 引数の「文字列 と JSON を」の型(長さと要素ごとの型が決まったリスト)


def parse_param_type(tokens: list[Token], i: int, end: int) -> tuple[Any, int]:
    """引数の型を1つ読む。「文字列 と JSON を」のように「と」でつなげば、定義の「名 と 値 を」に合わせて
    要素ごとに型の違うリスト(TypeName("と", [文字列, JSON]))"""
    t, i = parse_type(tokens, i)
    items = [t]
    while i < end - 1 and is_kw(tokens[i], KW_TO):
        t, i = parse_type(tokens, i + 1)
        items.append(t)
    return (t, i) if len(items) == 1 else (TypeName(TUPLE_TYPE, items), i)


def not_suru_error(last: Token) -> SuruError:
    """関数名が「する」で終わっていない(「x で 流す とは …」「数 で 流す は 数」)"""
    word = str(last.value)
    if last.kind == "CALL" and word.endswith(SURU):
        word = word[: -len(SURU)] + last.form
    return SuruError(f"関数名は「する」で終わる必要があります(「{word}」)", last.line)


def _parses_as_type(tokens: list[Token], line: int) -> bool:
    try:
        parse_type_all(tokens, line)
    except SuruError:
        return False
    return True


def parse_type_all(tokens: list[Token], line: int) -> Any:
    if not tokens:
        raise SuruError("「は」の後に型を書いてください", line)
    t, i = parse_type(tokens, 0)
    if i != len(tokens):
        raise SuruError(f"型の書き方が正しくありません(「{tokens[i].value}」)", tokens[i].line)
    return t


def _matching(tokens: list[Token], i: int) -> int:
    depth = 0
    for j in range(i, len(tokens)):
        if tokens[j].kind == "LP":
            depth += 1
        elif tokens[j].kind == "RP":
            depth -= 1
            if depth == 0:
                return j
    raise SuruError("「（」が閉じていません", tokens[i].line)


def parse_type(tokens: list[Token], i: int) -> tuple[Any, int]:
    """型を1つ読む: 「数」「甲」「数 の リスト」「（数 と 文字列） の 点」「（数 を 受け取って 数 を 返すこと）」"""
    if i >= len(tokens):
        raise SuruError("型が必要です", tokens[-1].line)
    tok = tokens[i]
    args: list | None = None
    if tok.kind == "LP":
        j = _matching(tokens, i)
        inner = tokens[i + 1 : j]
        i = j + 1
        if find_top_level(inner, KW_RETURN) is not None:
            t: Any = parse_fun_type(inner, tok.line)
        elif find_top_level(inner, KW_TO) is not None:
            args = [parse_type_all(part, tok.line) for part in split_top_level(inner, KW_TO)]
            t = None
        else:
            t = parse_type_all(inner, tok.line)
    elif tok.kind == "WORD":
        t = _type_word(tok, [])
        i += 1
    else:
        raise SuruError(f"「{tok.value}」は型ではありません", tok.line)
    while i + 1 < len(tokens) and is_kw(tokens[i], KW_NO) and tokens[i + 1].kind == "WORD":
        t = _type_word(tokens[i + 1], args if args is not None else [t])
        args = None
        i += 2
    if args is not None:
        raise SuruError("「（甲 と 乙）」の後には「の 型名」が必要です", tok.line)
    return t, i


def _type_word(tok: Token, args: list) -> Any:
    name = tok.value
    if name == ACTION_ALIAS:
        name = ACTION_TYPE  # 「入出力動作」は「動作」の別名
    if len(name) == 1 and name in TYPE_VAR_NAMES and not tok.quoted:
        if args:
            raise SuruError(f"「{name}」は型の引数をとりません", tok.line)
        return TypeVarName(name)
    if name in ("数", "文字列", "真偽", "小数", "整数", "番地", "バイト列", "無", "単精度") and args:
        raise SuruError(f"「{name}」は型の引数をとりません", tok.line)
    if name in ("リスト", "動作", "C形") and len(args) != 1:
        raise SuruError(f"「{name}」の前には型を1つ書いてください(「数 の {name}」)", tok.line)
    if name not in BUILTIN_TYPES and name not in _CTX.types:
        raise SuruError(f"「{name}」という型はありません", tok.line)
    return TypeName(name, list(args))


def parse_fun_type(tokens: list[Token], line: int) -> TypeFun:
    """「数 を 数 で 受け取って 数 を 返すこと」「数 を 返すこと」"""
    k = find_top_level(tokens, KW_LAMBDA)
    params = []
    if k is not None:
        i = 0
        while i < k:
            t, i = parse_param_type(tokens[:k], i, k)
            if i >= k or not (tokens[i].kind == "PART" or is_kw(tokens[i], GA)):
                raise SuruError("関数の型では、引数の型の後に助詞を書いてください", line)
            params.append((tokens[i].value, t))
            i += 1
        rest = tokens[k + 1 :]
    else:
        rest = tokens
    if len(rest) < 3 or not (rest[-2].kind == "PART" and rest[-2].value == "を") or not is_kw(rest[-1], KW_RETURN):
        raise SuruError("関数の型は「（数 を 受け取って 数 を 返すこと）」のように書きます", line)
    return TypeFun(params, parse_type_all(rest[:-2], line))


def split_top_level(tokens: list[Token], value: str) -> list[list[Token]]:
    out, cur, depth = [], [], 0
    for t in tokens:
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        if depth == 0 and is_kw(t, value):
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    out.append(cur)
    return out


def _check_name(tok: Token) -> str:
    if tok.kind != "WORD":
        raise SuruError(f"名前に「{tok.value}」は使えません", tok.line)
    if not tok.quoted and _is_all_hiragana(tok.value):
        raise hiragana_name_error(tok.value, tok.line)
    if tok.qualified:
        return tok.value
    if MODULE_SEP in tok.value:
        raise SuruError(f"「{tok.value}」: 読み込んだファイルの中の名前は定義できません", tok.line)
    return tok.value


def try_parse_typedef(node: Node) -> TypeDef | None:
    """「点 とは 横 と 縦 の 組」「図形 とは 半径 の 円 か 幅 と 高 の 長方形」「信号 とは 赤 か 黄 か 青」"""
    tokens = nosep(flatten(node))
    towa = find_top_level(tokens, KW_TOWA)
    if towa != 1 or tokens[0].kind != "WORD":
        return None
    body = tokens[2:]
    has_ka = find_top_level(body, KW_KA) is not None
    if not body or not (has_ka or is_kw(body[-1], KW_KUMI)):
        return None
    name = _check_name(tokens[0])
    line = tokens[0].line
    ctors = []
    typed: bool | None = None  # フィールドの型を書いたか(まだフィールドがなければ None)
    field_types: dict = {}
    for alt in split_top_level(body, KW_KA):
        if not alt:
            raise SuruError("「か」の前後に形を書いてください", line)
        if len(alt) == 1 and alt[0].kind == "WORD":
            ctors.append((_check_name(alt[0]), []))
            continue
        if len(alt) < 3 or not is_kw(alt[-2], KW_NO):
            raise SuruError(
                "型の形は「横 と 縦 の 点」のように「フィールド名 と … の 形の名前」で書いてください", alt[0].line
            )
        last = alt[-1]
        if is_kw(last, KW_KUMI):
            if has_ka:
                raise SuruError("「組」は形が1つのときだけ使えます(「か」で並べるときは形に名前を付けてください)", last.line)
            cname = name
        else:
            cname = _check_name(last)
        fields: list[str] = []
        if find_top_level(alt[:-2], KW_WA) is not None:
            # 「番号 は 数 で 名前 は 文字列 の 会員」: フィールドごとに型を書く
            typed = True if typed is None else typed
            if not typed:
                raise SuruError("フィールドの型は、型のすべてのフィールドに書くか、どれにも書かないかにしてください", last.line)
            for part in _split_typed_fields(alt[:-2], last.line):
                if len(part) < 3 or not is_kw(part[1], KW_WA):
                    raise SuruError("型を書くフィールドは「番号 は 数 で 名前 は 文字列 の 組」のように"
                                    "「フィールド名 は 型」を「で」で区切って書いてください", part[0].line if part else last.line)
                f = _check_name(part[0])
                if f in fields:
                    raise SuruError(f"フィールド名「{f}」が2回書かれています", part[0].line)
                fields.append(f)
                prev = field_types.get(f)
                if prev is not None and [t.value for t in prev] != [t.value for t in part[2:]]:
                    raise SuruError(f"フィールド「{f}」の型が形ごとに違います(同じ名前のフィールドは同じ型にしてください)",
                                    part[0].line)
                field_types[f] = part[2:]
            ctors.append((cname, fields))
            continue
        if alt[:-2]:
            typed = False if typed is None else typed
            if typed:
                raise SuruError("フィールドの型は、型のすべてのフィールドに書くか、どれにも書かないかにしてください", last.line)
        for i, t in enumerate(alt[:-2]):
            if i % 2 == 1:
                if not is_kw(t, KW_TO):
                    raise SuruError("フィールド名は「と」で区切ってください", t.line)
                continue
            f = _check_name(t)
            if f in fields:
                raise SuruError(f"フィールド名「{f}」が2回書かれています", t.line)
            fields.append(f)
        if len(alt[:-2]) % 2 == 0:
            raise SuruError("「と」の後にフィールド名が必要です", last.line)
        ctors.append((cname, fields))
    return TypeDef(name, ctors, line, field_types if typed else None)


def _split_typed_fields(tokens: list[Token], line: int) -> list[list[Token]]:
    """「番号 は 数 で 名前 は 文字列」を「で」(括弧の外)で分ける"""
    out: list[list[Token]] = [[]]
    depth = 0
    for t in tokens:
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        if depth == 0 and t.kind == "PART" and t.value == "で":
            if not out[-1]:
                raise SuruError("「で」の前にフィールドを書いてください", t.line)
            out.append([])
        else:
            out[-1].append(t)
    if not out[-1]:
        raise SuruError("「で」の後にフィールドを書いてください", line)
    return out


def _function_define(stmt: Any, what: str, line: int) -> Define:
    if not isinstance(stmt, Define) or not stmt.is_function:
        raise SuruError(f"{what}には「…する とは …」の関数の定義を書いてください", line)
    return stmt


def parse_trait_decl(node: Node, name_tok: Token, after: list[Token]) -> TraitDecl:
    """「比較可能 という 性質 とは」の後に、関数の宣言(本体なし)と既定の実装を並べる"""
    name = _check_name(name_tok)
    line = node.line.number
    if nosep(after):
        members = [Node(Line(node.line.indent, after, line, node.line.closed), node.children)]
    else:
        members = node.children
    decl = TraitDecl(name, [], [], line)
    for m in members:
        if find_top_level(nosep(m.line.tokens), KW_TOWA) is not None:
            decl.defaults.append(_function_define(parse_statement(m), "性質の中", m.line.number))
            continue
        head = nosep(flatten(m))
        if head[-1].kind != "CALL" or head[-1].form != SURU:
            raise SuruError("性質の中には「a と b を 比較する」のような関数の宣言か、関数の定義を書いてください", m.line.number)
        fname, params, _ = parse_definition_head(head, m.line.number)
        decl.sigs.append((fname, params))
    return decl


def parse_trait_impl(node: Node, tokens: list[Token]) -> TraitImpl:
    """「点 は 比較可能」の下の深い行に、その型での関数を定義する"""
    impl = TraitImpl(_check_name(tokens[0]), _check_name(tokens[2]), [], node.line.number)
    for c in node.children:
        impl.defs.append(_function_define(parse_statement(c), f"「{impl.type_name} は {impl.trait}」の下", c.line.number))
    return impl


def _then(first: Any, expr: Any) -> Do:
    """「first。それから、expr。」"""
    if isinstance(first, Do) and first.sequel:
        first.statements.append(expr)
        return first
    return Do([first, expr], getattr(first, "line", 0) or 0, sequel=True)


def attach_provisos(statements: list) -> list:
    """「ただし」の定義を、直前の(ただしでない)定義の局所定義にする。
    「それから」の文は、直前の文(定義なら本体)の後に続けて行う並びにする"""
    out: list = []
    target: Any = None
    extra: dict[int, list] = {}
    for s in statements:
        if isinstance(s, Sequel):
            prev = out[-1] if out else None
            if prev is None or isinstance(prev, TOP_LEVEL_ONLY):
                raise SuruError("「それから」の前に行うことを書いてください", s.line)
            if isinstance(prev, Define):
                prev.body = _then(prev.body, s.expr)
            else:
                out[-1] = _then(prev, s.expr)
            continue
        if isinstance(s, Proviso):
            if target is None:
                raise SuruError("「ただし」の前に「…とは」の定義が必要です", s.line)
            extra.setdefault(id(target), []).append(s)
        else:
            out.append(s)
            target = s if isinstance(s, (Define, TraitDecl, TraitImpl)) else None
    for s in out:
        provisos = extra.get(id(s))
        if not provisos:
            continue
        for p in provisos:
            if p.define is None and not isinstance(s, TraitDecl):
                raise SuruError("「ただし」の後には「…とは」の定義を書いてください", p.line)
        if isinstance(s, Define):
            s.body = Block(merge_clauses([p.define for p in provisos]) + [s.body])
        elif isinstance(s, TraitDecl):
            for p in provisos:
                if p.define is None:
                    s.sigs.append(p.sig)
                else:
                    s.defaults.append(_function_define(p.define, "性質の中", p.line))
        else:
            for p in provisos:
                s.defs.append(_function_define(p.define, f"「{s.type_name} は {s.trait}」の後", p.line))
    for s in out:
        if isinstance(s, TraitImpl):
            s.defs = merge_clauses(s.defs)
        elif isinstance(s, TraitDecl):
            s.defaults = merge_clauses(s.defaults)
    return merge_clauses(out)


def try_parse_visibility(tokens: list[Token]) -> Visibility | None:
    """「a と b は 非公開とする」「a は 公開とする」なら Visibility"""
    if tokens and tokens[-1].kind == "PERIOD":
        tokens = tokens[:-1]
    if (len(tokens) < 3 or tokens[-1].kind != "CALL" or tokens[-1].value not in (VIS_PUBLIC, VIS_PRIVATE)
            or not is_kw(tokens[-2], KW_WA)):
        return None
    word = tokens[-1].value
    names = []
    for i, t in enumerate(tokens[:-2]):
        if i % 2 == 1:
            if not is_kw(t, KW_TO):
                raise SuruError(f"「{word}」の前には、名前を「と」で並べてください(「確保する と 解放する は {word}」)", t.line)
        elif t.kind in ("WORD", "CALL"):
            names.append(t.value)
        else:
            raise SuruError(f"「{word}」の前には、このファイルで定義した名前を書いてください", t.line)
    if len(tokens[:-2]) % 2 == 0:
        raise SuruError(f"「{word}」の前には、名前を「と」で並べてください(「確保する と 解放する は {word}」)", tokens[-2].line)
    return Visibility(names, word == VIS_PUBLIC, tokens[0].line)


def private_names(statements: list) -> frozenset:
    """一番外の「… は 非公開とする」「… は 公開とする」から、外から見えない名前を決める"""
    vis = [s for s in statements if isinstance(s, Visibility)]
    if not vis:
        return frozenset()
    defined = {s.name for s in statements if isinstance(s, Define)}
    public: dict[str, int] = {}
    private: dict[str, int] = {}
    for v in vis:
        for n in v.names:
            if n not in defined:
                raise SuruError(f"「{n}」はこのファイルで定義していないので、{VIS_PUBLIC if v.public else VIS_PRIVATE}にできません", v.line)
            (public if v.public else private)[n] = v.line
            if n in public and n in private:
                raise SuruError(f"「{n}」が「{VIS_PUBLIC}」と「{VIS_PRIVATE}」の両方に書かれています", v.line)
    if public:
        return frozenset(defined - set(public))
    return frozenset(private)


def parse_block(nodes: list[Node]) -> Any:
    statements = attach_provisos([parse_statement(n) for n in nodes])
    for s, n in zip(statements, nodes):
        if isinstance(s, TOP_LEVEL_ONLY):
            raise SuruError("型や性質の定義は一番外側(字下げなし)に書いてください", s.line)
    if isinstance(statements[-1], Define):
        raise SuruError("ブロックの最後は式でなければなりません", nodes[-1].line.number)
    if len(statements) == 1:
        return statements[0]
    return Block(statements)


def parse_do(nodes: list[Node], line: int) -> Do:
    statements = attach_provisos([parse_statement(n) for n in nodes])
    for s in statements:
        if isinstance(s, TOP_LEVEL_ONLY):
            raise SuruError("型や性質の定義は一番外側(字下げなし)に書いてください", s.line)
    if isinstance(statements[-1], Define):
        raise SuruError("手順の最後は定義ではなく、行うこと(式)でなければなりません", statements[-1].line)
    return Do(statements, line)


def parse_program(source: str, ctx: ParseContext | None = None) -> list:
    """プログラムを解析する。ctx を渡すと、見つけた型をそこに登録する(対話モードで使う)"""
    global _CTX
    nodes = build_layout(split_lines(source))
    ctx = ctx if ctx is not None else ParseContext()
    # 読み込むファイルを先に読む(その中の型を使えるように)
    imports: dict = {}
    for n in nodes:
        lib = extern_lib_target(n, ctx)
        if lib is not None:
            imports[id(n)] = lib
            continue
        target = import_target(n)
        if target is not None:
            imports[id(n)] = Import(load_module(target[0], ctx, n.line.number), n.line.number, target[1])
    prelude = None
    if not ctx.in_prelude and not any(isinstance(i, Import) and i.module.path == PRELUDE_PATH for i in imports.values()):
        line = _prelude_line(nodes)
        if line is not None:
            prelude = Import(load_prelude(ctx, line), line, True, auto=True)
    if _has_quasi(nodes):
        found = [i.module for i in imports.values() if isinstance(i, Import)]
        found += [m for m in ctx.session_modules if all(m.path != f.path for f in found)]
        nodes = expand_quasi(nodes, found, cache={"ctx": ctx, "nodes": nodes + ctx.session_nodes})
    test_import = None
    first_test = next((n.line.number for n in nodes if n.line.tokens and is_test_head(nosep(n.line.tokens)[0])), None)
    if first_test is not None:
        # 試験のまとまりの中では「試験」の名前(一致確認する など)を前置きなしで使える(#193)
        lib = os.path.abspath(os.path.join(LIB_DIR, TEST_LIB + SOURCE_SUFFIX))
        opened = any(isinstance(i, Import) and i.open and i.module.path == lib for i in imports.values())
        if not opened and ctx.path != lib:
            test_import = Import(load_module(TEST_LIB, ctx, first_test), first_test, True, test=True)
    modules = ({i.module.name for i in imports.values() if isinstance(i, Import)} | ({PRELUDE_NAME} if prelude else set())
               | ({test_import.module.name} if test_import else set()))
    if modules:
        _join_in_nodes(nodes, modules)
    _qualify_type_names(nodes, ctx)
    # 「3 と 4 の 点」を読むために、型の定義を先に集める(定義の順番は自由)
    tds = []
    for n in nodes:
        td = try_parse_typedef(n)
        if td is not None:
            ctx.add(td)
            tds.append(td)
    saved, _CTX = _CTX, ctx
    try:
        ctx.resolve_field_types(tds)
        statements = [imports[id(n)] if id(n) in imports else parse_statement(n) for n in nodes]
        if prelude is not None:
            statements.insert(0, prelude)
        if test_import is not None:
            statements.insert(1 if prelude is not None else 0, test_import)
        name_examples(statements)
        _check_open_imports(statements)
        _attach_externs(statements)
        _attach_exports(statements)
        statements = attach_provisos(statements)
        body = [s for s in statements if not isinstance(s, (Import, ExternLib))]
        name_unwraps(body)
        resolve_param_calls(body, frozenset())
        split_branch_runs(body)
        return statements
    finally:
        _CTX = saved


def _comment_text(line: str) -> str | None:
    """注釈だけの行なら、注釈の印とその後の空白1つを除いた中身(注釈の行でなければ None)"""
    t = line.lstrip(" \t\u3000")
    if not t or t[0] not in COMMENT_STARTS:
        return None
    t = t[1:]
    if t[:1] in (" ", "\u3000"):
        t = t[1:]
    return t.rstrip(" \t\u3000\r")


def _doc_text(lines: list, head: bool) -> str:
    """注釈の行をつないで説明にする(頭の注釈なら SPDX と Copyright の行を除く)。前後の空の行は除く"""
    out = []
    for line in lines:
        t = _comment_text(line) or ""
        if t.startswith("点検しない"):
            continue
        if head and t.startswith(("SPDX-License-Identifier:", "Copyright", "!")):
            continue
        out.append(t)
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def doc_comments(source: str, program: list) -> tuple:
    """定義の説明(#209)。(ファイルの頭の注釈, {名前: 説明}) を返す(compiler/doc.go の DocComments と同じ)。
    定義の型の宣言(なければ定義)のすぐ上に、空行をはさまずに書いた注釈の行がその説明。
    ファイルの頭の注釈(SPDX-License-Identifier と Copyright の行を除く)がファイルの説明"""
    lines = source.replace("\r\n", "\n").split("\n")
    head_end = 0
    while head_end < len(lines) and _comment_text(lines[head_end]) is not None:
        head_end += 1
    module = _doc_text(lines[:head_end], True) if head_end else ""
    first: dict = {}

    def add(n: Any) -> None:
        if isinstance(n, Block):
            for s in n.statements:
                add(s)
            return
        if isinstance(n, Define):
            if n.test or n.name.startswith("\x00"):
                return
        elif not isinstance(n, (TypeSig, TypeDef, TraitDecl)):
            return
        line = int(n.line or 0)
        if not n.name or line <= 0:
            return
        if n.name not in first or line < first[n.name]:
            first[n.name] = line

    for s in program:
        add(s)
    names = {}
    for name, line in first.items():
        idx = line - 1
        if idx > len(lines):
            continue
        start = idx
        while start > 0 and _comment_text(lines[start - 1]) is not None:
            start -= 1
        if start == idx or start == 0:  # 上の注釈がファイルの頭まで続いていれば、それはファイルの説明
            continue
        d = _doc_text(lines[start:idx], False)
        if d:
            names[name] = d
    return module, names


DOC_KIND_FUNCTION, DOC_KIND_VALUE, DOC_KIND_TYPE, DOC_KIND_TRAIT = "関数", "値", "型", "性質"


def _statement_text(lines: list, line: int) -> str:
    """line(1 から)から始まる一番外の文の字句: その行と、続く字下げした行(compiler/doc.go の statementText と同じ)"""
    if line < 1 or line > len(lines):
        return ""
    first = lines[line - 1]
    t = first.lstrip(" \t\u3000")
    if t != first:  # まとまり(以下は外部の…です)の中の行は、その1行だけ
        return t.rstrip(" \t\r")
    out = [first.rstrip(" \t\r")]
    for ln in lines[line:]:
        if not ln.strip() or not ln.startswith((" ", "\t", "\u3000")) or _comment_text(ln) is not None:
            break
        out.append(ln.rstrip(" \t\r"))
    return "\n".join(out)


def _doc_usage(name: str, params: list) -> str:
    """引数の並びから「n を 三倍する」のような使い方を作る(compiler/analyze.go の usage と同じ)"""
    def short(n: str) -> str:  # 「表内の」を除き、外部の関数のまとまりで付けた「引数1」などは「…」にする
        n = n.rpartition(MODULE_SEP)[2]
        # 「（を）」は場合ごとの定義をまとめたときの引数
        return "…" if re.fullmatch(r"引数[0-9]+", n) or n.startswith("（") else n

    out = ""
    for part, pat in params:
        if isinstance(pat, str):
            out += short(pat)
        elif isinstance(pat, list) and all(isinstance(x, str) for x in pat):
            out += f" {KW_TO} ".join(short(x) for x in pat)
        else:
            out += "…"
        out += f" {part} "
    return out + name


def _doc_param_simple(pat: Any) -> bool:
    return isinstance(pat, str) or (isinstance(pat, list) and all(isinstance(x, str) for x in pat))


def document(source: str, program: list, private: frozenset = frozenset()) -> dict:
    """解析したプログラムから API ドキュメントを作る(#209、compiler/doc.go の Document と同じ)"""
    lines = source.replace("\r\n", "\n").split("\n")
    module, descs = doc_comments(source, program)
    items: list = []
    index: dict = {}

    def item(name: str, line: int) -> dict:
        if name in index:
            it = items[index[name]]
            it["line"] = min(it["line"], line)
            return it
        index[name] = len(items)
        items.append({"name": name, "kind": "", "line": line, "signature": "", "usage": "",
                      "description": descs.get(name, ""), "examples": []})
        return items[-1]

    examples = []

    def add(n: Any) -> None:
        if isinstance(n, Block):
            for s in n.statements:
                add(s)
        elif isinstance(n, Define):
            if n.example is not None and n.test:
                examples.append(n)
                return
            if n.test or n.name.startswith("\x00") or n.name in private:
                return
            it = item(n.name, int(n.line))
            if n.is_function:
                it["kind"] = DOC_KIND_FUNCTION
                simple = all(_doc_param_simple(p) for _, p in n.params)
                if not it["usage"] or (simple and "…" in it["usage"]):
                    it["usage"] = _doc_usage(n.name, n.params)
            elif not it["kind"]:
                it["kind"] = DOC_KIND_VALUE
        elif isinstance(n, TypeSig):
            if n.name in private:
                return
            it = item(n.name, int(n.line))
            it["signature"] = _statement_text(lines, int(n.line))
            if n.params is not None:
                it["kind"] = DOC_KIND_FUNCTION
            elif not it["kind"]:
                it["kind"] = DOC_KIND_VALUE
        elif isinstance(n, TypeDef):
            it = item(n.name, int(n.line))
            it["kind"], it["signature"] = DOC_KIND_TYPE, _statement_text(lines, int(n.line))
        elif isinstance(n, TraitDecl):
            it = item(n.name, int(n.line))
            it["kind"], it["signature"] = DOC_KIND_TRAIT, _statement_text(lines, int(n.line))

    for s in program:
        add(s)
    for x in examples:
        name = x.test[: -len("の例")] if x.test.endswith("の例") else x.test
        if name in index:
            items[index[name]]["examples"].append(_statement_text(lines, int(x.line)))
    items.sort(key=lambda it: it["line"])
    return {"file": "", "module": "", "description": module, "items": items}


def document_file(path: str) -> dict:
    """path のファイルを解析して、公開の名前の API ドキュメントを作る"""
    with open(path, encoding="utf-8") as f:
        source = f.read()
    ctx = ParseContext(base_dir=os.path.dirname(os.path.abspath(path)), path=path)
    program = parse_program(source, ctx)
    d = document(source, program, private_names(program))
    d["file"] = path
    d["module"] = os.path.basename(path)[: -len(".suru")] if path.endswith(".suru") else os.path.basename(path)
    return d


def doc_markdown(d: dict) -> str:
    """API ドキュメントを Markdown(MyST でも読める形)にする"""
    out = f"# 「{d['module']}」\n"
    if d["description"]:
        out += "\n" + d["description"] + "\n"
    for it in d["items"]:
        out += "\n## " + it["name"] + "\n"
        if it["signature"]:
            out += "\n```suru\n" + it["signature"] + "\n```\n"
        if it["usage"]:
            out += "\nUsage: `" + it["usage"] + "`\n"
        if it["description"]:
            out += "\n" + it["description"] + "\n"
        if it["examples"]:
            out += "\nExamples:\n\n```suru\n" + "\n".join(it["examples"]) + "\n```\n"
    return out


def doc_json(d: dict) -> str:
    import json

    return json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n"


DOC_USAGE = "使い方: --文書 [--json] [--出力 フォルダ] ファイルかフォルダ …"


def doc_command(args: list) -> int:
    """「suru --文書 …」(#209): ファイル(フォルダなら中の .suru)の公開の名前の API ドキュメントを、
    Markdown(--json なら1ファイル1行の JSON)で出す。--出力 があれば、ファイルごとに「名前.md」(「名前.json」)を書く"""
    as_json, out, paths = False, "", []
    i = 0
    while i < len(args):
        a = args[i]
        if a in JSON_FLAGS:
            as_json = True
        elif a in ("--出力", "--out", "-o"):
            if i + 1 >= len(args):
                print(DOC_USAGE, file=sys.stderr)
                return 2
            out = args[i + 1]
            i += 1
        elif a.startswith("--"):
            print(DOC_USAGE, file=sys.stderr)
            return 2
        else:
            paths.append(a)
        i += 1
    files = []
    for p in paths:
        if not os.path.exists(p):
            print(f"「{p}」が見つかりません", file=sys.stderr)
            print(DOC_USAGE, file=sys.stderr)
            return 2
        if os.path.isdir(p):
            files += sorted(os.path.join(p, n) for n in os.listdir(p)
                            if n.endswith(".suru") and os.path.isfile(os.path.join(p, n)))
        else:
            files.append(p)
    if not files:
        print(DOC_USAGE, file=sys.stderr)
        return 2
    if out:
        os.makedirs(out, exist_ok=True)
    status, first = 0, True
    for f in files:
        try:
            d = document_file(f)
        except SuruError as e:
            if as_json:
                print(error_json(e, "構文", f), file=sys.stderr)
            else:
                with open(f, encoding="utf-8") as fh:
                    print(f + ": " + format_error(e, fh.read()), file=sys.stderr)
            status = 1
            continue
        text, ext = (doc_json(d), ".json") if as_json else (doc_markdown(d), ".md")
        if out:
            with open(os.path.join(out, d["module"] + ext), "w", encoding="utf-8") as fh:
                fh.write(text)
            continue
        if not first and not as_json:
            sys.stdout.write("\n")
        first = False
        sys.stdout.write(text)
    return status


def short_type_name(name: str) -> str:
    """表示する型と形の名前: 読み込んだファイルの前置き(「部品内の」)を除く"""
    return name.rpartition(MODULE_SEP)[2]


def _is_lib_path(path: str) -> bool:
    return os.path.dirname(os.path.abspath(path)) == os.path.abspath(LIB_DIR)


def _qualify_type_names(nodes: list, ctx: ParseContext) -> None:
    """型と形の名前は、ファイルごとに分ける。読み込んだファイル(lib/ のものを除く)の型「点」は、中では「点」、
    外では「部品内の点」が本当の名前。外でも、ほかのファイルの型とぶつからなければ「点」と書ける。
    字句の名前を本当の名前に置きかえる(ぶつかる名前を前置きなしで書いたらエラー)"""
    own: dict[str, str] = {}
    for n in nodes:
        td = try_parse_typedef(n)
        if td is not None:
            for name in [td.name] + [c for c, _ in td.ctors]:
                own[name] = ctx.qualify + name
    candidates: dict[str, dict] = {}  # 前置きなしの名前 → {本当の名前: それを持つファイルの名前}
    full: dict[str, str] = {}  # 「部品内の点」 → 本当の名前
    for m in ctx.modules.values():
        if m is None:
            continue
        for s in m.program:
            if isinstance(s, TypeDef):
                for canon in [s.name] + [c for c, _ in s.ctors]:
                    name = short_type_name(canon)
                    full[m.name + MODULE_SEP + name] = canon
                    candidates.setdefault(name, {}).setdefault(canon, m.name)
    short = {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}
    owners = {k: list(v.values()) for k, v in candidates.items() if len(v) > 1}
    if not own and not short and not full:
        return
    # 変数や引数の名前にした語は、2つのファイルにある型の名前でも変数の名前として読む(#105)
    local = _local_names(nodes)

    def fix(tokens: list) -> list:
        out = []
        for t in tokens:
            if t.kind == "WORD":
                v = t.value
                canon = own.get(v)
                if canon is None and v in owners and v not in local:
                    names = "と".join(f"「{x}」" for x in owners[v])
                    raise SuruError(f"「{v}」は{names}の両方にある型か形の名前です。「{owners[v][0]}{MODULE_SEP}{v}」のように"
                                    "ファイルの名前を付けて書いてください", t.line)
                if canon is None:
                    canon = short.get(v) or full.get(v)
                if canon is not None and (canon != v or MODULE_SEP in canon):
                    t = Token(t.kind, canon, t.line, t.form, t.quoted, t.negated, MODULE_SEP in canon)
            out.append(t)
        return out

    def walk(ns: list) -> None:
        for n in ns:
            n.line.tokens = fix(n.line.tokens)
            walk(n.children)

    walk(nodes)


def _local_names(nodes: list) -> set:
    """ファイルの中で変数や引数の名前にした語: 「x とは …」の x と、「s に x を 接続 で 案内する とは …」の
    助詞の前の名前(括弧の外のもの)"""
    names: set = set()

    def visit(ns: list) -> None:
        for n in ns:
            toks = [t for t in n.line.tokens if t.kind != "SEP"]
            if toks and is_kw(toks[0], KW_PROVISO):
                toks = toks[1:]
            depth = 0
            for k, t in enumerate(toks):
                if t.kind == "LP":
                    depth += 1
                elif t.kind == "RP":
                    depth -= 1
                elif depth == 0 and is_kw(t, KW_TOWA):
                    head = toks[:k]
                    if len(head) == 1 and head[0].kind == "WORD":
                        names.add(head[0].value)
                    elif head and head[-1].kind == "CALL":
                        d = 0
                        for j, h in enumerate(head):
                            d += (h.kind == "LP") - (h.kind == "RP")
                            if d == 0 and h.kind == "WORD" and j + 1 < len(head) and head[j + 1].kind == "PART":
                                names.add(h.value)
                    break
            visit(n.children)

    visit(nodes)
    return names


def _prelude_line(nodes: list) -> int | None:
    """基本(成否・有無)の名前を書いた最初の行(なければ None。基本.suru そのものなら None)"""
    if any(td is not None and td.name in PRELUDE_TYPES for td in map(try_parse_typedef, nodes)):
        return None
    return _prelude_word_line(nodes)


def _prelude_word_line(nodes: list) -> int | None:
    for n in nodes:
        for k, t in enumerate(n.line.tokens):
            if t.kind in ("WORD", "CALL") and not t.quoted and (
                    t.value in PRELUDE_WORDS or t.value in PRELUDE_CALLS
                    or t.value.startswith(PRELUDE_NAME + MODULE_SEP)
                    # 「無」は「… は 無」なら外部の関数の型(C の void)
                    or t.value == PRELUDE_NONE and not (k > 0 and is_kw(n.line.tokens[k - 1], KW_WA))
                    # 「で」のない「試行する」は成否を返す
                    or t.kind == "CALL" and t.value == PRELUDE_TRY
                    and not any(u.kind == "PART" and u.value == "で" for u in n.line.tokens)):
                return n.line.number
        line = _prelude_word_line(n.children)
        if line is not None:
            return line
    return None


def load_prelude(ctx: ParseContext, line: int) -> Module:
    """lib/基本.suru を読む(同じフォルダに 基本.suru があっても、いつも同梱のもの)"""
    if PRELUDE_PATH in ctx.modules and ctx.modules[PRELUDE_PATH] is not None:
        return ctx.modules[PRELUDE_PATH]
    LIBRARY_SRCS.add(PRELUDE_PATH)
    return _load_path(PRELUDE_PATH, PRELUDE_NAME, ctx, line, prelude=True)


def module_names(module: Module) -> set:
    """読み込んだファイルの一番外の名前(標準ライブラリなら組み込みも)"""
    names = {s.name for s in module.program if isinstance(s, Define)} - module.private
    names |= {b.name for b in LIB_PRIMITIVES.get(module.path, ())}
    return names


def _check_open_imports(statements: list) -> None:
    """「読み込んで 使う」の2つのファイルに同じ名前があれば、自分で定義していない限りエラー"""
    own = {s.name for s in statements if isinstance(s, Define)}
    seen: dict[str, str] = {}
    for s in statements:
        if isinstance(s, Import) and s.open:
            for name in sorted(module_names(s.module) - own):
                if name in seen and seen[name] != s.module.name:
                    raise SuruError(
                        f"「{name}」は「{seen[name]}」と「{s.module.name}」の両方にあります。"
                        f"「{s.module.name}{MODULE_SEP}{name}」のように前置きを付けて使うか、片方を「{KW_IMPORT}」にしてください",
                        s.line)
                seen[name] = s.module.name


def _join_in_nodes(nodes: list, modules: set) -> None:
    for n in nodes:
        n.line.tokens = join_module_names(n.line.tokens, modules)
        _join_in_nodes(n.children, modules)


_QUASI_RECORD: tuple | None = None  # 「--展開」: (調べるファイルの ParseContext, [(頭の行, 以上の行, 展開したソース, 式なら字下げ)])


def expand_source(source: str, base_dir: str, path: str) -> str:
    """「suru --展開」: 準クォートを展開したソース(展開したコードの中の準クォートも展開したもの)"""
    global _QUASI_RECORD
    ctx = ParseContext(base_dir=base_dir, path=path)
    _QUASI_RECORD = (ctx, [])
    try:
        parse_program(source, ctx)
        record = list(_QUASI_RECORD[1])
    finally:
        _QUASI_RECORD = None
    raws = source.splitlines()
    out: list[str] = []
    k = 0
    for start, end, src, indent in sorted(record):
        out.extend(raws[k : start - 1])
        if indent is None:
            out.extend(src.splitlines())
        else:
            head = raws[start - 1]
            out.append(head[: head.find("とは") + 2] if "とは" in head else head)
            pad = " " * (indent + 2)
            out.extend(pad + x if x.strip() else x for x in src.splitlines())
        k = end
    out.extend(raws[k:])
    return "\n".join(out) + "\n"


def _has_quasi(nodes: list) -> bool:
    return any(n.line.quasi is not None or n.line.derive is not None or _has_quasi(n.children) for n in nodes)


def find_expander(name: str, modules: list, line: int, derive: bool = False) -> tuple:
    """【name】の展開の関数「name展開する」(derive なら導出の関数「name導出する」)を、読み込んだファイルから探す。
    (ファイル, 関数の名前)"""
    fname = name + (DERIVE_SUFFIX if derive else QUASI_SUFFIX)
    kind, arg = ("導出", "型記述") if derive else ("展開", "文字列")
    found = [m for m in modules
             if fname not in m.private and any(isinstance(d, Define) and d.name == fname for d in m.program)]
    if not found:
        raise SuruError(f"【{name}】の{kind}の関数「{fname}」が、読み込んだファイルにありません"
                        f"(「{arg} を {fname} は 文字列 の 成否」を定義したファイルを読み込んでください)", line)
    if len(found) > 1:
        names = "と".join(f"「{m.name}」" for m in found)
        raise SuruError(f"【{name}】の{kind}の関数「{fname}」が{names}の両方にあります", line)
    return found[0], fname


def run_expander(name: str, body: str, modules: list, line: int, cache: dict) -> str:
    """【name】の中身 body を展開の関数に渡し、返した する のソースを返す(インタプリタで動かす)"""
    module, fname = find_expander(name, modules, line)
    it = cache.get("interp")
    if it is None:
        it = cache["interp"] = Interpreter()
        if "ctx" in cache:
            it.ctx = cache["ctx"].copy()  # 読み込んだファイルの型(成否 など)
    try:
        env = it.load_module(module)
        v = it.perform(it.call(env.vars[fname], {WO: body}, line))
    except SuruError as e:
        raise SuruError(f"【{name}】の展開の関数「{fname}」が止まりました: {e.message}", line) from None
    return quasi_result(name, fname, v, line)


def run_deriver(tname: str, name: str, desc: Record, modules: list, line: int, cache: dict) -> str:
    """「tname は 【name】 を 導出する」: 型の記述 desc を導出の関数に渡し、返した する のソースを返す"""
    module, fname = find_expander(name, modules, line, derive=True)
    it = cache.get("interp")
    if it is None:
        it = cache["interp"] = Interpreter()
        if "ctx" in cache:
            it.ctx = cache["ctx"].copy()
    try:
        env = it.load_module(module)
        v = it.perform(it.call(env.vars[fname], {WO: desc}, line))
    except SuruError as e:
        raise SuruError(f"【{name}】の導出の関数「{fname}」が止まりました: {e.message}", line) from None
    if isinstance(v, Record) and v.type_name == "成否" and len(v.values) == 1 and isinstance(v.values[0], str):
        if v.ctor == "成功":
            return v.values[0]
        if v.ctor == "失敗":
            raise SuruError(f"【{name}】で「{tname}」を導出できません: {v.values[0]}", line)
    raise SuruError(f"【{name}】の導出の関数「{fname}」は「文字列 の 成否」を返してください", line)


def _type_text(t: Any) -> str:
    """型の書き方(lib/導出.suru の 型式文にする と同じ)"""
    if isinstance(t, TypeVarName):
        return t.name
    if isinstance(t, TypeName):
        if not t.args:
            return t.name
        if len(t.args) == 1:
            a = t.args[0]
            inner = _type_text(a)
            return (f"（{inner}）" if isinstance(a, TypeName) and a.args else inner) + f" の {t.name}"
        return "（" + " と ".join(_type_text(a) for a in t.args) + f"） の {t.name}"
    ps = " ".join(f"{_type_text(pt)} {p}" for p, pt in t.params)
    return f"（{ps} 受け取って {_type_text(t.result)} を 返すこと）"


def _type_form(t: Any) -> Record:
    """型を 型式 の値にする(lib/導出.suru)"""
    if isinstance(t, TypeVarName):
        return Record("名型", "型式", ("型式名", "型式引数"), (t.name, ()))
    if isinstance(t, TypeName):
        return Record("名型", "型式", ("型式名", "型式引数"), (t.name, tuple(_type_form(a) for a in t.args)))
    return Record("他型", "型式", ("型式文",), (_type_text(t),))


def _type_vars_of(t: Any, out: list) -> None:
    if isinstance(t, TypeVarName):
        if t.name not in out:
            out.append(t.name)
    elif isinstance(t, TypeName):
        for a in t.args:
            _type_vars_of(a, out)
    elif isinstance(t, TypeFun):
        for _, pt in t.params:
            _type_vars_of(pt, out)
        _type_vars_of(t.result, out)


def type_description(tname: str, scopes: list, line: int, ctx: "ParseContext | None" = None) -> Record:
    """「tname は 【X】 を 導出する」の tname の型の記述(型記述 の値)。型は同じファイルで定義したもの"""
    global _CTX
    tds = [d for nodes in scopes for n in nodes if n.line.quasi is None and n.line.derive is None
           for d in [try_parse_typedef(n)] if d is not None]
    td = next((d for d in tds if d.name == tname), None)
    if td is None:
        raise SuruError(f"「{tname}」の型の定義がこのファイルにありません(導出できるのは同じファイルで定義した型です)", line)
    if td.field_types is None and any(fs for _, fs in td.ctors):
        raise SuruError(f"「{tname}」のフィールドに型が書かれていないので導出できません"
                        f"(「{tname} とは 番号 は 数 で 名前 は 文字列 の 組」のように書きます)", line)
    # 型の名前を確かめるために、このファイルの型を(まだ集めていないので)ここで集める
    saved = _CTX
    _CTX = (ctx or ParseContext()).copy()
    for d in tds:
        _CTX.types.setdefault(d.name, [c for c, _ in d.ctors])
    try:
        types = {f: parse_type_all(toks, td.line) for f, toks in (td.field_types or {}).items()}
    finally:
        _CTX = saved
    tvars: list = []
    ctors = []
    for cname, fields in td.ctors:
        fs = []
        for f in fields:
            _type_vars_of(types[f], tvars)
            fs.append(Record("欄記述", "欄記述", ("欄名", "欄型"), (f, _type_form(types[f]))))
        ctors.append(Record("形記述", "形記述", ("形名", "欄群"), (cname, tuple(fs))))
    return Record("型記述", "型記述", ("型名", "型引数", "形群"), (tname, tuple(tvars), tuple(ctors)))


def description_source(r: Any) -> str:
    """型の記述の値を、する の式のソースにする(Go 版が導出の関数を動かすプログラムに書く。ここでは試験で比べる)"""
    if isinstance(r, str):
        return "「" + r + "」"
    if isinstance(r, tuple):
        if not r:
            return "空"
        if len(r) == 1:
            return "（" + description_source(r[0]) + " を 空 に 挿入する）"
        return "（" + " と ".join(description_source(x) for x in r) + "）"
    return "（" + " で ".join(f"{f} は {description_source(v)}" for f, v in zip(r.fields, r.values)) + f" の {r.ctor}）"


def quasi_result(name: str, fname: str, v: Any, line: int) -> str:
    """展開の関数の値(文字列 の 成否)から、する のソースを取り出す。失敗ならエラー"""
    if isinstance(v, Record) and v.type_name == "成否" and len(v.values) == 1:
        msg = v.values[0]
        if v.ctor == "成功" and isinstance(msg, str):
            return msg
        if v.ctor == "失敗" and isinstance(msg, str):
            m = re.match(r"^([0-9]+)行目[:：][ \t　]*(.*)$", msg, re.S)
            if m:  # 「2行目: …」は中身の2行目(頭の行の次から数える)
                raise SuruError(f"【{name}】の{m.group(1)}行目: {m.group(2)}", Pos(int(line) + int(m.group(1))))
            raise SuruError(f"【{name}】: {msg}", line)
    raise SuruError(f"【{name}】の展開の関数「{fname}」は「文字列 の 成否」を返してください", line)


def expand_quasi(nodes: list, modules: list, depth: int = 0, cache: dict | None = None, top: bool = True) -> list:
    """準クォートを、展開の関数が返した する のコードに置きかえる。一番外の「以下は【道】です」は文の並びに、
    「x とは 以下の【SQL】です」は x の式になる。展開したコードの中の準クォートも展開する"""
    cache = {} if cache is None else cache
    out: list = []
    for n in nodes:
        if n.line.derive is not None:
            out.extend(_expand_derive(n, nodes, modules, depth, cache, top))
            continue
        q = n.line.quasi
        if q is None:
            n.children = expand_quasi(n.children, modules, depth, cache, False)
            out.append(n)
            continue
        toks = n.line.tokens
        name, line = toks[-1].value, n.line.number
        if depth >= QUASI_MAX_DEPTH:
            raise SuruError(f"【{name}】の展開が深すぎます(展開したコードの中の準クォートが{QUASI_MAX_DEPTH}回続きました)", line)
        if len(toks) == 1 and not top:
            raise SuruError(f"「以下は【{name}】です」は一番外(字下げなし)にだけ書けます", line)
        src = run_expander(name, q, modules, line, cache)
        if depth == 0 and _QUASI_RECORD is not None and cache.get("ctx") is not None and cache["ctx"] is _QUASI_RECORD[0]:
            _QUASI_RECORD[1].append((int(line), n.line.quasi_end, src, None if len(toks) == 1 else n.line.indent))
        made = build_layout(split_lines(src, int(line))) if src.strip() else []
        made = expand_quasi(made, modules, depth + 1, cache, len(toks) == 1)
        if len(toks) == 1:
            for m in made:
                if import_target(m) is not None:
                    raise SuruError(f"【{name}】の展開したコードには、読み込みの文を書けません", line)
            out.extend(made)
            continue
        # 「x とは 以下の【SQL】です」: 展開したものを式として x の定義の本体にする
        head = toks[:-1]
        if len(made) == 1 and not made[0].children:
            n.line = Line(n.line.indent, head + [Token("LP", "(", line)] + made[0].line.tokens + [Token("RP", ")", line)],
                          line, n.line.closed)
        elif made:
            n.line = Line(n.line.indent, head, line, n.line.closed)
            n.children = _reindent(made, n.line.indent + 2)
        else:
            raise SuruError(f"【{name}】の展開の関数が空のコードを返しました(式の場所には式が要ります)", line)
        out.append(n)
    return out


def _expand_derive(n: Node, scope: list, modules: list, depth: int, cache: dict, top: bool) -> list:
    """「会員 は 【JSON】 と 【表】 を 導出する」を、導出の関数が返した定義にする"""
    tname, line = n.line.tokens[0].value, n.line.number
    names = n.line.derive
    label = "】 と 【".join(names)
    if not top or n.line.indent:
        raise SuruError(f"「{tname} は 【{label}】 を 導出する」は一番外(字下げなし)にだけ書けます", line)
    if depth >= QUASI_MAX_DEPTH:
        raise SuruError(f"【{names[0]}】の展開が深すぎます(展開したコードの中の準クォートが{QUASI_MAX_DEPTH}回続きました)", line)
    desc = type_description(tname, [scope, cache.get("nodes", [])], line, cache.get("ctx"))
    srcs = [run_deriver(tname, x, desc, modules, line, cache) for x in names]
    src = "\n".join(x.rstrip("\n") for x in srcs if x.strip())
    if depth == 0 and _QUASI_RECORD is not None and cache.get("ctx") is not None and cache["ctx"] is _QUASI_RECORD[0]:
        _QUASI_RECORD[1].append((int(line), int(line), src, None))
    made = build_layout(split_lines(src, int(line))) if src.strip() else []
    made = expand_quasi(made, modules, depth + 1, cache, True)
    for m in made:
        if import_target(m) is not None:
            raise SuruError(f"【{names[0]}】の導出したコードには、読み込みの文を書けません", line)
    return made


def _reindent(nodes: list, base: int) -> list:
    """展開した行の字下げを base からにする(字下げの差はそのまま)"""
    if not nodes:
        return nodes
    shift = base - nodes[0].line.indent

    def walk(ns: list) -> None:
        for m in ns:
            m.line.indent += shift
            walk(m.children)

    walk(nodes)
    return nodes


def import_target(node: Node) -> tuple[str, bool] | None:
    """「「数学」 を 読み込む」なら読み込むファイルの名前(「数学」)と、「読み込んで 使う」か"""
    tokens = nosep(flatten(node))
    if tokens and tokens[-1].kind == "PERIOD":
        tokens = tokens[:-1]
    if not any(is_kw(t, w) for t in tokens for w in (KW_IMPORT, KW_IMPORT_POLITE, KW_IMPORT_TE)):
        return None
    tail = [t.value if t.kind == "KW" else None for t in tokens[2:]]
    if (tail not in ([KW_IMPORT], [KW_IMPORT_POLITE], [KW_IMPORT_TE, KW_USE], [KW_IMPORT_TE, KW_USE_POLITE])
            or tokens[0].kind != "STR" or not (tokens[1].kind == "PART" and tokens[1].value == WO)
            or node.line.indent):
        raise SuruError(f"ファイルは一番外に「「数学」 を {KW_IMPORT}」か「「数学」 を {KW_IMPORT_TE} {KW_USE}」のように書いて読み込みます",
                        tokens[0].line)
    return tokens[0].value, len(tail) == 2


def extern_lib_target(node: Node, ctx: ParseContext) -> ExternLib | None:
    """「外部の「m」 を 読み込む」なら ExternLib"""
    tokens = nosep(flatten(node))
    if tokens and tokens[-1].kind == "PERIOD":
        tokens = tokens[:-1]
    if not tokens or not (tokens[0].kind == "WORD" and tokens[0].value == KW_EXTERN and not tokens[0].quoted):
        return None
    main_thread = len(tokens) == 5 and tokens[3].kind == "WORD" and tokens[3].value == KW_MAIN_THREAD and not tokens[3].quoted
    if main_thread:
        tokens = tokens[:3] + tokens[4:]
    if (len(tokens) != 4 or tokens[1].kind != "STR" or not (tokens[2].kind == "PART" and tokens[2].value == WO)
            or not (is_kw(tokens[3], KW_IMPORT) or is_kw(tokens[3], KW_IMPORT_POLITE)) or node.line.indent):
        raise SuruError(f"外部のライブラリは一番外に「{KW_EXTERN}「m」 を {KW_IMPORT}」"
                        f"(主スレッドで呼ぶなら「{KW_EXTERN}「m」 を {KW_MAIN_THREAD} {KW_IMPORT}」)のように書いて読み込みます", tokens[0].line)
    name = tokens[1].value
    if not name:
        raise SuruError("外部のライブラリの名前が空です", tokens[0].line)
    path = name
    if "/" in name or name.endswith((".so", ".dylib")):
        path = os.path.abspath(os.path.join(ctx.base_dir, name))
    return ExternLib(name, path, tokens[0].line, main_thread)


def _ffi_type(te: Any, sig: TypeSig, what: str) -> str:
    result = what == "値"
    names = [n for n, t in FFI_TYPES.items() if t != ("bytes" if result else "void")]
    if isinstance(te, TypeName) and not te.args and te.name in names:
        return FFI_TYPES[te.name]
    raise SuruError(f"外部の関数「{sig.name}」の{what}には {'・'.join(names)} のどれかの型を書いてください", sig.line)


def _parse_extern_args(inner: list, lp: Token) -> list:
    """「（a と 0 と b）」の中: 引数の名前か整数を「と」でつないだもの"""
    def bad(t: Token) -> SuruError:
        return SuruError("外部の関数の引数の並びには、引数の名前か整数を「と」でつないで書きます(「（a と 0 と b）」)", t.line)
    if not inner:
        raise bad(lp)
    out: list = []
    for i, t in enumerate(inner):
        if i % 2 == 1:
            if not (t.kind == "KW" and t.value == KW_TO) or i == len(inner) - 1:
                raise bad(t)
            continue
        if t.kind == "WORD" and not t.quoted and t.value != KW_EXTERN:
            out.append(("名前", t.value, t.line))
        elif t.kind == "NUM" and type(t.value) is int and INT64_MIN <= t.value <= INT64_MAX:
            out.append(("定数", t.value, t.line))
        else:
            raise bad(t)
    return out


def _attach_externs(statements: list) -> None:
    """外部の関数の定義に、同じファイルのライブラリと型の宣言(C の型)を付ける"""
    libs = [s.path for s in statements if isinstance(s, ExternLib)]
    main_thread = any(s.main_thread for s in statements if isinstance(s, ExternLib))
    sigs = {s.name: s for s in statements if isinstance(s, TypeSig)}
    seen: dict[str, str] = {}
    for d in statements:
        if not (isinstance(d, Define) and isinstance(d.body, Extern)):
            continue
        ext = d.body
        sig = sigs.get(d.name)
        if not d.is_function or sig is None or sig.params is None:
            raise SuruError(f"外部の関数「{d.name}」には型の宣言が必要です(「小数 を 余弦にする は 小数」のように書きます)", d.line)
        types = dict(sig.params)
        if sorted(types) != sorted(p for p, _ in d.params):
            raise SuruError(f"「{d.name}」の型の宣言の助詞が定義の助詞と違います", d.line)
        for p, pat in d.params:
            if not isinstance(pat, str):
                raise SuruError(f"外部の関数「{d.name}」の引数は名前だけで書いてください", d.line)
        ext.params = [_ffi_type(types[p], sig, f"「{p}」") for p, _ in d.params]
        if ext.cargs:
            names = [x for _, x in d.params]
            cargs = []
            for kind, v, line in ext.cargs:
                if kind == "名前":
                    if v not in names:
                        raise SuruError(f"「{v}」は「{d.name}」の引数ではありません", line)
                    cargs.append(("引数", names.index(v)))
                else:
                    cargs.append(("定数", v))
            for i, x in enumerate(names):
                if ("引数", i) not in cargs:
                    raise SuruError(f"外部の関数「{d.name}」の引数「{x}」を C に渡していません(「（…）」の中に書きます)", d.line)
            ext.cargs = cargs
        if ext.pointer:
            names = [x for _, x in d.params]
            if ext.pointer not in names:
                raise SuruError(f"「外部の（{ext.pointer}）」の「{ext.pointer}」は「{d.name}」の引数ではありません", ext.line)
            if ext.params[names.index(ext.pointer)] != "ptr":
                raise SuruError(f"「外部の（{ext.pointer}）」の「{ext.pointer}」は型の宣言で 番地 にしてください", ext.line)
        result = sig.result
        if isinstance(result, TypeName) and result.name == "動作":
            ext.action = True
            result = result.args[0]
        ext.result = _ffi_type(result, sig, "値")
        ext.libs = libs
        ext.main_thread = main_thread
        if ext.pointer:
            continue
        if ext.symbol in seen:
            raise SuruError(f"外部の関数「{ext.symbol}」が2回定義されています(「{seen[ext.symbol]}」と「{d.name}」)", d.line)
        seen[ext.symbol] = d.name


# 外部に出す C の名前に使えない頭(実行時ライブラリと IR の名前)
EXPORT_RESERVED = ("rt_", "suru_", "gc_")
# 外部に出す関数で、C の値でそのまま渡せる型(無は値だけ)
EXPORT_TYPE_NAMES = ("数", "小数", "単精度", "整数", "真偽", "文字列", "番地", "バイト列", "無")
# 外部に出す関数に使えるリストの型(要素の型 → 型の名前、#208 段階3)。C では番地と長さの2つで渡す
EXPORT_LIST_TYPES = {"数": "list_i64", "小数": "list_f64", "文字列": "list_str"}


def _export_type(te: Any, e: Export, what: str) -> str:
    """出す関数の引数・値の型 → C での渡し方。数などはそのまま、数・小数・文字列のリストとバイト列は番地と長さ、
    ほかの型(組・ほかのリスト・関数など)は中を見ない手札(val)で渡す(#208 段階3)"""
    if isinstance(te, TypeName) and not te.args and te.name in EXPORT_TYPE_NAMES:
        if te.name == "無" and what != "値":
            raise SuruError(f"外部に出す関数「{e.name}」の{what}に 無 は使えません(無 は値だけに書けます)", e.line)
        return FFI_TYPES[te.name]
    if (isinstance(te, TypeName) and te.name == "リスト" and len(te.args) == 1 and isinstance(te.args[0], TypeName)
            and not te.args[0].args and te.args[0].name in EXPORT_LIST_TYPES):
        return EXPORT_LIST_TYPES[te.args[0].name]
    return "val"


def _attach_exports(statements: list) -> None:
    """「以下は外部に出す関数です」の行に、同じファイルの型の宣言から C の型を付ける(#208、Go 版の attachExports と同じ)"""
    sigs = {s.name: s for s in statements if isinstance(s, TypeSig)}
    defs = {s.name: s for s in statements if isinstance(s, Define)}
    externs = {s.body.symbol for s in statements if isinstance(s, Define) and isinstance(s.body, Extern)}
    for e in statements:
        if not isinstance(e, Export):
            continue
        sym = e.symbol
        if not sym.isascii() or not (sym[:1].isalpha() or sym[:1] == "_") or not all(c.isalnum() or c == "_" for c in sym):
            raise SuruError(f"「{sym}」は C の名前にできません(英字か「_」で始まり、英字・数字・「_」だけで書きます)", e.line)
        for r in EXPORT_RESERVED:
            if sym.startswith(r):
                raise SuruError(f"C の名前「{sym}」は「{r}」で始まるので使えません(実行時ライブラリの名前とぶつかります)", e.line)
        if sym == "main":
            raise SuruError("C の名前「main」は使えません", e.line)
        if sym in externs:
            raise SuruError(f"C の名前「{sym}」は、このファイルで読み込む外部の関数と同じです", e.line)
        d = defs.get(e.name)
        if d is None:
            raise SuruError(f"「{e.name}」はこのファイルで定義していないので、外部に出せません", e.line)
        if isinstance(d.body, Extern):
            raise SuruError(f"「{e.name}」は外部の関数なので、外部に出せません", e.line)
        sig = sigs.get(e.name)
        if not d.is_function or sig is None or sig.params is None:
            raise SuruError(f"外部に出す関数「{e.name}」には型の宣言が必要です(「数 を 二倍する は 数 を 返す」のように書きます)", e.line)
        types = dict(sig.params)
        e.params = []
        for p, pat in d.params:
            if not isinstance(pat, str):
                raise SuruError(f"外部に出す関数「{e.name}」の引数は名前だけで書いてください", e.line)
            e.params.append(_export_type(types.get(p), e, f"「{p}」"))
        result = sig.result
        if isinstance(result, TypeName) and result.name == "動作":
            e.action = True
            result = result.args[0]
        e.result = _export_type(result, e, "値")


PROJECT_CONFIG = "組" + SOURCE_SUFFIX  # プロジェクトの設定(kumu)
PROJECT_LOCK = "組.lock"  # 依存を固めたファイル(kumu が書く)


def kumu_home() -> str:
    """kumu が取ってきたものを置くフォルダ($KUMU_HOME か ~/.kumu)"""
    return os.environ.get("KUMU_HOME") or os.path.join(os.path.expanduser("~"), ".kumu")


def package_dir(root: str, src: str, version: str) -> str:
    """依存の中身を置くフォルダ(compiler/packages.go の PackageDir と同じ)"""
    if src.startswith(".") or os.path.isabs(src):
        return os.path.normpath(os.path.join(root, src))
    key = src
    if "://" in key:
        scheme, rest = key.split("://", 1)
        key = scheme + "/" + rest.lstrip("/")
    key = key.replace(":", "_")
    if key.endswith(".git"):
        key = key[:-4]
    return os.path.join(kumu_home(), "依存", *key.split("/")[:-1], key.split("/")[-1] + "@" + version)


def find_packages(base_dir: str) -> dict[str, str]:
    """base_dir から上へ 組.suru を探し、隣の 組.lock に書いた依存を返す(名前 → フォルダ)"""
    d = os.path.abspath(base_dir)
    while True:
        if os.path.exists(os.path.join(d, PROJECT_CONFIG)):
            out = {}
            name = _project_name(os.path.join(d, PROJECT_CONFIG))
            if name:  # プロジェクト自身も、組.suru の名前で読み込める(試験/ のファイルから使う)
                out[name] = d
            try:
                with open(os.path.join(d, PROJECT_LOCK), encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except OSError:
                return out
            for line in lines:
                fields = line.split("\t")
                if line and not line.startswith("#") and len(fields) >= 3:
                    out[fields[0]] = package_dir(d, fields[1], fields[2])
            return out
        parent = os.path.dirname(d)
        if parent == d:
            return {}
        d = parent


def _project_name(path: str) -> str:
    """組.suru の「名前 とは 「…」」(読めなければ "")"""
    try:
        with open(path, encoding="utf-8") as f:
            program = parse_program(f.read(), ParseContext())
    except (OSError, SuruError):
        return ""
    for s in program:
        if isinstance(s, Define) and s.name == "名前" and isinstance(s.body, Str):
            return s.body.value
    return ""


def package_path(name: str, ctx: ParseContext, line: int) -> str | None:
    """読み込む名前「X」「X/部品」が依存のものなら、そのファイルのパス"""
    first, _, rest = name.removesuffix(SOURCE_SUFFIX).partition("/")
    folder = (ctx.packages or {}).get(first)
    if folder is None:
        return None
    if not os.path.isdir(folder):
        raise SuruError(f"依存の「{first}」がまだ取ってきてありません(kumu 作る か kumu 取得 で取ってきます)", line)
    return os.path.abspath(os.path.join(folder, *(rest or first).split("/")) + SOURCE_SUFFIX)


def load_module(name: str, ctx: ParseContext, line: int) -> Module:
    """ファイル「name.suru」を読んで解析する。同じファイルは一度だけ読む。
    探す順は、読み込むファイルのフォルダ → プロジェクトの依存 → 標準の lib"""
    if ctx.packages is None:
        ctx.packages = find_packages(ctx.base_dir)
    file = name if name.endswith(SOURCE_SUFFIX) else name + SOURCE_SUFFIX
    path = os.path.abspath(os.path.join(ctx.base_dir, file))
    if path == ctx.path:
        # 「試験/会話帳.suru」の「「会話帳」 を 読み込む」: 自分自身は飛ばして、依存・プロジェクトのフォルダ・標準の lib を探す
        lib = os.path.abspath(os.path.join(LIB_DIR, file))
        pkg = package_path(name, ctx, line)
        found = pkg or _project_file(file, ctx) or (lib if os.path.exists(lib) else None)
        if found is None:
            raise SuruError(f"「{file}」を読み込むと、自分自身を読み込むことになります"
                            "(同じ名前の別のファイルなら、置き場所かファイルの名前を変えてください)", line)
        _mark_library(found, ctx, found == pkg or found == lib)
        return _load_path(found, name, ctx, line)
    searched = not os.path.exists(path)
    if searched:
        path = package_path(name, ctx, line) or os.path.abspath(os.path.join(LIB_DIR, file))
    _mark_library(path, ctx, searched)
    return _load_path(path, name, ctx, line)


def _mark_library(path: str, ctx: ParseContext, searched: bool) -> None:
    """同梱の lib/ のファイル、依存(自分のプロジェクトの外)から見つけたファイル、ライブラリから読み込んだファイルを
    ライブラリとする(#154)。自分のプロジェクトのファイルは、組.suru の名前で読み込んでも自分のプログラム"""
    if _is_lib_path(path) or ctx.path in LIBRARY_SRCS or (searched and not _in_own_project(path, ctx.base_dir)):
        LIBRARY_SRCS.add(path)


def _in_own_project(path: str, base_dir: str) -> bool:
    """path が base_dir を含むプロジェクト(組.suru のあるフォルダ)の中か"""
    d = os.path.abspath(base_dir)
    while not os.path.exists(os.path.join(d, PROJECT_CONFIG)):
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent
    return os.path.abspath(path).startswith(os.path.join(d, ""))


def _project_file(file: str, ctx: ParseContext) -> str | None:
    """プロジェクト(組.suru のあるフォルダ)の一番上にある file。読み込むファイル自身のフォルダは除く"""
    d = os.path.abspath(ctx.base_dir)
    while True:
        if os.path.exists(os.path.join(d, PROJECT_CONFIG)):
            path = os.path.join(d, file)
            return path if d != os.path.abspath(ctx.base_dir) and os.path.exists(path) else None
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _load_path(path: str, name: str, ctx: ParseContext, line: int, prelude: bool = False) -> Module:
    stem = os.path.splitext(os.path.basename(path))[0]
    if not stem or _is_all_hiragana(stem) or any(_is_hiragana(c) for c in stem) or any(c in stem for c in " 　「」『』（）()、。"):
        raise SuruError(f"「{stem}」はファイルの名前に使えません(名前と同じく漢字・カタカナ・英字で書いてください)", line)
    if path in ctx.modules:
        if ctx.modules[path] is None:
            raise SuruError(f"「{stem}{SOURCE_SUFFIX}」を読み込むと、自分自身を読み込むことになります", line)
        return ctx.modules[path]
    try:
        with open(path, encoding="utf-8") as f:
            source = f.read()
    except OSError:
        raise SuruError(f"ファイル「{name}{'' if name.endswith(SOURCE_SUFFIX) else SOURCE_SUFFIX}」が見つかりません", line) from None
    ctx.modules[path] = None
    sub = ParseContext(ctx.ctors, ctx.types, os.path.dirname(path), path=path)
    sub.field_types = dict(ctx.field_types)
    sub.modules = ctx.modules
    sub.packages = ctx.packages
    sub.in_prelude = prelude
    sub.qualify = "" if _is_lib_path(path) else stem + MODULE_SEP
    global _POS_SRC
    saved_src, _POS_SRC = _POS_SRC, path
    SOURCES[path] = source
    try:
        program = drop_tests(parse_program(source, sub))  # 読み込んだファイルの試験と例は使わない(#193)
        for s in program:
            if not isinstance(s, (Define,) + TOP_LEVEL_ONLY):
                raise SuruError("読み込むファイルには定義だけを書いてください", first_line_of(s))
    except SuruError as e:
        raise module_error(e, stem, path, line) from None
    finally:
        _POS_SRC = saved_src
    ctx.ctors.update(sub.ctors)
    ctx.types.update(sub.types)
    ctx.field_types.update(sub.field_types)
    module = Module(stem, path, program, private_names(program), source)
    ctx.modules[path] = module
    return module


def first_line_of(node: Any) -> Any:
    line = getattr(node, "line", None)
    if line:
        return line
    if hasattr(node, "__dataclass_fields__"):
        for f in node.__dataclass_fields__:
            line = first_line_of(getattr(node, f))
            if line:
                return line
    return None


# ---------------------------------------------------------------------------
# 値
# ---------------------------------------------------------------------------
# 数 int/float、真偽 bool、文字列 str、リスト tuple(変更できない)、関数 Function/Builtin/Partial


class Env:
    def __init__(self, parent: "Env | None" = None):
        self.vars: dict[str, Any] = {}
        self.parent = parent

    def lookup(self, name: str, line: int | None) -> Any:
        env: Env | None = self
        while env is not None:
            if name in env.vars:
                return env.vars[name]
            env = env.parent
        raise SuruError(f"「{name}」は定義されていません", line)


@dataclass
class Function:
    name: str
    params: list  # [(助詞, パターン)]
    body: Any
    closure: Env
    lib: bool = field(default=False, compare=False)  # ライブラリで定義した関数(#154)

    def slots(self) -> list[tuple[str, bool]]:
        return [(p, True) for p, _ in self.params]


@dataclass
class Builtin:
    name: str
    params: list  # [(助詞, 必須か)]
    fn: Any  # fn(interp, args: dict, line) -> 値

    def slots(self) -> list[tuple[str, bool]]:
        return list(self.params)


@dataclass
class Partial:
    """引数の一部を先に渡した関数(「1 を 加算すること」)"""

    fn: Any
    bound: dict

    @property
    def name(self) -> str:
        return self.fn.name

    def slots(self) -> list[tuple[str, bool]]:
        return [(p, r) for p, r in self.fn.slots() if p not in self.bound]


@dataclass
class TraitMethod:
    """性質の関数(「比較する」)。「を」の値の型で、どの実装を使うか選ぶ"""

    name: str
    trait: str
    params: list  # [(助詞, パターン)]

    def slots(self) -> list[tuple[str, bool]]:
        return [(p, True) for p, _ in self.params]


FUNCTION_TYPES = (Function, Builtin, Partial, TraitMethod)


@dataclass(eq=False)
class Action:
    """動作(副作用のある計算)。作っただけでは何も起きず、トップレベルに置くと行われる"""

    name: str
    perform: Any  # perform(interp) -> 結果
    upos: Any = field(default_factory=call_pos, compare=False, repr=False)  # 作ったときの呼んだ場所(#154)


@dataclass
class Pure:
    """「x を 結果にする」: 何もせずに x を結果とする動作。連鎖する相手の型に合わせて使われる"""

    value: Any


ACTION_TYPES = (Action, Pure)
_OUT_LOCK = __import__("threading").Lock()  # 「表示する」の出力(スレッドから同時に書くとき)


def _write_stdout(text: str) -> None:
    """「続表示する」: 改行を付けずに書いて、すぐ見えるように出す"""
    sys.stdout.write(text)
    sys.stdout.flush()


@dataclass(frozen=True)
class Record:
    """組の値。「（横 は 3 で 縦 は 4 の 点）」"""

    ctor: str
    type_name: str
    fields: tuple
    values: tuple
    # 失敗の値だけが持つ、見えない覚え: 「した 中身」で返した場所と、「失敗説明する」の説明(比べるときは見ない)
    trace: tuple = field(default=(), compare=False)
    notes: tuple = field(default=(), compare=False)

    def get(self, name: str) -> Any:
        return self.values[self.fields.index(name)]


@dataclass(frozen=True)
class Address:
    """番地: 外部の関数とやりとりする C のポインタ(中は見ない)"""

    value: int

    def __str__(self) -> str:
        return f"番地(0x{self.value:x})"


def type_name_of(v: Any) -> str:
    if isinstance(v, Record):
        return v.type_name
    if isinstance(v, Address):
        return "番地"
    if isinstance(v, CShape):
        return "C形"
    if isinstance(v, bytes):
        return "バイト列"
    if isinstance(v, ACTION_TYPES):
        return "動作"
    if isinstance(v, bool):
        return "真偽"
    if isinstance(v, (int, float)):
        return "数"
    if isinstance(v, str):
        return "文字列"
    if isinstance(v, tuple):
        return "リスト"
    return "関数"


@dataclass
class Lazy:
    """値の定義(「税率 とは 0.1」)。ブロック内での相互参照のため、使うときに評価する"""

    expr: Any
    env: Env
    value: Any = None
    done: bool = False


def format_value(v: Any, nested: bool = False, fmt: Any = None) -> str:
    """値を表示用の文字列にする。fmt は入れ子の値の表示に使う関数(性質「表示可能」のため)"""
    fmt = fmt or (lambda x: format_value(x, True))
    if isinstance(v, Record):
        if not v.fields:
            return short_type_name(v.ctor)
        inner = " で ".join(f"{f} は {fmt(x)}" for f, x in zip(v.fields, v.values))
        return f"（{inner} の {short_type_name(v.ctor)}）"
    if v is True:
        return "真"
    if v is False:
        return "偽"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, tuple):
        if not v:
            return "空"
        return "（" + " と ".join(fmt(x) for x in v) + "）"
    if isinstance(v, str) and nested:
        return f"「{v}」"
    if isinstance(v, FUNCTION_TYPES):
        return f"<関数 {v.name}>"
    if isinstance(v, Action):
        return f"<動作 {v.name}>"
    if isinstance(v, Pure):
        return "<動作 結果にする>"
    if isinstance(v, bytes):
        return "バイト列（" + " ".join(f"{b:02x}" for b in v) + "）"
    return str(v)


def _action_hint(v: Any) -> str:
    if isinstance(v, ACTION_TYPES):
        return "。動作の結果を使うときは、「…してから」か、手順の中で「…した 結果」を使ってください"
    return ""


def _num(v: Any, line: int | None) -> Any:
    if isinstance(v, ACTION_TYPES):
        raise SuruError(f"動作「{format_value(v)}」で計算しようとしました{_action_hint(v)}", line)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SuruError(f"数ではない値「{format_value(v)}」で計算しようとしました", line)
    return v


def _list(v: Any, what: str, line: int | None) -> tuple:
    if not isinstance(v, tuple):
        raise SuruError(f"{what}はリストでなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def apply_op(op: str, a: Any, b: Any, line: int) -> Any:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "+" and isinstance(a, tuple) and isinstance(b, tuple):
        return a + b
    if op in ("<", ">", "<=", ">=") and isinstance(a, str) and isinstance(b, str):
        # 文字列どうしは文字の番号の順(辞書順)で比べる
        return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    if op == "+" and (isinstance(a, str) or isinstance(b, str)):
        return format_value(a) + format_value(b)
    a, b = _num(a, line), _num(b, line)
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op in ("/", "%") and b == 0:
        raise SuruError("0 で割ることはできません", line)
    if op == "/":
        if isinstance(a, int) and isinstance(b, int) and a % b == 0:
            return a // b
        return a / b
    if op == "%":
        return a % b
    if op == "^":
        return a ** b
    if op == "<":
        return a < b
    if op == ">":
        return a > b
    if op == "<=":
        return a <= b
    if op == ">=":
        return a >= b
    raise SuruError(f"未知の演算子 {op}", line)


def get_prop(v: Any, name: str, line: int) -> Any:
    if isinstance(v, Record):
        return get_field(v, name, line)
    if name == "長さ":
        if isinstance(v, str):
            return len(v)
        return len(_list(v, "「の 長さ」の前", line))
    lst = _list(v, f"「の {name}」の前", line)
    if name == "残り":
        if not lst:
            raise SuruError("空のリストに「残り」はありません", line)
        return lst[1:]
    if not lst:
        raise SuruError(f"空のリストに「{name}」はありません", line)
    return lst[0] if name == "先頭" else lst[-1]


def get_field(v: Any, name: str, line: int) -> Any:
    if not isinstance(v, Record) or name not in v.fields:
        raise SuruError(f"「{format_value(v)}」には「{name}」というフィールドがありません", line)
    return v.get(name)


# --- 組み込み関数 -------------------------------------------------------------


def _items(v: Any) -> tuple:
    return v if isinstance(v, tuple) else (v,)


def _fold_op(op: str, values: tuple, line: int, unit: Any) -> Any:
    if not values:
        return unit
    acc = values[0]
    for x in values[1:]:
        acc = apply_op(op, acc, x, line)
    return acc


def _b_add(it: "Interpreter", a: dict, line: int) -> Any:
    return _fold_op("+", _items(a[WO]) + (_items(a["に"]) if "に" in a else ()), line, 0)


def _b_mul(it: "Interpreter", a: dict, line: int) -> Any:
    return _fold_op("*", _items(a[WO]) + (_items(a["に"]) if "に" in a else ()), line, 1)


def _b_apply(it: "Interpreter", a: dict, line: int) -> Any:
    if "に" in a:
        return it.apply(a[WO], [a["に"]], line)
    return it.call(a[WO], {}, line)


def _b_filter(it: "Interpreter", a: dict, line: int) -> Any:
    return tuple(x for x in _list(a["から"], "「選別する」の「から」", line) if it.apply(a["で"], [x], line))


def _b_map(it: "Interpreter", a: dict, line: int) -> Any:
    return tuple(it.apply(a["で"], [x], line) for x in _list(a[WO], "「写像する」の「を」", line))


def _b_fold(it: "Interpreter", a: dict, line: int) -> Any:
    fn = a["で"]
    acc = a["から"]
    two = sum(1 for _, req in it.slots_of(fn, line) if req) >= 2
    for x in _list(a[WO], "「畳み込みする」の「を」", line):
        # 引数が2つ以上ある関数には2つの値として、1つの関数には「acc と x」のリストとして渡す
        acc = it.apply(fn, [acc, x] if two else [(acc, x)], line)
    return acc


def _show(it: "Interpreter", a: dict, line: int) -> Any:
    x = a[WO]

    def perform(it2: "Interpreter") -> Any:
        text = it2.format(x)
        with _OUT_LOCK:  # スレッドどうしで1行が混ざらないように
            it2.out(text)
        return x

    return Action("表示する", perform)


def _show_cont(it: "Interpreter", a: dict, line: int) -> Any:
    x = a[WO]

    def perform(it2: "Interpreter") -> Any:
        text = it2.format(x)
        with _OUT_LOCK:
            it2.write(text)
        return x

    return Action("続表示する", perform)


def _input(it: "Interpreter", a: dict, line: int) -> Any:
    prompt = it.format(a[WO]) if WO in a else ""

    def perform(it2: "Interpreter") -> Any:
        try:
            return it2.read(prompt)
        except EOFError:
            raise SuruError("入力がありません", line) from None

    return Action("入力する", perform)


def _to_number(it: "Interpreter", a: dict, line: int) -> Any:
    v = a[WO]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        text = unicodedata.normalize("NFKC", v).strip().replace("−", "-")
        for conv in (int, float):
            try:
                return conv(text)
            except ValueError:
                pass
    raise SuruError(f"「{format_value(v)}」は数値にできません{_action_hint(v)}", line)


def _run_all(it: "Interpreter", a: dict, line: int) -> Any:
    acts = _list(a[WO], "「実行する」の「を」", line)
    for x in acts:
        if not isinstance(x, ACTION_TYPES):
            raise SuruError(f"「{format_value(x)}」は動作ではありません(「実行する」には動作のリストを渡してください)", line)

    def perform(it2: "Interpreter") -> Any:
        return tuple(it2.perform(x) for x in acts)

    return Action("実行する", perform)


BUILTINS = [
    # x を 表示する / 「質問」を 入力する / 動作のリスト を 実行する: どれも動作を返す
    Builtin("表示する", [(WO, True)], _show),
    Builtin("続表示する", [(WO, True)], _show_cont),
    Builtin("入力する", [(WO, False)], _input),
    Builtin("実行する", [(WO, True)], _run_all),
    Builtin("数値にする", [(WO, True)], _to_number),
    Builtin("絶対値にする", [(WO, True)], lambda it, a, line: abs(_num(a[WO], line))),
    # a と b と c を 加算する / x を y に 加算する
    Builtin("加算する", [(WO, True), ("に", False)], _b_add),
    Builtin("乗算する", [(WO, True), ("に", False)], _b_mul),
    # a から b を 減算する
    Builtin("減算する", [("から", True), (WO, True)], lambda it, a, line: apply_op("-", a["から"], a[WO], line)),
    # a を b で 除算する
    Builtin("除算する", [(WO, True), ("で", True)], lambda it, a, line: apply_op("/", a[WO], a["で"], line)),
    # x を リスト に 追加する(末尾へ) / x を リスト に 挿入する(先頭へ)
    Builtin("追加する", [(WO, True), ("に", True)], lambda it, a, line: _list(a["に"], "「追加する」の「に」", line) + (a[WO],)),
    Builtin("挿入する", [(WO, True), ("に", True)], lambda it, a, line: (a[WO],) + _list(a["に"], "「挿入する」の「に」", line)),
    # 関数 を 値 に 適用する
    Builtin("適用する", [(WO, True), ("に", False)], _b_apply),
    # リスト から 関数 で 選別する / リスト を 関数 で 写像する / リスト を 初期値 から 関数 で 畳み込みする
    Builtin("選別する", [("から", True), ("で", True)], _b_filter),
    Builtin("畳み込みする", [(WO, True), ("から", True), ("で", True)], _b_fold),
]



# ---------------------------------------------------------------------------
# 標準ライブラリ(「「標準」 を 読み込む」で「標準内の…」として使う)
# ---------------------------------------------------------------------------

STD_NAME = "標準"


def data_path(*parts: str) -> str:
    """lib/ や runtime/ の場所。リポジトリでは suru.py の隣、pip で入れたときは隣の suru_data/ の中"""
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.join(here, "suru_data")):
        if os.path.exists(os.path.join(base, parts[0])):
            return os.path.join(base, *parts)
    return os.path.join(here, *parts)


LIB_DIR = data_path("lib")  # 見つからないファイルはここから探す
STD_PATH = os.path.join(LIB_DIR, STD_NAME + SOURCE_SUFFIX)
NET_NAME = "通信"
NET_PATH = os.path.join(LIB_DIR, NET_NAME + SOURCE_SUFFIX)
THREAD_NAME = "スレッド"
THREAD_PATH = os.path.join(LIB_DIR, THREAD_NAME + SOURCE_SUFFIX)
# 基本(成否・有無)は、その名前を書いたファイルが自動で「読み込んで 使う」
PRELUDE_NAME = "基本"
PRELUDE_PATH = os.path.join(LIB_DIR, PRELUDE_NAME + SOURCE_SUFFIX)
PRELUDE_NONE = "無"
PRELUDE_TRY = "試行する"
PRELUDE_TYPES = ("成否", "有無")
PRELUDE_WORDS = frozenset(("成否", "有無", "成功", "失敗", "有"))
PRELUDE_CALLS = frozenset(("成否にする", "有無にする", "中断する", "失敗説明する", "失敗詳細にする", "数値確認する", "入力確認する", "試算する"))  # 取出する は性質の関数なので入れない


def _int(v: Any, what: str, line: int | None) -> int:
    v = _num(v, line)
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if not isinstance(v, int):
        raise SuruError(f"{what}は整数でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _str(v: Any, what: str, line: int | None) -> str:
    if not isinstance(v, str):
        raise SuruError(f"{what}は文字列でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _seq(v: Any, what: str, line: int | None) -> Any:
    if not isinstance(v, (str, tuple)):
        raise SuruError(f"{what}は文字列かリストでなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _floor(it: Any, a: dict, line: int | None) -> Any:
    return math.floor(_num(a[WO], line))


def _sqrt(it: Any, a: dict, line: int | None) -> Any:
    x = _num(a[WO], line)
    if x < 0:
        raise SuruError(f"負の数「{format_value(x)}」の平方根は求められません", line)
    r = math.sqrt(x)
    return int(r) if r.is_integer() else r


def _range(it: Any, a: dict, line: int | None) -> tuple:
    lo = _int(a["から"], "「範囲にする」の「から」", line)
    hi = _int(a[WO], "「範囲にする」の「を」", line)
    return tuple(range(lo, hi + 1))


def _take(it: Any, a: dict, line: int | None) -> Any:
    xs = _seq(a["から"], "「先頭取得する」の「から」", line)
    n = _int(a[WO], "「先頭取得する」の「を」", line)
    return xs[: max(n, 0)]


def _drop(it: Any, a: dict, line: int | None) -> Any:
    xs = _seq(a["から"], "「先頭削除する」の「から」", line)
    n = _int(a[WO], "「先頭削除する」の「を」", line)
    return xs[max(n, 0):]


def _nth(it: Any, a: dict, line: int | None) -> Any:
    xs = _seq(a["から"], "「番目取得する」の「から」", line)
    n = _int(a[WO], "「番目取得する」の「を」", line)
    if not 1 <= n <= len(xs):
        raise SuruError(f"{n}番目はありません(長さは{len(xs)}です。位置は1から数えます)", line)
    return xs[n - 1]


def _contains(it: Any, a: dict, line: int | None) -> bool:
    xs = _seq(a[GA], "「含有である」の「が」", line)
    if isinstance(xs, str):
        return _str(a[WO], "文字列の「含有である」の「を」", line) in xs
    return a[WO] in xs


def _split(it: Any, a: dict, line: int | None) -> tuple:
    s = _str(a[WO], "「分割する」の「を」", line)
    sep = _str(a["で"], "「分割する」の「で」", line)
    if not sep:
        raise SuruError("「分割する」の「で」に空の文字列は使えません(1文字ずつにするには「文字分解する」)", line)
    return tuple(s.split(sep))


def _join(it: Any, a: dict, line: int | None) -> str:
    xs = _list(a[WO], "「結合する」の「を」", line)
    sep = _str(a["で"], "「結合する」の「で」", line)
    return sep.join(_str(x, "「結合する」のリストの要素", line) for x in xs)


def _replace(it: Any, a: dict, line: int | None) -> str:
    s = _str(a[WO], "「置換する」の「を」", line)
    old = _str(a["から"], "「置換する」の「から」", line)
    if not old:
        raise SuruError("「置換する」の「から」に空の文字列は使えません", line)
    return s.replace(old, _str(a["へ"], "「置換する」の「へ」", line))


def _str_fn(name: str, f: Any) -> Builtin:
    return Builtin(name, [(WO, True)], lambda it, a, line: f(_str(a[WO], f"「{name}」の「を」", line)))


def _affix(name: str, f: Any) -> Builtin:
    return Builtin(name, [(GA, True), ("で", True)],
                   lambda it, a, line: f(_str(a[GA], f"「{name}」の「が」", line), _str(a["で"], f"「{name}」の「で」", line)))


# 直列化: 値をバイト列にする(プロセスどうしで値を渡すため)。runtime/suru_rt.c と同じ形式
_SER_MAGIC = b"SURU\x01"


def _serialize(v: Any, line: int) -> bytes:
    out = bytearray(_SER_MAGIC)

    def text(b: bytes) -> None:
        out.extend(len(b).to_bytes(4, "little"))
        out.extend(b)

    def put(x: Any, depth: int) -> None:
        if depth > 10000:
            raise SuruError("入れ子が深すぎて直列化できません", line)
        if x is True or x is False:
            out.extend(b"b\x01" if x else b"b\x00")
        elif isinstance(x, int):
            if not -(1 << 63) <= x < (1 << 63):
                raise SuruError(f"「{format_value(x)}」は大きすぎて直列化できません(±2の63乗までです)", line)
            out.extend(b"i" + x.to_bytes(8, "little", signed=True))
        elif isinstance(x, float):
            out.extend(b"f" + struct.pack("<d", x))
        elif isinstance(x, str):
            out.extend(b"s")
            text(x.encode("utf-8"))
        elif isinstance(x, bytes):
            out.extend(b"y")
            text(x)
        elif isinstance(x, tuple):
            out.extend(b"l" + len(x).to_bytes(4, "little"))
            for y in x:
                put(y, depth + 1)
        elif isinstance(x, Record):
            out.extend(b"r")
            text(x.ctor.encode("utf-8"))
            out.extend(len(x.fields).to_bytes(4, "little"))
            for f, y in zip(x.fields, x.values):
                text(f.encode("utf-8"))
                put(y, depth + 1)
        else:
            raise SuruError(f"「{format_value(x)}」は直列化できません(関数・動作・番地はほかのプロセスへ渡せません)", line)

    put(v, 0)
    return bytes(out)


def _deserialize(it: "Interpreter", v: Any, line: int) -> Any:
    d = _bytes(v, "「復元する」の「を」", line)
    pos = [0]

    def bad() -> SuruError:
        return SuruError(f"バイト列が直列化した値ではありません({pos[0]} バイト目)", line)

    def take(k: int) -> bytes:
        if pos[0] + k > len(d):
            raise bad()
        b = d[pos[0]:pos[0] + k]
        pos[0] += k
        return b

    def u32() -> int:
        return int.from_bytes(take(4), "little")

    def get(depth: int) -> Any:
        if depth > 10000:
            raise SuruError("入れ子が深すぎて復元できません", line)
        t = take(1)
        if t == b"i":
            return int.from_bytes(take(8), "little", signed=True)
        if t == b"f":
            return struct.unpack("<d", take(8))[0]
        if t == b"b":
            x = take(1)[0]
            if x > 1:
                raise bad()
            return x == 1
        if t == b"s":
            try:
                return take(u32()).decode("utf-8")
            except UnicodeDecodeError:
                raise SuruError("復元した文字列が UTF-8 ではありません", line) from None
        if t == b"y":
            return take(u32())
        if t == b"l":
            k = u32()
            if k > len(d) - pos[0]:
                raise bad()
            return tuple(get(depth + 1) for _ in range(k))
        if t == b"r":
            try:
                name = take(u32()).decode("utf-8")
            except UnicodeDecodeError:
                raise bad() from None
            if name not in it.ctx.ctors:
                raise SuruError(f"形「{name}」はこのプログラムにないので復元できません", line)
            type_name, fields = it.ctx.ctors[name]
            nf = u32()
            if nf != len(fields):
                raise SuruError(f"形「{name}」のフィールドの数が違うので復元できません(このプログラムでは{len(fields)}個、バイト列では{nf}個)", line)
            values = []
            for j, f in enumerate(fields):
                if take(u32()) != f.encode("utf-8"):
                    raise SuruError(f"形「{name}」のフィールドが違うので復元できません({j + 1}番目は、このプログラムでは「{f}」)", line)
                values.append(get(depth + 1))
            if not fields:
                return it.shared.vars[name]
            return Record(name, type_name, tuple(fields), tuple(values))
        raise bad()

    if take(5)[:4] != b"SURU":
        raise bad()
    if d[4] != 1:
        raise SuruError(f"直列化の版({d[4]})に対応していません", line)
    r = get(0)
    if pos[0] != len(d):
        raise bad()
    return r


def _fixed_kinds(sample: Any, line: int) -> list:
    """固定の形: 見本の組を、葉のフィールドの並び(「i」整数・「f」小数・「b」真偽、どれも 8 バイト)にする。
    入れ子の組は平らにする(C の構造体と同じ並び)。runtime/suru_rt.c の fixed_kinds と同じ"""
    out: list = []

    def walk(x: Any, depth: int) -> None:
        if depth > 100:
            raise SuruError("入れ子が深すぎて固定の形にできません", line)
        if x is True or x is False:
            out.append("b")
        elif isinstance(x, int):
            out.append("i")
        elif isinstance(x, float):
            out.append("f")
        elif isinstance(x, Record) and x.fields:
            for y in x.values:
                walk(y, depth + 1)
        else:
            raise SuruError(f"「{format_value(x)}」は固定の形にできません(できるのは、数と真偽だけでできた組です)", line)

    if not (isinstance(sample, Record) and sample.fields):
        raise SuruError(f"固定の形の見本は組でなければなりません(「{format_value(sample)}」が渡されました)", line)
    walk(sample, 0)
    return out


def _fixed_serialize(v: Any, sample: Any, line: int) -> bytes:
    out = bytearray()
    _fixed_kinds(sample, line)

    def put(x: Any, s: Any) -> None:
        if isinstance(s, Record):
            if not isinstance(x, Record) or x.ctor != s.ctor:
                raise SuruError(f"「{format_value(x)}」は見本と形が違います(見本は「{s.ctor}」)", line)
            for y, t in zip(x.values, s.values):
                put(y, t)
        elif s is True or s is False:
            if x is not True and x is not False:
                raise SuruError(f"「{format_value(x)}」は見本と違って真偽ではありません", line)
            out.extend((1 if x else 0).to_bytes(8, "little"))
        elif isinstance(s, int):
            if x is True or x is False or not isinstance(x, int):
                raise SuruError(f"「{format_value(x)}」は見本と違って整数ではありません", line)
            if not -(1 << 63) <= x < (1 << 63):
                raise SuruError(f"「{format_value(x)}」は大きすぎて固定の形にできません(±2の63乗までです)", line)
            out.extend(x.to_bytes(8, "little", signed=True))
        else:
            if x is True or x is False or not isinstance(x, (int, float)):
                raise SuruError(f"「{format_value(x)}」は見本と違って数ではありません", line)
            out.extend(struct.pack("<d", float(x)))

    put(v, sample)
    return bytes(out)


def _fixed_deserialize(v: Any, sample: Any, line: int) -> Any:
    d = _bytes(v, "「固定復元する」の「を」", line)
    n = len(_fixed_kinds(sample, line)) * 8
    if len(d) != n:
        raise SuruError(f"バイト列の長さが見本の形と違います(形は {n} バイト、バイト列は {len(d)} バイト)", line)
    pos = [0]

    def get(s: Any) -> Any:
        if isinstance(s, Record):
            return Record(s.ctor, s.type_name, s.fields, tuple(get(t) for t in s.values))
        b = d[pos[0]:pos[0] + 8]
        pos[0] += 8
        if s is True or s is False:
            return int.from_bytes(b, "little") != 0
        if isinstance(s, int):
            return int.from_bytes(b, "little", signed=True)
        return struct.unpack("<d", b)[0]

    return get(sample)


def _sort_keys(keys: list, name: str, line: int) -> None:
    """整列の基準は、全部が数か、全部が文字列(比べ方は「<」と同じ)"""
    def is_num(k: Any) -> bool:
        return isinstance(k, (int, float)) and not isinstance(k, bool)
    for k in keys:
        if not (is_num(k) or isinstance(k, str)):
            raise SuruError(f"「{name}」では数か文字列しか比べられません(「{format_value(k)}」があります)", line)
    if any(is_num(k) for k in keys) and any(isinstance(k, str) for k in keys):
        raise SuruError(f"「{name}」では数と文字列を比べられません", line)


def _sort(it: Any, a: dict, line: int) -> tuple:
    xs = _list(a[WO], "「整列する」の「を」", line)
    _sort_keys(list(xs), "整列する", line)
    return tuple(sorted(xs))


def _sort_by(it: Any, a: dict, line: int) -> tuple:
    xs = _list(a[WO], "「基準整列する」の「を」", line)
    keys = [it.apply(a["で"], [x], line) for x in xs]
    _sort_keys(keys, "基準整列する", line)
    order = sorted(range(len(xs)), key=lambda i: keys[i])  # 同じ基準なら元の順(安定)
    return tuple(xs[i] for i in order)


# 標準.suru の中と、読み込んだ側の「標準内の…」でだけ使える組み込み(する では書けないもの)
STD_PRIMITIVES = [
    Builtin("切捨する", [(WO, True)], _floor),
    Builtin("平方根にする", [(WO, True)], _sqrt),
    Builtin("範囲にする", [("から", True), (WO, True)], _range),
    Builtin("逆順にする", [(WO, True)], lambda it, a, line: _seq(a[WO], "「逆順にする」の「を」", line)[::-1]),
    Builtin("整列する", [(WO, True)], _sort),
    Builtin("基準整列する", [(WO, True), ("で", True)], _sort_by),
    Builtin("先頭取得する", [("から", True), (WO, True)], _take),
    Builtin("先頭削除する", [("から", True), (WO, True)], _drop),
    Builtin("番目取得する", [("から", True), (WO, True)], _nth),
    Builtin("含有である", [(GA, True), (WO, True)], _contains),
    _str_fn("文字分解する", tuple),
    Builtin("分割する", [(WO, True), ("で", True)], _split),
    Builtin("結合する", [(WO, True), ("で", True)], _join),
    Builtin("置換する", [(WO, True), ("から", True), ("へ", True)], _replace),
    _str_fn("大文字にする", str.upper),
    _str_fn("小文字にする", str.lower),
    _str_fn("空白除去する", str.strip),
    _affix("先頭一致である", str.startswith),
    _affix("末尾一致である", str.endswith),
    Builtin("バイト数にする", [(WO, True)], lambda it, a, line: len(_str(a[WO], "「バイト数にする」の「を」", line).encode("utf-8"))),
    Builtin("文字にする", [(WO, True)], lambda it, a, line: _chr(a[WO], line)),
    Builtin("文字コードにする", [(WO, True)], lambda it, a, line: _ord(a[WO], line)),
    Builtin("試行する", [(WO, True), ("で", False)], lambda it, a, line: _try(a[WO], a.get("で"), line)),
    Builtin("後始末実行する", [(WO, True), ("で", True)], lambda it, a, line: _finally(a[WO], a["で"], line)),
    # バイト列と、外部の関数とのやりとり
    Builtin("バイト列にする", [(WO, True)], lambda it, a, line: _str(a[WO], "「バイト列にする」の「を」", line).encode("utf-8")),
    Builtin("バイト列組立する", [(WO, True)], lambda it, a, line: _bytes_of_list(a[WO], line)),
    Builtin("数列にする", [(WO, True)], lambda it, a, line: tuple(_bytes(a[WO], "「数列にする」の「を」", line))),
    Builtin("文字列にする", [(WO, True)], lambda it, a, line: _decode(a[WO], line)),
    Builtin("バイト長にする", [(WO, True)], lambda it, a, line: len(_bytes(a[WO], "「バイト長にする」の「を」", line))),
    Builtin("番地にする", [(WO, True)], lambda it, a, line: Address(_addr_num(a[WO], line))),
    Builtin("番地数値にする", [(WO, True)], lambda it, a, line: _signed_addr(_addr(a[WO], "「番地数値にする」の「を」", line).value)),
    Builtin("直列化する", [(WO, True)], lambda it, a, line: _serialize(a[WO], line)),
    Builtin("復元する", [(WO, True)], lambda it, a, line: _deserialize(it, a[WO], line)),
    Builtin("固定直列化する", [(WO, True), ("で", True)], lambda it, a, line: _fixed_serialize(a[WO], a["で"], line)),
    Builtin("固定復元する", [(WO, True), ("で", True)], lambda it, a, line: _fixed_deserialize(a[WO], a["で"], line)),
    Builtin("バイト列取得する", [("から", True), (WO, True)], lambda it, a, line: _peek(a["から"], a[WO], line)),
    Builtin("書込する", [(WO, True), ("へ", True)], lambda it, a, line: _poke(a[WO], a["へ"], line)),
    Builtin("番地加算する", [(WO, True), ("で", True)], lambda it, a, line: _addr_add(a[WO], a["で"], line)),
    Builtin("エラー番号取得する", [], lambda it, a, line: Action("エラー番号取得する", lambda it2: _errno())),
    Builtin("失敗する", [(WO, True)], lambda it, a, line: _fail_action(a[WO], line)),
    # 環境(lib/環境.suru が使う)
    Builtin("引数取得する", [], lambda it, a, line: Action("引数取得する", lambda it2: tuple(PROGRAM_ARGS))),
    Builtin("呼出場所取得する", [], lambda it, a, line: Pure(_call_site())),
    Builtin("終了する", [(WO, True)], lambda it, a, line: _exit_action(a[WO], line)),
    # ビット演算(整数を2の補数の並びとして扱う)
    Builtin("ビット積にする", [(WO, True), ("で", True)], lambda it, a, line: _bit_op("ビット積にする", a, line, lambda x, y: x & y)),
    Builtin("ビット和にする", [(WO, True), ("で", True)], lambda it, a, line: _bit_op("ビット和にする", a, line, lambda x, y: x | y)),
    Builtin("排他的論理和にする", [(WO, True), ("で", True)], lambda it, a, line: _bit_op("排他的論理和にする", a, line, lambda x, y: x ^ y)),
    Builtin("左シフトする", [(WO, True), ("で", True)], lambda it, a, line: _shift("左シフトする", a, line, lambda x, n: x << n)),
    Builtin("右シフトする", [(WO, True), ("で", True)], lambda it, a, line: _shift("右シフトする", a, line, lambda x, n: x >> n)),
    Builtin("バイト列排他和にする", [(WO, True), ("で", True)], lambda it, a, line: _bytes_xor(a[WO], a["で"], line)),
]


def _bit_op(name: str, a: dict, line: int, op: Any) -> int:
    return op(_int(a[WO], f"「{name}」の「を」", line), _int(a["で"], f"「{name}」の「で」", line))


def _shift(name: str, a: dict, line: int, op: Any) -> int:
    x = _int(a[WO], f"「{name}」の「を」", line)
    n = _int(a["で"], f"「{name}」の「で」", line)
    if not 0 <= n <= 63:
        raise SuruError(f"「{name}」の「で」は 0 から 63 までです(「{n}」が渡されました)", line)
    return op(x, n)


def _bytes_xor(v: Any, k: Any, line: int) -> bytes:
    """「b を 鍵 で バイト列排他和にする」: b の各バイトと、鍵を繰り返したものとの排他的論理和"""
    b = _bytes(v, "「バイト列排他和にする」の「を」", line)
    key = _bytes(k, "「バイト列排他和にする」の「で」", line)
    if not key:
        raise SuruError("「バイト列排他和にする」の「で」(鍵)が空のバイト列です", line)
    rep = (key * (len(b) // len(key) + 1))[:len(b)]
    return (int.from_bytes(b, "big") ^ int.from_bytes(rep, "big")).to_bytes(len(b), "big") if b else b""

PROGRAM_ARGS: list[str] = []  # プログラムに渡した引数(「suru プログラム.suru a b」の a と b)


def _exit_action(v: Any, line: int) -> Action:
    n = _num(v, line)
    if not isinstance(n, int) or not 0 <= n <= 255:
        raise SuruError(f"「{format_value(v)}」は終了コードではありません(0 から 255 までの整数です)", line)

    def perform(it: "Interpreter") -> Any:
        sys.stdout.flush()
        sys.stderr.flush()
        raise SystemExit(n)
    return Action("終了する", perform)


def _bytes(v: Any, what: str, line: int) -> bytes:
    if not isinstance(v, bytes):
        raise SuruError(f"{what}はバイト列でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _addr(v: Any, what: str, line: int) -> Address:
    if not isinstance(v, Address):
        raise SuruError(f"{what}は番地でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _bytes_of_list(v: Any, line: int) -> bytes:
    if not isinstance(v, tuple):
        raise SuruError(f"「バイト列組立する」の「を」はリストでなければなりません(「{format_value(v)}」が渡されました)", line)
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x <= 255:
            raise SuruError(f"「{format_value(x)}」は 0 から 255 までの整数ではありません", line)
    return bytes(v)


def _decode(v: Any, line: int) -> str:
    try:
        return _bytes(v, "「文字列にする」の「を」", line).decode("utf-8")
    except UnicodeDecodeError:
        raise SuruError("バイト列が UTF-8 の文字列ではありません", line) from None


def _signed_addr(n: int) -> int:
    """番地を C の intptr_t と同じ符号つきの数にする(コンパイルしたものと同じ値)"""
    return n - (1 << 64) if n >= 1 << 63 else n


def _addr_num(v: Any, line: int) -> int:
    n = _num(v, line)
    if not isinstance(n, int) or not MIN_COMPILED_INT <= n <= MAX_COMPILED_INT:
        raise SuruError(f"「{format_value(v)}」は番地にできません(整数が必要です)", line)
    # 負の数は C と同じく2の補数の番地にする(-1 は (void *)-1。SQLITE_TRANSIENT や MAP_FAILED など)
    return n & 0xFFFFFFFFFFFFFFFF


def _peek(p: Any, n: Any, line: int) -> Action:
    addr = _addr(p, "「バイト列取得する」の「から」", line)
    k = _num(n, line)
    if not isinstance(k, int) or k < 0:
        raise SuruError(f"「{format_value(n)}」は取得するバイト数ではありません", line)

    def perform(it: "Interpreter") -> bytes:
        import ctypes

        if addr.value == 0 and k > 0:
            raise SuruError("番地(0x0)からは取得できません", line)
        return ctypes.string_at(addr.value, k) if k else b""
    return Action("バイト列取得する", perform)


def _poke(b: Any, p: Any, line: int) -> Action:
    data = _bytes(b, "「書込する」の「を」", line)
    addr = _addr(p, "「書込する」の「へ」", line)

    def perform(it: "Interpreter") -> int:
        import ctypes

        if addr.value == 0 and data:
            raise SuruError("番地(0x0)へは書き込めません", line)
        if data:
            ctypes.memmove(addr.value, data, len(data))
        return len(data)
    return Action("書込する", perform)


# --- C のメモリを型を決めて読み書きする(番地 + 位置のところの値を1つ) ---
# C の型の名前 → (struct の書式, 大きさ, 種類)。種類: i 整数、f 小数、p 番地、b 真偽(ほかに C文字列: NUL で終わる文字列)
C_SCALARS = {
    "符号付き8": ("b", 1, "i"), "符号付き16": ("h", 2, "i"), "符号付き32": ("i", 4, "i"), "符号付き64": ("q", 8, "i"),
    "符号なし8": ("B", 1, "i"), "符号なし16": ("H", 2, "i"), "符号なし32": ("I", 4, "i"), "符号なし64": ("Q", 8, "i"),
    "単精度": ("f", 4, "f"), "小数": ("d", 8, "f"), "番地": ("Q", 8, "p"), "真偽": ("B", 1, "b"),
}
C_MEM_TYPES = tuple(C_SCALARS) + ("C文字列",)


def _int_range(t: str) -> tuple[int, int]:
    """C の整数の型に入る範囲(64 ビットはコンパイルしたプログラムの整数の範囲にそろえる)"""
    unsigned = t.startswith("符号なし")
    bits = int(t[4:])
    if unsigned:
        return 0, min((1 << bits) - 1, MAX_COMPILED_INT)
    return max(-(1 << (bits - 1)), MIN_COMPILED_INT), min((1 << (bits - 1)) - 1, MAX_COMPILED_INT)


def _c_offset(v: Any, fn: str, line: int) -> int:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int) or not MIN_COMPILED_INT <= v <= MAX_COMPILED_INT:
        raise SuruError(f"「{fn}」の「で」は位置(整数のバイト数)でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _c_encode(t: str, v: Any, what: str, line: int) -> bytes:
    """する の値を C の型 t のバイト列にする(入らなければエラー)"""
    import struct

    if t == "C文字列":
        if not isinstance(v, str):
            raise SuruError(f"{what}は文字列でなければなりません(「{format_value(v)}」が渡されました)", line)
        data = v.encode("utf-8")
        if b"\0" in data:
            raise SuruError(f"{what}は途中に文字コード 0 を含まない文字列でなければなりません", line)
        return data + b"\0"
    fmt, _, kind = C_SCALARS[t]
    if kind == "p":
        return struct.pack("=" + fmt, _addr(v, what, line).value)
    if kind == "b":
        if not isinstance(v, bool):
            raise SuruError(f"{what}は真偽でなければなりません(「{format_value(v)}」が渡されました)", line)
        return struct.pack("=" + fmt, 1 if v else 0)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SuruError(f"{what}は数でなければなりません(「{format_value(v)}」が渡されました)", line)
    if kind == "f":
        return struct.pack("=" + fmt, float(v))
    lo, hi = _int_range(t)
    n = int(v) if isinstance(v, float) and v.is_integer() else v
    if not isinstance(n, int) or not lo <= n <= hi:
        raise SuruError(f"「{format_value(v)}」は{t}に入りません({lo} から {hi} までの整数です)", line)
    return struct.pack("=" + fmt, n)


def _c_decode(t: str, data: bytes, line: int) -> Any:
    """C の型 t のバイト列を する の値にする"""
    import struct

    fmt, _, kind = C_SCALARS[t]
    (r,) = struct.unpack("=" + fmt, data)
    if kind == "p":
        return Address(r)
    if kind == "b":
        return r != 0
    if kind == "f":
        return float(r)
    if not MIN_COMPILED_INT <= r <= MAX_COMPILED_INT:
        raise SuruError(f"{t}の値 {r} が大きすぎます(整数は ±{MAX_COMPILED_INT} までです)", line)
    return r


def _mem_read(t: str, p: Any, off: Any, line: int) -> Action:
    fn = t + "読取する"
    base = _addr(p, f"「{fn}」の「から」", line)
    k = _c_offset(off, fn, line)

    def perform(it: "Interpreter") -> Any:
        import ctypes

        if base.value == 0:
            raise SuruError("番地(0x0)からは読み取れません", line)
        at = (base.value + k) & 0xFFFFFFFFFFFFFFFF
        if t == "C文字列":
            return ctypes.string_at(at).decode("utf-8", "replace")
        return _c_decode(t, ctypes.string_at(at, C_SCALARS[t][1]), line)
    return Action(fn, perform)


def _mem_write(t: str, v: Any, p: Any, off: Any, line: int) -> Action:
    fn = t + "書込する"
    data = _c_encode(t, v, f"「{fn}」の「を」", line)
    base = _addr(p, f"「{fn}」の「へ」", line)
    k = _c_offset(off, fn, line)

    def perform(it: "Interpreter") -> int:
        import ctypes

        if base.value == 0:
            raise SuruError("番地(0x0)へは書き込めません", line)
        ctypes.memmove((base.value + k) & 0xFFFFFFFFFFFFFFFF, data, len(data))
        return len(data)
    return Action(fn, perform)


def _addr_add(p: Any, n: Any, line: int) -> Address:
    base = _addr(p, "「番地加算する」の「を」", line)
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if isinstance(n, bool) or not isinstance(n, int) or not MIN_COMPILED_INT <= n <= MAX_COMPILED_INT:
        raise SuruError(f"「番地加算する」の「で」は整数でなければなりません(「{format_value(n)}」が渡されました)", line)
    return Address((base.value + n) & 0xFFFFFFFFFFFFFFFF)


def _mem_builtins() -> list:
    out = []
    for t in C_MEM_TYPES:
        out.append(Builtin(t + "読取する", [("から", True), ("で", True)],
                           lambda it, a, line, t=t: _mem_read(t, a["から"], a["で"], line)))
        out.append(Builtin(t + "書込する", [(WO, True), ("へ", True), ("で", True)],
                           lambda it, a, line, t=t: _mem_write(t, a[WO], a["へ"], a["で"], line)))
    return out


STD_PRIMITIVES.extend(_mem_builtins())


# --- C の構造体の形(「C形作成する」): 組と、C と同じ並び(揃えと詰め物)のメモリを行き来する ---
@dataclass(frozen=True, eq=False)
class CField:
    """C形の欄: 型の名前(C_SCALARS か「構造体」)、配列なら要素の数、構造体なら中の形"""

    ctype: str
    count: Any  # 配列の要素の数(配列でなければ None)
    inner: Any = None  # 構造体の欄の形(入れ子設定するまで None)


@dataclass(frozen=True, eq=False)
class CShape:
    """C形: 見本の組と、フィールドごとの欄"""

    sample: Record
    fields: tuple

    def __str__(self) -> str:
        return f"<C形 {short_type_name(self.sample.ctor)}>"


CSHAPE_STRUCT = "構造体"
CSHAPE_MAX_COUNT = 1 << 20  # 配列の欄の要素の数の上限


def _cshape(v: Any, what: str, line: int) -> CShape:
    if not isinstance(v, CShape):
        raise SuruError(f"{what}はC形でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v


def _cfield_spec(s: str, line: int) -> CField:
    """「符号付き32」「符号なし8[16]」「構造体」「構造体[3]」を読む"""
    name, count = s, None
    if s.endswith("]") and "[" in s:
        name, num = s[:-1].split("[", 1)
        if not num.isdigit() or not num.isascii() or not 1 <= int(num) <= CSHAPE_MAX_COUNT:
            raise SuruError(f"C形の欄「{s}」の配列の大きさは 1 から {CSHAPE_MAX_COUNT} までの整数で書きます(「符号なし8[16]」)", line)
        count = int(num)
    if name not in C_SCALARS and name != CSHAPE_STRUCT:
        raise SuruError(f"「{s}」はC形の欄の型ではありません(符号付き8〜64・符号なし8〜64・単精度・小数・番地・真偽・構造体、"
                        "配列は「符号なし8[16]」)", line)
    return CField(name, count)


def _cfield_fits(f: CField, x: Any, k: int, line: int) -> None:
    """見本のフィールドの値 x が欄 f に合うか(合わなければエラー)"""
    def bad(want: str) -> SuruError:
        return SuruError(f"C形の見本の{k}番目のフィールド「{format_value(x)}」は{want}でなければなりません(欄は「{_cfield_name(f)}」)", line)

    if f.count is not None:
        if not isinstance(x, tuple):
            raise bad("リスト")
        items = x
    else:
        items = (x,)
    for y in items:
        if f.ctype == CSHAPE_STRUCT:
            if not isinstance(y, Record):
                raise bad("組")
            if f.inner is not None and y.ctor != f.inner.sample.ctor:
                raise bad(f"「{short_type_name(f.inner.sample.ctor)}」の組")
            continue
        kind = C_SCALARS[f.ctype][2]
        if kind == "p" and not isinstance(y, Address):
            raise bad("番地")
        if kind == "b" and not isinstance(y, bool):
            raise bad("真偽")
        if kind in ("i", "f") and (isinstance(y, bool) or not isinstance(y, (int, float))):
            raise bad("数")


def _cfield_name(f: CField) -> str:
    return f.ctype + (f"[{f.count}]" if f.count is not None else "")


def _cshape_make(sample: Any, specs: Any, line: int) -> CShape:
    if not isinstance(sample, Record) or not sample.fields:
        raise SuruError(f"「C形作成する」の「を」はフィールドのある組でなければなりません(「{format_value(sample)}」が渡されました)", line)
    specs = _list(specs, "「C形作成する」の「で」", line)
    if len(specs) != len(sample.fields):
        raise SuruError(f"C形の欄の数({len(specs)})が、見本のフィールドの数({len(sample.fields)})と違います", line)
    fields = tuple(_cfield_spec(_str(s, "C形の欄", line), line) for s in specs)
    for k, (f, x) in enumerate(zip(fields, sample.values), 1):
        _cfield_fits(f, x, k, line)
    return CShape(sample, fields)


def _cshape_nest(shape: Any, k: Any, inner: Any, line: int) -> CShape:
    s = _cshape(shape, "「入れ子設定する」の「を」", line)
    sub = _cshape(inner, "「入れ子設定する」の「に」", line)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= len(s.fields):
        raise SuruError(f"「入れ子設定する」の「で」は 1 から {len(s.fields)} までの欄の番号です(「{format_value(k)}」が渡されました)", line)
    old = s.fields[k - 1]
    if old.ctype != CSHAPE_STRUCT:
        raise SuruError(f"C形の{k}番目の欄は「{_cfield_name(old)}」なので、入れ子にできません(「構造体」と書いた欄だけです)", line)
    f = CField(CSHAPE_STRUCT, old.count, sub)
    _cfield_fits(f, s.sample.values[k - 1], k, line)
    return CShape(s.sample, s.fields[:k - 1] + (f,) + s.fields[k:])


def _cfield_layout(f: CField, line: int) -> tuple[int, int]:
    """欄の (大きさ, 揃え)"""
    if f.ctype == CSHAPE_STRUCT:
        if f.inner is None:
            raise SuruError("C形に、中の形が決まっていない「構造体」の欄があります(「入れ子設定する」で決めます)", line)
        size, align = _cshape_layout(f.inner, line)[:2]
    else:
        size = align = C_SCALARS[f.ctype][1]
    return size * (f.count or 1), align


def _cshape_layout(s: CShape, line: int) -> tuple[int, int, tuple]:
    """C と同じ規則の (大きさ, 揃え, 欄ごとの位置): 欄はその揃えの倍数の位置に置き、全体は一番大きい揃えの倍数"""
    off, top, offs = 0, 1, []
    for f in s.fields:
        size, align = _cfield_layout(f, line)
        off = (off + align - 1) // align * align
        offs.append(off)
        off += size
        top = max(top, align)
    return (off + top - 1) // top * top, top, tuple(offs)


def _cshape_put(s: CShape, x: Any, out: bytearray, at: int, line: int) -> None:
    """組 x を out[at:] に C の並びで書く"""
    if not isinstance(x, Record) or x.ctor != s.sample.ctor:
        raise SuruError(f"「{format_value(x)}」はC形と違う組です(C形は「{short_type_name(s.sample.ctor)}」)", line)
    _, _, offs = _cshape_layout(s, line)
    for k, (f, v, off) in enumerate(zip(s.fields, x.values, offs), 1):
        items = (v,)
        if f.count is not None:
            if not isinstance(v, tuple) or len(v) != f.count:
                raise SuruError(f"「{format_value(v)}」は{f.count}個の要素のリストではありません({k}番目のフィールド「{x.fields[k - 1]}」)", line)
            items = v
        size = _cfield_layout(CField(f.ctype, None, f.inner), line)[0]
        for i, y in enumerate(items):
            if f.ctype == CSHAPE_STRUCT:
                _cshape_put(f.inner, y, out, at + off + i * size, line)
            else:
                data = _c_encode(f.ctype, y, f"{k}番目のフィールド「{x.fields[k - 1]}」", line)
                out[at + off + i * size:at + off + (i + 1) * size] = data


def _cshape_get(s: CShape, data: bytes, at: int, line: int) -> Record:
    _, _, offs = _cshape_layout(s, line)
    values = []
    for f, off in zip(s.fields, offs):
        size = _cfield_layout(CField(f.ctype, None, f.inner), line)[0]
        items = []
        for i in range(f.count or 1):
            p = at + off + i * size
            if f.ctype == CSHAPE_STRUCT:
                items.append(_cshape_get(f.inner, data, p, line))
            else:
                items.append(_c_decode(f.ctype, data[p:p + size], line))
        values.append(tuple(items) if f.count is not None else items[0])
    return Record(s.sample.ctor, s.sample.type_name, s.sample.fields, tuple(values))


def _cshape_bytes(x: Any, shape: Any, line: int) -> bytes:
    s = _cshape(shape, "「C直列化する」の「で」", line)
    out = bytearray(_cshape_layout(s, line)[0])
    _cshape_put(s, x, out, 0, line)
    return bytes(out)


def _cshape_from_bytes(b: Any, shape: Any, line: int) -> Record:
    data = _bytes(b, "「C復元する」の「を」", line)
    s = _cshape(shape, "「C復元する」の「で」", line)
    n = _cshape_layout(s, line)[0]
    if len(data) != n:
        raise SuruError(f"バイト列の長さがC形と違います(C形は {n} バイト、バイト列は {len(data)} バイト)", line)
    return _cshape_get(s, data, 0, line)


def _struct_read(p: Any, off: Any, shape: Any, line: int) -> Action:
    base = _addr(p, "「構造体読取する」の「から」", line)
    k = _c_offset(off, "構造体読取する", line)
    s = _cshape(shape, "「構造体読取する」の「を」", line)
    n = _cshape_layout(s, line)[0]

    def perform(it: "Interpreter") -> Any:
        import ctypes

        if base.value == 0:
            raise SuruError("番地(0x0)からは読み取れません", line)
        return _cshape_get(s, ctypes.string_at((base.value + k) & 0xFFFFFFFFFFFFFFFF, n), 0, line)
    return Action("構造体読取する", perform)


def _struct_write(x: Any, p: Any, off: Any, shape: Any, line: int) -> Action:
    s = _cshape(shape, "「構造体書込する」の「に」", line)
    data = _cshape_bytes(x, s, line)
    base = _addr(p, "「構造体書込する」の「へ」", line)
    k = _c_offset(off, "構造体書込する", line)

    def perform(it: "Interpreter") -> int:
        import ctypes

        if base.value == 0:
            raise SuruError("番地(0x0)へは書き込めません", line)
        ctypes.memmove((base.value + k) & 0xFFFFFFFFFFFFFFFF, data, len(data))
        return len(data)
    return Action("構造体書込する", perform)


STD_PRIMITIVES.extend([
    Builtin("C形作成する", [(WO, True), ("で", True)], lambda it, a, line: _cshape_make(a[WO], a["で"], line)),
    Builtin("入れ子設定する", [(WO, True), ("で", True), ("に", True)],
            lambda it, a, line: _cshape_nest(a[WO], a["で"], a["に"], line)),
    Builtin("C大きさにする", [(WO, True)],
            lambda it, a, line: _cshape_layout(_cshape(a[WO], "「C大きさにする」の「を」", line), line)[0]),
    Builtin("C揃えにする", [(WO, True)],
            lambda it, a, line: _cshape_layout(_cshape(a[WO], "「C揃えにする」の「を」", line), line)[1]),
    Builtin("C位置にする", [(WO, True), ("で", True)], lambda it, a, line: _cshape_offset(a[WO], a["で"], line)),
    Builtin("C直列化する", [(WO, True), ("で", True)], lambda it, a, line: _cshape_bytes(a[WO], a["で"], line)),
    Builtin("C復元する", [(WO, True), ("で", True)], lambda it, a, line: _cshape_from_bytes(a[WO], a["で"], line)),
    Builtin("構造体読取する", [("から", True), ("で", True), (WO, True)],
            lambda it, a, line: _struct_read(a["から"], a["で"], a[WO], line)),
    Builtin("構造体書込する", [(WO, True), ("へ", True), ("で", True), ("に", True)],
            lambda it, a, line: _struct_write(a[WO], a["へ"], a["で"], a["に"], line)),
])


def _cshape_offset(shape: Any, k: Any, line: int) -> int:
    s = _cshape(shape, "「C位置にする」の「を」", line)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= len(s.fields):
        raise SuruError(f"「C位置にする」の「で」は 1 から {len(s.fields)} までの欄の番号です(「{format_value(k)}」が渡されました)", line)
    return _cshape_layout(s, line)[2][k - 1]


def _errno() -> int:
    import ctypes

    return ctypes.get_errno()


def _abort(it: Any, a: dict, line: int) -> Any:
    raise SuruError(_str(a[WO], "「中断する」の「を」", line), line)


PRELUDE_PRIMITIVES = [
    Builtin("中断する", [(WO, True)], _abort),
    Builtin("失敗説明する", [(WO, True), ("で", True)], lambda it, a, line: _explain(it, a, line)),
    Builtin("失敗詳細にする", [(WO, True)], lambda it, a, line: _detail(it, a, line)),
    Builtin("数値確認する", [(WO, True)], lambda it, a, line: _number_check(it, a, line)),
    Builtin("入力確認する", [(WO, False)], lambda it, a, line: _input_check(it, a, line)),
    Builtin("試算する", [(WO, True)], lambda it, a, line: _calc_try(it, a, line)),
]


def _fail_action(v: Any, line: int) -> Action:
    msg = _str(v, "「失敗する」の「を」", line)

    def perform(it: "Interpreter") -> Any:
        raise SuruError(msg, line)
    return Action("失敗する", perform)


def _try(m: Any, alt: Any, line: int) -> Any:
    """「m を 代わり で 試行する」: m を行い、実行時エラーになったら、エラーの文を標準エラーに書いて 代わり を行う。
    「で」を省くと、成功なら 結果 の 成功、実行時エラーなら エラーの文 の 失敗(標準エラーには書かない)"""
    for v, p in ((m, "を"), (alt, "で")):
        if v is None:
            continue
        if not isinstance(v, ACTION_TYPES):
            raise SuruError(f"「試行する」の「{p}」は動作でなければなりません(「{format_value(v)}」が渡されました)", line)

    if alt is None:
        def perform_result(it: "Interpreter") -> Any:
            try:
                return Record("成功", "成否", ("値",), (it.perform(m),))
            except SuruError as e:
                return caught_failure(e)
            except RecursionError:
                return Record("失敗", "成否", ("理由",), ("再帰が深すぎます",))

        return Action("試行する", perform_result)

    def perform(it: "Interpreter") -> Any:
        try:
            return it.perform(m)
        except SuruError as e:
            print(f"エラー: {e}", file=sys.stderr, flush=True)
        except RecursionError:
            print("エラー: 再帰が深すぎます", file=sys.stderr, flush=True)
        return it.perform(alt)

    return Action("試行する", perform)


def _finally(m: Any, cleanup: Any, line: int) -> Any:
    """「m を 後始末 で 後始末実行する」: m を行い、成功しても実行時エラーでも 後始末 を行う。
    結果は m の結果。m がエラーなら、後始末のあとで同じエラーを続ける"""
    for v, p in ((m, "を"), (cleanup, "で")):
        if not isinstance(v, ACTION_TYPES):
            raise SuruError(f"「後始末実行する」の「{p}」は動作でなければなりません(「{format_value(v)}」が渡されました)", line)

    def perform(it: "Interpreter") -> Any:
        try:
            r = it.perform(m)
        except (SuruError, RecursionError):
            it.perform(cleanup)
            raise
        it.perform(cleanup)
        return r

    return Action("後始末実行する", perform)


def _chr(v: Any, line: int) -> str:
    n = _num(v, line)
    if not isinstance(n, int) or not 0 <= n <= 0x10FFFF or 0xD800 <= n <= 0xDFFF:
        raise SuruError(f"「{format_value(v)}」は文字の番号ではありません", line)
    return chr(n)


def _ord(v: Any, line: int) -> int:
    s = _str(v, "「文字コードにする」の「を」", line)
    if len(s) != 1:
        raise SuruError(f"「文字コードにする」の「を」は1文字の文字列です(「{s}」)", line)
    return ord(s)


# --- 通信(「通信」を読み込んだときだけ使える)。待受口と接続は番号で表す -----------

NET_TIMEOUT = 5  # 接続の受信・送信を待つ秒数(超えると「通信に失敗しました」)


class _Net:
    """インタプリタごとの、開いている待受口と接続(番号 → ソケット)"""

    def __init__(self) -> None:
        self.socks: dict = {}
        self.files: dict = {}  # 接続の読み込み用(行で読むため)
        self.raw: set = set()  # 記述子取得する で C に渡した接続(待つ時間は OS の設定で決める)
        self.next = 1

    def add(self, sock: Any) -> int:
        n, self.next = self.next, self.next + 1
        self.socks[n] = sock
        return n

    def get(self, v: Any, what: str, line: int) -> Any:
        sock = self.socks.get(v) if isinstance(v, int) and not isinstance(v, bool) else None
        if sock is None:
            raise SuruError(f"「{format_value(v)}」は開いている{what}ではありません", line)
        return sock

    def reader(self, v: Any, line: int) -> Any:
        sock = self.get(v, "接続", line)
        if v not in self.files:
            self.files[v] = sock.makefile("rb")
        return self.files[v]

    def read(self, v: Any, line: int, how: Any) -> Any:
        """読み込み用で読む。時間切れになった読み込み用はもう読めないので、次は作り直す"""
        sys.stdout.flush()  # 待つ前に、それまでの表示を出しておく(コンパイルしたものと同じ)
        try:
            return how(self.reader(v, line))
        except TimeoutError:
            f = self.files.pop(v, None)
            if f is not None:
                f.close()
            raise


def _net(it: "Interpreter") -> _Net:
    net = getattr(it, "_net", None)
    if net is None:
        net = it._net = _Net()
    return net


def _net_action(name: str, run: Any) -> Any:
    """通信の動作。OS のエラーは「通信に失敗しました」の実行時エラーにする"""
    def fn(it: "Interpreter", a: dict, line: int) -> Any:
        def perform(it2: "Interpreter") -> Any:
            try:
                return run(_net(it2), a, line)
            except TimeoutError:  # 待機時間設定する・期限付き接続する の時間切れ(OS によらず同じ文に)
                raise SuruError(f"「{name}」で通信に失敗しました(時間切れ)", line) from None
            except OSError as e:
                raise SuruError(f"「{name}」で通信に失敗しました({e.strerror or e})", line) from None
        return Action(name, perform)
    return fn


def _bind_addr(name: str, a: dict, line: int) -> tuple:
    """「ポート を アドレス に 待受開始する」の、アドレスの種類と待ち受けるアドレス(「に」がなければ 0.0.0.0。IPv6 のアドレスなら IPv6)"""
    import socket
    port = _num(a[WO], line)
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise SuruError(f"「{format_value(a[WO])}」はポートの番号ではありません", line)
    if "に" not in a:
        return socket.AF_INET, ("0.0.0.0", port)
    host = _str(a["に"], f"「{name}」の「に」", line)
    try:
        found = socket.getaddrinfo(host, port, socket.AF_UNSPEC, 0, 0, socket.AI_PASSIVE)
    except socket.gaierror as e:
        raise SuruError(f"「{name}」で通信に失敗しました({e.strerror or e})", line) from None
    pick = next((r for r in found if r[0] == socket.AF_INET), found[0])  # 名前なら IPv4 を先に(今までどおり)
    return pick[0], pick[4]


def _listen(net: _Net, a: dict, line: int) -> int:
    import socket
    family, addr = _bind_addr("待受開始する", a, line)
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(addr)
    except OSError:
        sock.close()
        raise
    sock.listen(16)
    return net.add(sock)


def _connect(net: _Net, a: dict, line: int, name: str = "接続する") -> int:
    import socket
    host = _str(a["に"], "「接続する」の「に」", line)
    port = _num(a["で"], line)
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise SuruError(f"「{format_value(a['で'])}」はポートの番号ではありません", line)
    limit = None  # 期限付き接続する の秒
    if WO in a:
        limit = _num(a[WO], line)
        if isinstance(limit, bool) or not limit > 0:
            raise SuruError(f"「{format_value(a[WO])}」は待つ秒数ではありません(0 より大きい数です)", line)
    try:
        sock = socket.create_connection((host, port), timeout=limit)
    except socket.gaierror as e:
        raise SuruError(f"「{name}」で通信に失敗しました({e.strerror or e})", line) from None
    sock.settimeout(None)
    # 応答を待つ時間は区切らない(LLM のように最初の応答まで長くかかる相手もいるため)
    return net.add(sock)


def _accept(net: _Net, a: dict, line: int) -> int:
    sys.stdout.flush()  # 待つ前に、それまでの表示を出しておく(コンパイルしたものと同じ)
    conn, _ = net.get(a["から"], "待受口", line).accept()
    conn.settimeout(NET_TIMEOUT)  # 何も送ってこない相手で止まらないように
    return net.add(conn)


def _recv_line(net: _Net, a: dict, line: int) -> str:
    # 行の終わりの改行も含めて返す。相手が閉じていれば空の文字列
    return net.read(a["から"], line, lambda f: f.readline(65536)).decode("utf-8", "replace")


def _recv(net: _Net, a: dict, line: int) -> str:
    n = _num(a[WO], line)
    if not isinstance(n, int) or n < 0:
        raise SuruError(f"「{format_value(a[WO])}」は受信するバイト数ではありません", line)
    return net.read(a["から"], line, lambda f: f.read(n)).decode("utf-8", "replace")


def _recv_bytes(net: _Net, a: dict, line: int) -> bytes:
    """「接続 から n を バイト列受信する」: n バイトまでをバイト列のまま(文字の途中で切れても壊さない)"""
    n = _num(a[WO], line)
    if not isinstance(n, int) or n < 0:
        raise SuruError(f"「{format_value(a[WO])}」は受信するバイト数ではありません", line)
    return net.read(a["から"], line, lambda f: f.read(n))


def _send(net: _Net, a: dict, line: int) -> int:
    data = _str(a[WO], "「送信する」の「を」", line).encode("utf-8")
    net.get(a["へ"], "接続", line).sendall(data)
    return len(data)


def _send_bytes(net: _Net, a: dict, line: int) -> int:
    data = _bytes(a[WO], "「バイト列送信する」の「を」", line)
    net.get(a["へ"], "接続", line).sendall(data)
    return len(data)


def _set_timeout(net: _Net, a: dict, line: int) -> int:
    """「接続 を 秒 で 待機時間設定する」: 受信・送信を待つ秒数(0 なら待ち続ける)"""
    sec = _num(a["で"], line)
    if isinstance(sec, bool) or sec < 0:
        raise SuruError(f"「{format_value(a['で'])}」は待つ秒数ではありません(0 以上の数です)", line)
    sock = net.get(a[WO], "接続", line)
    if a[WO] in net.raw:
        _os_timeout(sock, sec)
    else:
        sock.settimeout(sec if sec > 0 else None)
    return a[WO]


def _close(net: _Net, a: dict, line: int) -> int:
    v = a[WO]
    sock = net.get(v, "待受口か接続", line)
    f = net.files.pop(v, None)
    net.raw.discard(v)
    if f is not None:
        f.close()
    sock.close()
    del net.socks[v]
    return v


def _udp_open(net: _Net, a: dict, line: int) -> int:
    """「ポート を UDP開始する」: 0.0.0.0(「に」があればそのアドレス)のそのポートで受け取る UDP の口(0 なら OS が選ぶ)"""
    import socket
    family, addr = _bind_addr("UDP開始する", a, line)
    sock = socket.socket(family, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(addr)
    except OSError:
        sock.close()
        raise
    return net.add(sock)


def _udp_send(net: _Net, a: dict, line: int) -> int:
    """「バイト列 を 口 から ホスト に ポート で UDPバイト列送信する」: 1つの便りとして送る"""
    import socket
    data = _bytes(a[WO], "「UDPバイト列送信する」の「を」", line)
    sock = net.get(a["から"], "UDPの口", line)
    host = _str(a["に"], "「UDPバイト列送信する」の「に」", line)
    port = _num(a["で"], line)
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise SuruError(f"「{format_value(a['で'])}」はポートの番号ではありません", line)
    try:
        addr = socket.getaddrinfo(host, port, sock.family, socket.SOCK_DGRAM)[0][4]  # 口と同じ種類のアドレス
    except socket.gaierror as e:
        raise SuruError(f"「UDPバイト列送信する」で通信に失敗しました({e.strerror or e})", line) from None
    return sock.sendto(data, addr)


def _udp_recv(net: _Net, a: dict, line: int) -> Record:
    """「口 から UDPバイト列受信する」: 次の便りを1つ丸ごと(中身はバイト列)。送り主の IP アドレスとポートも"""
    sys.stdout.flush()  # 待つ前に、それまでの表示を出しておく(コンパイルしたものと同じ)
    data, addr = net.get(a["から"], "UDPの口", line).recvfrom(65536)
    return Record("UDP便", "UDP便", ("中身", "送り主", "ポート"), (data, addr[0], addr[1]))


def _sock_fd(net: _Net, a: dict, line: int) -> int:
    """「接続 を 記述子取得する」: OS のソケットの番号(OpenSSL などの C の関数に渡す)"""
    sock = net.get(a[WO], "接続", line)
    net.raw.add(a[WO])
    return sock.fileno()


def _os_timeout(sock: Any, sec: float) -> None:
    """C が読み書きするソケットは、ブロックするまま OS に待つ時間を決めさせる(コンパイルしたものと同じ)"""
    import socket
    import struct
    sock.settimeout(None)
    if sys.platform == "win32":
        v = struct.pack("I", int(sec * 1000))
    else:
        v = struct.pack("ll", int(sec), int((sec - int(sec)) * 1e6))
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, v)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, v)


def _local_port(net: _Net, a: dict, line: int) -> int:
    """「口 を ポート取得する」: 待受口・接続・UDP の口の、こちらのポート(0 で開いたときに OS が選んだもの)"""
    return net.get(a[WO], "待受口か接続かUDPの口", line).getsockname()[1]


def _peer_addr(net: _Net, a: dict, line: int) -> str:
    """「接続 を 相手アドレス取得する」: つながっている相手の IP アドレス"""
    return net.get(a[WO], "接続", line).getpeername()[0]


def _peer_port(net: _Net, a: dict, line: int) -> int:
    """「接続 を 相手ポート取得する」: つながっている相手のポート"""
    return net.get(a[WO], "接続", line).getpeername()[1]


def _broadcast(net: _Net, a: dict, line: int) -> int:
    """「口 を ブロードキャスト許可する」: 255.255.255.255 などへ送れるようにする"""
    import socket
    net.get(a[WO], "UDPの口", line).setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    return a[WO]


def _multicast(join: bool) -> Any:
    """「口 を アドレス に マルチキャスト参加する」「口 を アドレス から マルチキャスト離脱する」"""
    def run(net: _Net, a: dict, line: int) -> int:
        import ipaddress
        import socket
        import struct
        name, part = ("マルチキャスト参加する", "に") if join else ("マルチキャスト離脱する", "から")
        sock = net.get(a[WO], "UDPの口", line)
        text = _str(a[part], f"「{name}」の「{part}」", line)
        try:
            group = ipaddress.ip_address(text)
        except ValueError:
            group = None
        if group is None or not group.is_multicast:
            raise SuruError(f"「{text}」はマルチキャストのアドレスではありません(IPv4 は 224.0.0.0〜239.255.255.255、IPv6 は ff で始まる)", line)
        if group.version == 4:
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP if join else socket.IP_DROP_MEMBERSHIP,
                            group.packed + socket.inet_aton("0.0.0.0"))
        else:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP if join else socket.IPV6_LEAVE_GROUP,
                            group.packed + struct.pack("@I", 0))
        return a[WO]
    return run


NET_PRIMITIVES = [
    Builtin("待受開始する", [(WO, True), ("に", False)], _net_action("待受開始する", _listen)),
    Builtin("接続受付する", [("から", True)], _net_action("接続受付する", _accept)),
    Builtin("接続する", [("に", True), ("で", True)], _net_action("接続する", _connect)),
    Builtin("期限付き接続する", [("に", True), ("で", True), (WO, True)],
            _net_action("期限付き接続する", lambda net, a, line: _connect(net, a, line, "期限付き接続する"))),
    Builtin("行受信する", [("から", True)], _net_action("行受信する", _recv_line)),
    Builtin("受信する", [("から", True), (WO, True)], _net_action("受信する", _recv)),
    Builtin("バイト列受信する", [("から", True), (WO, True)], _net_action("バイト列受信する", _recv_bytes)),
    Builtin("送信する", [(WO, True), ("へ", True)], _net_action("送信する", _send)),
    Builtin("バイト列送信する", [(WO, True), ("へ", True)], _net_action("バイト列送信する", _send_bytes)),
    Builtin("切断する", [(WO, True)], _net_action("切断する", _close)),
    Builtin("待機時間設定する", [(WO, True), ("で", True)], _net_action("待機時間設定する", _set_timeout)),
    Builtin("UDP開始する", [(WO, True), ("に", False)], _net_action("UDP開始する", _udp_open)),
    Builtin("UDPバイト列送信する", [(WO, True), ("から", True), ("に", True), ("で", True)], _net_action("UDPバイト列送信する", _udp_send)),
    Builtin("UDPバイト列受信する", [("から", True)], _net_action("UDPバイト列受信する", _udp_recv)),
    Builtin("ポート取得する", [(WO, True)], _net_action("ポート取得する", _local_port)),
    Builtin("記述子取得する", [(WO, True)], _net_action("記述子取得する", _sock_fd)),
    Builtin("相手アドレス取得する", [(WO, True)], _net_action("相手アドレス取得する", _peer_addr)),
    Builtin("相手ポート取得する", [(WO, True)], _net_action("相手ポート取得する", _peer_port)),
    Builtin("ブロードキャスト許可する", [(WO, True)], _net_action("ブロードキャスト許可する", _broadcast)),
    Builtin("マルチキャスト参加する", [(WO, True), ("に", True)], _net_action("マルチキャスト参加する", _multicast(True))),
    Builtin("マルチキャスト離脱する", [(WO, True), ("から", True)], _net_action("マルチキャスト離脱する", _multicast(False))),
]


# ---------------------------------------------------------------------------
# スレッド(「スレッド」の組み込み)。Python の GIL があるので速くはならないが、書いたとおりに動く
# ---------------------------------------------------------------------------

THREAD_STACK = 256 << 20  # 深い再帰のために(仮想のメモリなので、使った分だけ実際に使う)


class _Sched:
    """スレッドどうしの待ち合わせ。通路と合流の状態は cv を持って変え、変えたら notify_all する"""

    import threading as _th

    cv = _th.Condition()
    alive: set = set()  # 動いているスレッド(と、プログラムを動かしているスレッド)
    waiting: dict = {}  # 通路や合流で待っているスレッド → 待つのを終えてよいか


def _sched_wait(ready: Any, line: int) -> None:
    """ready() が真になるまで待つ(cv を持って呼ぶ)。ほかのスレッドがみな待っていて進めないならエラー
    (外部の関数や入力で待っているスレッドは、そのうち進むかもしれないので数えない)"""
    import threading
    me = threading.get_ident()
    _Sched.alive.add(me)
    while not ready():
        others = [t for t in _Sched.alive if t != me]
        if all(t in _Sched.waiting and not _Sched.waiting[t]() for t in others):
            raise SuruError("すべてのスレッドが待っていて、先に進めません(通路や合流の待ち)", line)
        _Sched.waiting[me] = ready
        try:
            _Sched.cv.wait()
        finally:
            del _Sched.waiting[me]


def _start_thread(target: Any) -> Any:
    import threading

    def run() -> None:
        try:
            target()
        finally:
            with _Sched.cv:
                _Sched.alive.discard(threading.get_ident())
                _Sched.cv.notify_all()

    try:
        threading.stack_size(THREAD_STACK)
    except (ValueError, RuntimeError):
        pass
    th = threading.Thread(target=run, daemon=True)  # プログラムの終わりでは待たない(コンパイルしたものと同じ)
    with _Sched.cv:
        _Sched.alive.add(threading.get_ident())
        th.start()
        while th.ident is None:
            pass
        _Sched.alive.add(th.ident)
    return th


def _spawn(it: "Interpreter", a: dict, line: int) -> Any:
    m = a[WO]
    if not isinstance(m, ACTION_TYPES):
        raise SuruError(f"「並行開始する」の「を」は動作でなければなりません(「{format_value(m)}」が渡されました)", line)

    def perform(it2: "Interpreter") -> Any:
        box: dict = {}

        def run() -> None:
            try:
                box["value"] = it2.perform(m)
            except SuruError as e:  # このスレッドだけが終わる。文はその場で書く(1回の write でほかの行と混ざらないように)
                sys.stderr.write(f"エラー: {e}\n")
                sys.stderr.flush()
                box["error"] = True
            except RecursionError:
                sys.stderr.write("エラー: 再帰が深すぎます\n")
                sys.stderr.flush()
                box["error"] = True
            with _Sched.cv:
                box["done"] = True

        sys.stdout.flush()
        _start_thread(run)

        def join(it3: "Interpreter") -> Any:
            with _Sched.cv:
                _sched_wait(lambda: "done" in box, line)
            if "error" in box:
                raise SuruError("並行開始した動作はエラーで終わりました", line)
            return box["value"]

        # 動作の結果を動作にすると続けて行われてしまうので、「スレッド」の組(lib/スレッド.suru)で包む
        return Record(THREAD_CTOR, THREAD_NAME, (THREAD_FIELD,), (Action("合流する", join),))

    return Action("並行開始する", perform)


THREAD_CTOR, THREAD_FIELD = "スレッド", "中身"
CHAN_CTOR = "通路"


def _join(it: "Interpreter", a: dict, line: int) -> Any:
    t = a[WO]
    if not (isinstance(t, Record) and t.ctor == THREAD_CTOR):
        raise SuruError(f"「合流する」の「を」はスレッドでなければなりません(「{format_value(t)}」が渡されました)", line)
    return t.values[0]


def _pmap(it: "Interpreter", a: dict, line: int) -> Any:
    # 純粋な関数なので、順に計算しても結果は同じ(インタプリタは GIL で並列にならないので分けない)
    return tuple(it.apply(a["で"], [x], line) for x in _list(a[WO], "「並列写像する」の「を」", line))


def _ncpu(it: "Interpreter", a: dict, line: int) -> Any:
    return Action("コア数取得する", lambda it2: os.cpu_count() or 1)


class _Chan:
    """通路の中身(プロセスの中の列)。パイプなど別の種類も、同じ send・take・close の口で足す。
    状態は _Sched.cv を持って変える"""

    def __init__(self, cap: int) -> None:
        import collections
        self.cap, self.size = cap, max(cap, 1)
        self.items: Any = collections.deque()
        self.closed = False
        self.sent = self.taken = 0

    def __str__(self) -> str:
        return "<通路>"

    def send(self, x: Any, line: int) -> Any:
        with _Sched.cv:
            if self.closed:
                raise SuruError("閉じた通路には送れません", line)
            _sched_wait(lambda: self.closed or (len(self.items) < self.size and (self.cap > 0 or not self.items)), line)
            if self.closed:
                raise SuruError("閉じた通路には送れません", line)
            self.items.append(x)
            self.sent += 1
            my = self.sent
            _Sched.cv.notify_all()
            if self.cap == 0:  # 受け取られるまで待つ
                _sched_wait(lambda: self.taken >= my, line)
        return x

    def take(self, line: int) -> tuple:
        """(値があったか, 値)。閉じていて空なら (False, None)"""
        with _Sched.cv:
            _sched_wait(lambda: bool(self.items) or self.closed, line)
            if not self.items:
                return False, None
            x = self.items.popleft()
            self.taken += 1
            _Sched.cv.notify_all()
            return True, x

    def close(self) -> None:
        with _Sched.cv:
            self.closed = True
            _Sched.cv.notify_all()


class _PipeChan:
    """パイプの通路: fork したプロセスどうしで値を渡す。値は直列化して、長さ(4 バイト)を前に付けて書く。
    1つのプロセスでは向きは1つ: 初めて送ったら読む口を、初めて受け取ったら書く口を閉じる
    (書く口がすべて閉じると、受け取る側は「閉じた」と分かる)。runtime/suru_rt.c と同じ"""

    def __init__(self, it: "Interpreter", path: "str | None" = None) -> None:
        self.it = it
        self.path = path
        # 名前つきの通路(FIFO)は、初めて送る・受け取るときに開く(-2 はまだ開いていない口)
        self.r, self.w = (-2, -2) if path is not None else os.pipe()
        self.closed = False

    def __str__(self) -> str:
        return "<通路>"

    def _close(self, which: str) -> None:
        fd = getattr(self, which)
        if fd >= 0:
            os.close(fd)
        setattr(self, which, -1)

    def _open_end(self, which: str, other: str, flags: int, line: int) -> None:
        """まだ開いていない口を開き(相手が開くまで待つ)、もう一方の口は使わないことにする"""
        if self.path is None:
            self._close(other)
            return
        if getattr(self, other) == -2:
            setattr(self, other, -1)
        if getattr(self, which) != -2:
            return
        try:
            setattr(self, which, os.open(self.path, flags))
        except OSError as e:
            raise SuruError(f"名前つきの通路『{self.path}』を開けませんでした({e.strerror})", line) from None

    def send(self, x: Any, line: int) -> Any:
        if self.closed or self.w == -1:
            raise SuruError("閉じた通路には送れません", line)
        self._open_end("w", "r", os.O_WRONLY, line)
        d = _serialize(x, line)
        data = len(d).to_bytes(4, "little") + d
        # 名前つきなら書く人が何人もいるので、1つの値を書き終えるまでほかの人を待たせる
        if self.path is not None:
            _lock_fd(self.w, True)
        try:
            while data:
                data = data[os.write(self.w, data):]
        except BrokenPipeError:
            raise SuruError("受け取る相手がいないので、通路に送れません", line) from None
        except OSError as e:
            raise SuruError(f"通路に送れませんでした({e.strerror})", line) from None
        finally:
            if self.path is not None:
                _lock_fd(self.w, False)
        return x

    def _read(self, n: int, line: int) -> bytes:
        out = b""
        while len(out) < n:
            try:
                k = os.read(self.r, n - len(out))
            except OSError as e:
                raise SuruError(f"通路から受け取れませんでした({e.strerror})", line) from None
            if not k:
                break
            out += k
        return out

    def take(self, line: int) -> tuple:
        if self.r == -1:
            raise SuruError("この通路から受け取れません(このプロセスはこの通路に送っています)", line)
        self._open_end("r", "w", os.O_RDONLY, line)
        h = self._read(4, line)
        if not h:
            return False, None
        if len(h) < 4:
            raise SuruError("通路の値が途中で切れています", line)
        n = int.from_bytes(h, "little")
        d = self._read(n, line)
        if len(d) < n:
            raise SuruError("通路の値が途中で切れています", line)
        return True, _deserialize(self.it, d, line)

    def close(self) -> None:
        self._close("w")
        self.closed = True


def _fifo_chan(it: "Interpreter", p: Any, create: bool, line: int) -> Any:
    """名前つきの通路(FIFO)。作成なら、なければ作る。runtime/suru_rt.c の fifo_new・fifo_open と同じ"""
    name = "名前つき通路作成する" if create else "名前つき通路接続する"
    if not isinstance(p, str):
        raise SuruError(f"「{name}」の「を」は文字列でなければなりません(「{format_value(p)}」が渡されました)", line)
    try:
        st = os.stat(p)
    except OSError as e:
        if not create:
            raise SuruError(f"名前つきの通路『{p}』に接続できませんでした({e.strerror})", line) from None
        try:
            os.mkfifo(p, 0o600)
        except OSError as e2:
            raise SuruError(f"名前つきの通路『{p}』を作れませんでした({e2.strerror})", line) from None
    else:
        if not stat.S_ISFIFO(st.st_mode):
            if create:
                raise SuruError(f"『{p}』はすでにあり、名前つきの通路ではありません", line)
            raise SuruError(f"『{p}』は名前つきの通路ではありません", line)
    return Record(CHAN_CTOR, CHAN_CTOR, (THREAD_FIELD,), (_PipeChan(it, p),))


def _fifo_del(p: Any, line: int) -> int:
    if not isinstance(p, str):
        raise SuruError(f"「名前つき通路削除する」の「を」は文字列でなければなりません(「{format_value(p)}」が渡されました)", line)
    try:
        os.unlink(p)
    except OSError as e:
        raise SuruError(f"名前つきの通路『{p}』を消せませんでした({e.strerror})", line) from None
    return 0


def _need_chan(v: Any, what: str, line: int) -> _Chan:
    if not (isinstance(v, Record) and v.ctor == CHAN_CTOR and isinstance(v.values[0], (_Chan, _PipeChan))):
        raise SuruError(f"{what}は通路でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v.values[0]


def _chan_new(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        cap = _num(a["で"], line)
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            raise SuruError(f"「{format_value(a['で'])}」は通路の容量ではありません(0 以上の整数)", line)
        return Record(CHAN_CTOR, CHAN_CTOR, (THREAD_FIELD,), (_Chan(cap),))
    return Action("通路作成する", perform)


def _chan_recv(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        ok, x = _need_chan(a["から"], "「通路受信する」の「から」", line).take(line)
        if not ok:
            raise SuruError("通路は閉じていて、もう値がありません", line)
        return x
    return Action("通路受信する", perform)


def _chan_close(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        _need_chan(a[WO], "「通路閉鎖する」の「を」", line).close()
        return a[WO]
    return Action("通路閉鎖する", perform)


def _chan_each(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        c = _need_chan(a[WO], "「通路処理する」の「を」", line)
        k = 0
        while True:
            ok, x = c.take(line)
            if not ok:
                return k
            it2.perform(it2.apply(a["で"], [x], line))
            k += 1
    return Action("通路処理する", perform)


class _Gate:
    """ロック(owner と depth)と枠(free)。状態は _Sched.cv を持って変える"""

    def __init__(self, free: int = 0) -> None:
        self.owner: Any = None
        self.depth = 0
        self.free = free

    def __str__(self) -> str:
        return "<ロック>"


class _Box:
    """箱の中身。箱更新する は lock を持って計算して置きかえる"""

    def __init__(self, v: Any) -> None:
        import threading
        self.v = v
        self.lock = threading.Lock()

    def __str__(self) -> str:
        return "<箱>"


def _handle(ctor: str, obj: Any) -> Record:
    return Record(ctor, ctor, (THREAD_FIELD,), (obj,))


def _need_handle(v: Any, ctor: str, cls: Any, what: str, line: int) -> Any:
    if not (isinstance(v, Record) and v.ctor == ctor and isinstance(v.values[0], cls)):
        raise SuruError(f"{what}は{ctor}でなければなりません(「{format_value(v)}」が渡されました)", line)
    return v.values[0]


def _need_action(v: Any, what: str, line: int) -> None:
    if not isinstance(v, ACTION_TYPES):
        raise SuruError(f"{what}は動作でなければなりません(「{format_value(v)}」が渡されました)", line)


def _guarded(it: "Interpreter", m: Any, enter: Any, leave: Any) -> Any:
    """持っている間だけ m を行う。エラーで抜けても必ず手放す"""
    with _Sched.cv:
        enter()
    try:
        return it.perform(m)
    finally:
        with _Sched.cv:
            leave()
            _Sched.cv.notify_all()


def _locked(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        import threading
        g = _need_handle(a["で"], "ロック", _Gate, "「排他実行する」の「で」", line)
        _need_action(a[WO], "「排他実行する」の「を」", line)
        me = threading.get_ident()

        def enter() -> None:
            _sched_wait(lambda: g.owner is None or g.owner == me, line)
            g.owner = me
            g.depth += 1

        def leave() -> None:
            g.depth -= 1
            if g.depth == 0:
                g.owner = None
        return _guarded(it2, a[WO], enter, leave)
    return Action("排他実行する", perform)


def _slot_new(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        n = _num(a["で"], line)
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise SuruError(f"「{format_value(a['で'])}」は枠の数ではありません(1 以上の整数)", line)
        return _handle("枠", _Gate(n))
    return Action("枠作成する", perform)


def _slotted(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        g = _need_handle(a["で"], "枠", _Gate, "「枠内実行する」の「で」", line)
        _need_action(a[WO], "「枠内実行する」の「を」", line)

        def enter() -> None:
            _sched_wait(lambda: g.free > 0, line)
            g.free -= 1

        def leave() -> None:
            g.free += 1
        return _guarded(it2, a[WO], enter, leave)
    return Action("枠内実行する", perform)


def _box_update(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        b = _need_handle(a[WO], "箱", _Box, "「箱更新する」の「を」", line)
        with b.lock:  # 純粋な関数なので、持ったまま計算して置きかえる(ほかのスレッドとぶつからない)
            b.v = it2.apply(a["で"], [b.v], line)
            return b.v
    return Action("箱更新する", perform)


def _box_set(it: "Interpreter", a: dict, line: int) -> Any:
    def perform(it2: "Interpreter") -> Any:
        b = _need_handle(a["へ"], "箱", _Box, "「箱書込する」の「へ」", line)
        with b.lock:
            b.v = a[WO]
        return a[WO]
    return Action("箱書込する", perform)


THREAD_PRIMITIVES = [
    Builtin("並行開始する", [(WO, True)], _spawn),
    Builtin("合流する", [(WO, True)], _join),
    Builtin("並列写像する", [(WO, True), ("で", True)], _pmap),
    Builtin("コア数取得する", [], _ncpu),
    Builtin("通路作成する", [("で", True)], _chan_new),
    Builtin("プロセス間通路作成する", [], lambda it, a, line: Action(
        "プロセス間通路作成する", lambda it2: Record(CHAN_CTOR, CHAN_CTOR, (THREAD_FIELD,), (_PipeChan(it2),)))),
    Builtin("名前つき通路作成する", [(WO, True)], lambda it, a, line: Action(
        "名前つき通路作成する", lambda it2: _fifo_chan(it2, a[WO], True, line))),
    Builtin("名前つき通路接続する", [(WO, True)], lambda it, a, line: Action(
        "名前つき通路接続する", lambda it2: _fifo_chan(it2, a[WO], False, line))),
    Builtin("名前つき通路削除する", [(WO, True)], lambda it, a, line: Action(
        "名前つき通路削除する", lambda it2: _fifo_del(a[WO], line))),
    Builtin("通路送信する", [(WO, True), ("へ", True)],
            lambda it, a, line: Action("通路送信する", lambda it2: _need_chan(a["へ"], "「通路送信する」の「へ」", line).send(a[WO], line))),
    Builtin("通路受信する", [("から", True)], _chan_recv),
    Builtin("通路閉鎖する", [(WO, True)], _chan_close),
    Builtin("通路処理する", [(WO, True), ("で", True)], _chan_each),
    Builtin("ロック作成する", [], lambda it, a, line: Action("ロック作成する", lambda it2: _handle("ロック", _Gate()))),
    Builtin("排他実行する", [("で", True), (WO, True)], _locked),
    Builtin("枠作成する", [("で", True)], _slot_new),
    Builtin("枠内実行する", [("で", True), (WO, True)], _slotted),
    Builtin("箱作成する", [("で", True)], lambda it, a, line: Action("箱作成する", lambda it2: _handle("箱", _Box(a["で"])))),
    Builtin("箱読取する", [(WO, True)],
            lambda it, a, line: Action("箱読取する", lambda it2: _need_handle(a[WO], "箱", _Box, "「箱読取する」の「を」", line).v)),
    Builtin("箱更新する", [(WO, True), ("で", True)], _box_update),
    Builtin("箱書込する", [(WO, True), ("へ", True)], _box_set),
]


# ---------------------------------------------------------------------------
# 外部の関数(FFI)。インタプリタは ctypes で C の呼び出し規約の関数を呼ぶ
# ---------------------------------------------------------------------------

INT64_MIN, INT64_MAX = -(1 << 63), (1 << 63) - 1
MIN_COMPILED_INT, MAX_COMPILED_INT = -(1 << 62), (1 << 62) - 1  # コンパイルしたプログラムの整数の範囲
_FFI_LIBS: dict = {}


_NO_PKGCONFIG_LIBS = {"c", "m", "pthread", "dl", "rt"}  # どこにでもある C のライブラリ
_PKGCONFIG_CACHE: dict[str, str] = {}


def _pkgconfig_libdir(name: str) -> str:
    """短い名前のライブラリ(lib名前.so・.dylib)があるフォルダを、pkg-config の「lib名前」か「名前」の
    libdir から探す(Homebrew の /opt/homebrew/lib など)。見つからなければ ""。Go 版の PkgConfigLibDir と同じ"""
    import shutil
    import subprocess

    if name in _NO_PKGCONFIG_LIBS or "/" in name or "\\" in name:
        return ""
    if name in _PKGCONFIG_CACHE:
        return _PKGCONFIG_CACHE[name]
    found = ""
    pc = next((shutil.which(c) for c in (os.environ.get("PKG_CONFIG", ""), "pkg-config", "pkgconf") if c and shutil.which(c)), None)
    if pc:
        for module in (f"lib{name}", name):
            try:
                r = subprocess.run([pc, "--variable=libdir", module], capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                break
            d = r.stdout.strip()
            if r.returncode == 0 and d and any(os.path.exists(os.path.join(d, f"lib{name}{ext}")) for ext in (".so", ".dylib", ".a")):
                found = d
                break
    _PKGCONFIG_CACHE[name] = found
    return found


def _pkgconfig_lib_file(name: str) -> str | None:
    """pkg-config のフォルダにある lib名前 の共有ライブラリのファイル(なければ None)"""
    d = _pkgconfig_libdir(name)
    for ext in (".dylib", ".so") if sys.platform == "darwin" else (".so", ".dylib"):
        if d and os.path.exists(os.path.join(d, f"lib{name}{ext}")):
            return os.path.join(d, f"lib{name}{ext}")
    return None


def _default_lib_file(name: str) -> str:
    """見つからなかったライブラリの、OS ごとのふつうのファイル名"""
    if sys.platform == "win32":
        return f"{name}.dll"
    return f"lib{name}.so"


def _ffi_lib(path: str, line: int) -> Any:
    """ライブラリを開く(同じものは一度だけ)。短い名前(「m」)は OS の探し方で探し、なければ pkg-config で"""
    import ctypes
    import ctypes.util

    if path in _FFI_LIBS:
        return _FFI_LIBS[path]
    if sys.platform == "win32" and path in ("c", "m", "dl", "rt", "pthread"):
        path = "msvcrt"  # C の標準のライブラリは1つにまとまっている
    found = path if os.path.isabs(path) else ctypes.util.find_library(path) or _pkgconfig_lib_file(path) or _default_lib_file(path)
    try:
        lib = ctypes.CDLL(found, use_errno=True)
    except OSError as e:
        raise SuruError(f"外部のライブラリ「{path}」を開けません({e})", line) from None
    _FFI_LIBS[path] = lib
    return lib


# kumu の「Cソース」: プロジェクトと依存の C のソースを共有ライブラリにして、外部の関数を探すところに足す
# (cmd/kumu/csrc.go と同じ設定を読む。作ったものは kumu_home()/C/ に置き、中身が同じなら作り直さない)
_PROJECT_C: dict = {}  # プロジェクトのフォルダ → 開いたライブラリ(なければ None)
_FFI_BASE = [""]  # 動かしているプログラムのフォルダ(Interpreter.run が決める)


def _config_strings(path: str) -> dict:
    """組.suru の文字列か、それを と でつないだ項目(名前 → 文字列のリスト)"""
    try:
        with open(path, encoding="utf-8") as f:
            program = parse_program(f.read(), ParseContext())
    except (OSError, SuruError):
        return {}
    out = {}
    for s in program:
        if isinstance(s, Define) and isinstance(s.body, Str):
            out[s.name] = [s.body.value]
        elif isinstance(s, Define) and isinstance(s.body, ListLit) and all(isinstance(x, Str) for x in s.body.items):
            out[s.name] = [x.value for x in s.body.items]
    return out


def _expand_flags(items: list, key: str, project: str, line: int) -> list:
    """${名前} を環境変数にして、空白で分ける(Go の expandFlags と同じ)"""
    import re

    out = []
    for it in items:
        for name in re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", it):
            if name not in os.environ:
                raise SuruError(f"「{project}」の{key}「{it}」に使う環境変数「{name}」がありません", line)
        out.extend(re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.environ[m.group(1)], it).split())
    return out


def _project_root(base_dir: str) -> str | None:
    d = os.path.abspath(base_dir or ".")
    while True:
        if os.path.exists(os.path.join(d, PROJECT_CONFIG)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _project_c_lib(base_dir: str, line: int) -> Any:
    """base_dir のプロジェクトと依存の Cソース から作った共有ライブラリ(なければ None)"""
    import ctypes
    import hashlib
    import glob
    import shutil
    import subprocess

    root = _project_root(base_dir)
    if root is None:
        return None
    if root in _PROJECT_C:
        return _PROJECT_C[root]
    _PROJECT_C[root] = None
    dirs = [root] + [d for d in find_packages(root).values() if os.path.abspath(d) != root]
    units = []
    for d in dirs:
        cfg = _config_strings(os.path.join(d, PROJECT_CONFIG))
        name = (cfg.get("名前") or [os.path.basename(d)])[0]
        if cfg.get("Cソース") or cfg.get("リンク引数"):
            units.append((name, d, cfg.get("Cソース", []), _expand_flags(cfg.get("C引数", []), "C引数", name, line),
                          _expand_flags(cfg.get("リンク引数", []), "リンク引数", name, line)))
    if not units:
        return None
    cc = next((c for c in (os.environ.get("CC", ""), "clang", "cc") if c and shutil.which(c)), None)
    if cc is None:
        raise SuruError("Cソースを使うには C コンパイラ(clang)が必要です", line)
    h = hashlib.sha256(cc.encode())
    for name, d, srcs, cflags, links in units:
        h.update(("\0".join([name] + cflags + links)).encode())
        for src in srcs:
            path = os.path.join(d, *src.split("/"))
            try:
                with open(path, "rb") as f:
                    h.update(path.encode() + b"\0" + f.read())
            except OSError:
                raise SuruError(f"「{name}」のCソース「{src}」が読めません", line) from None
            for hp in sorted(glob.glob(os.path.join(os.path.dirname(path), "*.h"))):
                with open(hp, "rb") as f:
                    h.update(os.path.basename(hp).encode() + b"\0" + f.read())
    out_dir = os.path.join(kumu_home(), "C", h.hexdigest()[:16])
    so = os.path.join(out_dir, "libkumu_c.so")
    if not os.path.exists(so):
        os.makedirs(out_dir, exist_ok=True)
        objs, links_all = [], []
        for name, d, srcs, cflags, links in units:
            links_all += links
            for i, src in enumerate(srcs):
                obj = os.path.join(out_dir, f"{len(objs)}.o")
                r = subprocess.run([cc, "-O2", "-fPIC", "-c", os.path.join(d, *src.split("/")), "-o", obj] + cflags,
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    raise SuruError(f"「{name}」のCソース「{src}」のコンパイルに失敗しました:\n{r.stdout}{r.stderr}", line)
                objs.append(obj)
        tmp = f"{so}.{os.getpid()}.tmp"
        r = subprocess.run([cc, "-shared", "-o", tmp] + objs + links_all, capture_output=True, text=True)
        if r.returncode != 0:
            raise SuruError(f"Cソースの共有ライブラリを作れませんでした:\n{r.stdout}{r.stderr}", line)
        os.replace(tmp, so)
    _PROJECT_C[root] = ctypes.CDLL(so, use_errno=True)
    return _PROJECT_C[root]


def _ffi_symbol(ext: Extern, line: int) -> Any:
    import ctypes

    for path in ext.libs:
        lib = _ffi_lib(path, line)
        if hasattr(lib, ext.symbol):
            return getattr(lib, ext.symbol)
    own = _project_c_lib(_FFI_BASE[0], line)
    if own is not None and hasattr(own, ext.symbol):
        return getattr(own, ext.symbol)
    if "\0プロセス" not in _FFI_LIBS:  # libc などリンク済みのもの(Windows では C の標準のライブラリ)
        _FFI_LIBS["\0プロセス"] = ctypes.CDLL("msvcrt" if sys.platform == "win32" else None, use_errno=True)
    proc = _FFI_LIBS["\0プロセス"]
    if hasattr(proc, ext.symbol):
        return getattr(proc, ext.symbol)
    where = "・".join(f"「{p}」" for p in ext.libs) or "読み込んだライブラリ"
    raise SuruError(f"外部の関数「{ext.symbol}」が{where}に見つかりません", line)


def _ffi_ctype(t: str) -> Any:
    import ctypes

    return {"i64": ctypes.c_int64, "f64": ctypes.c_double, "f32": ctypes.c_float, "i32": ctypes.c_int32, "bool": ctypes.c_int32,
            "str": ctypes.c_char_p, "ptr": ctypes.c_void_p, "bytes": ctypes.c_char_p, "void": None}[t]


def _ffi_arg(t: str, v: Any, name: str, part: str, line: int) -> Any:
    def bad(want: str) -> SuruError:
        return SuruError(f"外部の関数「{name}」の「{part}」には{want}が必要です(「{format_value(v)}」が渡されました)", line)

    if t in ("i64", "i32"):
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if not isinstance(v, int) or isinstance(v, bool):
            raise bad("整数")
        lo, hi = (INT64_MIN, INT64_MAX) if t == "i64" else (-(1 << 31), (1 << 31) - 1)
        if not lo <= v <= hi:
            raise bad(f"{lo} から {hi} までの整数")
        return v
    if t in ("f64", "f32"):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise bad("数")
        return float(v)
    if t == "bool":
        if not isinstance(v, bool):
            raise bad("真偽")
        return 1 if v else 0
    if t == "str":
        if not isinstance(v, str):
            raise bad("文字列")
        data = v.encode("utf-8")
        if b"\0" in data:
            raise bad("途中に文字コード 0 を含まない文字列")
        return data
    if t == "bytes":
        if not isinstance(v, bytes):
            raise bad("バイト列")
        return v
    if not isinstance(v, Address):
        raise bad("番地")
    return v.value or None


def _ffi_result(t: str, r: Any, name: str, line: int) -> Any:
    if t == "void":
        return 0
    if t == "i64":
        if not MIN_COMPILED_INT <= r <= MAX_COMPILED_INT:
            raise SuruError(f"外部の関数「{name}」の値 {r} が大きすぎます(整数は ±{MAX_COMPILED_INT} までです)", line)
        return r
    if t == "i32":
        return int(r)
    if t in ("f64", "f32"):
        return float(r)
    if t == "bool":
        return r != 0
    if t == "str":
        return "" if r is None else r.decode("utf-8", "replace")
    return Address(r or 0)


def extern_builtin(d: Define) -> Builtin:
    """外部の関数の定義を、呼ぶと C の関数を呼ぶ組み込みにする(値が動作なら、行ったときに呼ぶ)"""
    ext: Extern = d.body
    parts = [p for p, _ in d.params]
    cfn: list = []

    names = [x for _, x in d.params]

    def call(a: dict, line: int) -> Any:
        import ctypes
        import threading

        if ext.main_thread and threading.current_thread() is not threading.main_thread():
            # インタプリタはプログラムを最初のスレッドで動かすので、別のスレッドからは呼べない
            raise SuruError(f"外部の関数「{d.name}」は主スレッドで呼ぶ関数なので、並行して動かしている処理からは呼べません"
                            "(インタプリタの制限です。コンパイルしたものでは呼べます)", line)
        if ext.pointer:
            k = names.index(ext.pointer)
            fp = a[parts[k]]
            if not isinstance(fp, Address) or fp.value == 0:
                raise SuruError(f"外部の関数「{d.name}」の「{parts[k]}」には関数の番地が必要です(「{format_value(fp)}」が渡されました)", line)
            ts = [t for i, t in enumerate(ext.params) if i != k]
            f = ctypes.CFUNCTYPE(_ffi_ctype(ext.result), *[_ffi_ctype(t) for t in ts], use_errno=True)(fp.value)
            args = [_ffi_arg(t, a[p], d.name, p, line) for i, (t, p) in enumerate(zip(ext.params, parts)) if i != k]
            ctypes.set_errno(0)
            return _ffi_result(ext.result, _ffi_invoke(f, args), d.name, line)
        if not cfn:
            f = _ffi_symbol(ext, line)
            if ext.cargs:
                f.argtypes = [ctypes.c_int64 if k == "定数" else _ffi_ctype(ext.params[v]) for k, v in ext.cargs]
            else:
                f.argtypes = [_ffi_ctype(t) for t in ext.params]
            f.restype = _ffi_ctype(ext.result)
            cfn.append(f)

        args = [_ffi_arg(t, a[p], d.name, p, line) for t, p in zip(ext.params, parts)]
        if ext.cargs:
            args = [v if k == "定数" else args[v] for k, v in ext.cargs]
        ctypes.set_errno(0)
        return _ffi_result(ext.result, _ffi_invoke(cfn[0], args), d.name, line)

    def act(a: dict, line: int) -> Any:
        # 動作の C の関数は、子のプロセスや C の stdio と表示の順が入れ替わらないよう、それまでの表示を出してから呼ぶ
        sys.stdout.flush()
        return call(a, line)

    if ext.action:
        return Builtin(d.name, [(p, True) for p in parts],
                       lambda it, a, line: Action(d.name, lambda it2: act(a, line)))
    return Builtin(d.name, [(p, True) for p in parts], lambda it, a, line: call(a, line))

# --- C から呼び戻す(「呼び戻し番地作成する」「通路送り番地作成する」。runtime/suru_rt.c の cb_* と同じ) ---
CB_SLOTS, CB_MAX_INT, CB_MAX_FLT = 32, 6, 8
CB_TYPES = {"数": "i64", "整数": "i32", "小数": "f64", "単精度": "f32", "真偽": "bool", "文字列": "str", "番地": "ptr"}
CB_RET_TYPES = {"数": "i64", "整数": "i32", "小数": "f64", "単精度": "f32", "真偽": "bool", "番地": "ptr", "無": "void"}
_CALLBACKS: dict = {}  # 番地 → (ctypes の関数, 値の返し方, 通路のパイプの口か None)
_CB_TLS = __import__("threading").local()  # depth: 外部の関数を呼んでいる途中か、error: 呼び戻しの中のエラー


def _cb_types(s: Any, fn: str, line: int) -> list:
    s = _str(s, f"「{fn}」の「で」", line)
    words = s.split()
    out = []
    for i, w in enumerate(words):
        if i % 2 == 1:
            if w != KW_TO or i == len(words) - 1:
                raise SuruError(f"「{s}」は「{fn}」の引数の型の並びではありません(数・整数・小数・単精度・真偽・文字列・番地を「と」でつなぎます)", line)
            continue
        if w not in CB_TYPES:
            raise SuruError(f"「{s}」は「{fn}」の引数の型の並びではありません(数・整数・小数・単精度・真偽・文字列・番地を「と」でつなぎます)", line)
        out.append(CB_TYPES[w])
        if sum(t not in ("f64", "f32") for t in out) > CB_MAX_INT or sum(t in ("f64", "f32") for t in out) > CB_MAX_FLT:
            raise SuruError(f"「{fn}」の引数の型が多すぎます(整数・番地などは {CB_MAX_INT} 個、小数・単精度は {CB_MAX_FLT} 個までです)", line)
    if not out:
        raise SuruError(f"「{fn}」の引数の型を1つ以上書いてください(「番地 と 数」)", line)
    return out


def _cb_family(ret: str) -> str:
    return ret if ret in ("f64", "f32") else "int"


def _cb_take(ret: str, line: int) -> None:
    fam = _cb_family(ret)
    if sum(1 for v in _CALLBACKS.values() if v[1] == fam) >= CB_SLOTS:
        raise SuruError(f"呼び戻しの番地が足りません(値の返し方ごとに {CB_SLOTS} 個までです。使わないものは「呼び戻し解放する」で放します)", line)


def _cb_die(msg: str) -> None:
    sys.stdout.flush()
    sys.stderr.write(f"エラー: {msg}\n")
    sys.stderr.flush()
    os._exit(1)


def _cb_value(t: str, x: Any) -> Any:
    if t in ("f64", "f32"):
        return float(x)
    if t == "bool":
        return x != 0
    if t == "str":
        return "" if x is None else x.decode("utf-8", "replace")
    if t == "ptr":
        return Address(x or 0)
    if not MIN_COMPILED_INT <= x <= MAX_COMPILED_INT:
        raise SuruError(f"整数が大きすぎます(コンパイルしたプログラムの整数は ±{MAX_COMPILED_INT} までです)", None)
    return x


def _ffi_invoke(f: Any, args: list) -> Any:
    """C の関数を呼ぶ。呼び戻しの中でエラーになったら、戻ってからそのエラーにする"""
    _CB_TLS.depth = getattr(_CB_TLS, "depth", 0) + 1
    try:
        r = f(*args)
    finally:
        _CB_TLS.depth -= 1
    err = getattr(_CB_TLS, "error", None)
    if err is not None and _CB_TLS.depth == 0:
        _CB_TLS.error = None
        raise err
    return r


def _cb_new(it: "Interpreter", f: Any, types: Any, ret: Any, line: int) -> Action:
    import ctypes

    if not isinstance(f, FUNCTION_TYPES):
        raise SuruError(f"「呼び戻し番地作成する」の「を」は関数でなければなりません(「{format_value(f)}」が渡されました)", line)
    ts = _cb_types(types, "呼び戻し番地作成する", line)
    r = _str(ret, "「呼び戻し番地作成する」の「に」", line)
    if r not in CB_RET_TYPES:
        raise SuruError(f"「{r}」は呼び戻しの値の型ではありません(数・整数・小数・単精度・真偽・番地・無のどれかです)", line)
    rt = CB_RET_TYPES[r]

    def callback(*cargs: Any) -> Any:
        if getattr(_CB_TLS, "depth", 0) <= 0:
            _cb_die("呼び戻しの番地が、外部の関数を呼んでいる途中ではないところ(ほかのスレッドなど)から呼ばれました"
                    "(ほかのスレッドからは「通路送り番地作成する」を使います)")
        if getattr(_CB_TLS, "error", None) is not None:
            return 0 if rt not in ("f64", "f32") else 0.0
        try:
            v = it.apply(f, [_cb_value(t, x) for t, x in zip(ts, cargs)], line)
            if isinstance(v, ACTION_TYPES):
                v = it.perform(v)
            if rt == "void":
                return None
            c = _ffi_arg(rt, v, "呼び戻し", WO, line)
            return c if rt != "ptr" else (c or 0)
        except SuruError as e:
            _CB_TLS.error = e
            return None if rt == "void" else 0.0 if rt in ("f64", "f32") else 0

    def perform(it2: "Interpreter") -> Address:
        _cb_take(rt, line)
        proto = ctypes.CFUNCTYPE(_ffi_ctype(rt), *[_ffi_ctype(t) for t in ts])
        cf = proto(callback)
        addr = ctypes.cast(cf, ctypes.c_void_p).value
        _CALLBACKS[addr] = (cf, _cb_family(rt), None)
        return Address(addr)
    return Action("呼び戻し番地作成する", perform)


def _cb_chan(sample: Any, chan: Any, types: Any, line: int) -> Action:
    import ctypes

    c = _need_chan(chan, "「通路送り番地作成する」の「へ」", line)
    ts = _cb_types(types, "通路送り番地作成する", line)
    if not isinstance(sample, Record) or len(sample.fields) != len(ts):
        raise SuruError(f"「通路送り番地作成する」の「を」は、フィールドが {len(ts)} 個の組でなければなりません(「{format_value(sample)}」が渡されました)", line)
    names = {v: k for k, v in CB_TYPES.items()}
    for i, (t, x) in enumerate(zip(ts, sample.values), 1):
        want = "真偽" if t == "bool" else "文字列" if t == "str" else "数"
        ok = isinstance(x, bool) if t == "bool" else isinstance(x, str) if t == "str" else (isinstance(x, (int, float)) and not isinstance(x, bool))
        if not ok:
            raise SuruError(f"見本の{i}番目のフィールド「{format_value(x)}」は{want}でなければなりません(型は「{names[t]}」。番地は番地数値にした数で届きます)", line)
    if not isinstance(c, _PipeChan) or c.path is not None or c.w < 0:
        raise SuruError("「通路送り番地作成する」の通路は、プロセス間通路作成する で作って、まだ受け取っていない通路にします", line)

    def perform(it2: "Interpreter") -> Address:
        _cb_take("void", line)
        fd = os.dup(c.w)

        def callback(*cargs: Any) -> None:
            vals = []
            for t, x in zip(ts, cargs):
                if t in ("f64", "f32"):
                    vals.append(float(x))
                elif t == "bool":
                    vals.append(x != 0)
                elif t == "str":
                    vals.append("" if x is None else x.decode("utf-8", "replace"))
                else:
                    vals.append(_signed_addr(x or 0) if t == "ptr" else x)
            d = _serialize(Record(sample.ctor, sample.type_name, sample.fields, tuple(vals)), line)
            data = len(d).to_bytes(4, "little") + d
            try:
                while data:
                    data = data[os.write(fd, data):]
            except OSError:
                pass  # 受け取る相手がいない: 捨てる

        cf = ctypes.CFUNCTYPE(None, *[_ffi_ctype(t) for t in ts])(callback)
        addr = ctypes.cast(cf, ctypes.c_void_p).value
        _CALLBACKS[addr] = (cf, "int", fd)
        return Address(addr)
    return Action("通路送り番地作成する", perform)


def _cb_free(p: Any, line: int) -> Action:
    a = _addr(p, "「呼び戻し解放する」の「を」", line)

    def perform(it: "Interpreter") -> int:
        if a.value not in _CALLBACKS:
            raise SuruError(f"「{format_value(a)}」は呼び戻しの番地ではありません(放したものか、作っていないもの)", line)
        _, _, fd = _CALLBACKS.pop(a.value)
        if fd is not None:
            os.close(fd)
        return 0
    return Action("呼び戻し解放する", perform)


STD_PRIMITIVES.extend([
    Builtin("呼び戻し番地作成する", [(WO, True), ("で", True), ("に", True)],
            lambda it, a, line: _cb_new(it, a[WO], a["で"], a["に"], line)),
    Builtin("呼び戻し解放する", [(WO, True)], lambda it, a, line: _cb_free(a[WO], line)),
])
THREAD_PRIMITIVES.append(Builtin("通路送り番地作成する", [(WO, True), ("へ", True), ("で", True)],
                                 lambda it, a, line: _cb_chan(a[WO], a["へ"], a["で"], line)))


# lib/ のファイルごとの組み込み(そのファイルの中と、読み込んだ側の「標準内の…」「通信内の…」で使える)
LIB_PRIMITIVES = {STD_PATH: STD_PRIMITIVES, NET_PATH: NET_PRIMITIVES, THREAD_PATH: THREAD_PRIMITIVES,
                  PRELUDE_PATH: PRELUDE_PRIMITIVES}

def make_global_env() -> Env:
    env = Env()
    for b in BUILTINS:
        env.vars[b.name] = b
    return env


# ---------------------------------------------------------------------------
# 評価
# ---------------------------------------------------------------------------


def bind(env: Env, pattern: Any, value: Any, part: str, fname: str, line: int) -> None:
    if isinstance(pattern, str):
        env.vars[pattern] = value
        return
    if not isinstance(value, tuple) or len(value) != len(pattern):
        got = f"{len(value)}個のリスト" if isinstance(value, tuple) else "1個の値"
        raise SuruError(
            f"「{fname}」の「{part}」には{len(pattern)}個の値が必要です(渡されたのは{got})", line
        )
    for name, v in zip(pattern, value):
        env.vars[name] = v


SHOWABLE = "表示可能"
TO_STRING = "文字列化する"
MAPPABLE = "写像可能"   # 関手: m を f で 写像する
MONAD = "連鎖可能"      # モナド: m を f で 連鎖する / x を 結果にする
MAP = "写像する"
BIND = "連鎖する"
UNIT = "結果にする"
F_PARAMS = [(WO, "m"), ("で", "f")]


def _run_key(node: Run) -> str:
    return f"\0した結果{id(node)}"


SUCCESS_SHAPES = ("成功", "有")  # 「した 中身」で中の値を取り出す形
FAILURE_SHAPES = ("失敗", "無")  # 「した 中身」でそのまま返す形
UNWRAP_TYPES = ("成否", "有無")


def is_top_unwrap_do(s: Any) -> bool:
    """一番外に書いた手順で、「した 中身」を使うもの(その結果が失敗ならエラーで終わる)"""
    return isinstance(s, Do) and any(r.unwrap for st in s.statements for r in collect_runs(st, []))


def check_top_failure(v: Any) -> None:
    """一番外の手順の結果が失敗なら、その詳細のエラーで終わる(Rust の main が Err を返したとき)"""
    if is_failure(v):
        raise SuruError(failure_detail(v))


def is_failure(v: Any) -> bool:
    return isinstance(v, Record) and v.type_name == "成否" and v.ctor == "失敗"


def add_trace(v: Any, run: Run) -> Any:
    """「した 中身」で失敗を返した場所(行と関数の名前)を、失敗の値の見えない経路に足す"""
    if not is_failure(v):
        return v
    return Record(v.ctor, v.type_name, v.fields, v.values, v.trace + (f"{int(run.line)}行目 {run.fn}",), v.notes)


ERROR_SITE = "(ここで実行時エラー)"


def caught_failure(e: "SuruError") -> Record:
    """「試行する」(で を省く)・「試算する」で受け止めた実行時エラーを失敗にする。起きた場所を経路の先頭に入れる"""
    trace = (_where(e.line) + ERROR_SITE,) if e.line else ()
    return Record("失敗", "成否", ("理由",), (e.message,), trace)


def failure_detail(v: Any) -> str:
    """失敗の詳細: 説明(外側から)、理由、経路(内側から)"""
    r = v.values[0]
    why = r if isinstance(r, str) else format_value(r)
    lines = [n + "のに失敗しました" for n in reversed(v.notes)] + [why]
    out = lines[0] + "".join("\n  原因: " + x for x in lines[1:])
    if v.trace:
        out += "\n  経路:" + "".join("\n    " + t for t in v.trace)
    return out


def _explain(it: Any, a: dict, line: int) -> Any:
    v, note = a[WO], _str(a["で"], "「失敗説明する」の「で」", line)
    if not is_failure(v):
        return v
    return Record(v.ctor, v.type_name, v.fields, v.values, v.trace, v.notes + (note,))


def _number_check(it: Any, a: dict, line: int) -> Any:
    """数にできれば 数 の 成功、できなければ エラーの文 の 失敗"""
    try:
        return Record("成功", "成否", ("値",), (_to_number(it, a, line),))
    except SuruError as e:
        return Record("失敗", "成否", ("理由",), (e.message,))


def _input_check(it: Any, a: dict, line: int) -> Any:
    """「入力確認する」: 1行読めれば 文字列 の 有、入力の終わり(Ctrl-D)なら 無 の動作"""
    prompt = it.format(a[WO]) if WO in a else ""

    def perform(it2: "Interpreter") -> Any:
        try:
            return Record("有", "有無", ("値",), (it2.read(prompt),))
        except EOFError:
            return Record("無", "有無", (), ())

    return Action("入力確認する", perform)


def _calc_try(it: Any, a: dict, line: int) -> Any:
    """「f を 試算する」: 引数を全部渡した関数の値 f を呼び、成功なら 値 の 成功、実行時エラーなら エラーの文 の 失敗"""
    f = a[WO]
    if not isinstance(f, FUNCTION_TYPES):
        raise SuruError(f"「試算する」の「を」は関数の値でなければなりません(「{format_value(f)}」が渡されました)", line)
    try:
        return Record("成功", "成否", ("値",), (it.call(f, {}, line),))
    except SuruError as e:
        return caught_failure(e)
    except RecursionError:
        return Record("失敗", "成否", ("理由",), ("再帰が深すぎます",))


def _detail(it: Any, a: dict, line: int) -> str:
    v = a[WO]
    if not is_failure(v):
        raise SuruError(f"「失敗詳細にする」の「を」は失敗の値でなければなりません(「{format_value(v)}」が渡されました)", line)
    return failure_detail(v)


class EarlyExit(Exception):
    """「…した 中身」が失敗(無)だったので、一番内側の関数からその値を返す"""

    def __init__(self, value: Any, line: Any):
        super().__init__("早期脱出")
        self.value = value
        self.line = line


def _call_name(call: Any) -> str:
    name = getattr(call, "name", "")
    return name[: -len(SURU)] if name.endswith(SURU) else name


def unwrap_value(v: Any, call: Any, line: Any) -> tuple[bool, Any]:
    """「した 中身」: 成功(有)なら (真, 中の値)、失敗(無)なら (偽, その値)。
    「xs の それぞれ を f した 中身」のリストは、全部が成功なら (真, 値のリスト)、そうでなければ (偽, 最初の失敗)"""
    if isinstance(v, tuple):
        out = []
        for e in v:
            ok, x = unwrap_value(e, call, line)
            if not ok:
                return False, x
            out.append(x)
        return True, tuple(out)
    if isinstance(v, Record) and v.type_name in UNWRAP_TYPES:
        if v.ctor in SUCCESS_SHAPES:
            return True, v.values[0]
        if v.ctor in FAILURE_SHAPES:
            return False, v
    raise SuruError(f"「{_call_name(call)}した 中身」: 「{format_value(v)}」は成否でも有無でもありません", line)


TOP_FN = "一番外"  # 関数の外の「した 中身」の経路の名前
LAMBDA_FN = "無名関数"


def name_unwraps(node: Any, fn: str = TOP_FN) -> None:
    """「した 中身」に、それを書いた一番内側の関数の名前を付ける(失敗の経路に使う)"""
    if isinstance(node, Define):
        if node.is_function:
            fn = node.name.split("\0")[-1]
    elif isinstance(node, Lambda):
        fn = LAMBDA_FN
    elif isinstance(node, Run):
        node.fn = fn
    if isinstance(node, (list, tuple)):
        for x in node:
            name_unwraps(x, fn)
    elif isinstance(node, dict):
        for x in node.values():
            name_unwraps(x, fn)
    elif hasattr(node, "__dataclass_fields__") and not isinstance(node, (Module, Token)):
        for f in node.__dataclass_fields__:
            name_unwraps(getattr(node, f), fn)


def pattern_names(pat: Any, out: set) -> set:
    """パターン(引数の名前・名前のリスト・形のパターン)が付ける名前"""
    if isinstance(pat, str):
        out.add(pat)
    elif isinstance(pat, PBind):
        out.add(pat.name)
    elif isinstance(pat, (list, tuple)):
        for x in pat:
            pattern_names(x, out)
    elif isinstance(pat, (PSeq, PCtor)):
        pattern_names(pat.items, out)
    elif isinstance(pat, PNamed):
        for _, x in pat.fields:
            pattern_names(x, out)
    return out


def resolve_param_calls(node: Any, local: frozenset) -> None:
    """「累 を 行 で 処理する」: 関数を受け取った引数(や局所の名前)「処理」を、名前+「する」で呼ぶ。
    同じ名前の局所の関数「処理する」があればそちらを使い、引数の名前は関数の外の定義より先に見る"""
    if isinstance(node, (Call, Ref)):
        stem = node.name[:-len(SURU)] if node.name.endswith(SURU) else ""
        if stem and node.name not in local and stem in local:
            node.name = stem
    elif isinstance(node, Define):
        if node.params:
            local = local | pattern_names([p for _, p in node.params], set())
    elif isinstance(node, Lambda):
        local = local | pattern_names([p for _, p in node.params], set())
    elif isinstance(node, (Block, Do)):
        local = local | {d.name for d in node.statements if isinstance(d, Define)}
    elif isinstance(node, Match):
        resolve_param_calls(node.subject, local)
        for pat, cond, expr in node.cases:
            inner = local | pattern_names(pat, set())
            resolve_param_calls(cond, inner)
            resolve_param_calls(expr, inner)
        resolve_param_calls(node.default, local)
        return
    if isinstance(node, (list, tuple)):
        for x in node:
            resolve_param_calls(x, local)
    elif isinstance(node, dict):
        for x in node.values():
            resolve_param_calls(x, local)
    elif hasattr(node, "__dataclass_fields__") and not isinstance(node, (Module, Token)):
        for f in node.__dataclass_fields__:
            resolve_param_calls(getattr(node, f), local)
def _has_run(node: Any) -> bool:
    """手順の文として行うところ(条件分岐の枝も含む。無名関数・手順・関数の定義の中は除く)に「した 結果」があるか"""
    if isinstance(node, (Lambda, Do, Module, Token)):
        return False
    if isinstance(node, Define):
        return not node.is_function and _has_run(node.body)
    if isinstance(node, Run):
        return True
    if isinstance(node, (list, tuple)):
        return any(_has_run(x) for x in node)
    if isinstance(node, dict):
        return any(_has_run(x) for x in node.values())
    if hasattr(node, "__dataclass_fields__"):
        return any(_has_run(getattr(node, f)) for f in node.__dataclass_fields__)
    return False


def _branch_if(node: Any) -> Any:
    """文の中の、枝に「した 結果」がある「もし」(If か Match。先に行うところから探す。なければ None)"""
    if isinstance(node, (Lambda, Do, Module, Token)):
        return None
    if isinstance(node, Define):
        return None if node.is_function else _branch_if(node.body)
    if isinstance(node, If):
        found = _branch_if(node.cond)
        if found is not None:
            return found
        return node if _has_run(node.then) or _has_run(node.other) else None
    if isinstance(node, Match):
        found = _branch_if(node.subject)
        if found is not None:
            return found
        return node if any(_has_run(e) for _, _, e in node.cases) or _has_run(node.default) else None
    if isinstance(node, (list, tuple)):
        items = list(node)
    elif isinstance(node, dict):
        items = list(node.values())
    elif hasattr(node, "__dataclass_fields__"):
        items = [getattr(node, f) for f in node.__dataclass_fields__]
    else:
        return None
    for x in items:
        found = _branch_if(x)
        if found is not None:
            return found
    return None


def _replace_node(node: Any, target: Any, repl: Any) -> Any:
    """node の中の target を repl にした木(変わったところだけ作り直す)"""
    if node is target:
        return repl
    if isinstance(node, (Lambda, Do, Module, Token)):
        return node
    if isinstance(node, list):
        out = [_replace_node(x, target, repl) for x in node]
        return node if all(a is b for a, b in zip(out, node)) else out
    if isinstance(node, tuple):
        out = tuple(_replace_node(x, target, repl) for x in node)
        return node if all(a is b for a, b in zip(out, node)) else out
    if isinstance(node, dict):
        out = {k: _replace_node(x, target, repl) for k, x in node.items()}
        return node if all(out[k] is node[k] for k in node) else out
    if hasattr(node, "__dataclass_fields__"):
        changes = {}
        for f in node.__dataclass_fields__:
            v = getattr(node, f)
            w = _replace_node(v, target, repl)
            if w is not v:
                changes[f] = w
        return dataclasses.replace(node, **changes) if changes else node
    return node


def split_branch_runs(node: Any) -> None:
    """手順の文の「もし」の枝に「した 結果」があれば、そこで手順を分ける:
    「…（もし c ならば A そうでなければ B）…」と残りの文は「もし c ならば 手順（…A…、残り） そうでなければ 手順（…B…、残り）」。
    選んだ枝の「した 結果」だけを行う"""
    if isinstance(node, Do):
        for i, s in enumerate(node.statements):
            t = _branch_if(s)
            if t is None:
                continue
            rest = node.statements[i + 1:]
            line = first_line_of(s) or node.line

            def branch(e: Any) -> Any:
                return Do([_replace_node(s, t, e)] + rest, line, io=node.io)

            if isinstance(t, If):
                split = If(t.cond, branch(t.then), branch(t.other))
            else:
                split = dataclasses.replace(t, cases=[(p, g, branch(e)) for p, g, e in t.cases],
                                            default=None if t.default is None else branch(t.default))
            node.statements = node.statements[:i] + [split]
            break
    if isinstance(node, (list, tuple)):
        for x in node:
            split_branch_runs(x)
    elif isinstance(node, dict):
        for x in node.values():
            split_branch_runs(x)
    elif hasattr(node, "__dataclass_fields__") and not isinstance(node, (Module, Token)):
        for f in node.__dataclass_fields__:
            split_branch_runs(getattr(node, f))


def has_pure_unwrap(node: Any) -> bool:
    """関数の本体として計算するところ(無名関数・手順・関数の定義の中は除く)に「した 中身」があるか"""
    if isinstance(node, (Lambda, Do)):
        return False
    if isinstance(node, Define):
        return not node.is_function and has_pure_unwrap(node.body)
    if isinstance(node, Run):
        return node.unwrap or has_pure_unwrap(node.call)
    if isinstance(node, (list, tuple)):
        return any(has_pure_unwrap(x) for x in node)
    if isinstance(node, dict):
        return any(has_pure_unwrap(x) for x in node.values())
    if hasattr(node, "__dataclass_fields__"):
        return any(has_pure_unwrap(getattr(node, f)) for f in node.__dataclass_fields__)
    return False


def collect_runs(node: Any, out: list) -> list:
    """文の中の「した 結果」を、先に行うものから順に集める(関数の本体や条件分岐の枝の中は除く)"""
    if isinstance(node, (Lambda, Do)):
        return out
    if isinstance(node, Define):
        if not node.is_function:
            collect_runs(node.body, out)
        return out
    if isinstance(node, If):
        return collect_runs(node.cond, out)
    if isinstance(node, Match):
        return collect_runs(node.subject, out)
    if isinstance(node, Run):
        collect_runs(node.call, out)
        out.append(node)
        return out
    if isinstance(node, (list, tuple)):
        for x in node:
            collect_runs(x, out)
    elif isinstance(node, dict):
        for x in node.values():
            collect_runs(x, out)
    elif hasattr(node, "__dataclass_fields__"):
        for f in node.__dataclass_fields__:
            collect_runs(getattr(node, f), out)
    return out


class Interpreter:
    def __init__(self, out: Any = None, read: Any = None, write: Any = None) -> None:
        self.out = out or print  # 「表示する」の出力先
        self.write = write or _write_stdout  # 「続表示する」の出力先(改行を付けない)
        self.read = read or input  # 「入力する」の入力元
        # shared は組み込み関数・形・性質の関数(どのファイルからも見える)。globals はこのプログラムの定義
        self.shared = make_global_env()
        self.globals = Env(self.shared)
        self.loaded: dict[str, Env] = {}  # 読み込んだファイル(絶対パス → その定義)
        self.ctx = ParseContext()
        self.traits: dict[str, dict] = {}  # 性質 → {関数名: (引数, 既定の実装 or None)}
        self.impls: dict[tuple[str, str], dict] = {}  # (性質, 型) → {関数名: Function}
        self.fixed: set[str] = set()  # 形の名前・性質の関数の名前(上書きできない)
        # 組み込みの性質「表示可能」: 実装しなくても全部の型が持つ。実装すると表示が変わる
        self.register_trait(TraitDecl(SHOWABLE, [(TO_STRING, [(WO, "x")])], [], 0))
        # 組み込みの性質「写像可能」「連鎖可能」。リストと動作が持つ
        self.register_trait(TraitDecl(MAPPABLE, [(MAP, F_PARAMS)], [], 0))
        self.register_trait(TraitDecl(MONAD, [(BIND, F_PARAMS), (UNIT, [(WO, "x")])], [], 0))
        unit = Builtin(UNIT, [(WO, True)], lambda it, a, line: Pure(a[WO]))
        self.traits[MONAD][UNIT] = ([(WO, "x")], unit)  # 結果にする は実装しなくてよい
        self.shared.vars[UNIT] = unit  # 「を」の型で選ばず、いつも中立の Pure を作る
        fmap = Builtin(MAP, [(WO, True), ("で", True)],
                       lambda it, a, line: it.fmap(a[WO], lambda v: it.apply(a["で"], [v], line), line))
        chain = Builtin(BIND, [(WO, True), ("で", True)],
                        lambda it, a, line: it.chain(a[WO], lambda v: it.apply(a["で"], [v], line), line))
        for tname in ("リスト", "動作"):
            self.impls[(MAPPABLE, tname)] = {MAP: fmap}
            self.impls[(MONAD, tname)] = {BIND: chain}

    def run(self, source: str, emit: Any = None) -> list[Any]:
        """プログラムを実行し、トップレベルの式の値のリストを返す。
        値が動作なら、その場で行う(結果はリストに入れない)。emit を渡すと値ができるたびに呼ぶ"""
        ctx = self.ctx.copy()
        program = parse_program(source, ctx)
        self.ctx = ctx
        return self.run_program(program, emit)

    def run_program(self, program: list, emit: Any = None, emit_stmt: Any = None) -> list[Any]:
        """解析済みのプログラムを実行する。emit_stmt を渡すと、値ができるたびに (値, 文) で呼ぶ"""
        _FFI_BASE[0] = self.ctx.base_dir  # Cソース(kumu)を探すプロジェクト
        self.load_program(program, self.globals)
        results = []
        for s in program:
            if isinstance(s, (Define,) + TOP_LEVEL_ONLY):
                continue
            try:
                v = self.eval(s, self.globals)
            except EarlyExit as e:
                raise SuruError("「した 中身」の失敗を返す先がありません(関数か手順の中で使ってください)", e.line) from None
            if isinstance(v, ACTION_TYPES):
                r = self.perform(v)
                if is_top_unwrap_do(s):
                    check_top_failure(r)
                continue
            results.append(v)
            if emit is not None:
                emit(v)
            if emit_stmt is not None:
                emit_stmt(v, s)
        return results

    def load_program(self, program: list, env: Env) -> None:
        """定義を先にすべて登録する(定義の順番は自由。相互再帰もできる)"""
        for stmt in program:
            if isinstance(stmt, Import):
                mod = self.load_module(stmt.module)
                for name, v in mod.vars.items():
                    if MODULE_SEP not in name and name not in stmt.module.private:
                        env.vars[stmt.module.name + MODULE_SEP + name] = v
                        if stmt.open:
                            env.vars[name] = v
        for stmt in program:
            if isinstance(stmt, TypeDef):
                self.register_type(stmt)
        for stmt in program:
            if isinstance(stmt, TraitDecl):
                self.register_trait(stmt, env)
        for stmt in program:
            if isinstance(stmt, TraitImpl):
                self.register_impl(stmt, env)
        for stmt in program:
            if isinstance(stmt, Define):
                if stmt.name in self.fixed:
                    raise SuruError(f"「{stmt.name}」は形か性質の関数の名前なので、定義し直せません", stmt.line)
                self.define(stmt, env)

    def load_module(self, module: Module) -> Env:
        """読み込んだファイルの定義を登録する(同じファイルは一度だけ)。型と性質はどこからも見える"""
        env = self.loaded.get(module.path)
        if env is None:
            env = self.loaded[module.path] = Env(self.shared)
            env.vars.update((b.name, b) for b in LIB_PRIMITIVES.get(module.path, ()))
            self.load_program(module.program, env)
        return env

    # --- 動作 -------------------------------------------------------------

    def perform(self, v: Any) -> Any:
        """動作を行って結果を返す(動作でない値はそのまま)"""
        while True:
            if isinstance(v, Action):
                if v.upos:  # ライブラリの関数が作った動作: その関数を呼んだ場所
                    old, _CALL.pos = call_pos(), v.upos
                    try:
                        v = v.perform(self)
                    finally:
                        _CALL.pos = old
                else:
                    v = v.perform(self)
                if not isinstance(v, ACTION_TYPES):
                    return v
                continue  # 「してから」の続きが返した動作も続けて行う
            if isinstance(v, Pure):
                return v.value
            return v

    def monad_impl(self, m: Any) -> dict | None:
        if isinstance(m, Record):
            return self.impls.get((MONAD, m.type_name))
        return None

    def is_monadic(self, v: Any) -> bool:
        return isinstance(v, ACTION_TYPES + (tuple,)) or self.monad_impl(v) is not None

    def coerce(self, r: Any, like: Any, line: int) -> Any:
        """「結果にする」で作った中立の値を、連鎖している相手(like)の型に合わせる"""
        if not isinstance(r, Pure):
            return r
        if isinstance(like, tuple):
            return (r.value,)
        fns = self.monad_impl(like)
        if fns is not None and UNIT in fns:
            return self.call(fns[UNIT], {WO: r.value}, line)
        return r

    def chain(self, m: Any, f: Any, line: int) -> Any:
        """m を行い(取り出し)、その結果を f(Python の関数)に渡す。モナドのバインド"""
        if isinstance(m, Pure):
            return f(m.value)
        if isinstance(m, Action):
            # 続きが返した動作は perform のループが続けて行う(入れ子にしないので、終わらない手順でもスタックが伸びない)
            return Action(m.name, lambda it: f(it.perform(m)))
        if isinstance(m, tuple):
            out: tuple = ()
            for x in m:
                r = self.coerce(f(x), m, line)
                if not isinstance(r, tuple):
                    raise SuruError(f"リストを連鎖するときは、続きもリストを返す必要があります(「{self.format(r)}」が返りました)", line)
                out += r
            return out
        fns = self.monad_impl(m)
        if fns is None:
            raise SuruError(f"「{self.format(m)}」は動作ではありません(性質「{MONAD}」を持っていません)", line)
        k = Builtin("続き", [(WO, True)], lambda it, a, l: it.coerce(f(a[WO]), m, line))
        return self.call(self.shared.vars[BIND], {WO: m, "で": k}, line)

    def fmap(self, m: Any, f: Any, line: int) -> Any:
        """m の結果に f を適用したもの(写像)"""
        if isinstance(m, Pure):
            return Pure(f(m.value))
        if isinstance(m, Action):
            return Action(m.name, lambda it: f(it.perform(m)))
        if isinstance(m, tuple):
            return tuple(f(x) for x in m)
        if isinstance(m, Record) and (MAPPABLE, m.type_name) in self.impls:
            k = Builtin("関数", [(WO, True)], lambda it, a, l: f(a[WO]))
            return self.call(self.shared.vars[MAP], {WO: m, "で": k}, line)
        if self.monad_impl(m) is not None:
            return self.chain(m, lambda v: Pure(f(v)), line)
        raise SuruError(f"「{self.format(m)}」は性質「{MAPPABLE}」を持っていません(「の 結果」が使えません)", line)

    def run_do(self, stmts: list, i: int, env: Env, line: int) -> Any:
        """手順の i 番目からを行う。「した 結果」は連鎖に、途中の文は「それから」に置きかえる"""
        s = stmts[i]
        runs = [r for r in collect_runs(s, []) if not self._has(env, _run_key(r))]
        if runs and runs[0].unwrap:
            r = runs[0]
            m = self.eval(r.call, env)

            def k_unwrap(v: Any) -> Any:
                ok, x = unwrap_value(v, r.call, r.line)
                if not ok:
                    return Pure(add_trace(x, r))  # 手順はここで終わり、失敗(無)を結果にする
                local = Env(env)
                local.vars[_run_key(r)] = x
                return self.run_do(stmts, i, local, line)

            if isinstance(m, ACTION_TYPES):
                return self.chain(m, k_unwrap, r.line)
            return k_unwrap(m)
        if runs:
            r = runs[0]
            m = self.eval(r.call, env)
            if not self.is_monadic(m):
                raise SuruError(f"「{r.call.name[:-len(SURU)]}した 結果」: 「{self.format(m)}」は動作ではありません", r.line)

            def k(v: Any) -> Any:
                local = Env(env)
                local.vars[_run_key(r)] = v
                return self.run_do(stmts, i, local, line)

            return self.chain(m, k, r.line)
        if isinstance(s, Define):
            local = Env(env)
            if s.is_function:
                self.define(s, local)
            else:
                local.vars[s.name] = self.eval(s.body, local)
            return self.run_do(stmts, i + 1, local, line)
        v = self.eval(s, env)
        if i == len(stmts) - 1:
            return v
        if not self.is_monadic(v):
            raise SuruError(f"手順の途中の文の値「{self.format(v)}」は動作ではありません", getattr(s, "line", line))
        return self.chain(v, lambda _: self.run_do(stmts, i + 1, env, line), line)

    @staticmethod
    def _has(env: Env, key: str) -> bool:
        e: Env | None = env
        while e is not None:
            if key in e.vars:
                return True
            e = e.parent
        return False

    def run_text(self, source: str) -> list[str]:
        """実行して、トップレベルの式の値を表示用の文字列で返す"""
        return [self.format(v) for v in self.run(source)]

    # --- 型と性質の登録 ---------------------------------------------------

    def register_type(self, td: TypeDef) -> None:
        for c, fields in td.ctors:
            if not fields:
                if c in self.shared.vars:
                    raise SuruError(f"形「{c}」は既に別の名前として使われています", td.line)
                self.shared.vars[c] = Record(c, td.name, (), ())
                self.fixed.add(c)

    def register_trait(self, decl: TraitDecl, env: Env | None = None) -> None:
        env = env or self.globals
        if decl.name in self.traits:
            raise SuruError(f"性質「{decl.name}」は既に定義されています", decl.line)
        methods: dict[str, tuple] = {}
        members = [(n, ps, None) for n, ps in decl.sigs] + [(d.name, d.params, d) for d in decl.defaults]
        for fname, params, d in members:
            if fname in methods:
                raise SuruError(f"性質「{decl.name}」の中で「{fname}」が2回書かれています", decl.line)
            if fname in self.shared.vars or fname in env.vars:
                raise SuruError(f"「{fname}」は既に使われている名前なので、性質の関数にできません", decl.line)
            default = Function(fname, d.params, d.body, env, in_library(d.line)) if d else None
            methods[fname] = (params, default)
        self.traits[decl.name] = methods
        for fname, (params, _) in methods.items():
            self.shared.vars[fname] = TraitMethod(fname, decl.name, params)
            self.fixed.add(fname)

    def register_impl(self, impl: TraitImpl, env: Env | None = None) -> None:
        env = env or self.globals
        trait = self.traits.get(impl.trait)
        if trait is None:
            raise SuruError(f"「{impl.trait}」という性質は定義されていません", impl.line)
        if impl.type_name not in self.ctx.types and impl.type_name not in BUILTIN_TYPES:
            raise SuruError(f"「{impl.type_name}」という型は定義されていません", impl.line)
        key = (impl.trait, impl.type_name)
        if key in self.impls:
            raise SuruError(f"「{impl.type_name} は {impl.trait}」が2回書かれています", impl.line)
        fns: dict[str, Function] = {}
        for d in impl.defs:
            if d.name not in trait:
                raise SuruError(f"「{d.name}」は性質「{impl.trait}」の関数ではありません", d.line)
            if d.name in fns:
                raise SuruError(f"「{d.name}」が2回定義されています", d.line)
            want = sorted(p for p, _ in trait[d.name][0])
            if sorted(p for p, _ in d.params) != want:
                raise SuruError(
                    f"「{d.name}」の助詞が性質「{impl.trait}」での宣言と違います(使う助詞: {'・'.join(want)})", d.line
                )
            fns[d.name] = Function(d.name, d.params, d.body, env, in_library(d.line))
        for fname, (_, default) in trait.items():
            if fname not in fns and default is None:
                raise SuruError(f"「{impl.type_name}」は性質「{impl.trait}」の「{fname}」を定義していません", impl.line)
        self.impls[key] = fns

    def dispatch(self, m: TraitMethod, args: dict, line: int) -> Any:
        """「を」の値(「を」を「a と b」で分解するなら最初の要素)の型で実装を選ぶ"""
        part, pat = next(((p, pat) for p, pat in m.params if p == WO), m.params[0])
        v = args[part]
        if not isinstance(pat, str) and isinstance(v, tuple) and v:
            v = v[0]
        tname = type_name_of(v)
        fns = self.impls.get((m.trait, tname))
        if fns is None:
            if m.trait == SHOWABLE:
                return self.format(args[part])
            raise SuruError(f"「{tname}」は性質「{m.trait}」を持っていません(「{m.name}」が使えません)", line)
        fn = fns.get(m.name) or self.traits[m.trait][m.name][1]
        return self.call(fn, args, line)

    def format(self, v: Any, nested: bool = False) -> str:
        """表示用の文字列。性質「表示可能」が実装されていれば「文字列化する」を使う"""
        fns = self.impls.get((SHOWABLE, type_name_of(v)))
        if fns is not None:
            s = self.call(fns[TO_STRING], {WO: v}, None)
            return s if isinstance(s, str) else format_value(s)
        return format_value(v, nested, lambda x: self.format(x, True))

    # --- パターンマッチ ---------------------------------------------------

    def match(self, pat: Any, v: Any, env: Env) -> bool:
        if isinstance(pat, PBind):
            env.vars[pat.name] = v
            return True
        if isinstance(pat, PValue):
            return self.eval(pat.expr, env) == v
        if isinstance(pat, PSeq):
            if not isinstance(v, tuple) or len(v) != len(pat.items):
                return False
            return all(self.match(p, x, env) for p, x in zip(pat.items, v))
        if isinstance(pat, PCtor):
            if not isinstance(v, Record) or v.ctor != pat.ctor:
                return False
            return all(self.match(p, x, env) for p, x in zip(pat.items, v.values))
        if isinstance(pat, PNamed):
            if pat.ctor is not None and (not isinstance(v, Record) or v.ctor != pat.ctor):
                return False
            for fname, p in pat.fields:
                if isinstance(v, Record) and fname in v.fields:
                    x = v.get(fname)
                elif isinstance(v, tuple) and v and fname in ("先頭", "残り"):
                    x = v[0] if fname == "先頭" else v[1:]
                else:
                    return False
                if not self.match(p, x, env):
                    return False
            return True
        raise SuruError(f"分からないパターン {pat!r}")

    def make_record(self, ctor: str, values: list, line: int) -> Record:
        type_name, fields = self.ctx.ctors[ctor]
        if len(values) == 1 and len(fields) >= 2 and isinstance(values[0], tuple) and len(values[0]) == len(fields):
            values = list(values[0])  # 「（3 と 4） の 点」
        if len(values) != len(fields):
            raise SuruError(f"「{ctor}」には{len(fields)}個の値が必要です(渡されたのは{len(values)}個)", line)
        return Record(ctor, type_name, tuple(fields), tuple(values))

    def truth(self, node: Any, env: Env, what: str) -> bool:
        v = self.eval(node, env)
        if not isinstance(v, bool):
            raise SuruError(f"「{what}」の条件は 真 か 偽 でなければなりません(「{self.format(v)}」でした)", getattr(node, "line", None))
        return v

    def define(self, d: Define, env: Env) -> None:
        if isinstance(d.body, Extern):
            env.vars[d.name] = extern_builtin(d)
        elif d.is_function:
            env.vars[d.name] = Function(d.name, d.params, d.body, env, in_library(d.line))
        else:
            env.vars[d.name] = Lazy(d.body, env)

    def force(self, v: Any) -> Any:
        """値の定義(Lazy)なら、初めて使うときに計算する。関数として呼ぶときも同じ(#141)"""
        if isinstance(v, Lazy):
            if not v.done:
                v.value, v.done = self.eval(v.expr, v.env), True
            return v.value
        return v

    def eval(self, node: Any, env: Env) -> Any:
        if isinstance(node, Num):
            return node.value
        if isinstance(node, Str):
            return node.value
        if isinstance(node, Var):
            return self.force(env.lookup(node.name, node.line))
        if isinstance(node, ListLit):
            return tuple(self.eval(i, env) for i in node.items)
        if isinstance(node, Prop):
            return get_prop(self.eval(node.target, env), node.name, node.line)
        if isinstance(node, Field):
            target = self.eval(node.target, env)
            if node.name == RESULT and not isinstance(target, Record) and self.is_monadic(target):
                raise SuruError(
                    "「の 結果」は「入力 の 結果 を 数値にする」のように呼び出しの引数に書いてください", node.line
                )
            return get_field(target, node.name, node.line)
        if isinstance(node, Chain):
            m = self.eval(node.call, env)
            if not self.is_monadic(m):
                raise SuruError(f"「してから」の前の「{self.format(m)}」は動作ではありません(純粋な値なら「して」を使います)", node.line)

            def k(v: Any) -> Any:
                local = Env(env)
                local.vars[HOLE] = v
                return self.eval(node.cont, local)

            return self.chain(m, k, node.line)
        if isinstance(node, Run):
            key = _run_key(node)
            e: Env | None = env
            while e is not None:
                if key in e.vars:
                    return e.vars[key]
                e = e.parent
            if node.unwrap:
                ok, x = unwrap_value(self.eval(node.call, env), node.call, node.line)
                if not ok:
                    raise EarlyExit(add_trace(x, node), node.line)
                return x
            raise SuruError(
                "「した 結果」は手順の文の中で使ってください(関数の本体や条件分岐の枝の中では、そこを「手順（…）」で囲みます)",
                node.line,
            )
        if isinstance(node, Do):
            v = self.run_do(node.statements, 0, Env(env), node.line)
            return v if self.is_monadic(v) else Pure(v)
        if isinstance(node, Construct):
            return self.make_record(node.ctor, [self.eval(i, env) for i in node.items], node.line)
        if isinstance(node, NamedConstruct):
            fields = self.ctx.ctors[node.ctor][1]
            given = {f: e for f, e in node.fields}
            for f in given:
                if f not in fields:
                    raise SuruError(f"「{node.ctor}」には「{f}」というフィールドがありません", node.line)
            for f in fields:
                if f not in given:
                    raise SuruError(f"「{node.ctor}」の「{f}」が書かれていません", node.line)
            return self.make_record(node.ctor, [self.eval(given[f], env) for f in fields], node.line)
        if isinstance(node, Update):
            target = self.eval(node.target, env)
            values = list(target.values) if isinstance(target, Record) else []
            for f, e in node.fields:
                if not isinstance(target, Record) or f not in target.fields:
                    raise SuruError(f"「{format_value(target)}」には「{f}」というフィールドがありません", node.line)
                values[target.fields.index(f)] = self.eval(e, env)
            return Record(target.ctor, target.type_name, target.fields, tuple(values))
        if isinstance(node, Match):
            v = self.eval(node.subject, env)
            for pat, guard, body in node.cases:
                local = Env(env)
                if self.match(pat, v, local) and (guard is None or self.truth(guard, local, KW_KATSU)):
                    return self.eval(body, local)
            if node.default is not None:
                return self.eval(node.default, env)
            if node.fname:
                raise SuruError(f"「{self.format(v)}」は「{node.fname}」のどの定義にも当てはまりません", node.line)
            raise SuruError(f"「{self.format(v)}」はどの場合にも当てはまりません", node.line)
        if isinstance(node, Each):
            return _list(self.eval(node.target, env), "「の それぞれ」の前", node.line)
        if isinstance(node, Not):
            return not self.truth(node.operand, env, DENAI)
        if isinstance(node, Neg):
            return -_num(self.eval(node.operand, env), None)
        if isinstance(node, BinOp) and node.op in (KW_KATSU, KW_MATAHA):
            # 左が決まれば右は計算しない
            left = self.truth(node.left, env, node.op)
            if left == (node.op == KW_MATAHA):
                return left
            return self.truth(node.right, env, node.op)
        if isinstance(node, BinOp):
            return apply_op(node.op, self.eval(node.left, env), self.eval(node.right, env), node.line)
        if isinstance(node, If):
            cond = self.eval(node.cond, env)
            return self.eval(node.then if cond else node.other, env)
        if isinstance(node, Call):
            fn = self.force(env.lookup(node.name, node.line))
            args = {}
            lifted = []  # 「入力 の 結果 を …」: 動作の結果に関数を適用する(写像)
            for p, a in node.args.items():
                if isinstance(a, Field) and a.name == RESULT:
                    t = self.eval(a.target, env)
                    if not (isinstance(t, Record) and RESULT in t.fields):
                        args[p] = t
                        lifted.append(p)
                        continue
                args[p] = self.eval(a, env)
            each = [p for p, a in node.args.items() if isinstance(a, Each)]
            if lifted:
                if each:
                    raise SuruError("「の 結果」と「の それぞれ」は1つの呼び出しに一緒に書けません", node.line)
                return self.lift_call(fn, args, lifted, node.line)
            if not each:
                return self.call(fn, args, node.line)
            # 「リスト の それぞれ を 三倍する」: 要素ごとに呼び出す
            lengths = {len(args[p]) for p in each}
            if len(lengths) > 1:
                raise SuruError("「それぞれ」のリストの長さがそろっていません", node.line)
            return tuple(
                self.call(fn, {**args, **{p: args[p][i] for p in each}}, node.line)
                for i in range(lengths.pop())
            )
        if isinstance(node, Ref):
            fn = self.force(env.lookup(node.name, node.line))
            if not isinstance(fn, FUNCTION_TYPES):
                raise SuruError(f"「{node.name}」は関数ではありません", node.line)
            if not node.args:
                return fn
            args = {p: self.eval(a, env) for p, a in node.args.items()}
            return self.partial(fn, args, node.line)
        if isinstance(node, Lambda):
            return Function("無名関数", node.params, node.body, env, in_library(node.line))
        if isinstance(node, Block):
            local = Env(env)
            for s in node.statements:
                if isinstance(s, Define):
                    self.define(s, local)
            # 「した 中身」を使う値の定義は、使うときでなく、書いた順にここで計算する
            for s in node.statements:
                if isinstance(s, Define) and not s.is_function and has_pure_unwrap(s.body):
                    local.vars[s.name] = self.eval(s.body, local)
            result = None
            for s in node.statements:
                if not isinstance(s, Define):
                    result = self.eval(s, local)
            return result
        raise SuruError(f"評価できない構文 {node!r}")

    def lift_call(self, fn: Any, args: dict, lifted: list, line: int) -> Any:
        """「の 結果」の引数が1つなら写像、2つ以上なら前のものから順に連鎖して最後を写像する"""
        p, rest = lifted[0], lifted[1:]
        if not rest:
            return self.fmap(args[p], lambda v: self.call(fn, {**args, p: v}, line), line)
        return self.chain(args[p], lambda v: self.lift_call(fn, {**args, p: v}, rest, line), line)

    def slots_of(self, fn: Any, line: int) -> list[tuple[str, bool]]:
        if not isinstance(fn, FUNCTION_TYPES):
            raise SuruError(f"「{format_value(fn)}」は関数ではありません", line)
        return fn.slots()

    def partial(self, fn: Any, args: dict, line: int) -> Any:
        slots = dict(self.slots_of(fn, line))
        for p in args:
            if p not in slots:
                raise SuruError(f"「{fn.name}」は「{p}」の引数を受け取りません", line)
        if isinstance(fn, Partial):
            return Partial(fn.fn, {**fn.bound, **args})
        return Partial(fn, args)

    def apply(self, fn: Any, values: list, line: int) -> Any:
        """関数の値に、まだ渡していない引数を定義の順に埋めて呼び出す。足りなければ部分適用"""
        slots = self.slots_of(fn, line)
        if len(values) > len(slots):
            raise SuruError(f"「{fn.name}」に渡す値が多すぎます", line)
        args = {p: v for (p, _), v in zip(slots, values)}
        if any(req and p not in args for p, req in slots):
            return self.partial(fn, args, line)
        return self.call(fn, args, line)

    def call(self, fn: Any, args: dict, line: int) -> Any:
        if isinstance(fn, Partial):
            dup = set(fn.bound) & set(args)
            if dup:
                raise SuruError(f"「{fn.name}」の「{dup.pop()}」は既に渡されています", line)
            return self.call(fn.fn, {**fn.bound, **args}, line)
        if not isinstance(fn, (Function, Builtin, TraitMethod)):
            raise SuruError(f"「{format_value(fn)}」は関数ではありません", line)
        slots = fn.slots()
        names = {p for p, _ in slots}
        for p in args:
            if p not in names:
                raise SuruError(f"「{fn.name}」は「{p}」の引数を受け取りません", line)
        for p, req in slots:
            if req and p not in args:
                raise SuruError(f"「{fn.name}」には「{p}」の引数が必要です", line)
        if isinstance(fn, Builtin):
            return fn.fn(self, args, line)
        if isinstance(fn, TraitMethod):
            return self.dispatch(fn, args, line)
        if fn.lib and is_user_pos(line):
            # 自分のプログラムからライブラリの関数を呼ぶ: その中の実行時エラーは、ここの位置で出す(#154)
            old, _CALL.pos = call_pos(), line
            try:
                return self.call_function(fn, args, line)
            finally:
                _CALL.pos = old
        return self.call_function(fn, args, line)

    def call_function(self, fn: Function, args: dict, line: int) -> Any:
        local = Env(fn.closure)
        for p, pat in fn.params:
            bind(local, pat, args[p], p, fn.name, line)
        try:
            result = self.eval(fn.body, local)
        except EarlyExit as e:
            return e.value
        if is_predicate(fn.name) and not isinstance(result, bool):
            raise SuruError(f"述語「{fn.name}」は 真 か 偽 を返す必要があります(「{self.format(result)}」が返りました)", line)
        return result


def _call_site() -> str:
    """「呼出場所取得する」: 自分のプログラムからライブラリの関数を呼んでいる場所(「「計算.suru」の6行目 3文字目」。なければ空)"""
    p = call_pos()
    return f"{_file_of(p)}{_where(p)}" if p else ""


def run(source: str) -> list[Any]:
    return Interpreter().run(source)


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------


# 行がこの言葉で終われば、字下げした続きの行があるとみなし、空行で確定する
REPL_BLOCK = (KW_TOWA, KW_GA, KW_THEN, KW_ELSE)
# 行がこの言葉で終われば、次の行に続く
REPL_CONTINUE = (KW_PROVISO, KW_SOREKARA, KW_TO, KW_KATSU, KW_MATAHA)
# 対話モードのコマンド(「:」か全角の「：」で始める)。名前 → (別の名前, 説明)
REPL_COMMANDS = {
    "助け": (("help", "?"), "使い方を表示する"),
    "型": (("type", "t"), "式の型を表示する(実行はしない)  例: :型 3 を 二乗する"),
    "読む": (("load", "l"), "ファイルを読んで、その定義を使えるようにする  例: :読む 例.suru"),
    "一覧": (("names",), "この対話で定義した名前と型を表示する"),
    "終わる": (("quit", "q", "exit"), "対話モードを終わる(Ctrl-D でも終わる)"),
}
REPL_KEEP = (Define, TypeDef, TraitDecl, TraitImpl, TypeSig, Import, ExternLib)  # 次の入力の型の検査に残す文


def history_path() -> str:
    """対話モードの履歴を置くファイル。SURU_HISTORY で変えられる"""
    if os.environ.get("SURU_HISTORY"):
        return os.environ["SURU_HISTORY"]
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "suru", "history")


def _paren_depth(text: str) -> int:
    """文字列・名前・コメントの外で、閉じていない括弧の数"""
    depth, i, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c in ("「", NAME_OPEN):
            j = find_string_close(text, i) if c == "「" else text.find(NAME_CLOSE, i + 1)
            if j < 0:
                return depth + 1  # 文字列が閉じていない
            i = j + 1
            continue
        if c in COMMENT_STARTS:
            j = text.find("\n", i)
            if j < 0:
                break
            i = j
        elif c in OPEN_PARENS:
            depth += 1
        elif c in CLOSE_PARENS:
            depth -= 1
        i += 1
    return depth


def _ika_open(lines: list[Line]) -> bool:
    """「以上」で閉じていない「以下の手順です」があるか(対話モードで入力を待つため)。
    場合分けがまだ開いていれば、その後の「以上」は場合分けを閉じる「以上」と見る"""
    stack: list[tuple[str, int]] = []  # ("手順" か "場合", 字下げ)
    for ln in lines:
        if not nosep(ln.tokens):
            continue
        while stack and stack[-1][0] == "場合" and stack[-1][1] >= ln.indent:
            stack.pop()  # 字下げで閉じた場合分け(場合分けを閉じる「以上」は場合と同じ深い行)
        if is_ijou(ln):
            if stack:
                stack.pop()
        elif opens_ika(ln) or opens_ext_block(ln) or opens_export_block(ln):
            stack.append(("手順", ln.indent))
        elif opens_case(ln):
            stack.append(("場合", ln.indent))
    return any(kind == "手順" for kind, _ in stack)


class Repl:
    """対話モード。1つの入力(1行か、空行までの複数行)ごとに、型を調べてから実行し、値と型を表示する"""

    def __init__(self, checking: bool = True, out: Any = None) -> None:
        self.interp = Interpreter()
        self.interp.ctx.base_dir = os.getcwd()
        self.checking = checking
        self.out = out or print
        self.kept: list = []  # これまでに通った定義(次の入力の型の検査に使う)
        self.defined: list[str] = []  # この対話で定義した名前(定義した順)

    # --- 入力のまとまり ------------------------------------------------

    @staticmethod
    def complete(buf: list[str]) -> bool:
        """ここまでの行で1つの入力として確定するか"""
        text = "\n".join(buf)
        if _paren_depth(text) > 0:
            return False
        try:
            lines = split_lines(text)
        except SuruError as e:
            if QUASI_UNCLOSED in e.message:
                return False  # 「以下は【道】です」の「以上です」がまだない
            lines = []
        if _ika_open(lines):
            return False  # 「以下の手順です」の「以上」がまだない
        if is_punct_line(text):
            # 句読点の書き方: 「。」で終わるまで読む
            return text.rstrip().endswith(PERIOD) or not text.strip()
        first = buf[0].split()
        if first and first[-1] in REPL_BLOCK:
            return len(buf) > 1 and not buf[-1].strip()  # 字下げした続きの行は空行で確定
        last = buf[-1].split()
        return not (last and last[-1] in REPL_CONTINUE)

    # --- 実行 ------------------------------------------------------------

    def feed(self, source: str, base_dir: str | None = None) -> bool:
        """1つの入力を実行して結果を表示する。うまくいけば True。
        base_dir を渡すとファイルの読み込み(読み込むファイルはそこから探し、定義の型は表示しない)"""
        if not source.strip():
            return True
        try:
            return self._feed(source, base_dir)
        except SuruError as e:
            self.out(format_error(e, source))
        except RecursionError:
            self.out("エラー: 再帰が深すぎます")
        except KeyboardInterrupt:
            self.out("中断しました")
        return False

    def _parse(self, source: str, base_dir: str | None) -> tuple:
        ctx = self.interp.ctx.copy()
        if base_dir is not None:
            ctx.base_dir = base_dir
        return drop_tests(parse_program(source, ctx)), ctx  # 対話モードでは試験のまとまりと例を使わない(#193)

    def _check(self, program: list, ctx: ParseContext) -> tuple[dict, list]:
        """型を調べて、(式の文の id → 型, 新しい定義の型の宣言) を返す"""
        if not self.checking:
            return {}, []
        from suru_check import session_types

        names = [s.name for s in program if isinstance(s, Define)]
        # 定義し直した名前は、前の定義を外して調べる(対話モードでは後の定義で置き換わる)
        old = [s for s in self.kept if not (isinstance(s, (Define, TypeSig)) and s.name in names)]
        values = [s for s in program if not isinstance(s, (Define,) + TOP_LEVEL_ONLY)]
        try:
            types, sigs = session_types(old + program, ctx, values, list(dict.fromkeys(names)))
        except Exception as e:  # suru_check は suru を別のモジュールとして読み込むので、名前で見分ける
            if type(e).__name__ != "SuruError":
                raise
            raise SuruError(e.message, e.line) from None
        return {id(s): t for s, t in zip(values, types)}, sigs

    def _feed(self, source: str, base_dir: str | None) -> bool:
        program, ctx = self._parse(source, base_dir)
        types, sigs = self._check(program, ctx)
        names = [s.name for s in program if isinstance(s, Define)]
        if base_dir is not None:
            ctx.base_dir = self.interp.ctx.base_dir
        self.interp.ctx = ctx
        self.kept = [s for s in self.kept if not (isinstance(s, (Define, TypeSig)) and s.name in names)]
        self.kept += [s for s in program if isinstance(s, REPL_KEEP)]
        self._remember(source, program)
        for n in names:
            if n in self.defined:
                self.defined.remove(n)
            self.defined.append(n)
        if base_dir is None:
            for sig in sigs:
                self.out(sig)

        def show(v: Any, s: Any) -> None:
            text = self.interp.format(v)
            t = types.get(id(s))
            self.out(f"{text} は {t}" if t else text)

        self.interp.run_program(program, emit_stmt=show)
        return True

    def _remember(self, source: str, program: list) -> None:
        """次の入力の準クォートと導出のために、読み込んだファイルと型の定義の行を覚える"""
        ctx = self.interp.ctx
        for s in program:
            if isinstance(s, Import) and all(m.path != s.module.path for m in ctx.session_modules):
                ctx.session_modules = ctx.session_modules + [s.module]
        tds = [n for n in build_layout(split_lines(source))
               if n.line.quasi is None and n.line.derive is None and try_parse_typedef(n) is not None]
        if tds:
            ctx.session_nodes = tds + ctx.session_nodes

    # --- コマンド --------------------------------------------------------

    def command(self, line: str) -> bool:
        """「:型 …」などを行う。終わるなら False"""
        parts = line.strip()[1:].replace("　", " ").strip().split(None, 1)
        name = parts[0] if parts else ""
        arg = line.strip()[1:].strip(" 　")[len(name):].strip(" 　") if parts else ""
        cmd = next((k for k, (alts, _) in REPL_COMMANDS.items() if name == k or name in alts), None)
        if cmd is None:
            self.out(f"エラー: 「:{name}」というコマンドはありません(:助け で一覧を表示します)")
        elif cmd == "終わる":
            return False
        elif cmd == "助け":
            self.out(self.help_text())
        elif cmd == "型":
            self.show_type(arg)
        elif cmd == "読む":
            self.load(arg)
        elif cmd == "一覧":
            self.show_names()
        return True

    @staticmethod
    def help_text() -> str:
        lines = ["式を入力すると、型を調べてから実行し、「値 は 型」を表示します。",
                 "「とは」などで終わる行は続きがあるとみなし、空行で確定します。句読点の書き方は「。」で確定します。",
                 "定義し直すと、前の定義と置き換わります。Ctrl-C で入力の取り消しや実行の中断ができます。",
                 "コマンド(「:」は全角の「：」でも可):"]
        for k, (alts, desc) in REPL_COMMANDS.items():
            lines.append(f"  :{k}(:{' :'.join(alts)})  {desc}")
        return "\n".join(lines)

    def show_type(self, source: str) -> None:
        if not source:
            self.out("使い方: :型 式")
            return
        try:
            program, ctx = self._parse(source, None)
            checking, self.checking = self.checking, True
            try:
                types, sigs = self._check(program, ctx)
            finally:
                self.checking = checking
        except SuruError as e:
            self.out(format_error(e, source))
            return
        for sig in sigs:
            self.out(sig)
        for t in types.values():
            self.out(t)

    def load(self, path: str) -> None:
        if not path:
            self.out("使い方: :読む ファイル.suru")
            return
        path = os.path.expanduser(path.strip("「」\"'"))
        if not os.path.exists(path) and os.path.exists(path + SOURCE_SUFFIX):
            path += SOURCE_SUFFIX
        try:
            with open(path, encoding="utf-8") as f:
                source = f.read()
        except FileNotFoundError:
            self.out(f"エラー: ファイル「{path}」が見つかりません")
            return
        except (OSError, UnicodeDecodeError):
            self.out(f"エラー: ファイル「{path}」を読めません")
            return
        before = len(self.defined)
        if self.feed(source, os.path.dirname(os.path.abspath(path))):
            self.out(f"「{path}」を読みました(:一覧 で定義した名前と型を表示します)" if len(self.defined) > before
                     else f"「{path}」を読みました")

    def show_names(self) -> None:
        if not self.defined:
            self.out("まだ何も定義していません")
            return
        if not self.checking:
            self.out("\n".join(self.defined))
            return
        from suru_check import session_types

        try:
            _, sigs = session_types(list(self.kept), self.interp.ctx.copy(), [], self.defined)
        except Exception as e:
            if type(e).__name__ != "SuruError":
                raise
            self.out("\n".join(self.defined))
            return
        self.out("\n".join(sigs))

    # --- 補完 ------------------------------------------------------------

    def candidates(self) -> list[str]:
        names = set()
        for env in (self.interp.shared, self.interp.globals):
            names.update(n for n in env.vars if not n.startswith("\0"))
        names.update(":" + k for k in REPL_COMMANDS)
        names.update((KW_TOWA, KW_IF, KW_THEN, KW_ELSE, KW_PROVISO, KW_SOREKARA, KW_RETURN, KW_LAMBDA, KW_IMPORT, KW_IKA, KW_IJOU))
        return sorted(names)


def _setup_readline(r: Repl) -> None:
    """行の編集・履歴・補完(Tab)を使えるようにする。readline がなければ何もしない"""
    try:
        import readline
    except ImportError:
        return
    import atexit

    path = history_path()
    try:
        readline.read_history_file(path)
    except OSError:
        pass
    readline.set_history_length(1000)

    def save() -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            readline.write_history_file(path)
        except OSError:
            pass

    atexit.register(save)
    matches: list[str] = []

    def completer(text: str, state: int) -> str | None:
        if state == 0:
            matches[:] = [n for n in r.candidates() if n.startswith(text)]
        return matches[state] if state < len(matches) else None

    readline.set_completer(completer)
    readline.set_completer_delims(" \t\n　()（）[]［］「」、。")
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def repl(files: list[str] | None = None, checking: bool = True) -> None:
    if __name__ == "__main__":
        # suru_check は「suru」として読み込んだ構文の木を調べるので、対話モードもそちらで動かす
        import suru

        return suru.repl(files, checking)
    r = Repl(checking)
    if sys.stdin.isatty():
        _setup_readline(r)
    print(f"「する」{__version__} 対話モード。:助け で使い方を表示します。Ctrl-D か :終わる で終わります。")
    for path in files or ():
        r.load(path)
    buf: list[str] = []
    while True:
        try:
            line = input("... " if buf else "する> ")
        except EOFError:
            print()
            return
        except KeyboardInterrupt:  # 入力の途中なら取り消す
            print()
            buf = []
            continue
        if not buf and line.strip()[:1] in (":", "："):
            if not r.command(line):
                return
            continue
        buf.append(line)
        if not r.complete(buf):
            continue
        source = "\n".join(buf)
        buf = []
        r.feed(source)

CHECK_FLAGS = ("--検査", "--check")  # 型の検査だけを行う(実行はしない)
DOC_FLAGS = ("--文書", "--doc")  # 公開の名前の API ドキュメントを出す(#209)
EXPAND_FLAGS = ("--展開", "--expand")  # 準クォートを展開したソースを表示する
NO_CHECK_FLAGS = ("--検査なし", "--no-check")  # 型の検査をせずに実行する
COMPILE_FLAGS = ("--翻訳", "--compile")  # バイナリにコンパイルする(suru_compile.py)
INTERPRETER_FLAGS = ("--インタプリタ", "--interpreter")  # コンパイルせずにインタプリタで動かす(#229)
REPL_FLAGS = ("--対話", "-i")  # ファイルを読んでから対話モードを始める
LINT_FLAGS = ("--点検", "--lint")  # lib/点検.suru(する で書いた点検)でファイルを調べる
TEST_FLAGS = ("--試験", "--test")  # 試験のまとまり・例・「…試験する」を動かす(#193)
JSON_FLAGS = ("--json", "--JSON")  # エラーと点検の知らせを1行に1つの JSON で出す
LINT_SOURCE = "「点検」 を 読み込む\n点検内の点検実行する\n"


def lint_lib_files() -> list[str]:
    """点検が使う lib のファイルの名前(点検.suru から「「X」 を 読み込む」をたどったものと 基本.suru)。
    キャッシュの名前はこのファイルだけで決めるので、ほかの lib のファイルを変えても作り直さない"""
    import re

    pattern = re.compile(r"^[ \t　]*「([^「」]+)」[ \t　]*を[ \t　]*読み込", re.M)
    found: set[str] = set()
    todo = ["点検", "基本"]
    while todo:
        name = todo.pop()
        path = os.path.join(LIB_DIR, name + SOURCE_SUFFIX)
        if name in found or not os.path.exists(path):
            continue
        found.add(name)
        with open(path, encoding="utf-8") as f:
            todo += pattern.findall(f.read())
    return sorted(n + SOURCE_SUFFIX for n in found)


def lint_binary() -> str | None:
    """点検をバイナリにしたもの。clang があれば初めに一度だけ作って、キャッシュに置く(点検が使う lib のファイルが変われば作り直す)。
    作れなければ None(インタプリタで動かす)"""
    import hashlib

    import suru_compile

    cc = suru_compile.find_cc()
    if cc is None or os.environ.get("SURU_LINT_INTERP"):
        return None
    h = hashlib.sha256((__version__ + cc).encode())
    for name in lint_lib_files():
        with open(os.path.join(LIB_DIR, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read())
    with open(suru_compile.RUNTIME, "rb") as f:
        h.update(f.read())
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "suru")
    # 点検は手元で動かすものなので、SURU_TARGET で別の OS 向けにしていても手元向けに作る(Go 版の lintbin と同じ)
    saved_target = os.environ.pop("SURU_TARGET", None)
    try:
        name = os.path.join(cache, f"点検-{h.hexdigest()[:16]}")
        exe = suru_compile.exe_path(name)
        if os.path.exists(exe):
            return exe
        try:
            os.makedirs(cache, exist_ok=True)
            ir = suru_compile.compile_source(LINT_SOURCE, LIB_DIR, os.path.join(LIB_DIR, "点検実行.suru"), True)
            ll = f"{name}.{os.getpid()}.ll"
            with open(ll, "w", encoding="utf-8") as f:
                f.write(ir)
            tmp = f"{name}.{os.getpid()}.tmp"
            suru_compile.build(ll, tmp)
            os.remove(ll)
            os.replace(suru_compile.exe_path(tmp), exe)
        except Exception as e:  # suru_compile は suru を別のモジュールとして読み込むので、名前で見分ける
            if type(e).__name__ != "SuruError" and not isinstance(e, OSError):
                raise
            return None
        return exe if os.path.exists(exe) else None
    finally:
        if saved_target is not None:
            os.environ["SURU_TARGET"] = saved_target


def lint(paths: list[str]) -> int:
    """「suru --点検 a.suru b.suru」: 知らせを「道:行:桁: 規則: 説明」で表示する。知らせがあれば 1"""
    import subprocess

    os.environ.setdefault("SURU_LIB", LIB_DIR)  # 「読み込んで 使う」ファイルの中の名前を調べるのに使う
    exe = lint_binary()
    if exe is not None:
        return subprocess.call([exe, *paths])
    PROGRAM_ARGS[:] = paths
    interp = Interpreter()
    interp.ctx.base_dir = LIB_DIR
    try:
        interp.run(LINT_SOURCE, emit=lambda v: None)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except SuruError as e:
        print(format_error(e, LINT_SOURCE), file=sys.stderr)
        return 1
    return 0


TEST_SUFFIX = "試験する"  # 試験/ のファイルの「…試験する」(引数なし)も試験(kumu 試験 と同じ)
SKIP_DIRS = ("出力",)


def test_files(path: str) -> list[str]:
    """道がファイルならそれ、フォルダなら下の .suru(出力/ と . で始まるフォルダは除く)"""
    if not os.path.isdir(path):
        return [path]
    found = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        found += [os.path.join(root, f) for f in sorted(files) if f.endswith(SOURCE_SUFFIX)]
    return found


def collect_tests(program: list) -> list[Define]:
    """ファイルの試験: 試験のまとまり・例・一番外の「…試験する」(引数なし)を書いた順に"""
    out = []
    for s in program:
        if isinstance(s, Define) and (s.test or s.is_function and not s.params and s.name.endswith(TEST_SUFFIX)
                                      and MODULE_SEP not in s.name):
            out.append(s)
    return out


def test_label(d: Define) -> str:
    """試験の表示の名前: 試験のまとまりは「二倍」、例は「二倍するの例(4行)」、ほかは定義の名前"""
    if d.example is not None:
        return f"{d.test}({d.line}行)"
    return d.test or d.name


def run_one_test(interp: "Interpreter", d: Define, path: str) -> str | None:
    """試験を1つ行う。合格なら None、不合格なら理由(試験が書いた出力は呼ぶ側が集める)"""
    try:
        if d.example is not None:
            actual = interp.eval(d.example[0], interp.globals)
            expected = interp.eval(d.example[1], interp.globals)
            if apply_op("==", actual, expected, d.line):
                return None
            return (f"{path}:{d.line}: 等しくありません: 期待は {interp.format(expected)} / 実際は {interp.format(actual)}")
        fn = interp.force(interp.globals.lookup(d.name, d.line))
        interp.perform(interp.call(fn, {}, d.line))
        return None
    except SystemExit as e:
        return "" if e.code else None
    except SuruError as e:
        return format_error(e, SOURCES.get(path))
    except RecursionError:
        return DEEP_RECURSION_MESSAGE


def run_tests(args: list[str]) -> int:
    """「suru --試験 ファイルかフォルダ … [名前 …]」: 試験のまとまり・例・「…試験する」を動かす。
    道でない引数は名前の一部で、どれかを含む試験(か、それを含む道のファイル)だけを動かす。不合格があれば 1"""
    import io

    paths = [a for a in args if os.path.exists(a)]
    filters = [a for a in args if not os.path.exists(a)]
    if not paths:
        print("使い方: suru --試験 ファイルかフォルダ … [名前 …]", file=sys.stderr)
        return 2
    files = [f for p in paths for f in test_files(p)]
    passed = failed = 0
    for file in files:
        with open(file, encoding="utf-8") as f:
            source = f.read()
        base_dir = os.path.dirname(os.path.abspath(file))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                ok = type_check(source, base_dir, file)
            interp = Interpreter()
            interp.ctx.base_dir = base_dir
            interp.ctx.path = os.path.abspath(file)
            program = parse_program(source, interp.ctx) if ok else []
        except SuruError as e:
            buf.write(format_error(e, source) + "\n")
            ok = False
        if not ok:
            print(f"✗ {file}(読めません)")
            print(indent_text(buf.getvalue().rstrip("\n")))
            failed += 1
            continue
        tests = [d for d in collect_tests(program)
                 if not filters or any(x in test_label(d) or x in file for x in filters)]
        if not tests:
            continue
        _FFI_BASE[0] = base_dir
        # lib/標準.suru などそのものの試験では、そのファイルの組み込みも使う(読み込んだときと同じ)
        interp.globals.vars.update((b.name, b) for b in LIB_PRIMITIVES.get(os.path.abspath(file), ()))
        interp.load_program(program, interp.globals)
        for d in tests:
            with captured_output() as out:
                reason = run_one_test(interp, d, file)
            if reason is None:
                print(f"✓ {file} {test_label(d)}")
                passed += 1
                continue
            print(f"✗ {file} {test_label(d)}")
            text = (out[0] + (reason + "\n" if reason else "")).rstrip("\n")
            if text:
                print(indent_text(text))
            failed += 1
    if passed == 0 and failed == 0:
        print(f"試験が見つかりません(「以下は「名前」の試験です」・「{KW_EXAMPLE} … は … です」・「…{TEST_SUFFIX}」を書きます)",
              file=sys.stderr)
        return 0
    print(f"\n合格 {passed}・不合格 {failed}")
    return 1 if failed else 0


@contextlib.contextmanager
def captured_output():
    """試験が書いた標準出力と標準エラーを集める(「低水準書込する」で直接書いたものも)。out[0] に入れる"""
    import tempfile

    out = [""]
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    with tempfile.TemporaryFile() as tmp:
        os.dup2(tmp.fileno(), 1)
        os.dup2(tmp.fileno(), 2)
        try:
            yield out
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])
            tmp.seek(0)
            out[0] = tmp.read().decode("utf-8", "replace")


def indent_text(s: str) -> str:
    return "    " + s.replace("\n", "\n    ")


def type_check(source: str, base_dir: str = ".", path: str = "", as_json: bool = False) -> bool:
    """型を調べる。間違いがあれば表示して False(as_json なら1行の JSON で)"""
    from suru_check import check

    try:
        check(source, base_dir, path)
    except Exception as e:  # suru_check は suru を別のモジュールとして読み込むので、名前で見分ける
        if type(e).__name__ != "SuruError":
            raise
        print(error_json(e, "型", path) if as_json else format_error(e, source), file=sys.stderr)
        return False
    return True


def bundled_suruc() -> str | None:
    """pip の OS ごとの wheel で suru と一緒に入った Go 版の suruc の道(#229)。なければ None。
    suru と同じフォルダ(venv の bin/ など)にあるものだけを使い、PATH のほかの版は使わない。
    `python3 suru.py` で動かしたとき(リポジトリのまま)は使わない。
    SURU_SURUC で道を決められ(空なら使わない)、SURU_INTERPRETER=1 なら使わない"""
    if os.environ.get("SURU_INTERPRETER") == "1":
        return None
    given = os.environ.get("SURU_SURUC")
    if given is not None:
        return given or None
    launcher = sys.argv[0] if sys.argv else ""
    name = os.path.basename(launcher).lower()
    if name not in ("suru", "suru.exe", "suru-script.py"):
        return None
    exe = os.path.join(os.path.dirname(os.path.abspath(launcher)), "suruc.exe" if os.name == "nt" else "suruc")
    return exe if os.path.isfile(exe) else None


# suruc --実行準備 の「ここではコンパイルできないので、インタプリタで動かす」の終了コード(cmd/suruc/run.go と同じ)
EXIT_NEED_INTERPRETER = 3


def run_compiled(suruc: str, path: str, args: list[str], checking: bool, as_json: bool) -> int | None:
    """suruc でキャッシュにバイナリを用意して、それに置き換わる(Windows では終わるまで待つ)。
    インタプリタで動かすべきときは None。検査やコンパイルのエラーなら、その終了コード"""
    import subprocess

    cmd = [suruc, "--実行準備"] + ([] if checking else ["--検査なし"]) + (["--json"] if as_json else []) + [path]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, encoding="utf-8")
    if r.returncode == EXIT_NEED_INTERPRETER:
        return None
    if r.returncode != 0:
        return r.returncode
    exe = r.stdout.strip()
    sys.stdout.flush()
    sys.stderr.flush()
    if as_json:  # 実行時のエラーも、インタプリタと同じ1行の JSON で(runtime/suru_rt.c の fail_msg)
        os.environ["SURU_ERROR_JSON"] = path
    if os.name == "nt":
        return subprocess.call([exe] + args)
    os.execv(exe, [exe] + args)
    return 1  # 戻ってこない


def subprocess_call(cmd: list[str]) -> int:
    import subprocess

    return subprocess.call(cmd)


def suruc_check(suruc: str, path: str, as_json: bool) -> bool:
    """同梱の suruc で型を調べる(エラーの文と JSON は Python 版と同じ。tests/test_go_compiler.py が確かめる)"""
    import subprocess

    cmd = [suruc, "--検査"] + (["--json"] if as_json else []) + [path]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL).returncode == 0


def _take_json_flag(argv: list[str]) -> tuple[list[str], bool]:
    """プログラムのファイルの前にある --json を取り除く(後ろの引数はプログラムに渡すので、そのまま)"""
    out, found, k = argv[:1], False, 1
    while k < len(argv) and argv[k].startswith("-"):
        if argv[k] in JSON_FLAGS:
            found = True
        else:
            out.append(argv[k])
        k += 1
    return out + argv[k:], found


# 再帰の深さの上限(#152)。Python 3.12 からは Python の関数を呼ぶたびに C のスタックを使わないので、
# 大きくしても止まらない(する の 1 段はおよそ Python の 3〜4 段で、20万段ほど。1 段におよそ 4KB のメモリを使う)。それより前は C のスタックがあふれないように小さくしておく
RECURSION_LIMIT = 1_000_000 if sys.version_info >= (3, 12) else 10000
DEEP_RECURSION_MESSAGE = "再帰が深すぎます(もっと深い再帰は、suruc か suru --翻訳 でコンパイルすると動きます)"


def main(argv: list[str]) -> int:
    sys.setrecursionlimit(RECURSION_LIMIT)
    if len(argv) >= 2 and argv[1] in ("--version", "--版"):
        print(f"する {__version__}")
        return 0
    if len(argv) >= 2 and argv[1] in COMPILE_FLAGS:
        suruc = bundled_suruc()
        if suruc:  # 同じ IR を出す Go 版のほうが速い
            return subprocess_call([suruc] + argv[2:])
        import suru_compile

        return suru_compile.main(argv[:1] + argv[2:])
    if len(argv) >= 2 and argv[1] in LINT_FLAGS:
        paths = [a if a not in JSON_FLAGS else "--json" for a in argv[2:]]
        if not [a for a in paths if a != "--json"]:
            print("使い方: suru --点検 [--json] ファイル.suru …", file=sys.stderr)
            return 2
        return lint(paths)
    if len(argv) >= 2 and argv[1] in TEST_FLAGS:
        return run_tests(argv[2:])
    if len(argv) >= 2 and argv[1] in DOC_FLAGS:
        return doc_command(argv[2:])
    argv, as_json = _take_json_flag(argv)
    if len(argv) >= 2 and argv[1] in EXPAND_FLAGS:
        if len(argv) != 3:
            print("使い方: suru --展開 ファイル.suru", file=sys.stderr)
            return 2
        with open(argv[2], encoding="utf-8") as f:
            source = f.read()
        try:
            sys.stdout.write(expand_source(source, os.path.dirname(os.path.abspath(argv[2])), argv[2]))
        except SuruError as e:
            print(error_json(e, "構文", argv[2]) if as_json else format_error(e, source), file=sys.stderr)
            return 1
        return 0
    if len(argv) >= 2 and argv[1] in CHECK_FLAGS:
        rest = [a for a in argv[2:] if a not in JSON_FLAGS]
        as_json = as_json or len(rest) < len(argv) - 2
        if len(rest) != 1:
            print("使い方: suru --検査 [--json] ファイル.suru", file=sys.stderr)
            return 2
        suruc = bundled_suruc()
        if suruc:
            return subprocess_call([suruc, "--検査"] + (["--json"] if as_json else []) + rest)
        with open(rest[0], encoding="utf-8") as f:
            source = f.read()
        try:
            if not type_check(source, os.path.dirname(os.path.abspath(rest[0])), rest[0], as_json):
                return 1
        except RecursionError:
            e = SuruError(DEEP_RECURSION_MESSAGE, None)
            print(error_json(e, "型", rest[0]) if as_json else format_error(e, source), file=sys.stderr)
            return 1
        if not as_json:
            print("型の検査で問題は見つかりませんでした")
        return 0
    checking = True
    interpreter = False  # --インタプリタ: コンパイルせずに Python のインタプリタで動かす(#229)
    while len(argv) >= 2 and argv[1] in NO_CHECK_FLAGS + INTERPRETER_FLAGS:
        if argv[1] in NO_CHECK_FLAGS:
            checking = False
        else:
            interpreter = True
        argv = argv[:1] + argv[2:]
    if len(argv) >= 2 and argv[1] in REPL_FLAGS:
        repl(argv[2:], checking)  # ファイルを読んでから対話モードを始める
        return 0
    if len(argv) < 2:
        repl(checking=checking)
        return 0
    # 同梱の suruc があれば、コンパイルして動かす(2回目からはキャッシュのバイナリ)。
    # C コンパイラがない・kumu の Cソース を使うときは、このままインタプリタで動かす
    suruc = None if interpreter else bundled_suruc()
    if suruc:
        code = run_compiled(suruc, argv[1], argv[2:], checking, as_json)
        if code is not None:
            return code
    with open(argv[1], encoding="utf-8") as f:
        source = f.read()
    PROGRAM_ARGS[:] = argv[2:]
    base_dir = os.path.dirname(os.path.abspath(argv[1]))

    def report(e: Exception, kind: str) -> int:
        print(error_json(e, kind, argv[1]) if as_json else format_error(e, source), file=sys.stderr)
        return 1

    # 実行の前に必ず型を調べる(間違いがあれば実行しない)。同梱の suruc があれば、そちらで速く調べる
    suruc = bundled_suruc() if checking else None
    if suruc:
        if not suruc_check(suruc, argv[1], as_json):
            return 1
        checking = False
    try:
        if checking and not type_check(source, base_dir, argv[1], as_json):
            return 1
    except SuruError as e:  # 構文のエラー
        return report(e, "構文")
    except RecursionError:
        return report(SuruError(DEEP_RECURSION_MESSAGE, None), "型")
    interp = Interpreter()
    interp.ctx.base_dir = base_dir
    interp.ctx.path = os.path.abspath(argv[1])
    try:
        interp.run(source, emit=lambda v: print(interp.format(v)))
    except SuruError as e:
        return report(e, "実行")
    except RecursionError:
        # Python のトレースバックではなく、する のエラーとして知らせる
        return report(SuruError(DEEP_RECURSION_MESSAGE, None), "実行")
    return 0


def cli() -> None:
    """pip で入れたときの「suru」コマンド"""
    if os.name == "nt":
        # Windows でパイプやファイルに出すと cp1252 などになり、日本語を書けない。
        # コンパイルしたプログラム(UTF-8 のマニフェスト)と同じく UTF-8 で読み書きする
        for f in (sys.stdin, sys.stdout, sys.stderr):
            if f is not None and hasattr(f, "reconfigure") and (f.encoding or "").lower() not in ("utf-8", "utf8"):
                f.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()

#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""日本語関数型プログラミング言語「する」のインタプリタ(プロトタイプ)

使い方:
    python3 suru.py ファイル.suru     # ファイルを実行(トップレベルの式の値を表示)
    python3 suru.py                   # 対話モード(REPL)
"""
from __future__ import annotations

__version__ = "0.1.0"

import math
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------


class Pos(int):
    """行番号。int として使えるが、何文字目か(col)も覚えている"""

    col: int | None

    def __new__(cls, line: int, col: int | None = None) -> "Pos":
        obj = int.__new__(cls, line)
        obj.col = col
        return obj


def _where(line: int | None) -> str:
    col = getattr(line, "col", None)
    return f"{line}行目 {col}文字目" if col else f"{line}行目"


class SuruError(Exception):
    """「する」の実行時・構文エラー"""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        self.col = getattr(line, "col", None)
        self.message = message
        super().__init__(f"{_where(line)}: {message}" if line else message)


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def format_error(e: "SuruError", source: str | None = None) -> str:
    """エラーの文と、分かれば該当する行と位置の印(^)を返す"""
    out = f"エラー: {e}"
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
RESERVED_MARKS = {"・": "中黒「・」"}
MODULE_MARK = "内"  # 読み込んだファイルの中の名前: 数学内の円周率
MODULE_SEP = MODULE_MARK + "の"
KW_IMPORT = "読み込む"  # 「数学」 を 読み込む
KW_IMPORT_POLITE = "読み込みます"
KW_IMPORT_TE = "読み込んで"  # 「数学」 を 読み込んで 使う: 前置きなしで使う
KW_USE = "使う"
KW_USE_POLITE = "使います"
SOURCE_SUFFIX = ".suru"
KW_EXTERN = "外部の"  # 外部の「m」 を 読み込む / x を 余弦にする とは 外部の「cos」

KEYWORDS = {
    KW_TO, KW_TOWA, KW_NO, KW_GA, KW_IF, KW_THEN, KW_ELSE, KW_LAMBDA, KW_RETURN, KW_PROVISO,
    KW_KA, KW_WA, KW_TOIU, KW_KUMI, KW_SEISHITSU, KW_SOREKARA, KW_KATSU, KW_MATAHA, DESU,
    KW_IMPORT, KW_IMPORT_POLITE, KW_IMPORT_TE, KW_USE, KW_USE_POLITE,
}
KANJI_KEYWORDS = {KW_KUMI, KW_SEISHITSU}
CONTINUATION_KEYWORDS = {KW_THEN, KW_ELSE}  # 行頭に来たら前の文の続きとみなす

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
TEJUN = "手順"      # 「手順（文。文。…）」: 文を順に行う
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
            if rest == KW_RETURN:
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
            j = text.find("」", i + 1)
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
        else:
            buf += c
        i += 1
    flush()
    return drop_desu(tokens)


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
MIXED_WORDS = ("受け取って", "返すこと", "長さ", "残り", KW_IMPORT_POLITE, KW_IMPORT, KW_IMPORT_TE, KW_USE_POLITE, KW_USE)
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
            f"{NAME_OPEN}割る数に{NAME_CLOSE}する のように{NAME_OPEN}{NAME_CLOSE}で囲んでください",
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
            j = text.find("」", i + 1)
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
        else:
            buf += c
        i += 1
    flush()
    return tokens


def is_punct_line(text: str) -> bool:
    """文字列・名前・コメントの外に「。」か「、」があるか"""
    i, n = 0, len(text)
    at_token_start = True
    while i < n:
        c = text[i]
        if c in ("「", NAME_OPEN):
            j = text.find("」" if c == "「" else NAME_CLOSE, i + 1)
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


def split_lines(source: str) -> list[Line]:
    lines = []
    raws = source.splitlines()
    k = 0
    while k < len(raws):
        raw, number = raws[k], k + 1
        indent = 0
        for c in raw:
            if c in INDENT_WIDTH:
                indent += INDENT_WIDTH[c]
            else:
                break
        if not is_punct_line(raw) and not _opens_punct(raws, k):
            tokens = tokenize_line(raw, number)
            if tokens:
                lines.append(Line(indent, tokens, number))
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
    """「入力した 結果」: 手順の中で動作を行った結果"""

    call: Any
    line: int


@dataclass
class Do:
    """「手順（文。文。…）」「…。それから、…。」: 文を順に行う"""

    statements: list
    line: int
    sequel: bool = False  # 「それから」で作った並び


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


@dataclass
class Import:
    """「「数学」 を 読み込む」: 数学.suru の定義を「数学・名前」で使えるようにする"""

    module: Module
    line: int
    open: bool = False  # 「読み込んで 使う」: 中の名前を前置きなしでも使う


@dataclass
class ExternLib:
    """「外部の「m」 を 読み込む」: C の呼び出し規約で呼べるライブラリ(.so / .dylib)を使う"""

    name: str  # 書いたとおり(「m」「./libあれ.so」)
    path: str  # 短い名前(「m」)か、ファイルなら絶対パス
    line: int


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
    pointer: str = ""  # 「外部の（f）」なら、関数の番地を持つ引数の名前(C には渡さない)


TOP_LEVEL_ONLY = (TypeDef, TraitDecl, TraitImpl, TypeSig, Import, ExternLib)
TYPE_VAR_NAMES = "甲乙丙丁戊己庚辛壬癸"
# 小数・整数は数の別名(外部の関数の宣言で C の double・int を表す)。番地は C のポインタ
# 無は外部の関数の値がないこと(C の void。する では 0)。バイト列は変更できないバイトの並び
BUILTIN_TYPES = ("数", "文字列", "真偽", "リスト", "関数", "動作", "小数", "整数", "番地", "バイト列", "無")
# 外部の関数に渡せる型 → C の型の名前(バイト列は引数だけ、無は値だけ)
FFI_TYPES = {"数": "i64", "小数": "f64", "整数": "i32", "真偽": "bool", "文字列": "str", "番地": "ptr",
             "バイト列": "bytes", "無": "void"}


class ParseContext:
    """構文解析で使う、定義済みの型と形の名前(「3 と 4 の 点」を読むために先に集める)"""

    def __init__(self, ctors: dict | None = None, types: dict | None = None, base_dir: str = ".",
                 modules: dict | None = None):
        self.ctors: dict[str, tuple[str, list]] = dict(ctors or {})  # 形 → (型, フィールド名)
        self.types: dict[str, list] = dict(types or {})  # 型 → [形]
        self.base_dir = base_dir  # 「「数学」 を 読み込む」で探すフォルダ
        self.modules: dict[str, Any] = dict(modules or {})  # 読み込んだファイル(絶対パス → Module。読み込み中は None)

    def copy(self) -> "ParseContext":
        return ParseContext(self.ctors, self.types, self.base_dir, self.modules)

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
            if not ln.closed and pos < len(lines) and lines[pos].indent > indent:
                node.children = block(indent + 1)
            # 行頭が ならば/そうでなければ の行は前の文の続き
            first = ln.tokens[0]
            if nodes and not ln.closed and not nodes[-1].line.closed and first.kind == "KW" and first.value in CONTINUATION_KEYWORDS:
                prev = nodes[-1]
                prev.children.append(node)
            else:
                nodes.append(node)
        return nodes

    top = block(0)
    if lines and lines[0].indent != 0:
        raise SuruError("最初の行はインデントできません", lines[0].number)
    return top


def flatten(node: Node) -> list[Token]:
    """行とその深い行を1つのトークン列にする。行の切れ目には区切り(SEP)を入れる(場合分けで使う)"""
    out = list(node.line.tokens)
    for c in node.children:
        out.append(Token("SEP", "", c.line.number))
        out.extend(flatten(c))
    return out


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
                    if res is None or res.kind != "WORD" or res.value != RESULT:
                        raise SuruError(f"「{tok.value[:-len(SURU)]}した」の後には「結果」を書いてください", tok.line)
                    self.next()
                    if has_piped:
                        args = merge_piped(args, piped)
                    value: Any = Run(Call(tok.value, args, tok.line), tok.line)
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
                raise SuruError("「した」の後には「結果」を書いてください", tok.line)

    # --- パターンマッチ ---------------------------------------------------
    # もし 値 が パターン ならば 式 { 区切り パターン ならば 式 } [ そうでなければ 式 ]
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
            pat = self.pattern()
            guard = self.guard()
        except SuruError:
            return None
        if not is_kw(self.peek(), KW_THEN):
            return None
        cases: list = []
        default = None
        while True:
            check_pattern(pat, self.peek().line)
            self.next()  # ならば
            cases.append((pat, guard, self.case_body()))
            tok = self.peek()
            if is_kw(tok, KW_ELSE):
                self.next()
                default = self.case_body()
                break
            if tok is None or tok.kind in ("RP", "PERIOD") or not self.sep_here():
                break
            pat = self.pattern()
            guard = self.guard()
            tok = self.peek()
            if not is_kw(tok, KW_THEN):
                raise SuruError("場合の後に「ならば」が必要です", tok.line if tok else self.last_line())
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
        if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)):
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
        if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)):
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
        if tok.kind == "WORD":
            nxt = self.tokens[self.pos] if self.pos < len(self.tokens) else None
            if tok.value == TEJUN and not tok.quoted and nxt is not None and nxt.kind == "LP":
                self.next()
                return self.paren_do(nxt)
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
        raise SuruError("関数名は「する」で終わる必要があります", last.line)
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
    out = list(tokens)
    for c in children:
        out.append(Token("SEP", "", c.line.number))
        out.extend(flatten(c))
    return out


def parse_statement(node: Node) -> Any:
    raw = node.line.tokens
    tokens = nosep(raw)
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
    if MODULE_SEP in name:
        raise SuruError(f"「{name}」: 読み込んだファイルの中の名前は定義できません", head[0].line)
    after_t = nosep(after)
    if len(after_t) == 1 and after_t[0].kind == "WORD" and after_t[0].value == TEJUN and not after_t[0].quoted and node.children:
        # 「挨拶する とは 手順」+ 深い行: 深い行を順に行う
        return Define(name, params, parse_do(node.children, node.line.number), is_function, node.line.number)
    if (len(after_t) == 2 and after_t[0].kind == "WORD" and after_t[0].value == KW_EXTERN and not after_t[0].quoted
            and after_t[1].kind == "STR" and not node.children):
        # 「x を 余弦にする とは 外部の「cos」」: C の関数を呼ぶ
        sym = after_t[1].value
        if not sym.isascii() or not (sym[:1].isalpha() or sym[:1] == "_") or not all(c.isalnum() or c == "_" for c in sym):
            raise SuruError(f"「{sym}」は C の関数の名前ではありません", after_t[1].line)
        if sym.startswith(("rt_", "suru_")):
            raise SuruError(f"「{sym}」は「する」の実行時が使う名前なので、外部の関数にできません", after_t[1].line)
        return Define(name, params, Extern(sym, after_t[1].line), is_function, node.line.number)
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


def _is_type_word(tok: Token) -> bool:
    return tok.kind == "WORD" and (
        tok.value in BUILTIN_TYPES or tok.value in _CTX.types or (len(tok.value) == 1 and tok.value in TYPE_VAR_NAMES)
    )


def try_parse_type_sig(tokens: list[Token]) -> TypeSig | None:
    """「数 を 階乗する は 数」「税率 は 数」なら型の宣言を返す(そうでなければ None)"""
    ha = find_top_level(tokens, KW_WA)
    if ha is None or ha == 0 or ha == len(tokens) - 1:
        return None
    left, right = tokens[:ha], tokens[ha + 1 :]
    line = tokens[0].line
    last = left[-1]
    if last.kind == "CALL" and last.form == SURU and not last.negated:
        # 関数: 「型 助詞 型 助詞 … 名前する は 型」
        params = []
        i = 0
        while i < len(left) - 1:
            t, i = parse_type(left, i)
            if i >= len(left) - 1 or not (left[i].kind == "PART" or is_kw(left[i], GA)):
                raise SuruError("型の宣言では、引数の型の後に助詞を書いてください(「数 を 階乗する は 数」)", line)
            params.append((left[i].value, t))
            i += 1
        name = last.value
        if any(p == q for k, (p, _) in enumerate(params) for q, _ in params[:k]):
            raise SuruError(f"「{name}」の型の宣言で同じ助詞が2回使われています", line)
        return TypeSig(name, params, parse_type_all(right, line), line)
    if len(left) == 1 and left[0].kind == "WORD" and right and (_is_type_word(right[0]) or right[0].kind == "LP"):
        # 値: 「税率 は 数」(「点 は 比較可能」は性質の実装)
        if len(right) == 1 and not _is_type_word(right[0]):
            return None
        return TypeSig(_check_name(left[0]), None, parse_type_all(right, line), line)
    return None


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
    if len(name) == 1 and name in TYPE_VAR_NAMES and not tok.quoted:
        if args:
            raise SuruError(f"「{name}」は型の引数をとりません", tok.line)
        return TypeVarName(name)
    if name in ("数", "文字列", "真偽", "小数", "整数", "番地", "バイト列", "無") and args:
        raise SuruError(f"「{name}」は型の引数をとりません", tok.line)
    if name in ("リスト", "動作") and len(args) != 1:
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
            t, i = parse_type(tokens[:k], i)
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
    return TypeDef(name, ctors, line)


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
    if any(isinstance(i, Import) for i in imports.values()):
        _join_in_nodes(nodes, {i.module.name for i in imports.values() if isinstance(i, Import)})
    # 「3 と 4 の 点」を読むために、型の定義を先に集める(定義の順番は自由)
    for n in nodes:
        td = try_parse_typedef(n)
        if td is not None:
            ctx.add(td)
    saved, _CTX = _CTX, ctx
    try:
        statements = [imports[id(n)] if id(n) in imports else parse_statement(n) for n in nodes]
        _check_open_imports(statements)
        _attach_externs(statements)
        return attach_provisos(statements)
    finally:
        _CTX = saved


def module_names(module: Module) -> set:
    """読み込んだファイルの一番外の名前(標準ライブラリなら組み込みも)"""
    names = {s.name for s in module.program if isinstance(s, Define)}
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
    if (len(tokens) != 4 or tokens[1].kind != "STR" or not (tokens[2].kind == "PART" and tokens[2].value == WO)
            or not (is_kw(tokens[3], KW_IMPORT) or is_kw(tokens[3], KW_IMPORT_POLITE)) or node.line.indent):
        raise SuruError(f"外部のライブラリは一番外に「{KW_EXTERN}「m」 を {KW_IMPORT}」のように書いて読み込みます", tokens[0].line)
    name = tokens[1].value
    if not name:
        raise SuruError("外部のライブラリの名前が空です", tokens[0].line)
    path = name
    if "/" in name or name.endswith((".so", ".dylib")):
        path = os.path.abspath(os.path.join(ctx.base_dir, name))
    return ExternLib(name, path, tokens[0].line)


def _ffi_type(te: Any, sig: TypeSig, what: str) -> str:
    result = what == "値"
    names = [n for n, t in FFI_TYPES.items() if t != ("bytes" if result else "void")]
    if isinstance(te, TypeName) and not te.args and te.name in names:
        return FFI_TYPES[te.name]
    raise SuruError(f"外部の関数「{sig.name}」の{what}には {'・'.join(names)} のどれかの型を書いてください", sig.line)


def _attach_externs(statements: list) -> None:
    """外部の関数の定義に、同じファイルのライブラリと型の宣言(C の型)を付ける"""
    libs = [s.path for s in statements if isinstance(s, ExternLib)]
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
        if ext.pointer:
            continue
        if ext.symbol in seen:
            raise SuruError(f"外部の関数「{ext.symbol}」が2回定義されています(「{seen[ext.symbol]}」と「{d.name}」)", d.line)
        seen[ext.symbol] = d.name


def load_module(name: str, ctx: ParseContext, line: int) -> Module:
    """ファイル「name.suru」を読んで解析する。同じファイルは一度だけ読む"""
    path = os.path.abspath(os.path.join(ctx.base_dir, name if name.endswith(SOURCE_SUFFIX) else name + SOURCE_SUFFIX))
    if not os.path.exists(path):
        path = os.path.abspath(os.path.join(LIB_DIR, name if name.endswith(SOURCE_SUFFIX) else name + SOURCE_SUFFIX))
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
    sub = ParseContext(ctx.ctors, ctx.types, os.path.dirname(path))
    sub.modules = ctx.modules
    try:
        program = parse_program(source, sub)
        for s in program:
            if not isinstance(s, (Define,) + TOP_LEVEL_ONLY):
                raise SuruError("読み込むファイルには定義だけを書いてください", first_line_of(s))
    except SuruError as e:
        raise SuruError(f"「{stem}{SOURCE_SUFFIX}」の{_where(e.line) if e.line else ''}: {e.message}", line) from None
    ctx.ctors.update(sub.ctors)
    ctx.types.update(sub.types)
    module = Module(stem, path, program)
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


@dataclass
class Pure:
    """「x を 結果にする」: 何もせずに x を結果とする動作。連鎖する相手の型に合わせて使われる"""

    value: Any


ACTION_TYPES = (Action, Pure)


@dataclass(frozen=True)
class Record:
    """組の値。「（横 は 3 で 縦 は 4 の 点）」"""

    ctor: str
    type_name: str
    fields: tuple
    values: tuple

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
            return v.ctor
        inner = " で ".join(f"{f} は {fmt(x)}" for f, x in zip(v.fields, v.values))
        return f"（{inner} の {v.ctor}）"
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
        it2.out(it2.format(x))
        return x

    return Action("表示する", perform)


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


# 標準.suru の中と、読み込んだ側の「標準内の…」でだけ使える組み込み(する では書けないもの)
STD_PRIMITIVES = [
    Builtin("切捨する", [(WO, True)], _floor),
    Builtin("平方根にする", [(WO, True)], _sqrt),
    Builtin("範囲にする", [("から", True), (WO, True)], _range),
    Builtin("逆順にする", [(WO, True)], lambda it, a, line: _seq(a[WO], "「逆順にする」の「を」", line)[::-1]),
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
    Builtin("試行する", [(WO, True), ("で", True)], lambda it, a, line: _try(a[WO], a["で"], line)),
    # バイト列と、外部の関数とのやりとり
    Builtin("バイト列にする", [(WO, True)], lambda it, a, line: _str(a[WO], "「バイト列にする」の「を」", line).encode("utf-8")),
    Builtin("バイト列組立する", [(WO, True)], lambda it, a, line: _bytes_of_list(a[WO], line)),
    Builtin("数列にする", [(WO, True)], lambda it, a, line: tuple(_bytes(a[WO], "「数列にする」の「を」", line))),
    Builtin("文字列にする", [(WO, True)], lambda it, a, line: _decode(a[WO], line)),
    Builtin("バイト長にする", [(WO, True)], lambda it, a, line: len(_bytes(a[WO], "「バイト長にする」の「を」", line))),
    Builtin("番地にする", [(WO, True)], lambda it, a, line: Address(_addr_num(a[WO], line))),
    Builtin("番地数値にする", [(WO, True)], lambda it, a, line: _addr(a[WO], "「番地数値にする」の「を」", line).value),
    Builtin("バイト列取得する", [("から", True), (WO, True)], lambda it, a, line: _peek(a["から"], a[WO], line)),
    Builtin("書込する", [(WO, True), ("へ", True)], lambda it, a, line: _poke(a[WO], a["へ"], line)),
    Builtin("エラー番号取得する", [], lambda it, a, line: Action("エラー番号取得する", lambda it2: _errno())),
    Builtin("失敗する", [(WO, True)], lambda it, a, line: _fail_action(a[WO], line)),
    # 環境(lib/環境.suru が使う)
    Builtin("引数取得する", [], lambda it, a, line: Action("引数取得する", lambda it2: tuple(PROGRAM_ARGS))),
    Builtin("終了する", [(WO, True)], lambda it, a, line: _exit_action(a[WO], line)),
]

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


def _addr_num(v: Any, line: int) -> int:
    n = _num(v, line)
    if not isinstance(n, int) or not 0 <= n <= MAX_COMPILED_INT:
        raise SuruError(f"「{format_value(v)}」は番地にできません(0 以上の整数が必要です)", line)
    return n


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


def _errno() -> int:
    import ctypes

    return ctypes.get_errno()


def _fail_action(v: Any, line: int) -> Action:
    msg = _str(v, "「失敗する」の「を」", line)

    def perform(it: "Interpreter") -> Any:
        raise SuruError(msg, line)
    return Action("失敗する", perform)


def _try(m: Any, alt: Any, line: int) -> Any:
    """「m を 代わり で 試行する」: m を行い、実行時エラーになったら、エラーの文を標準エラーに書いて 代わり を行う"""
    for v, p in ((m, "を"), (alt, "で")):
        if not isinstance(v, ACTION_TYPES):
            raise SuruError(f"「試行する」の「{p}」は動作でなければなりません(「{format_value(v)}」が渡されました)", line)

    def perform(it: "Interpreter") -> Any:
        try:
            return it.perform(m)
        except SuruError as e:
            print(f"エラー: {e}", file=sys.stderr, flush=True)
        except RecursionError:
            print("エラー: 再帰が深すぎます", file=sys.stderr, flush=True)
        return it.perform(alt)

    return Action("試行する", perform)


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
            except OSError as e:
                raise SuruError(f"「{name}」で通信に失敗しました({e.strerror or e})", line) from None
        return Action(name, perform)
    return fn


def _listen(net: _Net, a: dict, line: int) -> int:
    import socket
    port = _num(a[WO], line)
    if not isinstance(port, int) or not 0 <= port <= 65535:
        raise SuruError(f"「{format_value(a[WO])}」はポートの番号ではありません", line)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", port))
    sock.listen(16)
    return net.add(sock)


def _accept(net: _Net, a: dict, line: int) -> int:
    conn, _ = net.get(a["から"], "待受口", line).accept()
    conn.settimeout(NET_TIMEOUT)  # 何も送ってこない相手で止まらないように
    return net.add(conn)


def _recv_line(net: _Net, a: dict, line: int) -> str:
    # 行の終わりの改行も含めて返す。相手が閉じていれば空の文字列
    return net.reader(a["から"], line).readline(65536).decode("utf-8", "replace")


def _recv(net: _Net, a: dict, line: int) -> str:
    n = _num(a[WO], line)
    if not isinstance(n, int) or n < 0:
        raise SuruError(f"「{format_value(a[WO])}」は受信するバイト数ではありません", line)
    return net.reader(a["から"], line).read(n).decode("utf-8", "replace")


def _send(net: _Net, a: dict, line: int) -> int:
    data = _str(a[WO], "「送信する」の「を」", line).encode("utf-8")
    net.get(a["へ"], "接続", line).sendall(data)
    return len(data)


def _close(net: _Net, a: dict, line: int) -> int:
    v = a[WO]
    sock = net.get(v, "待受口か接続", line)
    f = net.files.pop(v, None)
    if f is not None:
        f.close()
    sock.close()
    del net.socks[v]
    return v


NET_PRIMITIVES = [
    Builtin("待受開始する", [(WO, True)], _net_action("待受開始する", _listen)),
    Builtin("接続受付する", [("から", True)], _net_action("接続受付する", _accept)),
    Builtin("行受信する", [("から", True)], _net_action("行受信する", _recv_line)),
    Builtin("受信する", [("から", True), (WO, True)], _net_action("受信する", _recv)),
    Builtin("送信する", [(WO, True), ("へ", True)], _net_action("送信する", _send)),
    Builtin("切断する", [(WO, True)], _net_action("切断する", _close)),
]


# ---------------------------------------------------------------------------
# 外部の関数(FFI)。インタプリタは ctypes で C の呼び出し規約の関数を呼ぶ
# ---------------------------------------------------------------------------

INT64_MIN, INT64_MAX = -(1 << 63), (1 << 63) - 1
MIN_COMPILED_INT, MAX_COMPILED_INT = -(1 << 62), (1 << 62) - 1  # コンパイルしたプログラムの整数の範囲
_FFI_LIBS: dict = {}


def _ffi_lib(path: str, line: int) -> Any:
    """ライブラリを開く(同じものは一度だけ)。短い名前(「m」)は OS の探し方で探す"""
    import ctypes
    import ctypes.util

    if path in _FFI_LIBS:
        return _FFI_LIBS[path]
    found = path if os.path.isabs(path) else ctypes.util.find_library(path) or f"lib{path}.so"
    try:
        lib = ctypes.CDLL(found, use_errno=True)
    except OSError as e:
        raise SuruError(f"外部のライブラリ「{path}」を開けません({e})", line) from None
    _FFI_LIBS[path] = lib
    return lib


def _ffi_symbol(ext: Extern, line: int) -> Any:
    import ctypes

    for path in ext.libs:
        lib = _ffi_lib(path, line)
        if hasattr(lib, ext.symbol):
            return getattr(lib, ext.symbol)
    proc = _FFI_LIBS.setdefault("\0プロセス", ctypes.CDLL(None, use_errno=True))  # libc などリンク済みのもの
    if hasattr(proc, ext.symbol):
        return getattr(proc, ext.symbol)
    where = "・".join(f"「{p}」" for p in ext.libs) or "読み込んだライブラリ"
    raise SuruError(f"外部の関数「{ext.symbol}」が{where}に見つかりません", line)


def _ffi_ctype(t: str) -> Any:
    import ctypes

    return {"i64": ctypes.c_int64, "f64": ctypes.c_double, "i32": ctypes.c_int32, "bool": ctypes.c_int32,
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
    if t == "f64":
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
    if t == "f64":
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

        if ext.pointer:
            k = names.index(ext.pointer)
            fp = a[parts[k]]
            if not isinstance(fp, Address) or fp.value == 0:
                raise SuruError(f"外部の関数「{d.name}」の「{parts[k]}」には関数の番地が必要です(「{format_value(fp)}」が渡されました)", line)
            ts = [t for i, t in enumerate(ext.params) if i != k]
            f = ctypes.CFUNCTYPE(_ffi_ctype(ext.result), *[_ffi_ctype(t) for t in ts], use_errno=True)(fp.value)
            args = [_ffi_arg(t, a[p], d.name, p, line) for i, (t, p) in enumerate(zip(ext.params, parts)) if i != k]
            ctypes.set_errno(0)
            return _ffi_result(ext.result, f(*args), d.name, line)
        if not cfn:
            f = _ffi_symbol(ext, line)
            f.argtypes = [_ffi_ctype(t) for t in ext.params]
            f.restype = _ffi_ctype(ext.result)
            cfn.append(f)

        args = [_ffi_arg(t, a[p], d.name, p, line) for t, p in zip(ext.params, parts)]
        ctypes.set_errno(0)
        return _ffi_result(ext.result, cfn[0](*args), d.name, line)

    def act(a: dict, line: int) -> Any:
        # 動作の C の関数は、子のプロセスや C の stdio と表示の順が入れ替わらないよう、それまでの表示を出してから呼ぶ
        sys.stdout.flush()
        return call(a, line)

    if ext.action:
        return Builtin(d.name, [(p, True) for p in parts],
                       lambda it, a, line: Action(d.name, lambda it2: act(a, line)))
    return Builtin(d.name, [(p, True) for p in parts], lambda it, a, line: call(a, line))

# lib/ のファイルごとの組み込み(そのファイルの中と、読み込んだ側の「標準内の…」「通信内の…」で使える)
LIB_PRIMITIVES = {STD_PATH: STD_PRIMITIVES, NET_PATH: NET_PRIMITIVES}

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
    def __init__(self, out: Any = None, read: Any = None) -> None:
        self.out = out or print  # 「表示する」の出力先
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
        self.load_program(program, self.globals)
        results = []
        for s in program:
            if isinstance(s, (Define,) + TOP_LEVEL_ONLY):
                continue
            v = self.eval(s, self.globals)
            if isinstance(v, ACTION_TYPES):
                self.perform(v)
                continue
            results.append(v)
            if emit is not None:
                emit(v)
        return results

    def load_program(self, program: list, env: Env) -> None:
        """定義を先にすべて登録する(定義の順番は自由。相互再帰もできる)"""
        for stmt in program:
            if isinstance(stmt, Import):
                mod = self.load_module(stmt.module)
                for name, v in mod.vars.items():
                    if MODULE_SEP not in name:
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
            default = Function(fname, d.params, d.body, env) if d else None
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
            fns[d.name] = Function(d.name, d.params, d.body, env)
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
            env.vars[d.name] = Function(d.name, d.params, d.body, env)
        else:
            env.vars[d.name] = Lazy(d.body, env)

    def eval(self, node: Any, env: Env) -> Any:
        if isinstance(node, Num):
            return node.value
        if isinstance(node, Str):
            return node.value
        if isinstance(node, Var):
            v = env.lookup(node.name, node.line)
            if isinstance(v, Lazy):
                if not v.done:
                    v.value, v.done = self.eval(v.expr, v.env), True
                return v.value
            return v
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
            fn = env.lookup(node.name, node.line)
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
            fn = env.lookup(node.name, node.line)
            if not isinstance(fn, FUNCTION_TYPES):
                raise SuruError(f"「{node.name}」は関数ではありません", node.line)
            if not node.args:
                return fn
            args = {p: self.eval(a, env) for p, a in node.args.items()}
            return self.partial(fn, args, node.line)
        if isinstance(node, Lambda):
            return Function("無名関数", node.params, node.body, env)
        if isinstance(node, Block):
            local = Env(env)
            for s in node.statements:
                if isinstance(s, Define):
                    self.define(s, local)
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
        local = Env(fn.closure)
        for p, pat in fn.params:
            bind(local, pat, args[p], p, fn.name, line)
        result = self.eval(fn.body, local)
        if is_predicate(fn.name) and not isinstance(result, bool):
            raise SuruError(f"述語「{fn.name}」は 真 か 偽 を返す必要があります(「{self.format(result)}」が返りました)", line)
        return result


def run(source: str) -> list[Any]:
    return Interpreter().run(source)


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------


def repl() -> None:
    interp = Interpreter()
    print("「する」対話モード。空行で入力を確定、Ctrl-D で終了します。")
    buf: list[str] = []
    while True:
        try:
            line = input("... " if buf else "する> ")
        except EOFError:
            print()
            return
        # 「とは」で終わる行から始まる複数行の入力は、空行が来るまでまとめて読む
        buf.append(line)
        text = "\n".join(buf)
        if is_punct_line(text):
            # 句読点の書き方: 「。」で終わるまで読む
            if not text.rstrip().endswith(PERIOD):
                continue
        elif line.rstrip().endswith(KW_TOWA) or (len(buf) > 1 and line.strip()):
            continue
        source = "\n".join(buf)
        buf = []
        if not source.strip():
            continue
        try:
            interp.run(source, emit=lambda v: print(interp.format(v)))
        except SuruError as e:
            print(format_error(e, source))
        except RecursionError:
            print("エラー: 再帰が深すぎます")


CHECK_FLAGS = ("--検査", "--check")  # 型の検査だけを行う(実行はしない)
NO_CHECK_FLAGS = ("--検査なし", "--no-check")  # 型の検査をせずに実行する
COMPILE_FLAGS = ("--翻訳", "--compile")  # バイナリにコンパイルする(suru_compile.py)
LINT_FLAGS = ("--点検", "--lint")  # lib/点検.suru(する で書いた点検)でファイルを調べる
LINT_SOURCE = "「点検」 を 読み込む\n点検内の点検実行する\n"


def lint_binary() -> str | None:
    """点検をバイナリにしたもの。clang があれば初めに一度だけ作って、キャッシュに置く(lib が変われば作り直す)。
    作れなければ None(インタプリタで動かす)"""
    import hashlib

    import suru_compile

    cc = suru_compile.find_cc()
    if cc is None or os.environ.get("SURU_LINT_INTERP"):
        return None
    h = hashlib.sha256((__version__ + cc).encode())
    for name in sorted(os.listdir(LIB_DIR)):
        if name.endswith(SOURCE_SUFFIX):
            with open(os.path.join(LIB_DIR, name), "rb") as f:
                h.update(name.encode() + b"\0" + f.read())
    with open(suru_compile.RUNTIME, "rb") as f:
        h.update(f.read())
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "suru")
    exe = os.path.join(cache, f"点検-{h.hexdigest()[:16]}")
    if os.path.exists(exe):
        return exe
    try:
        os.makedirs(cache, exist_ok=True)
        ir = suru_compile.compile_source(LINT_SOURCE, LIB_DIR, os.path.join(LIB_DIR, "点検実行.suru"), True)
        ll = f"{exe}.{os.getpid()}.ll"
        with open(ll, "w", encoding="utf-8") as f:
            f.write(ir)
        tmp = f"{exe}.{os.getpid()}.tmp"
        suru_compile.build(ll, tmp)
        os.remove(ll)
        os.replace(tmp, exe)
    except Exception as e:  # suru_compile は suru を別のモジュールとして読み込むので、名前で見分ける
        if type(e).__name__ != "SuruError" and not isinstance(e, OSError):
            raise
        return None
    return exe if os.path.exists(exe) else None


def lint(paths: list[str]) -> int:
    """「suru --点検 a.suru b.suru」: 知らせを「道:行:桁: 規則: 説明」で表示する。知らせがあれば 1"""
    import subprocess

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


def type_check(source: str, base_dir: str = ".") -> bool:
    """型を調べる。間違いがあれば表示して False"""
    from suru_check import check

    try:
        check(source, base_dir)
    except Exception as e:  # suru_check は suru を別のモジュールとして読み込むので、名前で見分ける
        if type(e).__name__ != "SuruError":
            raise
        print(format_error(e, source), file=sys.stderr)
        return False
    return True


def main(argv: list[str]) -> int:
    sys.setrecursionlimit(10000)
    if len(argv) >= 2 and argv[1] in ("--version", "--版"):
        print(f"する {__version__}")
        return 0
    if len(argv) >= 2 and argv[1] in COMPILE_FLAGS:
        import suru_compile

        return suru_compile.main(argv[:1] + argv[2:])
    if len(argv) >= 2 and argv[1] in LINT_FLAGS:
        if len(argv) < 3:
            print("使い方: suru --点検 ファイル.suru …", file=sys.stderr)
            return 2
        return lint(argv[2:])
    if len(argv) >= 3 and argv[1] in CHECK_FLAGS:
        with open(argv[2], encoding="utf-8") as f:
            source = f.read()
        if not type_check(source, os.path.dirname(os.path.abspath(argv[2]))):
            return 1
        print("型の検査で問題は見つかりませんでした")
        return 0
    checking = True
    if len(argv) >= 3 and argv[1] in NO_CHECK_FLAGS:
        checking = False
        argv = argv[:1] + argv[2:]
    if len(argv) < 2:
        repl()
        return 0
    with open(argv[1], encoding="utf-8") as f:
        source = f.read()
    PROGRAM_ARGS[:] = argv[2:]
    base_dir = os.path.dirname(os.path.abspath(argv[1]))
    # 実行の前に必ず型を調べる(間違いがあれば実行しない)
    try:
        if checking and not type_check(source, base_dir):
            return 1
    except SuruError as e:  # 構文のエラー
        print(format_error(e, source), file=sys.stderr)
        return 1
    interp = Interpreter()
    interp.ctx.base_dir = base_dir
    try:
        interp.run(source, emit=lambda v: print(interp.format(v)))
    except SuruError as e:
        print(format_error(e, source), file=sys.stderr)
        return 1
    return 0


def cli() -> None:
    """pip で入れたときの「suru」コマンド"""
    sys.exit(main(sys.argv))


if __name__ == "__main__":
    cli()

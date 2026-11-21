#!/usr/bin/env python3
"""日本語関数型プログラミング言語「する」のインタプリタ(プロトタイプ)

使い方:
    python3 suru.py ファイル.suru     # ファイルを実行(トップレベルの式の値を表示)
    python3 suru.py                   # 対話モード(REPL)
"""
from __future__ import annotations

import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 例外
# ---------------------------------------------------------------------------


class SuruError(Exception):
    """「する」の実行時・構文エラー"""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"{line}行目: {message}" if line else message)


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
KEYWORDS = {
    KW_TO, KW_TOWA, KW_NO, KW_GA, KW_IF, KW_THEN, KW_ELSE, KW_LAMBDA, KW_RETURN, KW_PROVISO,
    KW_KA, KW_WA, KW_TOIU, KW_KUMI, KW_SEISHITSU,
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
RESERVED_MARKS = {"・": "中黒「・」"}

SURU = "する"       # 終止形: パイプラインの終わり
SHITE = "して"      # 連用形: 結果を次の関数の「を」へ渡す
KOTO = "すること"   # 名詞化: 関数そのもの(値)

PROPERTIES = {"先頭", "残り", "最後", "長さ", "それぞれ"}


@dataclass
class Token:
    kind: str  # NUM STR OP LP RP WORD KW PART CALL PERIOD SEP(「、」や行の切れ目。場合分けの区切り)
    value: Any
    line: int
    form: str = ""  # CALL のとき "する" / "して" / "すること"
    quoted: bool = False  # 『』で囲んだ名前

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


def _classify_call(word: str, line: int) -> Token | None:
    for form in (KOTO, SURU, SHITE):
        if word.endswith(form) and len(word) > len(form):
            stem = word[: -len(form)]
            if _is_all_hiragana(stem):
                raise hiragana_function_error(stem, line)
            return Token("CALL", stem + SURU, line, form)
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
    quoted = False

    def flush() -> None:
        nonlocal buf, quoted
        if buf:
            tokens.extend(_classify(buf, line, quoted))
            buf = ""
        quoted = False

    while i < n:
        c = text[i]
        if c in SPACES:
            flush()
        elif c in COMMENT_STARTS and not buf:
            break
        elif c == "「":
            flush()
            j = text.find("」", i + 1)
            if j < 0:
                raise SuruError("文字列の「に対応する」がありません", line)
            tokens.append(Token("STR", text[i + 1 : j], line))
            i = j
        elif c == NAME_OPEN:
            j = _find_name_close(text, i, line)
            buf += text[i + 1 : j]
            quoted = True
            i = j
        elif c in OPEN_PARENS:
            flush()
            tokens.append(Token("LP", "(", line))
        elif c in CLOSE_PARENS:
            flush()
            tokens.append(Token("RP", ")", line))
        elif c in RESERVED_MARKS:
            raise SuruError(f"{RESERVED_MARKS[c]}は将来の書き方のために予約されています(文字列の中では使えます)", line)
        else:
            buf += c
        i += 1
    flush()
    return tokens


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
MIXED_WORDS = ("受け取って", "返すこと", "長さ", "残り")
# ひらがなを含む組み込み関数の名前(「する」の前の部分)。名前として切り出す
MIXED_NAMES = ("畳み込み",)
# ひらがなの並びを分けるときの辞書。長いものから順に照合する
HIRAGANA_WORDS = sorted(
    set(PARTICLES)
    | {KW_TO, KW_TOWA, KW_NO, KW_GA, KW_IF, KW_THEN, KW_ELSE, KW_PROVISO, KW_KA, KW_WA, KW_TOIU}
    | {"それぞれ", KOTO, SURU, SHITE},
    key=len,
    reverse=True,
)
CALL_FORMS = (KOTO, SURU, SHITE)


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
    words = []
    i = 0
    while i < len(text):
        w = next((w for w in HIRAGANA_WORDS if text.startswith(w, i)), None)
        if w is None:
            return None
        words.append(w)
        i += len(w)
    return words


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


def segment_run(pieces: list[tuple[str, bool]], line: int) -> list[Token]:
    """空白で区切られた1つの並び(『』で囲んだ部分を含む)を単語に分ける"""
    # 1. 文字の種類で切る
    parts: list[tuple[str, str]] = []  # (種類, 文字列)
    for text, quoted in pieces:
        if quoted:
            parts.append(("QNAME", text))
            continue
        i = 0
        while i < len(text):
            mixed = _mixed_word_at(text, i)
            if mixed:
                parts.append(("NAME" if mixed in MIXED_NAMES else "MIXED", mixed))
                i += len(mixed)
                continue
            cls = _char_class(text[i])
            if cls == "OTHER":
                raise SuruError(f"「{text[i]}」は使えない文字です", line)
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
        if cls in ("NAME", "QNAME"):
            if cls == "NAME" and text in ("真", "偽"):
                tokens.append(Token("NUM", text == "真", line))
            elif cls == "NAME" and text == KW_EMPTY:
                tokens.append(Token("NUM", (), line))
            elif cls == "NAME" and text in KANJI_KEYWORDS:
                tokens.append(Token("KW", text, line))
            else:
                tokens.append(Token("WORD", text, line, quoted=cls == "QNAME"))
        elif cls == "MIXED":
            kind = "KW" if text in KEYWORDS else "WORD"
            tokens.append(Token(kind, text, line))
        elif cls == "DIGIT":
            norm = unicodedata.normalize("NFKC", text)
            tokens.append(Token("NUM", float(norm) if "." in norm else int(norm), line))
        elif cls == "OP":
            tokens.extend(_split_operators(text, line))
        else:  # HIRA
            words = _split_hiragana(text, line, idx > 0 and parts[idx - 1][0] in ("NAME", "QNAME"), idx > 0)
            k = next((n for n, w in enumerate(words) if w in CALL_FORMS), None)
            if k is not None:
                # 「三倍にする」「絶対値にする」: 「する」の前のひらがなは関数名の一部
                stem = "".join(words[:k])
                prev = parts[idx - 1] if idx > 0 else None
                if prev is None or prev[0] not in ("NAME", "QNAME"):
                    if stem:
                        raise hiragana_function_error(stem, line)
                    raise SuruError(f"「{words[k]}」の前に関数名(漢字かカタカナ)が必要です", line)
                name_tok = tokens.pop()
                if _is_all_hiragana(name_tok.value + stem):
                    raise hiragana_function_error(name_tok.value + stem, line)
                tokens.append(Token("CALL", name_tok.value + stem + SURU, line, words[k]))
                words = words[k + 1 :]
            for w in words:
                if w in CALL_FORMS:
                    raise SuruError(f"「{w}」の前に関数名(漢字かカタカナ)が必要です", line)
                tokens.append(_hiragana_word_token(w, line))
    return tokens


def tokenize_punct_line(text: str, line: int) -> list[Token]:
    """句読点の書き方の1行を字句解析する。「。」は PERIOD トークンになる"""
    tokens: list[Token] = []
    run: list[tuple[str, bool]] = []
    buf = ""
    i, n = 0, len(text)

    def flush() -> None:
        nonlocal buf
        if buf:
            run.append((buf, False))
            buf = ""
        if run:
            tokens.extend(segment_run(run, line))
            run.clear()

    while i < n:
        c = text[i]
        if c in SPACES:
            flush()
        elif c == COMMA:
            flush()
            tokens.append(Token("SEP", COMMA, line))
        elif c in COMMENT_STARTS and not buf and not run:
            break
        elif c == "「":
            flush()
            j = text.find("」", i + 1)
            if j < 0:
                raise SuruError("文字列の「に対応する」がありません", line)
            tokens.append(Token("STR", text[i + 1 : j], line))
            i = j
        elif c == NAME_OPEN:
            j = _find_name_close(text, i, line)
            if buf:
                run.append((buf, False))
                buf = ""
            run.append((text[i + 1 : j], True))
            i = j
        elif c in OPEN_PARENS:
            flush()
            tokens.append(Token("LP", "(", line))
        elif c in CLOSE_PARENS:
            flush()
            tokens.append(Token("RP", ")", line))
        elif c == PERIOD:
            flush()
            tokens.append(Token("PERIOD", PERIOD, line))
        elif c in RESERVED_MARKS:
            raise SuruError(f"{RESERVED_MARKS[c]}は将来の書き方のために予約されています(文字列の中では使えます)", line)
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
        if not is_punct_line(raw):
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
        for sentence in split_sentences(tokens):
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


@dataclass
class Str:
    value: str


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
    cases: list  # [(パターン, 式)]
    default: Any
    line: int


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


TOP_LEVEL_ONLY = (TypeDef, TraitDecl, TraitImpl)
BUILTIN_TYPES = ("数", "文字列", "真偽", "リスト", "関数")


class ParseContext:
    """構文解析で使う、定義済みの型と形の名前(「3 と 4 の 点」を読むために先に集める)"""

    def __init__(self, ctors: dict | None = None, types: dict | None = None):
        self.ctors: dict[str, tuple[str, list]] = dict(ctors or {})  # 形 → (型, フィールド名)
        self.types: dict[str, list] = dict(types or {})  # 型 → [形]

    def copy(self) -> "ParseContext":
        return ParseContext(self.ctors, self.types)

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


def merge_piped(args: dict, piped: Any) -> dict:
    """「して」の結果を「を」に入れる。「を」が既にあれば、前に並べてリストにする"""
    args = dict(args)
    if WO in args:
        given = args[WO]
        items = given.items if isinstance(given, ListLit) else [given]
        args[WO] = ListLit([piped] + items)
    else:
        args = {WO: piped, **args}
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
    if isinstance(pat, PCtor):
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
        elif isinstance(p, PNamed):
            for f, q in p.fields:
                if p.ctor is not None and f not in _CTX.ctors[p.ctor][1]:
                    raise SuruError(f"「{p.ctor}」には「{f}」というフィールドがありません", line)
                walk(q)

    walk(pat)


def check_exhaustive(cases: list, line: int) -> None:
    """選択肢の型の場合分けで、書かれていない形があればエラーにする"""
    names = set()
    for pat, _ in cases:
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
        return self.pipeline()

    # パイプライン := 区間 { 区間 }
    # 区間 := { 値 助詞 } 呼び出し(…して | …する | …すること)
    # 「…して」の結果は次の区間の「を」に入る。
    def pipeline(self) -> Any:
        piped: Any = None
        has_piped = False
        while True:
            args: dict = {}
            while True:
                tok = self.peek()
                if tok is None or tok.kind in ("RP", "PERIOD") or (tok.kind == "KW" and tok.value in CONTINUATION_KEYWORDS):
                    break
                if tok.kind == "CALL" and tok.form != KOTO:
                    break
                if tok.kind == "CALL":  # …すること
                    self.next()
                    if not is_part(self.peek()):
                        # 区間の最後の「こと」は、前に並んだ引数を受け取る(部分適用)
                        if has_piped:
                            args = merge_piped(args, piped)
                        return Ref(tok.value, args, tok.line)
                    # 後ろに助詞が続く「こと」は外側の呼び出しの引数(関数そのもの)
                    value: Any = Ref(tok.value, {}, tok.line)
                elif is_kw(tok, KW_LAMBDA):
                    self.next()
                    if has_piped:
                        raise SuruError("「して」の後に「受け取って」は書けません", tok.line)
                    value = self.lambda_rest(args, tok.line)
                    args = {}
                else:
                    value = self.list_expr()
                part = self.peek()
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
                args = merge_piped(args, piped)
            piped = Call(tok.value, args, tok.line)
            has_piped = True
            if tok.form == SURU:
                return piped

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
        except SuruError:
            return None
        if not is_kw(self.peek(), KW_THEN):
            return None
        cases: list = []
        default = None
        while True:
            check_pattern(pat, self.peek().line)
            self.next()  # ならば
            cases.append((pat, self.case_body()))
            tok = self.peek()
            if is_kw(tok, KW_ELSE):
                self.next()
                default = self.case_body()
                break
            if tok is None or tok.kind in ("RP", "PERIOD") or not self.sep_here():
                break
            pat = self.pattern()
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
        return PValue(self.list_expr())

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
        items = [self.comparison()]
        while is_kw(self.peek(), KW_TO) and not self.sep_stop():
            self.next()
            items.append(self.comparison())
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

    def comparison(self) -> Any:
        left = self.additive()
        if is_kw(self.peek(), KW_NO) and is_ctor(self.peek(1)) and self._compares_at(2):
            # 「（3 と 4） の 点 が …」
            no = self.next()
            left = Construct(self.next().value, [left], no.line)
        tok = self.peek()
        if self.sep_stop():
            return left
        if is_kw(tok, KW_GA):
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

    def atom(self) -> Any:
        tok = self.next()
        if tok.kind == "NUM":
            return Num(tok.value)
        if tok.kind == "STR":
            return Str(tok.value)
        if tok.kind == "WORD":
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
    for t in tokens:
        if t.kind == "WORD" and not t.quoted and _is_all_hiragana(t.value) and t.value != "それぞれ":
            raise hiragana_name_error(t.value, t.line)
    if last.kind == "WORD" and len(tokens) == 1:
        return last.value, [], False  # 値の定義: 「税率 とは 0.1」
    if last.kind != "CALL" or last.form != SURU:
        raise SuruError("関数名は「する」で終わる必要があります", last.line)
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
        if len(tokens) == 3 and tokens[0].kind == "WORD" and is_kw(tokens[1], KW_WA) and tokens[2].kind == "WORD":
            return parse_trait_impl(node, tokens)
        return ExprParser(flatten(node)).parse_all()
    head = tokens[:towa]
    after = raw[_index_of(raw, tokens[towa]) + 1 :]
    if len(head) == 3 and head[0].kind == "WORD" and is_kw(head[1], KW_TOIU) and is_kw(head[2], KW_SEISHITSU):
        return parse_trait_decl(node, head[0], after)
    name, params, is_function = parse_definition_head(head, node.line.number)
    if nosep(after):
        # 同じ行に本体がある: 深い行はその続き
        body: Any = ExprParser(_with_children(after, node.children)).parse_all()
    else:
        if not node.children:
            raise SuruError("「とは」の後に本体が必要です", node.line.number)
        body = parse_block(node.children)
    return Define(name, params, body, is_function, node.line.number)


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


def attach_provisos(statements: list) -> list:
    """「ただし」の定義を、直前の(ただしでない)定義の局所定義にする"""
    out: list = []
    target: Any = None
    extra: dict[int, list] = {}
    for s in statements:
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
            s.body = Block([p.define for p in provisos] + [s.body])
        elif isinstance(s, TraitDecl):
            for p in provisos:
                if p.define is None:
                    s.sigs.append(p.sig)
                else:
                    s.defaults.append(_function_define(p.define, "性質の中", p.line))
        else:
            for p in provisos:
                s.defs.append(_function_define(p.define, f"「{s.type_name} は {s.trait}」の後", p.line))
    return out


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


def parse_program(source: str, ctx: ParseContext | None = None) -> list:
    """プログラムを解析する。ctx を渡すと、見つけた型をそこに登録する(対話モードで使う)"""
    global _CTX
    nodes = build_layout(split_lines(source))
    ctx = ctx if ctx is not None else ParseContext()
    # 「3 と 4 の 点」を読むために、型の定義を先に集める(定義の順番は自由)
    for n in nodes:
        td = try_parse_typedef(n)
        if td is not None:
            ctx.add(td)
    saved, _CTX = _CTX, ctx
    try:
        return attach_provisos([parse_statement(n) for n in nodes])
    finally:
        _CTX = saved


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


@dataclass(frozen=True)
class Record:
    """組の値。「（横 は 3 で 縦 は 4 の 点）」"""

    ctor: str
    type_name: str
    fields: tuple
    values: tuple

    def get(self, name: str) -> Any:
        return self.values[self.fields.index(name)]


def type_name_of(v: Any) -> str:
    if isinstance(v, Record):
        return v.type_name
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
    return str(v)


def _num(v: Any, line: int | None) -> Any:
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
    print(it.format(a[WO]))
    return a[WO]


BUILTINS = [
    Builtin("表示する", [(WO, True)], _show),
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
    Builtin("写像する", [(WO, True), ("で", True)], _b_map),
    Builtin("畳み込みする", [(WO, True), ("から", True), ("で", True)], _b_fold),
]


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


class Interpreter:
    def __init__(self) -> None:
        self.globals = make_global_env()
        self.ctx = ParseContext()
        self.traits: dict[str, dict] = {}  # 性質 → {関数名: (引数, 既定の実装 or None)}
        self.impls: dict[tuple[str, str], dict] = {}  # (性質, 型) → {関数名: Function}
        self.fixed: set[str] = set()  # 形の名前・性質の関数の名前(上書きできない)
        # 組み込みの性質「表示可能」: 実装しなくても全部の型が持つ。実装すると表示が変わる
        self.register_trait(TraitDecl(SHOWABLE, [(TO_STRING, [(WO, "x")])], [], 0))

    def run(self, source: str) -> list[Any]:
        """プログラムを実行し、トップレベルの式の値のリストを返す"""
        ctx = self.ctx.copy()
        program = parse_program(source, ctx)
        self.ctx = ctx
        # 定義は先にすべて登録する(定義の順番は自由。相互再帰もできる)
        for stmt in program:
            if isinstance(stmt, TypeDef):
                self.register_type(stmt)
        for stmt in program:
            if isinstance(stmt, TraitDecl):
                self.register_trait(stmt)
        for stmt in program:
            if isinstance(stmt, TraitImpl):
                self.register_impl(stmt)
        for stmt in program:
            if isinstance(stmt, Define):
                if stmt.name in self.fixed:
                    raise SuruError(f"「{stmt.name}」は形か性質の関数の名前なので、定義し直せません", stmt.line)
                self.define(stmt, self.globals)
        return [self.eval(s, self.globals) for s in program if not isinstance(s, (Define,) + TOP_LEVEL_ONLY)]

    def run_text(self, source: str) -> list[str]:
        """実行して、トップレベルの式の値を表示用の文字列で返す"""
        return [self.format(v) for v in self.run(source)]

    # --- 型と性質の登録 ---------------------------------------------------

    def register_type(self, td: TypeDef) -> None:
        for c, fields in td.ctors:
            if not fields:
                if c in self.globals.vars:
                    raise SuruError(f"形「{c}」は既に別の名前として使われています", td.line)
                self.globals.vars[c] = Record(c, td.name, (), ())
                self.fixed.add(c)

    def register_trait(self, decl: TraitDecl) -> None:
        if decl.name in self.traits:
            raise SuruError(f"性質「{decl.name}」は既に定義されています", decl.line)
        methods: dict[str, tuple] = {}
        members = [(n, ps, None) for n, ps in decl.sigs] + [(d.name, d.params, d) for d in decl.defaults]
        for fname, params, d in members:
            if fname in methods:
                raise SuruError(f"性質「{decl.name}」の中で「{fname}」が2回書かれています", decl.line)
            if fname in self.globals.vars:
                raise SuruError(f"「{fname}」は既に使われている名前なので、性質の関数にできません", decl.line)
            default = Function(fname, d.params, d.body, self.globals) if d else None
            methods[fname] = (params, default)
        self.traits[decl.name] = methods
        for fname, (params, _) in methods.items():
            self.globals.vars[fname] = TraitMethod(fname, decl.name, params)
            self.fixed.add(fname)

    def register_impl(self, impl: TraitImpl) -> None:
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
            fns[d.name] = Function(d.name, d.params, d.body, self.globals)
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

    def define(self, d: Define, env: Env) -> None:
        if d.is_function:
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
            return get_field(self.eval(node.target, env), node.name, node.line)
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
            for pat, body in node.cases:
                local = Env(env)
                if self.match(pat, v, local):
                    return self.eval(body, local)
            if node.default is not None:
                return self.eval(node.default, env)
            raise SuruError(f"「{self.format(v)}」はどの場合にも当てはまりません", node.line)
        if isinstance(node, Each):
            return _list(self.eval(node.target, env), "「の それぞれ」の前", node.line)
        if isinstance(node, Neg):
            return -_num(self.eval(node.operand, env), None)
        if isinstance(node, BinOp):
            return apply_op(node.op, self.eval(node.left, env), self.eval(node.right, env), node.line)
        if isinstance(node, If):
            cond = self.eval(node.cond, env)
            return self.eval(node.then if cond else node.other, env)
        if isinstance(node, Call):
            fn = env.lookup(node.name, node.line)
            args = {p: self.eval(a, env) for p, a in node.args.items()}
            each = [p for p, a in node.args.items() if isinstance(a, Each)]
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
        return self.eval(fn.body, local)


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
            for v in interp.run(source):
                print(interp.format(v))
        except SuruError as e:
            print(f"エラー: {e}")
        except RecursionError:
            print("エラー: 再帰が深すぎます")


def main(argv: list[str]) -> int:
    sys.setrecursionlimit(10000)
    if len(argv) < 2:
        repl()
        return 0
    with open(argv[1], encoding="utf-8") as f:
        source = f.read()
    interp = Interpreter()
    try:
        for v in interp.run(source):
            print(interp.format(v))
    except SuruError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

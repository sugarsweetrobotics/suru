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
KEYWORDS = {KW_TO, KW_TOWA, KW_NO, KW_GA, KW_IF, KW_THEN, KW_ELSE, KW_LAMBDA, KW_RETURN}
CONTINUATION_KEYWORDS = {KW_THEN, KW_ELSE}  # 行頭に来たら前の文の続きとみなす

# 引数を区別する格助詞。長いものから順に照合する(「より」「から」を先に)
PARTICLES = ("より", "から", "を", "に", "で", "へ")
WO = "を"

# 将来の「改行を減らす書き方」のために予約している記号
RESERVED_MARKS = {"、": "読点「、」", "・": "中黒「・」"}

SURU = "する"       # 終止形: パイプラインの終わり
SHITE = "して"      # 連用形: 結果を次の関数の「を」へ渡す
KOTO = "すること"   # 名詞化: 関数そのもの(値)

PROPERTIES = {"先頭", "残り", "最後", "長さ", "それぞれ"}


@dataclass
class Token:
    kind: str  # NUM STR OP LP RP WORD KW PART CALL
    value: Any
    line: int
    form: str = ""  # CALL のとき "する" / "して" / "すること"

    def __repr__(self) -> str:
        return f"{self.kind}:{self.value}{('/' + self.form) if self.form else ''}"


def _is_hiragana(c: str) -> bool:
    return "ぁ" <= c <= "ゟ"


def _classify_call(word: str, line: int) -> Token | None:
    for form in (KOTO, SURU, SHITE):
        if word.endswith(form) and len(word) > len(form):
            return Token("CALL", word[: -len(form)] + SURU, line, form)
    return None


def _classify(word: str, line: int) -> list[Token]:
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

    def flush() -> None:
        nonlocal buf
        if buf:
            tokens.extend(_classify(buf, line))
            buf = ""

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


@dataclass
class Line:
    indent: int
    tokens: list[Token]
    number: int


def split_lines(source: str) -> list[Line]:
    lines = []
    for number, raw in enumerate(source.splitlines(), start=1):
        indent = 0
        for c in raw:
            if c in INDENT_WIDTH:
                indent += INDENT_WIDTH[c]
            else:
                break
        tokens = tokenize_line(raw, number)
        if tokens:
            lines.append(Line(indent, tokens, number))
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
            if pos < len(lines) and lines[pos].indent > indent:
                node.children = block(indent + 1)
            # 行頭が ならば/そうでなければ の行は前の文の続き
            first = ln.tokens[0]
            if nodes and first.kind == "KW" and first.value in CONTINUATION_KEYWORDS:
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
    out = list(node.line.tokens)
    for c in node.children:
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


class ExprParser:
    """1つの式(トークン列)を解析する"""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self, k: int = 0) -> Token | None:
        i = self.pos + k
        return self.tokens[i] if i < len(self.tokens) else None

    def next(self) -> Token:
        tok = self.peek()
        if tok is None:
            last = self.tokens[-1].line if self.tokens else None
            raise SuruError("式が途中で終わっています", last)
        self.pos += 1
        return tok

    def last_line(self) -> int | None:
        if not self.tokens:
            return None
        return self.tokens[min(self.pos, len(self.tokens) - 1)].line

    def parse_all(self) -> Any:
        expr = self.expr()
        tok = self.peek()
        if tok is not None:
            raise SuruError(f"余分な「{tok.value}」があります", tok.line)
        return expr

    # 式 := もし 式 ならば 式 そうでなければ 式 | パイプライン
    def expr(self) -> Any:
        if is_kw(self.peek(), KW_IF):
            self.next()
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
                if tok is None or tok.kind == "RP" or (tok.kind == "KW" and tok.value in CONTINUATION_KEYWORDS):
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
    def list_expr(self) -> Any:
        first = self.comparison()
        if not is_kw(self.peek(), KW_TO):
            return first
        items = [first]
        while is_kw(self.peek(), KW_TO):
            self.next()
            items.append(self.comparison())
        return ListLit(items)

    def comparison(self) -> Any:
        left = self.additive()
        tok = self.peek()
        if is_kw(tok, KW_GA):
            self.next()
            return BinOp("==", left, self.additive(), tok.line)
        if tok is not None and tok.kind == "OP" and tok.value in ("==", "!=", "<", ">", "<=", ">="):
            self.next()
            right = self.additive()
            return BinOp(tok.value, left, right, tok.line)
        return left

    def additive(self) -> Any:
        left = self.term()
        while (tok := self.peek()) is not None and tok.kind == "OP" and tok.value in ("+", "-"):
            self.next()
            left = BinOp(tok.value, left, self.term(), tok.line)
        return left

    def term(self) -> Any:
        left = self.unary()
        while (tok := self.peek()) is not None and tok.kind == "OP" and tok.value in ("*", "/", "%"):
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
        if tok is not None and tok.kind == "OP" and tok.value == "^":
            self.next()
            return BinOp("^", base, self.unary(), tok.line)  # 右結合
        return base

    # 「リスト の 残り の 先頭」
    def postfix(self) -> Any:
        node = self.atom()
        while is_kw(self.peek(), KW_NO):
            no = self.next()
            name = self.next()
            if name.kind != "WORD" or name.value not in PROPERTIES:
                raise SuruError(
                    f"「の」の後には {'・'.join(sorted(PROPERTIES))} のどれかを書いてください", no.line
                )
            node = Each(node, no.line) if name.value == "それぞれ" else Prop(node, name.value, no.line)
        return node

    def atom(self) -> Any:
        tok = self.next()
        if tok.kind == "NUM":
            return Num(tok.value)
        if tok.kind == "STR":
            return Str(tok.value)
        if tok.kind == "WORD":
            return Var(tok.value, tok.line)
        if tok.kind == "LP":
            inner = self.expr()
            close = self.next()
            if close.kind != "RP":
                raise SuruError("「)」が必要です", close.line)
            return inner
        if tok.kind == "CALL" and tok.form == KOTO:
            return Ref(tok.value, {}, tok.line)
        raise SuruError(f"ここに「{tok.value}」は書けません", tok.line)


def parse_definition_head(tokens: list[Token], line: int) -> tuple[str, list, bool]:
    """「a を b で 除算する」→ ("除算する", [("を", "a"), ("で", "b")], True)、「x」→ ("x", [], False)"""
    if not tokens:
        raise SuruError("「とは」の前に定義する名前が必要です", line)
    last = tokens[-1]
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


def parse_statement(node: Node) -> Any:
    tokens = node.line.tokens
    towa = next((i for i, t in enumerate(tokens) if is_kw(t, KW_TOWA)), None)
    if towa is None:
        return ExprParser(flatten(node)).parse_all()
    name, params, is_function = parse_definition_head(tokens[:towa], node.line.number)
    after = tokens[towa + 1 :]
    if after:
        # 同じ行に本体がある: 深い行はその続き
        body_tokens = after + [t for c in node.children for t in flatten(c)]
        body: Any = ExprParser(body_tokens).parse_all()
    else:
        if not node.children:
            raise SuruError("「とは」の後に本体が必要です", node.line.number)
        body = parse_block(node.children)
    return Define(name, params, body, is_function, node.line.number)


def parse_block(nodes: list[Node]) -> Any:
    statements = [parse_statement(n) for n in nodes]
    if isinstance(statements[-1], Define):
        raise SuruError("ブロックの最後は式でなければなりません", nodes[-1].line.number)
    if len(statements) == 1:
        return statements[0]
    return Block(statements)


def parse_program(source: str) -> list:
    return [parse_statement(n) for n in build_layout(split_lines(source))]


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


FUNCTION_TYPES = (Function, Builtin, Partial)


@dataclass
class Lazy:
    """値の定義(「税率 とは 0.1」)。ブロック内での相互参照のため、使うときに評価する"""

    expr: Any
    env: Env
    value: Any = None
    done: bool = False


def format_value(v: Any, nested: bool = False) -> str:
    if v is True:
        return "真"
    if v is False:
        return "偽"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, tuple):
        if not v:
            return "空"
        return "（" + " と ".join(format_value(x, True) for x in v) + "）"
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
    print(format_value(a[WO]))
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


class Interpreter:
    def __init__(self) -> None:
        self.globals = make_global_env()

    def run(self, source: str) -> list[Any]:
        """プログラムを実行し、トップレベルの式の値のリストを返す"""
        program = parse_program(source)
        # 定義は先にすべて登録する(定義の順番は自由。相互再帰もできる)
        for stmt in program:
            if isinstance(stmt, Define):
                self.define(stmt, self.globals)
        return [self.eval(s, self.globals) for s in program if not isinstance(s, Define)]

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
        if not isinstance(fn, (Function, Builtin)):
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
        if line.rstrip().endswith(KW_TOWA) or (len(buf) > 1 and line.strip()):
            continue
        source = "\n".join(buf)
        buf = []
        if not source.strip():
            continue
        try:
            for v in interp.run(source):
                print(format_value(v))
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
    try:
        for v in Interpreter().run(source):
            print(format_value(v))
    except SuruError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

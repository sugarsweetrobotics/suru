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

KW_TO = "と"          # 引数の区切り
KW_WO = "を"          # 目的格(関数名の直前)
KW_TOWA = "とは"      # 定義
KW_IF = "もし"
KW_THEN = "ならば"
KW_ELSE = "そうでなければ"
KEYWORDS = {KW_TO, KW_WO, KW_TOWA, KW_IF, KW_THEN, KW_ELSE}
CONTINUATION_KEYWORDS = {KW_THEN, KW_ELSE}  # 行頭に来たら前の文の続きとみなす

SURU = "する"   # 終止形: パイプラインの終わり
SHITE = "して"  # 連用形: 結果を次の関数の第1引数へ渡す


@dataclass
class Token:
    kind: str  # NUM STR OP LP RP WORD KW CALL
    value: Any
    line: int
    form: str = ""  # CALL のとき "する" か "して"

    def __repr__(self) -> str:
        return f"{self.kind}:{self.value}{('/' + self.form) if self.form else ''}"


def _classify(word: str, line: int) -> Token:
    norm = unicodedata.normalize("NFKC", word)
    if norm in OPERATORS or word in OPERATORS:
        return Token("OP", OPERATORS.get(norm, OPERATORS.get(word)), line)
    try:
        num = int(norm)
        return Token("NUM", num, line)
    except ValueError:
        pass
    try:
        num = float(norm)
        return Token("NUM", num, line)
    except ValueError:
        pass
    if word in KEYWORDS:
        return Token("KW", word, line)
    if word in ("真", "偽"):
        return Token("NUM", word == "真", line)
    for form in (SURU, SHITE):
        if word.endswith(form) and len(word) > len(form):
            stem = word[: -len(form)]
            # 「を加算する」のように を が付いていれば取り除く
            if stem.startswith(KW_WO) and len(stem) > 1:
                stem = stem[1:]
            return Token("CALL", stem + SURU, line, form)
    return Token("WORD", word, line)


def tokenize_line(text: str, line: int) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(text)
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            tokens.append(_classify(buf, line))
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
        else:
            buf += c
        i += 1
    flush()

    # 「を 加算する」のように を が独立していても同じに扱う
    merged: list[Token] = []
    for t in tokens:
        if t.kind == "CALL" and merged and merged[-1].kind == "KW" and merged[-1].value == KW_WO:
            merged.pop()
        merged.append(t)
    return merged


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
    args: list
    line: int


@dataclass
class If:
    cond: Any
    then: Any
    other: Any


@dataclass
class Define:
    name: str
    params: list[str]
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


class ExprParser:
    """1つの式(トークン列)を解析する"""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> Token:
        tok = self.peek()
        if tok is None:
            last = self.tokens[-1].line if self.tokens else None
            raise SuruError("式が途中で終わっています", last)
        self.pos += 1
        return tok

    def parse_all(self) -> Any:
        expr = self.expr()
        tok = self.peek()
        if tok is not None:
            raise SuruError(f"余分なトークン「{tok.value}」があります", tok.line)
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
    # 区間 := [ 算術式 { と 算術式 } ] 呼び出し(…して | …する)
    # 「…して」の結果は次の区間の第1引数になる。
    def pipeline(self) -> Any:
        acc: Any = None
        has_acc = False
        while True:
            args: list = []
            tok = self.peek()
            if tok is None or tok.kind != "CALL":
                if has_acc and (tok is None or tok.kind in ("RP",) or tok.kind == "KW" and tok.value in (KW_THEN, KW_ELSE)):
                    raise SuruError("「して」の後に関数呼び出しが必要です", self.tokens[self.pos - 1].line)
                args.append(self.comparison())
                while is_kw(self.peek(), KW_TO):
                    self.next()
                    args.append(self.comparison())
            tok = self.peek()
            if tok is not None and tok.kind == "CALL":
                self.next()
                acc = Call(tok.value, ([acc] if has_acc else []) + args, tok.line)
                has_acc = True
                if tok.form == SHITE:
                    continue
                return acc
            # 呼び出しで終わらない
            if has_acc:
                line = tok.line if tok else self.tokens[-1].line
                raise SuruError("「して」の後は「…する」で終わる必要があります", line)
            if len(args) > 1:
                raise SuruError("「と」で並べた値の後には「を…する」が必要です", self.tokens[0].line)
            return args[0]

    def comparison(self) -> Any:
        left = self.additive()
        tok = self.peek()
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
        base = self.atom()
        tok = self.peek()
        if tok is not None and tok.kind == "OP" and tok.value == "^":
            self.next()
            return BinOp("^", base, self.unary(), tok.line)  # 右結合
        return base

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
        raise SuruError(f"ここに「{tok.value}」は書けません", tok.line)


def parse_definition_head(tokens: list[Token], line: int) -> tuple[str, list[str], bool]:
    """「a と b を加算する」→ ("加算する", ["a", "b"], True)、「x」→ ("x", [], False)"""
    if not tokens:
        raise SuruError("「とは」の前に定義する名前が必要です", line)
    last = tokens[-1]
    if last.kind == "WORD" and len(tokens) == 1:
        return last.value, [], False  # 値の定義: 「税率 とは 0.1」
    if last.kind != "CALL" or last.form != SURU:
        raise SuruError("関数名は「する」で終わる必要があります", last.line)
    params: list[str] = []
    rest = tokens[:-1]
    for i, t in enumerate(rest):
        if i % 2 == 0:
            if t.kind != "WORD":
                raise SuruError(f"引数名に「{t.value}」は使えません", t.line)
            if t.value in params:
                raise SuruError(f"引数名「{t.value}」が重複しています", t.line)
            params.append(t.value)
        elif not is_kw(t, KW_TO):
            raise SuruError("引数は「と」で区切ってください", t.line)
    if rest and len(rest) % 2 == 0:
        raise SuruError("「と」の後に引数名が必要です", rest[-1].line)
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
# 評価
# ---------------------------------------------------------------------------


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
    params: list[str]
    body: Any
    closure: Env


@dataclass
class Builtin:
    name: str
    arity: int | None
    fn: Any


@dataclass
class Lazy:
    """値の定義(「税率 とは 0.1」)。ブロック内での相互参照のため、使うときに評価する"""

    expr: Any
    env: Env
    value: Any = None
    done: bool = False


def format_value(v: Any) -> str:
    if v is True:
        return "真"
    if v is False:
        return "偽"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (Function, Builtin)):
        return f"<関数 {v.name}>"
    return str(v)


def _num(v: Any, line: int) -> Any:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SuruError(f"数ではない値「{format_value(v)}」で計算しようとしました", line)
    return v


def apply_op(op: str, a: Any, b: Any, line: int) -> Any:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
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


def make_global_env() -> Env:
    env = Env()
    builtins = [
        Builtin("表示する", 1, lambda x: (print(format_value(x)), x)[1]),
        Builtin("絶対値にする", 1, abs),
    ]
    for b in builtins:
        env.vars[b.name] = b
    return env


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
        if isinstance(node, Neg):
            return -_num(self.eval(node.operand, env), 0)
        if isinstance(node, BinOp):
            return apply_op(node.op, self.eval(node.left, env), self.eval(node.right, env), node.line)
        if isinstance(node, If):
            cond = self.eval(node.cond, env)
            return self.eval(node.then if cond else node.other, env)
        if isinstance(node, Call):
            fn = env.lookup(node.name, node.line)
            args = [self.eval(a, env) for a in node.args]
            return self.call(fn, args, node.line)
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

    def call(self, fn: Any, args: list, line: int) -> Any:
        if isinstance(fn, Builtin):
            if fn.arity is not None and len(args) != fn.arity:
                raise SuruError(f"「{fn.name}」の引数は{fn.arity}個です(渡されたのは{len(args)}個)", line)
            return fn.fn(*args)
        if isinstance(fn, Function):
            if len(args) != len(fn.params):
                raise SuruError(
                    f"「{fn.name}」の引数は{len(fn.params)}個です(渡されたのは{len(args)}個)", line
                )
            local = Env(fn.closure)
            local.vars.update(zip(fn.params, args))
            return self.eval(fn.body, local)
        raise SuruError(f"「{format_value(fn)}」は関数ではありません", line)


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

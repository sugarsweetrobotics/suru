"""「する」の静的な型検査(第1段階)

型を書かなくても、実行する前に型の間違いを見つける。Hindley–Milner の型推論を、
助詞つきの引数に合わせて広げたもの。

    python3 suru.py --検査 ファイル

第1段階で調べるもの: 数・文字列・真偽・リスト・関数・組・選択肢のある型・場合分け・
場合ごとの定義・述語。性質の関数と、動作の中身の型(手順・してから・した 結果)は
第2・第3段階で調べる予定で、今はどんな型とも合うものとして扱う。
"""

from __future__ import annotations

import itertools
from dataclasses import fields as dc_fields
from dataclasses import is_dataclass
from typing import Any

from suru import (
    BinOp, Block, Call, Chain, Construct, Define, Do, Each, Field, If, KW_KATSU, KW_MATAHA, Lambda,
    ListLit, Match, NamedConstruct, Neg, Not, Num, ParseContext, PBind, PCtor, PNamed, Prop, PSeq,
    PValue, Ref, RESULT, Run, Sequel, Str, SuruError, TraitDecl, TraitImpl, TypeDef, Update, Var, WO,
    HOLE, TO_STRING, MAP, BIND, UNIT, SHOWABLE, TOP_LEVEL_ONLY, is_predicate, parse_program,
)

# ---------------------------------------------------------------------------
# 型
# ---------------------------------------------------------------------------

_ids = itertools.count()


class TVar:
    """まだ決まっていない型(型変数)"""

    __slots__ = ("id", "ref")

    def __init__(self) -> None:
        self.id = next(_ids)
        self.ref: Any = None


class TCon:
    """数・文字列・真偽、リスト(要素の型)、動作(結果の型)、組や選択肢のある型"""

    __slots__ = ("name", "args")

    def __init__(self, name: str, args: tuple = ()):
        self.name = name
        self.args = tuple(args)


class TFun:
    """関数。引数は (助詞, 型) の並び(定義の順)。関数の値として渡すときは順番で合わせる"""

    __slots__ = ("params", "result")

    def __init__(self, params: list, result: Any):
        self.params = list(params)
        self.result = result


NUM, STR, BOOL = TCon("数"), TCon("文字列"), TCon("真偽")


def lst(t: Any) -> TCon:
    return TCon("リスト", (t,))


def act(t: Any) -> TCon:
    return TCon("動作", (t,))


def prune(t: Any) -> Any:
    while isinstance(t, TVar) and t.ref is not None:
        t = t.ref
    return t


def ftv(t: Any, out: set | None = None) -> set:
    out = set() if out is None else out
    t = prune(t)
    if isinstance(t, TVar):
        out.add(t)
    elif isinstance(t, TCon):
        for a in t.args:
            ftv(a, out)
    elif isinstance(t, TFun):
        for _, a in t.params:
            ftv(a, out)
        ftv(t.result, out)
    return out


class Mismatch(Exception):
    pass


def occurs(v: TVar, t: Any) -> bool:
    return v in ftv(t)


def unify(a: Any, b: Any) -> None:
    a, b = prune(a), prune(b)
    if a is b:
        return
    if isinstance(a, TVar):
        if occurs(a, b):
            raise Mismatch()
        a.ref = b
        return
    if isinstance(b, TVar):
        unify(b, a)
        return
    if isinstance(a, TCon) and isinstance(b, TCon):
        if a.name != b.name or len(a.args) != len(b.args):
            raise Mismatch()
        for x, y in zip(a.args, b.args):
            unify(x, y)
        return
    if isinstance(a, TFun) and isinstance(b, TFun):
        if len(a.params) != len(b.params):
            raise Mismatch()
        for (_, x), (_, y) in zip(a.params, b.params):
            unify(x, y)
        unify(a.result, b.result)
        return
    raise Mismatch()


# --- 表示 ---

VAR_NAMES = "甲乙丙丁戊己庚辛壬癸"


class Namer:
    def __init__(self) -> None:
        self.names: dict[TVar, str] = {}

    def __call__(self, t: Any, nested: bool = False) -> str:
        t = prune(t)
        if isinstance(t, TVar):
            if t not in self.names:
                k = len(self.names)
                self.names[t] = VAR_NAMES[k] if k < len(VAR_NAMES) else f"型{k + 1}"
            return self.names[t]
        if isinstance(t, TCon):
            if not t.args:
                return t.name
            s = f"{self(t.args[0], True)} の {t.name}"
            return f"（{s}）" if nested else s
        if isinstance(t, TFun):
            if not t.params:
                return f"（{self(t.result, True)} を 返すこと）"
            ps = " ".join(f"{self(x, True)} {p}" for p, x in t.params)
            return f"（{ps} 受け取って {self(t.result, True)} を 返すこと）"
        return "?"


def show(*ts: Any) -> list[str]:
    n = Namer()
    return [n(t) for t in ts]


# --- 型スキーム(多相) ---


class Constraint:
    """型の条件。t が決まったときに確かめる。
    kinds があれば「t はこれらの型のどれか」、trait があれば「t は性質を持ち、method の型は実装の型と同じ」"""

    __slots__ = ("t", "kinds", "message", "trait", "method", "ftype", "line")

    def __init__(self, t: Any, line: Any, kinds: tuple = (), message: str = "",
                 trait: str = "", method: str = "", ftype: Any = None):
        self.t, self.line, self.kinds, self.message = t, line, kinds, message
        self.trait, self.method, self.ftype = trait, method, ftype

    def subst(self, m: dict) -> "Constraint":
        return Constraint(
            _subst(self.t, m), self.line, self.kinds, self.message, self.trait, self.method,
            _subst(self.ftype, m) if self.ftype is not None else None,
        )

    def type_vars(self) -> set:
        out = ftv(self.t)
        if self.ftype is not None:
            ftv(self.ftype, out)
        return out


class Scheme:
    """多相な型: 「すべての vars について t」。constraints は使うたびに写して確かめる条件"""

    def __init__(self, vars_: list, t: Any, constraints: list | None = None):
        self.vars = vars_
        self.t = t
        self.constraints = constraints or []

    def instantiate(self, pending: list | None = None) -> Any:
        mapping = {v: TVar() for v in self.vars}
        if pending is not None:
            pending.extend(c.subst(mapping) for c in self.constraints)
        return _subst(self.t, mapping)


def _subst(t: Any, m: dict) -> Any:
    t = prune(t)
    if isinstance(t, TVar):
        return m.get(t, t)
    if isinstance(t, TCon):
        return TCon(t.name, tuple(_subst(a, m) for a in t.args)) if t.args else t
    if isinstance(t, TFun):
        return TFun([(p, _subst(a, m)) for p, a in t.params], _subst(t.result, m))
    return t


class TEnv:
    def __init__(self, parent: "TEnv | None" = None):
        self.vars: dict[str, Any] = {}  # 名前 → 型 か Scheme
        self.parent = parent

    def lookup(self, name: str) -> Any:
        e: TEnv | None = self
        while e is not None:
            if name in e.vars:
                return e.vars[name]
            e = e.parent
        return None

    def free_vars(self) -> set:
        out: set = set()
        e: TEnv | None = self
        while e is not None:
            for v in e.vars.values():
                if isinstance(v, Scheme):
                    out |= ftv(v.t) - set(v.vars)
                else:
                    ftv(v, out)
            e = e.parent
        return out


# ---------------------------------------------------------------------------
# 依存関係(相互再帰する定義をまとめて推論するため)
# ---------------------------------------------------------------------------


def referenced_names(node: Any, out: set) -> set:
    if isinstance(node, (Var, Call, Ref)):
        out.add(node.name)
    if isinstance(node, (list, tuple)):
        for x in node:
            referenced_names(x, out)
    elif isinstance(node, dict):
        for x in node.values():
            referenced_names(x, out)
    elif is_dataclass(node) and not isinstance(node, type):
        for f in dc_fields(node):
            referenced_names(getattr(node, f.name), out)
    return out


def sccs(defs: list, aliases: dict | None = None) -> list[list]:
    """強連結成分。依存される側から順に返す(Tarjan)。
    aliases は「性質の関数の名前 → その実装の定義の名前」(呼び出しは実装に依存する)"""
    aliases = aliases or {}
    names = {d.name: d for d in defs}
    graph = {}
    for d in defs:
        refs = set()
        for n in referenced_names(d.body, set()):
            refs.add(n)
            refs.update(aliases.get(n, ()))
        graph[d.name] = [n for n in refs if n in names]
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set = set()
    out: list[list] = []
    counter = itertools.count()

    def visit(v: str) -> None:
        index[v] = low[v] = next(counter)
        stack.append(v)
        on.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(names[w])
                if w == v:
                    break
            out.append(comp)

    for d in defs:
        if d.name not in index:
            visit(d.name)
    return out


# ---------------------------------------------------------------------------
# 推論
# ---------------------------------------------------------------------------


def _line(node: Any, default: Any = None) -> Any:
    return getattr(node, "line", None) or default


def first_line(node: Any) -> Any:
    """式の中で最初に見つかる行番号(行を持たない式のエラー用)"""
    line = getattr(node, "line", None)
    if line:
        return line
    if isinstance(node, (list, tuple)):
        items = list(node)
    elif isinstance(node, dict):
        items = list(node.values())
    elif is_dataclass(node) and not isinstance(node, type):
        items = [getattr(node, f.name) for f in dc_fields(node)]
    else:
        return None
    for x in items:
        line = first_line(x)
        if line:
            return line
    return None


class Checker:
    def __init__(self, ctx: ParseContext):
        self.ctx = ctx
        # 形のフィールドの型。型の引数はまだないので、プログラム全体で1つの型にそろえる
        self.field_types: dict[tuple[str, str], TVar] = {
            (c, f): TVar() for c, (_, fs) in ctx.ctors.items() for f in fs
        }
        self.traits: dict[str, dict] = {}  # 性質 → {"methods": {関数名: 引数}, "defaults": {関数名}}
        self.method_trait: dict[str, str] = {}  # 性質の関数 → 性質
        self.impls: dict[tuple[str, str], set] = {}  # (性質, 型名) → 実装した関数
        self.show_impls: set[str] = set()  # 「表示可能」の実装の定義の名前(文字列を返す)
        self.aliases: dict[str, list] = {}
        self.pending: list[Constraint] = []  # まだ確かめていない条件
        self.line: Any = None  # 今見ている式の行(位置の分からない式のエラー用)

    # --- エラー ---------------------------------------------------------

    def err(self, message: str, line: Any) -> SuruError:
        return SuruError(message, line or self.line)

    def unify_or(self, a: Any, b: Any, line: Any, message: "Any") -> None:
        """a と b をそろえる。そろわなければ message(a, b の表示) のエラー"""
        try:
            unify(a, b)
        except Mismatch:
            sa, sb = show(a, b)
            raise self.err(message(sa, sb), line) from None

    def expect(self, actual: Any, expected: Any, line: Any, what: str) -> None:
        self.unify_or(
            actual, expected, line,
            lambda sa, sb: f"{what}には{sb}が必要ですが、{sa}になっています",
        )

    # --- プログラム -----------------------------------------------------

    def check_program(self, program: list) -> None:
        defs = [s for s in program if isinstance(s, Define)]
        for s in program:
            if isinstance(s, TraitDecl):
                methods = dict(s.sigs)
                methods.update({d.name: d.params for d in s.defaults})
                self.traits[s.name] = {"methods": methods, "defaults": {d.name for d in s.defaults}}
                for m in methods:
                    self.method_trait[m] = s.name
                for d in s.defaults:
                    defs.append(self._renamed(d, impl_key(s.name, "", d.name)))
        for s in program:
            if isinstance(s, TraitImpl):
                self.impls[(s.trait, s.type_name)] = {d.name for d in s.defs}
                for d in s.defs:
                    key = impl_key(s.trait, s.type_name, d.name)
                    if s.trait == SHOWABLE:
                        self.show_impls.add(key)
                    defs.append(self._renamed(d, key))
        for d in defs:
            if d.name.startswith("\0"):
                self.aliases.setdefault(d.name.split("\0")[-1], []).append(d.name)
        env = self.infer_defs(defs, TEnv())
        for s in program:
            if isinstance(s, (Define,) + TOP_LEVEL_ONLY):
                continue
            self.line = first_line(s)
            self.infer(s, env)
            self.solve(env)
        self.solve(env)

    @staticmethod
    def _renamed(d: Define, name: str) -> Define:
        return Define(name, d.params, d.body, d.is_function, d.line)

    def inst(self, v: Any, line: Any = None, name: str = "") -> Any:
        """多相な型を写す。条件は呼んだ場所(line)のものとして確かめる"""
        if not isinstance(v, Scheme):
            return v
        start = len(self.pending)
        t = v.instantiate(self.pending)
        if line:
            for c in self.pending[start:]:
                c.line = line
                if c.kinds and name and "に渡した値: " not in c.message:
                    c.message = f"「{display_name(name)}」に渡した値: {c.message}"
        return t

    def infer_defs(self, defs: list, env: TEnv) -> TEnv:
        """定義の並びを推論し、それぞれの名前に多相な型を付けた新しい環境を返す"""
        scope = TEnv(env)
        for comp in sccs(defs, self.aliases):
            mono = {d.name: TVar() for d in comp}
            inner = TEnv(scope)
            inner.vars.update(mono)
            for d in comp:
                self.line = d.line
                t = self.infer_define(d, inner)
                self.unify_or(
                    mono[d.name], t, d.line,
                    lambda sa, sb, d=d: f"「{display_name(d.name)}」の型が合いません({sa} と {sb})",
                )
            self.solve(inner)
            outer_free = scope.free_vars()
            taken: set = set()
            for d in comp:
                t = mono[d.name]
                quantified = ftv(t) - outer_free
                mine = [c for c in self.pending if c.type_vars() & quantified]
                taken |= {id(c) for c in mine}
                scope.vars[d.name] = Scheme(list(quantified), t, mine)
            self.pending = [c for c in self.pending if id(c) not in taken]
        return scope

    # --- 型の条件 ---------------------------------------------------------

    def solve(self, env: TEnv) -> None:
        """型が決まった条件を確かめる"""
        progress = True
        while progress:
            progress = False
            for c in list(self.pending):
                if isinstance(prune(c.t), TVar):
                    continue
                if self.discharge(c, env):
                    self.pending.remove(c)
                    progress = True

    def discharge(self, c: Constraint, env: TEnv) -> bool:
        r = prune(c.t)
        name = r.name if isinstance(r, TCon) else "関数"
        if not c.trait:
            if name not in c.kinds:
                raise self.err(f"{c.message}です({show(r)[0]}になっています)", c.line)
            return True
        methods = self.impls.get((c.trait, name))
        if methods is None:
            raise self.err(f"{show(r)[0]}は性質「{c.trait}」を持っていません(「{c.method}」が使えません)", c.line)
        if c.method in methods:
            key = impl_key(c.trait, name, c.method)
        elif c.method in self.traits[c.trait]["defaults"]:
            key = impl_key(c.trait, "", c.method)
        else:
            return True  # 実装の足りない性質は実行時にエラーになる
        v = env.lookup(key)
        if v is None:
            return False
        impl = prune(self.inst(v))
        if not isinstance(impl, TFun):
            return True
        params = dict(impl.params)
        for p, t in c.ftype.params:
            if p in params:
                self.unify_or(
                    t, params[p], c.line,
                    lambda sa, sb, p=p: f"「{c.method}」({show(r)[0]}の実装)の「{p}」には{sb}が必要ですが、{sa}が渡されています",
                )
        self.unify_or(
            c.ftype.result, impl.result, c.line,
            lambda sa, sb: f"「{c.method}」({show(r)[0]}の実装)の値の型が合いません({sb} と {sa})",
        )
        return True

    def trait_fun(self, name: str, line: Any) -> TFun:
        """性質の関数の型。「を」(なければ最初の引数)の型で実装を選ぶ"""
        trait = self.method_trait[name]
        sig = self.traits[trait]["methods"][name]
        t = TVar()
        dispatch = next((p for p, _ in sig if p == WO), sig[0][0] if sig else None)
        params = []
        for p, pat in sig:
            if p == dispatch:
                params.append((p, t if isinstance(pat, str) else lst(t)))
            else:
                params.append((p, TVar()))
        ftype = TFun(params, TVar())
        if sig:
            self.pending.append(Constraint(t, line, trait=trait, method=name, ftype=ftype))
        return ftype

    def infer_define(self, d: Define, env: TEnv) -> Any:
        if not d.is_function:
            return self.infer(d.body, env)
        local = TEnv(env)
        params = [(p, self.bind_param(pat, local)) for p, pat in d.params]
        result = self.infer(d.body, local)
        if d.name in self.show_impls:
            self.expect(result, STR, d.line, f"「{TO_STRING}」の値")
        if is_predicate(d.name):
            self.expect(result, BOOL, d.line, f"述語「{d.name}」の値")
        return TFun(params, result)

    def bind_param(self, pat: Any, env: TEnv) -> Any:
        """関数の引数(「a」か「a と b」)に型を付ける"""
        if isinstance(pat, str):
            t = TVar()
            env.vars[pat] = t
            return t
        elem = TVar()
        for name in pat:
            env.vars[name] = elem
        return lst(elem)

    # --- 式 ---------------------------------------------------------------

    def infer(self, node: Any, env: TEnv) -> Any:
        line = _line(node)
        if line:
            self.line = line
        method = getattr(self, "infer_" + type(node).__name__, None)
        if method is None:
            return TVar()  # 第1段階では調べない式
        return method(node, env)

    def infer_Num(self, node: Num, env: TEnv) -> Any:
        if isinstance(node.value, bool):
            return BOOL
        if node.value == ():
            return lst(TVar())
        return NUM

    def infer_Str(self, node: Str, env: TEnv) -> Any:
        return STR

    def infer_Var(self, node: Var, env: TEnv) -> Any:
        v = env.lookup(node.name)
        if v is not None:
            return self.inst(v, node.line)
        info = self.ctx.ctors.get(node.name)
        if info is not None and not info[1]:
            return TCon(info[0])  # 中身のない形(「赤」)
        return TVar()  # 分からない名前は実行時にエラーになる

    def infer_ListLit(self, node: ListLit, env: TEnv) -> Any:
        elem = TVar()
        for item in node.items:
            t = self.infer(item, env)
            self.unify_or(
                elem, t, first_line(item),
                lambda sa, sb: f"リストの要素の型がそろっていません({sa} と {sb})。"
                "違う型の値をまとめるときは、組か選択肢のある型を使ってください",
            )
        return lst(elem)

    def infer_Prop(self, node: Prop, env: TEnv) -> Any:
        t = self.infer(node.target, env)
        if node.name == "長さ":
            self.need_kind(t, ("文字列", "リスト"), node.line, "「の 長さ」の前は文字列かリスト")
            return NUM
        elem = TVar()
        self.expect(t, lst(elem), node.line, f"「の {node.name}」の前")
        return lst(elem) if node.name == "残り" else elem

    def infer_Each(self, node: Each, env: TEnv) -> Any:
        t = self.infer(node.target, env)
        self.expect(t, lst(TVar()), node.line, "「の それぞれ」の前")
        return t

    def infer_Neg(self, node: Neg, env: TEnv) -> Any:
        self.expect(self.infer(node.operand, env), NUM, self.line, "「-」の後")
        return NUM

    def infer_Not(self, node: Not, env: TEnv) -> Any:
        self.expect(self.infer(node.operand, env), BOOL, node.line, "「でない」の前")
        return BOOL

    def infer_BinOp(self, node: BinOp, env: TEnv) -> Any:
        a = self.infer(node.left, env)
        b = self.infer(node.right, env)
        op = node.op
        if op in (KW_KATSU, KW_MATAHA):
            self.expect(a, BOOL, node.line, f"「{op}」の左")
            self.expect(b, BOOL, node.line, f"「{op}」の右")
            return BOOL
        if op in ("==", "!="):
            self.unify_or(a, b, node.line, lambda sa, sb: f"{sa} と {sb} は比べられません(同じ型どうしで比べてください)")
            return BOOL
        if op in ("<", ">", "<=", ">="):
            self.expect(a, NUM, node.line, f"「{op}」の左")
            self.expect(b, NUM, node.line, f"「{op}」の右")
            return BOOL
        if op == "+":
            self.unify_or(
                a, b, node.line,
                lambda sa, sb: f"「+」の両側の型が違います({sa} と {sb})。"
                "数を文字列につなぐときは「x を 文字列化する」を使ってください",
            )
            self.need_kind(a, ("数", "文字列", "リスト"), node.line, "「+」で足せるのは数・文字列・リスト")
            return a
        self.expect(a, NUM, node.line, f"「{op}」の左")
        self.expect(b, NUM, node.line, f"「{op}」の右")
        return NUM

    def need_kind(self, t: Any, kinds: tuple, line: Any, message: str) -> None:
        """t が kinds のどれかの型であること(t がまだ決まっていなければ、決まったときに確かめる)"""
        c = Constraint(t, line, kinds, message)
        if isinstance(prune(t), TVar):
            self.pending.append(c)
        else:
            self.discharge(c, TEnv())

    def infer_If(self, node: If, env: TEnv) -> Any:
        line = first_line(node) or self.line
        self.expect(self.infer(node.cond, env), BOOL, line, "「もし」の条件")
        a = self.infer(node.then, env)
        b = self.infer(node.other, env)
        self.unify_or(a, b, first_line(node.other) or line, lambda sa, sb: f"「ならば」と「そうでなければ」の値の型が違います({sa} と {sb})")
        return a

    def infer_Block(self, node: Block, env: TEnv) -> Any:
        defs = [s for s in node.statements if isinstance(s, Define)]
        local = self.infer_defs(defs, env)
        result: Any = TVar()
        for s in node.statements:
            if not isinstance(s, Define):
                result = self.infer(s, local)
        return result

    def infer_Lambda(self, node: Lambda, env: TEnv) -> Any:
        local = TEnv(env)
        params = [(p, self.bind_param(pat, local)) for p, pat in node.params]
        return TFun(params, self.infer(node.body, local))

    # --- 呼び出し ---------------------------------------------------------

    def infer_Call(self, node: Call, env: TEnv) -> Any:
        args: dict = {}
        each = False
        lifted: list = []
        for p, a in node.args.items():
            if isinstance(a, Each):
                t = self.infer(a.target, env)
                elem = TVar()
                self.expect(t, lst(elem), a.line, "「の それぞれ」の前")
                args[p] = elem
                each = True
            elif isinstance(a, Field) and a.name == RESULT and not self._has_field(RESULT):
                # 「入力 の 結果 を …」: 動作(やリスト)の結果に関数を適用する
                t = prune(self.infer(a.target, env))
                if isinstance(t, TCon) and t.name in ("動作", "リスト") and t.args:
                    args[p] = t.args[0]
                    lifted.append(t.name)
                else:
                    args[p] = TVar()
                    lifted.append("?")
            else:
                args[p] = self.infer(a, env)
        result = self.call_type(node.name, args, node.line, env)
        if each:
            result = lst(result)
        if lifted:
            result = TCon(lifted[-1], (result,)) if lifted[-1] != "?" else TVar()
        return result

    def call_type(self, name: str, args: dict, line: Any, env: TEnv) -> Any:
        v = env.lookup(name)
        if v is not None:
            t = prune(self.inst(v, line, name))
            if isinstance(t, TFun):
                return self.call_fun(name, t, args, line)
            return TVar()
        if name in self.method_trait:
            result = self.call_fun(name, self.trait_fun(name, line), args, line)
            self.solve(env)
            return result
        typer = BUILTIN_CALLS.get(name)
        if typer is not None:
            return typer(self, args, line)
        return TVar()  # 性質の関数(第2段階)や、実行時にエラーになる名前

    def call_fun(self, name: str, t: TFun, args: dict, line: Any) -> Any:
        params = dict(t.params)
        for p in args:
            if p not in params:
                raise self.err(f"「{name}」は「{p}」の引数を受け取りません", line)
        for p, pt in t.params:
            if p not in args:
                raise self.err(f"「{name}」には「{p}」の引数が必要です", line)
            self.arg(args[p], pt, line, name, p)
        return t.result

    def arg(self, actual: Any, expected: Any, line: Any, name: str, part: str) -> None:
        self.unify_or(
            actual, expected, line,
            lambda sa, sb: f"「{name}」の「{part}」には{sb}が必要ですが、{sa}が渡されています",
        )

    def fun_value(self, name: str, env: TEnv, line: Any) -> Any:
        """「三倍すること」の型"""
        v = env.lookup(name)
        if v is not None:
            return self.inst(v, line, name)
        if name in self.method_trait:
            return self.trait_fun(name, line)
        sig = BUILTIN_FUNS.get(name)
        if sig is not None:
            return sig()
        return TVar()

    def infer_Ref(self, node: Ref, env: TEnv) -> Any:
        t = prune(self.fun_value(node.name, env, node.line))
        if not node.args:
            return t
        given = {p: self.infer(a, env) for p, a in node.args.items()}
        if not isinstance(t, TFun):
            return TVar()
        params = dict(t.params)
        for p, at in given.items():
            if p not in params:
                raise self.err(f"「{node.name}」は「{p}」の引数を受け取りません", node.line)
            self.arg(at, params[p], node.line, node.name, p)
        return TFun([(p, x) for p, x in t.params if p not in given], t.result)

    def apply(self, fn: Any, values: list, line: Any, what: str) -> Any:
        """関数の値に値を順に渡したときの型(足りなければ部分適用)"""
        t = prune(fn)
        if isinstance(t, TVar):
            r = TVar()
            unify(t, TFun([(WO, v) for v in values], r))
            return r
        if not isinstance(t, TFun):
            raise self.err(f"{what}には関数が必要ですが、{show(t)[0]}になっています", line)
        if len(values) > len(t.params):
            raise self.err(f"{what}の関数{show(t)[0]}に渡す値が多すぎます", line)
        for (p, pt), v in zip(t.params, values):
            self.unify_or(v, pt, line, lambda sa, sb: f"{what}の関数は{sb}を受け取りますが、{sa}が渡されます")
        rest = t.params[len(values):]
        return TFun(rest, t.result) if rest else t.result

    # --- 組 ---------------------------------------------------------------

    def ctor_type(self, ctor: str) -> TCon:
        return TCon(self.ctx.ctors[ctor][0])

    def _has_field(self, name: str) -> bool:
        return any(f == name for (_, f) in self.field_types)

    def field_of(self, t: Any, name: str, line: Any) -> Any:
        """t の型の値の「name」フィールドの型"""
        r = prune(t)
        candidates = [(c, f) for (c, f) in self.field_types if f == name]
        if isinstance(r, TCon):
            mine = [(c, f) for (c, f) in candidates if self.ctx.ctors[c][0] == r.name]
            if not mine:
                raise self.err(f"{show(r)[0]}には「{name}」というフィールドがありません", line)
            ft = self.field_types[mine[0]]
            for key in mine[1:]:
                unify(self.field_types[key], ft)
            return ft
        types = {self.ctx.ctors[c][0] for c, _ in candidates}
        if len(types) == 1:
            self.expect(t, TCon(types.pop()), line, f"「の {name}」の前")
            return self.field_of(t, name, line)
        return TVar()

    def infer_Construct(self, node: Construct, env: TEnv) -> Any:
        fields = self.ctx.ctors[node.ctor][1]
        items = [self.infer(i, env) for i in node.items]
        if len(items) == 1 and len(fields) >= 2:
            # 「（3 と 4） の 点」: リストを1つ渡す
            elem = TVar()
            self.expect(items[0], lst(elem), node.line, f"「{node.ctor}」に渡す値")
            items = [elem] * len(fields)
        if len(items) != len(fields):
            raise self.err(f"「{node.ctor}」には{len(fields)}個の値が必要です(渡されたのは{len(items)}個)", node.line)
        for f, t in zip(fields, items):
            self.unify_or(
                t, self.field_types[(node.ctor, f)], node.line,
                lambda sa, sb, f=f: f"「{node.ctor}」の「{f}」は{sb}ですが、{sa}が渡されています",
            )
        return self.ctor_type(node.ctor)

    def infer_NamedConstruct(self, node: NamedConstruct, env: TEnv) -> Any:
        for f, e in node.fields:
            key = (node.ctor, f)
            if key not in self.field_types:
                raise self.err(f"「{node.ctor}」には「{f}」というフィールドがありません", node.line)
            self.unify_or(
                self.infer(e, env), self.field_types[key], node.line,
                lambda sa, sb, f=f: f"「{node.ctor}」の「{f}」は{sb}ですが、{sa}が渡されています",
            )
        return self.ctor_type(node.ctor)

    def infer_Update(self, node: Update, env: TEnv) -> Any:
        t = self.infer(node.target, env)
        for f, e in node.fields:
            ft = self.field_of(t, f, node.line)
            self.unify_or(
                self.infer(e, env), ft, node.line,
                lambda sa, sb, f=f: f"「{f}」は{sb}ですが、{sa}が渡されています",
            )
        return t

    def infer_Field(self, node: Field, env: TEnv) -> Any:
        t = self.infer(node.target, env)
        return self.field_of(t, node.name, node.line)

    # --- 場合分け ---------------------------------------------------------

    def infer_Match(self, node: Match, env: TEnv) -> Any:
        if isinstance(node.subject, ListLit):
            parts = [self.infer(i, env) for i in node.subject.items]
            subject: Any = None
        else:
            parts = None
            subject = self.infer(node.subject, env)
        result = TVar()
        for pat, guard, body in node.cases:
            local = TEnv(env)
            if parts is not None and isinstance(pat, PSeq) and len(pat.items) == len(parts):
                for p, t in zip(pat.items, parts):
                    self.bind_pattern(p, t, local, node.line)
            else:
                if subject is None:
                    subject = self.infer(node.subject, env)
                self.bind_pattern(pat, subject, local, node.line)
            if guard is not None:
                self.expect(self.infer(guard, local), BOOL, node.line, "「かつ」の条件")
            self.unify_or(
                self.infer(body, local), result, _line(body, node.line),
                lambda sa, sb: f"場合ごとの値の型がそろっていません({sb} と {sa})",
            )
        if node.default is not None:
            self.unify_or(
                self.infer(node.default, env), result, node.line,
                lambda sa, sb: f"「そうでなければ」の値の型がほかの場合と違います({sb} と {sa})",
            )
        return result

    def bind_pattern(self, pat: Any, t: Any, env: TEnv, line: Any) -> None:
        def mismatch(sa: str, sb: str) -> str:
            return f"パターンの型が合いません({sa} の値を {sb} のパターンで調べています)"

        if isinstance(pat, PBind):
            env.vars[pat.name] = t
        elif isinstance(pat, PValue):
            self.unify_or(t, self.infer(pat.expr, env), line, mismatch)
        elif isinstance(pat, PCtor):
            self.unify_or(t, self.ctor_type(pat.ctor), pat.line, mismatch)
            for f, p in zip(self.ctx.ctors[pat.ctor][1], pat.items):
                self.bind_pattern(p, self.field_types[(pat.ctor, f)], env, pat.line)
        elif isinstance(pat, PNamed):
            if pat.ctor is not None:
                self.unify_or(t, self.ctor_type(pat.ctor), pat.line, mismatch)
                for f, p in pat.fields:
                    self.bind_pattern(p, self.field_types[(pat.ctor, f)], env, pat.line)
            elif all(f in ("先頭", "残り") for f, _ in pat.fields) and not prune_is_record(t):
                elem = TVar()
                self.unify_or(t, lst(elem), pat.line, mismatch)
                for f, p in pat.fields:
                    self.bind_pattern(p, elem if f == "先頭" else lst(elem), env, pat.line)
            else:
                for f, p in pat.fields:
                    self.bind_pattern(p, self.field_of(t, f, pat.line), env, pat.line)
        elif isinstance(pat, PSeq):
            elem = TVar()
            self.unify_or(t, lst(elem), line, mismatch)
            for p in pat.items:
                self.bind_pattern(p, elem, env, line)

    # --- 動作(第3段階まではおおまかに) ----------------------------------

    def infer_Run(self, node: Run, env: TEnv) -> Any:
        self.infer(node.call, env)
        return TVar()

    def infer_Chain(self, node: Chain, env: TEnv) -> Any:
        self.infer(node.call, env)
        local = TEnv(env)
        local.vars[HOLE] = TVar()
        self.infer(node.cont, local)
        return TVar()

    def infer_Do(self, node: Do, env: TEnv) -> Any:
        local = TEnv(env)
        for s in node.statements:
            if isinstance(s, Define):
                local = self.infer_defs([s], local)
            else:
                self.infer(s, local)
        return TVar()

    def infer_Sequel(self, node: Sequel, env: TEnv) -> Any:
        self.infer(node.expr, env)
        return TVar()


def impl_key(trait: str, type_name: str, method: str) -> str:
    """性質の実装(型名が空なら既定の実装)の定義に付ける内部の名前"""
    return f"\0{trait}\0{type_name}\0{method}"


def display_name(name: str) -> str:
    return name.split("\0")[-1]


def prune_is_record(t: Any) -> bool:
    r = prune(t)
    return isinstance(r, TCon) and r.name not in ("数", "文字列", "真偽", "リスト", "動作")


# ---------------------------------------------------------------------------
# 組み込み関数の型
# ---------------------------------------------------------------------------


def _need(c: Checker, args: dict, p: str, t: Any, line: Any, name: str) -> None:
    if p in args:
        c.arg(args[p], t, line, name, p)


def _check_parts(name: str, args: dict, allowed: dict, line: Any, c: Checker) -> None:
    for p in args:
        if p not in allowed:
            raise c.err(f"「{name}」は「{p}」の引数を受け取りません", line)
    for p, required in allowed.items():
        if required and p not in args:
            raise c.err(f"「{name}」には「{p}」の引数が必要です", line)


def builtin(name: str, parts: dict):
    def deco(fn):
        def typer(c: Checker, args: dict, line: Any) -> Any:
            _check_parts(name, args, parts, line, c)
            return fn(c, args, line)

        BUILTIN_CALLS[name] = typer
        return fn

    return deco


BUILTIN_CALLS: dict = {}


@builtin("表示する", {WO: True})
def _t_show(c, a, line):
    return act(TVar())


@builtin("入力する", {WO: False})
def _t_input(c, a, line):
    return act(STR)


@builtin("実行する", {WO: True})
def _t_run(c, a, line):
    _need(c, a, WO, lst(act(TVar())), line, "実行する")
    return act(TVar())


@builtin("数値にする", {WO: True})
def _t_number(c, a, line):
    c.need_kind(a[WO], ("文字列", "数"), line, "「数値にする」の「を」は文字列")
    return NUM


@builtin("絶対値にする", {WO: True})
def _t_abs(c, a, line):
    _need(c, a, WO, NUM, line, "絶対値にする")
    return NUM


def _t_sum(name):
    def typer(c, a, line):
        if "に" in a:
            _need(c, a, WO, NUM, line, name)
            _need(c, a, "に", NUM, line, name)
            return NUM
        if not (isinstance(prune(a[WO]), TCon) and prune(a[WO]).name == "数"):
            _need(c, a, WO, lst(NUM), line, name)
        return NUM

    return typer


builtin("加算する", {WO: True, "に": False})(_t_sum("加算する"))
builtin("乗算する", {WO: True, "に": False})(_t_sum("乗算する"))


@builtin("減算する", {"から": True, WO: True})
def _t_sub(c, a, line):
    _need(c, a, "から", NUM, line, "減算する")
    _need(c, a, WO, NUM, line, "減算する")
    return NUM


@builtin("除算する", {WO: True, "で": True})
def _t_div(c, a, line):
    _need(c, a, WO, NUM, line, "除算する")
    _need(c, a, "で", NUM, line, "除算する")
    return NUM


def _t_cons(name):
    def typer(c, a, line):
        _need(c, a, "に", lst(a[WO]), line, name)
        return a["に"]

    return typer


builtin("追加する", {WO: True, "に": True})(_t_cons("追加する"))
builtin("挿入する", {WO: True, "に": True})(_t_cons("挿入する"))


@builtin("適用する", {WO: True, "に": False})
def _t_apply(c, a, line):
    return c.apply(a[WO], [a["に"]] if "に" in a else [], line, "「適用する」の「を」")


@builtin("選別する", {"から": True, "で": True})
def _t_filter(c, a, line):
    elem = TVar()
    _need(c, a, "から", lst(elem), line, "選別する")
    r = c.apply(a["で"], [elem], line, "「選別する」の「で」")
    c.expect(r, BOOL, line, "「選別する」の「で」の関数の値")
    return a["から"]


@builtin("畳み込みする", {WO: True, "から": True, "で": True})
def _t_fold(c, a, line):
    elem = TVar()
    acc = a["から"]
    _need(c, a, WO, lst(elem), line, "畳み込みする")
    f = prune(a["で"])
    if isinstance(f, TFun) and len(f.params) == 1:
        # 引数が1つの関数には（累積値 と 要素）のリストを渡す
        c.unify_or(acc, elem, line, lambda sa, sb: f"「畳み込みする」の初期値({sa})と要素({sb})の型が違います")
        r = c.apply(f, [lst(acc)], line, "「畳み込みする」の「で」")
    else:
        r = c.apply(f, [acc, elem], line, "「畳み込みする」の「で」")
    c.unify_or(r, acc, line, lambda sa, sb: f"「畳み込みする」の関数の値({sa})が初期値の型({sb})と違います")
    return acc


@builtin(MAP, {WO: True, "で": True})
def _t_map(c, a, line):
    m = prune(a[WO])
    if isinstance(m, TCon) and m.name == "動作":
        r = c.apply(a["で"], [m.args[0]], line, "「写像する」の「で」")
        return act(r)
    if isinstance(m, TCon) and m.name not in ("リスト",):
        c.apply(a["で"], [TVar()], line, "「写像する」の「で」")
        return TVar()  # 自分の型の写像可能(第2段階)
    elem = TVar()
    _need(c, a, WO, lst(elem), line, MAP)
    return lst(c.apply(a["で"], [elem], line, "「写像する」の「で」"))


@builtin(TO_STRING, {WO: True})
def _t_to_string(c, a, line):
    return STR


@builtin(BIND, {WO: True, "で": True})
def _t_bind(c, a, line):
    return TVar()  # 第3段階


@builtin(UNIT, {WO: True})
def _t_unit(c, a, line):
    return TVar()  # 第3段階


# 関数の値(「加算すること」)として使うときの型
BUILTIN_FUNS = {
    "表示する": lambda: TFun([(WO, TVar())], act(TVar())),
    "入力する": lambda: TFun([], act(STR)),
    "数値にする": lambda: TFun([(WO, STR)], NUM),
    "絶対値にする": lambda: TFun([(WO, NUM)], NUM),
    "加算する": lambda: TFun([(WO, NUM), ("に", NUM)], NUM),
    "乗算する": lambda: TFun([(WO, NUM), ("に", NUM)], NUM),
    "減算する": lambda: TFun([("から", NUM), (WO, NUM)], NUM),
    "除算する": lambda: TFun([(WO, NUM), ("で", NUM)], NUM),
    TO_STRING: lambda: TFun([(WO, TVar())], STR),
}


def _cons_fun():
    a = TVar()
    return TFun([(WO, a), ("に", lst(a))], lst(a))


BUILTIN_FUNS["追加する"] = _cons_fun
BUILTIN_FUNS["挿入する"] = _cons_fun


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def check(source: str) -> None:
    """型を調べる。間違いがあれば SuruError を出す"""
    ctx = ParseContext()
    program = parse_program(source, ctx)
    Checker(ctx).check_program(program)

"""「する」の静的な型検査

型を書かなくても、実行する前に型の間違いを見つける。Hindley–Milner の型推論を、
助詞つきの引数に合わせて広げたもの。

    python3 suru.py --検査 ファイル

調べるもの: 数・文字列・真偽・リスト・関数・組・選択肢のある型・場合分け・場合ごとの定義・
述語(第1段階)、性質の関数(第2段階)、動作(手順・してから・した 結果・結果にする・の 結果)と
型の引数をとる型(第3段階)。

自分の型は、フィールドごとに型の引数を持つ(「数 の 『たぶん』」)。自分自身を中に持つ
フィールド(木の「左」)は、推論の途中で型が無限に続くと分かったところで「その型自身」とし、
初めからやり直す。エラーでは、いつも同じ型で使うフィールドの型の引数は省いて表示する。
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
    HOLE, TO_STRING, MAP, TypeSig, TypeVarName, TypeFun, BIND, UNIT, SHOWABLE, MAPPABLE, MONAD, SURU, TOP_LEVEL_ONLY, is_predicate,
    parse_program, collect_runs, _run_key,
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


class PureVar(TVar):
    """「x を 結果にする」の型。どの動作(連鎖可能な型)になるかは、連鎖する相手で決まる。
    c は結果の型。動作やリストとそろえると、その結果の型を c とそろえる"""

    __slots__ = ("c",)

    def __init__(self, c: Any) -> None:
        super().__init__()
        self.c = c


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
        if isinstance(t, PureVar):
            ftv(t.c, out)
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


class Occurs(Mismatch):
    """v を t にすると型が無限に続く"""

    def __init__(self, v: TVar, t: Any):
        super().__init__()
        self.v, self.t = v, t


def occurs(v: TVar, t: Any) -> bool:
    return v in ftv(t)


BASIC = ("数", "文字列", "真偽")
MONADS = ("動作", "リスト")  # 組み込みの連鎖可能な型

# 自分の型のフィールドごとの、いつも使う型(型名 → 引数ごとの型か None)。エラーの表示で、
# 引数がすべてこの型(かどうでもよい型変数)なら省く
_usual: dict = {}

# 「結果にする」の値を自分の型とそろえたもの(Checker が、その型の「結果にする」の実装で確かめる)
_pure_deferred: list = []


def _bind(v: TVar, t: Any) -> None:
    if occurs(v, t):
        raise Occurs(v, t)
    v.ref = t


def unify(a: Any, b: Any) -> None:
    a, b = prune(a), prune(b)
    if a is b:
        return
    if isinstance(b, PureVar) and not isinstance(a, PureVar):
        a, b = b, a
    if isinstance(a, PureVar):
        if isinstance(b, PureVar):
            unify(a.c, b.c)
        elif isinstance(b, TVar):
            _bind(b, a)
            return
        elif isinstance(b, TCon) and b.name in MONADS:
            unify(a.c, b.args[0])
        elif isinstance(b, TCon) and b.name not in BASIC:
            _pure_deferred.append((a.c, b))
        else:
            raise Mismatch()
        _bind(a, b)
        return
    if isinstance(a, TVar):
        _bind(a, b)
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
    def __init__(self, *ts: Any) -> None:
        self.names: dict[TVar, str] = {}
        # 一度しか出てこない型変数(どんな型でもよいところ)。自分の型の引数がこれだけなら省く
        counts: dict = {}
        for t in ts:
            _count_vars(t, counts)
        self.lonely = {v for v, n in counts.items() if n == 1}

    def ordinary(self, t: TCon) -> bool:
        usual = _usual.get(t.name) or [None] * len(t.args)
        if len(usual) != len(t.args):
            return False
        return all(prune(a) in self.lonely or (u is not None and _teq(a, u)) for a, u in zip(t.args, usual))

    def __call__(self, t: Any, nested: bool = False) -> str:
        t = prune(t)
        if isinstance(t, PureVar):
            s = f"{self(t.c, True)} を 結果にしたもの"
            return f"（{s}）" if nested else s
        if isinstance(t, TVar):
            if t not in self.names:
                k = len(self.names)
                self.names[t] = VAR_NAMES[k] if k < len(VAR_NAMES) else f"型{k + 1}"
            return self.names[t]
        if isinstance(t, TCon):
            if not t.args or (t.name not in MONADS and self.ordinary(t)):
                return t.name
            inner = " と ".join(self(a, True) for a in t.args)
            s = f"{inner} の {t.name}" if len(t.args) == 1 else f"（{inner}） の {t.name}"
            return f"（{s}）" if nested else s
        if isinstance(t, TFun):
            if not t.params:
                return f"（{self(t.result, True)} を 返すこと）"
            ps = " ".join(f"{self(x, True)} {p}" for p, x in t.params)
            return f"（{ps} 受け取って {self(t.result, True)} を 返すこと）"
        return "?"


def _count_vars(t: Any, counts: dict) -> None:
    t = prune(t)
    if isinstance(t, TVar):
        counts[t] = counts.get(t, 0) + 1
        if isinstance(t, PureVar):
            _count_vars(t.c, counts)
    elif isinstance(t, TCon):
        for a in t.args:
            _count_vars(a, counts)
    elif isinstance(t, TFun):
        for _, a in t.params:
            _count_vars(a, counts)
        _count_vars(t.result, counts)


def show(*ts: Any) -> list[str]:
    n = Namer(*ts)
    return [n(t) for t in ts]


# --- 型スキーム(多相) ---


class Constraint:
    """型の条件。t が決まったときに確かめる。
    kinds があれば「t はこれらの型のどれか」、trait があれば「t は性質を持ち、method の型は実装の型と同じ」。
    op は動作の条件: "bind"(t を連鎖する。extra は 結果・続きの値・全体)、"map"(t を写像する。
    extra は 結果・関数の値・全体)、"wrap"(手順の最後の値 t。extra は 手順の値)、
    "flatten"(動作の続きの値 t。extra は 動作の結果)"""

    __slots__ = ("t", "kinds", "message", "trait", "method", "ftype", "line", "op", "extra")

    def __init__(self, t: Any, line: Any, kinds: tuple = (), message: str = "",
                 trait: str = "", method: str = "", ftype: Any = None, op: str = "", extra: tuple = ()):
        self.t, self.line, self.kinds, self.message = t, line, kinds, message
        self.trait, self.method, self.ftype = trait, method, ftype
        self.op, self.extra = op, tuple(extra)

    def subst(self, m: dict) -> "Constraint":
        return Constraint(
            _subst(self.t, m), self.line, self.kinds, self.message, self.trait, self.method,
            _subst(self.ftype, m) if self.ftype is not None else None,
            self.op, tuple(_subst(x, m) for x in self.extra),
        )

    def type_vars(self) -> set:
        out = ftv(self.t)
        if self.ftype is not None:
            ftv(self.ftype, out)
        for x in self.extra:
            ftv(x, out)
        return out


class Scheme:
    """多相な型: 「すべての vars について t」。constraints は使うたびに写して確かめる条件"""

    def __init__(self, vars_: list, t: Any, constraints: list | None = None):
        self.vars = vars_
        self.t = t
        self.constraints = constraints or []

    def instantiate(self, pending: list | None = None) -> Any:
        mapping: dict = {v: PureVar(None) if isinstance(v, PureVar) else TVar() for v in self.vars}
        for v in self.vars:
            if isinstance(v, PureVar):
                mapping[v].c = _subst(v.c, mapping)
        if pending is not None:
            pending.extend(c.subst(mapping) for c in self.constraints)
        return _subst(self.t, mapping)


def _subst(t: Any, m: dict) -> Any:
    t = prune(t)
    if isinstance(t, TVar):
        if t in m:
            return m[t]
        if isinstance(t, PureVar) and ftv(t.c) & m.keys():
            return PureVar(_subst(t.c, m))
        return t
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
    if isinstance(node, (Do, Chain, Run)):
        out.update((BIND, UNIT))  # 自分の型の「連鎖する」の実装を使う
    if isinstance(node, Field) and node.name == RESULT:
        out.update((MAP, BIND, UNIT))
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


# ---------------------------------------------------------------------------
# 自分の型の形(型の引数)
# ---------------------------------------------------------------------------

SELF = TCon("\0自身")  # 再帰するフィールドの型の中で「その型自身」を表す印


class Restart(Exception):
    """自分自身を中に持つフィールドが見つかったので、初めから推論し直す"""


class Shapes:
    """自分の型のフィールドの型の決め方。推論をやり直しても引き継ぐ。
    フィールドは (型名, フィールド名) で表し、同じ型の形どうしで同じ名前のフィールドは同じ型にする。
    ふつうのフィールドは型の引数になる。recursive は自分自身を中に持つフィールドの型(SELF と
    ほかのフィールドの ph を含む)"""

    def __init__(self, ctx: ParseContext):
        self.keys: dict[str, list] = {}
        for _, (tname, fs) in ctx.ctors.items():
            ks = self.keys.setdefault(tname, [])
            for f in fs:
                if (tname, f) not in ks:
                    ks.append((tname, f))
        self.ph = {k: TVar() for ks in self.keys.values() for k in ks}
        self.recursive: dict = {}

    def params(self, tname: str) -> list:
        return [k for k in self.keys.get(tname, []) if k not in self.recursive]

    def is_user(self, t: Any) -> bool:
        return isinstance(t, TCon) and t.name in self.keys and len(t.args) == len(self.params(t.name))

    def find_recursion(self, v: TVar, t: Any) -> bool:
        """v を t にそろえると型が無限に続くとき、t の中の自分の型で、引数に v を含むものがあれば、
        そのフィールドを「自分自身を中に持つ」ことにする"""
        for n in _nodes(t):
            if not self.is_user(n):
                continue
            ps = self.params(n.name)
            for i, a in enumerate(n.args):
                if v not in ftv(a):
                    continue
                mapping: dict = {}
                for j, b in enumerate(n.args):
                    rb = prune(b)
                    if j != i and isinstance(rb, TVar) and rb is not v:
                        mapping[rb] = self.ph[ps[j]]
                self.recursive[ps[i]] = _template(a, n, v, t, mapping)
                return True
        return False

    def learn_usual(self, instances: list) -> bool:
        """どの使い方でも同じ型(型変数を含まない)のフィールドを覚える(エラーの表示を短くするため)"""
        found = False
        for tname in self.keys:
            ps = self.params(tname)
            mine = [x for x in instances if x.name == tname and len(x.args) == len(ps)]
            usual = []
            for j in range(len(ps)):
                ts = [prune(x.args[j]) for x in mine]
                ok = bool(ts) and not any(ftv(x) for x in ts) and all(_teq(ts[0], x) for x in ts[1:])
                usual.append(_subst(ts[0], {}) if ok else None)
                found = found or ok
            _usual[tname] = usual
        return found


def _nodes(t: Any, out: list | None = None) -> list:
    out = [] if out is None else out
    t = prune(t)
    if isinstance(t, TCon):
        out.append(t)
        for a in t.args:
            _nodes(a, out)
    elif isinstance(t, TFun):
        for _, a in t.params:
            _nodes(a, out)
        _nodes(t.result, out)
    return out


def _template(a: Any, node: TCon, v: TVar, t: Any, mapping: dict) -> Any:
    """再帰するフィールドの型 a を、推論の型変数を含まない形にする(node は SELF、v は t)"""
    fresh: dict = {}
    seen = [False]

    def build(x: Any) -> Any:
        x = prune(x)
        if x is node:
            return SELF
        if x is v:
            if seen[0]:
                return TVar()
            seen[0] = True
            return build(t)
        if isinstance(x, TVar):
            if x in mapping:
                return mapping[x]
            return fresh.setdefault(x, TVar())
        if isinstance(x, TCon):
            return TCon(x.name, tuple(build(y) for y in x.args)) if x.args else x
        if isinstance(x, TFun):
            return TFun([(p, build(y)) for p, y in x.params], build(x.result))
        return x

    return build(a)


def _teq(a: Any, b: Any) -> bool:
    a, b = prune(a), prune(b)
    if isinstance(a, TCon) and isinstance(b, TCon):
        return a.name == b.name and len(a.args) == len(b.args) and all(map(_teq, a.args, b.args))
    if isinstance(a, TFun) and isinstance(b, TFun):
        return (len(a.params) == len(b.params) and all(_teq(x, y) for (_, x), (_, y) in zip(a.params, b.params))
                and _teq(a.result, b.result))
    return a is b


def _fill(t: Any, mapping: dict, self_t: Any) -> Any:
    if t is SELF:
        return self_t
    if isinstance(t, TVar):
        return mapping.get(t, t)
    if isinstance(t, TCon):
        return TCon(t.name, tuple(_fill(a, mapping, self_t) for a in t.args)) if t.args else t
    if isinstance(t, TFun):
        return TFun([(p, _fill(a, mapping, self_t)) for p, a in t.params], _fill(t.result, mapping, self_t))
    return t


class Checker:
    def __init__(self, ctx: ParseContext, shapes: Shapes | None = None):
        self.ctx = ctx
        self.shapes = shapes or Shapes(ctx)
        self.instances: list[TCon] = []  # 作った自分の型(いつも同じ型のフィールドを見つけるため)
        _pure_deferred.clear()
        self.traits: dict[str, dict] = {}  # 性質 → {"methods": {関数名: 引数}, "defaults": {関数名}}
        self.method_trait: dict[str, str] = {}  # 性質の関数 → 性質
        self.impls: dict[tuple[str, str], set] = {}  # (性質, 型名) → 実装した関数
        self.show_impls: set[str] = set()  # 「表示可能」の実装の定義の名前(文字列を返す)
        self.aliases: dict[str, list] = {}
        self.pending: list[Constraint] = []  # まだ確かめていない条件
        self.line: Any = None  # 今見ている式の行(位置の分からない式のエラー用)
        self.env: TEnv = TEnv()  # 組み込み関数の型を調べるときの環境

    # --- エラー ---------------------------------------------------------

    def err(self, message: str, line: Any) -> SuruError:
        return SuruError(message, line or self.line)

    def unify(self, a: Any, b: Any) -> None:
        """a と b をそろえる。自分の型が無限に続くなら、そのフィールドを再帰するものにしてやり直す"""
        try:
            unify(a, b)
        except Occurs as e:
            if self.shapes.find_recursion(e.v, e.t):
                raise Restart() from None
            raise Mismatch() from None

    def unify_or(self, a: Any, b: Any, line: Any, message: "Any") -> None:
        """a と b をそろえる。そろわなければ message(a, b の表示) のエラー"""
        try:
            self.unify(a, b)
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
        sigs = self.collect_sigs(program, defs)
        env = self.infer_defs(defs, TEnv(), sigs)
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

    def infer_defs(self, defs: list, env: TEnv, sigs: dict | None = None) -> TEnv:
        """定義の並びを推論し、それぞれの名前に多相な型を付けた新しい環境を返す。
        sigs は一番外の型の宣言(名前 → TypeSig)"""
        sigs = sigs or {}
        scope = TEnv(env)
        for comp in sccs(defs, self.aliases):
            mono = {d.name: TVar() for d in comp}
            inner = TEnv(scope)
            inner.vars.update(mono)
            # 宣言した型を先に付ける
            declared = {d.name: self.declared_type(sigs[d.name], d) for d in comp if d.name in sigs}
            for name, (t, _) in declared.items():
                if sigs[name].params is None:
                    self.unify(mono[name], t)
            # 関数は先に引数の型を決めておく(互いに呼び合う中でも引数を調べられるように)
            heads = {d.name: self.function_head(d, inner, mono[d.name]) for d in comp if d.is_function}
            for name, (t, _) in declared.items():
                if name in heads:
                    self.apply_sig(sigs[name], t, heads[name][1])
            for d in comp:
                self.line = d.line
                t = self.infer_define(d, inner, heads.get(d.name), sigs.get(d.name))
                self.unify_or(
                    mono[d.name], t, d.line,
                    (lambda sa, sb, d=d: f"「{display_name(d.name)}」は{sa}と宣言されていますが、{sb}になっています")
                    if d.name in declared and not d.is_function else
                    (lambda sa, sb, d=d: f"「{display_name(d.name)}」の型が合いません({sa} と {sb})"),
                )
            self.solve(inner)
            for name, (_, tvars) in declared.items():
                self.check_rigid(sigs[name], tvars)
            outer_free = scope.free_vars()
            taken: set = set()
            for d in comp:
                t = mono[d.name]
                quantified = ftv(t) - outer_free
                # 条件の中だけに出てくる型変数(手順の途中の結果など)も、使うたびに写す
                while True:
                    mine = [c for c in self.pending if c.type_vars() & quantified]
                    more = set().union(*(c.type_vars() for c in mine)) - outer_free - quantified
                    if not more:
                        break
                    quantified |= more
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
                r = prune(c.t)
                if isinstance(r, TVar) and not (c.op and isinstance(r, PureVar)):
                    continue
                if c not in self.pending:
                    continue
                self.pending.remove(c)
                if self.discharge(c, env):
                    progress = True
                else:
                    self.pending.append(c)
            for item in list(_pure_deferred):
                if self.coerce_pure(*item, env):
                    _pure_deferred.remove(item)
                    progress = True

    def post(self, c: Constraint, env: TEnv) -> None:
        self.pending.append(c)
        self.solve(env)

    def impl_type(self, trait: str, tname: str, method: str, env: TEnv) -> Any:
        """自分の型の性質の実装の型(まだ推論していなければ None)"""
        v = env.lookup(impl_key(trait, tname, method))
        return None if v is None else prune(self.inst(v))

    def coerce_pure(self, c: Any, t: TCon, env: TEnv) -> bool:
        """「結果にする」の値を自分の型 t にした: t の「結果にする」の実装があれば、その型で確かめる"""
        if UNIT not in self.impls.get((MONAD, t.name), ()):
            return True  # 実装がなければ、何もしない動作のまま連鎖の相手に渡る
        impl = self.impl_type(MONAD, t.name, UNIT, env)
        if impl is None:
            return False
        if isinstance(impl, TFun) and impl.params:
            self.unify_or(c, impl.params[0][1], self.line,
                          lambda sa, sb: f"「{UNIT}」({t.name}の実装)には{sb}が必要ですが、{sa}が渡されています")
            self.unify_or(t, impl.result, self.line, lambda sa, sb: f"「{UNIT}」の値の型が合いません({sa} と {sb})")
        return True

    def discharge(self, c: Constraint, env: TEnv) -> bool:
        if c.op:
            try:
                return getattr(self, "on_" + c.op)(prune(c.t), c, env)
            except Mismatch:
                raise self.err(f"動作の結果の型が合いません({show(c.t)[0]})", c.line) from None
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

    # --- 型の宣言 ---------------------------------------------------------

    def collect_sigs(self, program: list, defs: list) -> dict:
        names = {d.name: d for d in defs}
        sigs: dict = {}
        for s in program:
            if not isinstance(s, TypeSig):
                continue
            if s.name in sigs:
                raise self.err(f"「{s.name}」の型が2回宣言されています", s.line)
            if s.name in self.method_trait:
                raise self.err(f"「{s.name}」は性質の関数なので、型は性質の宣言で決まります", s.line)
            d = names.get(s.name)
            if d is None:
                raise self.err(f"「{s.name}」の型を宣言していますが、一番外にその定義がありません", s.line)
            if (s.params is not None) != d.is_function:
                what = "関数" if d.is_function else "値"
                raise self.err(f"「{s.name}」は{what}なので、型の宣言の書き方が違います", s.line)
            if s.params is not None:
                want = sorted(p for p, _ in d.params)
                got = sorted(p for p, _ in s.params)
                if want != got:
                    raise self.err(
                        f"「{s.name}」の型の宣言の助詞({'・'.join(got) or 'なし'})が定義の助詞({'・'.join(want) or 'なし'})と違います",
                        s.line)
            sigs[s.name] = s
        return sigs

    def declared_type(self, sig: TypeSig, d: Define) -> tuple:
        """宣言の型と、その中の型変数(甲・乙 … → TVar)"""
        tvars: dict = {}
        result = self.type_of(sig.result, tvars, sig.line)
        if sig.params is None:
            return result, tvars
        return TFun([(p, self.type_of(t, tvars, sig.line)) for p, t in sig.params], result), tvars

    def type_of(self, te: Any, tvars: dict, line: Any) -> Any:
        """型の書き方(TypeName など)から型を作る"""
        if isinstance(te, TypeVarName):
            return tvars.setdefault(te.name, TVar())
        if isinstance(te, TypeFun):
            return TFun([(p, self.type_of(t, tvars, line)) for p, t in te.params], self.type_of(te.result, tvars, line))
        args = [self.type_of(a, tvars, line) for a in te.args]
        if te.name in BASIC:
            return TCon(te.name)
        if te.name in MONADS:
            return TCon(te.name, (args[0],))
        if te.name not in self.shapes.keys:
            return TVar()  # 「関数」: どんな関数でもよい
        inst = self.fresh_type(te.name)
        keys = [k for k in self.shapes.keys[te.name] if k not in self.shapes.recursive]
        if len(args) > len(keys):
            raise self.err(f"「{te.name}」がとる型の引数は{len(keys)}個です(フィールド: {'・'.join(f for _, f in keys)})", line)
        for k, a in zip(keys, args):
            self.unify_or(self.field_type(inst, k), a, line,
                          lambda sa, sb, k=k: f"「{te.name}」の「{k[1]}」は{sa}なので、{sb}にはできません")
        return inst

    def apply_sig(self, sig: TypeSig, declared: TFun, head: TFun) -> None:
        """関数の宣言の型を、定義の引数(助詞ごと)と値に付ける"""
        params = dict(head.params)
        for p, t in declared.params:
            self.unify_or(params[p], t, sig.line,
                          lambda sa, sb, p=p: f"「{sig.name}」の「{p}」は{sb}と宣言されていますが、定義では{sa}です")
        self.unify_or(head.result, declared.result, sig.line,
                      lambda sa, sb: f"「{sig.name}」の値は{sb}と宣言されていますが、定義では{sa}です")

    def check_rigid(self, sig: TypeSig, tvars: dict) -> None:
        """甲・乙 … と宣言したところが、どんな型でもよいままか(決まった型や、互いに同じ型になっていないか)"""
        seen: dict = {}
        for name, v in tvars.items():
            r = prune(v)
            if not isinstance(r, TVar) or isinstance(r, PureVar):
                raise self.err(f"「{sig.name}」の型の宣言の「{name}」は、定義では{show(r)[0]}に決まります"
                               "(どんな型でもよいときだけ甲・乙 … を使います)", sig.line)
            if r in seen:
                raise self.err(f"「{sig.name}」の型の宣言の「{seen[r]}」と「{name}」は、定義では同じ型になります", sig.line)
            seen[r] = name

    def function_head(self, d: Define, env: TEnv, mono: Any = None) -> tuple:
        local = TEnv(env)
        params = [(p, self.bind_param(pat, local)) for p, pat in d.params]
        t = TFun(params, TVar())
        if mono is not None:
            self.unify(mono, t)
        return local, t

    def infer_define(self, d: Define, env: TEnv, head: tuple | None = None, sig: Any = None) -> Any:
        if not d.is_function:
            return self.infer(d.body, env)
        local, t = head or self.function_head(d, env)
        params = t.params
        result = self.infer(d.body, local)
        if sig is not None:
            self.unify_or(t.result, result, d.line,
                          lambda sa, sb: f"「{display_name(d.name)}」の値は{sa}と宣言されていますが、{sb}になっています")
        self.unify_or(t.result, result, d.line,
                      lambda sa, sb: f"「{display_name(d.name)}」の値の型が合いません({sa} と {sb})")
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
            return TVar()  # 調べない式
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
            return self.ctor_type(node.name)  # 中身のない形(「赤」)
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
        for x in (a, b):
            if _is_action(x):
                raise self.err(
                    f"「{op}」の{'左' if x is a else '右'}が動作({show(x)[0]})です。動作の結果で計算するときは"
                    "「…してから」か「… の 結果 を …」を使ってください", node.line)
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
        lifted: list = []  # 「の 結果」の引数: (値の型, 結果の型, 行)
        for p, a in node.args.items():
            if isinstance(a, Each):
                t = self.infer(a.target, env)
                elem = TVar()
                self.expect(t, lst(elem), a.line, "「の それぞれ」の前")
                args[p] = elem
                each = True
            elif isinstance(a, Field) and a.name == RESULT and not self._has_field(RESULT):
                # 「入力 の 結果 を …」: 動作(や連鎖可能な型)の結果に関数を適用する
                m = self.infer(a.target, env)
                elem = TVar()
                self.monad_elem(m, elem, env)
                args[p] = elem
                lifted.append((m, elem, a.line or node.line))
            else:
                args[p] = self.infer(a, env)
        result = self.call_type(node.name, args, node.line, env)
        if each:
            result = lst(result)
        # 最後の「の 結果」は写像、その前のものは前から順に連鎖する
        for idx in reversed(range(len(lifted))):
            m, elem, ln = lifted[idx]
            if idx == len(lifted) - 1:
                out = TVar()
                self.post(Constraint(m, ln, message=f"{{t}}は性質「{MAPPABLE}」を持っていません(「の 結果」が使えません)",
                                     op="map", extra=(elem, result, out)), env)
                result = out
            else:
                result = self.bind(m, elem, result, ln, f"{{t}}は性質「{MONAD}」を持っていません(「の 結果」が使えません)", env)
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
            self.env = env
            return typer(self, args, line)
        return TVar()  # 実行時にエラーになる名前

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
            self.unify(t, TFun([(WO, v) for v in values], r))
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

    def fresh_type(self, tname: str) -> TCon:
        t = TCon(tname, tuple(TVar() for _ in self.shapes.params(tname)))
        self.instances.append(t)
        return t

    def ctor_type(self, ctor: str) -> TCon:
        return self.fresh_type(self.ctx.ctors[ctor][0])

    def field_type(self, t: Any, key: tuple, seen: frozenset = frozenset()) -> Any:
        """自分の型 t(TCon)の値のフィールド key の型"""
        sh = self.shapes
        ps = sh.params(key[0])
        if key in ps:
            return t.args[ps.index(key)]
        tmpl = sh.recursive[key]
        mapping: dict = {}
        for v in ftv(tmpl):
            other = next((k for k, ph in sh.ph.items() if ph is v), None)
            if other is not None and other[0] == key[0] and other not in seen:
                mapping[v] = self.field_type(t, other, seen | {key})
            else:
                mapping[v] = TVar()
        return _fill(tmpl, mapping, t)

    def ctor_field(self, t: Any, ctor: str, f: str) -> Any:
        return self.field_type(prune(t), (self.ctx.ctors[ctor][0], f))

    def _has_field(self, name: str) -> bool:
        return any(name in fs for _, fs in self.ctx.ctors.values())

    def field_of(self, t: Any, name: str, line: Any) -> Any:
        """t の型の値の「name」フィールドの型"""
        r = prune(t)
        types = {tn for tn, fs in self.ctx.ctors.values() if name in fs}
        if isinstance(r, TCon):
            if r.name not in types or not self.shapes.is_user(r):
                if name == RESULT and (r.name in MONADS or (MONAD, r.name) in self.impls):
                    raise self.err("「の 結果」は「入力 の 結果 を 数値にする」のように呼び出しの引数に書いてください", line)
                raise self.err(f"{show(r)[0]}には「{name}」というフィールドがありません", line)
            return self.field_type(r, (r.name, name))
        if isinstance(r, PureVar) and name == RESULT:
            raise self.err("「の 結果」は「入力 の 結果 を 数値にする」のように呼び出しの引数に書いてください", line)
        if len(types) == 1:
            self.expect(t, self.fresh_type(types.pop()), line, f"「の {name}」の前")
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
        result = self.ctor_type(node.ctor)
        for f, t in zip(fields, items):
            self.unify_or(
                t, self.ctor_field(result, node.ctor, f), node.line,
                lambda sa, sb, f=f: f"「{node.ctor}」の「{f}」は{sb}ですが、{sa}が渡されています",
            )
        return result

    def infer_NamedConstruct(self, node: NamedConstruct, env: TEnv) -> Any:
        result = self.ctor_type(node.ctor)
        for f, e in node.fields:
            if f not in self.ctx.ctors[node.ctor][1]:
                raise self.err(f"「{node.ctor}」には「{f}」というフィールドがありません", node.line)
            self.unify_or(
                self.infer(e, env), self.ctor_field(result, node.ctor, f), node.line,
                lambda sa, sb, f=f: f"「{node.ctor}」の「{f}」は{sb}ですが、{sa}が渡されています",
            )
        return result

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
            ct = self.ctor_type(pat.ctor)
            self.unify_or(t, ct, pat.line, mismatch)
            for f, p in zip(self.ctx.ctors[pat.ctor][1], pat.items):
                self.bind_pattern(p, self.ctor_field(ct, pat.ctor, f), env, pat.line)
        elif isinstance(pat, PNamed):
            if pat.ctor is not None:
                ct = self.ctor_type(pat.ctor)
                self.unify_or(t, ct, pat.line, mismatch)
                for f, p in pat.fields:
                    self.bind_pattern(p, self.ctor_field(ct, pat.ctor, f), env, pat.line)
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

    # --- 動作 -------------------------------------------------------------

    def monad_elem(self, m: Any, elem: Any, env: TEnv | None = None) -> None:
        """m の型が分かっていれば、その結果の型を elem とそろえる(続きを推論する前に)"""
        r = prune(m)
        if isinstance(r, PureVar):
            self.unify(elem, r.c)
        elif isinstance(r, TCon) and r.name in MONADS:
            self.unify(elem, r.args[0])
        elif isinstance(r, TCon) and env is not None:
            # 自分の型: 「連鎖する」(なければ「写像する」)の実装で、関数に渡す値の型を見る
            for trait, method in ((MONAD, BIND), (MAPPABLE, MAP)):
                if method not in self.impls.get((trait, r.name), ()):
                    continue
                impl = self.impl_type(trait, r.name, method, env)
                if isinstance(impl, TFun):
                    params = dict(impl.params)
                    f = prune(params.get("で"))
                    if WO in params and isinstance(f, TFun) and f.params:
                        try:
                            self.unify(params[WO], r)
                            self.unify(f.params[0][1], elem)
                        except Mismatch:
                            pass  # 連鎖するところでエラーにする
                return

    def bind(self, m: Any, elem: Any, k: Any, line: Any, message: str, env: TEnv) -> Any:
        """m を行い、結果(elem)を続き(値 k)に渡したものの型"""
        out = TVar()
        self.post(Constraint(m, line, message=message, op="bind", extra=(elem, k, out)), env)
        return out

    def not_monad(self, m: Any, c: Constraint) -> SuruError:
        return self.err(c.message.format(t=show(m)[0]), c.line)

    def on_bind(self, m: Any, c: Constraint, env: TEnv) -> bool:
        elem, k, out = c.extra
        if isinstance(m, PureVar):  # 何もしない動作: 続きの値がそのまま全体の値
            self.unify(elem, m.c)
            self.unify(out, k)
            return True
        if not isinstance(m, TCon) or m.name in BASIC:
            raise self.not_monad(m, c)
        if m.name == "動作":
            self.unify(elem, m.args[0])
            b = TVar()
            self.unify(out, act(b))
            self.pending.append(Constraint(k, c.line, op="flatten", extra=(b,)))
            return True
        if m.name == "リスト":
            self.unify(elem, m.args[0])
            b = TVar()
            self.unify_or(k, lst(b), c.line,
                          lambda sa, sb: f"リストを連鎖するときは、続きもリストを返す必要があります({sa}が返ります)")
            self.unify(out, lst(b))
            return True
        if (MONAD, m.name) not in self.impls:
            raise self.not_monad(m, c)
        impl = self.impl_type(MONAD, m.name, BIND, env)
        if impl is None:
            return False
        self.use_impl(impl, m, elem, k, out, BIND, c.line)
        return True

    def use_impl(self, impl: Any, m: Any, elem: Any, k: Any, out: Any, method: str, line: Any) -> None:
        """自分の型の「連鎖する」「写像する」の実装の型で、m を f(elem を受け取って k を返す)で使う"""
        if not isinstance(impl, TFun):
            return
        params = dict(impl.params)
        tname = prune(m).name
        if WO in params:
            self.unify_or(m, params[WO], line,
                          lambda sa, sb: f"「{method}」({tname}の実装)の「を」には{sb}が必要ですが、{sa}が渡されています")
        if "で" in params:
            self.unify_or(TFun([(WO, elem)], k), params["で"], line,
                          lambda sa, sb: f"「{method}」({tname}の実装)の「で」には{sb}が必要ですが、{sa}が渡されています")
        self.unify_or(out, impl.result, line, lambda sa, sb: f"「{method}」({tname}の実装)の値の型が合いません({sa} と {sb})")

    def on_flatten(self, k: Any, c: Constraint, env: TEnv) -> bool:
        """動作の続きが返した値: 動作ならそれも行い、その結果が全体の結果になる"""
        (b,) = c.extra
        if isinstance(k, PureVar):
            self.unify(b, k.c)
        elif isinstance(k, TCon) and k.name == "動作":
            self.unify(b, k.args[0])
        else:
            self.unify(b, k)
        return True

    def on_map(self, m: Any, c: Constraint, env: TEnv) -> bool:
        elem, r, out = c.extra
        if isinstance(m, PureVar):
            self.unify(elem, m.c)
            self.unify(out, PureVar(r))
            return True
        if isinstance(m, TCon) and m.name in MONADS:
            self.unify(elem, m.args[0])
            self.unify(out, TCon(m.name, (r,)))
            return True
        if isinstance(m, TCon) and (MAPPABLE, m.name) in self.impls:
            impl = self.impl_type(MAPPABLE, m.name, MAP, env)
            if impl is None:
                return False
            self.use_impl(impl, m, elem, r, out, MAP, c.line)
            return True
        if isinstance(m, TCon) and (MONAD, m.name) in self.impls:
            self.pending.append(Constraint(m, c.line, message=c.message, op="bind", extra=(elem, PureVar(r), out)))
            return True
        raise self.not_monad(m, c)

    def on_wrap(self, v: Any, c: Constraint, env: TEnv) -> bool:
        """手順の最後の値: 動作でなければ、何もしない動作にする"""
        (out,) = c.extra
        if isinstance(v, PureVar) or (isinstance(v, TCon) and (v.name in MONADS or (MONAD, v.name) in self.impls)):
            self.unify(out, v)
        else:
            self.unify(out, PureVar(v))
        return True

    def infer_Run(self, node: Run, env: TEnv) -> Any:
        t = env.lookup(_run_key(node))
        if t is None:
            raise self.err(
                "「した 結果」は手順の文の中で使ってください(関数の本体や条件分岐の枝の中では、そこを「手順（…）」で囲みます)",
                node.line,
            )
        return t

    def infer_Chain(self, node: Chain, env: TEnv) -> Any:
        m = self.infer(node.call, env)
        elem = TVar()
        self.monad_elem(m, elem, env)
        local = TEnv(env)
        local.vars[HOLE] = elem
        k = self.infer(node.cont, local)
        return self.bind(m, elem, k, node.line,
                         "「してから」の前の値({t})は動作ではありません(純粋な値なら「して」を使います)", env)

    def infer_Do(self, node: Do, env: TEnv) -> Any:
        return self.do_type(node.statements, 0, TEnv(env), node.line)

    def do_type(self, stmts: list, i: int, env: TEnv, line: Any) -> Any:
        """手順の i 番目からの型。「した 結果」は連鎖に、途中の文は「それから」になる"""
        s = stmts[i]
        for r in collect_runs(s, []):
            key = _run_key(r)
            if env.lookup(key) is not None:
                continue
            m = self.infer(r.call, env)
            elem = TVar()
            self.monad_elem(m, elem, env)
            local = TEnv(env)
            local.vars[key] = elem
            k = self.do_type(stmts, i, local, line)
            name = getattr(r.call, "name", "")
            name = name[: -len(SURU)] if name.endswith(SURU) else name
            return self.bind(m, elem, k, r.line, f"「{name}した 結果」: {{t}}は動作ではありません", env)
        if isinstance(s, Define):
            local = self.infer_defs([s], env)
            if i + 1 == len(stmts):
                return TVar()
            return self.do_type(stmts, i + 1, local, line)
        v = self.infer(s, env)
        if i + 1 == len(stmts):
            out = TVar()
            self.post(Constraint(v, first_line(s) or line, op="wrap", extra=(out,)), env)
            return out
        k = self.do_type(stmts, i + 1, env, line)
        return self.bind(v, TVar(), k, first_line(s) or line, "手順の途中の文の値({t})は動作ではありません", env)

    def infer_Sequel(self, node: Sequel, env: TEnv) -> Any:
        return self.infer(node.expr, env)


def impl_key(trait: str, type_name: str, method: str) -> str:
    """性質の実装(型名が空なら既定の実装)の定義に付ける内部の名前"""
    return f"\0{trait}\0{type_name}\0{method}"


def display_name(name: str) -> str:
    return name.split("\0")[-1]


def _is_action(t: Any) -> bool:
    r = prune(t)
    return isinstance(r, PureVar) or (isinstance(r, TCon) and r.name == "動作")


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
    r = TVar()
    _need(c, a, WO, lst(act(r)), line, "実行する")
    return act(lst(r))


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
    elem = TVar()
    c.monad_elem(a[WO], elem, c.env)
    r = c.apply(a["で"], [elem], line, "「写像する」の「で」")
    out = TVar()
    c.post(Constraint(a[WO], line, message=f"「写像する」の「を」の{{t}}は性質「{MAPPABLE}」を持っていません",
                      op="map", extra=(elem, r, out)), c.env)
    return out


@builtin(TO_STRING, {WO: True})
def _t_to_string(c, a, line):
    return STR


@builtin(BIND, {WO: True, "で": True})
def _t_bind(c, a, line):
    elem = TVar()
    c.monad_elem(a[WO], elem, c.env)
    k = c.apply(a["で"], [elem], line, "「連鎖する」の「で」")
    return c.bind(a[WO], elem, k, line, f"「連鎖する」の「を」の{{t}}は性質「{MONAD}」を持っていません", c.env)


@builtin(UNIT, {WO: True})
def _t_unit(c, a, line):
    return PureVar(a[WO])


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
    UNIT: lambda: (lambda x: TFun([(WO, x)], PureVar(x)))(TVar()),
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
    shapes = Shapes(ctx)

    def attempt() -> tuple:
        for _ in range(100):
            checker = Checker(ctx, shapes)
            try:
                checker.check_program(program)
                return None, checker
            except Restart:
                continue
            except SuruError as e:
                return e, checker
        return None, checker

    _usual.clear()
    first, checker = attempt()
    if first is None:
        return
    # いつも同じ型で使うフィールドを覚えて、もう一度調べる(エラーの型の表示が短くなる)
    if shapes.learn_usual(checker.instances):
        second, _ = attempt()
        _usual.clear()
        raise second or first
    raise first

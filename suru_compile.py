# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
#
# 追加の許可(GPL 第7条): このコンパイラが出力する LLVM IR・オブジェクト・実行ファイルは、
# 出力の中にこのコンパイラ由来の部分が含まれていても、GPL の対象にはなりません。
# 出力は、元にした する のプログラムの作者が好きなライセンスで配れます。
"""「する」のコンパイラ: する のプログラムを LLVM IR にして、clang でバイナリにする。

    python3 suru_compile.py prog.suru            # → prog(実行ファイル)
    python3 suru_compile.py prog.suru -o 名前    # 出力の名前
    python3 suru_compile.py --ll prog.suru       # LLVM IR(prog.ll)だけを出す
    python3 suru.py --翻訳 prog.suru             # suru.py からも使える(--compile も可)

値の表し方や動作・性質の仕組みは runtime/suru_rt.c(C の実行時ライブラリ)にあり、
インタプリタ(suru.py)と同じ結果になるように作っている。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
from typing import Any

import suru as S

RUNTIME = S.data_path("runtime", "suru_rt.c")

# 外部の関数の C の型 → LLVM IR の型
FFI_IR = {"i64": "i64", "f64": "double", "f32": "float", "i32": "i32", "bool": "i32", "str": "ptr", "ptr": "ptr", "bytes": "ptr",
          "void": "void", "val": "ptr"}  # val は外部に出す関数の手札(#208)
LINK_MARK = "; suru-link: "  # IR の中の、リンクするライブラリの印(build が読む)
EXPORT_MARK = "; suru-export: "  # IR の中の、外部に出す関数の印(「C の名前 型の字 する の名前」、共有ライブラリとヘッダを作るときに読む、#208)
# 外部に出す関数の C の型 → rt_export に渡す型の字(Go 版の exportCodes と同じ)
EXPORT_CODES = {"i64": "l", "i32": "i", "f64": "d", "f32": "f", "bool": "b", "str": "s", "ptr": "p", "void": "v",
                "bytes": "y", "list_i64": "L", "list_f64": "D", "list_str": "S", "val": "h"}


def export_seq(t: str) -> bool:
    """番地と長さの2つで渡す型か(#208 段階3、Go 版の exportSeq と同じ)"""
    return t == "bytes" or t.startswith("list_")
PART_IDS = {"を": 0, "に": 1, "で": 2, "から": 3, "へ": 4, "より": 5, "が": 6}
OPS = {"+": 0, "-": 1, "*": 2, "/": 3, "%": 4, "^": 5, "<": 6, ">": 7, "<=": 8, ">=": 9, "==": 10, "!=": 11}
CMP_PRED = {"<": "slt", ">": "sgt", "<=": "sle", ">=": "sge", "==": "eq", "!=": "ne"}
INT_MAX = (1 << 62) - 1
INT_MIN = -(1 << 62)

DECLS = """
declare ptr @rt_alloc(i64)
declare i64 @rt_ffi_i64(i64, ptr, i32, i32)
declare i32 @rt_ffi_i32(i64, ptr, i32, i32)
declare double @rt_ffi_f64(i64, ptr, i32, i32)
declare float @rt_ffi_f32(i64, ptr, i32, i32)
declare ptr @rt_ffi_mt_buf()
declare void @rt_ffi_main(ptr, ptr)
declare i32 @rt_ffi_bool(i64, ptr, i32, i32)
declare ptr @rt_ffi_str(i64, ptr, i32, i32)
declare ptr @rt_ffi_ptr(i64, ptr, i32, i32)
declare ptr @rt_ffi_fnptr(i64, ptr, i32, i32)
declare ptr @rt_ffi_bytes(i64, ptr, i32, i32)
declare void @rt_ffi_pre()
declare void @rt_ffi_post()
declare i64 @rt_ffi_from_i64(i64, ptr, i32)
declare i64 @rt_ffi_from_i32(i32)
declare i64 @rt_ffi_from_bool(i32)
declare i64 @rt_ffi_from_str(ptr)
declare i64 @rt_ffi_from_ptr(ptr)
declare i64 @rt_ffi_action(i64, ptr, i32)
declare i64 @rt_bool(i32)
declare i64 @rt_float(double)
declare i64 @rt_str(ptr, i64)
declare i64 @rt_list(i64, ptr)
declare i64 @rt_make_fn(ptr, i32, ptr, ptr, ptr)
declare i64 @rt_lazy(ptr, ptr)
declare i64 @rt_force(i64)
declare void @rt_def_ctor(ptr, ptr, i32, ptr)
declare void @rt_trait(ptr)
declare void @rt_trait_method(ptr, ptr, i32, ptr, i32, i32, i64)
declare void @rt_impl(ptr, ptr, ptr, i64)
declare i64 @rt_binop(i32, i64, i64, i32)
declare i64 @rt_neg(i64, i32)
declare i32 @rt_truthy(i64)
declare i32 @rt_truth(i64, ptr, i32)
declare i64 @rt_pred_check(i64, ptr, i32)
declare i32 @rt_eq(i64, i64)
declare i64 @rt_field(i64, ptr, i32)
declare i64 @rt_field_result(i64, i32)
declare i64 @rt_prop(i64, ptr, i32)
declare i64 @rt_each_check(i64, i32)
declare i32 @rt_is_list_len(i64, i64)
declare i64 @rt_list_at(i64, i64)
declare i32 @rt_is_ctor(i64, ptr)
declare i64 @rt_rec_at(i64, i64)
declare i64 @rt_named_get(i64, ptr)
declare i64 @rt_bind_seq(i64, i64, i32, ptr, i32)
declare void @rt_no_match(i64, ptr, i32)
declare void @rt_run_outside(i32)
declare void @rt_fail(ptr, i32)
declare i64 @rt_construct(ptr, i32, ptr, i32)
declare i64 @rt_update(i64, i32, ptr, ptr, i32)
declare i64 @rt_call(i64, i32, ptr, ptr, i32)
declare i64 @rt_call_ex(i64, i32, ptr, ptr, ptr, i32)
declare i64 @rt_ref(i64, i32, ptr, ptr, ptr, i32)
declare i64 @rt_chain_then(i64, i64, i32)
declare i64 @rt_do_run(i64, i64, ptr, i32)
declare i64 @rt_do_unwrap(i64, i64, ptr, ptr, i32)
declare i64 @rt_unwrap(i64, ptr, i32)
declare i64 @rt_trace(i64, ptr, i32)
declare i64 @rt_do_seq(i64, i64, i32)
declare i64 @rt_do_result(i64)
declare i64 @rt_std(ptr)
declare i64 @rt_global_cached(ptr, ptr, i32)
declare void @rt_top(i64)
declare i64 @rt_export(ptr, i32, ptr, ptr, ptr, i32)
declare i32 @rt_enter(i32)
declare void @rt_leave(i32)
declare void @rt_top_unwrap(i64)
declare void @rt_safepoint()
@rt_gc_stop = external dso_local global i32
@rt_sp_tick = external thread_local(localexec) global i32
declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.ssub.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.smul.with.overflow.i64(i64, i64)
"""


class CompileError(Exception):
    pass


# 読み込んだファイルの行は、本体の行の後ろに続けて番号を振る(道 → 足す数)。実行時ライブラリの suru_files で戻す
LINE_BASE: dict[str, int] = {}


def line_count(text: str) -> int:
    return text.count("\n") + 1


def pos_of(node_or_line: Any) -> int:
    line = node_or_line if isinstance(node_or_line, int) else getattr(node_or_line, "line", 0)
    if not isinstance(line, int):
        return 0
    col = getattr(line, "col", None) or 0
    n = int(line)
    src = getattr(line, "src", None)
    if n and src:
        n += LINE_BASE.get(src, 0)
    return min(n, 0xFFFFF) | (min(col, 0x7FF) << 20)


def ir_bytes(data: bytes) -> str:
    out = []
    for b in data:
        if 0x20 <= b < 0x7F and b not in (0x22, 0x5C):
            out.append(chr(b))
        else:
            out.append(f"\\{b:02X}")
    return "".join(out)


def double_hex(x: float) -> str:
    return "0x%016X" % struct.unpack("<Q", struct.pack("<d", x))[0]


# --- 名前の結びつき(コンパイル時) ---------------------------------------


class FnInfo:
    """直接呼べる関数(一番外の関数と局所関数)"""

    def __init__(self, name: str, order: list, direct: str, wrapper: str):
        self.name = name
        self.order = order  # 助詞の順
        self.direct = direct  # @f.N(ptr up, i64..., i32 pos)
        self.wrapper = wrapper  # @g.N(ptr up, ptr args, i32 pos)
        self.lib = False  # ライブラリで定義した関数(自分のプログラムから呼ぶときに、呼んだ場所を覚える)


class Binding:
    def __init__(self, kind: str, **kw: Any):
        self.kind = kind  # slot / lfn / gfn / gval / gconst
        self.__dict__.update(kw)


class Scope:
    def __init__(self, parent: "Scope | None", fg: "FnGen | None"):
        self.parent = parent
        self.fg = fg
        self.vars: dict[str, Binding] = {}

    def lookup(self, name: str) -> Binding | None:
        s: Scope | None = self
        while s is not None:
            if name in s.vars:
                return s.vars[name]
            s = s.parent
        return None


# 関数の入口の安全点(Go 版の safepoint と同じ)。する のコードを呼ばない関数(葉)には置かない
SAFEPOINT = """  %sp = load atomic i32, ptr @rt_gc_stop monotonic, align 4
  %spc = icmp ne i32 %sp, 0
  br i1 %spc, label %sp.wait, label %b0
sp.wait:
  call void @rt_safepoint()
  br label %b0"""

# 呼んでも する のコードに戻らない実行時の関数(これだけを呼ぶ関数は再帰の輪に入らないので、安全点が要らない。
# 確保は rt_alloc の中で安全点を見る)。Go 版の leafSafe と同じ
LEAF_SAFE = frozenset("""@rt_alloc @rt_bool @rt_float @rt_str @rt_list @rt_make_fn @rt_lazy @rt_binop @rt_neg @rt_truthy
@rt_truth @rt_pred_check @rt_eq @rt_field @rt_field_result @rt_prop @rt_each_check @rt_is_list_len @rt_list_at
@rt_is_ctor @rt_rec_at @rt_named_get @rt_no_match @rt_fail @rt_construct @rt_update @rt_global_cached
@llvm.sadd.with.overflow.i64 @llvm.ssub.with.overflow.i64 @llvm.smul.with.overflow.i64""".split())
CALL_RE = re.compile(r"\bcall [^@%]*([@%][^(\s]*)\(")


# 自分だけを呼ぶ再帰の関数の安全点(#81): スレッドごとの数(rt_sp_tick)を減らし、SP_TICK 回に1回だけ rt_gc_stop を見る。
# GC を待たせるのは、ほかの関数を呼ばない(確保もしない)計算の 64 回分だけ。Go 版の safepointSelf と同じ
SP_TICK = 64
SAFEPOINT_SELF = f"""  %tk = load i32, ptr @rt_sp_tick, align 4
  %tk1 = sub i32 %tk, 1
  store i32 %tk1, ptr @rt_sp_tick, align 4
  %tkz = icmp eq i32 %tk1, 0
  br i1 %tkz, label %sp.tick, label %b0
sp.tick:
  store i32 {SP_TICK}, ptr @rt_sp_tick, align 4
""" + SAFEPOINT


def entry_safepoint(header: str, lines: list[str]) -> str:
    """関数の入口の安全点: 葉なら置かない、自分だけを呼ぶなら間引く、ほかはいつも見る"""
    calls = {m.group(1) for line in lines for m in CALL_RE.finditer(line)} - LEAF_SAFE
    if not calls:
        return "  br label %b0"
    m = re.search(r"(@[^(\s]*)\(", header)
    if m is not None and calls == {m.group(1)}:
        return SAFEPOINT_SELF
    return SAFEPOINT


class FnGen:
    """1つの LLVM の関数。ローカル変数はフレーム(i64 の配列、0番目は外側のフレーム)に置く"""

    def __init__(self, cg: "Compiler", parent: "FnGen | None"):
        self.cg = cg
        self.parent = parent
        self.lines: list[str] = []
        self.entry: list[str] = []
        self.n = 0
        self.nslots = 1
        self.escapes = False  # このフレームを捕まえる関数を作るか(作るならヒープに置く)
        self.label = "b0"
        self.lines.append("b0:")

    def tmp(self) -> str:
        self.n += 1
        return f"%t{self.n}"

    def new_label(self) -> str:
        self.n += 1
        return f"L{self.n}"

    def emit(self, line: str) -> None:
        self.lines.append("  " + line)

    def start(self, label: str) -> None:
        self.lines.append(f"{label}:")
        self.label = label

    def call(self, ret: str, fn: str, args: str) -> str:
        if ret == "void":
            self.emit(f"call void {fn}({args})")
            return ""
        t = self.tmp()
        self.emit(f"{t} = call {ret} {fn}({args})")
        return t

    def new_slot(self) -> int:
        k = self.nslots
        self.nslots += 1
        return k

    def array(self, values: list[str]) -> str:
        """i64 の配列(呼び出しの引数など)"""
        if not values:
            return "null"
        self.n += 1
        arr = f"%arr{self.n}"
        self.entry.append(f"  {arr} = alloca i64, i32 {len(values)}")
        for i, v in enumerate(values):
            p = self.tmp()
            self.emit(f"{p} = getelementptr i64, ptr {arr}, i64 {i}")
            self.emit(f"store i64 {v}, ptr {p}")
        return arr

    def frame_of(self, owner: "FnGen") -> str:
        """owner のフレームへのポインタ(外側へたどる)"""
        p, f = "%fr", self
        while f is not owner:
            t = self.tmp()
            self.emit(f"{t} = load ptr, ptr {p}")
            p, f = t, f.parent
            if f is None:
                raise CompileError("内部エラー: フレームが見つかりません")
        return p

    def store_slot(self, k: int, v: str) -> None:
        p = self.tmp()
        self.emit(f"{p} = getelementptr i64, ptr %fr, i64 {k}")
        self.emit(f"store i64 {v}, ptr {p}")

    def load_slot(self, owner: "FnGen", k: int) -> str:
        fr = self.frame_of(owner)
        p = self.tmp()
        self.emit(f"{p} = getelementptr i64, ptr {fr}, i64 {k}")
        t = self.tmp()
        self.emit(f"{t} = load i64, ptr {p}")
        return t

    def finish(self, header: str, ret_type: str = "i64") -> str:
        frame = []
        if self.escapes:
            frame.append(f"  %fr = call ptr @rt_alloc(i64 {self.nslots * 8})")
        else:
            frame.append(f"  %fr = alloca i64, i32 {self.nslots}")
        frame.append("  store ptr %up, ptr %fr")
        # 安全点: GC がほかのスレッドを止めたいとき(rt_gc_stop が 1)は、ここで止まる
        enter = entry_safepoint(header, self.lines)
        return "\n".join([f"{header} {{", "entry:"] + self.entry + frame + [enter] + self.lines + ["}"])


# --- コンパイラ ------------------------------------------------------------


class Compiler:
    def __init__(self, ctx: S.ParseContext, source: str):
        self.ctx = ctx
        self.source = source
        self.globals: list[str] = []
        self.functions: list[str] = []
        self.init: list[str] = []  # suru_main の始めに行う登録
        self.consts_init: list[str] = []
        self.cstrings: dict[bytes, str] = {}
        self.part_arrays: dict[tuple, str] = {}
        self.ptr_arrays: dict[tuple, str] = {}
        self.str_values: dict[str, str] = {}
        self.float_values: dict[float, str] = {}
        self.global_cache: dict[str, str] = {}
        self.roots: list[str] = []  # 値を入れる大域変数(GC の根)
        self.n = 0
        self.modules: dict[str, Scope] = {}
        self.init_fg: FnGen | None = None
        self.ffi_decls: dict[str, str] = {}  # 外部の関数の名前 → declare の行
        self.ffi_where: dict[str, Any] = {}  # 外部の関数の名前 → 初めに宣言した位置
        self.link_libs: list[str] = []  # リンクするライブラリ(ExternLib.path)
        self.exports: list[str] = []  # 外部に出す関数の C の名前(#208)

    def uid(self) -> int:
        self.n += 1
        return self.n

    # --- 定数 ---

    def cstr(self, s: str) -> str:
        data = s.encode("utf-8")
        if data not in self.cstrings:
            name = f"@s.{self.uid()}"
            self.globals.append(
                f'{name} = private unnamed_addr constant [{len(data) + 1} x i8] c"{ir_bytes(data)}\\00"')
            self.cstrings[data] = name
        return self.cstrings[data]

    def parts(self, parts: list) -> str:
        key = tuple(PART_IDS[p] for p in parts)
        if not key:
            return "null"
        if key not in self.part_arrays:
            name = f"@p.{self.uid()}"
            items = ", ".join(f"i32 {k}" for k in key)
            self.globals.append(f"{name} = private unnamed_addr constant [{len(key)} x i32] [{items}]")
            self.part_arrays[key] = name
        return self.part_arrays[key]

    def ptrs(self, names: list) -> str:
        key = tuple(names)
        if not key:
            return "null"
        if key not in self.ptr_arrays:
            name = f"@n.{self.uid()}"
            items = ", ".join(f"ptr {self.cstr(x)}" for x in key)
            self.globals.append(f"{name} = private unnamed_addr constant [{len(key)} x ptr] [{items}]")
            self.ptr_arrays[key] = name
        return self.ptr_arrays[key]

    def new_global(self, prefix: str) -> str:
        name = f"@{prefix}.{self.uid()}"
        self.globals.append(f"{name} = internal global i64 0")
        self.roots.append(name)
        return name

    def str_value(self, s: str) -> str:
        if s not in self.str_values:
            g = self.new_global("sv")
            data = s.encode("utf-8")
            self.consts_init.append(f"  %c{g[1:]} = call i64 @rt_str(ptr {self.cstr(s)}, i64 {len(data)})")
            self.consts_init.append(f"  store i64 %c{g[1:]}, ptr {g}")
            self.str_values[s] = g
        return self.str_values[s]

    def float_value(self, x: float) -> str:
        key = struct.pack("<d", x)
        if key not in self.float_values:
            g = self.new_global("fv")
            self.consts_init.append(f"  %c{g[1:]} = call i64 @rt_float(double {double_hex(x)})")
            self.consts_init.append(f"  store i64 %c{g[1:]}, ptr {g}")
            self.float_values[key] = g
        return self.float_values[key]

    # --- 式 ---

    def ex(self, node: Any, sc: Scope, fg: FnGen) -> str:
        m = getattr(self, "ex_" + type(node).__name__, None)
        if m is None:
            raise CompileError(f"この書き方はまだコンパイルできません({type(node).__name__})")
        return m(node, sc, fg)

    def ex_Num(self, node: S.Num, sc: Scope, fg: FnGen) -> str:
        v = node.value
        if v is True or v is False:
            return fg.call("i64", "@rt_bool", f"i32 {1 if v else 0}")
        if v == ():
            return fg.call("i64", "@rt_list", "i64 0, ptr null")
        if isinstance(v, int):
            if not INT_MIN <= v <= INT_MAX:
                raise CompileError(f"整数 {v} は大きすぎます(コンパイルしたプログラムの整数は ±{INT_MAX} までです)")
            return str((v << 1) | 1)
        return self.load_global(self.float_value(float(v)), fg)

    def load_global(self, g: str, fg: FnGen) -> str:
        t = fg.tmp()
        fg.emit(f"{t} = load i64, ptr {g}")
        return t

    def ex_Str(self, node: S.Str, sc: Scope, fg: FnGen) -> str:
        return self.load_global(self.str_value(node.value), fg)

    def var_value(self, name: str, sc: Scope, fg: FnGen, line: Any) -> str:
        b = sc.lookup(name)
        if b is None:
            if name not in self.global_cache:
                self.global_cache[name] = self.new_global("gc")
            return fg.call("i64", "@rt_global_cached", f"ptr {self.global_cache[name]}, ptr {self.cstr(name)}, i32 {pos_of(line)}")
        if b.kind in ("slot", "lfn"):
            v = fg.load_slot(b.owner, b.slot)
            if getattr(b, "lazy", False):
                v = fg.call("i64", "@rt_force", f"i64 {v}")
            return v
        if b.kind == "gval":
            v = self.load_global(b.g, fg)
            return fg.call("i64", "@rt_force", f"i64 {v}")
        return self.load_global(b.g, fg)  # gfn / gconst

    def ex_Var(self, node: S.Var, sc: Scope, fg: FnGen) -> str:
        return self.var_value(node.name, sc, fg, node.line)

    def ex_ListLit(self, node: S.ListLit, sc: Scope, fg: FnGen) -> str:
        vals = [self.ex(i, sc, fg) for i in node.items]
        arr = fg.array(vals)
        return fg.call("i64", "@rt_list", f"i64 {len(vals)}, ptr {arr}")

    def ex_Prop(self, node: S.Prop, sc: Scope, fg: FnGen) -> str:
        t = self.ex(node.target, sc, fg)
        return fg.call("i64", "@rt_prop", f"i64 {t}, ptr {self.cstr(node.name)}, i32 {pos_of(node)}")

    def ex_Field(self, node: S.Field, sc: Scope, fg: FnGen) -> str:
        t = self.ex(node.target, sc, fg)
        if node.name == S.RESULT:
            return fg.call("i64", "@rt_field_result", f"i64 {t}, i32 {pos_of(node)}")
        return fg.call("i64", "@rt_field", f"i64 {t}, ptr {self.cstr(node.name)}, i32 {pos_of(node)}")

    def ex_Each(self, node: S.Each, sc: Scope, fg: FnGen) -> str:
        t = self.ex(node.target, sc, fg)
        return fg.call("i64", "@rt_each_check", f"i64 {t}, i32 {pos_of(node)}")

    def ex_Neg(self, node: S.Neg, sc: Scope, fg: FnGen) -> str:
        t = self.ex(node.operand, sc, fg)
        return fg.call("i64", "@rt_neg", f"i64 {t}, i32 0")

    def ex_Not(self, node: S.Not, sc: Scope, fg: FnGen) -> str:
        return self.bool_value(self.truth(node, sc, fg, None), fg)

    def bool_value(self, b: str, fg: FnGen) -> str:
        """i1 を真偽の値にする"""
        z = fg.tmp()
        fg.emit(f"{z} = zext i1 {b} to i32")
        return fg.call("i64", "@rt_bool", f"i32 {z}")

    def truth(self, node: Any, sc: Scope, fg: FnGen, what: str | None) -> str:
        """式の真偽を i1 で。what が None なら「もし」の読み方(rt_truthy)、あれば真偽でないとエラー(rt_truth)。
        整数の比較・「かつ」「または」・「ではない」は真偽の値を作らずに分岐できるようにする(#80)"""
        def to_i1(v: str) -> str:
            if what is None:
                t = fg.call("i32", "@rt_truthy", f"i64 {v}")
            else:
                t = fg.call("i32", "@rt_truth", f"i64 {v}, ptr {self.cstr(what)}, i32 {pos_of(getattr(node, 'line', 0))}")
            b = fg.tmp()
            fg.emit(f"{b} = icmp ne i32 {t}, 0")
            return b

        if isinstance(node, S.Not):
            b = self.truth(node.operand, sc, fg, S.DENAI)
            x = fg.tmp()
            fg.emit(f"{x} = xor i1 {b}, true")
            return x
        if isinstance(node, S.BinOp) and node.op in (S.KW_KATSU, S.KW_MATAHA):
            return self.logic_i1(node, sc, fg)
        if not (isinstance(node, S.BinOp) and node.op in CMP_PRED):
            return to_i1(self.ex(node, sc, fg))
        # 比較: 両方が整数なら icmp の結果でそのまま分岐する
        a = self.ex(node.left, sc, fg)
        b = self.ex(node.right, sc, fg)
        both, fast, slow, join = fg.tmp(), fg.new_label(), fg.new_label(), fg.new_label()
        x, c, cmp = fg.tmp(), fg.tmp(), fg.tmp()
        fg.emit(f"{x} = and i64 {a}, {b}")
        fg.emit(f"{both} = and i64 {x}, 1")
        fg.emit(f"{c} = icmp ne i64 {both}, 0")
        fg.emit(f"br i1 {c}, label %{fast}, label %{slow}")
        fg.start(fast)
        fg.emit(f"{cmp} = icmp {CMP_PRED[node.op]} i64 {a}, {b}")
        fg.emit(f"br label %{join}")
        fg.start(slow)
        v = fg.call("i64", "@rt_binop", f"i32 {OPS[node.op]}, i64 {a}, i64 {b}, i32 {pos_of(node)}")
        sv = to_i1(v)
        fg.emit(f"br label %{join}")
        fg.start(join)
        r = fg.tmp()
        fg.emit(f"{r} = phi i1 [{cmp}, %{fast}], [{sv}, %{slow}]")
        return r

    def ex_BinOp(self, node: S.BinOp, sc: Scope, fg: FnGen) -> str:
        if node.op in (S.KW_KATSU, S.KW_MATAHA):
            return self.logic(node, sc, fg)
        a = self.ex(node.left, sc, fg)
        b = self.ex(node.right, sc, fg)
        op = OPS[node.op]
        pos = pos_of(node)
        if node.op not in ("+", "-", "*", "<", ">", "<=", ">=", "==", "!="):
            return fg.call("i64", "@rt_binop", f"i32 {op}, i64 {a}, i64 {b}, i32 {pos}")
        # 両方が整数なら、その場で計算する(溢れたら実行時ライブラリに任せる)
        both, fast, slow, join = fg.tmp(), fg.new_label(), fg.new_label(), fg.new_label()
        x, c = fg.tmp(), fg.tmp()
        fg.emit(f"{x} = and i64 {a}, {b}")
        fg.emit(f"{both} = and i64 {x}, 1")
        fg.emit(f"{c} = icmp ne i64 {both}, 0")
        fg.emit(f"br i1 {c}, label %{fast}, label %{slow}")
        fg.start(fast)
        if node.op in ("+", "-", "*"):
            if node.op == "+":
                y = fg.tmp()
                fg.emit(f"{y} = sub i64 {b}, 1")
                r = fg.tmp()
                fg.emit(f"{r} = call {{i64, i1}} @llvm.sadd.with.overflow.i64(i64 {a}, i64 {y})")
            elif node.op == "-":
                y = fg.tmp()
                fg.emit(f"{y} = sub i64 {b}, 1")
                r = fg.tmp()
                fg.emit(f"{r} = call {{i64, i1}} @llvm.ssub.with.overflow.i64(i64 {a}, i64 {y})")
            else:
                xa, yb = fg.tmp(), fg.tmp()
                fg.emit(f"{xa} = sub i64 {a}, 1")
                fg.emit(f"{yb} = ashr i64 {b}, 1")
                r = fg.tmp()
                fg.emit(f"{r} = call {{i64, i1}} @llvm.smul.with.overflow.i64(i64 {xa}, i64 {yb})")
            val, ovf = fg.tmp(), fg.tmp()
            fg.emit(f"{val} = extractvalue {{i64, i1}} {r}, 0")
            fg.emit(f"{ovf} = extractvalue {{i64, i1}} {r}, 1")
            if node.op == "*":
                v2 = fg.tmp()
                fg.emit(f"{v2} = or i64 {val}, 1")
                val = v2
            ok = fg.new_label()
            fg.emit(f"br i1 {ovf}, label %{slow}, label %{ok}")
            fg.start(ok)
            fast_val, fast_label = val, ok
        else:
            pred = CMP_PRED[node.op]
            cmp, z = fg.tmp(), fg.tmp()
            fg.emit(f"{cmp} = icmp {pred} i64 {a}, {b}")
            fg.emit(f"{z} = zext i1 {cmp} to i32")
            fast_val = fg.call("i64", "@rt_bool", f"i32 {z}")
            fast_label = fg.label
        fg.emit(f"br label %{join}")
        fg.start(slow)
        slow_val = fg.call("i64", "@rt_binop", f"i32 {op}, i64 {a}, i64 {b}, i32 {pos}")
        fg.emit(f"br label %{join}")
        fg.start(join)
        res = fg.tmp()
        fg.emit(f"{res} = phi i64 [{fast_val}, %{fast_label}], [{slow_val}, %{slow}]")
        return res

    def logic(self, node: S.BinOp, sc: Scope, fg: FnGen) -> str:
        return self.bool_value(self.logic_i1(node, sc, fg), fg)

    def logic_i1(self, node: S.BinOp, sc: Scope, fg: FnGen) -> str:
        """「かつ」「または」を i1 で: 左で決まれば右は計算しない"""
        ta = self.truth(node.left, sc, fg, node.op)
        done, right, join = fg.new_label(), fg.new_label(), fg.new_label()
        stop_on = node.op == S.KW_MATAHA
        if stop_on:
            fg.emit(f"br i1 {ta}, label %{done}, label %{right}")
        else:
            fg.emit(f"br i1 {ta}, label %{right}, label %{done}")
        fg.start(done)
        fg.emit(f"br label %{join}")
        fg.start(right)
        tb = self.truth(node.right, sc, fg, node.op)
        l2 = fg.label
        fg.emit(f"br label %{join}")
        fg.start(join)
        r = fg.tmp()
        fg.emit(f"{r} = phi i1 [{'true' if stop_on else 'false'}, %{done}], [{tb}, %{l2}]")
        return r

    def ex_If(self, node: S.If, sc: Scope, fg: FnGen) -> str:
        b = self.truth(node.cond, sc, fg, None)
        lt, le, lj = fg.new_label(), fg.new_label(), fg.new_label()
        fg.emit(f"br i1 {b}, label %{lt}, label %{le}")
        fg.start(lt)
        v1 = self.ex(node.then, sc, fg)
        l1 = fg.label
        fg.emit(f"br label %{lj}")
        fg.start(le)
        v2 = self.ex(node.other, sc, fg)
        l2 = fg.label
        fg.emit(f"br label %{lj}")
        fg.start(lj)
        r = fg.tmp()
        fg.emit(f"{r} = phi i64 [{v1}, %{l1}], [{v2}, %{l2}]")
        return r

    # --- 呼び出し ---

    def call_args(self, args: dict, sc: Scope, fg: FnGen) -> tuple[list, list, list]:
        parts, vals, flags = [], [], []
        for p, a in args.items():
            parts.append(p)
            if isinstance(a, S.Field) and a.name == S.RESULT:
                vals.append(self.ex(a.target, sc, fg))
                flags.append(2)
            elif isinstance(a, S.Each):
                vals.append(self.ex(a, sc, fg))
                flags.append(1)
            else:
                vals.append(self.ex(a, sc, fg))
                flags.append(0)
        return parts, vals, flags

    def ex_Call(self, node: S.Call, sc: Scope, fg: FnGen) -> str:
        b = sc.lookup(node.name)
        parts, vals, flags = self.call_args(node.args, sc, fg)
        pos = pos_of(node)
        if b is not None and b.kind in ("gfn", "lfn") and not any(flags) and sorted(parts) == sorted(b.info.order):
            by_part = dict(zip(parts, vals))
            up = "null" if b.kind == "gfn" else fg.frame_of(b.owner)
            args = ", ".join([f"ptr {up}"] + [f"i64 {by_part[p]}" for p in b.info.order] + [f"i32 {pos}"])
            if not (b.info.lib and pos and S.is_user_pos(node.line)):
                return fg.call("i64", b.info.direct, args)
            # 自分のプログラムからライブラリの関数を呼ぶ: その中の実行時エラーは、ここの位置で出す(#154)
            old = fg.call("i32", "@rt_enter", f"i32 {pos}")
            r = fg.call("i64", b.info.direct, args)
            fg.call("void", "@rt_leave", f"i32 {old}")
            return r
        fn = self.var_value(node.name, sc, fg, node.line)
        arr = fg.array(vals)
        pa = self.parts(parts)
        if any(flags):
            fl = f"@fl.{self.uid()}"
            self.globals.append(f"{fl} = private unnamed_addr constant [{len(flags)} x i32] [{', '.join(f'i32 {x}' for x in flags)}]")
            return fg.call("i64", "@rt_call_ex", f"i64 {fn}, i32 {len(vals)}, ptr {pa}, ptr {arr}, ptr {fl}, i32 {pos}")
        return fg.call("i64", "@rt_call", f"i64 {fn}, i32 {len(vals)}, ptr {pa}, ptr {arr}, i32 {pos}")

    def ex_Ref(self, node: S.Ref, sc: Scope, fg: FnGen) -> str:
        fn = self.var_value(node.name, sc, fg, node.line)
        parts = list(node.args)
        vals = [self.ex(a, sc, fg) for a in node.args.values()]
        arr = fg.array(vals)
        return fg.call("i64", "@rt_ref", f"i64 {fn}, i32 {len(vals)}, ptr {self.parts(parts)}, ptr {arr}, "
                                         f"ptr {self.cstr(node.name)}, i32 {pos_of(node)}")

    # --- 関数 ---

    def gen_function(self, name: str, params: list, body: Any, sc: Scope, parent: FnGen | None,
                     info: FnInfo, check_pred: bool = True) -> None:
        """関数の本体をコンパイルする(直接呼ぶ版と、関数の値から呼ぶ版)"""
        fg = FnGen(self, parent)
        local = Scope(sc, fg)
        argnames = [f"%a{i}" for i in range(len(params))]
        for (p, pat), a in zip(params, argnames):
            if isinstance(pat, str):
                k = fg.new_slot()
                fg.store_slot(k, a)
                local.vars[pat] = Binding("slot", owner=fg, slot=k)
            else:
                seq = fg.call("i64", "@rt_bind_seq", f"i64 {a}, i64 {len(pat)}, i32 {PART_IDS[p]}, ptr {self.cstr(name)}, i32 %pos")
                for i, x in enumerate(pat):
                    v = fg.call("i64", "@rt_list_at", f"i64 {seq}, i64 {i}")
                    k = fg.new_slot()
                    fg.store_slot(k, v)
                    local.vars[x] = Binding("slot", owner=fg, slot=k)
        if isinstance(body, S.Extern):
            body = self.extern_body(name, params, body)
        r = body(local, fg) if callable(body) else self.ex(body, local, fg)
        if check_pred and S.is_predicate(name):
            r = fg.call("i64", "@rt_pred_check", f"i64 {r}, ptr {self.cstr(name)}, i32 %pos")
        fg.emit(f"ret i64 {r}")
        header = f"define internal i64 {info.direct}(ptr %up, " + "".join(f"i64 {a}, " for a in argnames) + "i32 %pos)"
        self.functions.append(fg.finish(header))
        # 関数の値から呼ぶ版: 引数の配列を開いて直接呼ぶ版へ
        w = [f"define internal i64 {info.wrapper}(ptr %up, ptr %args, i32 %pos) {{", "entry:"]
        loads = []
        for i in range(len(params)):
            w.append(f"  %p{i} = getelementptr i64, ptr %args, i64 {i}")
            w.append(f"  %v{i} = load i64, ptr %p{i}")
            loads.append(f"i64 %v{i}, ")
        w.append(f"  %r = call i64 {info.direct}(ptr %up, {''.join(loads)}i32 %pos)")
        w.append("  ret i64 %r")
        w.append("}")
        self.functions.append("\n".join(w))

    def extern_body(self, name: str, params: list, ext: S.Extern) -> Any:
        """外部の関数の本体: 引数を C の値にして呼び、値を戻す。値が動作なら、行ったときに呼ぶ動作を返す"""
        for lib in ext.libs:
            if lib not in self.link_libs:
                self.link_libs.append(lib)
        ret = FFI_IR[ext.result]
        if not ext.pointer:
            if ext.cargs:
                cts = ["i64" if k == "定数" else FFI_IR[ext.params[v]] for k, v in ext.cargs]
            else:
                cts = [FFI_IR[t] for t in ext.params]
            decl = f"declare {ret} @{ext.symbol}({', '.join(cts)})"
            if self.ffi_decls.setdefault(ext.symbol, decl) != decl:
                first = self.ffi_where[ext.symbol]
                raise S.SuruError(f"外部の関数「{ext.symbol}」が違う型で2回宣言されています"
                                  f"(もう1つは{S._file_of(first)}{S._where(first)})。"
                                  "C の関数1つにつき、引数と値の型は1通りにそろえてください", ext.line)
            self.ffi_where.setdefault(ext.symbol, ext.line)
        fname = self.cstr(name)

        def call(sc: Scope, fg: FnGen) -> str:
            args = []
            fn = f"@{ext.symbol}"
            for (p, x), t in zip(params, ext.params):
                v = self.var_value(x, sc, fg, ext.line)
                if x == ext.pointer:
                    fn = fg.call("ptr", "@rt_ffi_fnptr", f"i64 {v}, ptr {fname}, i32 {PART_IDS[p]}, i32 %pos")
                    continue
                c = fg.call(FFI_IR[t], f"@rt_ffi_{t}", f"i64 {v}, ptr {fname}, i32 {PART_IDS[p]}, i32 %pos")
                args.append(f"{FFI_IR[t]} {c}")
            if ext.cargs:
                args = [f"i64 {v}" if k == "定数" else args[v] for k, v in ext.cargs]
            if ext.main_thread:
                r = self.main_thread_call(ret, fn, args, fg, ext.line)
            else:
                fg.call("void", "@rt_ffi_pre", "")
                r = fg.call(ret, fn, ", ".join(args))
                fg.call("void", "@rt_ffi_post", "")
            if ext.result == "void":
                return "1"  # 数の 0
            if ext.result == "i64":
                return fg.call("i64", "@rt_ffi_from_i64", f"i64 {r}, ptr {fname}, i32 %pos")
            if ext.result == "f64":
                return fg.call("i64", "@rt_float", f"double {r}")
            if ext.result == "f32":
                d = fg.tmp()
                fg.emit(f"{d} = fpext float {r} to double")
                return fg.call("i64", "@rt_float", f"double {d}")
            return fg.call("i64", f"@rt_ffi_from_{ext.result}", f"{ret} {r}")

        if not ext.action:
            return call

        def action(sc: Scope, fg: FnGen) -> str:
            k = self.closure(name, [(S.WO, f"\0捨てる{self.uid()}")], call, sc, fg, check_pred=False)
            return fg.call("i64", "@rt_ffi_action", f"i64 {k}, ptr {fname}, i32 %pos")
        return action

    def main_thread_call(self, ret: str, fn: str, args: list, fg: FnGen, line: int) -> str:
        """主スレッドで呼ぶ: 関数の番地と引数を rt_ffi_mt_buf に置き、それを読んで呼ぶ関数を rt_ffi_main に渡す"""
        if len(args) > 38:
            raise S.SuruError("主スレッドで呼ぶ外部の関数の引数は 38 個までです", line)
        buf = fg.call("ptr", "@rt_ffi_mt_buf", "")
        k = self.uid()
        th = [f"define internal void @mt.{k}(ptr %b) {{", "entry:"]
        fg.emit(f"store ptr {fn}, ptr {buf}")
        targs = []
        for i, a in enumerate(args):
            t, v = a.split(" ", 1)
            slot = fg.tmp()
            fg.emit(f"{slot} = getelementptr i64, ptr {buf}, i64 {i + 2}")
            fg.emit(f"store {t} {v}, ptr {slot}")
            th.append(f"  %s{i} = getelementptr i64, ptr %b, i64 {i + 2}")
            th.append(f"  %a{i} = load {t}, ptr %s{i}")
            targs.append(f"{t} %a{i}")
        th.append("  %f = load ptr, ptr %b")
        if ret == "void":
            th.append(f"  call void %f({', '.join(targs)})")
        else:
            th.append(f"  %r = call {ret} %f({', '.join(targs)})")
            th.append("  %rs = getelementptr i64, ptr %b, i64 1")
            th.append(f"  store {ret} %r, ptr %rs")
        th += ["  ret void", "}"]
        self.functions.append("\n".join(th))
        fg.call("void", "@rt_ffi_pre", "")
        fg.call("void", "@rt_ffi_main", f"ptr @mt.{k}, ptr {buf}")
        fg.call("void", "@rt_ffi_post", "")
        if ret == "void":
            return ""
        slot = fg.tmp()
        fg.emit(f"{slot} = getelementptr i64, ptr {buf}, i64 1")
        r = fg.tmp()
        fg.emit(f"{r} = load {ret}, ptr {slot}")
        return r

    def new_info(self, name: str, params: list) -> FnInfo:
        k = self.uid()
        return FnInfo(name, [p for p, _ in params], f"@f.{k}", f"@g.{k}")

    def make_fn_value(self, info: FnInfo, fg: FnGen, up: str) -> str:
        return fg.call("i64", "@rt_make_fn", f"ptr {self.cstr(info.name)}, i32 {len(info.order)}, "
                                             f"ptr {self.parts(info.order)}, ptr {info.wrapper}, ptr {up}")

    def closure(self, name: str, params: list, body: Any, sc: Scope, fg: FnGen, check_pred: bool = True) -> str:
        """その場で作る関数の値(外側のフレームを捕まえる)"""
        info = self.new_info(name, params)
        self.gen_function(name, params, body, sc, fg, info, check_pred)
        fg.escapes = True
        return self.make_fn_value(info, fg, "%fr")

    def ex_Lambda(self, node: S.Lambda, sc: Scope, fg: FnGen) -> str:
        return self.closure("無名関数", node.params, node.body, sc, fg)

    def thunk(self, body: Any, sc: Scope, parent: FnGen | None) -> str:
        """値の定義(使うときに計算する)。Code 型の関数の名前を返す"""
        fg = FnGen(self, parent)
        r = self.ex(body, Scope(sc, fg), fg)
        fg.emit(f"ret i64 {r}")
        name = f"@z.{self.uid()}"
        self.functions.append(fg.finish(f"define internal i64 {name}(ptr %up, ptr %args, i32 %pos)"))
        return name

    def local_defines(self, defines: list, sc: Scope, fg: FnGen) -> None:
        """ブロックの局所定義: 先に全部の名前を決めてから中身を作る(相互に参照できる)"""
        infos = {}
        for d in defines:
            k = fg.new_slot()
            if d.is_function:
                info = self.new_info(d.name, d.params)
                infos[id(d)] = info
                sc.vars[d.name] = Binding("lfn", owner=fg, slot=k, info=info)
            else:
                sc.vars[d.name] = Binding("slot", owner=fg, slot=k, lazy=True)
        eager = [d for d in defines if not d.is_function and S.has_pure_unwrap(d.body)]
        eager_ids = {id(d) for d in eager}
        for d in eager:
            sc.vars[d.name] = Binding("slot", owner=fg, slot=sc.vars[d.name].slot)
        for d in defines:
            b = sc.vars[d.name]
            if id(d) in eager_ids:
                continue
            if d.is_function:
                self.gen_function(d.name, d.params, d.body, sc, fg, b.info)
                fg.escapes = True
                v = self.make_fn_value(b.info, fg, "%fr")
            else:
                z = self.thunk(d.body, sc, fg)
                fg.escapes = True
                v = fg.call("i64", "@rt_lazy", f"ptr {z}, ptr %fr")
            fg.store_slot(b.slot, v)
        # 「した 中身」を使う値の定義は、使うときでなく、書いた順にここで計算する
        for d in eager:
            fg.store_slot(sc.vars[d.name].slot, self.ex(d.body, sc, fg))

    def ex_Block(self, node: S.Block, sc: Scope, fg: FnGen) -> str:
        local = Scope(sc, fg)
        self.local_defines([s for s in node.statements if isinstance(s, S.Define)], local, fg)
        result = "0"
        for s in node.statements:
            if not isinstance(s, S.Define):
                result = self.ex(s, local, fg)
        return result

    # --- 組 ---

    def ex_Construct(self, node: S.Construct, sc: Scope, fg: FnGen) -> str:
        vals = [self.ex(i, sc, fg) for i in node.items]
        arr = fg.array(vals)
        return fg.call("i64", "@rt_construct", f"ptr {self.cstr(node.ctor)}, i32 {len(vals)}, ptr {arr}, i32 {pos_of(node)}")

    def fail(self, msg: str, line: Any, fg: FnGen) -> str:
        fg.call("void", "@rt_fail", f"ptr {self.cstr(msg)}, i32 {pos_of(line)}")
        fg.emit("unreachable")
        fg.start(fg.new_label())
        return "0"

    def ex_NamedConstruct(self, node: S.NamedConstruct, sc: Scope, fg: FnGen) -> str:
        fields = self.ctx.ctors[node.ctor][1]
        given = {f: e for f, e in node.fields}
        for f in given:
            if f not in fields:
                return self.fail(f"「{node.ctor}」には「{f}」というフィールドがありません", node.line, fg)
        for f in fields:
            if f not in given:
                return self.fail(f"「{node.ctor}」の「{f}」が書かれていません", node.line, fg)
        vals = [self.ex(given[f], sc, fg) for f in fields]
        arr = fg.array(vals)
        return fg.call("i64", "@rt_construct", f"ptr {self.cstr(node.ctor)}, i32 {len(vals)}, ptr {arr}, i32 {pos_of(node)}")

    def ex_Update(self, node: S.Update, sc: Scope, fg: FnGen) -> str:
        t = self.ex(node.target, sc, fg)
        names = [f for f, _ in node.fields]
        vals = [self.ex(e, sc, fg) for _, e in node.fields]
        arr = fg.array(vals)
        return fg.call("i64", "@rt_update", f"i64 {t}, i32 {len(vals)}, ptr {self.ptrs(names)}, ptr {arr}, i32 {pos_of(node)}")

    # --- パターンマッチ ---

    def pattern(self, pat: Any, v: str, fail: str, sc: Scope, fg: FnGen) -> None:
        def check(cond_i32: str) -> None:
            c = fg.tmp()
            fg.emit(f"{c} = icmp ne i32 {cond_i32}, 0")
            ok = fg.new_label()
            fg.emit(f"br i1 {c}, label %{ok}, label %{fail}")
            fg.start(ok)

        if isinstance(pat, S.PBind):
            k = fg.new_slot()
            fg.store_slot(k, v)
            sc.vars[pat.name] = Binding("slot", owner=fg, slot=k)
        elif isinstance(pat, S.PValue):
            e = self.ex(pat.expr, sc, fg)
            check(fg.call("i32", "@rt_eq", f"i64 {e}, i64 {v}"))
        elif isinstance(pat, S.PSeq):
            check(fg.call("i32", "@rt_is_list_len", f"i64 {v}, i64 {len(pat.items)}"))
            for i, p in enumerate(pat.items):
                x = fg.call("i64", "@rt_list_at", f"i64 {v}, i64 {i}")
                self.pattern(p, x, fail, sc, fg)
        elif isinstance(pat, S.PCtor):
            check(fg.call("i32", "@rt_is_ctor", f"i64 {v}, ptr {self.cstr(pat.ctor)}"))
            nfields = len(self.ctx.ctors[pat.ctor][1]) if pat.ctor in self.ctx.ctors else len(pat.items)
            for i, p in enumerate(pat.items[:nfields]):
                x = fg.call("i64", "@rt_rec_at", f"i64 {v}, i64 {i}")
                self.pattern(p, x, fail, sc, fg)
        elif isinstance(pat, S.PNamed):
            if pat.ctor is not None:
                check(fg.call("i32", "@rt_is_ctor", f"i64 {v}, ptr {self.cstr(pat.ctor)}"))
            for fname, p in pat.fields:
                x = fg.call("i64", "@rt_named_get", f"i64 {v}, ptr {self.cstr(fname)}")
                c = fg.tmp()
                fg.emit(f"{c} = icmp ne i64 {x}, 0")
                ok = fg.new_label()
                fg.emit(f"br i1 {c}, label %{ok}, label %{fail}")
                fg.start(ok)
                self.pattern(p, x, fail, sc, fg)
        else:
            raise CompileError(f"分からないパターン {pat!r}")

    def ex_Match(self, node: S.Match, sc: Scope, fg: FnGen) -> str:
        subj = self.ex(node.subject, sc, fg)
        end = fg.new_label()
        results = []
        for pat, guard, body in node.cases:
            nxt = fg.new_label()
            local = Scope(sc, fg)
            self.pattern(pat, subj, nxt, local, fg)
            if guard is not None:
                c = self.truth(guard, local, fg, S.KW_KATSU)
                ok = fg.new_label()
                fg.emit(f"br i1 {c}, label %{ok}, label %{nxt}")
                fg.start(ok)
            v = self.ex(body, local, fg)
            results.append((v, fg.label))
            fg.emit(f"br label %{end}")
            fg.start(nxt)
        if node.default is not None:
            v = self.ex(node.default, sc, fg)
            results.append((v, fg.label))
            fg.emit(f"br label %{end}")
        else:
            fg.call("void", "@rt_no_match", f"i64 {subj}, ptr {self.cstr(node.fname)}, i32 {pos_of(node)}")
            fg.emit("unreachable")
        fg.start(end)
        if not results:
            fg.emit("unreachable")
            fg.start(fg.new_label())
            return "0"
        r = fg.tmp()
        fg.emit(f"{r} = phi i64 " + ", ".join(f"[{v}, %{l}]" for v, l in results))
        return r

    # --- 動作 ---

    def ex_Chain(self, node: S.Chain, sc: Scope, fg: FnGen) -> str:
        m = self.ex(node.call, sc, fg)
        k = self.closure("続き", [(S.WO, S.HOLE)], node.cont, sc, fg, check_pred=False)
        return fg.call("i64", "@rt_chain_then", f"i64 {m}, i64 {k}, i32 {pos_of(node)}")

    def ex_Run(self, node: S.Run, sc: Scope, fg: FnGen) -> str:
        key = S._run_key(node)
        if sc.lookup(key) is None and node.unwrap:
            # 関数の本体の「した 中身」: 失敗(無)ならその値を関数から返す
            v = self.ex(node.call, sc, fg)
            x = fg.call("i64", "@rt_unwrap", f"i64 {v}, ptr {self.cstr(S._call_name(node.call))}, i32 {pos_of(node)}")
            b = fg.tmp()
            fg.emit(f"{b} = icmp eq i64 {x}, 0")
            early, cont = fg.new_label(), fg.new_label()
            fg.emit(f"br i1 {b}, label %{early}, label %{cont}")
            fg.start(early)
            t = fg.call("i64", "@rt_trace", f"i64 {v}, ptr {self.cstr(node.fn)}, i32 {pos_of(node)}")
            fg.emit(f"ret i64 {t}")
            fg.start(cont)
            return x
        if sc.lookup(key) is None:
            fg.call("void", "@rt_run_outside", f"i32 {pos_of(node)}")
            fg.emit("unreachable")
            fg.start(fg.new_label())
            return "0"
        return self.var_value(key, sc, fg, node.line)

    def ex_Do(self, node: S.Do, sc: Scope, fg: FnGen) -> str:
        v = self.do(node.statements, 0, Scope(sc, fg), fg, node.line)
        return fg.call("i64", "@rt_do_result", f"i64 {v}")

    def do(self, stmts: list, i: int, sc: Scope, fg: FnGen, line: Any) -> str:
        """手順の i 番目からを行う。「した 結果」は連鎖に、途中の文は「それから」にする"""
        s = stmts[i]
        runs = [r for r in S.collect_runs(s, []) if sc.lookup(S._run_key(r)) is None]
        if runs:
            r = runs[0]
            m = self.ex(r.call, sc, fg)
            key = S._run_key(r)
            if r.unwrap:
                def rest_u(local: Scope, kfg: FnGen) -> str:
                    return self.do(stmts, i, local, kfg, line)

                k = self.closure("続き", [(S.WO, key)], rest_u, sc, fg, check_pred=False)
                return fg.call("i64", "@rt_do_unwrap", f"i64 {m}, i64 {k}, ptr {self.cstr(S._call_name(r.call))}, "
                                                       f"ptr {self.cstr(r.fn)}, i32 {pos_of(r)}")

            def rest(local: Scope, kfg: FnGen) -> str:
                return self.do(stmts, i, local, kfg, line)

            k = self.closure("続き", [(S.WO, key)], rest, sc, fg, check_pred=False)
            name = r.call.name[:-len(S.SURU)] if isinstance(r.call, S.Call) else ""
            return fg.call("i64", "@rt_do_run", f"i64 {m}, i64 {k}, ptr {self.cstr(name)}, i32 {pos_of(r)}")
        if isinstance(s, S.Define):
            local = Scope(sc, fg)
            if s.is_function:
                self.local_defines([s], local, fg)
            else:
                v = self.ex(s.body, local, fg)
                k = fg.new_slot()
                fg.store_slot(k, v)
                local.vars[s.name] = Binding("slot", owner=fg, slot=k)
            return self.do(stmts, i + 1, local, fg, line)
        v = self.ex(s, sc, fg)
        if i == len(stmts) - 1:
            return v

        def after(local: Scope, kfg: FnGen) -> str:
            return self.do(stmts, i + 1, local, kfg, line)

        k = self.closure("続き", [(S.WO, f"\0捨てる{self.uid()}")], after, sc, fg, check_pred=False)
        return fg.call("i64", "@rt_do_seq", f"i64 {v}, i64 {k}, i32 {pos_of(getattr(s, 'line', line))}")

    # --- プログラムとファイル ---

    def module(self, program: list, path: str, top: FnGen | None) -> Scope:
        """一番外の定義をコンパイルして、その名前の表を返す。読み込んだファイルは一度だけ"""
        if path in self.modules:
            return self.modules[path]
        sc = Scope(None, None)
        self.modules[path] = sc
        ini = self.init_fg
        for b in S.LIB_PRIMITIVES.get(path, ()):
            g = self.new_global("gp")
            v = ini.call("i64", "@rt_std", f"ptr {self.cstr(b.name)}")
            ini.emit(f"store i64 {v}, ptr {g}")
            sc.vars[b.name] = Binding("gconst", g=g)
        for stmt in program:
            if isinstance(stmt, S.Import):
                sub = self.module(stmt.module.program, stmt.module.path, None)
                for name, b in list(sub.vars.items()):
                    if S.MODULE_SEP not in name and name not in stmt.module.private:
                        sc.vars[stmt.module.name + S.MODULE_SEP + name] = b
                        if stmt.open:
                            sc.vars[name] = b
        defines = [s for s in program if isinstance(s, S.Define)]
        for d in defines:
            if d.is_function:
                info = self.new_info(d.name, d.params)
                info.lib = S.in_library(d.line)
                sc.vars[d.name] = Binding("gfn", g=self.new_global("gf"), info=info)
            else:
                sc.vars[d.name] = Binding("gval", g=self.new_global("gv"))
        for d in defines:
            b = sc.vars[d.name]
            if d.is_function:
                self.gen_function(d.name, d.params, d.body, sc, None, b.info)
                v = self.make_fn_value(b.info, ini, "null")
            else:
                z = self.thunk(d.body, sc, None)
                v = ini.call("i64", "@rt_lazy", f"ptr {z}, ptr null")
            ini.emit(f"store i64 {v}, ptr {b.g}")
        # 性質と、その実装
        for stmt in program:
            if isinstance(stmt, S.TraitDecl):
                ini.call("void", "@rt_trait", f"ptr {self.cstr(stmt.name)}")
                members = [(n, ps, None) for n, ps in stmt.sigs] + [(d.name, d.params, d) for d in stmt.defaults]
                for fname, params, d in members:
                    deflt = "0"
                    if d is not None:
                        deflt = self.global_function(d, sc, ini)
                    wo = next((k for k, (p, _) in enumerate(params) if p == S.WO), 0)
                    wo_list = 0 if isinstance(params[wo][1], str) else 1
                    parts = [p for p, _ in params]
                    ini.call("void", "@rt_trait_method", f"ptr {self.cstr(stmt.name)}, ptr {self.cstr(fname)}, i32 {len(parts)}, "
                                                         f"ptr {self.parts(parts)}, i32 {wo}, i32 {wo_list}, i64 {deflt}")
        for stmt in program:
            if isinstance(stmt, S.TraitImpl):
                t, ty = self.cstr(stmt.trait), self.cstr(stmt.type_name)
                ini.call("void", "@rt_impl", f"ptr {t}, ptr {ty}, ptr null, i64 0")
                for d in stmt.defs:
                    v = self.global_function(d, sc, ini)
                    ini.call("void", "@rt_impl", f"ptr {t}, ptr {ty}, ptr {self.cstr(d.name)}, i64 {v}")
        return sc

    def global_function(self, d: S.Define, sc: Scope, ini: FnGen) -> str:
        info = self.new_info(d.name, d.params)
        self.gen_function(d.name, d.params, d.body, sc, None, info)
        return self.make_fn_value(info, ini, "null")

    def compile(self, program: list, path: str) -> str:
        ini = FnGen(self, None)
        self.init_fg = ini
        # 形(どのファイルのものも)
        for ctor, (tname, fields) in self.ctx.ctors.items():
            ini.call("void", "@rt_def_ctor", f"ptr {self.cstr(ctor)}, ptr {self.cstr(tname)}, i32 {len(fields)}, ptr {self.ptrs(fields)}")
        sc = self.module(program, path, ini)
        self.export_wrappers(program, sc)
        top = Scope(sc, ini)
        for s in program:
            if isinstance(s, (S.Define,) + S.TOP_LEVEL_ONLY):
                continue
            v = self.ex(s, top, ini)
            ini.call("void", "@rt_top_unwrap" if S.is_top_unwrap_do(s) else "@rt_top", f"i64 {v}")
        ini.emit("ret i64 0")
        main = ini.finish("define internal i64 @suru_init(ptr %up)")
        self.functions.append(main)
        consts = "\n".join(self.consts_init)
        entry = f"define void @suru_main() {{\nentry:\n{consts}\n  %r = call i64 @suru_init(ptr null)\n  ret void\n}}"
        src = self.source.encode("utf-8")
        source = f'@suru_source = constant [{len(src) + 1} x i8] c"{ir_bytes(src)}\\00"\n' + self.files_table()
        links = [LINK_MARK + lib for lib in self.link_libs] + [EXPORT_MARK + sym for sym in self.exports]
        ffi = [self.ffi_decls[k] for k in sorted(self.ffi_decls)]
        return "\n".join(["; 「する」のコンパイラが作った LLVM IR"] + links + [DECLS] + ffi + [source] + self.globals + self.functions + [entry, self.roots_table()]) + "\n"

    def export_wrappers(self, program: list, sc: Scope) -> None:
        """「以下は外部に出す関数です」の関数を、C の呼び出し規約の関数として出す(#208、Go 版の exportWrappers と同じ)。
        引数を i64 の並びに置いて rt_export に渡し、実行時ライブラリが値に直して呼ぶ(初期化・スレッド・エラーもそこで扱う)"""
        for e in program:
            if not isinstance(e, S.Export):
                continue
            b = sc.vars[e.name]
            n = len(e.params)
            params = []
            slots = 0
            for k, t in enumerate(e.params):
                if export_seq(t):
                    params.append(f"ptr %a{k}, i64 %n{k}")
                    slots += 2
                else:
                    params.append(f"{FFI_IR[t]} %a{k}")
                    slots += 1
            if export_seq(e.result):
                params.append("ptr %outlen")
                slots += 1
            codes = "".join(EXPORT_CODES[t] for t in e.params) + EXPORT_CODES[e.result] + ("!" if e.action else "")
            self.exports.append(f"{e.symbol} {codes} {e.name}")
            slots = slots or 1
            ret = "ptr" if export_seq(e.result) else FFI_IR[e.result]
            lines = [f"define {ret} @{e.symbol}({', '.join(params)}) {{", "entry:", f"  %s = alloca [{slots} x i64]"]
            j = 0
            for k, t in enumerate(e.params):
                p = f"%p{k}"
                lines.append(f"  {p} = getelementptr [{slots} x i64], ptr %s, i64 0, i64 {j}")
                j += 1
                if export_seq(t):
                    lines += [f"  store ptr %a{k}, ptr {p}", f"  %q{k} = getelementptr [{slots} x i64], ptr %s, i64 0, i64 {j}",
                              f"  store i64 %n{k}, ptr %q{k}"]
                    j += 1
                elif t == "i64":
                    lines.append(f"  store i64 %a{k}, ptr {p}")
                elif t in ("i32", "bool"):
                    lines += [f"  %x{k} = sext i32 %a{k} to i64", f"  store i64 %x{k}, ptr {p}"]
                elif t == "f64":
                    lines.append(f"  store double %a{k}, ptr {p}")
                elif t == "f32":
                    lines += [f"  %x{k} = fpext float %a{k} to double", f"  store double %x{k}, ptr {p}"]
                else:  # str・ptr
                    lines.append(f"  store ptr %a{k}, ptr {p}")
            if export_seq(e.result):
                lines += [f"  %po = getelementptr [{slots} x i64], ptr %s, i64 0, i64 {j}", "  store ptr %outlen, ptr %po"]
            c = self.cstr(codes)
            nm = self.cstr(e.name)
            lines.append(f"  %r = call i64 @rt_export(ptr {b.g}, i32 {n}, ptr {c}, ptr %s, ptr {nm}, i32 {pos_of(e.line)})")
            r = e.result
            if r == "void":
                lines.append("  ret void")
            elif r == "i64":
                lines.append("  ret i64 %r")
            elif r in ("i32", "bool"):
                lines += ["  %v = trunc i64 %r to i32", "  ret i32 %v"]
            elif r == "f64":
                lines += ["  %v = bitcast i64 %r to double", "  ret double %v"]
            elif r == "f32":
                lines += ["  %d = bitcast i64 %r to double", "  %v = fptrunc double %d to float", "  ret float %v"]
            else:
                lines += ["  %v = inttoptr i64 %r to ptr", "  ret ptr %v"]
            self.functions.append("\n".join(lines) + "\n}")

    def files_table(self) -> str:
        """読み込んだファイル(読み込んだ順)の、行の番号に足した数・名前・中身(実行時エラーの表示に使う)"""
        mods = [m for m in self.ctx.modules.values() if m is not None]
        bases, names, srcs, libs = [], [], [], []
        for m in mods:
            bases.append(f"i32 {LINE_BASE.get(m.path, 0)}")
            libs.append(f"i32 {int(m.path in S.LIBRARY_SRCS)}")
            names.append(f"ptr {self.cstr(os.path.basename(m.path))}")
            data = m.source.encode("utf-8")
            g = f"@fs.{self.uid()}"
            self.globals.append(f'{g} = private unnamed_addr constant [{len(data) + 1} x i8] c"{ir_bytes(data)}\\00"')
            srcs.append(f"ptr {g}")
        n = len(mods)

        def arr(t: str, items: list) -> str:
            return f"[{', '.join(items)}]" if items else "zeroinitializer"

        return (f"@suru_file_base = constant [{n} x i32] {arr('i32', bases)}\n"
                f"@suru_file_name = constant [{n} x ptr] {arr('ptr', names)}\n"
                f"@suru_file_src = constant [{n} x ptr] {arr('ptr', srcs)}\n"
                f"@suru_file_lib = constant [{n} x i32] {arr('i32', libs)}\n"
                f"@suru_nfiles = constant i64 {n}")

    def roots_table(self) -> str:
        """GC の根: 値を入れる大域変数の一覧(runtime/suru_rt.c の suru_roots)"""
        items = ", ".join(f"ptr {g}" for g in self.roots)
        table = f"[{items}]" if self.roots else "zeroinitializer"
        return (f"@suru_roots = constant [{len(self.roots)} x ptr] {table}\n"
                f"@suru_nroots = constant i64 {len(self.roots)}")


def exports_of(ir: str) -> list[tuple[str, str, str]]:
    """IR の始めの「; suru-export: C の名前 型の字 する の名前」の行を読む(#208、Go 版の Exports と同じ)"""
    out = []
    for line in ir.split("\n"):
        if not line.startswith(";"):
            break
        if line.startswith(EXPORT_MARK):
            f = line[len(EXPORT_MARK):].split(" ", 2)
            out.append((f[0], f[1], f[2]) if len(f) == 3 else (f[0], "", ""))
    return out


def export_symbols(ir: str) -> list[str]:
    """IR の始めの「; suru-export: 」の行から、外部に出す関数の C の名前を読む(#208)"""
    return [sym for sym, _, _ in exports_of(ir)]


# 共有ライブラリが出す補助の関数(頭の名前_init など): (値の型, 名前, [(引数の型, 名前)], 英語の説明, 日本語の説明)。
# 実行時ライブラリの rt_lib_名前 を呼ぶ。型の「V」はヘッダでは 頭の名前_value、包みの C では void になる(#208、Go 版の LibHelpers と同じ)
LIB_HELPERS = [
    ("int", "init", [], "Initializes the library (the first call also does it). 0 on success, -1 on failure.",
     "ライブラリを用意します(最初の呼び出しでも行います)。うまくいけば 0、失敗なら -1。"),
    ("const char *", "last_error", [], "The error message of the last call on this thread, or NULL. The library owns it;\n"
     " * it stays valid until the next call on this thread (do not free it).",
     "このスレッドで最後に呼んだ関数のエラーの文(なければ NULL)。ライブラリのもので、\n * このスレッドで次に呼ぶまで使えます(解放しません)。"),
    ("void", "free", [("void *", "p")], "Frees a string, a list or a バイト列 returned by this library.",
     "このライブラリが返した文字列・リスト・バイト列を解放します。"),
    ("void", "release", [("V *", "h")], "Releases a handle (NULL is ignored). Any thread may call it at any time.",
     "手札を手放します(NULL なら何もしません)。どのスレッドからいつでも呼べます。"),
    ("const char *", "type", [("const V *", "h")], "The Suru type of the value (リスト, 数, 文字列, a record type ...). Do not free it.",
     "値の する の型の名前(リスト・数・文字列・組の型の名前など)。解放しません。"),
    ("char *", "show", [("const V *", "h")], "The value as 表示する shows it. Free it with {free}.",
     "表示する と同じ形の文字列。{free} で解放します。"),
    ("int64_t", "len", [("const V *", "h")], "The length of a list or a バイト列.", "リストかバイト列の長さ。"),
    ("V *", "get", [("const V *", "h"), ("int64_t", "i")], "Item i (from 0) of a list, as a new handle.",
     "リストの i 番目(0 から)を新しい手札で返します。"),
    ("V *", "field", [("const V *", "h"), ("const char *", "name")], "The field name of a record, as a new handle.",
     "組の項目 name を新しい手札で返します。"),
    ("int64_t", "to_int", [("const V *", "h")], "The value as a 数.", "値を 数 として読みます。"),
    ("double", "to_double", [("const V *", "h")], "The value as a 小数.", "値を 小数 として読みます。"),
    ("int", "to_bool", [("const V *", "h")], "The value as a 真偽 (0 or 1).", "値を 真偽(0 か 1)として読みます。"),
    ("char *", "to_string", [("const V *", "h")], "The value as a 文字列. Free it with {free}.",
     "値を 文字列 として読みます。{free} で解放します。"),
    ("V *", "from_int", [("int64_t", "x")], "A new handle holding the 数 x.", "数 x の新しい手札。"),
    ("V *", "from_double", [("double", "x")], "A new handle holding the 小数 x.", "小数 x の新しい手札。"),
    ("V *", "from_bool", [("int", "x")], "A new handle holding the 真偽 x.", "真偽 x の新しい手札。"),
    ("V *", "from_string", [("const char *", "s")], "A new handle holding a copy of the UTF-8 string s.",
     "UTF-8 の文字列 s の写しの新しい手札。"),
    ("V *", "list", [("V *const *", "items"), ("int64_t", "n")], "A new handle holding the list of the n handles in items.",
     "items の n 個の手札のリストの新しい手札。"),
    ("V *", "call", [("const V *", "f"), ("V *const *", "args"), ("int64_t", "n")],
     "Calls the function f with n handles. An action result is carried out. A new handle.",
     "関数 f を n 個の手札で呼びます。値が動作なら行います。新しい手札で返します。"),
]

# 型の字 → ヘッダに書く引数の C の型・値の C の型・する の型
# (y・L・D・S は番地と長さの2つで渡し、値なら長さを out_len に書く、#208 段階3)
HEADER_TYPES = {"l": ("int64_t", "int64_t", "数"), "i": ("int", "int", "整数"), "d": ("double", "double", "小数"),
                "f": ("float", "float", "単精度"), "b": ("int", "int", "真偽"), "s": ("const char *", "char *", "文字列"), "h": ("V *", "V *", "(手札)"),
                "p": ("void *", "void *", "番地"), "v": ("void", "void", "無"),
                "y": ("const uint8_t *", "uint8_t *", "バイト列"), "L": ("const int64_t *", "int64_t *", "数 の リスト"),
                "D": ("const double *", "double *", "小数 の リスト"), "S": ("const char *const *", "char **", "文字列 の リスト")}


def c_decl(t: str, name: str) -> str:
    """C の型と名前を並べる(「int64_t a1」「const char *a1」、Go 版の cDecl と同じ)"""
    return t + name if t.endswith("*") else f"{t} {name}"


def export_header(ir: str, prefix: str) -> str:
    """共有ライブラリの C のヘッダ(頭の名前.h)の中身を作る(#208 段階2、Go 版の ExportHeader と同じ文字を出す)"""
    guard = prefix.upper() + "_H"
    out = [f"/* {prefix}.h: generated by suruc. Do not edit.\n"
           " * 「する」のコンパイラが作ったヘッダです。直さないでください。\n"
           " *\n"
           f" * Errors: a call that fails returns 0, 0.0 or NULL, and {prefix}_last_error()\n"
           " *   returns its message (NULL when the last call on this thread succeeded).\n"
           " * Strings: string arguments are UTF-8 and are copied. A returned char * is\n"
           f" *   yours: free it with {prefix}_free().\n"
           " * Numbers: 数 (int64_t) must be within +-2^62; larger values are an error.\n * Lists and バイト列: an argument is a pointer and a length (aN, aN_len) and is copied;\n *   a result is a new block whose length is written to *out_len.\n * Threads: any thread may call these functions, also at the same time.\n"
           " *\n"
           f" * エラー: 失敗した呼び出しは 0・0.0・NULL を返し、{prefix}_last_error() で文を読めます\n"
           " *   (このスレッドの最後の呼び出しがうまくいったときは NULL)。\n"
           " * 文字列: 引数の文字列は UTF-8 で、写し取ります。返った char * は呼んだ側のもので、\n"
           f" *   {prefix}_free() で解放します。\n"
           " * 数: 数(int64_t)は ±2^62 までです。超えるとエラーになります。\n * リストとバイト列: 引数は番地と長さ(aN と aN_len)で渡し、写し取ります。\n *   値は新しい塊で、長さを *out_len に書きます。\n * スレッド: どのスレッドからも、同時にでも呼べます。\n"
           " */\n"
           f"#ifndef {guard}\n#define {guard}\n\n#include <stdint.h>\n\n"
           "#ifdef __cplusplus\nextern \"C\" {\n#endif\n\n"
           ]
    out[-1] = out[-1].removesuffix("\n")
    for k, (ret, hname, params, en, ja) in enumerate(LIB_HELPERS):
        if k == 3:
            out.append("\n/* Handles: a value that is not a number, a string, a バイト列 or a list of numbers,\n"
                       " * decimals or strings (a record, another list, a function ...) is passed as a\n"
                       f" * {prefix}_value *. A handle you get stays alive until {prefix}_release(); a handle\n"
                       " * you pass in is only borrowed.\n"
                       " * 手札: 数・文字列・バイト列・数や小数や文字列のリストで渡せない値(組・ほかのリスト・関数など)は\n"
                       f" * {prefix}_value * で渡します。受け取った手札は {prefix}_release() まで使えます。\n"
                       " * 渡した手札は借りるだけです。 */\n"
                       f"typedef struct {prefix}_value {prefix}_value;\n")
        args = ", ".join(c_decl(t.replace("V", f"{prefix}_value"), n) for t, n in params) or "void"
        doc = f"\n/* {en}\n * {ja} */\n".replace("{free}", f"{prefix}_free()")
        out.append(doc + c_decl(ret.replace("V", f"{prefix}_value"), f"{prefix}_{hname}") + f"({args});\n")
    for sym, codes0, name in exports_of(ir):
        codes = codes0.removesuffix("!")
        action = codes != codes0
        if not codes:
            continue
        cps, sps = [], []
        for k, ch in enumerate(codes[:-1]):
            ct, _, st = HEADER_TYPES[ch]
            cps.append(c_decl(ct.replace("V", f"{prefix}_value"), f"a{k + 1}"))
            if ch in "yLDS":
                cps.append(f"int64_t a{k + 1}_len")
            sps.append(st)
        rc = codes[-1]
        _, cres, sres = HEADER_TYPES[rc]
        if rc in "yLDS":
            cps.append("int64_t *out_len")
        line = f"\n/* する: {name}  {' と '.join(sps) or '(なし)'} → {sres}"
        if action:
            line += "(入出力動作)"
        if rc == "s":
            line += f"\n * The result is yours: free it with {prefix}_free(). / 値は {prefix}_free() で解放します。"
        elif rc == "S":
            line += (f"\n * The result is an array of out_len strings ending with NULL, in one block: free it once with {prefix}_free().\n"
                     f" * 値は out_len 個の文字列の並び(最後に NULL)で、1つの塊です。{prefix}_free() で1回だけ解放します。")
        elif rc == "h":
            line += f"\n * The result is a new handle: release it with {prefix}_release(). / 値は新しい手札で、{prefix}_release() で手放します。"
        elif rc in "yLDS":
            line += (f"\n * The result has *out_len items (out_len may be NULL); free it with {prefix}_free().\n"
                     f" * 値の長さは *out_len に書きます(out_len は NULL でもよい)。{prefix}_free() で解放します。")
        line += " */\n"
        line += c_decl(cres.replace("V", f"{prefix}_value"), sym) + f"({', '.join(cps) or 'void'});\n"
        out.append(line)
    out.append(f"\n#ifdef __cplusplus\n}}\n#endif\n\n#endif /* {guard} */\n")
    return "".join(out)


def check_library(program: list) -> None:
    """共有ライブラリにするプログラムの一番外を調べる(Go 版の checkLibrary と同じ)"""
    def bad(msg: str, line: Any) -> S.SuruError:
        err = S.SuruError(msg, line)
        err.kind = "コンパイル"
        return err
    if not any(isinstance(s, S.Export) for s in program):
        raise bad(f"共有ライブラリにするには、「{S.KW_IKA_EXPORT}です」で外部に出す関数を書きます"
                  f"(「{S.KW_IKA_EXPORT}です」「  二倍する は 「nibai」」「以上です」)", 0)
    for s in program:
        if isinstance(s, (S.Define,) + S.TOP_LEVEL_ONLY):
            continue
        raise bad("共有ライブラリにするファイルの一番外には、定義だけを書きます(一番外の文は、ライブラリを読み込んだときに行われてしまいます)",
                  S.first_line_of(s) or 0)


SP_TICK_EXE = "@rt_sp_tick = external thread_local(localexec) global i32"
SP_TICK_LIB = "@rt_sp_tick = external hidden thread_local global i32"


def compile_source(source: str, base_dir: str = ".", path: str = "<main>", check: bool = True, lib: bool = False) -> str:
    """する のプログラムを LLVM IR の文字列にする。間違いがあれば SuruError。
    lib なら共有ライブラリにするプログラム(「以下は外部に出す関数です」が要り、一番外には定義だけ、#208)"""
    if check:
        from suru_check import check as type_check

        type_check(source, base_dir, path)
    ctx = S.ParseContext(base_dir=base_dir, path=path)
    try:
        program = S.drop_tests(S.parse_program(source, ctx))  # 試験のまとまりと例は通常のビルドでは捨てる(#193)
    except S.SuruError as e:
        e.kind = "構文"  # --json の「kind」
        raise
    LINE_BASE.clear()
    base = line_count(source)
    for m in ctx.modules.values():
        if m is not None:
            LINE_BASE[m.path] = base
            base += line_count(m.source)
    # 定義の登録で見つかる間違い(名前の重なりなど)はインタプリタと同じように調べる
    it = S.Interpreter()
    it.ctx = ctx
    it.load_program(program, it.globals)
    if lib:
        check_library(program)
    try:
        ir = Compiler(ctx, source).compile(program, path)
        # 共有ライブラリでは、スレッドごとの変数をライブラリの中だけで使う形で読む
        # (localexec は実行ファイルでしか使えない。再帰の安全点が rt_sp_tick を使う、#208、Go 版と同じ)
        # 使わないなら宣言も消す(-O0 では、使わない hidden の宣言が TLS でない名前になり、リンクで食い違う)
        if lib and ir.count("@rt_sp_tick") == 1:
            return ir.replace(SP_TICK_EXE + "\n", "", 1)
        return ir.replace(SP_TICK_EXE, SP_TICK_LIB, 1) if lib else ir
    except CompileError as e:
        err = S.SuruError(str(e))
        err.kind = "コンパイル"
        raise err from None


def target() -> str:
    """作るプログラムの対象(clang の --target)。SURU_TARGET で別の OS 向けに作れる(Go 版の compiler.Target と同じ)"""
    return (os.environ.get("SURU_TARGET") or "").strip()


def target_windows() -> bool:
    """Windows 向けに作るか(Go 版の compiler.TargetWindows と同じ)"""
    t = target()
    if not t:
        return sys.platform == "win32"
    return "windows" in t or "mingw" in t


WINDOWS_NO_LIBS = {"dl", "rt", "pthread"}  # Windows にはなく C の標準のライブラリに入っているものと、作るときに必ず入れる pthread


def target_args() -> list[str]:
    t = target()
    return [f"--target={t}"] if t else []


def exe_path(out: str) -> str:
    """作るプログラムの道。Windows 向けなら .exe を付ける(Go 版の native.ExePath と同じ)"""
    if target_windows() and os.path.splitext(out)[1].lower() != ".exe":
        return out + ".exe"
    return out


def find_cc() -> str | None:
    for name in (os.environ.get("CC"), "clang"):
        if name and shutil.which(name):
            return name
    return None


# 共有ライブラリの形の実行時ライブラリ(main なし、名前を隠す)を作る引数(#208、Go 版の libFlags と同じ)
LIB_FLAGS = ["-DSURU_LIB", "-fPIC", "-fvisibility=hidden"]


def runtime_object(cc: str, prefix: str = "suru_rt-", flags: list[str] | None = None) -> str:
    """実行時ライブラリをコンパイルしたもの(中身が変わらなければ作り直さない)"""
    with open(RUNTIME, "rb") as f:
        digest = hashlib.sha256(f.read() + (cc + "\0" + target()).encode()).hexdigest()[:16]
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "suru")
    obj = os.path.join(cache, f"{prefix}{digest}.o")
    if not os.path.exists(obj):
        os.makedirs(cache, exist_ok=True)
        tmp = f"{obj}.{os.getpid()}.tmp"
        r = subprocess.run([cc, *target_args(), *(flags or []), "-O2", "-w", "-c", "-x", "c", RUNTIME, "-o", tmp],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise S.SuruError("実行時ライブラリのコンパイルに失敗しました:\n" + r.stderr)
        os.replace(tmp, obj)
    return obj


def _standard_lib_dir(d: str) -> bool:
    """リンカーと dlopen が普通に探すフォルダか(rpath を足さない)"""
    d = os.path.normpath(d)
    roots = ("/lib", "/lib64", "/usr/lib", "/usr/lib64")
    return d in roots or (os.path.dirname(d) in roots and "-linux-" in os.path.basename(d))


def _pkgconfig_link_flags(lib: str) -> list[str]:
    """短い名前のライブラリを、pkg-config のフォルダから探す clang の引数(Go 版の pkgConfigLinkFlags と同じ)"""
    d = S._pkgconfig_libdir(lib)
    if not d or _standard_lib_dir(d):
        return []
    if target_windows():
        return [f"-L{d}"]
    return [f"-L{d}", f"-Wl,-rpath,{d}"]


def link_flags(ll_path: str) -> list[str]:
    """IR の始めの「; suru-link: 」の行から、外部のライブラリをリンクする引数を作る"""
    flags: list[str] = []
    with open(ll_path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith(";"):
                break
            if line.startswith(LINK_MARK):
                lib = line[len(LINK_MARK):].rstrip("\n")
                if os.path.isabs(lib):
                    flags.append(lib)
                    if not target_windows():  # Windows の DLL は .exe と同じフォルダか PATH から探す
                        flags.append(f"-Wl,-rpath,{os.path.dirname(lib)}")
                elif lib != "c" and not (target_windows() and lib in WINDOWS_NO_LIBS):
                    flags += _pkgconfig_link_flags(lib) + [f"-l{lib}"]
    return flags


def build(ll_path: str, out: str, opt: str = "-O2") -> None:
    cc = find_cc()
    if cc is None:
        raise S.SuruError("バイナリを作るには clang が必要です(LLVM IR だけなら --ll を付けてください)")
    exe = exe_path(out)
    link_out, tmp_dir = exe, None
    if target_windows() and not windows_lld() and not exe.isascii():
        # GNU ld は Windows で日本語の道に書けないので、一時フォルダに作ってから移す(Go 版と同じ)
        import tempfile

        tmp_dir = tempfile.mkdtemp(prefix="suru-link-")
        link_out = os.path.join(tmp_dir, "out.exe")
    cmd = [cc, *target_args(), opt, "-w", ll_path, runtime_object(cc), "-o", link_out] + link_flags(ll_path)
    if target_windows():
        if windows_lld():
            # lld は日本語の道も読み書きできる(GNU ld は Windows の ANSI の道しか扱えない)
            cmd.append("-fuse-ld=lld")
        # pthread(winpthreads)は中に入れて、libwinpthread-1.dll なしで動くようにする(Go 版と同じ)
        cmd += ["-lm", "-Wl,-Bstatic", "-lpthread", "-Wl,-Bdynamic", "-lws2_32"]
        m = manifest_object()
        if m:
            cmd.append(m)
    else:
        cmd += ["-lm", "-lpthread"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise S.SuruError("clang でのビルドに失敗しました:\n" + r.stderr)
        if tmp_dir:
            shutil.copyfile(link_out, exe)
            os.chmod(exe, 0o755)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def target_darwin() -> bool:
    t = target()
    if not t:
        return sys.platform == "darwin"
    return "apple" in t or "darwin" in t


def lib_path(out: str) -> str:
    """共有ライブラリの道。拡張子がなければ OS に合わせて付ける(Go 版の native.LibPath と同じ)"""
    if os.path.splitext(out)[1] in (".so", ".dylib", ".dll"):
        return out
    return out + (".dll" if target_windows() else ".dylib" if target_darwin() else ".so")


def lib_prefix(out: str) -> str:
    """共有ライブラリの道から、補助の関数の頭の名前を決める(libkeisan.so → keisan、Go 版の native.LibPrefix と同じ)"""
    base = os.path.basename(out)
    for ext in (".so", ".dylib", ".dll"):
        if base.endswith(ext):
            base = base[: -len(ext)]
            break
    if base.startswith("lib"):
        base = base[3:]
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", base):
        raise S.SuruError(f"共有ライブラリの名前「{os.path.basename(out)}」から補助の関数の名前(「名前_last_error」など)を作れません。"
                          "-o には英字・数字・「_」だけの名前を付けてください(「-o libkeisan.so」)")
    return base


def lib_shim(prefix: str) -> str:
    """補助の関数(頭の名前_init など)を出す小さな C のファイルの中身(Go 版の LibShim と同じ)"""
    out = ['#include <stdint.h>\n#define E __attribute__((visibility("default")))\n']
    for ret, name, params, _, _ in LIB_HELPERS:
        ps = ", ".join(c_decl(t.replace("V", "void"), n) for t, n in params) or "void"
        ret = ret.replace("V", "void")
        call = f"rt_lib_{name}({', '.join(n for _, n in params)});"
        if ret != "void":
            call = "return " + call
        out.append(c_decl(ret, f"rt_lib_{name}") + f"({ps});\n")
        out.append("E " + c_decl(ret, f"{prefix}_{name}") + f"({ps}) {{ {call} }}\n")
    return "".join(out)


def lib_helper_symbols(prefix: str) -> list[str]:
    """補助の関数の C の名前(Go 版の LibHelperSymbols と同じ)"""
    return [f"{prefix}_{h[1]}" for h in LIB_HELPERS]


def build_shared(ll_path: str, out: str, opt: str = "-O2") -> str:
    """LLVM IR を共有ライブラリの形の実行時ライブラリとつないで共有ライブラリにする(#208、Go 版の native.BuildShared と同じ)。
    外に見せるのは、出す関数と補助の関数だけ"""
    import tempfile

    cc = find_cc()
    if cc is None:
        raise S.SuruError("共有ライブラリを作るには clang が必要です(LLVM IR だけなら --ll を付けてください)")
    lib = lib_path(out)
    prefix = lib_prefix(lib)
    rt = runtime_object(cc, "suru_rt_lib-", LIB_FLAGS)
    with open(ll_path, encoding="utf-8") as f:
        ir = f.read()
    syms = export_symbols(ir) + lib_helper_symbols(prefix)
    with tempfile.TemporaryDirectory(prefix="suru-lib-") as d:
        shim = os.path.join(d, "shim.c")
        with open(shim, "w", encoding="utf-8") as f:
            f.write(lib_shim(prefix))
        cmd = [cc, *target_args(), opt, "-w", "-fPIC", ll_path, rt, shim, "-o", lib]
        tmp = None
        if target_windows():
            # Windows(段階5): 出す名前は .def に並べ、import ライブラリ(lib名前.dll.a)も作る。
            # 一時フォルダで同じ名前に作ってから移す(Go 版と同じ)
            dfile = os.path.join(d, "exports.def")
            with open(dfile, "w", encoding="utf-8") as f:
                f.write("EXPORTS\n    " + "\n    ".join(syms) + "\n")
            tmp = os.path.join(d, os.path.basename(lib))
            cmd = [cc, *target_args(), opt, "-w", ll_path, rt, shim, dfile, "-o", tmp, "-shared", f"-Wl,--out-implib,{tmp}.a"]
            if windows_lld():
                cmd.append("-fuse-ld=lld")
        elif target_darwin():
            lst = os.path.join(d, "exports.txt")
            with open(lst, "w", encoding="utf-8") as f:
                f.write("".join(f"_{s}\n" for s in syms))
            cmd += ["-dynamiclib", f"-Wl,-install_name,@rpath/{os.path.basename(lib)}", f"-Wl,-exported_symbols_list,{lst}"]
        else:
            script = os.path.join(d, "exports.map")
            with open(script, "w", encoding="utf-8") as f:
                f.write("{\n  global:\n    " + ";\n    ".join(syms) + ";\n  local: *;\n};\n")
            cmd += ["-shared", f"-Wl,--version-script={script}"]
        cmd += link_flags(ll_path)
        if target_windows():
            # pthread(winpthreads)は中に入れて、libwinpthread-1.dll なしで動くようにする(実行ファイルと同じ)
            cmd += ["-lm", "-Wl,-Bstatic", "-lpthread", "-Wl,-Bdynamic", "-lws2_32"]
        else:
            cmd += ["-lm", "-lpthread"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise S.SuruError("clang でのビルドに失敗しました:\n" + r.stderr)
        if tmp is not None:
            try:
                for ext in ("", ".a"):
                    shutil.copyfile(tmp + ext, lib + ext)
            except OSError as e:
                raise S.SuruError(f"共有ライブラリを『{lib}』に書けません({e.strerror})") from None
    with open(header_path(lib, prefix), "w", encoding="utf-8") as f:
        f.write(export_header(ir, prefix))
    return lib


def header_path(lib: str, prefix: str) -> str:
    """共有ライブラリと同じ所に置く C のヘッダの道(libkeisan.so → keisan.h、#208 段階2、Go 版の HeaderPath と同じ)"""
    return os.path.join(os.path.dirname(lib), prefix + ".h")


def windows_lld() -> bool:
    """Windows 向けのリンクに lld(ld.lld)を使えるか(Go 版の windowsLLD と同じ)"""
    return shutil.which("ld.lld") is not None


# Windows のプログラムに埋め込む印。ファイルの道などの文字を UTF-8 で扱うようにする(Go 版の windowsManifest と同じ)
WINDOWS_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
    </windowsSettings>
  </application>
</assembly>
"""


def manifest_object() -> str | None:
    """WINDOWS_MANIFEST をリソースにしたオブジェクト(windres で作り、置いておく)。windres がなければ None"""
    tools = ([f"{target()}-windres"] if target() else []) + ["llvm-windres", "windres"]
    tool = next((t for t in tools if shutil.which(t)), None)
    if tool is None:
        return None
    digest = hashlib.sha256((WINDOWS_MANIFEST + "\0" + tool).encode()).hexdigest()[:16]
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "suru")
    d = os.path.join(cache, f"manifest-{digest}")
    obj = os.path.join(d, "manifest.o")
    if os.path.exists(obj):
        return obj
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "suru.manifest"), "w", encoding="utf-8") as f:
        f.write(WINDOWS_MANIFEST)
    with open(os.path.join(d, "manifest.rc"), "w", encoding="utf-8") as f:
        f.write('1 24 "suru.manifest"\n')
    tmp = f"manifest.o.{os.getpid()}.tmp"
    r = subprocess.run([tool, "-O", "coff", "-i", "manifest.rc", "-o", tmp], cwd=d, capture_output=True)
    if r.returncode != 0:
        return None
    os.replace(os.path.join(d, tmp), obj)
    return obj


USAGE = "使い方: python3 suru_compile.py [--ll] [--検査なし] [--共有ライブラリ] [--json] プログラム.suru [-o 出力]"
SHARED_FLAGS = ("--共有ライブラリ", "--shared")  # 他の言語から呼べる共有ライブラリを作る(#208)


def main(argv: list[str]) -> int:
    args = argv[1:]
    ll_only = "--ll" in args
    check = not any(a in S.NO_CHECK_FLAGS for a in args)
    as_json = any(a in S.JSON_FLAGS for a in args)
    shared = any(a in SHARED_FLAGS for a in args)
    out = None
    if "-o" in args:
        k = args.index("-o")
        if k + 1 >= len(args):
            print(USAGE, file=sys.stderr)
            return 2
        out = args[k + 1]
        del args[k:k + 2]
    files = [a for a in args if not a.startswith("--")]
    if len(files) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    src_path = files[0]
    with open(src_path, encoding="utf-8") as f:
        source = f.read()
    base_dir = os.path.dirname(os.path.abspath(src_path))
    stem = os.path.splitext(src_path)[0]
    try:
        ir = compile_source(source, base_dir, os.path.abspath(src_path), check, lib=shared)
        ll_path = (out if ll_only and out else stem + ".ll")
        with open(ll_path, "w", encoding="utf-8") as f:
            f.write(ir)
        if not ll_only and shared:
            build_shared(ll_path, out or os.path.join(os.path.dirname(stem), "lib" + os.path.basename(stem)))
            os.remove(ll_path)
        elif not ll_only:
            build(ll_path, out or stem)
            os.remove(ll_path)
    except S.SuruError as e:
        if as_json:
            print(S.error_json(e, "コンパイル", src_path), file=sys.stderr)
        else:
            print(S.format_error(e, source), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    sys.exit(main(sys.argv))

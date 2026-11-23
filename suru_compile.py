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
FFI_IR = {"i64": "i64", "f64": "double", "i32": "i32", "bool": "i32", "str": "ptr", "ptr": "ptr", "bytes": "ptr",
          "void": "void"}
LINK_MARK = "; suru-link: "  # IR の中の、リンクするライブラリの印(build が読む)
PART_IDS = {"を": 0, "に": 1, "で": 2, "から": 3, "へ": 4, "より": 5, "が": 6}
OPS = {"+": 0, "-": 1, "*": 2, "/": 3, "%": 4, "^": 5, "<": 6, ">": 7, "<=": 8, ">=": 9, "==": 10, "!=": 11}
INT_MAX = (1 << 62) - 1
INT_MIN = -(1 << 62)

DECLS = """
declare ptr @rt_alloc(i64)
declare i64 @rt_ffi_i64(i64, ptr, i32, i32)
declare i32 @rt_ffi_i32(i64, ptr, i32, i32)
declare double @rt_ffi_f64(i64, ptr, i32, i32)
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
declare i64 @rt_do_seq(i64, i64, i32)
declare i64 @rt_do_result(i64)
declare i64 @rt_std(ptr)
declare i64 @rt_global_cached(ptr, ptr, i32)
declare void @rt_top(i64)
declare void @rt_safepoint()
@rt_gc_stop = external global i32
declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.ssub.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.smul.with.overflow.i64(i64, i64)
"""


class CompileError(Exception):
    pass


def pos_of(node_or_line: Any) -> int:
    line = node_or_line if isinstance(node_or_line, int) else getattr(node_or_line, "line", 0)
    if not isinstance(line, int):
        return 0
    col = getattr(line, "col", None) or 0
    return int(line) | (min(col, 0x7FF) << 20)


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


def is_leaf(lines: list[str]) -> bool:
    return all(m.group(1) in LEAF_SAFE for line in lines for m in CALL_RE.finditer(line))


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
        enter = "  br label %b0" if is_leaf(self.lines) else SAFEPOINT
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
        self.link_libs: list[str] = []  # リンクするライブラリ(ExternLib.path)

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
        t = self.ex(node.operand, sc, fg)
        b = fg.call("i32", "@rt_truth", f"i64 {t}, ptr {self.cstr(S.DENAI)}, i32 {pos_of(getattr(node.operand, 'line', 0))}")
        x = fg.tmp()
        fg.emit(f"{x} = xor i32 {b}, 1")
        return fg.call("i64", "@rt_bool", f"i32 {x}")

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
            pred = {"<": "slt", ">": "sgt", "<=": "sle", ">=": "sge", "==": "eq", "!=": "ne"}[node.op]
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
        """「かつ」「または」: 左で決まれば右は計算しない"""
        what = self.cstr(node.op)
        a = self.ex(node.left, sc, fg)
        ta = fg.call("i32", "@rt_truth", f"i64 {a}, ptr {what}, i32 {pos_of(getattr(node.left, 'line', 0))}")
        c = fg.tmp()
        stop_on = 1 if node.op == S.KW_MATAHA else 0
        fg.emit(f"{c} = icmp eq i32 {ta}, {stop_on}")
        done, right, join = fg.new_label(), fg.new_label(), fg.new_label()
        fg.emit(f"br i1 {c}, label %{done}, label %{right}")
        fg.start(done)
        v1 = fg.call("i64", "@rt_bool", f"i32 {stop_on}")
        fg.emit(f"br label %{join}")
        fg.start(right)
        b = self.ex(node.right, sc, fg)
        tb = fg.call("i32", "@rt_truth", f"i64 {b}, ptr {what}, i32 {pos_of(getattr(node.right, 'line', 0))}")
        v2 = fg.call("i64", "@rt_bool", f"i32 {tb}")
        l2 = fg.label
        fg.emit(f"br label %{join}")
        fg.start(join)
        r = fg.tmp()
        fg.emit(f"{r} = phi i64 [{v1}, %{done}], [{v2}, %{l2}]")
        return r

    def ex_If(self, node: S.If, sc: Scope, fg: FnGen) -> str:
        c = self.ex(node.cond, sc, fg)
        t = fg.call("i32", "@rt_truthy", f"i64 {c}")
        b = fg.tmp()
        fg.emit(f"{b} = icmp ne i32 {t}, 0")
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
            return fg.call("i64", b.info.direct, args)
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
            decl = f"declare {ret} @{ext.symbol}({', '.join(FFI_IR[t] for t in ext.params)})"
            if self.ffi_decls.setdefault(ext.symbol, decl) != decl:
                raise S.SuruError(f"外部の関数「{ext.symbol}」が違う型で2回宣言されています", ext.line)
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
            fg.call("void", "@rt_ffi_pre", "")
            r = fg.call(ret, fn, ", ".join(args))
            fg.call("void", "@rt_ffi_post", "")
            if ext.result == "void":
                return "1"  # 数の 0
            if ext.result == "i64":
                return fg.call("i64", "@rt_ffi_from_i64", f"i64 {r}, ptr {fname}, i32 %pos")
            if ext.result == "f64":
                return fg.call("i64", "@rt_float", f"double {r}")
            return fg.call("i64", f"@rt_ffi_from_{ext.result}", f"{ret} {r}")

        if not ext.action:
            return call

        def action(sc: Scope, fg: FnGen) -> str:
            k = self.closure(name, [(S.WO, f"\0捨てる{self.uid()}")], call, sc, fg, check_pred=False)
            return fg.call("i64", "@rt_ffi_action", f"i64 {k}, ptr {fname}, i32 %pos")
        return action

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
        for d in defines:
            b = sc.vars[d.name]
            if d.is_function:
                self.gen_function(d.name, d.params, d.body, sc, fg, b.info)
                fg.escapes = True
                v = self.make_fn_value(b.info, fg, "%fr")
            else:
                z = self.thunk(d.body, sc, fg)
                fg.escapes = True
                v = fg.call("i64", "@rt_lazy", f"ptr {z}, ptr %fr")
            fg.store_slot(b.slot, v)

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
                g = self.ex(guard, local, fg)
                t = fg.call("i32", "@rt_truth", f"i64 {g}, ptr {self.cstr(S.KW_KATSU)}, i32 {pos_of(getattr(guard, 'line', 0))}")
                c = fg.tmp()
                fg.emit(f"{c} = icmp ne i32 {t}, 0")
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
        top = Scope(sc, ini)
        for s in program:
            if isinstance(s, (S.Define,) + S.TOP_LEVEL_ONLY):
                continue
            v = self.ex(s, top, ini)
            ini.call("void", "@rt_top", f"i64 {v}")
        ini.emit("ret i64 0")
        main = ini.finish("define internal i64 @suru_init(ptr %up)")
        self.functions.append(main)
        consts = "\n".join(self.consts_init)
        entry = f"define void @suru_main() {{\nentry:\n{consts}\n  %r = call i64 @suru_init(ptr null)\n  ret void\n}}"
        src = self.source.encode("utf-8")
        source = f'@suru_source = constant [{len(src) + 1} x i8] c"{ir_bytes(src)}\\00"'
        links = [LINK_MARK + lib for lib in self.link_libs]
        ffi = [self.ffi_decls[k] for k in sorted(self.ffi_decls)]
        return "\n".join(["; 「する」のコンパイラが作った LLVM IR"] + links + [DECLS] + ffi + [source] + self.globals + self.functions + [entry, self.roots_table()]) + "\n"

    def roots_table(self) -> str:
        """GC の根: 値を入れる大域変数の一覧(runtime/suru_rt.c の suru_roots)"""
        items = ", ".join(f"ptr {g}" for g in self.roots)
        table = f"[{items}]" if self.roots else "zeroinitializer"
        return (f"@suru_roots = constant [{len(self.roots)} x ptr] {table}\n"
                f"@suru_nroots = constant i64 {len(self.roots)}")


def compile_source(source: str, base_dir: str = ".", path: str = "<main>", check: bool = True) -> str:
    """する のプログラムを LLVM IR の文字列にする。間違いがあれば SuruError"""
    if check:
        from suru_check import check as type_check

        type_check(source, base_dir)
    ctx = S.ParseContext(base_dir=base_dir)
    program = S.parse_program(source, ctx)
    # 定義の登録で見つかる間違い(名前の重なりなど)はインタプリタと同じように調べる
    it = S.Interpreter()
    it.ctx = ctx
    it.load_program(program, it.globals)
    try:
        return Compiler(ctx, source).compile(program, path)
    except CompileError as e:
        raise S.SuruError(str(e)) from None


def find_cc() -> str | None:
    for name in (os.environ.get("CC"), "clang"):
        if name and shutil.which(name):
            return name
    return None


def runtime_object(cc: str) -> str:
    """実行時ライブラリをコンパイルしたもの(中身が変わらなければ作り直さない)"""
    with open(RUNTIME, "rb") as f:
        digest = hashlib.sha256(f.read() + cc.encode()).hexdigest()[:16]
    cache = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "suru")
    obj = os.path.join(cache, f"suru_rt-{digest}.o")
    if not os.path.exists(obj):
        os.makedirs(cache, exist_ok=True)
        tmp = f"{obj}.{os.getpid()}.tmp"
        r = subprocess.run([cc, "-O2", "-w", "-c", RUNTIME, "-o", tmp], capture_output=True, text=True)
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
                    flags += [lib, f"-Wl,-rpath,{os.path.dirname(lib)}"]
                elif lib != "c":
                    flags += _pkgconfig_link_flags(lib) + [f"-l{lib}"]
    return flags


def build(ll_path: str, out: str, opt: str = "-O2") -> None:
    cc = find_cc()
    if cc is None:
        raise S.SuruError("バイナリを作るには clang が必要です(LLVM IR だけなら --ll を付けてください)")
    cmd = [cc, opt, "-w", ll_path, runtime_object(cc), "-o", out] + link_flags(ll_path) + ["-lm", "-lpthread"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise S.SuruError("clang でのビルドに失敗しました:\n" + r.stderr)


USAGE = "使い方: python3 suru_compile.py [--ll] [--検査なし] プログラム.suru [-o 出力]"


def main(argv: list[str]) -> int:
    args = argv[1:]
    ll_only = "--ll" in args
    check = not any(a in S.NO_CHECK_FLAGS for a in args)
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
        ir = compile_source(source, base_dir, os.path.abspath(src_path), check)
        ll_path = (out if ll_only and out else stem + ".ll")
        with open(ll_path, "w", encoding="utf-8") as f:
            f.write(ir)
        if not ll_only:
            build(ll_path, out or stem)
            os.remove(ll_path)
    except S.SuruError as e:
        print(S.format_error(e, source), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    sys.exit(main(sys.argv))

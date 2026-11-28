// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"fmt"
	"strconv"
	"strings"
)

// C構造体を値で渡す・返す外部の関数(#241)。呼び出しの決まり(ABI)は OS と CPU ごとに違うので、IR では割り振らず、
// 関数ごとに小さな C の中継(suru_cs_…)を書いて、プログラムと同じ clang でコンパイルする。中継は する の値(V)を受け取り、
// C構造体にして C の関数を呼び、値を する の値にして返す。中継の C のソースは IR の頭の「; suru-cshim: 」の行に入れ、
// ビルドするときに取り出す(CShimSource)。suru_compile.py の CShim と同じものを書く

// CShimMark は IR の中の、C の中継のソースの1行の印
const CShimMark = "; suru-cshim: "

// cStructCTypes は C構造体のフィールドの C の型 → (C の型の名前, 実行時ライブラリの C_MEM の番号)
var cStructCTypes = map[string]struct {
	C   string
	Mem int
}{
	"符号付き8": {"int8_t", 0}, "符号付き16": {"int16_t", 1}, "符号付き32": {"int32_t", 2}, "符号付き64": {"int64_t", 3},
	"符号なし8": {"uint8_t", 4}, "符号なし16": {"uint16_t", 5}, "符号なし32": {"uint32_t", 6}, "符号なし64": {"uint64_t", 7},
	"単精度": {"float", 8}, "小数": {"double", 9}, "番地": {"void *", 10}, "真偽": {"uint8_t", 11},
}

// 外部の関数の引数・値の C の型(FFI の型の字 → C の型、する の値から変える関数、する の値にする式)
var cShimScalar = map[string]struct{ C, From, To string }{
	"i64":   {"int64_t", "rt_ffi_i64", "rt_ffi_from_i64(r, %s, pos)"},
	"i32":   {"int32_t", "rt_ffi_i32", "rt_ffi_from_i32(r)"},
	"f64":   {"double", "rt_ffi_f64", "rt_float(r)"},
	"f32":   {"float", "rt_ffi_f32", "rt_float((double)r)"},
	"bool":  {"int32_t", "rt_ffi_bool", "rt_ffi_from_bool(r)"},
	"str":   {"const char *", "rt_ffi_str", "rt_ffi_from_str(r)"},
	"ptr":   {"void *", "rt_ffi_ptr", "rt_ffi_from_ptr(r)"},
	"bytes": {"const uint8_t *", "rt_ffi_bytes", ""},
	"void":  {"void", "", "1"},
}

const cShimHead = `/* 「する」のコンパイラが書いた、C構造体を値で渡す外部の関数の中継(#241) */
#include <stdint.h>
typedef int64_t V;
V rt_cs_field(V, const char *, int32_t, const char *, int32_t);
void rt_cs_put(V, int32_t, void *, const char *, int32_t);
V rt_cs_get(int32_t, const void *, int32_t);
const char *rt_cs_what(const char *, const char *);
V rt_construct(const char *, int32_t, const V *, int32_t);
void rt_ffi_pre(void);
void rt_ffi_post(void);
int64_t rt_ffi_i64(V, const char *, int32_t, int32_t);
int32_t rt_ffi_i32(V, const char *, int32_t, int32_t);
double rt_ffi_f64(V, const char *, int32_t, int32_t);
float rt_ffi_f32(V, const char *, int32_t, int32_t);
int32_t rt_ffi_bool(V, const char *, int32_t, int32_t);
const char *rt_ffi_str(V, const char *, int32_t, int32_t);
void *rt_ffi_ptr(V, const char *, int32_t, int32_t);
const uint8_t *rt_ffi_bytes(V, const char *, int32_t, int32_t);
void *rt_ffi_fnptr(V, const char *, int32_t, int32_t);
V rt_ffi_from_i64(int64_t, const char *, int32_t);
V rt_ffi_from_i32(int32_t);
V rt_ffi_from_bool(int32_t);
V rt_ffi_from_str(const char *);
V rt_ffi_from_ptr(void *);
V rt_float(double);
`

type cShim struct {
	index  map[string]int // C構造体の型 → 番号(suru_cs_t番号)
	types  []string       // 構造体の定義と、する の値との行き来の関数(使う順)
	funcs  []string       // 中継の関数
	byName map[string]string
	n      int
}

// cQuote は C の文字列の書き方にする(UTF-8 はそのまま)
func cQuote(s string) string {
	var b strings.Builder
	b.WriteByte('"')
	for i := 0; i < len(s); i++ {
		ch := s[i]
		switch {
		case ch == '"' || ch == '\\':
			b.WriteByte('\\')
			b.WriteByte(ch)
		case ch < 0x20 || ch == 0x7f:
			fmt.Fprintf(&b, "\\%03o", ch)
		default:
			b.WriteByte(ch)
		}
	}
	b.WriteByte('"')
	return b.String()
}

// structType は C構造体 name の C の型の名前(なければ定義と行き来の関数を書く)
func (s *cShim) structType(name string, structs map[string][]CStructField) string {
	if s.index == nil {
		s.index = map[string]int{}
	}
	if k, ok := s.index[name]; ok {
		return fmt.Sprintf("suru_cs_t%d", k)
	}
	fields := structs[name]
	for _, f := range fields { // 入れ子を先に
		if _, ok := structs[f.CType]; ok {
			s.structType(f.CType, structs)
		}
	}
	k := len(s.index)
	s.index[name] = k
	t := fmt.Sprintf("suru_cs_t%d", k)
	var def, in, out strings.Builder
	def.WriteString("typedef struct {")
	fmt.Fprintf(&in, "static %s %s_in(V v, const char *what, int32_t pos) {\n  %s r;\n", t, t, t)
	fmt.Fprintf(&out, "static V %s_out(%s c, int32_t pos) {\n  V x[%d];\n", t, t, len(fields))
	for i, f := range fields {
		fname := cQuote(f.Name)
		if _, ok := structs[f.CType]; ok {
			inner := s.structType(f.CType, structs)
			fmt.Fprintf(&def, " %s f%d;", inner, i)
			fmt.Fprintf(&in, "  r.f%d = %s_in(rt_cs_field(v, %s, %d, what, pos), rt_cs_what(what, %s), pos);\n", i, inner, cQuote(name), i, fname)
			fmt.Fprintf(&out, "  x[%d] = %s_out(c.f%d, pos);\n", i, inner, i)
			continue
		}
		ct := cStructCTypes[f.CType]
		fmt.Fprintf(&def, " %s f%d;", ct.C, i)
		fmt.Fprintf(&in, "  rt_cs_put(rt_cs_field(v, %s, %d, what, pos), %d, &r.f%d, rt_cs_what(what, %s), pos);\n", cQuote(name), i, ct.Mem, i, fname)
		fmt.Fprintf(&out, "  x[%d] = rt_cs_get(%d, &c.f%d, pos);\n", i, ct.Mem, i)
	}
	fmt.Fprintf(&def, " } %s; /* %s */", t, strings.ReplaceAll(name, "*/", "* /"))
	in.WriteString("  return r;\n}")
	fmt.Fprintf(&out, "  return rt_construct(%s, %d, x, pos);\n}", cQuote(name), len(fields))
	s.types = append(s.types, def.String(), in.String(), out.String())
	return t
}

// cType は外部の関数の引数・値の C の型
func (s *cShim) cType(t string, structs map[string][]CStructField) string {
	if strings.HasPrefix(t, CStructFFI) {
		return s.structType(strings.TrimPrefix(t, CStructFFI), structs)
	}
	return cShimScalar[t].C
}

// function は中継の関数を書き、その名前を返す。params は定義の引数、pointer は関数の番地を持つ引数(なければ "")
func (s *cShim) function(name string, params []Param, ext *Extern) string {
	key := ext.Symbol
	if ext.Pointer != "" {
		key = ""
	}
	if s.byName == nil {
		s.byName = map[string]string{}
	}
	if fn, ok := s.byName[key]; ok && key != "" {
		return fn
	}
	s.n++
	fn := fmt.Sprintf("suru_cs_f%d", s.n)
	if key != "" {
		s.byName[key] = fn
	}
	ret := s.cType(ext.Result, ext.Structs)
	fq := cQuote(name)
	var proto, conv, cargs []string
	var vparams []string
	fptr := ""
	for i, p := range params {
		vparams = append(vparams, fmt.Sprintf("V a%d", i))
		if p.Name == ext.Pointer && ext.Pointer != "" {
			fptr = fmt.Sprintf("rt_ffi_fnptr(a%d, %s, %d, pos)", i, fq, partIDs[p.Part])
			continue
		}
		t := ext.Params[i]
		ct := s.cType(t, ext.Structs)
		proto = append(proto, ct)
		if strings.HasPrefix(t, CStructFFI) {
			what := cQuote("外部の関数「" + name + "」の「" + p.Part + "」")
			conv = append(conv, fmt.Sprintf("  %s x%d = %s_in(a%d, %s, pos);", ct, i, ct, i, what))
		} else {
			conv = append(conv, fmt.Sprintf("  %s x%d = %s(a%d, %s, %d, pos);", ct, i, cShimScalar[t].From, i, fq, partIDs[p.Part]))
		}
		cargs = append(cargs, fmt.Sprintf("x%d", i))
	}
	if ext.CArgs != nil {
		// 「外部の「f」（a と 0 と b）」: C に渡す並び
		byParam := cargs
		cargs, proto = nil, nil
		for _, a := range ext.CArgs {
			if a.IsConst {
				cargs = append(cargs, strconv.FormatInt(a.Const, 10)+"LL")
				proto = append(proto, "int64_t")
			} else {
				cargs = append(cargs, byParam[a.Param])
				proto = append(proto, s.cType(ext.Params[a.Param], ext.Structs))
			}
		}
	}
	plist := strings.Join(proto, ", ")
	if plist == "" {
		plist = "void"
	}
	var b strings.Builder
	callee := ext.Symbol
	if fptr == "" {
		fmt.Fprintf(&b, "%s %s(%s);\n", ret, ext.Symbol, plist)
	} else {
		callee = "fp"
	}
	fmt.Fprintf(&b, "V %s(%s) {\n", fn, strings.Join(append(vparams, "int32_t pos"), ", "))
	if fptr != "" {
		fmt.Fprintf(&b, "  %s (*fp)(%s) = (%s (*)(%s))%s;\n", ret, plist, ret, plist, fptr)
	}
	for _, l := range conv {
		b.WriteString(l + "\n")
	}
	b.WriteString("  rt_ffi_pre();\n")
	call := callee + "(" + strings.Join(cargs, ", ") + ")"
	switch {
	case ext.Result == "void":
		b.WriteString("  " + call + ";\n  rt_ffi_post();\n  return 1;\n}")
	case strings.HasPrefix(ext.Result, CStructFFI):
		fmt.Fprintf(&b, "  %s r = %s;\n  rt_ffi_post();\n  return %s_out(r, pos);\n}", ret, call, ret)
	default:
		to := cShimScalar[ext.Result].To
		if strings.Contains(to, "%s") {
			to = fmt.Sprintf(to, fq)
		}
		fmt.Fprintf(&b, "  %s r = %s;\n  rt_ffi_post();\n  return %s;\n}", ret, call, to)
	}
	s.funcs = append(s.funcs, b.String())
	return fn
}

// source は中継の C のソース(中継がなければ "")
func (s *cShim) source() string {
	if len(s.funcs) == 0 {
		return ""
	}
	return cShimHead + strings.Join(s.types, "\n") + "\n" + strings.Join(s.funcs, "\n") + "\n"
}

// marks は IR の頭に置く「; suru-cshim: 」の行
func (s *cShim) marks() string {
	src := s.source()
	if src == "" {
		return ""
	}
	var b strings.Builder
	for _, l := range strings.Split(strings.TrimSuffix(src, "\n"), "\n") {
		b.WriteString(CShimMark + l + "\n")
	}
	return b.String()
}

// CShimSource は IR の頭の「; suru-cshim: 」の行から、C の中継のソースを取り出す(なければ "")
func CShimSource(ir string) string {
	var b strings.Builder
	for _, line := range strings.Split(ir, "\n") {
		if !strings.HasPrefix(line, ";") {
			break
		}
		if strings.HasPrefix(line, CShimMark) {
			b.WriteString(strings.TrimPrefix(line, CShimMark) + "\n")
		}
	}
	return b.String()
}

// cStructExtern は C構造体を値で渡す外部の関数の本体: する の値のまま中継を呼ぶ
func (c *Compiler) cStructExtern(name string, params []Param, ext *Extern) genBody {
	if ext.MainThread {
		raise(ext.Line, "主スレッドで呼ぶ外部の関数「"+name+"」には、まだ C構造体を値で渡せません")
	}
	for _, lib := range ext.Libs {
		found := false
		for _, l := range c.linkLibs {
			found = found || l == lib
		}
		if !found {
			c.linkLibs = append(c.linkLibs, lib)
		}
	}
	fn := c.cshim.function(name, params, ext)
	ps := make([]string, 0, len(params)+1)
	for range params {
		ps = append(ps, "i64")
	}
	c.ffiDecls[fn] = "declare i64 @" + fn + "(" + strings.Join(append(ps, "i32"), ", ") + ")"
	fname := c.cstr(name)
	call := func(sc *scope, fg *fnGen) string {
		var args []string
		for _, p := range params {
			args = append(args, "i64 "+c.varValue(p.Name, sc, fg, ext.Line))
		}
		args = append(args, "i32 %pos")
		return fg.call("i64", "@"+fn, strings.Join(args, ", "))
	}
	if !ext.Action {
		return call
	}
	return func(sc *scope, fg *fnGen) string {
		k := c.closure(name, []Param{{Part: WO, Name: fmt.Sprintf("\x00捨てる%d", c.uid())}}, genBody(call), sc, fg, false)
		return fg.call("i64", "@rt_ffi_action", fmt.Sprintf("i64 %s, ptr %s, i32 %%pos", k, fname))
	}
}

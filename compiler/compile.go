// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics
//
// 追加の許可(GPL 第7条): このコンパイラが出力する LLVM IR・オブジェクト・実行ファイルは、
// 出力の中にこのコンパイラ由来の部分が含まれていても、GPL の対象にはなりません。
// 出力は、元にした する のプログラムの作者が好きなライセンスで配れます。

package compiler

import (
	"fmt"
	"math"
	"math/big"
	"sort"
	"strings"
)

// --- LLVM IR の生成(suru_compile.py と同じ IR を出す) ---

// ffiIR は外部の関数の C の型 → LLVM IR の型
var ffiIR = map[string]string{"i64": "i64", "f64": "double", "i32": "i32", "bool": "i32", "str": "ptr", "ptr": "ptr", "bytes": "ptr",
	"void": "void"}

// LinkMark は IR の中の、リンクするライブラリの印(ビルドで読む)
const LinkMark = "; suru-link: "

var partIDs = map[string]int{"を": 0, "に": 1, "で": 2, "から": 3, "へ": 4, "より": 5, "が": 6}
var opIDs = map[string]int{"+": 0, "-": 1, "*": 2, "/": 3, "%": 4, "^": 5, "<": 6, ">": 7, "<=": 8, ">=": 9, "==": 10, "!=": 11}

var intMax = new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 62), big.NewInt(1))
var intMin = new(big.Int).Neg(new(big.Int).Lsh(big.NewInt(1), 62))

const decls = `
declare ptr @rt_alloc(i64)
declare i64 @rt_ffi_i64(i64, ptr, i32, i32)
declare i32 @rt_ffi_i32(i64, ptr, i32, i32)
declare double @rt_ffi_f64(i64, ptr, i32, i32)
declare i32 @rt_ffi_bool(i64, ptr, i32, i32)
declare ptr @rt_ffi_str(i64, ptr, i32, i32)
declare ptr @rt_ffi_ptr(i64, ptr, i32, i32)
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
declare {i64, i1} @llvm.sadd.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.ssub.with.overflow.i64(i64, i64)
declare {i64, i1} @llvm.smul.with.overflow.i64(i64, i64)
`

func compileError(msg string) { panic(&SuruError{Message: msg}) }

func posOf(p Pos) int {
	col := p.Col
	if col > 0x7FF {
		col = 0x7FF
	}
	return p.Line | (col << 20)
}

func irBytes(data string) string {
	var b strings.Builder
	for i := 0; i < len(data); i++ {
		c := data[i]
		if c >= 0x20 && c < 0x7F && c != 0x22 && c != 0x5C {
			b.WriteByte(c)
		} else {
			fmt.Fprintf(&b, "\\%02X", c)
		}
	}
	return b.String()
}

func doubleBits(x float64) uint64 {
	if math.IsNaN(x) {
		// Python の float('nan') と同じビット
		if math.Signbit(x) {
			return 0xFFF8000000000000
		}
		return 0x7FF8000000000000
	}
	return math.Float64bits(x)
}

func doubleHex(x float64) string { return fmt.Sprintf("0x%016X", doubleBits(x)) }

// --- 名前の結びつき ---

type fnInfo struct {
	name    string
	order   []string
	direct  string
	wrapper string
}

type binding struct {
	kind  string // slot / lfn / gfn / gval / gconst
	owner *fnGen
	slot  int
	lazy  bool
	info  *fnInfo
	g     string
}

type scope struct {
	parent *scope
	fg     *fnGen
	vars   map[string]*binding
	order  []string
}

func newScope(parent *scope, fg *fnGen) *scope {
	return &scope{parent: parent, fg: fg, vars: map[string]*binding{}}
}

func (s *scope) set(name string, b *binding) {
	if _, ok := s.vars[name]; !ok {
		s.order = append(s.order, name)
	}
	s.vars[name] = b
}

func (s *scope) lookup(name string) *binding {
	for x := s; x != nil; x = x.parent {
		if b, ok := x.vars[name]; ok {
			return b
		}
	}
	return nil
}

type fnGen struct {
	cg      *Compiler
	parent  *fnGen
	lines   []string
	entry   []string
	n       int
	nslots  int
	escapes bool
	label   string
}

func newFnGen(cg *Compiler, parent *fnGen) *fnGen {
	return &fnGen{cg: cg, parent: parent, nslots: 1, label: "b0", lines: []string{"b0:"}}
}

func (f *fnGen) tmp() string {
	f.n++
	return fmt.Sprintf("%%t%d", f.n)
}

func (f *fnGen) newLabel() string {
	f.n++
	return fmt.Sprintf("L%d", f.n)
}

func (f *fnGen) emit(line string) { f.lines = append(f.lines, "  "+line) }

func (f *fnGen) start(label string) {
	f.lines = append(f.lines, label+":")
	f.label = label
}

func (f *fnGen) call(ret, fn, args string) string {
	if ret == "void" {
		f.emit("call void " + fn + "(" + args + ")")
		return ""
	}
	t := f.tmp()
	f.emit(t + " = call " + ret + " " + fn + "(" + args + ")")
	return t
}

func (f *fnGen) newSlot() int {
	k := f.nslots
	f.nslots++
	return k
}

func (f *fnGen) array(values []string) string {
	if len(values) == 0 {
		return "null"
	}
	f.n++
	arr := fmt.Sprintf("%%arr%d", f.n)
	f.entry = append(f.entry, fmt.Sprintf("  %s = alloca i64, i32 %d", arr, len(values)))
	for i, v := range values {
		p := f.tmp()
		f.emit(fmt.Sprintf("%s = getelementptr i64, ptr %s, i64 %d", p, arr, i))
		f.emit(fmt.Sprintf("store i64 %s, ptr %s", v, p))
	}
	return arr
}

func (f *fnGen) frameOf(owner *fnGen) string {
	p, g := "%fr", f
	for g != owner {
		t := f.tmp()
		f.emit(t + " = load ptr, ptr " + p)
		p, g = t, g.parent
		if g == nil {
			compileError("内部エラー: フレームが見つかりません")
		}
	}
	return p
}

func (f *fnGen) storeSlot(k int, v string) {
	p := f.tmp()
	f.emit(fmt.Sprintf("%s = getelementptr i64, ptr %%fr, i64 %d", p, k))
	f.emit(fmt.Sprintf("store i64 %s, ptr %s", v, p))
}

func (f *fnGen) loadSlot(owner *fnGen, k int) string {
	fr := f.frameOf(owner)
	p := f.tmp()
	f.emit(fmt.Sprintf("%s = getelementptr i64, ptr %s, i64 %d", p, fr, k))
	t := f.tmp()
	f.emit(fmt.Sprintf("%s = load i64, ptr %s", t, p))
	return t
}

func (f *fnGen) finish(header string) string {
	var b strings.Builder
	size := len(header) + 128
	for _, e := range f.entry {
		size += len(e) + 1
	}
	for _, l := range f.lines {
		size += len(l) + 1
	}
	b.Grow(size)
	b.WriteString(header + " {\nentry:")
	for _, e := range f.entry {
		b.WriteString("\n" + e)
	}
	if f.escapes {
		fmt.Fprintf(&b, "\n  %%fr = call ptr @rt_alloc(i64 %d)", f.nslots*8)
	} else {
		fmt.Fprintf(&b, "\n  %%fr = alloca i64, i32 %d", f.nslots)
	}
	b.WriteString("\n  store ptr %up, ptr %fr\n  br label %b0")
	for _, l := range f.lines {
		b.WriteString("\n" + l)
	}
	b.WriteString("\n}")
	return b.String()
}

// --- コンパイラ ---

type Compiler struct {
	ctx         *ParseContext
	source      string
	globals     []string
	functions   []string
	consts      []string
	cstrings    map[string]string
	partArrays  map[string]string
	ptrArrays   map[string]string
	strValues   map[string]string
	floatValues map[uint64]string
	globalCache map[string]string
	n           int
	modules     map[string]*scope
	initFg      *fnGen
	ffiDecls    map[string]string // 外部の関数の名前 → declare の行
	linkLibs    []string          // リンクするライブラリ(ExternLib.Path)
}

func newCompiler(ctx *ParseContext, source string) *Compiler {
	return &Compiler{ctx: ctx, source: source, cstrings: map[string]string{}, partArrays: map[string]string{},
		ptrArrays: map[string]string{}, strValues: map[string]string{}, floatValues: map[uint64]string{},
		globalCache: map[string]string{}, modules: map[string]*scope{}, ffiDecls: map[string]string{}}
}

func (c *Compiler) uid() int {
	c.n++
	return c.n
}

func (c *Compiler) cstr(s string) string {
	if name, ok := c.cstrings[s]; ok {
		return name
	}
	name := fmt.Sprintf("@s.%d", c.uid())
	c.globals = append(c.globals, fmt.Sprintf(`%s = private unnamed_addr constant [%d x i8] c"%s\00"`, name, len(s)+1, irBytes(s)))
	c.cstrings[s] = name
	return name
}

func (c *Compiler) parts(parts []string) string {
	if len(parts) == 0 {
		return "null"
	}
	ids := make([]string, len(parts))
	for i, p := range parts {
		ids[i] = fmt.Sprintf("i32 %d", partIDs[p])
	}
	key := strings.Join(ids, ", ")
	if name, ok := c.partArrays[key]; ok {
		return name
	}
	name := fmt.Sprintf("@p.%d", c.uid())
	c.globals = append(c.globals, fmt.Sprintf("%s = private unnamed_addr constant [%d x i32] [%s]", name, len(parts), key))
	c.partArrays[key] = name
	return name
}

func (c *Compiler) ptrs(names []string) string {
	if len(names) == 0 {
		return "null"
	}
	key := strings.Join(names, "\x00\x01")
	if name, ok := c.ptrArrays[key]; ok {
		return name
	}
	name := fmt.Sprintf("@n.%d", c.uid())
	items := make([]string, len(names))
	for i, x := range names {
		items[i] = "ptr " + c.cstr(x)
	}
	c.globals = append(c.globals, fmt.Sprintf("%s = private unnamed_addr constant [%d x ptr] [%s]", name, len(names), strings.Join(items, ", ")))
	c.ptrArrays[key] = name
	return name
}

func (c *Compiler) newGlobal(prefix string) string {
	name := fmt.Sprintf("@%s.%d", prefix, c.uid())
	c.globals = append(c.globals, name+" = internal global i64 0")
	return name
}

func (c *Compiler) strValue(s string) string {
	if g, ok := c.strValues[s]; ok {
		return g
	}
	g := c.newGlobal("sv")
	c.consts = append(c.consts, fmt.Sprintf("  %%c%s = call i64 @rt_str(ptr %s, i64 %d)", g[1:], c.cstr(s), len(s)))
	c.consts = append(c.consts, fmt.Sprintf("  store i64 %%c%s, ptr %s", g[1:], g))
	c.strValues[s] = g
	return g
}

func (c *Compiler) floatValue(x float64) string {
	key := doubleBits(x)
	if g, ok := c.floatValues[key]; ok {
		return g
	}
	g := c.newGlobal("fv")
	c.consts = append(c.consts, fmt.Sprintf("  %%c%s = call i64 @rt_float(double %s)", g[1:], doubleHex(x)))
	c.consts = append(c.consts, fmt.Sprintf("  store i64 %%c%s, ptr %s", g[1:], g))
	c.floatValues[key] = g
	return g
}

func typeNameOf(n Node) string {
	t := fmt.Sprintf("%T", n)
	return strings.TrimPrefix(t, "*compiler.")
}

func (c *Compiler) ex(node Node, sc *scope, fg *fnGen) string {
	switch n := node.(type) {
	case *Num:
		return c.exNum(n, fg)
	case *Str:
		return c.loadGlobal(c.strValue(n.Value), fg)
	case *Var:
		return c.varValue(n.Name, sc, fg, n.Line)
	case *ListLit:
		vals := c.exAll(n.Items, sc, fg)
		arr := fg.array(vals)
		return fg.call("i64", "@rt_list", fmt.Sprintf("i64 %d, ptr %s", len(vals), arr))
	case *Prop:
		t := c.ex(n.Target, sc, fg)
		return fg.call("i64", "@rt_prop", fmt.Sprintf("i64 %s, ptr %s, i32 %d", t, c.cstr(n.Name), posOf(n.Line)))
	case *Field:
		t := c.ex(n.Target, sc, fg)
		if n.Name == Result {
			return fg.call("i64", "@rt_field_result", fmt.Sprintf("i64 %s, i32 %d", t, posOf(n.Line)))
		}
		return fg.call("i64", "@rt_field", fmt.Sprintf("i64 %s, ptr %s, i32 %d", t, c.cstr(n.Name), posOf(n.Line)))
	case *Each:
		t := c.ex(n.Target, sc, fg)
		return fg.call("i64", "@rt_each_check", fmt.Sprintf("i64 %s, i32 %d", t, posOf(n.Line)))
	case *Neg:
		t := c.ex(n.Operand, sc, fg)
		return fg.call("i64", "@rt_neg", fmt.Sprintf("i64 %s, i32 0", t))
	case *Not:
		t := c.ex(n.Operand, sc, fg)
		b := fg.call("i32", "@rt_truth", fmt.Sprintf("i64 %s, ptr %s, i32 %d", t, c.cstr(Denai), posOf(lineOf(n.Operand))))
		x := fg.tmp()
		fg.emit(x + " = xor i32 " + b + ", 1")
		return fg.call("i64", "@rt_bool", "i32 "+x)
	case *BinOp:
		return c.exBinOp(n, sc, fg)
	case *If:
		return c.exIf(n, sc, fg)
	case *Call:
		return c.exCall(n, sc, fg)
	case *Ref:
		fn := c.varValue(n.Name, sc, fg, n.Line)
		vals := c.exAll(argNodes(n.Args), sc, fg)
		arr := fg.array(vals)
		return fg.call("i64", "@rt_ref", fmt.Sprintf("i64 %s, i32 %d, ptr %s, ptr %s, ptr %s, i32 %d",
			fn, len(vals), c.parts(n.Args.Parts()), arr, c.cstr(n.Name), posOf(n.Line)))
	case *Lambda:
		return c.closure("無名関数", n.Params, exprBody{n.Body}, sc, fg, true)
	case *Block:
		local := newScope(sc, fg)
		var defs []*Define
		for _, s := range n.Statements {
			if d, ok := s.(*Define); ok {
				defs = append(defs, d)
			}
		}
		c.localDefines(defs, local, fg)
		result := "0"
		for _, s := range n.Statements {
			if _, ok := s.(*Define); !ok {
				result = c.ex(s, local, fg)
			}
		}
		return result
	case *Construct:
		vals := c.exAll(n.Items, sc, fg)
		arr := fg.array(vals)
		return fg.call("i64", "@rt_construct", fmt.Sprintf("ptr %s, i32 %d, ptr %s, i32 %d", c.cstr(n.Ctor), len(vals), arr, posOf(n.Line)))
	case *NamedConstruct:
		return c.exNamedConstruct(n, sc, fg)
	case *Update:
		t := c.ex(n.Target, sc, fg)
		var names []string
		var es []Node
		for _, f := range n.Fields {
			names = append(names, f.Name)
			es = append(es, f.Value)
		}
		vals := c.exAll(es, sc, fg)
		arr := fg.array(vals)
		return fg.call("i64", "@rt_update", fmt.Sprintf("i64 %s, i32 %d, ptr %s, ptr %s, i32 %d", t, len(vals), c.ptrs(names), arr, posOf(n.Line)))
	case *Match:
		return c.exMatch(n, sc, fg)
	case *Chain:
		m := c.ex(n.Call, sc, fg)
		k := c.closure("続き", []Param{{Part: WO, Name: Hole}}, exprBody{n.Cont}, sc, fg, false)
		return fg.call("i64", "@rt_chain_then", fmt.Sprintf("i64 %s, i64 %s, i32 %d", m, k, posOf(n.Line)))
	case *Run:
		key := runKey(n)
		if sc.lookup(key) == nil {
			fg.call("void", "@rt_run_outside", fmt.Sprintf("i32 %d", posOf(n.Line)))
			fg.emit("unreachable")
			fg.start(fg.newLabel())
			return "0"
		}
		return c.varValue(key, sc, fg, n.Line)
	case *Do:
		v := c.do(n.Statements, 0, newScope(sc, fg), fg, n.Line)
		return fg.call("i64", "@rt_do_result", "i64 "+v)
	}
	compileError(fmt.Sprintf("この書き方はまだコンパイルできません(%s)", typeNameOf(node)))
	return ""
}

func (c *Compiler) exAll(ns []Node, sc *scope, fg *fnGen) []string {
	out := make([]string, len(ns))
	for i, x := range ns {
		out[i] = c.ex(x, sc, fg)
	}
	return out
}

func (c *Compiler) exNum(n *Num, fg *fnGen) string {
	v := n.Value
	switch v.Kind {
	case NBool:
		b := 0
		if v.B {
			b = 1
		}
		return fg.call("i64", "@rt_bool", fmt.Sprintf("i32 %d", b))
	case NEmpty:
		return fg.call("i64", "@rt_list", "i64 0, ptr null")
	case NInt:
		if v.I.Cmp(intMin) < 0 || v.I.Cmp(intMax) > 0 {
			compileError(fmt.Sprintf("整数 %s は大きすぎます(コンパイルしたプログラムの整数は ±%s までです)", v.I.String(), intMax.String()))
		}
		r := new(big.Int).Lsh(v.I, 1)
		r.Or(r, big.NewInt(1))
		return r.String()
	}
	return c.loadGlobal(c.floatValue(v.F), fg)
}

func (c *Compiler) loadGlobal(g string, fg *fnGen) string {
	t := fg.tmp()
	fg.emit(t + " = load i64, ptr " + g)
	return t
}

func (c *Compiler) varValue(name string, sc *scope, fg *fnGen, line Pos) string {
	b := sc.lookup(name)
	if b == nil {
		g, ok := c.globalCache[name]
		if !ok {
			g = c.newGlobal("gc")
			c.globalCache[name] = g
		}
		return fg.call("i64", "@rt_global_cached", fmt.Sprintf("ptr %s, ptr %s, i32 %d", g, c.cstr(name), posOf(line)))
	}
	switch b.kind {
	case "slot", "lfn":
		v := fg.loadSlot(b.owner, b.slot)
		if b.lazy {
			v = fg.call("i64", "@rt_force", "i64 "+v)
		}
		return v
	case "gval":
		v := c.loadGlobal(b.g, fg)
		return fg.call("i64", "@rt_force", "i64 "+v)
	}
	return c.loadGlobal(b.g, fg)
}

func (c *Compiler) exBinOp(n *BinOp, sc *scope, fg *fnGen) string {
	if n.Op == KwKatsu || n.Op == KwMataha {
		return c.logic(n, sc, fg)
	}
	a := c.ex(n.Left, sc, fg)
	b := c.ex(n.Right, sc, fg)
	op := opIDs[n.Op]
	pos := posOf(n.Line)
	switch n.Op {
	case "+", "-", "*", "<", ">", "<=", ">=", "==", "!=":
	default:
		return fg.call("i64", "@rt_binop", fmt.Sprintf("i32 %d, i64 %s, i64 %s, i32 %d", op, a, b, pos))
	}
	both, fast, slow, join := fg.tmp(), fg.newLabel(), fg.newLabel(), fg.newLabel()
	x, cc := fg.tmp(), fg.tmp()
	fg.emit(fmt.Sprintf("%s = and i64 %s, %s", x, a, b))
	fg.emit(fmt.Sprintf("%s = and i64 %s, 1", both, x))
	fg.emit(fmt.Sprintf("%s = icmp ne i64 %s, 0", cc, both))
	fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", cc, fast, slow))
	fg.start(fast)
	var fastVal, fastLabel string
	if n.Op == "+" || n.Op == "-" || n.Op == "*" {
		var r string
		switch n.Op {
		case "+", "-":
			y := fg.tmp()
			fg.emit(fmt.Sprintf("%s = sub i64 %s, 1", y, b))
			r = fg.tmp()
			fn := "sadd"
			if n.Op == "-" {
				fn = "ssub"
			}
			fg.emit(fmt.Sprintf("%s = call {i64, i1} @llvm.%s.with.overflow.i64(i64 %s, i64 %s)", r, fn, a, y))
		default:
			xa, yb := fg.tmp(), fg.tmp()
			fg.emit(fmt.Sprintf("%s = sub i64 %s, 1", xa, a))
			fg.emit(fmt.Sprintf("%s = ashr i64 %s, 1", yb, b))
			r = fg.tmp()
			fg.emit(fmt.Sprintf("%s = call {i64, i1} @llvm.smul.with.overflow.i64(i64 %s, i64 %s)", r, xa, yb))
		}
		val, ovf := fg.tmp(), fg.tmp()
		fg.emit(fmt.Sprintf("%s = extractvalue {i64, i1} %s, 0", val, r))
		fg.emit(fmt.Sprintf("%s = extractvalue {i64, i1} %s, 1", ovf, r))
		if n.Op == "*" {
			v2 := fg.tmp()
			fg.emit(fmt.Sprintf("%s = or i64 %s, 1", v2, val))
			val = v2
		}
		ok := fg.newLabel()
		fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", ovf, slow, ok))
		fg.start(ok)
		fastVal, fastLabel = val, ok
	} else {
		pred := map[string]string{"<": "slt", ">": "sgt", "<=": "sle", ">=": "sge", "==": "eq", "!=": "ne"}[n.Op]
		cmp, z := fg.tmp(), fg.tmp()
		fg.emit(fmt.Sprintf("%s = icmp %s i64 %s, %s", cmp, pred, a, b))
		fg.emit(fmt.Sprintf("%s = zext i1 %s to i32", z, cmp))
		fastVal = fg.call("i64", "@rt_bool", "i32 "+z)
		fastLabel = fg.label
	}
	fg.emit("br label %" + join)
	fg.start(slow)
	slowVal := fg.call("i64", "@rt_binop", fmt.Sprintf("i32 %d, i64 %s, i64 %s, i32 %d", op, a, b, pos))
	fg.emit("br label %" + join)
	fg.start(join)
	res := fg.tmp()
	fg.emit(fmt.Sprintf("%s = phi i64 [%s, %%%s], [%s, %%%s]", res, fastVal, fastLabel, slowVal, slow))
	return res
}

func (c *Compiler) logic(n *BinOp, sc *scope, fg *fnGen) string {
	what := c.cstr(n.Op)
	a := c.ex(n.Left, sc, fg)
	ta := fg.call("i32", "@rt_truth", fmt.Sprintf("i64 %s, ptr %s, i32 %d", a, what, posOf(lineOf(n.Left))))
	cc := fg.tmp()
	stopOn := 0
	if n.Op == KwMataha {
		stopOn = 1
	}
	fg.emit(fmt.Sprintf("%s = icmp eq i32 %s, %d", cc, ta, stopOn))
	done, right, join := fg.newLabel(), fg.newLabel(), fg.newLabel()
	fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", cc, done, right))
	fg.start(done)
	v1 := fg.call("i64", "@rt_bool", fmt.Sprintf("i32 %d", stopOn))
	fg.emit("br label %" + join)
	fg.start(right)
	b := c.ex(n.Right, sc, fg)
	tb := fg.call("i32", "@rt_truth", fmt.Sprintf("i64 %s, ptr %s, i32 %d", b, what, posOf(lineOf(n.Right))))
	v2 := fg.call("i64", "@rt_bool", "i32 "+tb)
	l2 := fg.label
	fg.emit("br label %" + join)
	fg.start(join)
	r := fg.tmp()
	fg.emit(fmt.Sprintf("%s = phi i64 [%s, %%%s], [%s, %%%s]", r, v1, done, v2, l2))
	return r
}

func (c *Compiler) exIf(n *If, sc *scope, fg *fnGen) string {
	cv := c.ex(n.Cond, sc, fg)
	t := fg.call("i32", "@rt_truthy", "i64 "+cv)
	b := fg.tmp()
	fg.emit(fmt.Sprintf("%s = icmp ne i32 %s, 0", b, t))
	lt, le, lj := fg.newLabel(), fg.newLabel(), fg.newLabel()
	fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", b, lt, le))
	fg.start(lt)
	v1 := c.ex(n.Then, sc, fg)
	l1 := fg.label
	fg.emit("br label %" + lj)
	fg.start(le)
	v2 := c.ex(n.Other, sc, fg)
	l2 := fg.label
	fg.emit("br label %" + lj)
	fg.start(lj)
	r := fg.tmp()
	fg.emit(fmt.Sprintf("%s = phi i64 [%s, %%%s], [%s, %%%s]", r, v1, l1, v2, l2))
	return r
}

func (c *Compiler) callArgs(args Args, sc *scope, fg *fnGen) ([]string, []string, []int) {
	var parts, vals []string
	var flags []int
	for _, a := range args {
		parts = append(parts, a.Part)
		if f, ok := a.Value.(*Field); ok && f.Name == Result {
			vals = append(vals, c.ex(f.Target, sc, fg))
			flags = append(flags, 2)
		} else if _, ok := a.Value.(*Each); ok {
			vals = append(vals, c.ex(a.Value, sc, fg))
			flags = append(flags, 1)
		} else {
			vals = append(vals, c.ex(a.Value, sc, fg))
			flags = append(flags, 0)
		}
	}
	return parts, vals, flags
}

func (c *Compiler) exCall(n *Call, sc *scope, fg *fnGen) string {
	b := sc.lookup(n.Name)
	parts, vals, flags := c.callArgs(n.Args, sc, fg)
	anyFlag := false
	for _, f := range flags {
		if f != 0 {
			anyFlag = true
		}
	}
	pos := posOf(n.Line)
	if b != nil && (b.kind == "gfn" || b.kind == "lfn") && !anyFlag && eqStrings(sortedParts(parts), sortedParts(b.info.order)) {
		byPart := map[string]string{}
		for i, p := range parts {
			byPart[p] = vals[i]
		}
		up := "null"
		if b.kind != "gfn" {
			up = fg.frameOf(b.owner)
		}
		as := []string{"ptr " + up}
		for _, p := range b.info.order {
			as = append(as, "i64 "+byPart[p])
		}
		as = append(as, fmt.Sprintf("i32 %d", pos))
		return fg.call("i64", b.info.direct, strings.Join(as, ", "))
	}
	fn := c.varValue(n.Name, sc, fg, n.Line)
	arr := fg.array(vals)
	pa := c.parts(parts)
	if anyFlag {
		fl := fmt.Sprintf("@fl.%d", c.uid())
		fs := make([]string, len(flags))
		for i, x := range flags {
			fs[i] = fmt.Sprintf("i32 %d", x)
		}
		c.globals = append(c.globals, fmt.Sprintf("%s = private unnamed_addr constant [%d x i32] [%s]", fl, len(flags), strings.Join(fs, ", ")))
		return fg.call("i64", "@rt_call_ex", fmt.Sprintf("i64 %s, i32 %d, ptr %s, ptr %s, ptr %s, i32 %d", fn, len(vals), pa, arr, fl, pos))
	}
	return fg.call("i64", "@rt_call", fmt.Sprintf("i64 %s, i32 %d, ptr %s, ptr %s, i32 %d", fn, len(vals), pa, arr, pos))
}

// fnBody は関数の本体(式か、IR を作る関数)
type fnBody interface{}
type exprBody struct{ node Node }
type genBody func(local *scope, fg *fnGen) string

func (c *Compiler) genFunction(name string, params []Param, body fnBody, sc *scope, parent *fnGen, info *fnInfo, checkPred bool) {
	fg := newFnGen(c, parent)
	local := newScope(sc, fg)
	argnames := make([]string, len(params))
	for i := range params {
		argnames[i] = fmt.Sprintf("%%a%d", i)
	}
	for i, p := range params {
		a := argnames[i]
		if !p.List {
			k := fg.newSlot()
			fg.storeSlot(k, a)
			local.set(p.Name, &binding{kind: "slot", owner: fg, slot: k})
		} else {
			seq := fg.call("i64", "@rt_bind_seq", fmt.Sprintf("i64 %s, i64 %d, i32 %d, ptr %s, i32 %%pos", a, len(p.Names), partIDs[p.Part], c.cstr(name)))
			for j, x := range p.Names {
				v := fg.call("i64", "@rt_list_at", fmt.Sprintf("i64 %s, i64 %d", seq, j))
				k := fg.newSlot()
				fg.storeSlot(k, v)
				local.set(x, &binding{kind: "slot", owner: fg, slot: k})
			}
		}
	}
	if eb, ok := body.(exprBody); ok {
		if ext, ok := eb.node.(*Extern); ok {
			body = c.externBody(name, params, ext)
		}
	}
	var r string
	switch b := body.(type) {
	case genBody:
		r = b(local, fg)
	case exprBody:
		r = c.ex(b.node, local, fg)
	}
	if checkPred && isPredicate(name) {
		r = fg.call("i64", "@rt_pred_check", fmt.Sprintf("i64 %s, ptr %s, i32 %%pos", r, c.cstr(name)))
	}
	fg.emit("ret i64 " + r)
	var hb strings.Builder
	hb.WriteString("define internal i64 " + info.direct + "(ptr %up, ")
	for _, a := range argnames {
		hb.WriteString("i64 " + a + ", ")
	}
	hb.WriteString("i32 %pos)")
	c.functions = append(c.functions, fg.finish(hb.String()))
	w := []string{"define internal i64 " + info.wrapper + "(ptr %up, ptr %args, i32 %pos) {", "entry:"}
	var loads strings.Builder
	for i := range params {
		w = append(w, fmt.Sprintf("  %%p%d = getelementptr i64, ptr %%args, i64 %d", i, i))
		w = append(w, fmt.Sprintf("  %%v%d = load i64, ptr %%p%d", i, i))
		fmt.Fprintf(&loads, "i64 %%v%d, ", i)
	}
	w = append(w, fmt.Sprintf("  %%r = call i64 %s(ptr %%up, %si32 %%pos)", info.direct, loads.String()))
	w = append(w, "  ret i64 %r", "}")
	c.functions = append(c.functions, strings.Join(w, "\n"))
}

// externBody は外部の関数の本体: 引数を C の値にして呼び、値を戻す。値が動作なら、行ったときに呼ぶ動作を返す
func (c *Compiler) externBody(name string, params []Param, ext *Extern) genBody {
	for _, lib := range ext.Libs {
		found := false
		for _, l := range c.linkLibs {
			found = found || l == lib
		}
		if !found {
			c.linkLibs = append(c.linkLibs, lib)
		}
	}
	ret := ffiIR[ext.Result]
	ps := make([]string, len(ext.Params))
	for i, t := range ext.Params {
		ps[i] = ffiIR[t]
	}
	decl := "declare " + ret + " @" + ext.Symbol + "(" + strings.Join(ps, ", ") + ")"
	if prev, ok := c.ffiDecls[ext.Symbol]; ok && prev != decl {
		raise(ext.Line, "外部の関数「"+ext.Symbol+"」が違う型で2回宣言されています")
	}
	c.ffiDecls[ext.Symbol] = decl
	fname := c.cstr(name)
	call := func(sc *scope, fg *fnGen) string {
		args := make([]string, len(params))
		for i, p := range params {
			t := ext.Params[i]
			v := c.varValue(p.Name, sc, fg, ext.Line)
			cv := fg.call(ffiIR[t], "@rt_ffi_"+t, fmt.Sprintf("i64 %s, ptr %s, i32 %d, i32 %%pos", v, fname, partIDs[p.Part]))
			args[i] = ffiIR[t] + " " + cv
		}
		fg.call("void", "@rt_ffi_pre", "")
		r := fg.call(ret, "@"+ext.Symbol, strings.Join(args, ", "))
		fg.call("void", "@rt_ffi_post", "")
		switch ext.Result {
		case "void":
			return "1" // 数の 0
		case "i64":
			return fg.call("i64", "@rt_ffi_from_i64", fmt.Sprintf("i64 %s, ptr %s, i32 %%pos", r, fname))
		case "f64":
			return fg.call("i64", "@rt_float", "double "+r)
		}
		return fg.call("i64", "@rt_ffi_from_"+ext.Result, ret+" "+r)
	}
	if !ext.Action {
		return call
	}
	return func(sc *scope, fg *fnGen) string {
		k := c.closure(name, []Param{{Part: WO, Name: fmt.Sprintf("\x00捨てる%d", c.uid())}}, genBody(call), sc, fg, false)
		return fg.call("i64", "@rt_ffi_action", fmt.Sprintf("i64 %s, ptr %s, i32 %%pos", k, fname))
	}
}

func (c *Compiler) newInfo(name string, params []Param) *fnInfo {
	k := c.uid()
	return &fnInfo{name, paramParts(params), fmt.Sprintf("@f.%d", k), fmt.Sprintf("@g.%d", k)}
}

func (c *Compiler) makeFnValue(info *fnInfo, fg *fnGen, up string) string {
	return fg.call("i64", "@rt_make_fn", fmt.Sprintf("ptr %s, i32 %d, ptr %s, ptr %s, ptr %s",
		c.cstr(info.name), len(info.order), c.parts(info.order), info.wrapper, up))
}

func (c *Compiler) closure(name string, params []Param, body fnBody, sc *scope, fg *fnGen, checkPred bool) string {
	info := c.newInfo(name, params)
	c.genFunction(name, params, body, sc, fg, info, checkPred)
	fg.escapes = true
	return c.makeFnValue(info, fg, "%fr")
}

func (c *Compiler) thunk(body Node, sc *scope, parent *fnGen) string {
	fg := newFnGen(c, parent)
	r := c.ex(body, newScope(sc, fg), fg)
	fg.emit("ret i64 " + r)
	name := fmt.Sprintf("@z.%d", c.uid())
	c.functions = append(c.functions, fg.finish("define internal i64 "+name+"(ptr %up, ptr %args, i32 %pos)"))
	return name
}

func (c *Compiler) localDefines(defines []*Define, sc *scope, fg *fnGen) {
	for _, d := range defines {
		k := fg.newSlot()
		if d.IsFunction {
			info := c.newInfo(d.Name, d.Params)
			sc.set(d.Name, &binding{kind: "lfn", owner: fg, slot: k, info: info})
		} else {
			sc.set(d.Name, &binding{kind: "slot", owner: fg, slot: k, lazy: true})
		}
	}
	for _, d := range defines {
		b := sc.vars[d.Name]
		var v string
		if d.IsFunction {
			c.genFunction(d.Name, d.Params, exprBody{d.Body}, sc, fg, b.info, true)
			fg.escapes = true
			v = c.makeFnValue(b.info, fg, "%fr")
		} else {
			z := c.thunk(d.Body, sc, fg)
			fg.escapes = true
			v = fg.call("i64", "@rt_lazy", fmt.Sprintf("ptr %s, ptr %%fr", z))
		}
		fg.storeSlot(b.slot, v)
	}
}

func (c *Compiler) fail(msg string, line Pos, fg *fnGen) string {
	fg.call("void", "@rt_fail", fmt.Sprintf("ptr %s, i32 %d", c.cstr(msg), posOf(line)))
	fg.emit("unreachable")
	fg.start(fg.newLabel())
	return "0"
}

func (c *Compiler) exNamedConstruct(n *NamedConstruct, sc *scope, fg *fnGen) string {
	info, _ := c.ctx.Ctors.Get(n.Ctor)
	given := map[string]Node{}
	for _, f := range n.Fields {
		given[f.Name] = f.Value
	}
	for _, f := range n.Fields {
		if !contains(info.Fields, f.Name) {
			return c.fail("「"+n.Ctor+"」には「"+f.Name+"」というフィールドがありません", n.Line, fg)
		}
	}
	for _, f := range info.Fields {
		if _, ok := given[f]; !ok {
			return c.fail("「"+n.Ctor+"」の「"+f+"」が書かれていません", n.Line, fg)
		}
	}
	var es []Node
	for _, f := range info.Fields {
		es = append(es, given[f])
	}
	vals := c.exAll(es, sc, fg)
	arr := fg.array(vals)
	return fg.call("i64", "@rt_construct", fmt.Sprintf("ptr %s, i32 %d, ptr %s, i32 %d", c.cstr(n.Ctor), len(vals), arr, posOf(n.Line)))
}

func (c *Compiler) pattern(pat Node, v, fail string, sc *scope, fg *fnGen) {
	check := func(cond string) {
		cc := fg.tmp()
		fg.emit(fmt.Sprintf("%s = icmp ne i32 %s, 0", cc, cond))
		ok := fg.newLabel()
		fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", cc, ok, fail))
		fg.start(ok)
	}
	switch p := pat.(type) {
	case *PBind:
		k := fg.newSlot()
		fg.storeSlot(k, v)
		sc.set(p.Name, &binding{kind: "slot", owner: fg, slot: k})
	case *PValue:
		e := c.ex(p.Expr, sc, fg)
		check(fg.call("i32", "@rt_eq", fmt.Sprintf("i64 %s, i64 %s", e, v)))
	case *PSeq:
		check(fg.call("i32", "@rt_is_list_len", fmt.Sprintf("i64 %s, i64 %d", v, len(p.Items))))
		for i, q := range p.Items {
			x := fg.call("i64", "@rt_list_at", fmt.Sprintf("i64 %s, i64 %d", v, i))
			c.pattern(q, x, fail, sc, fg)
		}
	case *PCtor:
		check(fg.call("i32", "@rt_is_ctor", fmt.Sprintf("i64 %s, ptr %s", v, c.cstr(p.Ctor))))
		nfields := len(p.Items)
		if info, ok := c.ctx.Ctors.Get(p.Ctor); ok {
			nfields = len(info.Fields)
		}
		items := p.Items
		if nfields < len(items) {
			items = items[:nfields]
		}
		for i, q := range items {
			x := fg.call("i64", "@rt_rec_at", fmt.Sprintf("i64 %s, i64 %d", v, i))
			c.pattern(q, x, fail, sc, fg)
		}
	case *PNamed:
		if p.HasCtor {
			check(fg.call("i32", "@rt_is_ctor", fmt.Sprintf("i64 %s, ptr %s", v, c.cstr(p.Ctor))))
		}
		for _, f := range p.Fields {
			x := fg.call("i64", "@rt_named_get", fmt.Sprintf("i64 %s, ptr %s", v, c.cstr(f.Name)))
			cc := fg.tmp()
			fg.emit(fmt.Sprintf("%s = icmp ne i64 %s, 0", cc, x))
			ok := fg.newLabel()
			fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", cc, ok, fail))
			fg.start(ok)
			c.pattern(f.Value, x, fail, sc, fg)
		}
	default:
		compileError(fmt.Sprintf("分からないパターン %s", typeNameOf(pat)))
	}
}

func (c *Compiler) exMatch(n *Match, sc *scope, fg *fnGen) string {
	subj := c.ex(n.Subject, sc, fg)
	end := fg.newLabel()
	type res struct{ v, l string }
	var results []res
	for _, cs := range n.Cases {
		nxt := fg.newLabel()
		local := newScope(sc, fg)
		c.pattern(cs.Pat, subj, nxt, local, fg)
		if cs.Guard != nil {
			g := c.ex(cs.Guard, local, fg)
			t := fg.call("i32", "@rt_truth", fmt.Sprintf("i64 %s, ptr %s, i32 %d", g, c.cstr(KwKatsu), posOf(lineOf(cs.Guard))))
			cc := fg.tmp()
			fg.emit(fmt.Sprintf("%s = icmp ne i32 %s, 0", cc, t))
			ok := fg.newLabel()
			fg.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", cc, ok, nxt))
			fg.start(ok)
		}
		v := c.ex(cs.Body, local, fg)
		results = append(results, res{v, fg.label})
		fg.emit("br label %" + end)
		fg.start(nxt)
	}
	if n.Default != nil {
		v := c.ex(n.Default, sc, fg)
		results = append(results, res{v, fg.label})
		fg.emit("br label %" + end)
	} else {
		fg.call("void", "@rt_no_match", fmt.Sprintf("i64 %s, ptr %s, i32 %d", subj, c.cstr(n.Fname), posOf(n.Line)))
		fg.emit("unreachable")
	}
	fg.start(end)
	if len(results) == 0 {
		fg.emit("unreachable")
		fg.start(fg.newLabel())
		return "0"
	}
	r := fg.tmp()
	parts := make([]string, len(results))
	for i, x := range results {
		parts[i] = fmt.Sprintf("[%s, %%%s]", x.v, x.l)
	}
	fg.emit(r + " = phi i64 " + strings.Join(parts, ", "))
	return r
}

// --- 手順 ---

func runKey(r *Run) string { return fmt.Sprintf("\x00した結果%p", r) }

// collectRuns は文の中の「した 結果」を、先に行うものから順に集める
func collectRuns(node Node, out []*Run) []*Run {
	switch n := node.(type) {
	case nil:
		return out
	case *Lambda, *Do:
		return out
	case *Define:
		if !n.IsFunction {
			out = collectRuns(n.Body, out)
		}
		return out
	case *If:
		return collectRuns(n.Cond, out)
	case *Match:
		return collectRuns(n.Subject, out)
	case *Run:
		out = collectRuns(n.Call, out)
		return append(out, n)
	}
	for _, ch := range node.Children() {
		out = collectRuns(ch, out)
	}
	return out
}

func (c *Compiler) do(stmts []Node, i int, sc *scope, fg *fnGen, line Pos) string {
	s := stmts[i]
	var runs []*Run
	for _, r := range collectRuns(s, nil) {
		if sc.lookup(runKey(r)) == nil {
			runs = append(runs, r)
		}
	}
	if len(runs) > 0 {
		r := runs[0]
		m := c.ex(r.Call, sc, fg)
		key := runKey(r)
		rest := genBody(func(local *scope, kfg *fnGen) string { return c.do(stmts, i, local, kfg, line) })
		k := c.closure("続き", []Param{{Part: WO, Name: key}}, rest, sc, fg, false)
		name := ""
		if call, ok := r.Call.(*Call); ok {
			name = strings.TrimSuffix(call.Name, Suru)
			if !strings.HasSuffix(call.Name, Suru) {
				rs := []rune(call.Name)
				if len(rs) >= 2 {
					name = string(rs[:len(rs)-2])
				} else {
					name = ""
				}
			}
		}
		return fg.call("i64", "@rt_do_run", fmt.Sprintf("i64 %s, i64 %s, ptr %s, i32 %d", m, k, c.cstr(name), posOf(r.Line)))
	}
	if d, ok := s.(*Define); ok {
		local := newScope(sc, fg)
		if d.IsFunction {
			c.localDefines([]*Define{d}, local, fg)
		} else {
			v := c.ex(d.Body, local, fg)
			k := fg.newSlot()
			fg.storeSlot(k, v)
			local.set(d.Name, &binding{kind: "slot", owner: fg, slot: k})
		}
		return c.do(stmts, i+1, local, fg, line)
	}
	v := c.ex(s, sc, fg)
	if i == len(stmts)-1 {
		return v
	}
	after := genBody(func(local *scope, kfg *fnGen) string { return c.do(stmts, i+1, local, kfg, line) })
	k := c.closure("続き", []Param{{Part: WO, Name: fmt.Sprintf("\x00捨てる%d", c.uid())}}, after, sc, fg, false)
	sl := line
	if l, ok := s.(Lined); ok {
		sl = l.GetLine()
	}
	return fg.call("i64", "@rt_do_seq", fmt.Sprintf("i64 %s, i64 %s, i32 %d", v, k, posOf(sl)))
}

// --- プログラムとファイル ---

func (c *Compiler) module(program []Node, path string) *scope {
	if sc, ok := c.modules[path]; ok {
		return sc
	}
	sc := newScope(nil, nil)
	c.modules[path] = sc
	ini := c.initFg
	for _, b := range libPrimitives(path) {
		g := c.newGlobal("gp")
		v := ini.call("i64", "@rt_std", "ptr "+c.cstr(b.Name))
		ini.emit(fmt.Sprintf("store i64 %s, ptr %s", v, g))
		sc.set(b.Name, &binding{kind: "gconst", g: g})
	}
	for _, s := range program {
		if imp, ok := s.(*Import); ok {
			sub := c.module(imp.Module.Program, imp.Module.Path)
			for _, name := range append([]string{}, sub.order...) {
				b := sub.vars[name]
				if !strings.Contains(name, ModuleSep) {
					sc.set(imp.Module.Name+ModuleSep+name, b)
					if imp.Open {
						sc.set(name, b)
					}
				}
			}
		}
	}
	var defines []*Define
	for _, s := range program {
		if d, ok := s.(*Define); ok {
			defines = append(defines, d)
		}
	}
	for _, d := range defines {
		if d.IsFunction {
			info := c.newInfo(d.Name, d.Params)
			sc.set(d.Name, &binding{kind: "gfn", g: c.newGlobal("gf"), info: info})
		} else {
			sc.set(d.Name, &binding{kind: "gval", g: c.newGlobal("gv")})
		}
	}
	for _, d := range defines {
		b := sc.vars[d.Name]
		var v string
		if d.IsFunction {
			c.genFunction(d.Name, d.Params, exprBody{d.Body}, sc, nil, b.info, true)
			v = c.makeFnValue(b.info, ini, "null")
		} else {
			z := c.thunk(d.Body, sc, nil)
			v = ini.call("i64", "@rt_lazy", fmt.Sprintf("ptr %s, ptr null", z))
		}
		ini.emit(fmt.Sprintf("store i64 %s, ptr %s", v, b.g))
	}
	for _, s := range program {
		decl, ok := s.(*TraitDecl)
		if !ok {
			continue
		}
		ini.call("void", "@rt_trait", "ptr "+c.cstr(decl.Name))
		type member struct {
			name   string
			params []Param
			d      *Define
		}
		var members []member
		for _, sg := range decl.Sigs {
			members = append(members, member{sg.Name, sg.Params, nil})
		}
		for _, d := range decl.Defaults {
			members = append(members, member{d.Name, d.Params, d})
		}
		for _, m := range members {
			deflt := "0"
			if m.d != nil {
				deflt = c.globalFunction(m.d, sc, ini)
			}
			wo := 0
			for k, p := range m.params {
				if p.Part == WO {
					wo = k
					break
				}
			}
			woList := 0
			if m.params[wo].List {
				woList = 1
			}
			parts := paramParts(m.params)
			ini.call("void", "@rt_trait_method", fmt.Sprintf("ptr %s, ptr %s, i32 %d, ptr %s, i32 %d, i32 %d, i64 %s",
				c.cstr(decl.Name), c.cstr(m.name), len(parts), c.parts(parts), wo, woList, deflt))
		}
	}
	for _, s := range program {
		impl, ok := s.(*TraitImpl)
		if !ok {
			continue
		}
		t, ty := c.cstr(impl.Trait), c.cstr(impl.TypeName)
		ini.call("void", "@rt_impl", fmt.Sprintf("ptr %s, ptr %s, ptr null, i64 0", t, ty))
		for _, d := range impl.Defs {
			v := c.globalFunction(d, sc, ini)
			ini.call("void", "@rt_impl", fmt.Sprintf("ptr %s, ptr %s, ptr %s, i64 %s", t, ty, c.cstr(d.Name), v))
		}
	}
	return sc
}

func (c *Compiler) globalFunction(d *Define, sc *scope, ini *fnGen) string {
	info := c.newInfo(d.Name, d.Params)
	c.genFunction(d.Name, d.Params, exprBody{d.Body}, sc, nil, info, true)
	return c.makeFnValue(info, ini, "null")
}

func (c *Compiler) compile(program []Node, path string) string {
	ini := newFnGen(c, nil)
	c.initFg = ini
	for _, ctor := range c.ctx.Ctors.Keys() {
		info, _ := c.ctx.Ctors.Get(ctor)
		ini.call("void", "@rt_def_ctor", fmt.Sprintf("ptr %s, ptr %s, i32 %d, ptr %s", c.cstr(ctor), c.cstr(info.Type), len(info.Fields), c.ptrs(info.Fields)))
	}
	sc := c.module(program, path)
	top := newScope(sc, ini)
	for _, s := range program {
		if _, ok := s.(*Define); ok || isTopLevelOnly(s) {
			continue
		}
		v := c.ex(s, top, ini)
		ini.call("void", "@rt_top", "i64 "+v)
	}
	ini.emit("ret i64 0")
	main := ini.finish("define internal i64 @suru_init(ptr %up)")
	c.functions = append(c.functions, main)
	entry := "define void @suru_main() {\nentry:\n" + strings.Join(c.consts, "\n") + "\n  %r = call i64 @suru_init(ptr null)\n  ret void\n}"
	source := fmt.Sprintf(`@suru_source = constant [%d x i8] c"%s\00"`, len(c.source)+1, irBytes(c.source))
	var b strings.Builder
	size := len(decls) + len(source) + len(entry) + 256
	for _, g := range c.globals {
		size += len(g) + 1
	}
	for _, f := range c.functions {
		size += len(f) + 1
	}
	b.Grow(size)
	b.WriteString("; 「する」のコンパイラが作った LLVM IR\n")
	for _, lib := range c.linkLibs {
		b.WriteString(LinkMark + lib + "\n")
	}
	b.WriteString(decls)
	syms := make([]string, 0, len(c.ffiDecls))
	for k := range c.ffiDecls {
		syms = append(syms, k)
	}
	sort.Strings(syms)
	for _, k := range syms {
		b.WriteString("\n" + c.ffiDecls[k])
	}
	b.WriteString("\n" + source)
	for _, g := range c.globals {
		b.WriteString("\n" + g)
	}
	for _, f := range c.functions {
		b.WriteString("\n" + f)
	}
	b.WriteString("\n" + entry + "\n")
	return b.String()
}

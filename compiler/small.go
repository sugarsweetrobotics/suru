// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics
//
// 追加の許可(GPL 第7条): このコンパイラが出力する LLVM IR・オブジェクト・実行ファイルは、
// 出力の中にこのコンパイラ由来の部分が含まれていても、GPL の対象にはなりません。
// 出力は、元にした する のプログラムの作者が好きなライセンスで配れます。

package compiler

// small.go は「小さい する」: マイコン(AVR)向けに、ヒープも GC も使わない LLVM IR を作る。
//
//   - 値は 数(i32)・真偽(i32 の 0 か 1)・文字列の定数(フラッシュの番地)・無 だけ。
//   - 動作は、呼んだところでその場で行う。動作を値として持ち回る書き方(引数に渡す・リストに入れる)は使えない。
//   - 型は型の検査の結果から決める。型が決まらない関数は、呼んだところの引数の型ごとに作る。
//   - 関数の最後で自分を呼ぶ繰り返し(手順の最後の「点滅する」など)は、スタックを使わないループにする。
//   - 中で定義した関数は、外の値を引数にして一番外の関数にする。
//
// 実行時の C(runtime/avr/suru_avr.c)が main を持ち、suru_main を呼ぶ。

import (
	"fmt"
	"math/big"
	"sort"
	"strings"
)

// SmallTarget はマイコンの種類(IR に書く情報)
type SmallTarget struct {
	Name string // 表示用(「Arduino Uno」など)
}

type sk int

const (
	skUnit sk = iota
	skInt
	skBool
	skStr
)

func (k sk) ir() string {
	if k == skStr {
		return "ptr addrspace(1)"
	}
	return "i32"
}

func (k sk) String() string {
	return [...]string{"無", "数", "真偽", "文字列"}[k]
}

// sval は式の値。v が "" なら、そこから先へは進まない(自分を呼ぶループで飛んだ)
type sval struct {
	v   string
	k   sk
	act bool
}

var sUnit = sval{v: "0", k: skUnit}

type sbind struct {
	kind string // "val"(値) / "slot"(引数。alloca の番地) / "fn"(関数)
	v    string
	k    sk
	id   int
	fn   *sfn
}

type sscope struct {
	vars   map[string]*sbind
	parent *sscope
	file   string // 型を引くときのファイル(本体なら "")
}

func newSScope(parent *sscope) *sscope {
	s := &sscope{vars: map[string]*sbind{}, parent: parent}
	if parent != nil {
		s.file = parent.file
	}
	return s
}

func (s *sscope) lookup(name string) *sbind {
	for x := s; x != nil; x = x.parent {
		if b, ok := x.vars[name]; ok {
			return b
		}
	}
	return nil
}

func (s *sscope) byID(id int) *sbind {
	for x := s; x != nil; x = x.parent {
		for _, b := range x.vars {
			if b.id == id && (b.kind == "val" || b.kind == "slot") {
				return b
			}
		}
	}
	return nil
}

// values は見えている値(引数と局所の値)を名前の順に返す(中の関数に渡すもの)
func (s *sscope) values() []*sbind {
	seen := map[string]bool{}
	var out []*sbind
	for x := s; x != nil; x = x.parent {
		names := make([]string, 0, len(x.vars))
		for n := range x.vars {
			names = append(names, n)
		}
		sort.Strings(names)
		for _, n := range names {
			if seen[n] {
				continue
			}
			seen[n] = true
			if b := x.vars[n]; b.kind == "val" || b.kind == "slot" {
				out = append(out, b)
			}
		}
	}
	return out
}

type scap struct {
	name string
	id   int
	k    sk
}

// sfn は する の関数(または引数なしの値の定義)
type sfn struct {
	name   string
	params []Param // 定義の順
	body   Node
	ext    *Extern
	line   Pos
	scope  *sscope // 定義したところ
	caps   []scap  // 中の関数: 外から受け取る値
	specs  map[string]*sspec
	result Type // 型の検査で分かった値の型(なければ nil)
}

// sspec は引数の型を決めて作った関数
type sspec struct {
	ir          string
	params      []sk
	result      sk
	resultKnown bool
	act         bool
	text        string
}

type defKey struct {
	file      string
	line, col int
	name      string
}

type small struct {
	ctx      *ParseContext
	target   SmallTarget
	defTypes map[defKey]Type
	strs     map[string]string
	globals  []string
	decls    map[string]string
	funcs    []*sspec
	queue    []func()
	uid      int
	ids      int
	modules  map[string]*sscope
}

func sfail(line Pos, format string, args ...any) {
	panic(&SuruError{Message: fmt.Sprintf(format, args...), Line: line})
}

// CompileSmall は する のプログラムを、マイコン向けの小さい LLVM IR にする。間違いがあれば *SuruError
func CompileSmall(source, baseDir, path string, target SmallTarget) (ir string, err *SuruError) {
	err = try(func() {
		ctx := NewParseContext(baseDir)
		ctx.Path = filePath(path)
		program := ParseProgram(source, ctx)
		var uses []Use
		if e := typeCheck(program, ctx, true, func(c *Checker) { uses = c.uses }); e != nil {
			panic(e)
		}
		program = DropTests(program) // 試験のまとまりと例は捨てる(#193)
		checkDefinitions(program, ctx)
		c := &small{ctx: ctx, target: target, defTypes: map[defKey]Type{}, strs: map[string]string{},
			decls: map[string]string{}, modules: map[string]*sscope{}}
		for _, u := range uses {
			if u.Def {
				c.defTypes[defKey{u.File, u.Pos.Line, u.Pos.Col, u.Name}] = u.T
			}
		}
		ir = c.compile(program)
	})
	return
}

// --- 型 ---

// kindOf は型の検査の型を、小さい する の値の種類にする。act は動作か。ok が false なら決まっていない
func kindOf(t Type) (k sk, act bool, ok bool) {
	t = prune(t)
	switch x := t.(type) {
	case *TCon:
		switch x.Name {
		case "数", "整数":
			return skInt, false, true
		case "真偽":
			return skBool, false, true
		case "文字列":
			return skStr, false, true
		case "無":
			return skUnit, false, true
		case "動作", "入出力動作":
			if len(x.Args) == 0 {
				return skUnit, true, true
			}
			if v, isVar := prune(x.Args[0]).(*TVar); isVar && v.ref == nil {
				return skUnit, true, true
			}
			k, _, ok := kindOf(x.Args[0])
			return k, true, ok
		}
	}
	return skUnit, false, false
}

func (c *small) defType(file string, d *Define) Type {
	return c.defTypes[defKey{file, d.Line.Line, d.Line.Col, d.Name}]
}

// resultOf は関数の型から、値の種類(分かれば)と動作かを決める
func resultOf(t Type) (k sk, act, known bool) {
	if t == nil {
		return skUnit, false, false
	}
	t = prune(t)
	f, isFun := t.(*TFun)
	if !isFun {
		return kindOf(t)
	}
	r := prune(f.Result)
	k, act, known = kindOf(r)
	if known {
		return
	}
	// 引数と同じ型変数なら、引数の型で決まる。そうでない型変数(使われない値)は 無
	if c, ok := r.(*TCon); ok && (c.Name == "動作" || c.Name == "入出力動作") && len(c.Args) == 1 {
		act = true
		r = prune(c.Args[0])
	}
	if v, ok := r.(*TVar); ok {
		for _, p := range f.Params {
			if occursIn(v, p.T) {
				return skUnit, act, false
			}
		}
		return skUnit, act, true
	}
	return skUnit, act, false
}

// --- 関数を作る場所 ---

type sgen struct {
	c          *small
	lines      []string
	allocas    []string
	n          int
	label      string
	fn         *sfn
	spec       *sspec
	paramSlots []string
	bodyLabel  string
}

func (g *sgen) tmp() string { g.n++; return fmt.Sprintf("%%t%d", g.n) }
func (g *sgen) newLabel() string {
	g.n++
	return fmt.Sprintf("L%d", g.n)
}
func (g *sgen) emit(s string) { g.lines = append(g.lines, "  "+s) }
func (g *sgen) start(l string) {
	g.lines = append(g.lines, l+":")
	g.label = l
}

func (c *small) newID() int { c.ids++; return c.ids }

// str は文字列の定数(フラッシュに置く)
func (c *small) str(s string) string {
	if g, ok := c.strs[s]; ok {
		return g
	}
	c.uid++
	g := fmt.Sprintf("@str.%d", c.uid)
	c.globals = append(c.globals, fmt.Sprintf(`%s = private unnamed_addr addrspace(1) constant [%d x i8] c"%s\00"`, g, len(s)+1, irBytes(s)))
	c.strs[s] = g
	return g
}

func (c *small) declare(sym, ret string, params []string, line Pos) {
	d := fmt.Sprintf("declare %s @%s(%s) addrspace(1)", ret, sym, strings.Join(params, ", "))
	if old, ok := c.decls[sym]; ok && old != d {
		sfail(line, "外部の関数「%s」が違う型で2回宣言されています", sym)
	}
	c.decls[sym] = d
}

func (c *small) rt(g *sgen, ret, sym string, args ...string) string {
	var ps []string
	for _, a := range args {
		ps = append(ps, strings.SplitN(a, " %", 2)[0])
	}
	// 型の部分だけを宣言に使う(定数の引数は「i32 5」の形)
	for i, a := range args {
		f := strings.Fields(a)
		ps[i] = strings.Join(f[:len(f)-1], " ")
	}
	c.declare(sym, ret, ps, Pos{})
	if ret == "void" {
		g.emit(fmt.Sprintf("call addrspace(1) void @%s(%s)", sym, strings.Join(args, ", ")))
		return ""
	}
	t := g.tmp()
	g.emit(fmt.Sprintf("%s = call addrspace(1) %s @%s(%s)", t, ret, sym, strings.Join(args, ", ")))
	return t
}

// --- プログラム ---

func (c *small) module(program []Node, path string) *sscope {
	if sc, ok := c.modules[path]; ok {
		return sc
	}
	sc := newSScope(nil)
	sc.file = path
	c.modules[path] = sc
	for _, s := range program {
		switch n := s.(type) {
		case *Import:
			sub := c.module(n.Module.Program, n.Module.Path)
			for name, b := range sub.vars {
				if strings.Contains(name, ModuleSep) || n.Module.Private[name] {
					continue
				}
				sc.vars[n.Module.Name+ModuleSep+name] = b
				if n.Open {
					sc.vars[name] = b
				}
			}
		case *TypeDef:
			sfail(n.Line, "マイコン向けでは、型の定義(組・場合の型)はまだ使えません")
		case *TraitDecl:
			sfail(n.Line, "マイコン向けでは、性質はまだ使えません")
		case *TraitImpl:
			sfail(n.Line, "マイコン向けでは、性質はまだ使えません")
		}
	}
	for _, s := range program {
		if d, ok := s.(*Define); ok {
			f := &sfn{name: d.Name, params: d.Params, body: d.Body, line: d.Line, scope: sc, specs: map[string]*sspec{}}
			if ext, ok := d.Body.(*Extern); ok {
				f.ext = ext
			}
			f.result = c.defType(path, d)
			sc.vars[d.Name] = &sbind{kind: "fn", fn: f}
		}
	}
	return sc
}

func (c *small) compile(program []Node) string {
	sc := c.module(program, "")
	g := &sgen{c: c}
	g.start("entry")
	top := newSScope(sc)
	for _, s := range program {
		if _, ok := s.(*Define); ok || isTopLevelOnly(s) {
			continue
		}
		v := c.ex(s, top, g, false)
		if !v.act && v.k != skUnit {
			c.print(g, v)
			c.rt(g, "void", "suru_newline")
		}
	}
	g.emit("ret void")
	main := "define void @suru_main() addrspace(1) {\n" + strings.Join(g.lines, "\n") + "\n}"
	for len(c.queue) > 0 {
		f := c.queue[0]
		c.queue = c.queue[1:]
		f()
	}
	var b strings.Builder
	b.WriteString("; 「する」のコンパイラが作った、マイコン向けの LLVM IR(" + c.target.Name + ")\n")
	syms := make([]string, 0, len(c.decls))
	for k := range c.decls {
		syms = append(syms, k)
	}
	sort.Strings(syms)
	for _, k := range syms {
		b.WriteString(c.decls[k] + "\n")
	}
	for _, gl := range c.globals {
		b.WriteString(gl + "\n")
	}
	for _, f := range c.funcs {
		b.WriteString("\n" + f.text + "\n")
	}
	b.WriteString("\n" + main + "\n")
	return b.String()
}

// --- 式 ---

func unsupported(line Pos, what string) {
	sfail(line, "マイコン向けでは、%sは使えません", what)
}

func (c *small) ex(node Node, sc *sscope, g *sgen, tail bool) sval {
	switch n := node.(type) {
	case *Num:
		switch n.Value.Kind {
		case NInt:
			x := n.Value.I
			if x.Cmp(big.NewInt(2147483647)) > 0 || x.Cmp(big.NewInt(-2147483648)) < 0 {
				sfail(n.Line, "マイコン向けの数は -2147483648 から 2147483647 までです(%s)", x.String())
			}
			return sval{v: x.String(), k: skInt}
		case NBool:
			if n.Value.B {
				return sval{v: "1", k: skBool}
			}
			return sval{v: "0", k: skBool}
		case NFloat:
			unsupported(n.Line, "小数")
		default:
			unsupported(n.Line, "リスト")
		}
	case *Str:
		return sval{v: c.str(n.Value), k: skStr}
	case *Var:
		return c.variable(n.Name, n.Line, sc, g, tail)
	case *BinOp:
		return c.binop(n, sc, g)
	case *Neg:
		x := c.ex(n.Operand, sc, g, false)
		t := g.tmp()
		g.emit(fmt.Sprintf("%s = sub i32 0, %s", t, x.v))
		return sval{v: t, k: skInt}
	case *Not:
		x := c.ex(n.Operand, sc, g, false)
		t := g.tmp()
		g.emit(fmt.Sprintf("%s = xor i32 %s, 1", t, x.v))
		return sval{v: t, k: skBool}
	case *If:
		cond := c.ex(n.Cond, sc, g, false)
		b := g.tmp()
		g.emit(fmt.Sprintf("%s = icmp ne i32 %s, 0", b, cond.v))
		lt, le, end := g.newLabel(), g.newLabel(), g.newLabel()
		g.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", b, lt, le))
		var outs []sval
		var labels []string
		g.start(lt)
		v1 := c.ex(n.Then, sc, g, tail)
		outs, labels = append(outs, v1), append(labels, g.label)
		g.brTo(v1, end)
		g.start(le)
		v2 := c.ex(n.Other, sc, g, tail)
		outs, labels = append(outs, v2), append(labels, g.label)
		g.brTo(v2, end)
		return c.join(g, end, outs, labels, firstLine(n))
	case *Block:
		local := newSScope(sc)
		var defs []*Define
		for _, s := range n.Statements {
			if d, ok := s.(*Define); ok {
				defs = append(defs, d)
			}
		}
		c.localFns(defs, local, true)
		r := sUnit
		var rest []Node
		for _, s := range n.Statements {
			if _, ok := s.(*Define); !ok {
				rest = append(rest, s)
			}
		}
		for i, s := range rest {
			r = c.ex(s, local, g, tail && i == len(rest)-1)
			if r.v == "" {
				return r
			}
		}
		return r
	case *Do:
		return c.do(n.Statements, sc, g, tail)
	case *Run:
		if n.Unwrap {
			unsupported(n.Line, "「した 中身」")
		}
		v := c.ex(n.Call, sc, g, false)
		v.act = false
		return v
	case *Field:
		if n.Name != Result {
			unsupported(n.Line, "組の欄")
		}
		v := c.ex(n.Target, sc, g, false)
		v.act = false
		return v
	case *Chain:
		m := c.ex(n.Call, sc, g, false)
		local := newSScope(sc)
		local.vars[Hole] = &sbind{kind: "val", v: m.v, k: m.k, id: c.newID()}
		r := c.ex(n.Cont, local, g, tail)
		r.act = true
		return r
	case *Call:
		return c.call(n, sc, g, tail)
	case *Match:
		return c.match(n, sc, g, tail)
	case *ListLit:
		unsupported(firstLine(n), "リスト")
	case *Lambda:
		unsupported(n.Line, "無名関数")
	case *Ref:
		unsupported(n.Line, "関数を値にすること(すること)")
	case *Each:
		unsupported(n.Line, "「それぞれ」")
	case *Prop:
		unsupported(n.Line, "性質")
	case *Construct:
		unsupported(n.Line, "組")
	case *NamedConstruct:
		unsupported(n.Line, "組")
	case *Update:
		unsupported(n.Line, "組")
	}
	sfail(firstLine(node), "マイコン向けでは、この書き方(%s)はまだ使えません", typeNameOf(node))
	return sUnit
}

// brTo は枝が進めるなら end へ飛ぶ
func (g *sgen) brTo(v sval, end string) {
	if v.v != "" {
		g.emit("br label %" + end)
	}
}

// join は枝の値を1つにする(phi)。進めない枝は入れない
func (c *small) join(g *sgen, end string, outs []sval, labels []string, line Pos) sval {
	var live []sval
	var ls []string
	for i, o := range outs {
		if o.v == "" {
			continue
		}
		live = append(live, o)
		ls = append(ls, labels[i])
	}
	g.start(end)
	if len(live) == 0 {
		g.emit("unreachable")
		return sval{}
	}
	k := live[0].k
	act := false
	for _, o := range live {
		act = act || o.act
		if o.k != k {
			if o.k == skStr || k == skStr {
				sfail(line, "枝の値の型が違います(%s と %s)", k, o.k)
			}
			k = skInt
		}
	}
	if len(live) == 1 {
		return sval{v: live[0].v, k: k, act: act}
	}
	r := g.tmp()
	var parts []string
	for i, o := range live {
		parts = append(parts, fmt.Sprintf("[%s, %%%s]", o.v, ls[i]))
	}
	g.emit(fmt.Sprintf("%s = phi %s %s", r, k.ir(), strings.Join(parts, ", ")))
	return sval{v: r, k: k, act: act}
}

func (c *small) variable(name string, line Pos, sc *sscope, g *sgen, tail bool) sval {
	b := sc.lookup(name)
	if b == nil {
		sfail(line, "マイコン向けでは「%s」は使えません", displayName(name))
	}
	switch b.kind {
	case "val":
		return sval{v: b.v, k: b.k}
	case "slot":
		t := g.tmp()
		g.emit(fmt.Sprintf("%s = load %s, ptr %s", t, b.k.ir(), b.v))
		return sval{v: t, k: b.k}
	}
	if len(b.fn.params) > 0 {
		sfail(line, "マイコン向けでは、関数「%s」を値として使うことはできません", displayName(name))
	}
	return c.callFn(b.fn, nil, nil, line, sc, g, tail)
}

func (c *small) toBool(g *sgen, v sval) string {
	b := g.tmp()
	g.emit(fmt.Sprintf("%s = icmp ne i32 %s, 0", b, v.v))
	return b
}

func (c *small) binop(n *BinOp, sc *sscope, g *sgen) sval {
	if n.Op == KwKatsu || n.Op == KwMataha {
		a := c.ex(n.Left, sc, g, false)
		ba := c.toBool(g, a)
		right, done := g.newLabel(), g.newLabel()
		from := g.label
		if n.Op == KwKatsu {
			g.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", ba, right, done))
		} else {
			g.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", ba, done, right))
		}
		g.start(right)
		b := c.ex(n.Right, sc, g, false)
		lb := g.label
		g.emit("br label %" + done)
		g.start(done)
		r := g.tmp()
		short := "0"
		if n.Op == KwMataha {
			short = "1"
		}
		g.emit(fmt.Sprintf("%s = phi i32 [%s, %%%s], [%s, %%%s]", r, short, from, b.v, lb))
		return sval{v: r, k: skBool}
	}
	a := c.ex(n.Left, sc, g, false)
	b := c.ex(n.Right, sc, g, false)
	if a.k == skStr || b.k == skStr {
		if n.Op == "+" {
			sfail(n.Line, "マイコン向けでは、文字列をつなぐのは「表示する」の「を」の中だけです")
		}
		sfail(n.Line, "マイコン向けでは、文字列の比べ算はまだ使えません")
	}
	t := g.tmp()
	switch n.Op {
	case "+", "-", "*":
		op := map[string]string{"+": "add", "-": "sub", "*": "mul"}[n.Op]
		g.emit(fmt.Sprintf("%s = %s i32 %s, %s", t, op, a.v, b.v))
		return sval{v: t, k: skInt}
	case "/", "%":
		sym := "suru_floordiv"
		if n.Op == "%" {
			sym = "suru_floormod"
		}
		return sval{v: c.rt(g, "i32", sym, "i32 "+a.v, "i32 "+b.v, fmt.Sprintf("i32 %d", n.Line.Line)), k: skInt}
	case "^":
		return sval{v: c.rt(g, "i32", "suru_pow", "i32 "+a.v, "i32 "+b.v), k: skInt}
	case "<", ">", "<=", ">=", "==", "!=":
		pred := map[string]string{"<": "slt", ">": "sgt", "<=": "sle", ">=": "sge", "==": "eq", "!=": "ne"}[n.Op]
		x := g.tmp()
		g.emit(fmt.Sprintf("%s = icmp %s i32 %s, %s", x, pred, a.v, b.v))
		g.emit(fmt.Sprintf("%s = zext i1 %s to i32", t, x))
		return sval{v: t, k: skBool}
	}
	sfail(n.Line, "マイコン向けでは、演算「%s」は使えません", n.Op)
	return sUnit
}

// --- 手順 ---

func (c *small) do(stmts []Node, sc *sscope, g *sgen, tail bool) sval {
	local := newSScope(sc)
	last := sUnit
	for i, s := range stmts {
		isLast := i == len(stmts)-1
		if d, ok := s.(*Define); ok {
			local = newSScope(local)
			if d.IsFunction || len(d.Params) > 0 {
				c.localFns([]*Define{d}, local, false)
			} else if _, act, _ := resultOf(c.defType(sc.file, d)); act {
				// 動作に名前を付けただけ: 使うたびに行う
				c.localFns([]*Define{d}, local, false)
			} else {
				v := c.ex(d.Body, local, g, false)
				if v.v == "" {
					return v
				}
				local.vars[d.Name] = &sbind{kind: "val", v: v.v, k: v.k, id: c.newID()}
			}
			last = sUnit
			continue
		}
		last = c.ex(s, local, g, tail && isLast)
		if last.v == "" {
			return last
		}
	}
	last.act = true
	return last
}

// localFns は中の定義を関数にする。値の定義も(block なら)引数なしの関数にする
func (c *small) localFns(defs []*Define, sc *sscope, block bool) {
	vals := sc.values()
	var caps []scap
	for _, b := range vals {
		caps = append(caps, scap{name: "", id: b.id, k: b.k})
	}
	// 名前は、見えている名前で入れる
	for i, b := range vals {
		for x := sc; x != nil; x = x.parent {
			found := false
			for n, bb := range x.vars {
				if bb == b {
					caps[i].name = n
					found = true
					break
				}
			}
			if found {
				break
			}
		}
	}
	for _, d := range defs {
		f := &sfn{name: d.Name, params: d.Params, body: d.Body, line: d.Line, scope: sc, caps: caps, specs: map[string]*sspec{}}
		if ext, ok := d.Body.(*Extern); ok {
			f.ext = ext
		}
		f.result = c.defType(sc.file, d)
		sc.vars[d.Name] = &sbind{kind: "fn", fn: f}
	}
}

// --- 呼び出し ---

func (c *small) call(n *Call, sc *sscope, g *sgen, tail bool) sval {
	b := sc.lookup(n.Name)
	if b == nil {
		return c.builtin(n, sc, g)
	}
	if b.kind != "fn" {
		sfail(n.Line, "マイコン向けでは、関数を値として渡すことはできません(「%s」)", displayName(n.Name))
	}
	f := b.fn
	byPart := map[string]sval{}
	var order []string
	for _, a := range n.Args {
		if _, ok := a.Value.(*Each); ok {
			unsupported(n.Line, "「それぞれ」")
		}
		v := c.ex(a.Value, sc, g, false)
		if v.v == "" {
			return v
		}
		byPart[a.Part] = v
		order = append(order, a.Part)
	}
	var vals []sval
	for _, p := range f.params {
		if p.List || p.Pat != nil {
			sfail(n.Line, "マイコン向けでは、「%s」の引数の書き方(リストや形)は使えません", displayName(f.name))
		}
		v, ok := byPart[p.Part]
		if !ok {
			sfail(n.Line, "マイコン向けでは、「%s」の「%s」を省けません", displayName(f.name), p.Part)
		}
		vals = append(vals, v)
	}
	if len(vals) != len(n.Args) {
		sfail(n.Line, "「%s」に渡した引数が合いません", displayName(f.name))
	}
	return c.callFn(f, vals, order, n.Line, sc, g, tail)
}

func (c *small) callFn(f *sfn, vals []sval, _ []string, line Pos, sc *sscope, g *sgen, tail bool) sval {
	if f.ext != nil {
		return c.callExtern(f, vals, line, g)
	}
	kinds := make([]sk, len(vals))
	key := ""
	for i, v := range vals {
		kinds[i] = v.k
		key += fmt.Sprint(int(v.k))
	}
	sp := c.spec(f, kinds, key)
	var args []string
	for i, v := range vals {
		args = append(args, sp.params[i].ir()+" "+v.v)
	}
	for _, cp := range f.caps {
		b := sc.byID(cp.id)
		if b == nil {
			sfail(line, "「%s」の外の値「%s」が見つかりません(コンパイラの間違い)", displayName(f.name), displayName(cp.name))
		}
		v := b.v
		if b.kind == "slot" {
			t := g.tmp()
			g.emit(fmt.Sprintf("%s = load %s, ptr %s", t, b.k.ir(), b.v))
			v = t
		}
		args = append(args, b.k.ir()+" "+v)
	}
	if tail && g.spec == sp && g.fn == f {
		// 自分を最後に呼ぶ: 引数を置きかえて本体の始めへ戻る
		for i := range vals {
			g.emit(fmt.Sprintf("store %s %s, ptr %s", sp.params[i].ir(), vals[i].v, g.paramSlots[i]))
		}
		g.emit("br label %" + g.bodyLabel)
		g.start(g.newLabel())
		g.emit("unreachable")
		return sval{}
	}
	if !sp.resultKnown {
		sfail(line, "マイコン向けでは「%s」の値の型が決まりません(型の宣言を書いてください)", displayName(f.name))
	}
	t := g.tmp()
	g.emit(fmt.Sprintf("%s = call addrspace(1) %s %s(%s)", t, sp.result.ir(), sp.ir, strings.Join(args, ", ")))
	return sval{v: t, k: sp.result, act: sp.act}
}

func (c *small) spec(f *sfn, kinds []sk, key string) *sspec {
	if sp, ok := f.specs[key]; ok {
		return sp
	}
	c.uid++
	sp := &sspec{ir: fmt.Sprintf("@f.%d", c.uid), params: kinds}
	sp.result, sp.act, sp.resultKnown = resultOf(f.result)
	f.specs[key] = sp
	c.funcs = append(c.funcs, sp)
	c.genSpec(f, sp)
	return sp
}

func (c *small) genSpec(f *sfn, sp *sspec) {
	g := &sgen{c: c, fn: f, spec: sp}
	outer := newSScope(f.scope)
	var header []string
	for i, cp := range f.caps {
		a := fmt.Sprintf("%%c%d", i)
		outer.vars[cp.name] = &sbind{kind: "val", v: a, k: cp.k, id: cp.id}
		header = append(header, cp.k.ir()+" "+a)
	}
	local := newSScope(outer)
	var params []string
	g.start("entry")
	for i, p := range f.params {
		a := fmt.Sprintf("%%a%d", i)
		params = append(params, sp.params[i].ir()+" "+a)
		slot := fmt.Sprintf("%%p%d", i)
		g.emit(fmt.Sprintf("%s = alloca %s", slot, sp.params[i].ir()))
		g.emit(fmt.Sprintf("store %s %s, ptr %s", sp.params[i].ir(), a, slot))
		g.paramSlots = append(g.paramSlots, slot)
		local.vars[p.Name] = &sbind{kind: "slot", v: slot, k: sp.params[i], id: c.newID()}
	}
	g.bodyLabel = "body"
	g.emit("br label %body")
	g.start("body")
	r := c.ex(f.body, local, g, true)
	if !sp.resultKnown {
		sp.result, sp.resultKnown = r.k, true
	}
	if r.act {
		sp.act = true
	}
	if r.v != "" {
		if sp.result == skUnit || r.k == skUnit {
			g.emit(fmt.Sprintf("ret %s %s", sp.result.ir(), zeroOf(sp.result)))
		} else {
			g.emit(fmt.Sprintf("ret %s %s", sp.result.ir(), r.v))
		}
	}
	all := append(params, header...)
	sp.text = fmt.Sprintf("; %s\ndefine internal %s %s(%s) addrspace(1) {\n%s\n}", displayName(f.name), sp.result.ir(), sp.ir, strings.Join(all, ", "), strings.Join(g.lines, "\n"))
}

func zeroOf(k sk) string {
	if k == skStr {
		return "null"
	}
	return "0"
}

// cKind は外部の関数の C の型
func cKind(t string, line Pos, name string) sk {
	switch t {
	case "i64", "i32":
		return skInt
	case "bool":
		return skBool
	case "str":
		return skStr
	case "void":
		return skUnit
	}
	sfail(line, "マイコン向けでは、外部の関数「%s」の型(%s)は使えません", name, t)
	return skUnit
}

func (c *small) callExtern(f *sfn, vals []sval, line Pos, g *sgen) sval {
	ext := f.ext
	if ext.Pointer != "" {
		unsupported(line, "関数の番地を使う外部の関数")
	}
	var types, args []string
	add := func(k sk, v string) {
		types = append(types, k.ir())
		args = append(args, k.ir()+" "+v)
	}
	if len(ext.CArgs) > 0 {
		for _, a := range ext.CArgs {
			if a.IsConst {
				add(skInt, fmt.Sprint(int32(a.Const)))
			} else {
				add(cKind(ext.Params[a.Param], line, ext.Symbol), vals[a.Param].v)
			}
		}
	} else {
		for i, v := range vals {
			add(cKind(ext.Params[i], line, ext.Symbol), v.v)
		}
	}
	rk := cKind(ext.Result, line, ext.Symbol)
	ret := rk.ir()
	if rk == skUnit {
		ret = "void"
	}
	c.declare(ext.Symbol, ret, types, ext.Line)
	if rk == skUnit {
		g.emit(fmt.Sprintf("call addrspace(1) void @%s(%s)", ext.Symbol, strings.Join(args, ", ")))
		return sval{v: "0", k: skUnit, act: ext.Action}
	}
	t := g.tmp()
	g.emit(fmt.Sprintf("%s = call addrspace(1) %s @%s(%s)", t, ret, ext.Symbol, strings.Join(args, ", ")))
	return sval{v: t, k: rk, act: ext.Action}
}

// --- 組み込み ---

func (c *small) arg(n *Call, part string, sc *sscope, g *sgen) (sval, bool) {
	x, ok := n.Args.Get(part)
	if !ok {
		return sUnit, false
	}
	return c.ex(x, sc, g, false), true
}

func (c *small) builtin(n *Call, sc *sscope, g *sgen) sval {
	switch n.Name {
	case "表示する", "続表示する":
		x, _ := n.Args.Get(WO)
		c.printExpr(x, sc, g)
		if n.Name == "表示する" {
			c.rt(g, "void", "suru_newline")
		}
		return sval{v: "0", k: skUnit, act: true}
	case "絶対値にする":
		a, _ := c.arg(n, WO, sc, g)
		return sval{v: c.rt(g, "i32", "suru_abs", "i32 "+a.v), k: skInt}
	case "加算する", "乗算する":
		op := "add"
		if n.Name == "乗算する" {
			op = "mul"
		}
		x, _ := n.Args.Get(WO)
		var items []Node
		if l, ok := x.(*ListLit); ok {
			items = l.Items
		} else {
			items = []Node{x}
		}
		if y, ok := n.Args.Get("に"); ok {
			items = append(items, y)
		}
		acc := ""
		for _, it := range items {
			v := c.ex(it, sc, g, false)
			if acc == "" {
				acc = v.v
				continue
			}
			t := g.tmp()
			g.emit(fmt.Sprintf("%s = %s i32 %s, %s", t, op, acc, v.v))
			acc = t
		}
		return sval{v: acc, k: skInt}
	case "減算する":
		a, _ := c.arg(n, "から", sc, g)
		b, _ := c.arg(n, WO, sc, g)
		t := g.tmp()
		g.emit(fmt.Sprintf("%s = sub i32 %s, %s", t, a.v, b.v))
		return sval{v: t, k: skInt}
	case "除算する":
		a, _ := c.arg(n, WO, sc, g)
		b, _ := c.arg(n, "で", sc, g)
		return sval{v: c.rt(g, "i32", "suru_floordiv", "i32 "+a.v, "i32 "+b.v, fmt.Sprintf("i32 %d", n.Line.Line)), k: skInt}
	}
	if n.Name == "文字列化する" {
		sfail(n.Line, "マイコン向けでは、「文字列化する」は「表示する」の「を」の中だけで使えます")
	}
	sfail(n.Line, "マイコン向けでは「%s」は使えません", displayName(n.Name))
	return sUnit
}

// isStrExpr は値が文字列になる式か(表示するの中の + を、つないで表示するために見る)
func (c *small) isStrExpr(x Node, sc *sscope) bool {
	switch n := x.(type) {
	case *Str:
		return true
	case *BinOp:
		return n.Op == "+" && (c.isStrExpr(n.Left, sc) || c.isStrExpr(n.Right, sc))
	case *Var:
		if b := sc.lookup(n.Name); b != nil {
			if b.kind == "fn" {
				k, _, _ := resultOf(b.fn.result)
				return k == skStr
			}
			return b.k == skStr
		}
	case *Call:
		if n.Name == "文字列化する" && sc.lookup(n.Name) == nil {
			return true
		}
		if b := sc.lookup(n.Name); b != nil && b.kind == "fn" {
			if b.fn.ext != nil {
				return b.fn.ext.Result == "str"
			}
			k, _, _ := resultOf(b.fn.result)
			return k == skStr
		}
	}
	return false
}

func (c *small) printExpr(x Node, sc *sscope, g *sgen) {
	if b, ok := x.(*BinOp); ok && b.Op == "+" && c.isStrExpr(b, sc) {
		c.printExpr(b.Left, sc, g)
		c.printExpr(b.Right, sc, g)
		return
	}
	if call, ok := x.(*Call); ok && call.Name == "文字列化する" && sc.lookup(call.Name) == nil {
		y, _ := call.Args.Get(WO)
		c.printExpr(y, sc, g)
		return
	}
	c.print(g, c.ex(x, sc, g, false))
}

func (c *small) print(g *sgen, v sval) {
	switch v.k {
	case skInt:
		c.rt(g, "void", "suru_put_int", "i32 "+v.v)
	case skBool:
		c.rt(g, "void", "suru_put_bool", "i32 "+v.v)
	case skStr:
		c.rt(g, "void", "suru_put_str", "ptr addrspace(1) "+v.v)
	}
}

// --- 場合分け ---

func (c *small) match(n *Match, sc *sscope, g *sgen, tail bool) sval {
	var subj []sval
	if l, ok := n.Subject.(*ListLit); ok {
		for _, it := range l.Items {
			subj = append(subj, c.ex(it, sc, g, false))
		}
	} else {
		subj = []sval{c.ex(n.Subject, sc, g, false)}
	}
	var outs []sval
	var labels []string
	end := g.newLabel()
	for _, cs := range n.Cases {
		next := g.newLabel()
		local := newSScope(sc)
		pats := []Node{cs.Pat}
		if len(subj) > 1 {
			ps, ok := cs.Pat.(*PSeq)
			if !ok || len(ps.Items) != len(subj) {
				unsupported(n.Line, "この場合分けの形")
			}
			pats = ps.Items
		}
		for i, p := range pats {
			c.pattern(p, subj[i], next, local, g, n.Line)
		}
		if cs.Guard != nil {
			gv := c.ex(cs.Guard, local, g, false)
			b := c.toBool(g, gv)
			ok := g.newLabel()
			g.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", b, ok, next))
			g.start(ok)
		}
		v := c.ex(cs.Body, local, g, tail)
		outs, labels = append(outs, v), append(labels, g.label)
		g.brTo(v, end)
		g.start(next)
	}
	if n.Default != nil {
		v := c.ex(n.Default, sc, g, tail)
		outs, labels = append(outs, v), append(labels, g.label)
		g.brTo(v, end)
	} else {
		name := c.str(displayName(n.Fname))
		c.rt(g, "void", "suru_no_match", "ptr addrspace(1) "+name, fmt.Sprintf("i32 %d", n.Line.Line))
		g.emit("unreachable")
	}
	return c.join(g, end, outs, labels, n.Line)
}

func (c *small) pattern(p Node, v sval, fail string, sc *sscope, g *sgen, line Pos) {
	switch q := p.(type) {
	case *PBind:
		sc.vars[q.Name] = &sbind{kind: "val", v: v.v, k: v.k, id: c.newID()}
	case *PValue:
		e := c.ex(q.Expr, sc, g, false)
		if e.k == skStr || v.k == skStr {
			unsupported(line, "文字列の場合分け")
		}
		b := g.tmp()
		g.emit(fmt.Sprintf("%s = icmp eq i32 %s, %s", b, e.v, v.v))
		ok := g.newLabel()
		g.emit(fmt.Sprintf("br i1 %s, label %%%s, label %%%s", b, ok, fail))
		g.start(ok)
	default:
		unsupported(line, "この場合分けの形(リストや組)")
	}
}

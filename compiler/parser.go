// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// --- 例外のかわり(Python の raise / try と同じ流れにするため panic を使う) ---

func raise(line Pos, msg string) { panic(&SuruError{Message: msg, Line: line}) }

func raisef(line Pos, format string, args ...any) {
	panic(&SuruError{Message: fmt.Sprintf(format, args...), Line: line})
}

func must[T any](v T, err error) T {
	if err != nil {
		if se, ok := err.(*SuruError); ok {
			panic(se)
		}
		panic(err)
	}
	return v
}

// try は f の中の SuruError を返す(ほかの panic はそのまま)
func try(f func()) (err *SuruError) {
	defer func() {
		if r := recover(); r != nil {
			if se, ok := r.(*SuruError); ok {
				err = se
				return
			}
			panic(r)
		}
	}()
	f()
	return nil
}

// --- 型の名前と形の名前 ---

type CtorInfo struct {
	Type   string
	Fields []string
}

// CtorMap は順番を保つ 形 → (型, フィールド名) の表
type CtorMap struct {
	keys []string
	m    map[string]CtorInfo
}

func newCtorMap() *CtorMap { return &CtorMap{m: map[string]CtorInfo{}} }

func (c *CtorMap) Get(k string) (CtorInfo, bool) { v, ok := c.m[k]; return v, ok }
func (c *CtorMap) Has(k string) bool             { _, ok := c.m[k]; return ok }
func (c *CtorMap) Set(k string, v CtorInfo) {
	if _, ok := c.m[k]; !ok {
		c.keys = append(c.keys, k)
	}
	c.m[k] = v
}
func (c *CtorMap) Keys() []string { return c.keys }
func (c *CtorMap) Copy() *CtorMap {
	n := newCtorMap()
	for _, k := range c.keys {
		n.Set(k, c.m[k])
	}
	return n
}
func (c *CtorMap) Update(o *CtorMap) {
	for _, k := range o.keys {
		c.Set(k, o.m[k])
	}
}

// TypeMap は順番を保つ 型 → [形] の表
type TypeMap struct {
	keys []string
	m    map[string][]string
}

func newTypeMap() *TypeMap { return &TypeMap{m: map[string][]string{}} }

func (t *TypeMap) Get(k string) ([]string, bool) { v, ok := t.m[k]; return v, ok }
func (t *TypeMap) Has(k string) bool             { _, ok := t.m[k]; return ok }
func (t *TypeMap) Set(k string, v []string) {
	if _, ok := t.m[k]; !ok {
		t.keys = append(t.keys, k)
	}
	t.m[k] = v
}
func (t *TypeMap) Copy() *TypeMap {
	n := newTypeMap()
	for _, k := range t.keys {
		n.Set(k, t.m[k])
	}
	return n
}
func (t *TypeMap) Update(o *TypeMap) {
	for _, k := range o.keys {
		t.Set(k, o.m[k])
	}
}

// 小数・整数は数の別名(外部の関数の宣言で C の double・int を表す)。番地は C のポインタ
// 無は外部の関数の値がないこと(C の void。する では 0)。バイト列は変更できないバイトの並び
var builtinTypes = []string{"数", "文字列", "真偽", "リスト", "関数", "動作", "小数", "整数", "番地", "バイト列", "無"}

// KwExtern は外部の関数・ライブラリの印
const KwExtern = "外部の"

// ffiTypeNames は外部の関数に渡せる型(書く順)と C の型
var ffiTypeNames = []string{"数", "小数", "整数", "真偽", "文字列", "番地", "バイト列", "無"}
var ffiTypes = map[string]string{"数": "i64", "小数": "f64", "整数": "i32", "真偽": "bool", "文字列": "str", "番地": "ptr",
	"バイト列": "bytes", "無": "void"}
var builtinTypeSet = setOf(builtinTypes...)

const typeVarNames = "甲乙丙丁戊己庚辛壬癸"

// ParseContext は構文解析で使う、定義済みの型と形の名前
type ParseContext struct {
	Ctors   *CtorMap
	Types   *TypeMap
	BaseDir string
	Modules map[string]*Module // 絶対パス → Module(読み込み中は nil)
	Loading map[string]bool
	// Packages はプロジェクトの依存(名前 → Package)。nil なら、初めて読み込むときに BaseDir から探す
	Packages map[string]Package
	// InPrelude は 基本.suru そのものを読んでいるとき(基本を自動で読み込まない)
	InPrelude bool
}

func NewParseContext(baseDir string) *ParseContext {
	return &ParseContext{Ctors: newCtorMap(), Types: newTypeMap(), BaseDir: baseDir,
		Modules: map[string]*Module{}, Loading: map[string]bool{}}
}

func (c *ParseContext) add(td *TypeDef) {
	if c.Types.Has(td.Name) || builtinTypeSet[td.Name] {
		raisef(td.Line, "型「%s」は既に定義されています", td.Name)
	}
	var names []string
	for _, ct := range td.Ctors {
		names = append(names, ct.Name)
	}
	count := func(x string) int {
		n := 0
		for _, y := range names {
			if y == x {
				n++
			}
		}
		return n
	}
	for _, ct := range td.Ctors {
		if count(ct.Name) > 1 {
			raisef(td.Line, "形「%s」が2回書かれています", ct.Name)
		}
		if info, ok := c.Ctors.Get(ct.Name); ok {
			raisef(td.Line, "形「%s」は既に型「%s」で使われています", ct.Name, info.Type)
		}
		for _, f := range ct.Fields {
			if count(f) > 0 || f == td.Name || c.Ctors.Has(f) || c.Types.Has(f) {
				raisef(td.Line, "フィールド名「%s」は型や形の名前と同じにできません", f)
			}
		}
	}
	c.Types.Set(td.Name, names)
	for _, ct := range td.Ctors {
		c.Ctors.Set(ct.Name, CtorInfo{td.Name, append([]string{}, ct.Fields...)})
	}
}

var curCtx = NewParseContext(".")

func isCtor(t *Token) bool { return t != nil && t.Kind == "WORD" && curCtx.Ctors.Has(t.S) }

func isNullary(name string) bool {
	info, ok := curCtx.Ctors.Get(name)
	return ok && len(info.Fields) == 0
}

// --- レイアウト ---

type LNode struct {
	Line     *Line
	Children []*LNode
}

func buildLayout(lines []*Line) []*LNode {
	pos := 0
	var block func(minIndent int) []*LNode
	block = func(minIndent int) []*LNode {
		var nodes []*LNode
		if pos >= len(lines) {
			return nodes
		}
		indent := lines[pos].Indent
		for pos < len(lines) {
			ln := lines[pos]
			if ln.Indent < indent {
				if ln.Indent >= minIndent {
					raise(ln.Number, "インデントがそろっていません")
				}
				break
			}
			if ln.Indent > indent {
				raise(ln.Number, "予期しないインデントです")
			}
			pos++
			node := &LNode{Line: ln}
			if !ln.Closed && pos < len(lines) && lines[pos].Indent > indent {
				node.Children = block(indent + 1)
			}
			first := ln.Tokens[0]
			if len(nodes) > 0 && !ln.Closed && !nodes[len(nodes)-1].Line.Closed && first.Kind == "KW" && continuationKeywords[first.S] {
				prev := nodes[len(nodes)-1]
				prev.Children = append(prev.Children, node)
			} else {
				nodes = append(nodes, node)
			}
		}
		return nodes
	}
	top := block(0)
	if len(lines) > 0 && lines[0].Indent != 0 {
		raise(lines[0].Number, "最初の行はインデントできません")
	}
	return top
}

func flatten(node *LNode) []*Token {
	out := append([]*Token{}, node.Line.Tokens...)
	for _, c := range node.Children {
		out = append(out, tok("SEP", "", c.Line.Number))
		out = append(out, flatten(c)...)
	}
	return out
}

func isKw(t *Token, v string) bool { return t != nil && t.Kind == "KW" && t.S == v }
func isPart(t *Token, v string) bool {
	return t != nil && t.Kind == "PART" && (v == "" || t.S == v)
}

func mergePiped(args Args, piped Node, key string) Args {
	out := make(Args, 0, len(args)+1)
	if given, ok := args.Get(key); ok {
		var items []Node
		if l, ok := given.(*ListLit); ok {
			items = l.Items
		} else {
			items = []Node{given}
		}
		for _, a := range args {
			if a.Part == key {
				out = append(out, Arg{key, &ListLit{Items: append([]Node{piped}, items...)}})
			} else {
				out = append(out, a)
			}
		}
		return out
	}
	out = append(out, Arg{key, piped})
	return append(out, args...)
}

func toPattern(node Node, line Pos) Param {
	var vs []Node
	if l, ok := node.(*ListLit); ok {
		vs = l.Items
	} else {
		vs = []Node{node}
	}
	for _, v := range vs {
		if vv, ok := v.(*Var); ok && !vv.Quoted && isAllHiragana(vv.Name) && vv.Name != "それぞれ" {
			panic(hiraganaNameError(vv.Name, vv.Line))
		}
	}
	if v, ok := node.(*Var); ok {
		return Param{Name: v.Name}
	}
	if l, ok := node.(*ListLit); ok {
		var names []string
		all := true
		for _, i := range l.Items {
			if v, ok := i.(*Var); ok {
				names = append(names, v.Name)
			} else {
				all = false
			}
		}
		if all {
			return Param{Names: names, List: true}
		}
	}
	raise(line, "引数の名前には名前か「名前 と 名前」しか書けません")
	return Param{}
}

func checkParams(params []Param, line Pos) {
	seen := map[string]bool{}
	for _, p := range params {
		names := p.Names
		if !p.List {
			names = []string{p.Name}
		}
		for _, n := range names {
			if seen[n] {
				raisef(line, "引数名「%s」が重複しています", n)
			}
			seen[n] = true
		}
	}
}

func patternBinders(pat Node) []string {
	switch p := pat.(type) {
	case *PBind:
		return []string{p.Name}
	case *PCtor:
		var out []string
		for _, q := range p.Items {
			out = append(out, patternBinders(q)...)
		}
		return out
	case *PSeq:
		var out []string
		for _, q := range p.Items {
			out = append(out, patternBinders(q)...)
		}
		return out
	case *PNamed:
		var out []string
		for _, f := range p.Fields {
			out = append(out, patternBinders(f.Value)...)
		}
		return out
	}
	return nil
}

func checkPattern(pat Node, line Pos) {
	names := patternBinders(pat)
	cnt := map[string]int{}
	for _, n := range names {
		cnt[n]++
	}
	for _, n := range names {
		if cnt[n] > 1 {
			raisef(line, "パターンの中で名前「%s」が2回使われています", n)
		}
	}
	var walk func(p Node)
	walk = func(p Node) {
		switch q := p.(type) {
		case *PCtor:
			info, _ := curCtx.Ctors.Get(q.Ctor)
			if len(q.Items) != len(info.Fields) {
				raisef(line, "「%s」のパターンには%d個の名前が必要です(書かれているのは%d個)", q.Ctor, len(info.Fields), len(q.Items))
			}
			for _, x := range q.Items {
				walk(x)
			}
		case *PSeq:
			for _, x := range q.Items {
				walk(x)
			}
		case *PNamed:
			for _, f := range q.Fields {
				if q.HasCtor {
					info, _ := curCtx.Ctors.Get(q.Ctor)
					if !contains(info.Fields, f.Name) {
						raisef(line, "「%s」には「%s」というフィールドがありません", q.Ctor, f.Name)
					}
				}
				walk(f.Value)
			}
		}
	}
	walk(pat)
}

func contains(xs []string, x string) bool {
	for _, y := range xs {
		if y == x {
			return true
		}
	}
	return false
}

func checkExhaustive(cases []Case, line Pos, fname string) {
	names := map[string]bool{}
	for _, c := range cases {
		if c.Guard != nil {
			continue
		}
		switch p := c.Pat.(type) {
		case *PCtor:
			names[p.Ctor] = true
			continue
		case *PNamed:
			if p.HasCtor && p.Ctor != "" {
				names[p.Ctor] = true
				continue
			}
		case *PValue:
			if v, ok := p.Expr.(*Var); ok && isNullary(v.Name) {
				names[v.Name] = true
				continue
			}
		}
		return
	}
	types := map[string]bool{}
	var tname string
	for n := range names {
		info, _ := curCtx.Ctors.Get(n)
		types[info.Type] = true
		tname = info.Type
	}
	if len(types) != 1 {
		return
	}
	all, _ := curCtx.Types.Get(tname)
	var missing []string
	for _, c := range all {
		if !names[c] {
			missing = append(missing, c)
		}
	}
	if len(missing) > 0 && fname != "" {
		raisef(line, "「%s」に「%s」の場合の定義がありません", fname, strings.Join(missing, "」「"))
	}
	if len(missing) > 0 {
		raisef(line, "「%s」の場合がありません(すべての形を書くか、最後に「そうでなければ …」を書いてください)", strings.Join(missing, "」「"))
	}
}

// --- 式の構文解析 ---

type ExprParser struct {
	tokens  []*Token
	pos     int
	stopSep bool
	inNamed bool
	noLogic bool
}

func newExprParser(tokens []*Token) *ExprParser { return &ExprParser{tokens: tokens} }

func (p *ExprParser) skip(i int) int {
	for i < len(p.tokens) && p.tokens[i].Kind == "SEP" {
		i++
	}
	return i
}

func (p *ExprParser) peek(k int) *Token {
	i := p.skip(p.pos)
	for n := 0; n < k; n++ {
		i = p.skip(i + 1)
	}
	if i < len(p.tokens) {
		return p.tokens[i]
	}
	return nil
}

func (p *ExprParser) peek0() *Token { return p.peek(0) }

func (p *ExprParser) next() *Token {
	i := p.skip(p.pos)
	if i >= len(p.tokens) {
		var last Pos
		if len(p.tokens) > 0 {
			last = p.tokens[len(p.tokens)-1].Line
		}
		raise(last, "式が途中で終わっています")
	}
	p.pos = i + 1
	return p.tokens[i]
}

func (p *ExprParser) sepHere() bool {
	return p.pos < len(p.tokens) && p.tokens[p.pos].Kind == "SEP"
}

func (p *ExprParser) sepStop() bool { return p.stopSep && p.sepHere() }

func (p *ExprParser) lastLine() Pos {
	if len(p.tokens) == 0 {
		return Pos{}
	}
	k := p.pos
	if k > len(p.tokens)-1 {
		k = len(p.tokens) - 1
	}
	return p.tokens[k].Line
}

func (p *ExprParser) parseAll() Node {
	e := p.expr()
	if t := p.peek0(); t != nil {
		if t.Kind == "RP" {
			raise(t.Line, "対応する「(」のない「)」があります")
		}
		raise(t.Line, "余分な「"+t.Value()+"」があります")
	}
	return e
}

func (p *ExprParser) expr() Node {
	if isKw(p.peek0(), KwIf) {
		ifTok := p.next()
		start := p.pos
		if m := p.matchRest(ifTok.Line); m != nil {
			return m
		}
		p.pos = start
		cond := p.expr()
		t := p.next()
		if !isKw(t, KwThen) {
			raise(t.Line, "「もし」の後に「ならば」が必要です")
		}
		then := p.expr()
		t = p.next()
		if !isKw(t, KwElse) {
			raise(t.Line, "「ならば」の後に「そうでなければ」が必要です")
		}
		other := p.expr()
		return &If{cond, then, other}
	}
	return p.logicChain()
}

func (p *ExprParser) logicChain() Node {
	left := p.andChain()
	for isKw(p.peek0(), KwMataha) && !p.sepStop() && !p.noLogic {
		t := p.next()
		left = &BinOp{KwMataha, left, p.andChain(), t.Line}
	}
	return left
}

func (p *ExprParser) andChain() Node {
	left := p.pipeline(nil, false)
	for isKw(p.peek0(), KwKatsu) && !p.sepStop() && !p.noLogic {
		t := p.next()
		left = &BinOp{KwKatsu, left, p.pipeline(nil, false), t.Line}
	}
	return left
}

func (p *ExprParser) callAhead(k int, stops ...string) bool {
	i := p.skip(p.pos)
	for n := 0; n < k; n++ {
		i = p.skip(i + 1)
	}
	depth := 0
	stopSet := setOf(append(stops, KwThen, KwElse, KwTowa)...)
	for i < len(p.tokens) {
		t := p.tokens[i]
		switch {
		case t.Kind == "LP":
			depth++
		case t.Kind == "RP":
			depth--
			if depth < 0 {
				return false
			}
		case depth == 0:
			if t.Kind == "PERIOD" || (t.Kind == "KW" && stopSet[t.S]) {
				return false
			}
			if t.Kind == "SEP" && p.stopSep {
				return false
			}
			if t.Kind == "CALL" {
				return true
			}
		}
		i++
	}
	return false
}

func (p *ExprParser) pipeline(piped Node, hasPiped bool) Node {
	for {
		var args Args
		for {
			t := p.peek0()
			if t == nil || t.Kind == "RP" || t.Kind == "PERIOD" || (t.Kind == "KW" && continuationKeywords[t.S]) {
				break
			}
			var value Node
			if t.Kind == "CALL" && t.Form == Shita {
				p.next()
				res := p.peek0()
				if res == nil || res.Kind != "WORD" || (res.S != Result && res.S != Content) {
					raise(t.Line, "「"+strings.TrimSuffix(t.S, Suru)+"した」の後には「結果」か「中身」を書いてください")
				}
				p.next()
				if hasPiped {
					args = mergePiped(args, piped, WO)
				}
				value = &Run{&Call{t.S, args, t.Line}, t.Line, res.S == Content}
				args, piped, hasPiped = nil, nil, false
			} else if t.Kind == "CALL" && t.Form != Koto {
				break
			} else if t.Kind == "CALL" {
				p.next()
				if !isPart(p.peek0(), "") {
					if hasPiped {
						key := WO
						if isPredicate(t.S) {
							key = GA
						}
						args = mergePiped(args, piped, key)
					}
					return &Ref{t.S, args, t.Line}
				}
				value = &Ref{t.S, nil, t.Line}
			} else if isKw(t, KwLambda) {
				p.next()
				if hasPiped {
					raise(t.Line, "「して」の後に「受け取って」は書けません")
				}
				value = p.lambdaRest(args, t.Line)
				args = nil
			} else {
				value = p.listExpr()
			}
			part := p.peek0()
			if isKw(part, KwGa) && p.predicateAhead(1) {
				part = tok("PART", GA, part.Line)
			}
			if isPart(part, "") {
				if part.S == WO && isKw(p.peek(1), KwReturn) {
					if len(args) > 0 || hasPiped {
						raise(part.Line, "「返すこと」の前には値を1つだけ書いてください")
					}
					return value
				}
				p.next()
				if args.Has(part.S) {
					raise(part.Line, "助詞「"+part.S+"」が1つの呼び出しで2回使われています")
				}
				args = append(args, Arg{part.S, value})
				continue
			}
			if len(args) > 0 || hasPiped {
				line := p.lastLine()
				if part != nil {
					line = part.Line
				}
				raise(line, "値の後に助詞(を・に・で・から・へ・より)か「…する」が必要です")
			}
			return value
		}
		t := p.peek0()
		if t == nil || t.Kind != "CALL" {
			line := p.lastLine()
			if t != nil {
				line = t.Line
			}
			if hasPiped {
				raise(line, "「して」の後は「…する」で終わる必要があります")
			}
			if len(args) > 0 {
				raise(line, "助詞の後に「…する」が必要です")
			}
			raise(line, "式がありません")
		}
		p.next()
		if hasPiped {
			key := WO
			if isPredicate(t.S) {
				key = GA
			}
			args = mergePiped(args, piped, key)
		}
		call := &Call{t.S, args, t.Line}
		piped = call
		hasPiped = true
		if t.Form == Suru {
			if t.Negated {
				return &Not{call, t.Line}
			}
			return call
		}
		if t.Form == Shitekara {
			cont := p.pipeline(&Var{Name: Hole, Line: t.Line}, true)
			return &Chain{call, cont, t.Line}
		}
		if t.Form == Shita {
			raise(t.Line, "「した」の後には「結果」か「中身」を書いてください")
		}
	}
}

func (p *ExprParser) matchRest(line Pos) Node {
	var pat, guard, subject Node
	err := try(func() {
		items := []Node{p.additive()}
		for isKw(p.peek0(), KwTo) {
			p.next()
			items = append(items, p.additive())
		}
		if len(items) == 1 {
			subject = items[0]
		} else {
			subject = &ListLit{items}
		}
		if isKw(p.peek0(), KwNo) && isCtor(p.peek(1)) {
			no := p.next()
			subject = &Construct{p.next().S, items, no.Line}
		}
		if !isKw(p.peek0(), KwGa) {
			subject = nil
			return
		}
		p.next()
		pat = p.pattern()
		guard = p.guard()
	})
	if err != nil || subject == nil {
		return nil
	}
	if !isKw(p.peek0(), KwThen) {
		return nil
	}
	var cases []Case
	var deflt Node
	for {
		checkPattern(pat, p.peek0().Line)
		p.next()
		cases = append(cases, Case{pat, guard, p.caseBody()})
		t := p.peek0()
		if isKw(t, KwElse) {
			p.next()
			deflt = p.caseBody()
			break
		}
		if t == nil || t.Kind == "RP" || t.Kind == "PERIOD" || !p.sepHere() {
			break
		}
		pat = p.pattern()
		guard = p.guard()
		t = p.peek0()
		if !isKw(t, KwThen) {
			l := p.lastLine()
			if t != nil {
				l = t.Line
			}
			raise(l, "場合の後に「ならば」が必要です")
		}
	}
	if deflt == nil {
		checkExhaustive(cases, line, "")
	}
	return &Match{subject, cases, deflt, line, ""}
}

func (p *ExprParser) caseBody() Node {
	save := p.stopSep
	p.stopSep = true
	defer func() { p.stopSep = save }()
	return p.expr()
}

func (p *ExprParser) comparesAt(k int) bool {
	t := p.peek(k)
	return isKw(t, KwGa) || (t != nil && t.Kind == "OP" && compareOps[t.S])
}

var compareOps = setOf("==", "!=", "<", ">", "<=", ">=")

func (p *ExprParser) atNamed() bool {
	t0, t1 := p.peek0(), p.peek(1)
	return t0 != nil && t0.Kind == "WORD" && isKw(t1, KwWa)
}

func (p *ExprParser) pattern() Node {
	if p.atNamed() {
		return p.namedPattern()
	}
	if c := p.tryCtorPattern(); c != nil {
		return c
	}
	save := p.noLogic
	p.noLogic = true
	defer func() { p.noLogic = save }()
	return &PValue{p.listExpr()}
}

func (p *ExprParser) guard() Node {
	if !isKw(p.peek0(), KwKatsu) {
		return nil
	}
	p.next()
	save := p.noLogic
	p.noLogic = false
	defer func() { p.noLogic = save }()
	return p.logicChain()
}

func (p *ExprParser) paramPattern() Node {
	if p.atNamed() {
		return p.namedPattern()
	}
	if c := p.tryCtorPattern(); c != nil {
		return c
	}
	items := []Node{p.patternItem()}
	for isKw(p.peek0(), KwTo) {
		p.next()
		items = append(items, p.patternItem())
	}
	if len(items) == 1 {
		return items[0]
	}
	return &PSeq{items}
}

func (p *ExprParser) tryCtorPattern() Node {
	start := p.pos
	var items []Node
	err := try(func() {
		items = []Node{p.patternItem()}
		for isKw(p.peek0(), KwTo) {
			p.next()
			items = append(items, p.patternItem())
		}
	})
	if err != nil {
		p.pos = start
		return nil
	}
	if isKw(p.peek0(), KwNo) && isCtor(p.peek(1)) {
		no := p.next()
		return &PCtor{p.next().S, items, no.Line}
	}
	if len(items) == 1 {
		if c, ok := items[0].(*PCtor); ok {
			return c
		}
	}
	p.pos = start
	return nil
}

func (p *ExprParser) patternItem() Node {
	t := p.next()
	if t.Kind == "WORD" {
		if isNullary(t.S) {
			return &PCtor{t.S, nil, t.Line}
		}
		if !t.Quoted && isAllHiragana(t.S) {
			panic(hiraganaNameError(t.S, t.Line))
		}
		return &PBind{t.S}
	}
	if t.Kind == "NUM" {
		return &PValue{&Num{Value: t.N}}
	}
	if t.Kind == "STR" {
		return &PValue{&Str{Value: t.S}}
	}
	if t.Kind == "OP" && t.S == "-" && p.peek0() != nil && p.peek0().Kind == "NUM" {
		return &PValue{&Num{Value: p.next().N.Neg()}}
	}
	if t.Kind == "LP" {
		save := p.stopSep
		p.stopSep = false
		inner := p.pattern()
		p.stopSep = save
		cl := p.next()
		if cl.Kind != "RP" {
			raise(cl.Line, "「)」が必要です")
		}
		return inner
	}
	raise(t.Line, "パターンに「"+t.Value()+"」は書けません")
	return nil
}

func (p *ExprParser) namedPattern() Node {
	line := p.peek0().Line
	var fields []FieldVal
	for {
		name := p.next()
		p.next()
		for _, f := range fields {
			if f.Name == name.Value() {
				raise(name.Line, "「"+name.Value()+"」が2回書かれています")
			}
		}
		fields = append(fields, FieldVal{name.Value(), p.patternItem()})
		if p.namedContinues() {
			p.next()
			continue
		}
		break
	}
	pn := &PNamed{Fields: fields, Line: line}
	if isKw(p.peek0(), KwNo) && isCtor(p.peek(1)) {
		p.next()
		pn.Ctor = p.next().S
		pn.HasCtor = true
	}
	return pn
}

func (p *ExprParser) namedContinues() bool {
	t2 := p.peek(2)
	return isPart(p.peek0(), "で") && p.peek(1) != nil && p.peek(1).Kind == "WORD" && isKw(t2, KwWa)
}

func (p *ExprParser) namedConstruct() Node {
	line := p.peek0().Line
	var fields []FieldVal
	for {
		name := p.next()
		p.next()
		for _, f := range fields {
			if f.Name == name.Value() {
				raise(name.Line, "「"+name.Value()+"」が2回書かれています")
			}
		}
		p.inNamed = true
		var value Node
		func() {
			defer func() { p.inNamed = false }()
			value = p.comparison()
		}()
		fields = append(fields, FieldVal{name.Value(), value})
		if p.namedContinues() {
			p.next()
			continue
		}
		break
	}
	last := fields[len(fields)-1]
	if f, ok := last.Value.(*Field); ok && !isKw(p.peek0(), KwNo) {
		fields[len(fields)-1] = FieldVal{last.Name, f.Target}
		return &Update{&Var{Name: f.Name, Line: f.Line}, fields, line}
	}
	if !isKw(p.peek0(), KwNo) {
		raise(line, "「名前 は 値」の後に「の 型名」が必要です(例: 横 は 3 で 縦 は 4 の 点)")
	}
	p.next()
	t := p.peek0()
	if isCtor(t) {
		p.next()
		return &NamedConstruct{t.S, fields, line}
	}
	return &Update{p.atom(), fields, line}
}

func (p *ExprParser) lambdaRest(args Args, line Pos) Node {
	var params []Param
	for _, a := range args {
		pp := toPattern(a.Value, line)
		pp.Part = a.Part
		params = append(params, pp)
	}
	checkParams(params, line)
	body := p.expr()
	t := p.peek0()
	if t == nil {
		raise(p.lastLine(), "「受け取って」の後は「… を 返すこと」で終わる必要があります")
	}
	p.next()
	if !isPart(t, WO) || !isKw(p.peek0(), KwReturn) {
		raise(t.Line, "「受け取って」の後は「… を 返すこと」で終わる必要があります")
	}
	p.next()
	return &Lambda{params, body, line}
}

func (p *ExprParser) listExpr() Node {
	if p.atNamed() {
		return p.namedConstruct()
	}
	items := []Node{p.logic()}
	for isKw(p.peek0(), KwTo) && !p.sepStop() {
		p.next()
		items = append(items, p.logic())
	}
	if isKw(p.peek0(), KwNo) && isCtor(p.peek(1)) && !p.sepStop() {
		no := p.next()
		node := &Construct{p.next().S, items, no.Line}
		if isKw(p.peek0(), KwTo) {
			raise(no.Line, "組を「と」で並べるときは、（1 と 2 の 点） と （3 と 4 の 点） のように括弧で囲んでください")
		}
		return node
	}
	if len(items) == 1 {
		return items[0]
	}
	return &ListLit{items}
}

func (p *ExprParser) logic() Node {
	left := p.conjunction()
	for isKw(p.peek0(), KwMataha) && !p.sepStop() && !p.noLogic && !p.callAhead(1, KwMataha) {
		t := p.next()
		left = &BinOp{KwMataha, left, p.conjunction(), t.Line}
	}
	return left
}

func (p *ExprParser) conjunction() Node {
	left := p.comparison()
	for isKw(p.peek0(), KwKatsu) && !p.sepStop() && !p.noLogic && !p.callAhead(1, KwKatsu, KwMataha) {
		t := p.next()
		left = &BinOp{KwKatsu, left, p.comparison(), t.Line}
	}
	return left
}

var predStops = setOf(KwThen, KwElse, KwGa, KwTowa, KwKatsu, KwMataha)

func (p *ExprParser) predicateAhead(k int) bool {
	i := p.skip(p.pos)
	for n := 0; n < k; n++ {
		i = p.skip(i + 1)
	}
	depth := 0
	for i < len(p.tokens) {
		t := p.tokens[i]
		switch {
		case t.Kind == "LP":
			depth++
		case t.Kind == "RP":
			depth--
			if depth < 0 {
				return false
			}
		case depth == 0:
			if t.Kind == "PERIOD" || (t.Kind == "KW" && predStops[t.S]) {
				return false
			}
			if t.Kind == "SEP" && p.stopSep {
				return false
			}
			if t.Kind == "CALL" {
				if t.Form == Koto && i+1 < len(p.tokens) && p.tokens[i+1].Kind == "PART" {
					i++
					continue
				}
				return isPredicate(t.S) && t.Form == Suru
			}
		}
		i++
	}
	return false
}

func (p *ExprParser) comparison() Node {
	left := p.additive()
	if isKw(p.peek0(), KwNo) && isCtor(p.peek(1)) && p.comparesAt(2) {
		no := p.next()
		left = &Construct{p.next().S, []Node{left}, no.Line}
	}
	t := p.peek0()
	if p.sepStop() {
		return left
	}
	if isKw(t, KwGa) && !p.predicateAhead(1) {
		p.next()
		right := p.additive()
		if isKw(p.peek0(), KwNo) && isCtor(p.peek(1)) {
			no := p.next()
			right = &Construct{p.next().S, []Node{right}, no.Line}
		}
		return &BinOp{"==", left, right, t.Line}
	}
	if t != nil && t.Kind == "OP" && compareOps[t.S] {
		p.next()
		right := p.additive()
		return &BinOp{t.S, left, right, t.Line}
	}
	return left
}

func (p *ExprParser) additive() Node {
	left := p.term()
	for {
		t := p.peek0()
		if t == nil || t.Kind != "OP" || (t.S != "+" && t.S != "-") || p.sepStop() {
			return left
		}
		p.next()
		left = &BinOp{t.S, left, p.term(), t.Line}
	}
}

func (p *ExprParser) term() Node {
	left := p.unary()
	for {
		t := p.peek0()
		if t == nil || t.Kind != "OP" || (t.S != "*" && t.S != "/" && t.S != "%") || p.sepStop() {
			return left
		}
		p.next()
		left = &BinOp{t.S, left, p.unary(), t.Line}
	}
}

func (p *ExprParser) unary() Node {
	t := p.peek0()
	if t != nil && t.Kind == "OP" && t.S == "-" {
		p.next()
		return &Neg{p.unary()}
	}
	return p.power()
}

func (p *ExprParser) power() Node {
	base := p.postfix()
	t := p.peek0()
	if t != nil && t.Kind == "OP" && t.S == "^" && !p.sepStop() {
		p.next()
		return &BinOp{"^", base, p.unary(), t.Line}
	}
	return base
}

func sortedProps() string {
	var ps []string
	for k := range properties {
		ps = append(ps, k)
	}
	sort.Strings(ps)
	return strings.Join(ps, "・")
}

func (p *ExprParser) postfix() Node {
	node := p.atom()
	for isKw(p.peek0(), KwNo) && !p.sepStop() {
		nxt := p.peek(1)
		if isCtor(nxt) || (p.inNamed && nxt != nil && nxt.Kind == "LP") {
			break
		}
		no := p.next()
		name := p.next()
		if name.Kind != "WORD" {
			raise(no.Line, "「の」の後には "+sortedProps()+" かフィールドの名前を書いてください")
		}
		switch {
		case name.S == "それぞれ":
			node = &Each{node, no.Line}
		case properties[name.S]:
			node = &Prop{node, name.S, no.Line}
		default:
			node = &Field{node, name.S, no.Line}
		}
	}
	return node
}

func (p *ExprParser) parenBlock(open *Token) Node {
	depth, i, isBlock := 0, p.pos, false
	found := false
	for i < len(p.tokens) {
		t := p.tokens[i]
		if t.Kind == "LP" {
			depth++
		} else if t.Kind == "RP" {
			if depth == 0 {
				found = true
				break
			}
			depth--
		} else if depth == 0 && (t.Kind == "PERIOD" || isKw(t, KwTowa)) {
			isBlock = true
		}
		i++
	}
	if !found {
		raise(open.Line, "「(」に対応する「)」がありません")
	}
	if !isBlock {
		return nil
	}
	inner := append(append([]*Token{}, p.tokens[p.pos:i]...), tok("PERIOD", Period, open.Line))
	p.pos = i + 1
	sentences := splitSentences(inner)
	if len(sentences) == 0 {
		raise(open.Line, "括弧の中に式がありません")
	}
	var nodes []*LNode
	for _, s := range sentences {
		nodes = append(nodes, &LNode{Line: &Line{0, s, s[0].Line, true}})
	}
	return parseBlock(nodes)
}

func (p *ExprParser) parenDo(open *Token) Node {
	depth, i := 0, p.pos
	found := false
	for i < len(p.tokens) {
		t := p.tokens[i]
		if t.Kind == "LP" {
			depth++
		} else if t.Kind == "RP" {
			if depth == 0 {
				found = true
				break
			}
			depth--
		}
		i++
	}
	if !found {
		raise(open.Line, "「(」に対応する「)」がありません")
	}
	inner := append(append([]*Token{}, p.tokens[p.pos:i]...), tok("PERIOD", Period, open.Line))
	p.pos = i + 1
	var nodes []*LNode
	for _, x := range splitSentences(inner) {
		x = stripSeps(x)
		if len(x) > 0 {
			nodes = append(nodes, &LNode{Line: &Line{0, x, x[0].Line, true}})
		}
	}
	if len(nodes) == 0 {
		raise(open.Line, "手順の中に文がありません")
	}
	return parseDo(nodes, open.Line)
}

func (p *ExprParser) atom() Node {
	t := p.next()
	switch t.Kind {
	case "NUM":
		return &Num{t.N, t.Line}
	case "STR":
		return &Str{t.S, t.Line}
	case "WORD":
		var nxt *Token
		if p.pos < len(p.tokens) {
			nxt = p.tokens[p.pos]
		}
		if t.S == Tejun && !t.Quoted && nxt != nil && nxt.Kind == "LP" {
			p.next()
			return p.parenDo(nxt)
		}
		return &Var{t.S, t.Line, t.Quoted}
	case "LP":
		if b := p.parenBlock(t); b != nil {
			return b
		}
		save := p.stopSep
		p.stopSep = false
		inner := p.expr()
		p.stopSep = save
		cl := p.next()
		if cl.Kind != "RP" {
			raise(cl.Line, "「)」が必要です")
		}
		return inner
	case "CALL":
		if t.Form == Koto {
			return &Ref{t.S, nil, t.Line}
		}
	}
	raise(t.Line, "ここに「"+t.Value()+"」は書けません")
	return nil
}

// --- 文 ---

func parseDefinitionHead(tokens []*Token, line Pos) (string, []Param, bool) {
	tokens = nosep(tokens)
	if len(tokens) == 0 {
		raise(line, "「とは」の前に定義する名前が必要です")
	}
	last := tokens[len(tokens)-1]
	if last.Kind == "CALL" && isPredicate(last.S) {
		if last.Negated {
			raise(last.Line, "述語は「…である」の形で定義してください(「…でない」は自動で使えます)")
		}
		nt := make([]*Token, len(tokens))
		for i, t := range tokens {
			if isKw(t, KwGa) {
				nt[i] = tok("PART", GA, t.Line)
			} else {
				nt[i] = t
			}
		}
		tokens = nt
	}
	for _, t := range tokens {
		if t.Kind == "WORD" && !t.Quoted && isAllHiragana(t.S) && t.S != "それぞれ" {
			panic(hiraganaNameError(t.S, t.Line))
		}
	}
	if last.Kind == "WORD" && len(tokens) == 1 {
		return last.S, nil, false
	}
	if last.Kind != "CALL" || last.Form != Suru {
		raise(last.Line, "関数名は「する」で終わる必要があります")
	}
	for _, t := range tokens[:len(tokens)-1] {
		if isPatternToken(t) {
			return last.S, parsePatternHead(tokens[:len(tokens)-1], line), true
		}
	}
	var params []Param
	var names []string
	var prev *Token
	for _, t := range tokens[:len(tokens)-1] {
		switch {
		case t.Kind == "WORD":
			if len(names) > 0 && !isKw(prev, KwTo) {
				raise(t.Line, "引数名の後には助詞(を・に・で・から・へ・より)が必要です")
			}
			names = append(names, t.S)
		case isKw(t, KwTo):
			if len(names) == 0 || prev.Kind != "WORD" {
				raise(t.Line, "「と」の前に引数名が必要です")
			}
		case t.Kind == "PART":
			if len(names) == 0 || prev.Kind != "WORD" {
				raise(t.Line, "助詞「"+t.S+"」の前に引数名が必要です")
			}
			for _, q := range params {
				if q.Part == t.S {
					raise(t.Line, "助詞「"+t.S+"」が2回使われています(1つの関数で各助詞は1回まで)")
				}
			}
			if len(names) == 1 {
				params = append(params, Param{Part: t.S, Name: names[0]})
			} else {
				params = append(params, Param{Part: t.S, Names: names, List: true})
			}
			names = nil
		default:
			raise(t.Line, "引数名に「"+t.Value()+"」は使えません")
		}
		prev = t
	}
	if len(names) > 0 {
		raise(line, "引数名の後には助詞(を・に・で・から・へ・より)が必要です")
	}
	checkParams(params, line)
	return last.S, params, true
}

func isPatternToken(t *Token) bool {
	switch t.Kind {
	case "NUM", "STR", "LP", "RP", "OP":
		return true
	}
	if t.Kind == "KW" && (t.S == KwNo || t.S == KwWa) {
		return true
	}
	return t.Kind == "WORD" && isNullary(t.S)
}

func parsePatternHead(tokens []*Token, line Pos) []Param {
	type seg struct {
		part string
		toks []*Token
	}
	var segments []seg
	var cur []*Token
	depth := 0
	for k, t := range tokens {
		if t.Kind == "LP" {
			depth++
		} else if t.Kind == "RP" {
			depth--
		}
		namedAnd := isPart(t, "で") && k+2 < len(tokens) && tokens[k+1].Kind == "WORD" && isKw(tokens[k+2], KwWa)
		if t.Kind == "PART" && depth == 0 && !namedAnd {
			if len(cur) == 0 {
				raise(t.Line, "助詞「"+t.S+"」の前に引数が必要です")
			}
			for _, s := range segments {
				if s.part == t.S {
					raise(t.Line, "助詞「"+t.S+"」が2回使われています(1つの関数で各助詞は1回まで)")
				}
			}
			segments = append(segments, seg{t.S, cur})
			cur = nil
		} else {
			cur = append(cur, t)
		}
	}
	if len(cur) > 0 {
		raise(cur[len(cur)-1].Line, "引数の後には助詞(を・に・で・から・へ・より)が必要です")
	}
	var params []Param
	var pats []Node
	for _, s := range segments {
		parser := newExprParser(s.toks)
		pat := parser.paramPattern()
		if rest := parser.peek0(); rest != nil {
			raise(rest.Line, "引数のパターンに「"+rest.Value()+"」は書けません")
		}
		params = append(params, Param{Part: s.part, Pat: pat})
		pats = append(pats, pat)
	}
	checkPattern(&PSeq{pats}, line)
	return params
}

func paramToPattern(p Param) Node {
	if p.Pat != nil {
		return p.Pat
	}
	if !p.List {
		return &PBind{p.Name}
	}
	var items []Node
	for _, n := range p.Names {
		items = append(items, &PBind{n})
	}
	return &PSeq{items}
}

func sortedParts(ps []string) []string {
	out := append([]string{}, ps...)
	sort.Strings(out)
	return out
}

func eqStrings(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func paramParts(ps []Param) []string {
	out := make([]string, len(ps))
	for i, p := range ps {
		out[i] = p.Part
	}
	return out
}

func combineClauses(group []*Define) *Define {
	first := group[0]
	name := first.Name
	order := paramParts(first.Params)
	for _, d := range group[1:] {
		if !eqStrings(sortedParts(paramParts(d.Params)), sortedParts(order)) {
			o := strings.Join(order, "・")
			if o == "" {
				o = "なし"
			}
			raisef(d.Line, "「%s」の定義ごとに助詞が違います(場合ごとに定義するときは、どれも同じ助詞で書いてください。%d行目は「%s」)",
				name, first.Line.Line, o)
		}
	}
	slot := map[string]string{}
	for _, p := range order {
		slot[p] = "（" + p + "）"
	}
	var cases []Case
	for k, d := range group {
		pats := map[string]Node{}
		for _, p := range d.Params {
			pats[p.Part] = paramToPattern(p)
		}
		var items []Node
		allAny := true
		for _, p := range order {
			items = append(items, pats[p])
			if _, ok := pats[p].(*PBind); !ok {
				allAny = false
			}
		}
		var pat Node
		if len(items) == 1 {
			pat = items[0]
		} else {
			pat = &PSeq{items}
		}
		if k+1 < len(group) && allAny {
			raisef(d.Line, "「%s」のこの定義はどんな値にも当てはまるので、%d行目からの定義が使われません(決まった値や形の場合を先に書いてください)",
				name, group[k+1].Line.Line)
		}
		cases = append(cases, Case{pat, nil, d.Body})
	}
	var subject Node
	if len(order) == 1 {
		subject = &Var{Name: slot[order[0]], Line: first.Line}
		checkExhaustive(cases, first.Line, name)
	} else {
		var vs []Node
		for _, p := range order {
			vs = append(vs, &Var{Name: slot[p], Line: first.Line})
		}
		subject = &ListLit{vs}
	}
	body := &Match{subject, cases, nil, first.Line, name}
	var params []Param
	for _, p := range order {
		params = append(params, Param{Part: p, Name: slot[p]})
	}
	return &Define{name, params, body, true, first.Line}
}

func mergeClauses(statements []Node) []Node {
	var out []Node
	seen := map[string]Pos{}
	i := 0
	isFn := func(s Node) (*Define, bool) {
		d, ok := s.(*Define)
		return d, ok && d.IsFunction
	}
	for i < len(statements) {
		s, ok := isFn(statements[i])
		if !ok {
			out = append(out, statements[i])
			i++
			continue
		}
		j := i + 1
		for j < len(statements) {
			d, ok := isFn(statements[j])
			if !ok || d.Name != s.Name {
				break
			}
			j++
		}
		var group []*Define
		for _, x := range statements[i:j] {
			group = append(group, x.(*Define))
		}
		if l, ok := seen[s.Name]; ok {
			raisef(s.Line, "「%s」は%d行目でも定義されています(場合ごとに定義するときは続けて書いてください)", s.Name, l.Line)
		}
		seen[s.Name] = s.Line
		allSimple := true
		for _, p := range s.Params {
			if !p.simple() {
				allSimple = false
			}
		}
		if len(group) == 1 && allSimple {
			out = append(out, s)
		} else {
			out = append(out, combineClauses(group))
		}
		i = j
	}
	return out
}

func mergeDefs(ds []*Define) []*Define {
	ns := mergeClauses(defNodes(ds))
	out := make([]*Define, len(ns))
	for i, n := range ns {
		out[i] = n.(*Define)
	}
	return out
}

func findTopLevel(tokens []*Token, value string) int {
	depth := 0
	for i, t := range tokens {
		switch {
		case t.Kind == "LP":
			depth++
		case t.Kind == "RP":
			depth--
		case depth == 0 && isKw(t, value):
			return i
		}
	}
	return -1
}

func indexOf(raw []*Token, t *Token) int {
	for i, x := range raw {
		if x == t {
			return i
		}
	}
	return -1
}

func withChildren(tokens []*Token, children []*LNode) []*Token {
	out := append([]*Token{}, tokens...)
	for _, c := range children {
		out = append(out, tok("SEP", "", c.Line.Number))
		out = append(out, flatten(c)...)
	}
	return out
}

func parseStatement(node *LNode) Node {
	raw := node.Line.Tokens
	tokens := nosep(raw)
	if isKw(tokens[0], KwSorekara) {
		rest := raw[indexOf(raw, tokens[0])+1:]
		inner := &LNode{&Line{node.Line.Indent, rest, node.Line.Number, node.Line.Closed}, node.Children}
		if len(nosep(flatten(inner))) == 0 {
			raise(tokens[0].Line, "「それから」の後に文が必要です")
		}
		stmt := parseStatement(inner)
		switch stmt.(type) {
		case *Define, *Proviso, *Sequel:
			raise(tokens[0].Line, "「それから」の後には行うこと(式)を書いてください")
		}
		if isTopLevelOnly(stmt) {
			raise(tokens[0].Line, "「それから」の後には行うこと(式)を書いてください")
		}
		return &Sequel{stmt, tokens[0].Line}
	}
	if isKw(tokens[0], KwProviso) {
		rest := raw[indexOf(raw, tokens[0])+1:]
		if len(nosep(rest)) == 0 {
			raise(tokens[0].Line, "「ただし」の後に定義が必要です")
		}
		inner := &LNode{&Line{node.Line.Indent, rest, node.Line.Number, node.Line.Closed}, node.Children}
		if findTopLevel(nosep(rest), KwTowa) < 0 {
			head := nosep(flatten(inner))
			last := head[len(head)-1]
			if last.Kind != "CALL" || last.Form != Suru {
				raise(tokens[0].Line, "「ただし」の後には「…とは」の定義を書いてください")
			}
			name, params, _ := parseDefinitionHead(head, node.Line.Number)
			return &Proviso{nil, tokens[0].Line, &Sig{name, params}}
		}
		st := parseStatement(inner)
		d, ok := st.(*Define)
		if !ok {
			raise(tokens[0].Line, "「ただし」の後には「…とは」の定義を書いてください")
		}
		return &Proviso{d, tokens[0].Line, nil}
	}
	if vis := tryParseVisibility(nosep(flatten(node))); vis != nil {
		return vis
	}
	if td := tryParseTypedef(node); td != nil {
		return td
	}
	towa := findTopLevel(tokens, KwTowa)
	if towa < 0 {
		if sig := tryParseTypeSig(nosep(flatten(node))); sig != nil {
			return sig
		}
		if len(tokens) == 3 && tokens[0].Kind == "WORD" && isKw(tokens[1], KwWa) && tokens[2].Kind == "WORD" {
			return parseTraitImpl(node, tokens)
		}
		return newExprParser(flatten(node)).parseAll()
	}
	head := tokens[:towa]
	after := raw[indexOf(raw, tokens[towa])+1:]
	if len(head) == 3 && head[0].Kind == "WORD" && isKw(head[1], KwToiu) && isKw(head[2], KwSeishitsu) {
		return parseTraitDecl(node, head[0], after)
	}
	name, params, isFunction := parseDefinitionHead(head, node.Line.Number)
	if strings.Contains(name, ModuleSep) {
		raise(head[0].Line, "「"+name+"」: 読み込んだファイルの中の名前は定義できません")
	}
	afterT := nosep(after)
	if len(afterT) == 1 && afterT[0].Kind == "WORD" && afterT[0].S == Tejun && !afterT[0].Quoted && len(node.Children) > 0 {
		return &Define{name, params, parseDo(node.Children, node.Line.Number), isFunction, node.Line.Number}
	}
	if len(afterT) == 2 && afterT[0].Kind == "WORD" && afterT[0].S == KwExtern && !afterT[0].Quoted &&
		afterT[1].Kind == "STR" && len(node.Children) == 0 {
		// 「x を 余弦にする とは 外部の「cos」」: C の関数を呼ぶ
		sym := afterT[1].S
		if !isCSymbol(sym) {
			raise(afterT[1].Line, "「"+sym+"」は C の関数の名前ではありません")
		}
		if strings.HasPrefix(sym, "rt_") || strings.HasPrefix(sym, "suru_") {
			raise(afterT[1].Line, "「"+sym+"」は「する」の実行時が使う名前なので、外部の関数にできません")
		}
		return &Define{name, params, &Extern{Symbol: sym, Line: afterT[1].Line}, isFunction, node.Line.Number}
	}
	if len(afterT) == 4 && afterT[0].Kind == "WORD" && afterT[0].S == KwExtern && !afterT[0].Quoted &&
		afterT[1].Kind == "LP" && afterT[2].Kind == "WORD" && afterT[3].Kind == "RP" && len(node.Children) == 0 {
		// 「x を f で 呼ぶ とは 外部の（f）」: 引数 f の番地にある C の関数を呼ぶ
		return &Define{name, params, &Extern{Line: afterT[2].Line, Pointer: afterT[2].S}, isFunction, node.Line.Number}
	}
	var body Node
	if len(afterT) > 0 {
		body = newExprParser(withChildren(after, node.Children)).parseAll()
	} else {
		if len(node.Children) == 0 {
			raise(node.Line.Number, "「とは」の後に本体が必要です")
		}
		body = parseBlock(node.Children)
	}
	return &Define{name, params, body, isFunction, node.Line.Number}
}

func isTypeWord(t *Token) bool {
	if t.Kind != "WORD" {
		return false
	}
	return builtinTypeSet[t.S] || curCtx.Types.Has(t.S) || (len([]rune(t.S)) == 1 && strings.Contains(typeVarNames, t.S))
}

func tryParseTypeSig(tokens []*Token) Node {
	ha := findTopLevel(tokens, KwWa)
	if ha <= 0 || ha == len(tokens)-1 {
		return nil
	}
	left, right := tokens[:ha], tokens[ha+1:]
	line := tokens[0].Line
	last := left[len(left)-1]
	if last.Kind == "CALL" && last.Form == Suru && !last.Negated {
		var params []TypeParam
		i := 0
		for i < len(left)-1 {
			var t Node
			t, i = parseType(left, i)
			if i >= len(left)-1 || !(left[i].Kind == "PART" || isKw(left[i], GA)) {
				raise(line, "型の宣言では、引数の型の後に助詞を書いてください(「数 を 階乗する は 数」)")
			}
			params = append(params, TypeParam{left[i].S, t})
			i++
		}
		name := last.S
		for k, a := range params {
			for _, b := range params[:k] {
				if a.Part == b.Part {
					raise(line, "「"+name+"」の型の宣言で同じ助詞が2回使われています")
				}
			}
		}
		return &TypeSig{name, params, true, parseTypeAll(right, line), line}
	}
	if len(left) == 1 && left[0].Kind == "WORD" && len(right) > 0 && (isTypeWord(right[0]) || right[0].Kind == "LP") {
		if len(right) == 1 && !isTypeWord(right[0]) {
			return nil
		}
		return &TypeSig{checkName(left[0]), nil, false, parseTypeAll(right, line), line}
	}
	return nil
}

func parseTypeAll(tokens []*Token, line Pos) Node {
	if len(tokens) == 0 {
		raise(line, "「は」の後に型を書いてください")
	}
	t, i := parseType(tokens, 0)
	if i != len(tokens) {
		raise(tokens[i].Line, "型の書き方が正しくありません(「"+tokens[i].Value()+"」)")
	}
	return t
}

func matching(tokens []*Token, i int) int {
	depth := 0
	for j := i; j < len(tokens); j++ {
		if tokens[j].Kind == "LP" {
			depth++
		} else if tokens[j].Kind == "RP" {
			depth--
			if depth == 0 {
				return j
			}
		}
	}
	raise(tokens[i].Line, "「（」が閉じていません")
	return 0
}

func parseType(tokens []*Token, i int) (Node, int) {
	if i >= len(tokens) {
		raise(tokens[len(tokens)-1].Line, "型が必要です")
	}
	t0 := tokens[i]
	var args []Node
	hasArgs := false
	var t Node
	if t0.Kind == "LP" {
		j := matching(tokens, i)
		inner := tokens[i+1 : j]
		i = j + 1
		if findTopLevel(inner, KwReturn) >= 0 {
			t = parseFunType(inner, t0.Line)
		} else if findTopLevel(inner, KwTo) >= 0 {
			for _, part := range splitTopLevel(inner, KwTo) {
				args = append(args, parseTypeAll(part, t0.Line))
			}
			hasArgs = true
		} else {
			t = parseTypeAll(inner, t0.Line)
		}
	} else if t0.Kind == "WORD" {
		t = typeWord(t0, nil)
		i++
	} else {
		raise(t0.Line, "「"+t0.Value()+"」は型ではありません")
	}
	for i+1 < len(tokens) && isKw(tokens[i], KwNo) && tokens[i+1].Kind == "WORD" {
		a := args
		if !hasArgs {
			a = []Node{t}
		}
		t = typeWord(tokens[i+1], a)
		args, hasArgs = nil, false
		i += 2
	}
	if hasArgs {
		raise(t0.Line, "「（甲 と 乙）」の後には「の 型名」が必要です")
	}
	return t, i
}

func typeWord(t *Token, args []Node) Node {
	name := t.S
	if len([]rune(name)) == 1 && strings.Contains(typeVarNames, name) && !t.Quoted {
		if len(args) > 0 {
			raise(t.Line, "「"+name+"」は型の引数をとりません")
		}
		return &TypeVarName{name}
	}
	if (name == "数" || name == "文字列" || name == "真偽" || name == "小数" || name == "整数" || name == "番地" || name == "バイト列" || name == "無") && len(args) > 0 {
		raise(t.Line, "「"+name+"」は型の引数をとりません")
	}
	if (name == "リスト" || name == "動作") && len(args) != 1 {
		raise(t.Line, "「"+name+"」の前には型を1つ書いてください(「数 の "+name+"」)")
	}
	if !builtinTypeSet[name] && !curCtx.Types.Has(name) {
		raise(t.Line, "「"+name+"」という型はありません")
	}
	return &TypeName{name, append([]Node{}, args...)}
}

func parseFunType(tokens []*Token, line Pos) Node {
	k := findTopLevel(tokens, KwLambda)
	var params []TypeParam
	var rest []*Token
	if k >= 0 {
		i := 0
		for i < k {
			var t Node
			t, i = parseType(tokens[:k], i)
			if i >= k || !(tokens[i].Kind == "PART" || isKw(tokens[i], GA)) {
				raise(line, "関数の型では、引数の型の後に助詞を書いてください")
			}
			params = append(params, TypeParam{tokens[i].S, t})
			i++
		}
		rest = tokens[k+1:]
	} else {
		rest = tokens
	}
	if len(rest) < 3 || !(rest[len(rest)-2].Kind == "PART" && rest[len(rest)-2].S == "を") || !isKw(rest[len(rest)-1], KwReturn) {
		raise(line, "関数の型は「（数 を 受け取って 数 を 返すこと）」のように書きます")
	}
	return &TypeFun{params, parseTypeAll(rest[:len(rest)-2], line)}
}

func splitTopLevel(tokens []*Token, value string) [][]*Token {
	var out [][]*Token
	var cur []*Token
	depth := 0
	for _, t := range tokens {
		if t.Kind == "LP" {
			depth++
		} else if t.Kind == "RP" {
			depth--
		}
		if depth == 0 && isKw(t, value) {
			out = append(out, cur)
			cur = nil
		} else {
			cur = append(cur, t)
		}
	}
	return append(out, cur)
}

func checkName(t *Token) string {
	if t.Kind != "WORD" {
		raise(t.Line, "名前に「"+t.Value()+"」は使えません")
	}
	if !t.Quoted && isAllHiragana(t.S) {
		panic(hiraganaNameError(t.S, t.Line))
	}
	if strings.Contains(t.S, ModuleSep) {
		raise(t.Line, "「"+t.S+"」: 読み込んだファイルの中の名前は定義できません")
	}
	return t.S
}

func tryParseTypedef(node *LNode) *TypeDef {
	tokens := nosep(flatten(node))
	towa := findTopLevel(tokens, KwTowa)
	if towa != 1 || tokens[0].Kind != "WORD" {
		return nil
	}
	body := tokens[2:]
	hasKa := findTopLevel(body, KwKa) >= 0
	if len(body) == 0 || !(hasKa || isKw(body[len(body)-1], KwKumi)) {
		return nil
	}
	name := checkName(tokens[0])
	line := tokens[0].Line
	var ctors []Ctor
	for _, alt := range splitTopLevel(body, KwKa) {
		if len(alt) == 0 {
			raise(line, "「か」の前後に形を書いてください")
		}
		if len(alt) == 1 && alt[0].Kind == "WORD" {
			ctors = append(ctors, Ctor{checkName(alt[0]), nil})
			continue
		}
		if len(alt) < 3 || !isKw(alt[len(alt)-2], KwNo) {
			raise(alt[0].Line, "型の形は「横 と 縦 の 点」のように「フィールド名 と … の 形の名前」で書いてください")
		}
		last := alt[len(alt)-1]
		var cname string
		if isKw(last, KwKumi) {
			if hasKa {
				raise(last.Line, "「組」は形が1つのときだけ使えます(「か」で並べるときは形に名前を付けてください)")
			}
			cname = name
		} else {
			cname = checkName(last)
		}
		var fields []string
		for i, t := range alt[:len(alt)-2] {
			if i%2 == 1 {
				if !isKw(t, KwTo) {
					raise(t.Line, "フィールド名は「と」で区切ってください")
				}
				continue
			}
			f := checkName(t)
			if contains(fields, f) {
				raise(t.Line, "フィールド名「"+f+"」が2回書かれています")
			}
			fields = append(fields, f)
		}
		if len(alt[:len(alt)-2])%2 == 0 {
			raise(last.Line, "「と」の後にフィールド名が必要です")
		}
		ctors = append(ctors, Ctor{cname, fields})
	}
	return &TypeDef{name, ctors, line}
}

func functionDefine(stmt Node, what string, line Pos) *Define {
	d, ok := stmt.(*Define)
	if !ok || !d.IsFunction {
		raise(line, what+"には「…する とは …」の関数の定義を書いてください")
	}
	return d
}

func parseTraitDecl(node *LNode, nameTok *Token, after []*Token) Node {
	name := checkName(nameTok)
	line := node.Line.Number
	var members []*LNode
	if len(nosep(after)) > 0 {
		members = []*LNode{{&Line{node.Line.Indent, after, line, node.Line.Closed}, node.Children}}
	} else {
		members = node.Children
	}
	decl := &TraitDecl{Name: name, Line: line}
	for _, m := range members {
		if findTopLevel(nosep(m.Line.Tokens), KwTowa) >= 0 {
			decl.Defaults = append(decl.Defaults, functionDefine(parseStatement(m), "性質の中", m.Line.Number))
			continue
		}
		head := nosep(flatten(m))
		last := head[len(head)-1]
		if last.Kind != "CALL" || last.Form != Suru {
			raise(m.Line.Number, "性質の中には「a と b を 比較する」のような関数の宣言か、関数の定義を書いてください")
		}
		fname, params, _ := parseDefinitionHead(head, m.Line.Number)
		decl.Sigs = append(decl.Sigs, Sig{fname, params})
	}
	return decl
}

func parseTraitImpl(node *LNode, tokens []*Token) Node {
	impl := &TraitImpl{TypeName: checkName(tokens[0]), Trait: checkName(tokens[2]), Line: node.Line.Number}
	for _, c := range node.Children {
		impl.Defs = append(impl.Defs, functionDefine(parseStatement(c), "「"+impl.TypeName+" は "+impl.Trait+"」の下", c.Line.Number))
	}
	return impl
}

func thenDo(first Node, expr Node) Node {
	if d, ok := first.(*Do); ok && d.Sequel {
		d.Statements = append(d.Statements, expr)
		return d
	}
	return &Do{[]Node{first, expr}, lineOf(first), true}
}

func attachProvisos(statements []Node) []Node {
	var out []Node
	var target Node
	extra := map[Node][]*Proviso{}
	for _, s := range statements {
		if sq, ok := s.(*Sequel); ok {
			var prev Node
			if len(out) > 0 {
				prev = out[len(out)-1]
			}
			if prev == nil || isTopLevelOnly(prev) {
				raise(sq.Line, "「それから」の前に行うことを書いてください")
			}
			if d, ok := prev.(*Define); ok {
				d.Body = thenDo(d.Body, sq.Expr)
			} else {
				out[len(out)-1] = thenDo(prev, sq.Expr)
			}
			continue
		}
		if pv, ok := s.(*Proviso); ok {
			if target == nil {
				raise(pv.Line, "「ただし」の前に「…とは」の定義が必要です")
			}
			extra[target] = append(extra[target], pv)
		} else {
			out = append(out, s)
			switch s.(type) {
			case *Define, *TraitDecl, *TraitImpl:
				target = s
			default:
				target = nil
			}
		}
	}
	for _, s := range out {
		provisos := extra[s]
		if len(provisos) == 0 {
			continue
		}
		_, isDecl := s.(*TraitDecl)
		for _, p := range provisos {
			if p.Define == nil && !isDecl {
				raise(p.Line, "「ただし」の後には「…とは」の定義を書いてください")
			}
		}
		switch v := s.(type) {
		case *Define:
			var ds []Node
			for _, p := range provisos {
				ds = append(ds, p.Define)
			}
			v.Body = &Block{append(mergeClauses(ds), v.Body)}
		case *TraitDecl:
			for _, p := range provisos {
				if p.Define == nil {
					v.Sigs = append(v.Sigs, *p.Sig)
				} else {
					v.Defaults = append(v.Defaults, functionDefine(p.Define, "性質の中", p.Line))
				}
			}
		case *TraitImpl:
			for _, p := range provisos {
				v.Defs = append(v.Defs, functionDefine(p.Define, "「"+v.TypeName+" は "+v.Trait+"」の後", p.Line))
			}
		}
	}
	for _, s := range out {
		switch v := s.(type) {
		case *TraitImpl:
			v.Defs = mergeDefs(v.Defs)
		case *TraitDecl:
			v.Defaults = mergeDefs(v.Defaults)
		}
	}
	return mergeClauses(out)
}

func parseStatements(nodes []*LNode) []Node {
	var out []Node
	for _, n := range nodes {
		out = append(out, parseStatement(n))
	}
	return out
}

func parseBlock(nodes []*LNode) Node {
	statements := attachProvisos(parseStatements(nodes))
	for _, s := range statements {
		if isTopLevelOnly(s) {
			raise(lineOf(s), "型や性質の定義は一番外側(字下げなし)に書いてください")
		}
	}
	if _, ok := statements[len(statements)-1].(*Define); ok {
		raise(nodes[len(nodes)-1].Line.Number, "ブロックの最後は式でなければなりません")
	}
	if len(statements) == 1 {
		return statements[0]
	}
	return &Block{statements}
}

func parseDo(nodes []*LNode, line Pos) Node {
	statements := attachProvisos(parseStatements(nodes))
	for _, s := range statements {
		if isTopLevelOnly(s) {
			raise(lineOf(s), "型や性質の定義は一番外側(字下げなし)に書いてください")
		}
	}
	if d, ok := statements[len(statements)-1].(*Define); ok {
		raise(d.Line, "手順の最後は定義ではなく、行うこと(式)でなければなりません")
	}
	return &Do{statements, line, false}
}

// --- プログラムとファイルの読み込み ---

// ParseProgram はプログラムを解析する。見つけた型を ctx に登録する
func ParseProgram(source string, ctx *ParseContext) []Node {
	lines := must(splitSourceLines(source))
	nodes := buildLayout(lines)
	imports := map[*LNode]Node{}
	var modNames []string
	for _, n := range nodes {
		if lib := externLibTarget(n, ctx); lib != nil {
			imports[n] = lib
			continue
		}
		if name, open, ok := importTarget(n); ok {
			imp := &Import{loadModule(name, ctx, n.Line.Number), n.Line.Number, open}
			imports[n] = imp
			modNames = append(modNames, imp.Module.Name)
		}
	}
	var prelude *Import
	if !ctx.InPrelude && !hasPreludeImport(imports) {
		if line, ok := preludeLine(nodes); ok {
			prelude = &Import{loadPrelude(ctx, line), line, true}
			modNames = append(modNames, PreludeName)
		}
	}
	if len(modNames) > 0 {
		joinInNodes(nodes, setOf(modNames...))
	}
	for _, n := range nodes {
		if td := tryParseTypedef(n); td != nil {
			ctx.add(td)
		}
	}
	saved := curCtx
	curCtx = ctx
	defer func() { curCtx = saved }()
	var statements []Node
	for _, n := range nodes {
		if imp, ok := imports[n]; ok {
			statements = append(statements, imp)
		} else {
			statements = append(statements, parseStatement(n))
		}
	}
	if prelude != nil {
		statements = append([]Node{prelude}, statements...)
	}
	checkOpenImports(statements)
	attachExterns(statements)
	return attachProvisos(statements)
}

// 基本(成否・有無)は、その名前を書いたファイルが自動で「読み込んで 使う」
const PreludeName = "基本"

var preludeWords = setOf("成否", "有無", "成功", "失敗", "有")
var preludeCalls = setOf("成否にする", "有無にする", "中断する") // 取出する は性質の関数なので入れない

func hasPreludeImport(imports map[*LNode]Node) bool {
	for _, i := range imports {
		if imp, ok := i.(*Import); ok && isLibFile(imp.Module.Path, PreludePath) {
			return true
		}
	}
	return false
}

// preludeLine は基本(成否・有無)の名前を書いた最初の行(基本.suru そのものなら false)
func preludeLine(nodes []*LNode) (Pos, bool) {
	for _, n := range nodes {
		if td := tryParseTypedef(n); td != nil && (td.Name == "成否" || td.Name == "有無") {
			return Pos{}, false
		}
	}
	return preludeWordLine(nodes)
}

func preludeWordLine(nodes []*LNode) (Pos, bool) {
	for _, n := range nodes {
		for k, t := range n.Line.Tokens {
			if (t.Kind == "WORD" || t.Kind == "CALL") && !t.Quoted &&
				(preludeWords[t.S] || preludeCalls[t.S] || strings.HasPrefix(t.S, PreludeName+ModuleSep) ||
					// 「無」は「… は 無」なら外部の関数の型(C の void)
					t.S == "無" && !(k > 0 && isKw(n.Line.Tokens[k-1], KwWa))) {
				return n.Line.Number, true
			}
		}
		if line, ok := preludeWordLine(n.Children); ok {
			return line, true
		}
	}
	return Pos{}, false
}

// loadPrelude は lib/基本.suru を読む(同じフォルダに 基本.suru があっても、いつも同梱のもの)
func loadPrelude(ctx *ParseContext, line Pos) *Module {
	path := libPath(PreludeName + SourceSuffix)
	if m, ok := ctx.Modules[path]; ok {
		return m
	}
	return loadPath(path, PreludeName+SourceSuffix, ctx, line, true)
}

// externLibTarget は「外部の「m」 を 読み込む」なら ExternLib
func externLibTarget(node *LNode, ctx *ParseContext) *ExternLib {
	tokens := nosep(flatten(node))
	if len(tokens) > 0 && tokens[len(tokens)-1].Kind == "PERIOD" {
		tokens = tokens[:len(tokens)-1]
	}
	if len(tokens) == 0 || !(tokens[0].Kind == "WORD" && tokens[0].S == KwExtern && !tokens[0].Quoted) {
		return nil
	}
	if len(tokens) != 4 || tokens[1].Kind != "STR" || !(tokens[2].Kind == "PART" && tokens[2].S == WO) ||
		!(isKw(tokens[3], KwImport) || isKw(tokens[3], KwImportPolit)) || node.Line.Indent != 0 {
		raise(tokens[0].Line, "外部のライブラリは一番外に「"+KwExtern+"「m」 を "+KwImport+"」のように書いて読み込みます")
	}
	name := tokens[1].S
	if name == "" {
		raise(tokens[0].Line, "外部のライブラリの名前が空です")
	}
	path := name
	if strings.Contains(name, "/") || strings.HasSuffix(name, ".so") || strings.HasSuffix(name, ".dylib") {
		path = absPath(filepath.Join(ctx.BaseDir, name))
	}
	return &ExternLib{name, path, tokens[0].Line}
}

func ffiType(te Node, sig *TypeSig, what string) string {
	skip := "void"
	if what == "値" {
		skip = "bytes"
	}
	var names []string
	for _, n := range ffiTypeNames {
		if ffiTypes[n] != skip {
			names = append(names, n)
		}
	}
	if tn, ok := te.(*TypeName); ok && len(tn.Args) == 0 {
		if t, ok := ffiTypes[tn.Name]; ok && t != skip {
			return t
		}
	}
	raise(sig.Line, "外部の関数「"+sig.Name+"」の"+what+"には "+strings.Join(names, "・")+" のどれかの型を書いてください")
	return ""
}

// attachExterns は外部の関数の定義に、同じファイルのライブラリと型の宣言(C の型)を付ける
func attachExterns(statements []Node) {
	var libs []string
	sigs := map[string]*TypeSig{}
	for _, s := range statements {
		switch x := s.(type) {
		case *ExternLib:
			libs = append(libs, x.Path)
		case *TypeSig:
			sigs[x.Name] = x
		}
	}
	seen := map[string]string{}
	for _, s := range statements {
		d, ok := s.(*Define)
		if !ok {
			continue
		}
		ext, ok := d.Body.(*Extern)
		if !ok {
			continue
		}
		sig := sigs[d.Name]
		if !d.IsFunction || sig == nil || !sig.HasParams {
			raise(d.Line, "外部の関数「"+d.Name+"」には型の宣言が必要です(「小数 を 余弦にする は 小数」のように書きます)")
		}
		types := map[string]Node{}
		var got, want []string
		for _, p := range sig.Params {
			types[p.Part] = p.Type
			got = append(got, p.Part)
		}
		for _, p := range d.Params {
			want = append(want, p.Part)
		}
		sort.Strings(got)
		sort.Strings(want)
		if !eqStrings(got, want) {
			raise(d.Line, "「"+d.Name+"」の型の宣言の助詞が定義の助詞と違います")
		}
		for _, p := range d.Params {
			if p.List || !p.simple() {
				raise(d.Line, "外部の関数「"+d.Name+"」の引数は名前だけで書いてください")
			}
		}
		ext.Params = nil
		for _, p := range d.Params {
			ext.Params = append(ext.Params, ffiType(types[p.Part], sig, "「"+p.Part+"」"))
		}
		result := sig.Result
		if tn, ok := result.(*TypeName); ok && tn.Name == "動作" {
			ext.Action = true
			result = tn.Args[0]
		}
		ext.Result = ffiType(result, sig, "値")
		ext.Libs = libs
		if ext.Pointer != "" {
			k := -1
			for i, p := range d.Params {
				if p.Name == ext.Pointer {
					k = i
				}
			}
			if k < 0 {
				raise(ext.Line, "「外部の（"+ext.Pointer+"）」の「"+ext.Pointer+"」は「"+d.Name+"」の引数ではありません")
			}
			if ext.Params[k] != "ptr" {
				raise(ext.Line, "「外部の（"+ext.Pointer+"）」の「"+ext.Pointer+"」は型の宣言で 番地 にしてください")
			}
			continue
		}
		if prev, ok := seen[ext.Symbol]; ok {
			raise(d.Line, "外部の関数「"+ext.Symbol+"」が2回定義されています(「"+prev+"」と「"+d.Name+"」)")
		}
		seen[ext.Symbol] = d.Name
	}
}

func isCSymbol(sym string) bool {
	if sym == "" {
		return false
	}
	for i, c := range sym {
		alpha := (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
		if !(alpha || c == '_' || (i > 0 && c >= '0' && c <= '9')) {
			return false
		}
	}
	return true
}

func moduleNames(m *Module) map[string]bool {
	names := map[string]bool{}
	for _, s := range m.Program {
		if d, ok := s.(*Define); ok && !m.Private[d.Name] {
			names[d.Name] = true
		}
	}
	for _, b := range libPrimitives(m.Path) {
		names[b.Name] = true
	}
	return names
}

func checkOpenImports(statements []Node) {
	own := map[string]bool{}
	for _, s := range statements {
		if d, ok := s.(*Define); ok {
			own[d.Name] = true
		}
	}
	seen := map[string]string{}
	for _, s := range statements {
		imp, ok := s.(*Import)
		if !ok || !imp.Open {
			continue
		}
		var names []string
		for n := range moduleNames(imp.Module) {
			if !own[n] {
				names = append(names, n)
			}
		}
		sort.Strings(names)
		for _, name := range names {
			if prev, ok := seen[name]; ok && prev != imp.Module.Name {
				raisef(imp.Line, "「%s」は「%s」と「%s」の両方にあります。「%s%s%s」のように前置きを付けて使うか、片方を「%s」にしてください",
					name, prev, imp.Module.Name, imp.Module.Name, ModuleSep, name, KwImport)
			}
			seen[name] = imp.Module.Name
		}
	}
}

func joinInNodes(nodes []*LNode, modules map[string]bool) {
	for _, n := range nodes {
		n.Line.Tokens = must(joinModuleNames(n.Line.Tokens, modules))
		joinInNodes(n.Children, modules)
	}
}

func importTarget(node *LNode) (string, bool, bool) {
	tokens := nosep(flatten(node))
	if len(tokens) > 0 && tokens[len(tokens)-1].Kind == "PERIOD" {
		tokens = tokens[:len(tokens)-1]
	}
	found := false
	for _, t := range tokens {
		if isKw(t, KwImport) || isKw(t, KwImportPolit) || isKw(t, KwImportTe) {
			found = true
		}
	}
	if !found {
		return "", false, false
	}
	var tail []string
	if len(tokens) > 2 {
		for _, t := range tokens[2:] {
			if t.Kind == "KW" {
				tail = append(tail, t.S)
			} else {
				tail = append(tail, "\x00none")
			}
		}
	}
	okTail := eqStrings(tail, []string{KwImport}) || eqStrings(tail, []string{KwImportPolit}) ||
		eqStrings(tail, []string{KwImportTe, KwUse}) || eqStrings(tail, []string{KwImportTe, KwUsePolite})
	if !okTail || tokens[0].Kind != "STR" || !(tokens[1].Kind == "PART" && tokens[1].S == WO) || node.Line.Indent != 0 {
		raise(tokens[0].Line, "ファイルは一番外に「「数学」 を "+KwImport+"」か「「数学」 を "+KwImportTe+" "+KwUse+"」のように書いて読み込みます")
	}
	return tokens[0].S, len(tail) == 2, true
}

// 同梱の lib/ の中のファイル(「標準」など)は、このパスの名前で表す
const embeddedLibPrefix = "\x00lib/"

// StdPath は標準ライブラリのファイルのパス
var StdPath = embeddedLibPrefix + "標準" + SourceSuffix

// NetPath は通信ライブラリのファイルのパス
var NetPath = embeddedLibPrefix + "通信" + SourceSuffix

// ThreadPath はスレッドのライブラリのファイルのパス
var ThreadPath = embeddedLibPrefix + "スレッド" + SourceSuffix

// PreludePath は基本(成否・有無)のファイルのパス
var PreludePath = embeddedLibPrefix + PreludeName + SourceSuffix

// LibFS は同梱の lib/(cmd/suruc が設定する)
var LibFS fs.FS

// LibDir が空でなければ、lib/ をこのフォルダから読む
var LibDir string

func libPath(file string) string {
	if LibDir != "" {
		return filepath.Join(LibDir, file)
	}
	return embeddedLibPrefix + file
}

func readSource(path string) (string, bool) {
	if strings.HasPrefix(path, embeddedLibPrefix) {
		if LibFS == nil {
			return "", false
		}
		data, err := fs.ReadFile(LibFS, strings.TrimPrefix(path, embeddedLibPrefix))
		if err != nil {
			return "", false
		}
		return NormalizeNewlines(string(data)), true
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return "", false
	}
	return NormalizeNewlines(string(data)), true
}

func exists(path string) bool {
	if strings.HasPrefix(path, embeddedLibPrefix) {
		if LibFS == nil {
			return false
		}
		_, err := fs.Stat(LibFS, strings.TrimPrefix(path, embeddedLibPrefix))
		return err == nil
	}
	_, err := os.Stat(path)
	return err == nil
}

func absPath(p string) string {
	a, err := filepath.Abs(p)
	if err != nil {
		return filepath.Clean(p)
	}
	return a
}

func pathBase(p string) string {
	if strings.HasPrefix(p, embeddedLibPrefix) {
		return filepath.Base(strings.TrimPrefix(p, embeddedLibPrefix))
	}
	return filepath.Base(p)
}

func pathDir(p string) string {
	if strings.HasPrefix(p, embeddedLibPrefix) {
		d := filepath.Dir(strings.TrimPrefix(p, embeddedLibPrefix))
		if d == "." {
			return strings.TrimSuffix(embeddedLibPrefix, "/")
		}
		return embeddedLibPrefix + d
	}
	return filepath.Dir(p)
}

func splitExt(p string) string {
	ext := filepath.Ext(p)
	if ext == p || strings.HasPrefix(ext, ".") && len(ext) == len(p) {
		return p
	}
	return strings.TrimSuffix(p, ext)
}

func loadModule(name string, ctx *ParseContext, line Pos) *Module {
	file := name
	if !strings.HasSuffix(name, SourceSuffix) {
		file = name + SourceSuffix
	}
	var path string
	if strings.HasPrefix(ctx.BaseDir, embeddedLibPrefix) || ctx.BaseDir == strings.TrimSuffix(embeddedLibPrefix, "/") {
		path = libPath(file)
	} else {
		path = absPath(filepath.Join(ctx.BaseDir, file))
	}
	if ctx.Packages == nil && !strings.HasPrefix(ctx.BaseDir, embeddedLibPrefix) {
		ctx.Packages = FindPackages(ctx.BaseDir)
	}
	if !exists(path) {
		if p, ok := packagePath(name, ctx, line); ok {
			path = p
		} else if LibDir != "" {
			path = absPath(filepath.Join(LibDir, file))
		} else {
			path = embeddedLibPrefix + filepath.Clean(file)
		}
	}
	return loadPath(path, file, ctx, line, false)
}

func loadPath(path, file string, ctx *ParseContext, line Pos, prelude bool) *Module {
	stem := splitExt(pathBase(path))
	bad := stem == "" || isAllHiragana(stem) || strings.ContainsFunc(stem, isHiragana) || strings.ContainsAny(stem, " 　「」『』（）()、。")
	if bad {
		raise(line, "「"+stem+"」はファイルの名前に使えません(名前と同じく漢字・カタカナ・英字で書いてください)")
	}
	if ctx.Loading[path] {
		raise(line, "「"+stem+SourceSuffix+"」を読み込むと、自分自身を読み込むことになります")
	}
	if m, ok := ctx.Modules[path]; ok {
		return m
	}
	source, ok := readSource(path)
	if !ok {
		raise(line, "ファイル「"+file+"」が見つかりません")
	}
	ctx.Loading[path] = true
	sub := &ParseContext{Ctors: ctx.Ctors.Copy(), Types: ctx.Types.Copy(), BaseDir: pathDir(path), Modules: ctx.Modules, Loading: ctx.Loading, Packages: ctx.Packages, InPrelude: prelude}
	var program []Node
	err := try(func() {
		program = ParseProgram(source, sub)
		for _, s := range program {
			if _, ok := s.(*Define); !ok && !isTopLevelOnly(s) {
				raise(firstLineOf(s), "読み込むファイルには定義だけを書いてください")
			}
		}
	})
	if err != nil {
		w := ""
		if err.Line.Line != 0 {
			w = where(err.Line)
		}
		raise(line, "「"+stem+SourceSuffix+"」の"+w+": "+err.Message)
	}
	ctx.Ctors.Update(sub.Ctors)
	ctx.Types.Update(sub.Types)
	m := &Module{stem, path, program, privateNames(program)}
	delete(ctx.Loading, path)
	ctx.Modules[path] = m
	return m
}

// firstLineOf は suru.py の first_line_of(リストの中までは見ない)
func firstLineOf(n Node) Pos {
	if n == nil {
		return Pos{}
	}
	if l := lineOf(n); l.Line != 0 {
		return l
	}
	switch v := n.(type) {
	case *Neg:
		return firstLineOf(v.Operand)
	case *If:
		for _, c := range []Node{v.Cond, v.Then, v.Other} {
			if l := firstLineOf(c); l.Line != 0 {
				return l
			}
		}
	case *PValue:
		return firstLineOf(v.Expr)
	case *Proviso:
		if v.Define != nil {
			return firstLineOf(v.Define)
		}
	case *Chain:
		for _, c := range []Node{v.Call, v.Cont} {
			if l := firstLineOf(c); l.Line != 0 {
				return l
			}
		}
	case *Run:
		return firstLineOf(v.Call)
	case *Sequel:
		return firstLineOf(v.Expr)
	case *Prop:
		return firstLineOf(v.Target)
	case *Each:
		return firstLineOf(v.Target)
	case *BinOp:
		for _, c := range []Node{v.Left, v.Right} {
			if l := firstLineOf(c); l.Line != 0 {
				return l
			}
		}
	case *Not:
		return firstLineOf(v.Operand)
	case *Lambda:
		return firstLineOf(v.Body)
	case *Define:
		return firstLineOf(v.Body)
	case *Update:
		return firstLineOf(v.Target)
	case *Field:
		return firstLineOf(v.Target)
	case *Match:
		for _, c := range []Node{v.Subject, v.Default} {
			if l := firstLineOf(c); l.Line != 0 {
				return l
			}
		}
	}
	return Pos{}
}

const (
	VisPublic  = "公開とする"
	VisPrivate = "非公開とする"
)

// tryParseVisibility は「a と b は 非公開とする」「a は 公開とする」なら Visibility
func tryParseVisibility(tokens []*Token) *Visibility {
	if len(tokens) > 0 && tokens[len(tokens)-1].Kind == "PERIOD" {
		tokens = tokens[:len(tokens)-1]
	}
	n := len(tokens)
	if n < 3 || tokens[n-1].Kind != "CALL" || (tokens[n-1].S != VisPublic && tokens[n-1].S != VisPrivate) || !isKw(tokens[n-2], KwWa) {
		return nil
	}
	word := tokens[n-1].S
	var names []string
	for i, t := range tokens[:n-2] {
		if i%2 == 1 {
			if !isKw(t, KwTo) {
				raise(t.Line, "「"+word+"」の前には、名前を「と」で並べてください(「確保する と 解放する は "+word+"」)")
			}
		} else if t.Kind == "WORD" || t.Kind == "CALL" {
			names = append(names, t.S)
		} else {
			raise(t.Line, "「"+word+"」の前には、このファイルで定義した名前を書いてください")
		}
	}
	if (n-2)%2 == 0 {
		raise(tokens[n-2].Line, "「"+word+"」の前には、名前を「と」で並べてください(「確保する と 解放する は "+word+"」)")
	}
	return &Visibility{names, word == VisPublic, tokens[0].Line}
}

// privateNames は一番外の「… は 非公開とする」「… は 公開とする」から、外から見えない名前を決める
func privateNames(statements []Node) map[string]bool {
	var vis []*Visibility
	defined := map[string]bool{}
	for _, s := range statements {
		switch x := s.(type) {
		case *Visibility:
			vis = append(vis, x)
		case *Define:
			defined[x.Name] = true
		}
	}
	out := map[string]bool{}
	if len(vis) == 0 {
		return out
	}
	public := map[string]bool{}
	private := map[string]bool{}
	for _, v := range vis {
		for _, n := range v.Names {
			if !defined[n] {
				w := VisPrivate
				if v.Public {
					w = VisPublic
				}
				raise(v.Line, "「"+n+"」はこのファイルで定義していないので、"+w+"にできません")
			}
			if v.Public {
				public[n] = true
			} else {
				private[n] = true
			}
			if public[n] && private[n] {
				raise(v.Line, "「"+n+"」が「"+VisPublic+"」と「"+VisPrivate+"」の両方に書かれています")
			}
		}
	}
	if len(public) > 0 {
		for n := range defined {
			if !public[n] {
				out[n] = true
			}
		}
		return out
	}
	return private
}

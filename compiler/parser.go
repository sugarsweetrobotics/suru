// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
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
var builtinTypes = []string{"数", "文字列", "真偽", "リスト", "関数", "動作", "小数", "整数", "番地", "バイト列", "無", "入出力動作", "単精度", "C形"}

// KwExtern は外部の関数・ライブラリの印
const KwExtern = "外部の"

// KwMainThread は「外部の「SDL3」 を 主スレッドで 読み込む」
const KwMainThread = "主スレッドで"

// ffiTypeNames は外部の関数に渡せる型(書く順)と C の型
var ffiTypeNames = []string{"数", "小数", "整数", "真偽", "文字列", "番地", "バイト列", "無", "単精度"}
var ffiTypes = map[string]string{"数": "i64", "小数": "f64", "整数": "i32", "真偽": "bool", "文字列": "str", "番地": "ptr",
	"バイト列": "bytes", "無": "void", "単精度": "f32"}
var builtinTypeSet = setOf(builtinTypes...)

const typeVarNames = "甲乙丙丁戊己庚辛壬癸"

// ParseContext は構文解析で使う、定義済みの型と形の名前
type ParseContext struct {
	Ctors   *CtorMap
	Types   *TypeMap
	BaseDir string
	Modules map[string]*Module // 絶対パス → Module(読み込み中は nil)
	// Order は読み込みを始めた順の道(suru.py の ctx.modules の順。どの ParseContext でも同じものを指す)
	Order   *[]string
	Loading map[string]bool
	// Packages はプロジェクトの依存(名前 → Package)。nil なら、初めて読み込むときに BaseDir から探す
	Packages map[string]Package
	// InPrelude は 基本.suru そのものを読んでいるとき(基本を自動で読み込まない)
	InPrelude bool
	// Qualify は読み込んだファイル(lib/ のものを除く)を解析しているときの「部品内の」。そのファイルの型と形の名前に付ける
	Qualify string
	// Path は解析しているファイルの絶対パス(自分と同じ名前のファイルを読み込むときに飛ばす。分からなければ "")
	Path string
	// FieldTypes はフィールドの型を書いた型 → フィールドの型(「番号 は 数 で … の 組」)
	FieldTypes map[string][]FieldTypeDecl
}

// resolveFieldTypes はフィールドの型を書いた型の、型の字句を読む(型の定義をすべて集めてから。後ろで定義する型も書ける)
func (c *ParseContext) resolveFieldTypes(tds []*TypeDef) {
	for _, td := range tds {
		if td.FieldTypes == nil {
			continue
		}
		if c.FieldTypes == nil {
			c.FieldTypes = map[string][]FieldTypeDecl{}
		}
		var out []FieldTypeDecl
		for _, ft := range td.FieldTypes {
			out = append(out, FieldTypeDecl{ft.Name, parseTypeAll(ft.Toks, td.Line)})
		}
		c.FieldTypes[td.Name] = out
	}
}

func copyFieldTypes(m map[string][]FieldTypeDecl) map[string][]FieldTypeDecl {
	out := map[string][]FieldTypeDecl{}
	for k, v := range m {
		out[k] = v
	}
	return out
}

func NewParseContext(baseDir string) *ParseContext {
	return &ParseContext{Ctors: newCtorMap(), Types: newTypeMap(), BaseDir: baseDir,
		Modules: map[string]*Module{}, Loading: map[string]bool{}, Order: &[]string{}}
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
	lines = expandExterns(lines)
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
			if (!ln.Closed || opensIka(ln)) && pos < len(lines) && lines[pos].Indent > indent {
				node.Children = block(indent + 1)
			}
			// 行頭が ならば/そうでなければ の行は前の文の続き。
			// 「… ならば 以下の手順です」の後は、深い行の「以上」で閉じていれば続ける(#190)
			first := ln.Tokens[0]
			if len(nodes) > 0 && !ln.Closed && !nodes[len(nodes)-1].Line.Closed && first.Kind == "KW" && continuationKeywords[first.S] &&
				(!opensIka(nodes[len(nodes)-1].Line) || ikaClosedDeep(nodes[len(nodes)-1])) {
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
	return closeIjou(top)
}

// opensIka は「… とは 以下の手順です」で終わる行か
func opensIka(ln *Line) bool {
	ts := nosep(ln.Tokens)
	return len(ts) > 0 && ts[len(ts)-1].Kind == "KW" && (ikaWords[ts[len(ts)-1].S] || isTestHead(ts[len(ts)-1]) && len(ts) == 1)
}

// ikaClosedDeep は「以下の手順です」の行で、深い行の「以上」で既に閉じているか(その後の続きの行は式の続き)
func ikaClosedDeep(n *LNode) bool {
	for _, c := range n.Children {
		if isIjou(c.Line) {
			return true
		}
	}
	return false
}

// isIjou は「以上」だけの行(文)か
func isIjou(ln *Line) bool {
	ts := nosep(ln.Tokens)
	return len(ts) == 1 && isKw(ts[0], KwIjou)
}

// ijouThenMore は「以上」の後に同じ深さで文が続くなら、そう知らせる
// (場合分けを閉じる「以上」は場合と同じ深い行にあるので、ここには来ない)
func ijouThenMore(n *LNode) {
	for k := 0; k+1 < len(n.Children); k++ {
		if isIjou(n.Children[k].Line) {
			raise(n.Children[k+1].Line.Number, "「"+KwIjou+"」の後に文があります(手順の文は「"+KwIjou+"」の前に書きます)")
		}
	}
}

func ikaMissing(n *LNode) {
	ts := nosep(n.Line.Tokens)
	raise(n.Line.Number, "「"+ts[len(ts)-1].S+"です」を閉じる「"+KwIjou+"」がありません(手順の最後の文の後に「"+KwIjou+"」だけの行を書きます)")
}

// closeIjou は「以下の手順です」の行に、「以上」までの文を深い行としてまとめる(「以上」の行は取り除く)。
// 文は深い行か、同じ字下げで続く行(句読点の書き方では続く文)。「以上」は最後の深い行か、頭と同じ字下げの行
func closeIjou(nodes []*LNode) []*LNode {
	var out []*LNode
	for i := 0; i < len(nodes); {
		var n *LNode
		n, i = closeOne(nodes, i)
		out = append(out, n)
	}
	return out
}

func closeOne(nodes []*LNode, i int) (*LNode, int) {
	n := nodes[i]
	i++
	n.Children = closeIjou(n.Children)
	if !opensIka(n.Line) {
		return n, i
	}
	if j := ijouBeforeContinuation(n); j >= 0 && !isTestHead(nosep(n.Line.Tokens)[0]) {
		// 「もし … ならば 以下の手順です」+ 深い行 + 「以上」の後に「そうでなければ …」(#190):
		// 手順の文を DO の字句にして行に入れ、続きの行を深い行として残す
		body, rest := n.Children[:j], n.Children[j+1:]
		if len(body) == 0 {
			ts := nosep(n.Line.Tokens)
			raise(n.Line.Number, "「"+ts[len(ts)-1].S+"です」と「"+KwIjou+"」の間に文がありません")
		}
		toks := n.Line.Tokens
		k := -1
		for x, t := range toks {
			if t.Kind == "KW" && ikaWords[t.S] {
				k = x
			}
		}
		do := &Token{Kind: "DO", S: toks[k].S, Form: toks[k].S, Line: toks[k].Line, Do: body}
		line := append(append(append([]*Token{}, toks[:k]...), do), toks[k+1:]...)
		n.Line = &Line{Indent: n.Line.Indent, Tokens: line, Number: n.Line.Number, Closed: n.Line.Closed}
		n.Children = rest
		return n, i
	}
	if len(n.Children) > 0 {
		if isIjou(n.Children[len(n.Children)-1].Line) {
			n.Children = n.Children[:len(n.Children)-1]
		} else if i < len(nodes) && isIjou(nodes[i].Line) {
			i++
		} else {
			ijouThenMore(n)
			ikaMissing(n)
		}
	} else {
		var body []*LNode
		for i < len(nodes) && !isIjou(nodes[i].Line) {
			var m *LNode
			m, i = closeOne(nodes, i)
			body = append(body, m)
		}
		if i >= len(nodes) {
			ikaMissing(n)
		}
		i++
		n.Children = body
	}
	if len(n.Children) == 0 {
		ts := nosep(n.Line.Tokens)
		raise(n.Line.Number, "「"+ts[len(ts)-1].S+"です」と「"+KwIjou+"」の間に文がありません")
	}
	return n, i
}

// ijouBeforeContinuation は、深い行の「以上」の後に続きの行(ならば・そうでなければ)だけがあれば、その「以上」の位置を返す(なければ -1)
func ijouBeforeContinuation(n *LNode) int {
	j := -1
	for k, c := range n.Children {
		if isIjou(c.Line) {
			j = k
			break
		}
	}
	if j < 0 || j == len(n.Children)-1 {
		return -1
	}
	for _, c := range n.Children[j+1:] {
		ts := nosep(c.Line.Tokens)
		if len(ts) == 0 || ts[0].Kind != "KW" || !continuationKeywords[ts[0].S] {
			return -1
		}
	}
	return j
}

func flatten(node *LNode) []*Token {
	return withChildren(node.Line.Tokens, node.Children)
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
	// caseIndents は読んでいる場合分けの、場合の行の字下げ(外側から。分からなければ -1)
	caseIndents []*int
}

// sepIndent は i から続く区切りのうち、行の切れ目の区切りの字下げ(なければ -1)
func (p *ExprParser) sepIndent(i int) int {
	d := -1
	for i < len(p.tokens) && p.tokens[i].Kind == "SEP" {
		if p.tokens[i].SepIndent > 0 {
			d = p.tokens[i].SepIndent - 1
		}
		i++
	}
	return d
}

// outerCaseHere は次が、外側の場合分けの場合と同じか浅い字下げの行か(この場合分けより浅いときだけ)
func (p *ExprParser) outerCaseHere(mine int) bool {
	d := p.sepIndent(p.pos)
	if d < 0 || mine < 0 || d >= mine {
		return false
	}
	for _, o := range p.caseIndents[:len(p.caseIndents)-1] {
		if *o >= 0 && d <= *o {
			return true
		}
	}
	return false
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

// 書き方を案内するエラー(#155)
const (
	eachLambdaMessage = "「それぞれ」の後には「…する」で終わる関数の名前を書きます" +
		"(無名関数を使うときは「xs を （x を 受け取って … を 返すこと） で 写像する」と書きます)"
	matchCallMessage = "「もし 値 が」の場合分けで値に呼び出しを書くときは、括弧で囲んでください" +
		"(「もし （s を JSON解析する） が」のように書きます)"
	provisoIndentMessage = "「ただし」は、付け足す定義の行と同じ字下げで書いてください(字下げした行は前の行の続きとして読みます)"
)

func (p *ExprParser) parseAll() Node {
	e := p.expr()
	if t := p.peek0(); t != nil {
		if t.Kind == "RP" {
			raise(t.Line, "対応する「(」のない「)」があります")
		}
		if isKw(t, KwIjou) {
			raise(t.Line, "対応する「もし 値 が」の場合分けか「以下の手順です」のない「"+KwIjou+"」があります")
		}
		if isKw(t, KwProviso) && p.sepIndent(p.pos) >= 0 {
			raise(t.Line, provisoIndentMessage) // 字下げした行の頭の「ただし」
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
			if _, ok := cond.(*Call); ok && isKw(t, KwGa) {
				raise(t.Line, matchCallMessage)
			}
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
				value = &Run{&Call{t.S, args, t.Line}, t.Line, res.S == Content, ""}
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
				if _, ok := value.(*Lambda); ok && args.hasEach() {
					raise(line, eachLambdaMessage)
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
	firstPat := 0
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
		firstPat = p.pos
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
	here := p.sepIndent(firstPat)
	p.caseIndents = append(p.caseIndents, &here)
	defer func() { p.caseIndents = p.caseIndents[:len(p.caseIndents)-1] }()
	for {
		checkPattern(pat, p.peek0().Line)
		p.next()
		cases = append(cases, Case{pat, guard, p.caseBody()})
		t := p.peek0()
		if isKw(t, KwIjou) {
			p.next() // 「以上」: この場合分けを閉じる
			break
		}
		if p.outerCaseHere(here) {
			break // 外側の場合分けの字下げの行: この場合分けはここまで
		}
		if isKw(t, KwElse) {
			p.next()
			deflt = p.caseBody()
			if isKw(p.peek0(), KwIjou) {
				p.next()
			}
			break
		}
		if t == nil || t.Kind == "RP" || t.Kind == "PERIOD" || !p.sepHere() {
			break
		}
		if here < 0 {
			here = p.sepIndent(p.pos)
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
	if (isKw(p.peek0(), KwNo) || isKw(p.peek0(), KwToiu)) && isCtor(p.peek(1)) {
		// 「s の JSON文字列」「s という JSON文字列」(パターンでは「という」も書ける)
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
	if (isKw(p.peek0(), KwNo) || isKw(p.peek0(), KwToiu)) && isCtor(p.peek(1)) {
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
		nodes = append(nodes, &LNode{Line: &Line{Indent: 0, Tokens: s, Number: s[0].Line, Closed: true}})
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
			nodes = append(nodes, &LNode{Line: &Line{Indent: 0, Tokens: x, Number: x[0].Line, Closed: true}})
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
	case "DO":
		// 「以下の手順です」+ 文 + 「以上」
		d := parseDo(t.Do, t.Line)
		d.(*Do).IO = t.Form == KwIkaIO
		return d
	case "WORD":
		var nxt *Token
		if p.pos < len(p.tokens) {
			nxt = p.tokens[p.pos]
		}
		if (t.S == Tejun || t.S == TejunIO) && !t.Quoted && nxt != nil && nxt.Kind == "LP" {
			p.next()
			d := p.parenDo(nxt)
			d.(*Do).IO = t.S == TejunIO
			return d
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
		panic(notSuruError(last))
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
	return &Define{name, params, body, true, first.Line, "", nil}
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

// withChildren は行のトークンに深い行を続ける。「以下の手順です」で終わる行なら、深い行(手順の文)を1つの DO トークンにする
func withChildren(tokens []*Token, children []*LNode) []*Token {
	ts := nosep(tokens)
	if len(children) > 0 && len(ts) > 0 && ts[len(ts)-1].Kind == "KW" && ikaWords[ts[len(ts)-1].S] {
		last := ts[len(ts)-1]
		k := indexOf(tokens, last)
		out := append([]*Token{}, tokens[:k]...)
		out = append(out, &Token{Kind: "DO", S: last.S, Form: last.S, Line: last.Line, Do: children})
		return append(out, tokens[k+1:]...)
	}
	out := append([]*Token{}, tokens...)
	for _, c := range children {
		sep := tok("SEP", "", c.Line.Number)
		sep.SepIndent = c.Line.Indent + 1
		out = append(out, sep)
		out = append(out, flatten(c)...)
	}
	return out
}

// parseTestBlock は「以下は「二倍」の試験です」+ 手順の文 + 「以上です」(#193)。引数のない手順の定義にする
func parseTestBlock(node *LNode, tokens []*Token) Node {
	head := tokens[0]
	if len(tokens) != 1 || !isTestHead(head) {
		for _, t := range tokens {
			if isTestHead(t) {
				raise(t.Line, "「"+t.S+"です」は1行に、それだけを書きます(手順の文は次の行から書き、最後に「"+KwIjou+"です」)")
			}
		}
	}
	if node.Line.Indent != 0 {
		raise(head.Line, "「"+head.S+"です」は一番外(字下げなし)に書いてください")
	}
	name := testHeadName(head)
	if strings.TrimSpace(name) == "" {
		raise(head.Line, "試験の名前を「」の中に書いてください(「以下は「二倍」の試験です」)")
	}
	do := parseDo(node.Children, node.Line.Number)
	return &Define{testPrefix + name, nil, do, true, node.Line.Number, name, nil}
}

// parseExample は「例えば （2 を 二倍する） は 4 です」(#193)。実際 = 期待 を確かめる、引数のない定義にする
func parseExample(node *LNode) Node {
	tokens := nosep(flatten(node))
	word := tokens[0]
	usage := "「" + KwExample + " （2 を 二倍する） は 4 です」のように、「" + KwExample + " 式 は 期待する値」と書きます"
	if node.Line.Indent != 0 {
		raise(word.Line, "「"+KwExample+"」の例は一番外(字下げなし)に、定義のすぐ下に書いてください")
	}
	rest := tokens[1:]
	wa := findTopLevel(rest, KwWa)
	if wa <= 0 || wa == len(rest)-1 {
		raise(word.Line, usage)
	}
	actual := newExprParser(rest[:wa]).parseAll()
	expected := newExprParser(rest[wa+1:]).parseAll()
	body := &BinOp{"==", actual, expected, word.Line}
	return &Define{fmt.Sprintf("%s%d", examplePrefix, node.Line.Number.Line), nil, body, true, node.Line.Number, "例", []Node{actual, expected}}
}

// IsTestDefine は試験のまとまりか例の定義か
func IsTestDefine(n Node) bool {
	d, ok := n.(*Define)
	return ok && d.Test != ""
}

// DropTests は試験のまとまりと例、それらのために読み込んだ「試験」を除く(通常のビルドと、読み込んだファイル)
func DropTests(program []Node) []Node {
	var out []Node
	for _, s := range program {
		if imp, ok := s.(*Import); (ok && imp.Test) || IsTestDefine(s) {
			continue
		}
		out = append(out, s)
	}
	return out
}

// nameExamples は例の名前を、すぐ上の定義の名前から決める(「二倍するの例」)。同じ名前の試験のまとまりが2つあればエラー
func nameExamples(statements []Node) {
	prev := ""
	seen := map[string]Pos{}
	for _, s := range statements {
		d, ok := s.(*Define)
		if !ok {
			continue
		}
		switch {
		case d.Example != nil:
			if prev != "" {
				d.Test = prev + "の例"
			} else {
				d.Test = "例"
			}
		case d.Test != "":
			if p, dup := seen[d.Test]; dup {
				raise(d.Line, fmt.Sprintf("「%s」の試験は%d行目にもあります(試験の名前は1つずつ違うものにしてください)", d.Test, p.Line))
			}
			seen[d.Test] = d.Line
		default:
			prev = d.Name
		}
	}
}

func parseStatement(node *LNode) Node {
	raw := node.Line.Tokens
	tokens := nosep(raw)
	if len(tokens) == 1 && isKw(tokens[0], KwIjou) {
		raise(tokens[0].Line, "対応する「以下の手順です」のない「"+KwIjou+"」があります")
	}
	for _, t := range tokens {
		if isTestHead(t) {
			return parseTestBlock(node, tokens)
		}
	}
	if tokens[0].Kind == "WORD" && !tokens[0].Quoted && tokens[0].S == KwExample {
		return parseExample(node)
	}
	if isKw(tokens[0], KwSorekara) {
		rest := raw[indexOf(raw, tokens[0])+1:]
		inner := &LNode{&Line{Indent: node.Line.Indent, Tokens: rest, Number: node.Line.Number, Closed: node.Line.Closed}, node.Children}
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
		inner := &LNode{&Line{Indent: node.Line.Indent, Tokens: rest, Number: node.Line.Number, Closed: node.Line.Closed}, node.Children}
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
	if isKw(tokens[0], KwExportMark) {
		return &Export{Name: tokens[1].S, Symbol: tokens[2].S, Line: tokens[0].Line}
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
	if strings.Contains(name, ModuleSep) && !head[0].Qualified {
		raise(head[0].Line, "「"+name+"」: 読み込んだファイルの中の名前は定義できません")
	}
	afterT := nosep(after)
	if len(afterT) == 1 && afterT[0].Kind == "KW" && ikaWords[afterT[0].S] {
		// 「挨拶する とは 以下の手順です」+ 文 + 「以上」(文は closeIjou が深い行にまとめた)
		d := parseDo(node.Children, node.Line.Number)
		d.(*Do).IO = afterT[0].S == KwIkaIO
		return &Define{name, params, d, isFunction, node.Line.Number, "", nil}
	}
	if len(afterT) == 1 && afterT[0].Kind == "WORD" && (afterT[0].S == Tejun || afterT[0].S == TejunIO) && !afterT[0].Quoted && len(node.Children) > 0 {
		// 「挨拶する とは 手順」+ 深い行(「入出力手順」なら動作だけ)
		d := parseDo(node.Children, node.Line.Number)
		d.(*Do).IO = afterT[0].S == TejunIO
		return &Define{name, params, d, isFunction, node.Line.Number, "", nil}
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
		return &Define{name, params, &Extern{Symbol: sym, Line: afterT[1].Line}, isFunction, node.Line.Number, "", nil}
	}
	if len(afterT) >= 5 && afterT[0].Kind == "WORD" && afterT[0].S == KwExtern && !afterT[0].Quoted &&
		afterT[1].Kind == "STR" && afterT[2].Kind == "LP" && afterT[len(afterT)-1].Kind == "RP" && len(node.Children) == 0 {
		// 「… とは 外部の「pcre2_match_8」（c と s と n と o と 0 と md と 0）」: C に渡す引数を並べて書く
		sym := afterT[1].S
		if !isCSymbol(sym) {
			raise(afterT[1].Line, "「"+sym+"」は C の関数の名前ではありません")
		}
		if strings.HasPrefix(sym, "rt_") || strings.HasPrefix(sym, "suru_") {
			raise(afterT[1].Line, "「"+sym+"」は「する」の実行時が使う名前なので、外部の関数にできません")
		}
		return &Define{name, params, &Extern{Symbol: sym, Line: afterT[1].Line, CArgs: parseExternArgs(afterT[2 : len(afterT)-1])}, isFunction, node.Line.Number, "", nil}
	}
	if len(afterT) == 4 && afterT[0].Kind == "WORD" && afterT[0].S == KwExtern && !afterT[0].Quoted &&
		afterT[1].Kind == "LP" && afterT[2].Kind == "WORD" && afterT[3].Kind == "RP" && len(node.Children) == 0 {
		// 「x を f で 呼ぶ とは 外部の（f）」: 引数 f の番地にある C の関数を呼ぶ
		return &Define{name, params, &Extern{Line: afterT[2].Line, Pointer: afterT[2].S}, isFunction, node.Line.Number, "", nil}
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
	return &Define{name, params, body, isFunction, node.Line.Number, "", nil}
}

func isTypeWord(t *Token) bool {
	if t.Kind != "WORD" {
		return false
	}
	return builtinTypeSet[t.S] || curCtx.Types.Has(t.S) || (len([]rune(t.S)) == 1 && strings.Contains(typeVarNames, t.S))
}

const returnsOnlyFun = "「を 返す」は関数の型の宣言の終わりにだけ書けます(「数 を 階乗する は 数 を 返す」)"

// dropReturns は型の宣言の「は」より後ろの終わりの飾り「を 返す」「を 返します」を取り除く
func dropReturns(right []*Token) ([]*Token, bool) {
	n := len(right)
	if n >= 3 && right[n-2].Kind == "PART" && right[n-2].S == "を" && right[n-1].Kind == "KW" &&
		(right[n-1].S == KwHensu || right[n-1].S == KwHensuPolite) {
		return right[:n-2], true
	}
	return right, false
}

// actionReturning は型の宣言の中の「数 を 返す 動作」を「数 の 動作」にする(「入出力動作」も)
func actionReturning(tokens []*Token) []*Token {
	var out []*Token
	for i := 0; i < len(tokens); i++ {
		t := tokens[i]
		if t.Kind == "PART" && t.S == "を" && i+2 < len(tokens) && isKw(tokens[i+1], KwHensu) &&
			tokens[i+2].Kind == "WORD" && (tokens[i+2].S == "動作" || tokens[i+2].S == "入出力動作") && !tokens[i+2].Quoted {
			out = append(out, tok("KW", KwNo, t.Line), tokens[i+2])
			i += 2
			continue
		}
		out = append(out, t)
	}
	return out
}

func tryParseTypeSig(tokens []*Token) Node {
	ha := findTopLevel(tokens, KwWa)
	if ha <= 0 || ha == len(tokens)-1 {
		return nil
	}
	left, right := tokens[:ha], tokens[ha+1:]
	line := tokens[0].Line
	last := left[len(left)-1]
	right, returns := dropReturns(right)
	left, right = actionReturning(left), actionReturning(right)
	if last.Kind == "CALL" && last.Form == Suru && !last.Negated {
		// 関数: 「型 助詞 型 助詞 … 名前する は 型」(後ろに「を 返す」を付けてもよい)
		var params []TypeParam
		i := 0
		for i < len(left)-1 {
			var t Node
			t, i = parseParamType(left, i, len(left)-1)
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
	if (last.Kind == "WORD" || last.Kind == "CALL") && len(left) >= 2 && (left[len(left)-2].Kind == "PART" || isKw(left[len(left)-2], GA)) &&
		parsesAsType(right, line) {
		// 「数 で 流す は 数 を 返す 入出力動作」: 関数の型の宣言のつもりで、名前が「する」で終わっていない
		panic(notSuruError(last))
	}
	if len(left) == 1 && left[0].Kind == "WORD" && len(right) > 0 && (isTypeWord(right[0]) || right[0].Kind == "LP") {
		if len(right) == 1 && !isTypeWord(right[0]) {
			return nil
		}
		if returns {
			raise(line, returnsOnlyFun)
		}
		return &TypeSig{checkName(left[0]), nil, false, parseTypeAll(right, line), line}
	}
	return nil
}

// notSuruError は関数名が「する」で終わっていないときのエラー(「x で 流す とは …」「数 で 流す は 数」)
func notSuruError(last *Token) *SuruError {
	word := last.Value()
	if last.Kind == "CALL" && strings.HasSuffix(word, Suru) {
		word = strings.TrimSuffix(word, Suru) + last.Form
	}
	return &SuruError{Message: "関数名は「する」で終わる必要があります(「" + word + "」)", Line: last.Line}
}

func parsesAsType(tokens []*Token, line Pos) bool {
	return try(func() { parseTypeAll(tokens, line) }) == nil
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

// TupleType は引数の「文字列 と JSON を」の型(長さと要素ごとの型が決まったリスト)の TypeName の名前
const TupleType = "と"

// parseParamType は引数の型を1つ読む。「文字列 と JSON を」のように「と」でつなげば、定義の「名 と 値 を」に合わせて
// 要素ごとに型の違うリスト(TypeName{"と", [文字列, JSON]})
func parseParamType(tokens []*Token, i, end int) (Node, int) {
	t, i := parseType(tokens, i)
	items := []Node{t}
	for i < end-1 && isKw(tokens[i], KwTo) {
		t, i = parseType(tokens, i+1)
		items = append(items, t)
	}
	if len(items) == 1 {
		return t, i
	}
	return &TypeName{TupleType, items}, i
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
	if name == "入出力動作" {
		name = "動作" // 「入出力動作」は「動作」の別名
	}
	if len([]rune(name)) == 1 && strings.Contains(typeVarNames, name) && !t.Quoted {
		if len(args) > 0 {
			raise(t.Line, "「"+name+"」は型の引数をとりません")
		}
		return &TypeVarName{name}
	}
	if (name == "数" || name == "文字列" || name == "真偽" || name == "小数" || name == "整数" || name == "番地" || name == "バイト列" || name == "無" || name == "単精度") && len(args) > 0 {
		raise(t.Line, "「"+name+"」は型の引数をとりません")
	}
	if (name == "リスト" || name == "動作" || name == "C形") && len(args) != 1 {
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
			t, i = parseParamType(tokens[:k], i, k)
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
	if t.Qualified {
		return t.S
	}
	if strings.Contains(t.S, ModuleSep) {
		raise(t.Line, "「"+t.S+"」: 読み込んだファイルの中の名前は定義できません")
	}
	return t.S
}

// ShortTypeName は表示する型と形の名前: 読み込んだファイルの前置き(「部品内の」)を除く
func ShortTypeName(name string) string {
	if i := strings.LastIndex(name, ModuleSep); i >= 0 {
		return name[i+len(ModuleSep):]
	}
	return name
}

func isLibPath(path string) bool {
	if strings.HasPrefix(path, embeddedLibPrefix) {
		return true
	}
	if LibDir == "" {
		return false
	}
	lib, err1 := filepath.Abs(LibDir)
	dir, err2 := filepath.Abs(filepath.Dir(path))
	return err1 == nil && err2 == nil && lib == dir
}

// qualifyTypeNames: 型と形の名前は、ファイルごとに分ける(suru.py の _qualify_type_names と同じ)。
// 読み込んだファイル(lib/ のものを除く)の型「点」は、中では「点」、外では「部品内の点」が本当の名前。
// 外でも、ほかのファイルの型とぶつからなければ「点」と書ける。字句の名前を本当の名前に置きかえる
func qualifyTypeNames(nodes []*LNode, ctx *ParseContext) {
	own := map[string]string{}
	for _, n := range nodes {
		if td := tryParseTypedef(n); td != nil {
			own[td.Name] = ctx.Qualify + td.Name
			for _, c := range td.Ctors {
				own[c.Name] = ctx.Qualify + c.Name
			}
		}
	}
	type cand struct{ canon, mod string }
	candidates := map[string][]cand{} // 前置きなしの名前 → 本当の名前とそれを持つファイル(見つけた順)
	full := map[string]string{}       // 「部品内の点」 → 本当の名前
	add := func(m *Module, canon string) {
		name := ShortTypeName(canon)
		full[m.Name+ModuleSep+name] = canon
		for _, c := range candidates[name] {
			if c.canon == canon {
				return
			}
		}
		candidates[name] = append(candidates[name], cand{canon, m.Name})
	}
	if ctx.Order != nil {
		for _, p := range *ctx.Order {
			m := ctx.Modules[p]
			if m == nil {
				continue
			}
			for _, s := range m.Program {
				if td, ok := s.(*TypeDef); ok {
					add(m, td.Name)
					for _, c := range td.Ctors {
						add(m, c.Name)
					}
				}
			}
		}
	}
	if len(own) == 0 && len(candidates) == 0 {
		return
	}
	// 変数や引数の名前にした語は、2つのファイルにある型の名前でも変数の名前として読む(#105)
	local := localNames(nodes)
	var fix func(ns []*LNode)
	fix = func(ns []*LNode) {
		for _, n := range ns {
			for i, t := range n.Line.Tokens {
				if t.Kind != "WORD" {
					continue
				}
				v := t.S
				canon, ok := own[v]
				if !ok {
					if cs := candidates[v]; len(cs) > 1 && local[v] {
						continue
					} else if len(cs) > 1 {
						names := make([]string, len(cs))
						for k, c := range cs {
							names[k] = "「" + c.mod + "」"
						}
						raise(t.Line, "「"+v+"」は"+strings.Join(names, "と")+"の両方にある型か形の名前です。「"+cs[0].mod+ModuleSep+v+"」のようにファイルの名前を付けて書いてください")
					} else if len(cs) == 1 {
						canon, ok = cs[0].canon, true
					} else {
						canon, ok = full[v]
					}
				}
				if ok && (canon != v || strings.Contains(canon, ModuleSep)) {
					nt := *t
					nt.S = canon
					nt.Qualified = strings.Contains(canon, ModuleSep)
					n.Line.Tokens[i] = &nt
				}
			}
			fix(n.Children)
		}
	}
	fix(nodes)
}

// localNames: ファイルの中で変数や引数の名前にした語(suru.py の _local_names と同じ)。
// 「x とは …」の x と、「s に x を 接続 で 案内する とは …」の助詞の前の名前(括弧の外のもの)
func localNames(nodes []*LNode) map[string]bool {
	names := map[string]bool{}
	var visit func(ns []*LNode)
	visit = func(ns []*LNode) {
		for _, n := range ns {
			var toks []*Token
			for _, t := range n.Line.Tokens {
				if t.Kind != "SEP" {
					toks = append(toks, t)
				}
			}
			if len(toks) > 0 && isKw(toks[0], KwProviso) {
				toks = toks[1:]
			}
			depth := 0
			for k, t := range toks {
				if t.Kind == "LP" {
					depth++
				} else if t.Kind == "RP" {
					depth--
				} else if depth == 0 && isKw(t, KwTowa) {
					head := toks[:k]
					if len(head) == 1 && head[0].Kind == "WORD" {
						names[head[0].S] = true
					} else if len(head) > 0 && head[len(head)-1].Kind == "CALL" {
						d := 0
						for j, h := range head {
							if h.Kind == "LP" {
								d++
							} else if h.Kind == "RP" {
								d--
							}
							if d == 0 && h.Kind == "WORD" && j+1 < len(head) && head[j+1].Kind == "PART" {
								names[h.S] = true
							}
						}
					}
					break
				}
			}
			visit(n.Children)
		}
	}
	visit(nodes)
	return names
}

func tryParseTypedef(node *LNode) *TypeDef {
	tokens := nosep(flatten(node))
	towa := findTopLevel(tokens, KwTowa)
	if towa != 1 || tokens[0].Kind != "WORD" {
		return nil
	}
	body := splitTrailingKumi(tokens[2:])
	hasKa := findTopLevel(body, KwKa) >= 0
	if len(body) == 0 || !(hasKa || isKw(body[len(body)-1], KwKumi)) {
		return nil
	}
	name := checkName(tokens[0])
	line := tokens[0].Line
	var ctors []Ctor
	typed := 0 // フィールドの型を書いたか(0: まだフィールドがない、1: 書いた、-1: 書いていない)
	var fieldTypes []FieldTypeToks
	mixed := "フィールドの型は、型のすべてのフィールドに書くか、どれにも書かないかにしてください"
	style := "" // 型の書き方(「は」か「かっこ」)。1つの型の中ではそろえる
	typedField := func(nameTok *Token, typeToks []*Token, fields []string, kind string) []string {
		if style != "" && style != kind {
			raise(nameTok.Line, typedStyleMixed)
		}
		style = kind
		f := checkName(nameTok)
		if contains(fields, f) {
			raise(nameTok.Line, "フィールド名「"+f+"」が2回書かれています")
		}
		fields = append(fields, f)
		// 「数 を 返す 動作」は型の宣言と同じく「数 の 動作」と読む(#206)
		typeToks = actionReturning(typeToks)
		for _, ft := range fieldTypes {
			if ft.Name == f {
				if !sameTokenValues(ft.Toks, typeToks) {
					raise(nameTok.Line, "フィールド「"+f+"」の型が形ごとに違います(同じ名前のフィールドは同じ型にしてください)")
				}
				return fields
			}
		}
		fieldTypes = append(fieldTypes, FieldTypeToks{f, typeToks})
		return fields
	}
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
		if findTopLevel(alt[:len(alt)-2], KwWa) >= 0 {
			// 「番号 は 数 で 名前 は 文字列 の 会員」: フィールドごとに型を書く
			if typed < 0 {
				raise(last.Line, mixed)
			}
			typed = 1
			for _, part := range splitTypedFields(alt[:len(alt)-2], last.Line) {
				if len(part) < 3 || !isKw(part[1], KwWa) {
					if hasKind(part, "LP") {
						raise(part[0].Line, typedStyleMixed)
					}
					l := last.Line
					if len(part) > 0 {
						l = part[0].Line
					}
					raise(l, "型を書くフィールドは「番号 は 数 で 名前 は 文字列 の 組」のように"+
						"「フィールド名 は 型」を「で」で区切って書いてください")
				}
				fields = typedField(part[0], part[2:], fields, "は")
			}
			ctors = append(ctors, Ctor{cname, fields})
			continue
		}
		if hasKind(alt[:len(alt)-2], "LP") {
			// 「番号 （数） と 名前 （文字列） の 品」: フィールド名の後ろのかっこに型を書く
			if typed < 0 {
				raise(last.Line, mixed)
			}
			typed = 1
			for _, pf := range splitParenFields(alt[:len(alt)-2], last.Line) {
				fields = typedField(pf.name, pf.toks, fields, "かっこ")
			}
			ctors = append(ctors, Ctor{cname, fields})
			continue
		}
		if len(alt) > 2 {
			if typed > 0 {
				raise(last.Line, mixed)
			}
			typed = -1
		}
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
	td := &TypeDef{Name: name, Ctors: ctors, Line: line}
	if typed > 0 {
		td.FieldTypes = fieldTypes
	}
	return td
}

const typedStyleMixed = "フィールドの型は、1つの型の中では「番号 は 数 で 名前 は 文字列 の 組」か" +
	"「番号 （数） と 名前 （文字列） の 組」のどちらかの書き方にそろえてください"

func hasKind(tokens []*Token, kind string) bool {
	for _, t := range tokens {
		if t.Kind == kind {
			return true
		}
	}
	return false
}

// splitTrailingKumi は空白の書き方で詰めて書いた最後の「の組」を「の 組」に分ける(「番号 と 名前 の組」)
func splitTrailingKumi(body []*Token) []*Token {
	n := len(body)
	if n >= 2 && body[n-1].Kind == "WORD" && body[n-1].S == KwNo+KwKumi && !body[n-1].Quoted &&
		!body[n-1].Qualified && (body[n-2].Kind == "WORD" || body[n-2].Kind == "RP") {
		last := body[n-1]
		out := append([]*Token{}, body[:n-1]...)
		return append(out, &Token{Kind: "KW", S: KwNo, Line: last.Line}, &Token{Kind: "KW", S: KwKumi, Line: last.Line})
	}
	return body
}

type parenField struct {
	name *Token
	toks []*Token
}

// splitParenFields は「番号 （数） と 名前 （文字列）」を、フィールド名とかっこの中の型の字句に分ける
func splitParenFields(tokens []*Token, line Pos) []parenField {
	var out []parenField
	i := 0
	for {
		if i >= len(tokens) {
			raise(line, "「と」の後にフィールド名が必要です")
		}
		nameTok := tokens[i]
		if nameTok.Kind == "LP" {
			raise(nameTok.Line, "かっこの前にフィールド名を書いてください(「番号 （数）」)")
		}
		if isKw(nameTok, KwWa) {
			raise(nameTok.Line, typedStyleMixed)
		}
		if i+1 >= len(tokens) || tokens[i+1].Kind != "LP" {
			if i+1 < len(tokens) && isKw(tokens[i+1], KwWa) {
				raise(tokens[i+1].Line, typedStyleMixed)
			}
			if i+1 < len(tokens) && !isKw(tokens[i+1], KwTo) {
				raise(tokens[i+1].Line, "フィールド名は「と」で区切ってください")
			}
			raise(nameTok.Line, "フィールドの型は、型のすべてのフィールドに書くか、どれにも書かないかにしてください")
		}
		j := matching(tokens, i+1)
		inner := tokens[i+2 : j]
		if len(inner) == 0 {
			raise(tokens[i+1].Line, "「"+nameTok.Value()+"」のかっこの中に型を書いてください")
		}
		// 関数の型はかっこごと(「は」の書き方の「処理 は （数 を 受け取って 数 を 返すこと）」と同じ字句)
		if findTopLevel(inner, KwReturn) >= 0 {
			out = append(out, parenField{nameTok, tokens[i+1 : j+1]})
		} else {
			out = append(out, parenField{nameTok, inner})
		}
		i = j + 1
		if i == len(tokens) {
			return out
		}
		if isKw(tokens[i], KwWa) || isPart(tokens[i], "で") {
			raise(tokens[i].Line, typedStyleMixed)
		}
		if !isKw(tokens[i], KwTo) {
			raise(tokens[i].Line, "フィールドは「と」で区切ってください(「番号 （数） と 名前 （文字列）」)")
		}
		i++
	}
}

// splitTypedFields は「番号 は 数 で 名前 は 文字列」を「で」(括弧の外)で分ける
func splitTypedFields(tokens []*Token, line Pos) [][]*Token {
	out := [][]*Token{{}}
	depth := 0
	for _, t := range tokens {
		if t.Kind == "LP" {
			depth++
		} else if t.Kind == "RP" {
			depth--
		}
		if depth == 0 && t.Kind == "PART" && t.S == "で" {
			if len(out[len(out)-1]) == 0 {
				raise(t.Line, "「で」の前にフィールドを書いてください")
			}
			out = append(out, []*Token{})
		} else {
			out[len(out)-1] = append(out[len(out)-1], t)
		}
	}
	if len(out[len(out)-1]) == 0 {
		raise(line, "「で」の後にフィールドを書いてください")
	}
	return out
}

func sameTokenValues(a, b []*Token) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i].S != b[i].S {
			return false
		}
	}
	return true
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
		members = []*LNode{{&Line{Indent: node.Line.Indent, Tokens: after, Number: line, Closed: node.Line.Closed}, node.Children}}
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
	return &Do{[]Node{first, expr}, lineOf(first), true, false}
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
	return &Do{statements, line, false, false}
}

// --- プログラムとファイルの読み込み ---

// ParseProgram はプログラムを解析する。見つけた型を ctx に登録する
func ParseProgram(source string, ctx *ParseContext) []Node {
	lines := must(splitSourceLines(source))
	nodes := buildLayout(lines)
	imports := map[*LNode]Node{}
	var modNames []string
	var mods []*Module
	for _, n := range nodes {
		if lib := externLibTarget(n, ctx); lib != nil {
			imports[n] = lib
			continue
		}
		if name, open, ok := importTarget(n); ok {
			imp := &Import{loadModule(name, ctx, n.Line.Number), n.Line.Number, open, false}
			imports[n] = imp
			modNames = append(modNames, imp.Module.Name)
			mods = append(mods, imp.Module)
		}
	}
	if hasQuasi(nodes) {
		quasiScope = nodes
		nodes = expandQuasi(nodes, mods, 0, true, ctx)
		quasiScope = nil
	}
	var prelude *Import
	if !ctx.InPrelude && !hasPreludeImport(imports) {
		if line, ok := preludeLine(nodes); ok {
			prelude = &Import{loadPrelude(ctx, line), line, true, false}
			modNames = append(modNames, PreludeName)
		}
	}
	var testImport *Import
	for _, n := range nodes {
		if ts := nosep(n.Line.Tokens); len(ts) > 0 && isTestHead(ts[0]) {
			// 試験のまとまりの中では「試験」の名前(一致確認する など)を前置きなしで使える(#193)
			opened := false
			for _, imp := range imports {
				if i, ok := imp.(*Import); ok && i.Open && i.Module.Name == TestLib && isLibPath(i.Module.Path) {
					opened = true
				}
			}
			if !opened && !(splitExt(pathBase(ctx.Path)) == TestLib && isLibPath(ctx.Path)) {
				testImport = &Import{loadModule(TestLib, ctx, n.Line.Number), n.Line.Number, true, true}
				modNames = append(modNames, testImport.Module.Name)
			}
			break
		}
	}
	if len(modNames) > 0 {
		joinInNodes(nodes, setOf(modNames...))
	}
	qualifyTypeNames(nodes, ctx)
	var tds []*TypeDef
	for _, n := range nodes {
		if td := tryParseTypedef(n); td != nil {
			ctx.add(td)
			tds = append(tds, td)
		}
	}
	saved := curCtx
	curCtx = ctx
	defer func() { curCtx = saved }()
	ctx.resolveFieldTypes(tds)
	var statements []Node
	for _, n := range nodes {
		if imp, ok := imports[n]; ok {
			statements = append(statements, imp)
		} else {
			statements = append(statements, parseStatement(n))
		}
	}
	if testImport != nil {
		statements = append([]Node{testImport}, statements...)
	}
	if prelude != nil {
		statements = append([]Node{prelude}, statements...)
	}
	nameExamples(statements)
	checkOpenImports(statements)
	attachExterns(statements)
	attachExports(statements)
	statements = attachProvisos(statements)
	for _, st := range statements {
		switch st.(type) {
		case *Import, *ExternLib:
		default:
			nameUnwraps(st, topFn)
			resolveParamCalls(st, nil)
			splitBranchRuns(st)
		}
	}
	return statements
}

// patternNames はパターン(引数の名前・名前のリスト・形のパターン)が付ける名前を out に足す
func patternNames(pat Node, out map[string]bool) {
	switch p := pat.(type) {
	case *PBind:
		out[p.Name] = true
	case *PSeq:
		for _, x := range p.Items {
			patternNames(x, out)
		}
	case *PCtor:
		for _, x := range p.Items {
			patternNames(x, out)
		}
	case *PNamed:
		for _, f := range p.Fields {
			patternNames(f.Value, out)
		}
	}
}

func paramNames(params []Param, local map[string]bool) map[string]bool {
	out := map[string]bool{}
	for k := range local {
		out[k] = true
	}
	for _, p := range params {
		switch {
		case p.Pat != nil:
			patternNames(p.Pat, out)
		case p.List:
			for _, x := range p.Names {
				out[x] = true
			}
		default:
			out[p.Name] = true
		}
	}
	return out
}

func withNames(local map[string]bool, names []string) map[string]bool {
	out := map[string]bool{}
	for k := range local {
		out[k] = true
	}
	for _, x := range names {
		out[x] = true
	}
	return out
}

func defNames(statements []Node) []string {
	var out []string
	for _, st := range statements {
		if d, ok := st.(*Define); ok {
			out = append(out, d.Name)
		}
	}
	return out
}

// resolveParamCalls は「累 を 行 で 処理する」: 関数を受け取った引数(や局所の名前)「処理」を、名前+「する」で呼ぶ。
// 同じ名前の局所の関数「処理する」があればそちらを使い、引数の名前は関数の外の定義より先に見る(suru.py と同じ)
func resolveParamCalls(node Node, local map[string]bool) {
	fix := func(name *string) {
		if strings.HasSuffix(*name, Suru) && len(*name) > len(Suru) {
			stem := strings.TrimSuffix(*name, Suru)
			if !local[*name] && local[stem] {
				*name = stem
			}
		}
	}
	switch n := node.(type) {
	case nil:
		return
	case *Import, *Module:
		return
	case *Call:
		fix(&n.Name)
	case *Ref:
		fix(&n.Name)
	case *Define:
		if len(n.Params) > 0 {
			local = paramNames(n.Params, local)
		}
	case *Lambda:
		local = paramNames(n.Params, local)
	case *Block:
		local = withNames(local, defNames(n.Statements))
	case *Do:
		local = withNames(local, defNames(n.Statements))
	case *Match:
		resolveParamCalls(n.Subject, local)
		for _, c := range n.Cases {
			inner := map[string]bool{}
			for k := range local {
				inner[k] = true
			}
			patternNames(c.Pat, inner)
			resolveParamCalls(c.Guard, inner)
			resolveParamCalls(c.Body, inner)
		}
		resolveParamCalls(n.Default, local)
		return
	}
	for _, ch := range node.Children() {
		resolveParamCalls(ch, local)
	}
}

// 関数の外と無名関数の「した 中身」の経路の名前
const (
	topFn    = "一番外"
	lambdaFn = "無名関数"
)

// nameUnwraps は「した 中身」に、それを書いた一番内側の関数の名前を付ける(失敗の経路に使う)
func nameUnwraps(node Node, fn string) {
	switch n := node.(type) {
	case nil:
		return
	case *Import, *Module:
		return
	case *Define:
		if n.IsFunction {
			parts := strings.Split(n.Name, "\x00")
			fn = parts[len(parts)-1]
		}
	case *Lambda:
		fn = lambdaFn
	case *Run:
		n.Fn = fn
	}
	for _, ch := range node.Children() {
		nameUnwraps(ch, fn)
	}
}

// parseExternArgs は「（a と 0 と b）」の中: 引数の名前か整数を「と」でつないだもの
func parseExternArgs(toks []*Token) []ExternArg {
	bad := func(t *Token) {
		raise(t.Line, "外部の関数の引数の並びには、引数の名前か整数を「と」でつないで書きます(「（a と 0 と b）」)")
	}
	var out []ExternArg
	inner := toks[1:]
	if len(inner) == 0 {
		bad(toks[0])
	}
	for i, t := range inner {
		if i%2 == 1 {
			if !isKw(t, KwTo) || i == len(inner)-1 {
				bad(t)
			}
			continue
		}
		switch {
		case t.Kind == "WORD" && !t.Quoted && t.S != KwExtern:
			out = append(out, ExternArg{Name: t.S, Line: t.Line})
		case t.Kind == "NUM" && t.N.Kind == NInt && t.N.I.IsInt64():
			out = append(out, ExternArg{IsConst: true, Const: t.N.I.Int64(), Line: t.Line})
		default:
			bad(t)
		}
	}
	return out
}

// 基本(成否・有無)は、その名前を書いたファイルが自動で「読み込んで 使う」
const PreludeName = "基本"

var preludeWords = setOf("成否", "有無", "成功", "失敗", "有")
var preludeCalls = setOf("成否にする", "有無にする", "中断する", "失敗説明する", "失敗詳細にする", "数値確認する", "入力確認する", "試算する") // 取出する は性質の関数なので入れない

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
					t.S == "無" && !(k > 0 && isKw(n.Line.Tokens[k-1], KwWa)) ||
					// 「で」のない「試行する」は成否を返す
					t.Kind == "CALL" && t.S == "試行する" && !lineHasPart(n.Line.Tokens, "で")) {
				return n.Line.Number, true
			}
		}
		if line, ok := preludeWordLine(n.Children); ok {
			return line, true
		}
	}
	return Pos{}, false
}

func lineHasPart(tokens []*Token, part string) bool {
	for _, u := range tokens {
		if u.Kind == "PART" && u.S == part {
			return true
		}
	}
	return false
}

// loadPrelude は lib/基本.suru を読む(同じフォルダに 基本.suru があっても、いつも同梱のもの)
func loadPrelude(ctx *ParseContext, line Pos) *Module {
	path := libPath(PreludeName + SourceSuffix)
	if m, ok := ctx.Modules[path]; ok {
		return m
	}
	libraryFiles.Store(path, true)
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
	mainThread := len(tokens) == 5 && tokens[3].Kind == "WORD" && tokens[3].S == KwMainThread && !tokens[3].Quoted
	if mainThread {
		tokens = append(append([]*Token{}, tokens[:3]...), tokens[4:]...)
	}
	if len(tokens) != 4 || tokens[1].Kind != "STR" || !(tokens[2].Kind == "PART" && tokens[2].S == WO) ||
		!(isKw(tokens[3], KwImport) || isKw(tokens[3], KwImportPolit)) || node.Line.Indent != 0 {
		raise(tokens[0].Line, "外部のライブラリは一番外に「"+KwExtern+"「m」 を "+KwImport+"」"+
			"(主スレッドで呼ぶなら「"+KwExtern+"「m」 を "+KwMainThread+" "+KwImport+"」)のように書いて読み込みます")
	}
	name := tokens[1].S
	if name == "" {
		raise(tokens[0].Line, "外部のライブラリの名前が空です")
	}
	path := name
	if strings.Contains(name, "/") || strings.HasSuffix(name, ".so") || strings.HasSuffix(name, ".dylib") {
		path = absPath(filepath.Join(ctx.BaseDir, name))
	}
	return &ExternLib{name, path, tokens[0].Line, mainThread}
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
	mainThread := false
	sigs := map[string]*TypeSig{}
	for _, s := range statements {
		switch x := s.(type) {
		case *ExternLib:
			libs = append(libs, x.Path)
			mainThread = mainThread || x.MainThread
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
		if ext.CArgs != nil {
			used := map[int]bool{}
			for i, a := range ext.CArgs {
				if a.IsConst {
					continue
				}
				k := -1
				for j, p := range d.Params {
					if p.Name == a.Name {
						k = j
					}
				}
				if k < 0 {
					raise(a.Line, "「"+a.Name+"」は「"+d.Name+"」の引数ではありません")
				}
				ext.CArgs[i].Param = k
				used[k] = true
			}
			for j, p := range d.Params {
				if !used[j] {
					raise(d.Line, "外部の関数「"+d.Name+"」の引数「"+p.Name+"」を C に渡していません(「（…）」の中に書きます)")
				}
			}
		}
		result := sig.Result
		if tn, ok := result.(*TypeName); ok && tn.Name == "動作" {
			ext.Action = true
			result = tn.Args[0]
		}
		ext.Result = ffiType(result, sig, "値")
		ext.Libs = libs
		ext.MainThread = mainThread
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

// exportReserved は外部に出す C の名前に使えない頭(実行時ライブラリと IR の名前)
var exportReserved = []string{"rt_", "suru_", "gc_"}

// attachExports は「以下は外部に出す関数です」の行に、同じファイルの型の宣言から C の型を付ける(#208)
func attachExports(statements []Node) {
	sigs := map[string]*TypeSig{}
	defs := map[string]*Define{}
	externs := map[string]bool{}
	for _, s := range statements {
		switch x := s.(type) {
		case *TypeSig:
			sigs[x.Name] = x
		case *Define:
			defs[x.Name] = x
			if ext, ok := x.Body.(*Extern); ok {
				externs[ext.Symbol] = true
			}
		}
	}
	for _, s := range statements {
		e, ok := s.(*Export)
		if !ok {
			continue
		}
		if !isCSymbol(e.Symbol) {
			raise(e.Line, "「"+e.Symbol+"」は C の名前にできません(英字か「_」で始まり、英字・数字・「_」だけで書きます)")
		}
		for _, r := range exportReserved {
			if strings.HasPrefix(e.Symbol, r) {
				raise(e.Line, "C の名前「"+e.Symbol+"」は「"+r+"」で始まるので使えません(実行時ライブラリの名前とぶつかります)")
			}
		}
		if e.Symbol == "main" {
			raise(e.Line, "C の名前「main」は使えません")
		}
		if externs[e.Symbol] {
			raise(e.Line, "C の名前「"+e.Symbol+"」は、このファイルで読み込む外部の関数と同じです")
		}
		d := defs[e.Name]
		if d == nil {
			raise(e.Line, "「"+e.Name+"」はこのファイルで定義していないので、外部に出せません")
		}
		if _, ok := d.Body.(*Extern); ok {
			raise(e.Line, "「"+e.Name+"」は外部の関数なので、外部に出せません")
		}
		sig := sigs[e.Name]
		if !d.IsFunction || sig == nil || !sig.HasParams {
			raise(e.Line, "外部に出す関数「"+e.Name+"」には型の宣言が必要です(「数 を 二倍する は 数 を 返す」のように書きます)")
		}
		types := map[string]Node{}
		for _, p := range sig.Params {
			types[p.Part] = p.Type
		}
		e.Params = nil
		for _, p := range d.Params {
			if p.List || !p.simple() {
				raise(e.Line, "外部に出す関数「"+e.Name+"」の引数は名前だけで書いてください")
			}
			e.Params = append(e.Params, exportType(types[p.Part], e, "「"+p.Part+"」"))
		}
		result := sig.Result
		if tn, ok := result.(*TypeName); ok && tn.Name == "動作" {
			e.Action = true
			result = tn.Args[0]
		}
		e.Result = exportType(result, e, "値")
	}
}

// exportTypeNames は外部に出す関数で、C の値でそのまま渡せる型(無は値だけ)
var exportTypeNames = []string{"数", "小数", "単精度", "整数", "真偽", "文字列", "番地", "バイト列", "無"}

// exportListTypes は外部に出す関数に使えるリストの型(要素の型 → 型の名前、#208 段階3)。C では番地と長さの2つで渡す
var exportListTypes = []string{"数", "list_i64", "小数", "list_f64", "文字列", "list_str"}

// exportType は出す関数の引数・値の型 → C での渡し方。数などはそのまま、数・小数・文字列のリストとバイト列は番地と長さ、
// ほかの型(組・ほかのリスト・関数など)は中を見ない手札(val)で渡す(#208 段階3)
func exportType(te Node, e *Export, what string) string {
	if tn, ok := te.(*TypeName); ok && len(tn.Args) == 0 {
		for _, n := range exportTypeNames {
			if n == tn.Name {
				if n == "無" && what != "値" {
					raise(e.Line, "外部に出す関数「"+e.Name+"」の"+what+"に 無 は使えません(無 は値だけに書けます)")
				}
				return ffiTypes[n]
			}
		}
	}
	if tn, ok := te.(*TypeName); ok && tn.Name == "リスト" && len(tn.Args) == 1 {
		if el, ok := tn.Args[0].(*TypeName); ok && len(el.Args) == 0 {
			for k := 0; k < len(exportListTypes); k += 2 {
				if exportListTypes[k] == el.Name {
					return exportListTypes[k+1]
				}
			}
		}
	}
	return "val"
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
	for _, b := range mainLibPrimitives(m.Path) {
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

// --- 準クォートの展開(#192) ---

// Expander は展開の関数 fname(読み込んだファイル mod の中)に中身 body を渡して動かす。成功なら ok が true で out が
// する のソース、失敗なら ok が false で out が失敗の文。動かせなければ err。suruc などのコマンドが入れる
var Expander func(mod *Module, fname, body string) (ok bool, out string, err error)

// QuasiExpansion は「--展開」のための、一番外のファイルの準クォートと展開したソース
type QuasiExpansion struct {
	Start, End int    // 頭の行と「以上」の行
	Src        string // 展開したソース
	ExprIndent int    // 式の形なら頭の字下げ、一番外の形なら -1
}

// QuasiRecord を入れておくと、Ctx のファイルの準クォートを Items に足す(suruc --展開)
var QuasiRecord *struct {
	Ctx   *ParseContext
	Items []QuasiExpansion
}

var quasiFailLine = regexp.MustCompile(`(?s)^([0-9]+)行目[:：][ \t　]*(.*)$`)

func hasQuasi(nodes []*LNode) bool {
	for _, n := range nodes {
		if n.Line.HasQuasi || n.Line.Derive != nil || hasQuasi(n.Children) {
			return true
		}
	}
	return false
}

// findExpander は【name】の展開の関数「name展開する」(derive なら導出の関数「name導出する」)を、読み込んだファイルから探す
func findExpander(name string, mods []*Module, line Pos, derive bool) (*Module, string) {
	fname, kind, arg := name+quasiSuffix, "展開", "文字列"
	if derive {
		fname, kind, arg = name+deriveSuffix, "導出", "型記述"
	}
	var found []*Module
	for _, m := range mods {
		if m.Private[fname] {
			continue
		}
		for _, d := range m.Program {
			if def, ok := d.(*Define); ok && def.Name == fname {
				found = append(found, m)
				break
			}
		}
	}
	if len(found) == 0 {
		raise(line, "【"+name+"】の"+kind+"の関数「"+fname+"」が、読み込んだファイルにありません"+
			"(「"+arg+" を "+fname+" は 文字列 の 成否」を定義したファイルを読み込んでください)")
	}
	if len(found) > 1 {
		var names []string
		for _, m := range found {
			names = append(names, "「"+m.Name+"」")
		}
		raise(line, "【"+name+"】の"+kind+"の関数「"+fname+"」が"+strings.Join(names, "と")+"の両方にあります")
	}
	return found[0], fname
}

// runExpander は【name】の中身を展開の関数に渡し、返した する のソースを返す
func runExpander(name, body string, mods []*Module, line Pos) string {
	mod, fname := findExpander(name, mods, line, false)
	if Expander == nil {
		raise(line, "【"+name+"】: この道具では準クォートを展開できません")
	}
	savedFile := curPosFile
	curPosFile = ""
	ok, out, err := Expander(mod, fname, body)
	curPosFile = savedFile
	if err != nil {
		raise(line, "【"+name+"】の展開の関数「"+fname+"」が止まりました: "+err.Error())
	}
	if ok {
		return out
	}
	if m := quasiFailLine.FindStringSubmatch(out); m != nil {
		n, _ := strconv.Atoi(m[1])
		raise(Pos{line.Line + n, 0, line.File}, "【"+name+"】の"+m[1]+"行目: "+m[2])
	}
	raise(line, "【"+name+"】: "+out)
	return ""
}

// expandQuasi は準クォートを、展開の関数が返した する のコードに置きかえる(suru.py の expand_quasi と同じ)
func expandQuasi(nodes []*LNode, mods []*Module, depth int, top bool, ctx *ParseContext) []*LNode {
	var out []*LNode
	for _, n := range nodes {
		if n.Line.Derive != nil {
			out = append(out, expandDerive(n, nodes, mods, depth, top, ctx)...)
			continue
		}
		if !n.Line.HasQuasi {
			n.Children = expandQuasi(n.Children, mods, depth, false, ctx)
			out = append(out, n)
			continue
		}
		toks := n.Line.Tokens
		name, line := toks[len(toks)-1].S, n.Line.Number
		if depth >= quasiMaxDepth {
			raisef(line, "【%s】の展開が深すぎます(展開したコードの中の準クォートが%d回続きました)", name, quasiMaxDepth)
		}
		if len(toks) == 1 && !top {
			raise(line, "「以下は【"+name+"】です」は一番外(字下げなし)にだけ書けます")
		}
		src := runExpander(name, n.Line.Quasi, mods, line)
		if depth == 0 && QuasiRecord != nil && QuasiRecord.Ctx == ctx {
			ind := -1
			if len(toks) > 1 {
				ind = n.Line.Indent
			}
			QuasiRecord.Items = append(QuasiRecord.Items, QuasiExpansion{line.Line, n.Line.QuasiEnd, src, ind})
		}
		var made []*LNode
		if strings.TrimSpace(src) != "" {
			made = buildLayout(must(splitSourceLinesAt(src, line)))
		}
		made = expandQuasi(made, mods, depth+1, len(toks) == 1, ctx)
		if len(toks) == 1 {
			for _, m := range made {
				if _, _, ok := importTarget(m); ok {
					raise(line, "【"+name+"】の展開したコードには、読み込みの文を書けません")
				}
			}
			out = append(out, made...)
			continue
		}
		// 「x とは 以下の【SQL】です」: 展開したものを式として x の定義の本体にする
		head := append([]*Token{}, toks[:len(toks)-1]...)
		switch {
		case len(made) == 1 && len(made[0].Children) == 0:
			body := append(append(head, &Token{Kind: "LP", S: "(", Line: line}), made[0].Line.Tokens...)
			body = append(body, &Token{Kind: "RP", S: ")", Line: line})
			n.Line = &Line{Indent: n.Line.Indent, Tokens: body, Number: line, Closed: n.Line.Closed}
		case len(made) > 0:
			n.Line = &Line{Indent: n.Line.Indent, Tokens: head, Number: line, Closed: n.Line.Closed}
			n.Children = reindent(made, n.Line.Indent+2)
		default:
			raise(line, "【"+name+"】の展開の関数が空のコードを返しました(式の場所には式が要ります)")
		}
		out = append(out, n)
	}
	return out
}

// --- 導出(#192): 「会員 は 【JSON】 と 【表】 を 導出する」 ---

// Deriver は導出の関数 fname(読み込んだファイル mod の中)に、型の記述(する の式のソース desc)を渡して動かす
var Deriver func(mod *Module, fname, desc string) (ok bool, out string, err error)

// quasiScope は展開しているファイルの一番外の行(導出する型の定義を探す)
var quasiScope []*LNode

// expandDerive は導出の行を、導出の関数が返した定義にする(suru.py の _expand_derive と同じ)
func expandDerive(n *LNode, scope []*LNode, mods []*Module, depth int, top bool, ctx *ParseContext) []*LNode {
	tname, line := n.Line.Tokens[0].S, n.Line.Number
	names := n.Line.Derive
	if !top || n.Line.Indent != 0 {
		raise(line, "「"+tname+" は 【"+strings.Join(names, "】 と 【")+"】 を 導出する」は一番外(字下げなし)にだけ書けます")
	}
	if depth >= quasiMaxDepth {
		raisef(line, "【%s】の展開が深すぎます(展開したコードの中の準クォートが%d回続きました)", names[0], quasiMaxDepth)
	}
	desc := typeDescription(tname, [][]*LNode{scope, quasiScope}, line, ctx)
	var srcs []string
	for _, x := range names {
		if src := runDeriver(tname, x, desc, mods, line); strings.TrimSpace(src) != "" {
			srcs = append(srcs, strings.TrimRight(src, "\n"))
		}
	}
	src := strings.Join(srcs, "\n")
	if depth == 0 && QuasiRecord != nil && QuasiRecord.Ctx == ctx {
		QuasiRecord.Items = append(QuasiRecord.Items, QuasiExpansion{line.Line, line.Line, src, -1})
	}
	var made []*LNode
	if strings.TrimSpace(src) != "" {
		made = buildLayout(must(splitSourceLinesAt(src, line)))
	}
	made = expandQuasi(made, mods, depth+1, true, ctx)
	for _, m := range made {
		if _, _, ok := importTarget(m); ok {
			raise(line, "【"+names[0]+"】の導出したコードには、読み込みの文を書けません")
		}
	}
	return made
}

// runDeriver は型の記述を導出の関数に渡し、返した する のソースを返す
func runDeriver(tname, name, desc string, mods []*Module, line Pos) string {
	mod, fname := findExpander(name, mods, line, true)
	if Deriver == nil {
		raise(line, "【"+name+"】: この道具では導出できません")
	}
	savedFile := curPosFile
	curPosFile = ""
	ok, out, err := Deriver(mod, fname, desc)
	curPosFile = savedFile
	if err != nil {
		raise(line, "【"+name+"】の導出の関数「"+fname+"」が止まりました: "+err.Error())
	}
	if !ok {
		raise(line, "【"+name+"】で「"+tname+"」を導出できません: "+out)
	}
	return out
}

// typeDescription は tname の型の記述(lib/導出.suru の 型記述 の値)を、する の式のソースにする。型は同じファイルで定義したもの
func typeDescription(tname string, scopes [][]*LNode, line Pos, ctx *ParseContext) string {
	var tds []*TypeDef
	var td *TypeDef
	for _, nodes := range scopes {
		for _, n := range nodes {
			if n.Line.HasQuasi || n.Line.Derive != nil {
				continue
			}
			if d := tryParseTypedef(n); d != nil {
				tds = append(tds, d)
				if td == nil && d.Name == tname {
					td = d
				}
			}
		}
	}
	if td == nil {
		raise(line, "「"+tname+"」の型の定義がこのファイルにありません(導出できるのは同じファイルで定義した型です)")
	}
	hasFields := false
	for _, c := range td.Ctors {
		if len(c.Fields) > 0 {
			hasFields = true
		}
	}
	if td.FieldTypes == nil && hasFields {
		raise(line, "「"+tname+"」のフィールドに型が書かれていないので導出できません"+
			"(「"+tname+" とは 番号 は 数 で 名前 は 文字列 の 組」のように書きます)")
	}
	// 型の名前を確かめるために、このファイルの型を(まだ集めていないので)ここで集める
	tmp := *ctx
	tmp.Types = ctx.Types.Copy()
	for _, d := range tds {
		if !tmp.Types.Has(d.Name) {
			var cs []string
			for _, c := range d.Ctors {
				cs = append(cs, c.Name)
			}
			tmp.Types.Set(d.Name, cs)
		}
	}
	saved := curCtx
	curCtx = &tmp
	types := map[string]Node{}
	for _, ft := range td.FieldTypes {
		types[ft.Name] = parseTypeAll(ft.Toks, td.Line)
	}
	curCtx = saved
	var tvars []string
	var ctors []string
	for _, c := range td.Ctors {
		var fs []string
		for _, f := range c.Fields {
			typeVarsOf(types[f], &tvars)
			fs = append(fs, "（欄名 は "+descStr(f)+" で 欄型 は "+typeForm(types[f])+" の 欄記述）")
		}
		ctors = append(ctors, "（形名 は "+descStr(c.Name)+" で 欄群 は "+descList(fs)+" の 形記述）")
	}
	var vs []string
	for _, v := range tvars {
		vs = append(vs, descStr(v))
	}
	return "（型名 は " + descStr(tname) + " で 型引数 は " + descList(vs) + " で 形群 は " + descList(ctors) + " の 型記述）"
}

func descStr(s string) string { return "「" + s + "」" }

func descList(xs []string) string {
	switch len(xs) {
	case 0:
		return "空"
	case 1:
		return "（" + xs[0] + " を 空 に 挿入する）"
	}
	return "（" + strings.Join(xs, " と ") + "）"
}

// typeForm は型を 型式 の値のソースにする
func typeForm(t Node) string {
	switch x := t.(type) {
	case *TypeVarName:
		return "（型式名 は " + descStr(x.Name) + " で 型式引数 は 空 の 名型）"
	case *TypeName:
		var as []string
		for _, a := range x.Args {
			as = append(as, typeForm(a))
		}
		return "（型式名 は " + descStr(x.Name) + " で 型式引数 は " + descList(as) + " の 名型）"
	}
	return "（型式文 は " + descStr(typeText(t)) + " の 他型）"
}

// typeText は型の書き方(lib/導出.suru の 型式文にする と同じ)
func typeText(t Node) string {
	switch x := t.(type) {
	case *TypeVarName:
		return x.Name
	case *TypeName:
		if len(x.Args) == 0 {
			return x.Name
		}
		if len(x.Args) == 1 {
			inner := typeText(x.Args[0])
			if a, ok := x.Args[0].(*TypeName); ok && len(a.Args) > 0 {
				inner = "（" + inner + "）"
			}
			return inner + " の " + x.Name
		}
		var as []string
		for _, a := range x.Args {
			as = append(as, typeText(a))
		}
		return "（" + strings.Join(as, " と ") + "） の " + x.Name
	case *TypeFun:
		var ps []string
		for _, p := range x.Params {
			ps = append(ps, typeText(p.Type)+" "+p.Part)
		}
		return "（" + strings.Join(ps, " ") + " 受け取って " + typeText(x.Result) + " を 返すこと）"
	}
	return ""
}

func typeVarsOf(t Node, out *[]string) {
	switch x := t.(type) {
	case *TypeVarName:
		for _, v := range *out {
			if v == x.Name {
				return
			}
		}
		*out = append(*out, x.Name)
	case *TypeName:
		for _, a := range x.Args {
			typeVarsOf(a, out)
		}
	case *TypeFun:
		for _, p := range x.Params {
			typeVarsOf(p.Type, out)
		}
		typeVarsOf(x.Result, out)
	}
}

// reindent は展開した行の字下げを base からにする(字下げの差はそのまま)
func reindent(nodes []*LNode, base int) []*LNode {
	if len(nodes) == 0 {
		return nodes
	}
	shift := base - nodes[0].Line.Indent
	var walk func(ns []*LNode)
	walk = func(ns []*LNode) {
		for _, m := range ns {
			m.Line.Indent += shift
			walk(m.Children)
		}
	}
	walk(nodes)
	return nodes
}

// ExpandSource は「suruc --展開」: 準クォートを展開したソース
func ExpandSource(source, baseDir, path string) (out string, err *SuruError) {
	ctx := NewParseContext(baseDir)
	ctx.Path = filePath(path)
	QuasiRecord = &struct {
		Ctx   *ParseContext
		Items []QuasiExpansion
	}{Ctx: ctx}
	defer func() { QuasiRecord = nil }()
	if err = tagged("構文", func() { ParseProgram(source, ctx) }); err != nil {
		return
	}
	items := append([]QuasiExpansion{}, QuasiRecord.Items...)
	sort.Slice(items, func(i, j int) bool { return items[i].Start < items[j].Start })
	raws := SplitLines(source)
	var lines []string
	k := 0
	for _, it := range items {
		lines = append(lines, raws[k:it.Start-1]...)
		srcLines := strings.Split(strings.ReplaceAll(it.Src, "\r\n", "\n"), "\n")
		if len(srcLines) > 0 && srcLines[len(srcLines)-1] == "" {
			srcLines = srcLines[:len(srcLines)-1]
		}
		if it.ExprIndent < 0 {
			lines = append(lines, srcLines...)
		} else {
			head := raws[it.Start-1]
			if i := strings.Index(head, "とは"); i >= 0 {
				head = head[:i+len("とは")]
			}
			lines = append(lines, head)
			pad := strings.Repeat(" ", it.ExprIndent+2)
			for _, x := range srcLines {
				if strings.TrimSpace(x) != "" {
					x = pad + x
				}
				lines = append(lines, x)
			}
		}
		k = it.End
	}
	lines = append(lines, raws[k:]...)
	return strings.Join(lines, "\n") + "\n", nil
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
	lib := embeddedLibPrefix + filepath.Clean(file)
	if LibDir != "" {
		lib = absPath(filepath.Join(LibDir, file))
	}
	if ctx.Path != "" && path == ctx.Path {
		// 「試験/会話帳.suru」の「「会話帳」 を 読み込む」: 自分自身は飛ばして、依存・プロジェクトのフォルダ・標準の lib を探す
		if p, ok := packagePath(name, ctx, line); ok {
			markLibrary(p, ctx, true)
			return loadPath(p, file, ctx, line, false)
		}
		if p, ok := projectFile(file, ctx.BaseDir); ok {
			markLibrary(p, ctx, false)
			return loadPath(p, file, ctx, line, false)
		}
		if exists(lib) {
			markLibrary(lib, ctx, true)
			return loadPath(lib, file, ctx, line, false)
		}
		raise(line, "「"+file+"」を読み込むと、自分自身を読み込むことになります(同じ名前の別のファイルなら、置き場所かファイルの名前を変えてください)")
	}
	searched := !exists(path)
	if searched {
		if p, ok := packagePath(name, ctx, line); ok {
			path = p
		} else {
			path = lib
		}
	}
	markLibrary(path, ctx, searched)
	return loadPath(path, file, ctx, line, false)
}

// libraryFiles はライブラリのファイル(同梱の lib/ と依存のもの、そこから読み込んだもの)の道。それ以外は自分のプログラム(#154)
var libraryFiles sync.Map

// markLibrary は同梱の lib/ のファイル、依存(自分のプロジェクトの外)から見つけたファイル、ライブラリから読み込んだファイルを
// ライブラリとする。自分のプロジェクトのファイルは、組.suru の名前で読み込んでも自分のプログラム
func markLibrary(path string, ctx *ParseContext, searched bool) {
	if isLibPath(path) || IsLibraryFile(ctx.Path) || (searched && !inOwnProject(path, ctx.BaseDir)) {
		libraryFiles.Store(path, true)
	}
}

// inOwnProject は path が dir を含むプロジェクト(組.suru のあるフォルダ)の中か
func inOwnProject(path, dir string) bool {
	if dir == "" || strings.HasPrefix(dir, embeddedLibPrefix) {
		return false
	}
	d := absPath(dir)
	for !exists(filepath.Join(d, ProjectConfig)) {
		parent := filepath.Dir(d)
		if parent == d {
			return false
		}
		d = parent
	}
	return strings.HasPrefix(absPath(path), d+string(filepath.Separator))
}

// IsLibraryFile は道がライブラリのファイルか
func IsLibraryFile(path string) bool {
	_, ok := libraryFiles.Load(path)
	return ok
}

// InLibrary はライブラリのファイルの中の位置か
func InLibrary(p Pos) bool { return p.File != "" && IsLibraryFile(p.File) }

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
	if ctx.Order != nil {
		*ctx.Order = append(*ctx.Order, path)
	}
	sub := &ParseContext{Ctors: ctx.Ctors.Copy(), Types: ctx.Types.Copy(), BaseDir: pathDir(path), Path: path, Modules: ctx.Modules, Loading: ctx.Loading, Packages: ctx.Packages, InPrelude: prelude, Order: ctx.Order, FieldTypes: copyFieldTypes(ctx.FieldTypes)}
	if !isLibPath(path) {
		sub.Qualify = stem + ModuleSep
	}
	var program []Node
	savedFile := curPosFile
	curPosFile = path
	err := try(func() {
		program = DropTests(ParseProgram(source, sub)) // 読み込んだファイルの試験と例は使わない(#193)
		for _, s := range program {
			if _, ok := s.(*Define); !ok && !isTopLevelOnly(s) {
				raise(firstLineOf(s), "読み込むファイルには定義だけを書いてください")
			}
		}
	})
	curPosFile = savedFile
	if err != nil {
		panic(moduleError(err, stem, path, line))
	}
	ctx.Ctors.Update(sub.Ctors)
	ctx.Types.Update(sub.Types)
	if len(sub.FieldTypes) > 0 {
		if ctx.FieldTypes == nil {
			ctx.FieldTypes = map[string][]FieldTypeDecl{}
		}
		for k, v := range sub.FieldTypes {
			ctx.FieldTypes[k] = v
		}
	}
	m := &Module{stem, path, program, privateNames(program), source, sub.Packages}
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

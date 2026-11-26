// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

// --- 構文木(suru.py の「構文木」と同じ) ---

// Node は構文木の節。Children はフィールドの順(Python の dataclass の順)の子
type Node interface {
	Children() []Node
}

// Lined は line を持つ節
type Lined interface {
	GetLine() Pos
}

// Param は引数(助詞と名前。List なら「a と b」で、Names に並べる)。Pat は場合ごとの定義のパターン
type Param struct {
	Part  string
	Name  string
	Names []string
	List  bool
	Pat   Node
}

func (p Param) simple() bool { return p.Pat == nil }

// Arg は呼び出しの引数(Python の dict の順を保つ)
type Arg struct {
	Part  string
	Value Node
}

type Args []Arg

func (a Args) Get(p string) (Node, bool) {
	for _, x := range a {
		if x.Part == p {
			return x.Value, true
		}
	}
	return nil, false
}

func (a Args) Has(p string) bool { _, ok := a.Get(p); return ok }

// hasEach は引数に「xs の それぞれ」があるか
func (a Args) hasEach() bool {
	for _, x := range a {
		if _, ok := x.Value.(*Each); ok {
			return true
		}
	}
	return false
}

func (a Args) Parts() []string {
	out := make([]string, len(a))
	for i, x := range a {
		out[i] = x.Part
	}
	return out
}

func argNodes(a Args) []Node {
	out := make([]Node, 0, len(a))
	for _, x := range a {
		out = append(out, x.Value)
	}
	return out
}

func paramNodes(ps []Param) []Node {
	var out []Node
	for _, p := range ps {
		if p.Pat != nil {
			out = append(out, p.Pat)
		}
	}
	return out
}

type Num struct {
	Value NumVal
	Line  Pos
}
type Str struct {
	Value string
	Line  Pos
}
type Var struct {
	Name   string
	Line   Pos
	Quoted bool
}
type ListLit struct{ Items []Node }
type Prop struct {
	Target Node
	Name   string
	Line   Pos
}
type Each struct {
	Target Node
	Line   Pos
}
type BinOp struct {
	Op          string
	Left, Right Node
	Line        Pos
}
type Neg struct{ Operand Node }
type Not struct {
	Operand Node
	Line    Pos
}
type Call struct {
	Name string
	Args Args
	Line Pos
}
type Ref struct {
	Name string
	Args Args
	Line Pos
}
type Lambda struct {
	Params []Param
	Body   Node
	Line   Pos
}
type If struct{ Cond, Then, Other Node }
type Define struct {
	Name       string
	Params     []Param
	Body       Node
	IsFunction bool
	Line       Pos
	// Test は試験のまとまりか例なら試験の名前(「二倍」「二倍するの例」)。名前で呼べず、通常のビルドでは捨てる(#193)
	Test string
	// Example は例なら [実際の式, 期待の式]
	Example []Node
}
type Block struct{ Statements []Node }
type Sig struct {
	Name   string
	Params []Param
}
type Proviso struct {
	Define *Define
	Line   Pos
	Sig    *Sig
}
type Chain struct {
	Call Node
	Cont Node
	Line Pos
}
type Run struct {
	Call Node
	Line Pos
	// Unwrap なら「…した 中身」: 成功(有)なら中の値、失敗(無)なら一番内側の関数か手順がその失敗を返す
	Unwrap bool
	// Fn は「した 中身」を書いた関数の名前(失敗の経路に使う)
	Fn string
}
type Do struct {
	Statements []Node
	Line       Pos
	Sequel     bool
	IO         bool // 「入出力手順」: 値は動作でなければならない
}
type Sequel struct {
	Expr Node
	Line Pos
}
type Ctor struct {
	Name   string
	Fields []string
}
type TypeDef struct {
	Name  string
	Ctors []Ctor
	Line  Pos
}
type Construct struct {
	Ctor  string
	Items []Node
	Line  Pos
}
type FieldVal struct {
	Name  string
	Value Node
}
type NamedConstruct struct {
	Ctor   string
	Fields []FieldVal
	Line   Pos
}
type Update struct {
	Target Node
	Fields []FieldVal
	Line   Pos
}
type Field struct {
	Target Node
	Name   string
	Line   Pos
}
type PBind struct{ Name string }
type PSeq struct{ Items []Node }
type PValue struct{ Expr Node }
type PCtor struct {
	Ctor  string
	Items []Node
	Line  Pos
}
type PNamed struct {
	Fields  []FieldVal
	Ctor    string
	HasCtor bool
	Line    Pos
}
type Case struct {
	Pat   Node
	Guard Node
	Body  Node
}
type Match struct {
	Subject Node
	Cases   []Case
	Default Node
	Line    Pos
	Fname   string
}
type TraitDecl struct {
	Name     string
	Sigs     []Sig
	Defaults []*Define
	Line     Pos
}
type TraitImpl struct {
	TypeName string
	Trait    string
	Defs     []*Define
	Line     Pos
}
type TypeParam struct {
	Part string
	Type Node
}
type TypeSig struct {
	Name      string
	Params    []TypeParam
	HasParams bool
	Result    Node
	Line      Pos
}
type TypeName struct {
	Name string
	Args []Node
}
type TypeFun struct {
	Params []TypeParam
	Result Node
}
type TypeVarName struct{ Name string }
type Module struct {
	Name    string
	Path    string
	Program []Node
	Private map[string]bool // 「… は 非公開とする」で外から見えない名前
	Source  string          // ファイルの中身(コンパイルした実行ファイルのエラーの表示に使う)
}

// Visibility は「確保する と 解放する は 非公開とする」: 読み込んだ側から見えるか
type Visibility struct {
	Names  []string
	Public bool
	Line   Pos
}
type Import struct {
	Module *Module
	Line   Pos
	Open   bool
	// Test は試験のまとまりのために自動で読み込んだ「試験」(通常のビルドでは捨てる)
	Test bool
}

// ExternLib は「外部の「m」 を 読み込む」
type ExternLib struct {
	Name string // 書いたとおり
	Path string // 短い名前か、ファイルなら絶対パス
	Line Pos
	// MainThread は「外部の「m」 を 主スレッドで 読み込む」
	MainThread bool
}

// Extern は「x を 余弦にする とは 外部の「cos」」の本体
type Extern struct {
	Symbol     string
	Line       Pos
	Libs       []string
	Params     []string // 定義の引数の順に C の型(i64 f64 i32 bool str ptr)
	Result     string
	Action     bool
	MainThread bool   // 主スレッドで呼ぶ(同じファイルに「… を 主スレッドで 読み込む」がある)
	Pointer    string // 「外部の（f）」なら、関数の番地を持つ引数の名前(C には渡さない)
	// 「外部の「f」（a と 0 と b）」なら、C に渡す引数の並び(なければ定義の引数の順)
	CArgs []ExternArg
}

// ExternArg は C に渡す引数の1つ: 定義の引数(Name、attachExterns が Param に番号を入れる)か、整数の定数(int64_t)
type ExternArg struct {
	Name    string
	Param   int
	IsConst bool
	Const   int64
	Line    Pos
}

func nn(xs ...Node) []Node {
	out := make([]Node, 0, len(xs))
	for _, x := range xs {
		if x != nil && !isNilNode(x) {
			out = append(out, x)
		}
	}
	return out
}

func isNilNode(x Node) bool {
	switch v := x.(type) {
	case *Define:
		return v == nil
	case *Module:
		return v == nil
	}
	return false
}

func fieldNodes(fs []FieldVal) []Node {
	out := make([]Node, 0, len(fs))
	for _, f := range fs {
		out = append(out, f.Value)
	}
	return out
}

func defNodes(ds []*Define) []Node {
	out := make([]Node, 0, len(ds))
	for _, d := range ds {
		out = append(out, d)
	}
	return out
}

func typeParamNodes(ps []TypeParam) []Node {
	out := make([]Node, 0, len(ps))
	for _, p := range ps {
		out = append(out, p.Type)
	}
	return out
}

func (n *Num) Children() []Node     { return nil }
func (n *Str) Children() []Node     { return nil }
func (n *Var) Children() []Node     { return nil }
func (n *ListLit) Children() []Node { return n.Items }
func (n *Prop) Children() []Node    { return nn(n.Target) }
func (n *Each) Children() []Node    { return nn(n.Target) }
func (n *BinOp) Children() []Node   { return nn(n.Left, n.Right) }
func (n *Neg) Children() []Node     { return nn(n.Operand) }
func (n *Not) Children() []Node     { return nn(n.Operand) }
func (n *Call) Children() []Node    { return argNodes(n.Args) }
func (n *Ref) Children() []Node     { return argNodes(n.Args) }
func (n *Lambda) Children() []Node  { return append(paramNodes(n.Params), nn(n.Body)...) }
func (n *If) Children() []Node      { return nn(n.Cond, n.Then, n.Other) }
func (n *Define) Children() []Node  { return append(paramNodes(n.Params), nn(n.Body)...) }
func (n *Block) Children() []Node   { return n.Statements }
func (n *Proviso) Children() []Node {
	if n.Define != nil {
		return []Node{n.Define}
	}
	return nil
}
func (n *Chain) Children() []Node     { return nn(n.Call, n.Cont) }
func (n *Run) Children() []Node       { return nn(n.Call) }
func (n *Do) Children() []Node        { return n.Statements }
func (n *Sequel) Children() []Node    { return nn(n.Expr) }
func (n *TypeDef) Children() []Node   { return nil }
func (n *Construct) Children() []Node { return n.Items }
func (n *NamedConstruct) Children() []Node {
	return fieldNodes(n.Fields)
}
func (n *Update) Children() []Node { return append(nn(n.Target), fieldNodes(n.Fields)...) }
func (n *Field) Children() []Node  { return nn(n.Target) }
func (n *PBind) Children() []Node  { return nil }
func (n *PSeq) Children() []Node   { return n.Items }
func (n *PValue) Children() []Node { return nn(n.Expr) }
func (n *PCtor) Children() []Node  { return n.Items }
func (n *PNamed) Children() []Node { return fieldNodes(n.Fields) }
func (n *Match) Children() []Node {
	out := nn(n.Subject)
	for _, c := range n.Cases {
		out = append(out, nn(c.Pat, c.Guard, c.Body)...)
	}
	return append(out, nn(n.Default)...)
}
func (n *TraitDecl) Children() []Node {
	var out []Node
	for _, s := range n.Sigs {
		out = append(out, paramNodes(s.Params)...)
	}
	return append(out, defNodes(n.Defaults)...)
}
func (n *TraitImpl) Children() []Node   { return defNodes(n.Defs) }
func (n *TypeSig) Children() []Node     { return append(typeParamNodes(n.Params), nn(n.Result)...) }
func (n *TypeName) Children() []Node    { return n.Args }
func (n *TypeFun) Children() []Node     { return append(typeParamNodes(n.Params), nn(n.Result)...) }
func (n *TypeVarName) Children() []Node { return nil }
func (n *Module) Children() []Node      { return n.Program }
func (n *Import) Children() []Node      { return nn(n.Module) }
func (n *ExternLib) Children() []Node   { return nil }
func (n *Visibility) Children() []Node  { return nil }
func (n *Extern) Children() []Node      { return nil }

func (n *Num) GetLine() Pos            { return n.Line }
func (n *Str) GetLine() Pos            { return n.Line }
func (n *Var) GetLine() Pos            { return n.Line }
func (n *Prop) GetLine() Pos           { return n.Line }
func (n *Each) GetLine() Pos           { return n.Line }
func (n *BinOp) GetLine() Pos          { return n.Line }
func (n *Not) GetLine() Pos            { return n.Line }
func (n *Call) GetLine() Pos           { return n.Line }
func (n *Ref) GetLine() Pos            { return n.Line }
func (n *Lambda) GetLine() Pos         { return n.Line }
func (n *Define) GetLine() Pos         { return n.Line }
func (n *Proviso) GetLine() Pos        { return n.Line }
func (n *Chain) GetLine() Pos          { return n.Line }
func (n *Run) GetLine() Pos            { return n.Line }
func (n *Do) GetLine() Pos             { return n.Line }
func (n *Sequel) GetLine() Pos         { return n.Line }
func (n *TypeDef) GetLine() Pos        { return n.Line }
func (n *Construct) GetLine() Pos      { return n.Line }
func (n *NamedConstruct) GetLine() Pos { return n.Line }
func (n *Update) GetLine() Pos         { return n.Line }
func (n *Field) GetLine() Pos          { return n.Line }
func (n *PCtor) GetLine() Pos          { return n.Line }
func (n *PNamed) GetLine() Pos         { return n.Line }
func (n *Match) GetLine() Pos          { return n.Line }
func (n *TraitDecl) GetLine() Pos      { return n.Line }
func (n *TraitImpl) GetLine() Pos      { return n.Line }
func (n *TypeSig) GetLine() Pos        { return n.Line }
func (n *Import) GetLine() Pos         { return n.Line }
func (n *ExternLib) GetLine() Pos      { return n.Line }
func (n *Visibility) GetLine() Pos     { return n.Line }
func (n *Extern) GetLine() Pos         { return n.Line }

// lineOf は Python の getattr(node, "line", 0)
func lineOf(n Node) Pos {
	if l, ok := n.(Lined); ok {
		return l.GetLine()
	}
	return Pos{}
}

// firstLine は式の中で最初に見つかる行番号
func firstLine(n Node) Pos {
	if n == nil {
		return Pos{}
	}
	if l := lineOf(n); l.Line != 0 {
		return l
	}
	for _, c := range n.Children() {
		if l := firstLine(c); l.Line != 0 {
			return l
		}
	}
	return Pos{}
}

func isTopLevelOnly(n Node) bool {
	switch n.(type) {
	case *TypeDef, *TraitDecl, *TraitImpl, *TypeSig, *Import, *ExternLib, *Visibility:
		return true
	}
	return false
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"fmt"
	"strings"
)

// --- 型(suru_check.py の「型」と同じ) ---

type Type interface{ isType() }

// TVar はまだ決まっていない型。Pure なら「x を 結果にする」の型(C は結果の型)
type TVar struct {
	gen  bool // 型スキームで多相にした型変数
	id   int
	ref  Type
	Pure bool
	C    Type
}

type TCon struct {
	Name string
	Args []Type
}

type TParam struct {
	Part string
	T    Type
}

// TFun: 関数。Real は助詞が本物(定義・無名関数・部分適用・型の宣言のもの。組み込みの型の「を」の仮置きではない)。
// Strict は受け取った関数を助詞を付けて呼ぶところがある(助詞もそろえる。#104)。suru_check.py の TFun と同じ
type TFun struct {
	Params []TParam
	Result Type
	Real   bool
	Strict bool
}

func (*TVar) isType() {}
func (*TCon) isType() {}
func (*TFun) isType() {}

// 型変数の番号(Python の itertools.count と同じく通し番号)
type typeState struct {
	nextID   int
	genEpoch int               // 多相にした型変数が後から決まった回数(環境の自由な型変数の覚えを捨てる印)
	usual    map[string][]Type // 型名 → フィールドごとのいつもの型(nil は決まっていない)
	deferred []pureDeferred
}

type pureDeferred struct {
	c Type
	t *TCon
}

var ts = &typeState{usual: map[string][]Type{}}

func newTVar() *TVar {
	ts.nextID++
	return &TVar{id: ts.nextID}
}

func newPureVar(c Type) *TVar {
	v := newTVar()
	v.Pure = true
	v.C = c
	return v
}

var (
	NUM  = &TCon{Name: "数"}
	STR  = &TCon{Name: "文字列"}
	BOOL = &TCon{Name: "真偽"}
)

func lst(t Type) *TCon { return &TCon{"リスト", []Type{t}} }
func act(t Type) *TCon { return &TCon{"動作", []Type{t}} }

// threadT は lib/スレッド.suru の型「甲 の スレッド」
func threadT(t Type) *TCon { return &TCon{"スレッド", []Type{t}} }

// chanT は lib/スレッド.suru の型「甲 の 通路」
func chanT(t Type) *TCon { return &TCon{"通路", []Type{t}} }

func prune(t Type) Type {
	for {
		v, ok := t.(*TVar)
		if !ok || v.ref == nil {
			return t
		}
		t = v.ref
	}
}

// varSet は順番を保つ型変数の集合
type varSet struct {
	m     map[*TVar]bool
	order []*TVar
}

func newVarSet() *varSet { return &varSet{m: map[*TVar]bool{}} }

func (s *varSet) add(v *TVar) {
	if !s.m[v] {
		s.m[v] = true
		s.order = append(s.order, v)
	}
}
func (s *varSet) has(v *TVar) bool { return s.m[v] }
func (s *varSet) len() int         { return len(s.order) }

func ftv(t Type, out *varSet) *varSet {
	if out == nil {
		out = newVarSet()
	}
	t = prune(t)
	switch x := t.(type) {
	case *TVar:
		if out.m[x] {
			return out
		}
		out.add(x)
		if x.Pure {
			ftv(x.C, out)
		}
	case *TCon:
		for _, a := range x.Args {
			ftv(a, out)
		}
	case *TFun:
		for _, p := range x.Params {
			ftv(p.T, out)
		}
		ftv(x.Result, out)
	}
	return out
}

// 型がそろわないとき(Occurs は v を t にすると型が無限に続くとき)
type mismatch struct {
	occurs   bool
	particle bool // 助詞を付けて呼ぶ関数の、助詞が違う
	v        *TVar
	t        Type
}

type restart struct{}

func throwMismatch() { panic(&mismatch{}) }

func occursIn(v *TVar, t Type) bool { return occurs(v, prune(t)) }

func occurs(v *TVar, t Type) bool {
	t = prune(t)
	switch x := t.(type) {
	case *TVar:
		if x == v {
			return true
		}
		if x.Pure && x.C != nil {
			return occurs(v, x.C)
		}
	case *TCon:
		for _, a := range x.Args {
			if occurs(v, a) {
				return true
			}
		}
	case *TFun:
		for _, p := range x.Params {
			if occurs(v, p.T) {
				return true
			}
		}
		return occurs(v, x.Result)
	}
	return false
}

var basicTypes = setOf("数", "文字列", "真偽", "番地", "バイト列")

// numAliases は外部の関数の宣言で使う数の別名
var numAliases = setOf("小数", "整数", "無", "単精度")
var monadTypes = setOf("動作", "リスト")

func bindVar(v *TVar, t Type) {
	if occursIn(v, t) {
		panic(&mismatch{occurs: true, v: v, t: t})
	}
	if v.gen {
		ts.genEpoch++
	}
	v.ref = t
}

func unify(a, b Type) {
	a, b = prune(a), prune(b)
	if a == b {
		return
	}
	if bv, ok := b.(*TVar); ok && bv.Pure {
		if av, ok := a.(*TVar); !ok || !av.Pure {
			a, b = b, a
		}
	}
	if av, ok := a.(*TVar); ok && av.Pure {
		switch bb := b.(type) {
		case *TVar:
			if bb.Pure {
				unify(av.C, bb.C)
			} else {
				bindVar(bb, av)
				return
			}
		case *TCon:
			if monadTypes[bb.Name] {
				unify(av.C, bb.Args[0])
			} else if !basicTypes[bb.Name] {
				ts.deferred = append(ts.deferred, pureDeferred{av.C, bb})
			} else {
				throwMismatch()
			}
		default:
			throwMismatch()
		}
		bindVar(av, b)
		return
	}
	if av, ok := a.(*TVar); ok {
		bindVar(av, b)
		return
	}
	if _, ok := b.(*TVar); ok {
		unify(b, a)
		return
	}
	if ac, ok := a.(*TCon); ok {
		if bc, ok := b.(*TCon); ok {
			if ac.Name != bc.Name || len(ac.Args) != len(bc.Args) {
				throwMismatch()
			}
			for i := range ac.Args {
				unify(ac.Args[i], bc.Args[i])
			}
			return
		}
	}
	if af, ok := a.(*TFun); ok {
		if bf, ok := b.(*TFun); ok {
			if len(af.Params) != len(bf.Params) {
				throwMismatch()
			}
			if (af.Strict || bf.Strict) && af.Real && bf.Real {
				// 助詞を付けて呼ばれる関数は、助詞もそろえる(助詞ごとに合わせる)
				bp := map[string]Type{}
				for _, p := range bf.Params {
					bp[p.Part] = p.T
				}
				for _, p := range af.Params {
					if _, ok := bp[p.Part]; !ok {
						panic(&mismatch{particle: true})
					}
				}
				if len(bp) != len(af.Params) {
					panic(&mismatch{particle: true})
				}
				af.Strict, bf.Strict = true, true
				for _, p := range af.Params {
					unify(p.T, bp[p.Part])
				}
			} else {
				for i := range af.Params {
					unify(af.Params[i].T, bf.Params[i].T)
				}
			}
			unify(af.Result, bf.Result)
			return
		}
	}
	throwMismatch()
}

// --- 表示 ---

const varNames = "甲乙丙丁戊己庚辛壬癸"

type namer struct {
	names  map[*TVar]string
	count  int
	lonely map[*TVar]bool
}

func newNamer(tys ...Type) *namer {
	counts := map[*TVar]int{}
	for _, t := range tys {
		countVars(t, counts)
	}
	lonely := map[*TVar]bool{}
	for v, n := range counts {
		if n == 1 {
			lonely[v] = true
		}
	}
	return &namer{names: map[*TVar]string{}, lonely: lonely}
}

func countVars(t Type, counts map[*TVar]int) {
	t = prune(t)
	switch x := t.(type) {
	case *TVar:
		counts[x]++
		if x.Pure {
			countVars(x.C, counts)
		}
	case *TCon:
		for _, a := range x.Args {
			countVars(a, counts)
		}
	case *TFun:
		for _, p := range x.Params {
			countVars(p.T, counts)
		}
		countVars(x.Result, counts)
	}
}

func (n *namer) ordinary(t *TCon) bool {
	usual := ts.usual[t.Name]
	if len(usual) == 0 {
		usual = make([]Type, len(t.Args))
	}
	if len(usual) != len(t.Args) {
		return false
	}
	for i, a := range t.Args {
		ra := prune(a)
		if v, ok := ra.(*TVar); ok && n.lonely[v] {
			continue
		}
		if usual[i] != nil && teq(a, usual[i]) {
			continue
		}
		return false
	}
	return true
}

var vnames = []rune(varNames)

func (n *namer) show(t Type, nested bool) string {
	t = prune(t)
	switch x := t.(type) {
	case *TVar:
		if x.Pure {
			s := n.show(x.C, true) + " を 結果にしたもの"
			if nested {
				return "（" + s + "）"
			}
			return s
		}
		if name, ok := n.names[x]; ok {
			return name
		}
		k := len(n.names)
		var name string
		if k < len(vnames) {
			name = string(vnames[k])
		} else {
			name = fmt.Sprintf("型%d", k+1)
		}
		n.names[x] = name
		return name
	case *TCon:
		if x.Name == TupleType {
			parts := make([]string, len(x.Args))
			for k, a := range x.Args {
				parts[k] = n.show(a, true)
			}
			return "（" + strings.Join(parts, " と ") + "）"
		}
		if len(x.Args) == 0 || (!monadTypes[x.Name] && n.ordinary(x)) {
			return x.Name
		}
		parts := make([]string, len(x.Args))
		for i, a := range x.Args {
			parts[i] = n.show(a, true)
		}
		inner := strings.Join(parts, " と ")
		var s string
		if len(x.Args) == 1 {
			s = inner + " の " + x.Name
		} else {
			s = "（" + inner + "） の " + x.Name
		}
		if nested {
			return "（" + s + "）"
		}
		return s
	case *TFun:
		if len(x.Params) == 0 {
			return "（" + n.show(x.Result, true) + " を 返すこと）"
		}
		ps := make([]string, len(x.Params))
		for i, p := range x.Params {
			ps[i] = n.show(p.T, true) + " " + p.Part
		}
		return "（" + strings.Join(ps, " ") + " 受け取って " + n.show(x.Result, true) + " を 返すこと）"
	}
	return "?"
}

func show(tys ...Type) []string {
	n := newNamer(tys...)
	out := make([]string, len(tys))
	for i, t := range tys {
		out[i] = n.show(t, false)
	}
	return out
}

func show1(t Type) string { return show(t)[0] }

// --- 型の条件と型スキーム ---

type Constraint struct {
	T       Type
	Line    Pos
	Kinds   []string
	Message string
	Trait   string
	Method  string
	FType   *TFun
	Op      string
	Extra   []Type
}

func (c *Constraint) subst(m map[*TVar]Type) *Constraint {
	n := *c
	n.T = substT(c.T, m)
	if c.FType != nil {
		n.FType = substT(c.FType, m).(*TFun)
	}
	n.Extra = make([]Type, len(c.Extra))
	for i, x := range c.Extra {
		n.Extra[i] = substT(x, m)
	}
	return &n
}

func (c *Constraint) typeVars() *varSet {
	out := ftv(c.T, nil)
	if c.FType != nil {
		ftv(c.FType, out)
	}
	for _, x := range c.Extra {
		ftv(x, out)
	}
	return out
}

type Scheme struct {
	Vars        []*TVar
	T           Type
	Constraints []*Constraint
}

func (s *Scheme) instantiate(pending *[]*Constraint) Type {
	mapping := map[*TVar]Type{}
	for _, v := range s.Vars {
		if v.Pure {
			mapping[v] = newPureVar(nil)
		} else {
			mapping[v] = newTVar()
		}
	}
	for _, v := range s.Vars {
		if v.Pure {
			mapping[v].(*TVar).C = substT(v.C, mapping)
		}
	}
	if pending != nil {
		for _, c := range s.Constraints {
			*pending = append(*pending, c.subst(mapping))
		}
	}
	return substT(s.T, mapping)
}

func substT(t Type, m map[*TVar]Type) Type {
	t = prune(t)
	switch x := t.(type) {
	case *TVar:
		if r, ok := m[x]; ok {
			return r
		}
		if x.Pure {
			fv := ftv(x.C, nil)
			for _, v := range fv.order {
				if _, ok := m[v]; ok {
					return newPureVar(substT(x.C, m))
				}
			}
		}
		return x
	case *TCon:
		if len(x.Args) == 0 {
			return x
		}
		args := make([]Type, len(x.Args))
		for i, a := range x.Args {
			args[i] = substT(a, m)
		}
		return &TCon{x.Name, args}
	case *TFun:
		ps := make([]TParam, len(x.Params))
		for i, p := range x.Params {
			ps[i] = TParam{p.Part, substT(p.T, m)}
		}
		return &TFun{Params: ps, Result: substT(x.Result, m), Real: x.Real, Strict: x.Strict}
	}
	return t
}

// PrimRef は標準ライブラリの組み込み(「標準内の逆順にする」)
type PrimRef struct{ Name string }

type TEnv struct {
	vars   map[string]any // 型 / *Scheme / *PrimRef
	parent *TEnv
	// hidden は読み込んだファイルの「非公開とする」名前 → そのファイルの名前(見えないが、
	// 呼べば型の検査で「定義されていません」にする)
	hidden map[string]string
	// 自由な型変数を求めるための覚え: 各名前の型の自由な型変数(入れたとき)。
	// 型変数は後で決まっても、その中の自由な型変数を見ればよいので、覚えは作り直さなくてよい
	cand      []*TVar
	candOK    bool
	candEpoch int
}

// hiddenIn は name が読み込んだファイルの非公開の名前なら、そのファイルの名前
func (e *TEnv) hiddenIn(name string) (string, bool) {
	for ; e != nil; e = e.parent {
		if m, ok := e.hidden[name]; ok {
			return m, true
		}
	}
	return "", false
}

func (e *TEnv) set(name string, v any) {
	if _, ok := e.vars[name]; ok {
		e.candOK = false
	} else if e.candOK {
		e.cand = appendFree(e.cand, v)
	}
	e.vars[name] = v
}

func appendFree(out []*TVar, v any) []*TVar {
	switch s := v.(type) {
	case *Scheme:
		bound := map[*TVar]bool{}
		for _, b := range s.Vars {
			bound[b] = true
		}
		for _, w := range ftv(s.T, nil).order {
			if !bound[w] {
				out = append(out, w)
			}
		}
	case Type:
		out = append(out, ftv(s, nil).order...)
	}
	return out
}

// freeVars は環境の中の(多相でない)型変数(suru_check.py の TEnv.free_vars と同じ結果)
func (e *TEnv) freeVars() *varSet {
	out := newVarSet()
	for x := e; x != nil; x = x.parent {
		if !x.candOK || x.candEpoch != ts.genEpoch {
			x.cand = nil
			for _, v := range x.vars {
				x.cand = appendFree(x.cand, v)
			}
			x.candOK = true
			x.candEpoch = ts.genEpoch
		}
		for _, u := range x.cand {
			ftv(u, out)
		}
	}
	return out
}

func newTEnv(parent *TEnv) *TEnv { return &TEnv{vars: map[string]any{}, parent: parent} }

func (e *TEnv) lookup(name string) any {
	for x := e; x != nil; x = x.parent {
		if v, ok := x.vars[name]; ok {
			return v
		}
	}
	return nil
}

func teq(a, b Type) bool {
	a, b = prune(a), prune(b)
	if ac, ok := a.(*TCon); ok {
		if bc, ok := b.(*TCon); ok {
			if ac.Name != bc.Name || len(ac.Args) != len(bc.Args) {
				return false
			}
			for i := range ac.Args {
				if !teq(ac.Args[i], bc.Args[i]) {
					return false
				}
			}
			return true
		}
	}
	if af, ok := a.(*TFun); ok {
		if bf, ok := b.(*TFun); ok {
			if len(af.Params) != len(bf.Params) {
				return false
			}
			for i := range af.Params {
				if !teq(af.Params[i].T, bf.Params[i].T) {
					return false
				}
			}
			return teq(af.Result, bf.Result)
		}
	}
	return a == b
}

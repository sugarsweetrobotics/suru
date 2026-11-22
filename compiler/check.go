// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"fmt"
	"sort"
	"strings"
)

// --- 型の検査(suru_check.py と同じ) ---

func implKey(trait, typeName, method string) string {
	return "\x00" + trait + "\x00" + typeName + "\x00" + method
}

func displayName(name string) string {
	i := strings.LastIndex(name, "\x00")
	return name[i+1:]
}

func isAction(t Type) bool {
	r := prune(t)
	if v, ok := r.(*TVar); ok {
		return v.Pure
	}
	c, ok := r.(*TCon)
	return ok && c.Name == "動作"
}

func pruneIsRecord(t Type) bool {
	r := prune(t)
	c, ok := r.(*TCon)
	if !ok {
		return false
	}
	switch c.Name {
	case "数", "文字列", "真偽", "リスト", "動作":
		return false
	}
	return true
}

// --- 依存関係 ---

func referencedNames(node Node, out *orderedSet) {
	if node == nil {
		return
	}
	switch n := node.(type) {
	case *Var:
		out.add(n.Name)
	case *Call:
		out.add(n.Name)
	case *Ref:
		out.add(n.Name)
	}
	switch n := node.(type) {
	case *Do, *Chain, *Run:
		out.add(BindName)
		out.add(UnitName)
	case *Field:
		if n.Name == Result {
			out.add(MapName)
			out.add(BindName)
			out.add(UnitName)
		}
	}
	for _, c := range node.Children() {
		referencedNames(c, out)
	}
}

type orderedSet struct {
	m     map[string]bool
	order []string
}

func newOrderedSet() *orderedSet { return &orderedSet{m: map[string]bool{}} }
func (s *orderedSet) add(x string) {
	if !s.m[x] {
		s.m[x] = true
		s.order = append(s.order, x)
	}
}

func sccs(defs []*Define, aliases map[string][]string) [][]*Define {
	names := map[string]*Define{}
	for _, d := range defs {
		names[d.Name] = d
	}
	graph := map[string][]string{}
	for _, d := range defs {
		rs := newOrderedSet()
		refs := newOrderedSet()
		referencedNames(d.Body, rs)
		for _, n := range rs.order {
			refs.add(n)
			for _, a := range aliases[n] {
				refs.add(a)
			}
		}
		var g []string
		for _, n := range refs.order {
			if _, ok := names[n]; ok {
				g = append(g, n)
			}
		}
		graph[d.Name] = g
	}
	index := map[string]int{}
	low := map[string]int{}
	var stack []string
	on := map[string]bool{}
	var out [][]*Define
	counter := 0
	var visit func(v string)
	visit = func(v string) {
		index[v] = counter
		low[v] = counter
		counter++
		stack = append(stack, v)
		on[v] = true
		for _, w := range graph[v] {
			if _, ok := index[w]; !ok {
				visit(w)
				if low[w] < low[v] {
					low[v] = low[w]
				}
			} else if on[w] {
				if index[w] < low[v] {
					low[v] = index[w]
				}
			}
		}
		if low[v] == index[v] {
			var comp []*Define
			for {
				w := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				delete(on, w)
				comp = append(comp, names[w])
				if w == v {
					break
				}
			}
			out = append(out, comp)
		}
	}
	for _, d := range defs {
		if _, ok := index[d.Name]; !ok {
			visit(d.Name)
		}
	}
	return out
}

// --- 自分の型の形 ---

type fieldKey struct{ T, F string }

var selfType = &TCon{Name: "\x00自身"}

type Shapes struct {
	keys      map[string][]fieldKey
	keyOrder  []string
	ph        map[fieldKey]*TVar
	phOrder   []fieldKey
	recursive map[fieldKey]Type
}

func newShapes(ctx *ParseContext) *Shapes {
	s := &Shapes{keys: map[string][]fieldKey{}, ph: map[fieldKey]*TVar{}, recursive: map[fieldKey]Type{}}
	for _, c := range ctx.Ctors.Keys() {
		info, _ := ctx.Ctors.Get(c)
		ks, ok := s.keys[info.Type]
		if !ok {
			s.keyOrder = append(s.keyOrder, info.Type)
		}
		for _, f := range info.Fields {
			k := fieldKey{info.Type, f}
			found := false
			for _, x := range ks {
				if x == k {
					found = true
				}
			}
			if !found {
				ks = append(ks, k)
			}
		}
		s.keys[info.Type] = ks
	}
	for _, t := range s.keyOrder {
		for _, k := range s.keys[t] {
			s.ph[k] = newTVar()
			s.phOrder = append(s.phOrder, k)
		}
	}
	return s
}

func (s *Shapes) params(tname string) []fieldKey {
	var out []fieldKey
	for _, k := range s.keys[tname] {
		if _, ok := s.recursive[k]; !ok {
			out = append(out, k)
		}
	}
	return out
}

func (s *Shapes) isUser(t Type) bool {
	c, ok := t.(*TCon)
	if !ok {
		return false
	}
	_, has := s.keys[c.Name]
	return has && len(c.Args) == len(s.params(c.Name))
}

func indexKey(ks []fieldKey, k fieldKey) int {
	for i, x := range ks {
		if x == k {
			return i
		}
	}
	return -1
}

func (s *Shapes) findRecursion(v *TVar, t Type) bool {
	for _, n := range typeNodes(t, nil) {
		if !s.isUser(n) {
			continue
		}
		ps := s.params(n.Name)
		for i, a := range n.Args {
			if !ftv(a, nil).has(v) {
				continue
			}
			mapping := map[*TVar]Type{}
			for j, b := range n.Args {
				rb := prune(b)
				if bv, ok := rb.(*TVar); ok && j != i && bv != v {
					mapping[bv] = s.ph[ps[j]]
				}
			}
			s.recursive[ps[i]] = template(a, n, v, t, mapping)
			return true
		}
	}
	return false
}

func (s *Shapes) learnUsual(instances []*TCon) bool {
	found := false
	for _, tname := range s.keyOrder {
		ps := s.params(tname)
		var mine []*TCon
		for _, x := range instances {
			if x.Name == tname && len(x.Args) == len(ps) {
				mine = append(mine, x)
			}
		}
		usual := make([]Type, len(ps))
		for j := range ps {
			var tys []Type
			for _, x := range mine {
				tys = append(tys, prune(x.Args[j]))
			}
			ok := len(tys) > 0
			for _, x := range tys {
				if ftv(x, nil).len() > 0 {
					ok = false
				}
			}
			if ok {
				for _, x := range tys[1:] {
					if !teq(tys[0], x) {
						ok = false
					}
				}
			}
			if ok {
				usual[j] = substT(tys[0], map[*TVar]Type{})
				found = true
			}
		}
		ts.usual[tname] = usual
	}
	return found
}

func typeNodes(t Type, out []*TCon) []*TCon {
	t = prune(t)
	switch x := t.(type) {
	case *TCon:
		out = append(out, x)
		for _, a := range x.Args {
			out = typeNodes(a, out)
		}
	case *TFun:
		for _, p := range x.Params {
			out = typeNodes(p.T, out)
		}
		out = typeNodes(x.Result, out)
	}
	return out
}

func template(a Type, node *TCon, v *TVar, t Type, mapping map[*TVar]Type) Type {
	fresh := map[*TVar]Type{}
	seen := false
	var build func(x Type) Type
	build = func(x Type) Type {
		x = prune(x)
		if xc, ok := x.(*TCon); ok && xc == node {
			return selfType
		}
		if xv, ok := x.(*TVar); ok && xv == v {
			if seen {
				return newTVar()
			}
			seen = true
			return build(t)
		}
		switch y := x.(type) {
		case *TVar:
			if m, ok := mapping[y]; ok {
				return m
			}
			if f, ok := fresh[y]; ok {
				return f
			}
			f := newTVar()
			fresh[y] = f
			return f
		case *TCon:
			if len(y.Args) == 0 {
				return y
			}
			args := make([]Type, len(y.Args))
			for i, b := range y.Args {
				args[i] = build(b)
			}
			return &TCon{y.Name, args}
		case *TFun:
			ps := make([]TParam, len(y.Params))
			for i, p := range y.Params {
				ps[i] = TParam{p.Part, build(p.T)}
			}
			return &TFun{ps, build(y.Result)}
		}
		return x
	}
	return build(a)
}

func fill(t Type, mapping map[*TVar]Type, self Type) Type {
	if t == Type(selfType) {
		return self
	}
	switch x := t.(type) {
	case *TVar:
		if m, ok := mapping[x]; ok {
			return m
		}
		return x
	case *TCon:
		if len(x.Args) == 0 {
			return x
		}
		args := make([]Type, len(x.Args))
		for i, a := range x.Args {
			args[i] = fill(a, mapping, self)
		}
		return &TCon{x.Name, args}
	case *TFun:
		ps := make([]TParam, len(x.Params))
		for i, p := range x.Params {
			ps[i] = TParam{p.Part, fill(p.T, mapping, self)}
		}
		return &TFun{ps, fill(x.Result, mapping, self)}
	}
	return t
}

// --- 検査 ---

type traitInfo struct {
	methods  []Sig // 名前 → 引数(宣言の順、既定の実装は後)
	defaults map[string]bool
}

func (t *traitInfo) method(name string) ([]Param, bool) {
	for _, s := range t.methods {
		if s.Name == name {
			return s.Params, true
		}
	}
	return nil, false
}

type Checker struct {
	ctx         *ParseContext
	shapes      *Shapes
	instances   []*TCon
	traits      map[string]*traitInfo
	methodTrait map[string]string
	impls       map[[2]string]map[string]bool
	showImpls   map[string]bool
	aliases     map[string][]string
	pending     []*Constraint
	line        Pos
	env         *TEnv
	base        *TEnv
	checked     map[string]*TEnv
	// エディター向け(Analyze): 名前を使ったところと定義したところの型を覚える
	record bool
	file   string // 調べている読み込んだファイル(本体なら "")
	uses   []Use
}

func newChecker(ctx *ParseContext, shapes *Shapes) *Checker {
	ts.deferred = nil
	return &Checker{ctx: ctx, shapes: shapes, traits: map[string]*traitInfo{}, methodTrait: map[string]string{},
		impls: map[[2]string]map[string]bool{}, showImpls: map[string]bool{}, aliases: map[string][]string{},
		env: newTEnv(nil)}
}

func (c *Checker) err(line Pos, msg string) *SuruError {
	if line.Line == 0 {
		line = c.line
	}
	return &SuruError{Message: msg, Line: line}
}

func (c *Checker) fail(line Pos, msg string) { panic(c.err(line, msg)) }

// catchMismatch は f の中の型の不一致を返す(Restart や SuruError はそのまま)
func catchMismatch(f func()) (m *mismatch) {
	defer func() {
		if r := recover(); r != nil {
			if mm, ok := r.(*mismatch); ok {
				m = mm
				return
			}
			panic(r)
		}
	}()
	f()
	return nil
}

func (c *Checker) unify(a, b Type) {
	m := catchMismatch(func() { unify(a, b) })
	if m == nil {
		return
	}
	if m.occurs && c.shapes.findRecursion(m.v, m.t) {
		panic(restart{})
	}
	throwMismatch()
}

func (c *Checker) unifyOr(a, b Type, line Pos, message func(sa, sb string) string) {
	if catchMismatch(func() { c.unify(a, b) }) != nil {
		s := show(a, b)
		c.fail(line, message(s[0], s[1]))
	}
}

func (c *Checker) expect(actual, expected Type, line Pos, what string) {
	c.unifyOr(actual, expected, line, func(sa, sb string) string {
		return what + "には" + sb + "が必要ですが、" + sa + "になっています"
	})
}

// --- プログラム ---

func (c *Checker) checkProgram(program []Node) {
	c.base = newTEnv(nil)
	c.checked = map[string]*TEnv{}
	env := c.checkUnit(program, nil)
	for _, s := range program {
		if _, ok := s.(*Define); ok || isTopLevelOnly(s) {
			continue
		}
		c.line = firstLine(s)
		c.infer(s, env)
		c.solve(env)
	}
	c.solve(env)
}

func (c *Checker) checkUnit(program []Node, prims map[string]any) *TEnv {
	local := newTEnv(c.base)
	for k, v := range prims {
		local.set(k, v)
	}
	for _, s := range program {
		if imp, ok := s.(*Import); ok {
			sc := c.checkModule(imp.Module, imp.Line)
			for name, v := range sc.vars {
				if !strings.HasPrefix(name, "\x00") && !strings.Contains(name, ModuleSep) {
					local.set(imp.Module.Name+ModuleSep+name, v)
					if imp.Open {
						local.set(name, v)
					}
				}
			}
		}
	}
	var defs []*Define
	for _, s := range program {
		if d, ok := s.(*Define); ok {
			defs = append(defs, d)
		}
	}
	for _, s := range program {
		decl, ok := s.(*TraitDecl)
		if !ok {
			continue
		}
		info := &traitInfo{defaults: map[string]bool{}}
		set := func(name string, params []Param) {
			for i := range info.methods {
				if info.methods[i].Name == name {
					info.methods[i].Params = params
					return
				}
			}
			info.methods = append(info.methods, Sig{name, params})
		}
		for _, sg := range decl.Sigs {
			set(sg.Name, sg.Params)
		}
		for _, d := range decl.Defaults {
			set(d.Name, d.Params)
			info.defaults[d.Name] = true
		}
		c.traits[decl.Name] = info
		for _, m := range info.methods {
			c.methodTrait[m.Name] = decl.Name
		}
		for _, d := range decl.Defaults {
			defs = append(defs, renamed(d, implKey(decl.Name, "", d.Name)))
		}
	}
	for _, s := range program {
		impl, ok := s.(*TraitImpl)
		if !ok {
			continue
		}
		names := map[string]bool{}
		for _, d := range impl.Defs {
			names[d.Name] = true
		}
		c.impls[[2]string{impl.Trait, impl.TypeName}] = names
		for _, d := range impl.Defs {
			key := implKey(impl.Trait, impl.TypeName, d.Name)
			if impl.Trait == Showable {
				c.showImpls[key] = true
			}
			defs = append(defs, renamed(d, key))
		}
	}
	for _, d := range defs {
		if strings.HasPrefix(d.Name, "\x00") {
			k := displayName(d.Name)
			c.aliases[k] = append(c.aliases[k], d.Name)
		}
	}
	sigs := c.collectSigs(program, defs)
	sc := c.inferDefs(defs, local, sigs)
	for name, v := range sc.vars {
		if strings.HasPrefix(name, "\x00") {
			c.base.set(name, v)
		}
	}
	return sc
}

func (c *Checker) checkModule(m *Module, line Pos) *TEnv {
	if sc, ok := c.checked[m.Path]; ok {
		return sc
	}
	var sc *TEnv
	err := try(func() {
		var prims map[string]any
		if bs := libPrimitives(m.Path); bs != nil {
			prims = map[string]any{}
			for _, b := range bs {
				prims[b.Name] = &PrimRef{b.Name}
			}
		}
		savedFile := c.file
		c.file = m.Path
		defer func() { c.file = savedFile }()
		sc = c.checkUnit(m.Program, prims)
		c.checked[m.Path] = sc
		for n, v := range prims {
			if _, ok := sc.vars[n]; !ok {
				sc.set(n, v)
			}
		}
		c.solve(sc)
	})
	if err != nil {
		w := ""
		if err.Line.Line != 0 {
			w = where(err.Line)
		}
		raise(line, "「"+m.Name+SourceSuffix+"」の"+w+": "+err.Message)
	}
	return sc
}

func renamed(d *Define, name string) *Define {
	return &Define{name, d.Params, d.Body, d.IsFunction, d.Line}
}

func (c *Checker) inst(v any, line Pos, name string) Type {
	s, ok := v.(*Scheme)
	if !ok {
		return v.(Type)
	}
	start := len(c.pending)
	t := s.instantiate(&c.pending)
	if line.Line != 0 {
		for _, k := range c.pending[start:] {
			k.Line = line
			if len(k.Kinds) > 0 && name != "" && !strings.Contains(k.Message, "に渡した値: ") {
				k.Message = "「" + displayName(name) + "」に渡した値: " + k.Message
			}
		}
	}
	return t
}

func (c *Checker) inferDefs(defs []*Define, env *TEnv, sigs map[string]*TypeSig) *TEnv {
	scope := newTEnv(env)
	for _, comp := range sccs(defs, c.aliases) {
		mono := map[string]*TVar{}
		for _, d := range comp {
			mono[d.Name] = newTVar()
		}
		inner := newTEnv(scope)
		for k, v := range mono {
			inner.set(k, v)
		}
		type decl struct {
			t     Type
			tvars *tvarMap
		}
		declared := map[string]decl{}
		var declOrder []string
		for _, d := range comp {
			if sg, ok := sigs[d.Name]; ok {
				t, tv := c.declaredType(sg)
				declared[d.Name] = decl{t, tv}
				declOrder = append(declOrder, d.Name)
			}
		}
		for _, name := range declOrder {
			if !sigs[name].HasParams {
				c.unify(mono[name], declared[name].t)
			}
		}
		type head struct {
			local *TEnv
			t     *TFun
		}
		heads := map[string]head{}
		for _, d := range comp {
			if d.IsFunction {
				l, t := c.functionHead(d, inner, mono[d.Name])
				heads[d.Name] = head{l, t}
			}
		}
		for _, name := range declOrder {
			if h, ok := heads[name]; ok {
				c.applySig(sigs[name], declared[name].t.(*TFun), h.t)
			}
		}
		for _, d := range comp {
			c.line = d.Line
			var hp *head
			if h, ok := heads[d.Name]; ok {
				hp = &h
			}
			var t Type
			if hp != nil {
				t = c.inferDefine(d, inner, hp.local, hp.t, sigs[d.Name])
			} else {
				t = c.inferDefine(d, inner, nil, nil, sigs[d.Name])
			}
			_, isDecl := declared[d.Name]
			dd := d
			if isDecl && !d.IsFunction {
				c.unifyOr(mono[d.Name], t, d.Line, func(sa, sb string) string {
					return "「" + displayName(dd.Name) + "」は" + sa + "と宣言されていますが、" + sb + "になっています"
				})
			} else {
				c.unifyOr(mono[d.Name], t, d.Line, func(sa, sb string) string {
					return "「" + displayName(dd.Name) + "」の型が合いません(" + sa + " と " + sb + ")"
				})
			}
		}
		c.solve(inner)
		for _, name := range declOrder {
			c.checkRigid(sigs[name], declared[name].tvars)
		}
		for _, d := range comp {
			c.note(d.Line, d.Name, mono[d.Name], true)
		}
		outerFree := scope.freeVars()
		taken := map[*Constraint]bool{}
		for _, d := range comp {
			t := mono[d.Name]
			quantified := newVarSet()
			for _, v := range ftv(t, nil).order {
				if !outerFree.has(v) {
					quantified.add(v)
				}
			}
			var mine []*Constraint
			for {
				mine = nil
				for _, k := range c.pending {
					tv := k.typeVars()
					for _, v := range tv.order {
						if quantified.has(v) {
							mine = append(mine, k)
							break
						}
					}
				}
				more := newVarSet()
				for _, k := range mine {
					for _, v := range k.typeVars().order {
						if !outerFree.has(v) && !quantified.has(v) {
							more.add(v)
						}
					}
				}
				if more.len() == 0 {
					break
				}
				for _, v := range more.order {
					quantified.add(v)
				}
			}
			for _, k := range mine {
				taken[k] = true
			}
			for _, v := range quantified.order {
				v.gen = true
			}
			scope.set(d.Name, &Scheme{append([]*TVar{}, quantified.order...), t, mine})
		}
		var rest []*Constraint
		for _, k := range c.pending {
			if !taken[k] {
				rest = append(rest, k)
			}
		}
		c.pending = rest
	}
	return scope
}

// --- 型の条件 ---

func (c *Checker) removePending(k *Constraint) bool {
	for i, x := range c.pending {
		if x == k {
			c.pending = append(c.pending[:i:i], c.pending[i+1:]...)
			return true
		}
	}
	return false
}

func (c *Checker) inPending(k *Constraint) bool {
	for _, x := range c.pending {
		if x == k {
			return true
		}
	}
	return false
}

func (c *Checker) solve(env *TEnv) {
	progress := true
	for progress {
		progress = false
		snapshot := append([]*Constraint{}, c.pending...)
		for _, k := range snapshot {
			r := prune(k.T)
			if v, ok := r.(*TVar); ok && !(k.Op != "" && v.Pure) {
				continue
			}
			if !c.inPending(k) {
				continue
			}
			c.removePending(k)
			if c.discharge(k, env) {
				progress = true
			} else {
				c.pending = append(c.pending, k)
			}
		}
		items := append([]pureDeferred{}, ts.deferred...)
		for _, item := range items {
			if c.coercePure(item.c, item.t, env) {
				for i, x := range ts.deferred {
					if x == item {
						ts.deferred = append(ts.deferred[:i:i], ts.deferred[i+1:]...)
						break
					}
				}
				progress = true
			}
		}
	}
}

func (c *Checker) post(k *Constraint, env *TEnv) {
	c.pending = append(c.pending, k)
	c.solve(env)
}

func (c *Checker) implType(trait, tname, method string, env *TEnv) Type {
	v := env.lookup(implKey(trait, tname, method))
	if v == nil {
		return nil
	}
	return prune(c.inst(v, Pos{}, ""))
}

func (c *Checker) coercePure(cv Type, t *TCon, env *TEnv) bool {
	if !c.impls[[2]string{Monad, t.Name}][UnitName] {
		return true
	}
	impl := c.implType(Monad, t.Name, UnitName, env)
	if impl == nil {
		return false
	}
	if f, ok := impl.(*TFun); ok && len(f.Params) > 0 {
		// 多相にした後の型変数に触れるかもしれないので、環境の自由な型変数の覚えを捨てる
		ts.genEpoch++
		c.unifyOr(cv, f.Params[0].T, c.line, func(sa, sb string) string {
			return "「" + UnitName + "」(" + t.Name + "の実装)には" + sb + "が必要ですが、" + sa + "が渡されています"
		})
		c.unifyOr(t, f.Result, c.line, func(sa, sb string) string {
			return "「" + UnitName + "」の値の型が合いません(" + sa + " と " + sb + ")"
		})
	}
	return true
}

func (c *Checker) discharge(k *Constraint, env *TEnv) bool {
	if k.Op != "" {
		var result bool
		m := catchMismatch(func() {
			r := prune(k.T)
			switch k.Op {
			case "bind":
				result = c.onBind(r, k, env)
			case "map":
				result = c.onMap(r, k, env)
			case "wrap":
				result = c.onWrap(r, k, env)
			case "flatten":
				result = c.onFlatten(r, k, env)
			case "item":
				result = c.onItem(r, k, env)
			}
		})
		if m != nil {
			c.fail(k.Line, "動作の結果の型が合いません("+show1(k.T)+")")
		}
		return result
	}
	r := prune(k.T)
	name := "関数"
	if tc, ok := r.(*TCon); ok {
		name = tc.Name
	}
	if k.Trait == "" {
		if !contains(k.Kinds, name) {
			c.fail(k.Line, k.Message+"です("+show1(r)+"になっています)")
		}
		return true
	}
	methods, ok := c.impls[[2]string{k.Trait, name}]
	if !ok {
		c.fail(k.Line, show1(r)+"は性質「"+k.Trait+"」を持っていません(「"+k.Method+"」が使えません)")
	}
	var key string
	if methods[k.Method] {
		key = implKey(k.Trait, name, k.Method)
	} else if c.traits[k.Trait].defaults[k.Method] {
		key = implKey(k.Trait, "", k.Method)
	} else {
		return true
	}
	v := env.lookup(key)
	if v == nil {
		return false
	}
	impl := prune(c.inst(v, Pos{}, ""))
	f, ok := impl.(*TFun)
	if !ok {
		return true
	}
	params := map[string]Type{}
	for _, p := range f.Params {
		params[p.Part] = p.T
	}
	for _, p := range k.FType.Params {
		if pt, ok := params[p.Part]; ok {
			part := p.Part
			c.unifyOr(p.T, pt, k.Line, func(sa, sb string) string {
				return "「" + k.Method + "」(" + show1(r) + "の実装)の「" + part + "」には" + sb + "が必要ですが、" + sa + "が渡されています"
			})
		}
	}
	c.unifyOr(k.FType.Result, f.Result, k.Line, func(sa, sb string) string {
		return "「" + k.Method + "」(" + show1(r) + "の実装)の値の型が合いません(" + sb + " と " + sa + ")"
	})
	return true
}

func (c *Checker) traitFun(name string, line Pos) *TFun {
	trait := c.methodTrait[name]
	sig, _ := c.traits[trait].method(name)
	t := newTVar()
	dispatch := ""
	if len(sig) > 0 {
		dispatch = sig[0].Part
	}
	for _, p := range sig {
		if p.Part == WO {
			dispatch = WO
			break
		}
	}
	var params []TParam
	for _, p := range sig {
		if p.Part == dispatch {
			if !p.List {
				params = append(params, TParam{p.Part, t})
			} else {
				params = append(params, TParam{p.Part, lst(t)})
			}
		} else {
			params = append(params, TParam{p.Part, newTVar()})
		}
	}
	ftype := &TFun{params, newTVar()}
	if len(sig) > 0 {
		c.pending = append(c.pending, &Constraint{T: t, Line: line, Trait: trait, Method: name, FType: ftype})
	}
	return ftype
}

// --- 型の宣言 ---

func (c *Checker) collectSigs(program []Node, defs []*Define) map[string]*TypeSig {
	names := map[string]*Define{}
	for _, d := range defs {
		names[d.Name] = d
	}
	sigs := map[string]*TypeSig{}
	for _, s := range program {
		sg, ok := s.(*TypeSig)
		if !ok {
			continue
		}
		if _, ok := sigs[sg.Name]; ok {
			c.fail(sg.Line, "「"+sg.Name+"」の型が2回宣言されています")
		}
		if _, ok := c.methodTrait[sg.Name]; ok {
			c.fail(sg.Line, "「"+sg.Name+"」は性質の関数なので、型は性質の宣言で決まります")
		}
		d, ok := names[sg.Name]
		if !ok {
			c.fail(sg.Line, "「"+sg.Name+"」の型を宣言していますが、一番外にその定義がありません")
		}
		if sg.HasParams != d.IsFunction {
			what := "値"
			if d.IsFunction {
				what = "関数"
			}
			c.fail(sg.Line, "「"+sg.Name+"」は"+what+"なので、型の宣言の書き方が違います")
		}
		if sg.HasParams {
			want := sortedParts(paramParts(d.Params))
			var gp []string
			for _, p := range sg.Params {
				gp = append(gp, p.Part)
			}
			got := sortedParts(gp)
			if !eqStrings(want, got) {
				g, w := joinDot(got), joinDot(want)
				if g == "" {
					g = "なし"
				}
				if w == "" {
					w = "なし"
				}
				c.fail(sg.Line, "「"+sg.Name+"」の型の宣言の助詞("+g+")が定義の助詞("+w+")と違います")
			}
		}
		sigs[sg.Name] = sg
	}
	return sigs
}

type tvarMap struct {
	m     map[string]*TVar
	order []string
}

func (t *tvarMap) get(name string) *TVar {
	if v, ok := t.m[name]; ok {
		return v
	}
	v := newTVar()
	t.m[name] = v
	t.order = append(t.order, name)
	return v
}

func (c *Checker) declaredType(sg *TypeSig) (Type, *tvarMap) {
	tvars := &tvarMap{m: map[string]*TVar{}}
	result := c.typeOf(sg.Result, tvars, sg.Line)
	if !sg.HasParams {
		return result, tvars
	}
	var ps []TParam
	for _, p := range sg.Params {
		ps = append(ps, TParam{p.Part, c.typeOf(p.Type, tvars, sg.Line)})
	}
	return &TFun{ps, result}, tvars
}

func (c *Checker) typeOf(te Node, tvars *tvarMap, line Pos) Type {
	switch x := te.(type) {
	case *TypeVarName:
		return tvars.get(x.Name)
	case *TypeFun:
		var ps []TParam
		for _, p := range x.Params {
			ps = append(ps, TParam{p.Part, c.typeOf(p.Type, tvars, line)})
		}
		return &TFun{ps, c.typeOf(x.Result, tvars, line)}
	}
	tn := te.(*TypeName)
	var args []Type
	for _, a := range tn.Args {
		args = append(args, c.typeOf(a, tvars, line))
	}
	if basicTypes[tn.Name] {
		return &TCon{Name: tn.Name}
	}
	if monadTypes[tn.Name] {
		return &TCon{tn.Name, []Type{args[0]}}
	}
	if _, ok := c.shapes.keys[tn.Name]; !ok {
		return newTVar()
	}
	inst := c.freshType(tn.Name)
	var keys []fieldKey
	for _, k := range c.shapes.keys[tn.Name] {
		if _, ok := c.shapes.recursive[k]; !ok {
			keys = append(keys, k)
		}
	}
	if len(args) > len(keys) {
		var fs []string
		for _, k := range keys {
			fs = append(fs, k.F)
		}
		c.fail(line, fmt.Sprintf("「%s」がとる型の引数は%d個です(フィールド: %s)", tn.Name, len(keys), joinDot(fs)))
	}
	for i, a := range args {
		if i >= len(keys) {
			break
		}
		k := keys[i]
		c.unifyOr(c.fieldType(inst, k, nil), a, line, func(sa, sb string) string {
			return "「" + tn.Name + "」の「" + k.F + "」は" + sa + "なので、" + sb + "にはできません"
		})
	}
	return inst
}

func (c *Checker) applySig(sg *TypeSig, declared *TFun, head *TFun) {
	params := map[string]Type{}
	for _, p := range head.Params {
		params[p.Part] = p.T
	}
	for _, p := range declared.Params {
		part := p.Part
		c.unifyOr(params[p.Part], p.T, sg.Line, func(sa, sb string) string {
			return "「" + sg.Name + "」の「" + part + "」は" + sb + "と宣言されていますが、定義では" + sa + "です"
		})
	}
	c.unifyOr(head.Result, declared.Result, sg.Line, func(sa, sb string) string {
		return "「" + sg.Name + "」の値は" + sb + "と宣言されていますが、定義では" + sa + "です"
	})
}

func (c *Checker) checkRigid(sg *TypeSig, tvars *tvarMap) {
	seen := map[*TVar]string{}
	for _, name := range tvars.order {
		r := prune(tvars.m[name])
		rv, ok := r.(*TVar)
		if !ok || rv.Pure {
			c.fail(sg.Line, "「"+sg.Name+"」の型の宣言の「"+name+"」は、定義では"+show1(r)+"に決まります(どんな型でもよいときだけ甲・乙 … を使います)")
		}
		if prev, ok := seen[rv]; ok {
			c.fail(sg.Line, "「"+sg.Name+"」の型の宣言の「"+prev+"」と「"+name+"」は、定義では同じ型になります")
		}
		seen[rv] = name
	}
}

func (c *Checker) functionHead(d *Define, env *TEnv, mono Type) (*TEnv, *TFun) {
	local := newTEnv(env)
	var params []TParam
	for _, p := range d.Params {
		params = append(params, TParam{p.Part, c.bindParam(p, local)})
	}
	t := &TFun{params, newTVar()}
	if mono != nil {
		c.unify(mono, t)
	}
	return local, t
}

func (c *Checker) inferDefine(d *Define, env *TEnv, local *TEnv, t *TFun, sg *TypeSig) Type {
	if !d.IsFunction {
		return c.infer(d.Body, env)
	}
	if t == nil {
		local, t = c.functionHead(d, env, nil)
	}
	result := c.infer(d.Body, local)
	if sg != nil {
		c.unifyOr(t.Result, result, d.Line, func(sa, sb string) string {
			return "「" + displayName(d.Name) + "」の値は" + sa + "と宣言されていますが、" + sb + "になっています"
		})
	}
	c.unifyOr(t.Result, result, d.Line, func(sa, sb string) string {
		return "「" + displayName(d.Name) + "」の値の型が合いません(" + sa + " と " + sb + ")"
	})
	if c.showImpls[d.Name] {
		c.expect(result, STR, d.Line, "「"+ToString+"」の値")
	}
	if isPredicate(d.Name) {
		c.expect(result, BOOL, d.Line, "述語「"+d.Name+"」の値")
	}
	return &TFun{t.Params, result}
}

func (c *Checker) bindParam(p Param, env *TEnv) Type {
	if !p.List {
		t := newTVar()
		env.set(p.Name, t)
		return t
	}
	elem := newTVar()
	for _, n := range p.Names {
		env.set(n, elem)
	}
	return lst(elem)
}

// --- 式 ---

func (c *Checker) infer(node Node, env *TEnv) Type {
	if l := lineOf(node); l.Line != 0 {
		c.line = l
	}
	switch n := node.(type) {
	case *Num:
		switch n.Value.Kind {
		case NBool:
			return BOOL
		case NEmpty:
			return lst(newTVar())
		}
		return NUM
	case *Str:
		return STR
	case *Var:
		t := c.inferVar(n, env)
		c.note(n.Line, n.Name, t, false)
		return t
	case *ListLit:
		elem := newTVar()
		for _, item := range n.Items {
			t := c.infer(item, env)
			c.unifyOr(elem, t, firstLine(item), func(sa, sb string) string {
				return "リストの要素の型がそろっていません(" + sa + " と " + sb + ")。違う型の値をまとめるときは、組か選択肢のある型を使ってください"
			})
		}
		return lst(elem)
	case *Prop:
		t := c.infer(n.Target, env)
		if n.Name == "長さ" {
			c.needKind(t, []string{"文字列", "リスト"}, n.Line, "「の 長さ」の前は文字列かリスト")
			return NUM
		}
		elem := newTVar()
		c.expect(t, lst(elem), n.Line, "「の "+n.Name+"」の前")
		if n.Name == "残り" {
			return lst(elem)
		}
		return elem
	case *Each:
		t := c.infer(n.Target, env)
		c.expect(t, lst(newTVar()), n.Line, "「の それぞれ」の前")
		return t
	case *Neg:
		c.expect(c.infer(n.Operand, env), NUM, c.line, "「-」の後")
		return NUM
	case *Not:
		c.expect(c.infer(n.Operand, env), BOOL, n.Line, "「でない」の前")
		return BOOL
	case *BinOp:
		return c.inferBinOp(n, env)
	case *If:
		line := firstLine(n)
		if line.Line == 0 {
			line = c.line
		}
		c.expect(c.infer(n.Cond, env), BOOL, line, "「もし」の条件")
		a := c.infer(n.Then, env)
		b := c.infer(n.Other, env)
		ol := firstLine(n.Other)
		if ol.Line == 0 {
			ol = line
		}
		c.unifyOr(a, b, ol, func(sa, sb string) string {
			return "「ならば」と「そうでなければ」の値の型が違います(" + sa + " と " + sb + ")"
		})
		return a
	case *Block:
		var defs []*Define
		for _, s := range n.Statements {
			if d, ok := s.(*Define); ok {
				defs = append(defs, d)
			}
		}
		local := c.inferDefs(defs, env, nil)
		var result Type = newTVar()
		for _, s := range n.Statements {
			if _, ok := s.(*Define); !ok {
				result = c.infer(s, local)
			}
		}
		return result
	case *Lambda:
		local := newTEnv(env)
		var params []TParam
		for _, p := range n.Params {
			params = append(params, TParam{p.Part, c.bindParam(p, local)})
		}
		return &TFun{params, c.infer(n.Body, local)}
	case *Call:
		return c.inferCall(n, env)
	case *Ref:
		return c.inferRef(n, env)
	case *Construct:
		return c.inferConstruct(n, env)
	case *NamedConstruct:
		result := c.ctorType(n.Ctor)
		info, _ := c.ctx.Ctors.Get(n.Ctor)
		for _, f := range n.Fields {
			if !contains(info.Fields, f.Name) {
				c.fail(n.Line, "「"+n.Ctor+"」には「"+f.Name+"」というフィールドがありません")
			}
			fname := f.Name
			c.unifyOr(c.infer(f.Value, env), c.ctorField(result, n.Ctor, f.Name), n.Line, func(sa, sb string) string {
				return "「" + n.Ctor + "」の「" + fname + "」は" + sb + "ですが、" + sa + "が渡されています"
			})
		}
		return result
	case *Update:
		t := c.infer(n.Target, env)
		for _, f := range n.Fields {
			ft := c.fieldOf(t, f.Name, n.Line)
			fname := f.Name
			c.unifyOr(c.infer(f.Value, env), ft, n.Line, func(sa, sb string) string {
				return "「" + fname + "」は" + sb + "ですが、" + sa + "が渡されています"
			})
		}
		return t
	case *Field:
		t := c.infer(n.Target, env)
		return c.fieldOf(t, n.Name, n.Line)
	case *Match:
		return c.inferMatch(n, env)
	case *Run:
		t := env.lookup(runKey(n))
		if t == nil {
			c.fail(n.Line, "「した 結果」は手順の文の中で使ってください(関数の本体や条件分岐の枝の中では、そこを「手順（…）」で囲みます)")
		}
		return t.(Type)
	case *Chain:
		m := c.infer(n.Call, env)
		elem := newTVar()
		c.monadElem(m, elem, env)
		local := newTEnv(env)
		local.set(Hole, elem)
		k := c.infer(n.Cont, local)
		return c.bind(m, elem, k, n.Line, "「してから」の前の値({t})は動作ではありません(純粋な値なら「して」を使います)", env)
	case *Do:
		return c.doType(n.Statements, 0, newTEnv(env), n.Line)
	case *Sequel:
		return c.infer(n.Expr, env)
	}
	return newTVar()
}

func (c *Checker) inferVar(n *Var, env *TEnv) Type {
	v := env.lookup(n.Name)
	if p, ok := v.(*PrimRef); ok {
		return primFuns[p.Name]()
	}
	if v != nil {
		return c.inst(v, n.Line, "")
	}
	if info, ok := c.ctx.Ctors.Get(n.Name); ok && len(info.Fields) == 0 {
		return c.ctorType(n.Name)
	}
	return newTVar()
}

func (c *Checker) inferBinOp(n *BinOp, env *TEnv) Type {
	a := c.infer(n.Left, env)
	b := c.infer(n.Right, env)
	op := n.Op
	for i, x := range []Type{a, b} {
		if isAction(x) {
			side := "右"
			if i == 0 || x == a {
				side = "左"
			}
			c.fail(n.Line, "「"+op+"」の"+side+"が動作("+show1(x)+")です。動作の結果で計算するときは「…してから」か「… の 結果 を …」を使ってください")
		}
	}
	switch op {
	case KwKatsu, KwMataha:
		c.expect(a, BOOL, n.Line, "「"+op+"」の左")
		c.expect(b, BOOL, n.Line, "「"+op+"」の右")
		return BOOL
	case "==", "!=":
		c.unifyOr(a, b, n.Line, func(sa, sb string) string {
			return sa + " と " + sb + " は比べられません(同じ型どうしで比べてください)"
		})
		return BOOL
	case "<", ">", "<=", ">=":
		c.expect(a, NUM, n.Line, "「"+op+"」の左")
		c.expect(b, NUM, n.Line, "「"+op+"」の右")
		return BOOL
	case "+":
		c.unifyOr(a, b, n.Line, func(sa, sb string) string {
			return "「+」の両側の型が違います(" + sa + " と " + sb + ")。数を文字列につなぐときは「x を 文字列化する」を使ってください"
		})
		c.needKind(a, []string{"数", "文字列", "リスト"}, n.Line, "「+」で足せるのは数・文字列・リスト")
		return a
	}
	c.expect(a, NUM, n.Line, "「"+op+"」の左")
	c.expect(b, NUM, n.Line, "「"+op+"」の右")
	return NUM
}

func (c *Checker) needKind(t Type, kinds []string, line Pos, message string) {
	k := &Constraint{T: t, Line: line, Kinds: kinds, Message: message}
	if _, ok := prune(t).(*TVar); ok {
		c.pending = append(c.pending, k)
	} else {
		c.discharge(k, newTEnv(nil))
	}
}

// --- 呼び出し ---

type typedArg struct {
	part string
	t    Type
}

type typedArgs []typedArg

func (a typedArgs) get(p string) (Type, bool) {
	for _, x := range a {
		if x.part == p {
			return x.t, true
		}
	}
	return nil, false
}

func (a typedArgs) must(p string) Type { t, _ := a.get(p); return t }

func (c *Checker) inferCall(n *Call, env *TEnv) Type {
	var args typedArgs
	each := false
	type lift struct {
		m, elem Type
		line    Pos
	}
	var lifted []lift
	for _, a := range n.Args {
		if e, ok := a.Value.(*Each); ok {
			t := c.infer(e.Target, env)
			elem := newTVar()
			c.expect(t, lst(elem), e.Line, "「の それぞれ」の前")
			args = append(args, typedArg{a.Part, elem})
			each = true
		} else if f, ok := a.Value.(*Field); ok && f.Name == Result && !c.hasField(Result) {
			m := c.infer(f.Target, env)
			elem := newTVar()
			c.monadElem(m, elem, env)
			args = append(args, typedArg{a.Part, elem})
			l := f.Line
			if l.Line == 0 {
				l = n.Line
			}
			lifted = append(lifted, lift{m, elem, l})
		} else {
			args = append(args, typedArg{a.Part, c.infer(a.Value, env)})
		}
	}
	result := c.callType(n.Name, args, n.Line, env)
	if c.record {
		ps := make([]TParam, len(args))
		for i, a := range args {
			ps[i] = TParam{a.part, a.t}
		}
		c.note(n.Line, n.Name, &TFun{ps, result}, false)
	}
	if each {
		result = lst(result)
	}
	for idx := len(lifted) - 1; idx >= 0; idx-- {
		l := lifted[idx]
		if idx == len(lifted)-1 {
			out := newTVar()
			c.post(&Constraint{T: l.m, Line: l.line, Message: "{t}は性質「" + Mappable + "」を持っていません(「の 結果」が使えません)",
				Op: "map", Extra: []Type{l.elem, result, out}}, env)
			result = out
		} else {
			result = c.bind(l.m, l.elem, result, l.line, "{t}は性質「"+Monad+"」を持っていません(「の 結果」が使えません)", env)
		}
	}
	return result
}

func (c *Checker) callType(name string, args typedArgs, line Pos, env *TEnv) Type {
	v := env.lookup(name)
	if p, ok := v.(*PrimRef); ok {
		c.env = env
		return primCalls[p.Name](c, args, line)
	}
	if v != nil {
		t := prune(c.inst(v, line, name))
		if f, ok := t.(*TFun); ok {
			return c.callFun(name, f, args, line)
		}
		return newTVar()
	}
	if _, ok := c.methodTrait[name]; ok {
		result := c.callFun(name, c.traitFun(name, line), args, line)
		c.solve(env)
		return result
	}
	if typer, ok := builtinCalls[name]; ok {
		c.env = env
		return typer(c, args, line)
	}
	return newTVar()
}

func (c *Checker) callFun(name string, t *TFun, args typedArgs, line Pos) Type {
	params := map[string]bool{}
	for _, p := range t.Params {
		params[p.Part] = true
	}
	for _, a := range args {
		if !params[a.part] {
			c.fail(line, "「"+name+"」は「"+a.part+"」の引数を受け取りません")
		}
	}
	for _, p := range t.Params {
		at, ok := args.get(p.Part)
		if !ok {
			c.fail(line, "「"+name+"」には「"+p.Part+"」の引数が必要です")
		}
		c.arg(at, p.T, line, name, p.Part)
	}
	return t.Result
}

func (c *Checker) arg(actual, expected Type, line Pos, name, part string) {
	c.unifyOr(actual, expected, line, func(sa, sb string) string {
		return "「" + name + "」の「" + part + "」には" + sb + "が必要ですが、" + sa + "が渡されています"
	})
}

func (c *Checker) funValue(name string, env *TEnv, line Pos) Type {
	v := env.lookup(name)
	if p, ok := v.(*PrimRef); ok {
		return primFuns[p.Name]()
	}
	if v != nil {
		return c.inst(v, line, name)
	}
	if _, ok := c.methodTrait[name]; ok {
		return c.traitFun(name, line)
	}
	if sig, ok := builtinFuns[name]; ok {
		return sig()
	}
	return newTVar()
}

func (c *Checker) inferRef(n *Ref, env *TEnv) Type {
	t := prune(c.funValue(n.Name, env, n.Line))
	c.note(n.Line, n.Name, t, false)
	if len(n.Args) == 0 {
		return t
	}
	var given typedArgs
	for _, a := range n.Args {
		given = append(given, typedArg{a.Part, c.infer(a.Value, env)})
	}
	f, ok := t.(*TFun)
	if !ok {
		return newTVar()
	}
	params := map[string]Type{}
	for _, p := range f.Params {
		params[p.Part] = p.T
	}
	for _, g := range given {
		pt, ok := params[g.part]
		if !ok {
			c.fail(n.Line, "「"+n.Name+"」は「"+g.part+"」の引数を受け取りません")
		}
		c.arg(g.t, pt, n.Line, n.Name, g.part)
	}
	var rest []TParam
	for _, p := range f.Params {
		if _, ok := given.get(p.Part); !ok {
			rest = append(rest, p)
		}
	}
	return &TFun{rest, f.Result}
}

func (c *Checker) apply(fn Type, values []Type, line Pos, what string) Type {
	t := prune(fn)
	if _, ok := t.(*TVar); ok {
		r := newTVar()
		var ps []TParam
		for _, v := range values {
			ps = append(ps, TParam{WO, v})
		}
		c.unify(t, &TFun{ps, r})
		return r
	}
	f, ok := t.(*TFun)
	if !ok {
		c.fail(line, what+"には関数が必要ですが、"+show1(t)+"になっています")
	}
	if len(values) > len(f.Params) {
		c.fail(line, what+"の関数"+show1(t)+"に渡す値が多すぎます")
	}
	for i, v := range values {
		c.unifyOr(v, f.Params[i].T, line, func(sa, sb string) string {
			return what + "の関数は" + sb + "を受け取りますが、" + sa + "が渡されます"
		})
	}
	rest := f.Params[len(values):]
	if len(rest) > 0 {
		return &TFun{rest, f.Result}
	}
	return f.Result
}

// --- 組 ---

func (c *Checker) freshType(tname string) *TCon {
	ps := c.shapes.params(tname)
	args := make([]Type, len(ps))
	for i := range ps {
		args[i] = newTVar()
	}
	t := &TCon{tname, args}
	c.instances = append(c.instances, t)
	return t
}

func (c *Checker) ctorType(ctor string) *TCon {
	info, _ := c.ctx.Ctors.Get(ctor)
	return c.freshType(info.Type)
}

func (c *Checker) fieldType(t *TCon, key fieldKey, seen map[fieldKey]bool) Type {
	sh := c.shapes
	ps := sh.params(key.T)
	if i := indexKey(ps, key); i >= 0 {
		return t.Args[i]
	}
	tmpl := sh.recursive[key]
	mapping := map[*TVar]Type{}
	for _, v := range ftv(tmpl, nil).order {
		var other *fieldKey
		for _, k := range sh.phOrder {
			if sh.ph[k] == v {
				kk := k
				other = &kk
				break
			}
		}
		if other != nil && other.T == key.T && !seen[*other] {
			ns := map[fieldKey]bool{key: true}
			for k := range seen {
				ns[k] = true
			}
			mapping[v] = c.fieldType(t, *other, ns)
		} else {
			mapping[v] = newTVar()
		}
	}
	return fill(tmpl, mapping, t)
}

func (c *Checker) ctorField(t Type, ctor, f string) Type {
	info, _ := c.ctx.Ctors.Get(ctor)
	return c.fieldType(prune(t).(*TCon), fieldKey{info.Type, f}, nil)
}

func (c *Checker) hasField(name string) bool {
	for _, k := range c.ctx.Ctors.Keys() {
		info, _ := c.ctx.Ctors.Get(k)
		if contains(info.Fields, name) {
			return true
		}
	}
	return false
}

func (c *Checker) fieldOf(t Type, name string, line Pos) Type {
	r := prune(t)
	types := newOrderedSet()
	for _, k := range c.ctx.Ctors.Keys() {
		info, _ := c.ctx.Ctors.Get(k)
		if contains(info.Fields, name) {
			types.add(info.Type)
		}
	}
	if rc, ok := r.(*TCon); ok {
		if !types.m[rc.Name] || !c.shapes.isUser(rc) {
			_, hasMonad := c.impls[[2]string{Monad, rc.Name}]
			if name == Result && (monadTypes[rc.Name] || hasMonad) {
				c.fail(line, "「の 結果」は「入力 の 結果 を 数値にする」のように呼び出しの引数に書いてください")
			}
			c.fail(line, show1(rc)+"には「"+name+"」というフィールドがありません")
		}
		return c.fieldType(rc, fieldKey{rc.Name, name}, nil)
	}
	if rv, ok := r.(*TVar); ok && rv.Pure && name == Result {
		c.fail(line, "「の 結果」は「入力 の 結果 を 数値にする」のように呼び出しの引数に書いてください")
	}
	if len(types.order) == 1 {
		c.expect(t, c.freshType(types.order[0]), line, "「の "+name+"」の前")
		return c.fieldOf(t, name, line)
	}
	return newTVar()
}

func (c *Checker) inferConstruct(n *Construct, env *TEnv) Type {
	info, _ := c.ctx.Ctors.Get(n.Ctor)
	fields := info.Fields
	var items []Type
	for _, i := range n.Items {
		items = append(items, c.infer(i, env))
	}
	if len(items) == 1 && len(fields) >= 2 {
		elem := newTVar()
		c.expect(items[0], lst(elem), n.Line, "「"+n.Ctor+"」に渡す値")
		items = make([]Type, len(fields))
		for i := range items {
			items[i] = elem
		}
	}
	if len(items) != len(fields) {
		c.fail(n.Line, fmt.Sprintf("「%s」には%d個の値が必要です(渡されたのは%d個)", n.Ctor, len(fields), len(items)))
	}
	result := c.ctorType(n.Ctor)
	for i, f := range fields {
		fname := f
		c.unifyOr(items[i], c.ctorField(result, n.Ctor, f), n.Line, func(sa, sb string) string {
			return "「" + n.Ctor + "」の「" + fname + "」は" + sb + "ですが、" + sa + "が渡されています"
		})
	}
	return result
}

// --- 場合分け ---

func (c *Checker) inferMatch(n *Match, env *TEnv) Type {
	var parts []Type
	var subject Type
	listSubject := false
	if l, ok := n.Subject.(*ListLit); ok {
		listSubject = true
		for _, i := range l.Items {
			parts = append(parts, c.infer(i, env))
		}
	} else {
		subject = c.infer(n.Subject, env)
	}
	result := newTVar()
	for _, cs := range n.Cases {
		local := newTEnv(env)
		if ps, ok := cs.Pat.(*PSeq); ok && listSubject && len(ps.Items) == len(parts) {
			for i, p := range ps.Items {
				c.bindPattern(p, parts[i], local, n.Line)
			}
		} else {
			if subject == nil {
				subject = c.infer(n.Subject, env)
			}
			c.bindPattern(cs.Pat, subject, local, n.Line)
		}
		if cs.Guard != nil {
			c.expect(c.infer(cs.Guard, local), BOOL, n.Line, "「かつ」の条件")
		}
		bl := lineOf(cs.Body)
		if bl.Line == 0 {
			bl = n.Line
		}
		c.unifyOr(c.infer(cs.Body, local), result, bl, func(sa, sb string) string {
			return "場合ごとの値の型がそろっていません(" + sb + " と " + sa + ")"
		})
	}
	if n.Default != nil {
		c.unifyOr(c.infer(n.Default, env), result, n.Line, func(sa, sb string) string {
			return "「そうでなければ」の値の型がほかの場合と違います(" + sb + " と " + sa + ")"
		})
	}
	return result
}

func patMismatch(sa, sb string) string {
	return "パターンの型が合いません(" + sa + " の値を " + sb + " のパターンで調べています)"
}

func (c *Checker) bindPattern(pat Node, t Type, env *TEnv, line Pos) {
	switch p := pat.(type) {
	case *PBind:
		env.set(p.Name, t)
	case *PValue:
		c.unifyOr(t, c.infer(p.Expr, env), line, patMismatch)
	case *PCtor:
		ct := c.ctorType(p.Ctor)
		c.unifyOr(t, ct, p.Line, patMismatch)
		info, _ := c.ctx.Ctors.Get(p.Ctor)
		for i, f := range info.Fields {
			if i >= len(p.Items) {
				break
			}
			c.bindPattern(p.Items[i], c.ctorField(ct, p.Ctor, f), env, p.Line)
		}
	case *PNamed:
		if p.HasCtor {
			ct := c.ctorType(p.Ctor)
			c.unifyOr(t, ct, p.Line, patMismatch)
			for _, f := range p.Fields {
				c.bindPattern(f.Value, c.ctorField(ct, p.Ctor, f.Name), env, p.Line)
			}
			return
		}
		allList := true
		for _, f := range p.Fields {
			if f.Name != "先頭" && f.Name != "残り" {
				allList = false
			}
		}
		if allList && !pruneIsRecord(t) {
			elem := newTVar()
			c.unifyOr(t, lst(elem), p.Line, patMismatch)
			for _, f := range p.Fields {
				if f.Name == "先頭" {
					c.bindPattern(f.Value, elem, env, p.Line)
				} else {
					c.bindPattern(f.Value, lst(elem), env, p.Line)
				}
			}
			return
		}
		for _, f := range p.Fields {
			c.bindPattern(f.Value, c.fieldOf(t, f.Name, p.Line), env, p.Line)
		}
	case *PSeq:
		elem := newTVar()
		c.unifyOr(t, lst(elem), line, patMismatch)
		for _, q := range p.Items {
			c.bindPattern(q, elem, env, line)
		}
	}
}

// --- 動作 ---

func (c *Checker) monadElem(m, elem Type, env *TEnv) {
	r := prune(m)
	if rv, ok := r.(*TVar); ok && rv.Pure {
		c.unify(elem, rv.C)
		return
	}
	rc, ok := r.(*TCon)
	if !ok {
		return
	}
	if monadTypes[rc.Name] {
		c.unify(elem, rc.Args[0])
		return
	}
	if env == nil {
		return
	}
	for _, tm := range [][2]string{{Monad, BindName}, {Mappable, MapName}} {
		if !c.impls[[2]string{tm[0], rc.Name}][tm[1]] {
			continue
		}
		impl := c.implType(tm[0], rc.Name, tm[1], env)
		if f, ok := impl.(*TFun); ok {
			params := map[string]Type{}
			for _, p := range f.Params {
				params[p.Part] = p.T
			}
			fp, _ := prune(params["で"]).(*TFun)
			if wo, ok := params[WO]; ok && fp != nil && len(fp.Params) > 0 {
				catchMismatch(func() {
					c.unify(wo, rc)
					c.unify(fp.Params[0].T, elem)
				})
			}
		}
		return
	}
}

func (c *Checker) bind(m, elem, k Type, line Pos, message string, env *TEnv) Type {
	out := newTVar()
	c.post(&Constraint{T: m, Line: line, Message: message, Op: "bind", Extra: []Type{elem, k, out}}, env)
	return out
}

func (c *Checker) notMonad(m Type, k *Constraint) {
	c.fail(k.Line, strings.ReplaceAll(k.Message, "{t}", show1(m)))
}

func (c *Checker) onBind(m Type, k *Constraint, env *TEnv) bool {
	elem, kk, out := k.Extra[0], k.Extra[1], k.Extra[2]
	if mv, ok := m.(*TVar); ok && mv.Pure {
		c.unify(elem, mv.C)
		c.unify(out, kk)
		return true
	}
	mc, ok := m.(*TCon)
	if !ok || basicTypes[mc.Name] {
		c.notMonad(m, k)
	}
	if mc.Name == "動作" {
		c.unify(elem, mc.Args[0])
		b := newTVar()
		c.unify(out, act(b))
		c.pending = append(c.pending, &Constraint{T: kk, Line: k.Line, Op: "flatten", Extra: []Type{b}})
		return true
	}
	if mc.Name == "リスト" {
		c.unify(elem, mc.Args[0])
		b := newTVar()
		c.unifyOr(kk, lst(b), k.Line, func(sa, sb string) string {
			return "リストを連鎖するときは、続きもリストを返す必要があります(" + sa + "が返ります)"
		})
		c.unify(out, lst(b))
		return true
	}
	if _, ok := c.impls[[2]string{Monad, mc.Name}]; !ok {
		c.notMonad(m, k)
	}
	impl := c.implType(Monad, mc.Name, BindName, env)
	if impl == nil {
		return false
	}
	c.useImpl(impl, m, elem, kk, out, BindName, k.Line)
	return true
}

func (c *Checker) useImpl(impl Type, m, elem, k, out Type, method string, line Pos) {
	f, ok := impl.(*TFun)
	if !ok {
		return
	}
	params := map[string]Type{}
	for _, p := range f.Params {
		params[p.Part] = p.T
	}
	tname := prune(m).(*TCon).Name
	if wo, ok := params[WO]; ok {
		c.unifyOr(m, wo, line, func(sa, sb string) string {
			return "「" + method + "」(" + tname + "の実装)の「を」には" + sb + "が必要ですが、" + sa + "が渡されています"
		})
	}
	if de, ok := params["で"]; ok {
		c.unifyOr(&TFun{[]TParam{{WO, elem}}, k}, de, line, func(sa, sb string) string {
			return "「" + method + "」(" + tname + "の実装)の「で」には" + sb + "が必要ですが、" + sa + "が渡されています"
		})
	}
	c.unifyOr(out, f.Result, line, func(sa, sb string) string {
		return "「" + method + "」(" + tname + "の実装)の値の型が合いません(" + sa + " と " + sb + ")"
	})
}

func (c *Checker) onItem(t Type, k *Constraint, env *TEnv) bool {
	item := k.Extra[0]
	tc, ok := t.(*TCon)
	if ok && tc.Name == "文字列" {
		c.unifyOr(item, STR, k.Line, func(sa, sb string) string {
			return k.Message + "の要素には" + sb + "が必要ですが、" + sa + "になっています"
		})
	} else if ok && tc.Name == "リスト" {
		c.unifyOr(item, tc.Args[0], k.Line, func(sa, sb string) string {
			return k.Message + "の要素には" + sb + "が必要ですが、" + sa + "になっています"
		})
	} else {
		c.fail(k.Line, k.Message+"の「"+k.Method+"」は文字列かリストです("+show1(t)+"になっています)")
	}
	return true
}

func (c *Checker) onFlatten(kt Type, k *Constraint, env *TEnv) bool {
	b := k.Extra[0]
	if kv, ok := kt.(*TVar); ok && kv.Pure {
		c.unify(b, kv.C)
	} else if kc, ok := kt.(*TCon); ok && kc.Name == "動作" {
		c.unify(b, kc.Args[0])
	} else {
		c.unify(b, kt)
	}
	return true
}

func (c *Checker) onMap(m Type, k *Constraint, env *TEnv) bool {
	elem, r, out := k.Extra[0], k.Extra[1], k.Extra[2]
	if mv, ok := m.(*TVar); ok && mv.Pure {
		c.unify(elem, mv.C)
		c.unify(out, newPureVar(r))
		return true
	}
	if mc, ok := m.(*TCon); ok {
		if monadTypes[mc.Name] {
			c.unify(elem, mc.Args[0])
			c.unify(out, &TCon{mc.Name, []Type{r}})
			return true
		}
		if _, ok := c.impls[[2]string{Mappable, mc.Name}]; ok {
			impl := c.implType(Mappable, mc.Name, MapName, env)
			if impl == nil {
				return false
			}
			c.useImpl(impl, m, elem, r, out, MapName, k.Line)
			return true
		}
		if _, ok := c.impls[[2]string{Monad, mc.Name}]; ok {
			c.pending = append(c.pending, &Constraint{T: m, Line: k.Line, Message: k.Message, Op: "bind", Extra: []Type{elem, newPureVar(r), out}})
			return true
		}
	}
	c.notMonad(m, k)
	return false
}

func (c *Checker) onWrap(v Type, k *Constraint, env *TEnv) bool {
	out := k.Extra[0]
	isM := false
	if vv, ok := v.(*TVar); ok && vv.Pure {
		isM = true
	} else if vc, ok := v.(*TCon); ok {
		_, has := c.impls[[2]string{Monad, vc.Name}]
		isM = monadTypes[vc.Name] || has
	}
	if isM {
		c.unify(out, v)
	} else {
		c.unify(out, newPureVar(v))
	}
	return true
}

func (c *Checker) doType(stmts []Node, i int, env *TEnv, line Pos) Type {
	s := stmts[i]
	for _, r := range collectRuns(s, nil) {
		key := runKey(r)
		if env.lookup(key) != nil {
			continue
		}
		m := c.infer(r.Call, env)
		elem := newTVar()
		c.monadElem(m, elem, env)
		local := newTEnv(env)
		local.set(key, Type(elem))
		k := c.doType(stmts, i, local, line)
		name := ""
		if call, ok := r.Call.(*Call); ok {
			name = call.Name
		}
		name = strings.TrimSuffix(name, Suru)
		return c.bind(m, elem, k, r.Line, "「"+name+"した 結果」: {t}は動作ではありません", env)
	}
	if d, ok := s.(*Define); ok {
		local := c.inferDefs([]*Define{d}, env, nil)
		if i+1 == len(stmts) {
			return newTVar()
		}
		return c.doType(stmts, i+1, local, line)
	}
	v := c.infer(s, env)
	sl := firstLine(s)
	if sl.Line == 0 {
		sl = line
	}
	if i+1 == len(stmts) {
		out := newTVar()
		c.post(&Constraint{T: v, Line: sl, Op: "wrap", Extra: []Type{out}}, env)
		return out
	}
	k := c.doType(stmts, i+1, env, line)
	return c.bind(v, newTVar(), k, sl, "手順の途中の文の値({t})は動作ではありません", env)
}

// --- 入口 ---

// TypeCheck は型を調べる。間違いがあれば *SuruError で panic する
func TypeCheck(program []Node, ctx *ParseContext) {
	if err := typeCheck(program, ctx, false, nil); err != nil {
		panic(err)
	}
}

// typeCheck は型を調べて、最初の間違いを返す。done があれば、最後に使った検査器を渡す
// (型の表示が ts.usual に左右されるので、片付ける前に呼ぶ)
func typeCheck(program []Node, ctx *ParseContext, record bool, done func(*Checker)) *SuruError {
	shapes := newShapes(ctx)
	attempt := func() (*SuruError, *Checker) {
		var checker *Checker
		for n := 0; n < 100; n++ {
			checker = newChecker(ctx, shapes)
			checker.record = record
			restarted := false
			var serr *SuruError
			func() {
				defer func() {
					if r := recover(); r != nil {
						switch x := r.(type) {
						case restart:
							restarted = true
						case *SuruError:
							serr = x
						default:
							panic(r)
						}
					}
				}()
				checker.checkProgram(program)
			}()
			if restarted {
				continue
			}
			return serr, checker
		}
		return nil, checker
	}
	ts.usual = map[string][]Type{}
	first, checker := attempt()
	if first == nil {
		if done != nil {
			done(checker)
		}
		return nil
	}
	if shapes.learnUsual(checker.instances) {
		second, checker2 := attempt()
		if done != nil {
			done(checker2)
		}
		ts.usual = map[string][]Type{}
		if second != nil {
			return second
		}
		return first
	}
	if done != nil {
		done(checker)
	}
	return first
}

var _ = sort.Strings

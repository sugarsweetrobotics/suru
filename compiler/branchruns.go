// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import "reflect"

// 手順の文の「もし」の枝に「した 結果」があれば、そこで手順を分ける(suru.py の split_branch_runs と同じ)

// hasRun は、手順の文として行うところ(条件分岐の枝も含む。無名関数・手順・関数の定義の中は除く)に「した 結果」があるか
func hasRun(node Node) bool {
	switch n := node.(type) {
	case nil:
		return false
	case *Lambda, *Do, *Module, *Import:
		return false
	case *Define:
		return !n.IsFunction && hasRun(n.Body)
	case *Run:
		return true
	}
	for _, ch := range node.Children() {
		if hasRun(ch) {
			return true
		}
	}
	return false
}

// branchIf は文の中の、枝に「した 結果」がある「もし」(*If か *Match。先に行うところから探す)
func branchIf(node Node) Node {
	switch n := node.(type) {
	case nil:
		return nil
	case *Lambda, *Do, *Module, *Import:
		return nil
	case *Define:
		if n.IsFunction {
			return nil
		}
		return branchIf(n.Body)
	case *If:
		if f := branchIf(n.Cond); f != nil {
			return f
		}
		if hasRun(n.Then) || hasRun(n.Other) {
			return n
		}
		return nil
	case *Match:
		if f := branchIf(n.Subject); f != nil {
			return f
		}
		for _, c := range n.Cases {
			if hasRun(c.Body) {
				return n
			}
		}
		if hasRun(n.Default) {
			return n
		}
		return nil
	}
	for _, ch := range node.Children() {
		if f := branchIf(ch); f != nil {
			return f
		}
	}
	return nil
}

var nodeType = reflect.TypeOf((*Node)(nil)).Elem()

// replaceNode は node の中の target を repl にした木(変わったところだけ作り直す)
func replaceNode(node, target, repl Node) Node {
	if node == nil {
		return nil
	}
	if node == target {
		return repl
	}
	switch node.(type) {
	case *Lambda, *Do, *Module, *Import:
		return node
	}
	v := reflect.ValueOf(node)
	if v.Kind() != reflect.Pointer || v.Elem().Kind() != reflect.Struct {
		return node
	}
	nv, changed := replaceValue(v.Elem(), target, repl)
	if !changed {
		return node
	}
	p := reflect.New(v.Elem().Type())
	p.Elem().Set(nv)
	return p.Interface().(Node)
}

func replaceValue(v reflect.Value, target, repl Node) (reflect.Value, bool) {
	switch v.Kind() {
	case reflect.Interface:
		if v.IsNil() || !v.Type().Implements(nodeType) {
			return v, false
		}
		n, ok := v.Interface().(Node)
		if !ok {
			return v, false
		}
		w := replaceNode(n, target, repl)
		if w == n {
			return v, false
		}
		out := reflect.New(v.Type()).Elem()
		out.Set(reflect.ValueOf(w))
		return out, true
	case reflect.Pointer:
		if v.IsNil() || v.Elem().Kind() != reflect.Struct {
			return v, false
		}
		n, ok := v.Interface().(Node)
		if !ok {
			return v, false
		}
		w := replaceNode(n, target, repl)
		if w == n {
			return v, false
		}
		return reflect.ValueOf(w), true
	case reflect.Struct:
		var out reflect.Value
		for i := 0; i < v.NumField(); i++ {
			if !v.Type().Field(i).IsExported() {
				continue
			}
			f, ch := replaceValue(v.Field(i), target, repl)
			if ch {
				if !out.IsValid() {
					out = reflect.New(v.Type()).Elem()
					out.Set(v)
				}
				out.Field(i).Set(f)
			}
		}
		if out.IsValid() {
			return out, true
		}
		return v, false
	case reflect.Slice:
		var out reflect.Value
		for i := 0; i < v.Len(); i++ {
			f, ch := replaceValue(v.Index(i), target, repl)
			if ch {
				if !out.IsValid() {
					out = reflect.MakeSlice(v.Type(), v.Len(), v.Len())
					reflect.Copy(out, v)
				}
				out.Index(i).Set(f)
			}
		}
		if out.IsValid() {
			return out, true
		}
		return v, false
	}
	return v, false
}

// splitBranchRuns: 「…（もし c ならば A そうでなければ B）…」と残りの文を
// 「もし c ならば 手順（…A…、残り） そうでなければ 手順（…B…、残り）」にする。選んだ枝の「した 結果」だけを行う
func splitBranchRuns(node Node) {
	if node == nil {
		return
	}
	if d, ok := node.(*Do); ok {
		for i, s := range d.Statements {
			t := branchIf(s)
			if t == nil {
				continue
			}
			rest := d.Statements[i+1:]
			line := firstLineOf(s)
			if line.Line == 0 {
				line = d.Line
			}
			branch := func(e Node) Node {
				stmts := append([]Node{replaceNode(s, t, e)}, rest...)
				return &Do{Statements: stmts, Line: line, IO: d.IO}
			}
			var split Node
			switch m := t.(type) {
			case *If:
				split = &If{Cond: m.Cond, Then: branch(m.Then), Other: branch(m.Other)}
			case *Match:
				nm := *m
				nm.Cases = make([]Case, len(m.Cases))
				for k, c := range m.Cases {
					nm.Cases[k] = Case{Pat: c.Pat, Guard: c.Guard, Body: branch(c.Body)}
				}
				if m.Default != nil {
					nm.Default = branch(m.Default)
				}
				split = &nm
			}
			d.Statements = append(append([]Node{}, d.Statements[:i]...), split)
			break
		}
	}
	switch node.(type) {
	case *Module, *Import:
		return
	}
	for _, ch := range node.Children() {
		splitBranchRuns(ch)
	}
}

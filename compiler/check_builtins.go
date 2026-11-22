// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

// --- 組み込み関数の型(suru_check.py と同じ) ---

type typer func(c *Checker, a typedArgs, line Pos) Type

type partReq struct {
	part     string
	required bool
}

func checkParts(name string, a typedArgs, allowed []partReq, line Pos, c *Checker) {
	for _, x := range a {
		ok := false
		for _, p := range allowed {
			if p.part == x.part {
				ok = true
			}
		}
		if !ok {
			c.fail(line, "「"+name+"」は「"+x.part+"」の引数を受け取りません")
		}
	}
	for _, p := range allowed {
		if _, has := a.get(p.part); p.required && !has {
			c.fail(line, "「"+name+"」には「"+p.part+"」の引数が必要です")
		}
	}
}

func need(c *Checker, a typedArgs, p string, t Type, line Pos, name string) {
	if at, ok := a.get(p); ok {
		c.arg(at, t, line, name, p)
	}
}

var builtinCalls = map[string]typer{}

func builtin(name string, parts []partReq, fn typer) {
	builtinCalls[name] = func(c *Checker, a typedArgs, line Pos) Type {
		checkParts(name, a, parts, line, c)
		return fn(c, a, line)
	}
}

func req(p string) partReq { return partReq{p, true} }
func opt(p string) partReq { return partReq{p, false} }

func sumTyper(name string) typer {
	return func(c *Checker, a typedArgs, line Pos) Type {
		if _, ok := a.get("に"); ok {
			need(c, a, WO, NUM, line, name)
			need(c, a, "に", NUM, line, name)
			return NUM
		}
		if pc, ok := prune(a.must(WO)).(*TCon); !(ok && pc.Name == "数") {
			need(c, a, WO, lst(NUM), line, name)
		}
		return NUM
	}
}

func consTyper(name string) typer {
	return func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, "に", lst(a.must(WO)), line, name)
		return a.must("に")
	}
}

func init() {
	builtin("表示する", []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type { return act(newTVar()) })
	builtin("入力する", []partReq{opt(WO)}, func(c *Checker, a typedArgs, line Pos) Type { return act(STR) })
	builtin("実行する", []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type {
		r := newTVar()
		need(c, a, WO, lst(act(r)), line, "実行する")
		return act(lst(r))
	})
	builtin("数値にする", []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type {
		c.needKind(a.must(WO), []string{"文字列", "数"}, line, "「数値にする」の「を」は文字列")
		return NUM
	})
	builtin("絶対値にする", []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, NUM, line, "絶対値にする")
		return NUM
	})
	builtin("加算する", []partReq{req(WO), opt("に")}, sumTyper("加算する"))
	builtin("乗算する", []partReq{req(WO), opt("に")}, sumTyper("乗算する"))
	builtin("減算する", []partReq{req("から"), req(WO)}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, "から", NUM, line, "減算する")
		need(c, a, WO, NUM, line, "減算する")
		return NUM
	})
	builtin("除算する", []partReq{req(WO), req("で")}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, NUM, line, "除算する")
		need(c, a, "で", NUM, line, "除算する")
		return NUM
	})
	builtin("追加する", []partReq{req(WO), req("に")}, consTyper("追加する"))
	builtin("挿入する", []partReq{req(WO), req("に")}, consTyper("挿入する"))
	builtin("適用する", []partReq{req(WO), opt("に")}, func(c *Checker, a typedArgs, line Pos) Type {
		var vals []Type
		if ni, ok := a.get("に"); ok {
			vals = []Type{ni}
		}
		return c.apply(a.must(WO), vals, line, "「適用する」の「を」")
	})
	builtin("選別する", []partReq{req("から"), req("で")}, func(c *Checker, a typedArgs, line Pos) Type {
		elem := newTVar()
		need(c, a, "から", lst(elem), line, "選別する")
		r := c.apply(a.must("で"), []Type{elem}, line, "「選別する」の「で」")
		c.expect(r, BOOL, line, "「選別する」の「で」の関数の値")
		return a.must("から")
	})
	builtin("畳み込みする", []partReq{req(WO), req("から"), req("で")}, func(c *Checker, a typedArgs, line Pos) Type {
		elem := newTVar()
		acc := a.must("から")
		need(c, a, WO, lst(elem), line, "畳み込みする")
		f := prune(a.must("で"))
		var r Type
		if ff, ok := f.(*TFun); ok && len(ff.Params) == 1 {
			c.unifyOr(acc, elem, line, func(sa, sb string) string {
				return "「畳み込みする」の初期値(" + sa + ")と要素(" + sb + ")の型が違います"
			})
			r = c.apply(f, []Type{lst(acc)}, line, "「畳み込みする」の「で」")
		} else {
			r = c.apply(f, []Type{acc, elem}, line, "「畳み込みする」の「で」")
		}
		c.unifyOr(r, acc, line, func(sa, sb string) string {
			return "「畳み込みする」の関数の値(" + sa + ")が初期値の型(" + sb + ")と違います"
		})
		return acc
	})
	builtin(MapName, []partReq{req(WO), req("で")}, func(c *Checker, a typedArgs, line Pos) Type {
		elem := newTVar()
		c.monadElem(a.must(WO), elem, c.env)
		r := c.apply(a.must("で"), []Type{elem}, line, "「写像する」の「で」")
		out := newTVar()
		c.post(&Constraint{T: a.must(WO), Line: line, Message: "「写像する」の「を」の{t}は性質「" + Mappable + "」を持っていません",
			Op: "map", Extra: []Type{elem, r, out}}, c.env)
		return out
	})
	builtin(ToString, []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type { return STR })
	builtin(BindName, []partReq{req(WO), req("で")}, func(c *Checker, a typedArgs, line Pos) Type {
		elem := newTVar()
		c.monadElem(a.must(WO), elem, c.env)
		k := c.apply(a.must("で"), []Type{elem}, line, "「連鎖する」の「で」")
		return c.bind(a.must(WO), elem, k, line, "「連鎖する」の「を」の{t}は性質「"+Monad+"」を持っていません", c.env)
	})
	builtin(UnitName, []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type { return newPureVar(a.must(WO)) })

	consFun := func() Type {
		x := newTVar()
		return &TFun{[]TParam{{WO, x}, {"に", lst(x)}}, lst(x)}
	}
	builtinFuns = map[string]func() Type{
		"表示する":   func() Type { return &TFun{[]TParam{{WO, newTVar()}}, act(newTVar())} },
		"入力する":   func() Type { return &TFun{nil, act(STR)} },
		"数値にする":  func() Type { return &TFun{[]TParam{{WO, STR}}, NUM} },
		"絶対値にする": func() Type { return &TFun{[]TParam{{WO, NUM}}, NUM} },
		"加算する":   func() Type { return &TFun{[]TParam{{WO, NUM}, {"に", NUM}}, NUM} },
		"乗算する":   func() Type { return &TFun{[]TParam{{WO, NUM}, {"に", NUM}}, NUM} },
		"減算する":   func() Type { return &TFun{[]TParam{{"から", NUM}, {WO, NUM}}, NUM} },
		"除算する":   func() Type { return &TFun{[]TParam{{WO, NUM}, {"で", NUM}}, NUM} },
		ToString: func() Type { return &TFun{[]TParam{{WO, newTVar()}}, STR} },
		UnitName: func() Type {
			x := newTVar()
			return &TFun{[]TParam{{WO, x}}, newPureVar(x)}
		},
		"追加する": consFun,
		"挿入する": consFun,
	}

	simple := func(name string, params []TParam, result Type) {
		var parts []partReq
		for _, p := range params {
			parts = append(parts, req(p.Part))
		}
		prim(name, parts, func() Type { return &TFun{append([]TParam{}, params...), result} },
			func(c *Checker, a typedArgs, line Pos) Type {
				for _, p := range params {
					need(c, a, p.Part, p.T, line, name)
				}
				return result
			})
	}
	simple("切捨する", []TParam{{WO, NUM}}, NUM)
	simple("平方根にする", []TParam{{WO, NUM}}, NUM)
	simple("範囲にする", []TParam{{"から", NUM}, {WO, NUM}}, lst(NUM))
	simple("文字分解する", []TParam{{WO, STR}}, lst(STR))
	simple("分割する", []TParam{{WO, STR}, {"で", STR}}, lst(STR))
	simple("結合する", []TParam{{WO, lst(STR)}, {"で", STR}}, STR)
	simple("置換する", []TParam{{WO, STR}, {"から", STR}, {"へ", STR}}, STR)
	for _, n := range []string{"大文字にする", "小文字にする", "空白除去する"} {
		simple(n, []TParam{{WO, STR}}, STR)
	}
	for _, n := range []string{"先頭一致である", "末尾一致である"} {
		simple(n, []TParam{{GA, STR}, {"で", STR}}, BOOL)
	}
	simple("バイト数にする", []TParam{{WO, STR}}, NUM)
	simple("文字にする", []TParam{{WO, NUM}}, STR)
	simple("文字コードにする", []TParam{{WO, STR}}, NUM)
	// 通信(「通信」の組み込み)。待受口と接続は番号
	simple("待受開始する", []TParam{{WO, NUM}}, act(NUM))
	simple("接続受付する", []TParam{{"から", NUM}}, act(NUM))
	simple("行受信する", []TParam{{"から", NUM}}, act(STR))
	simple("受信する", []TParam{{"から", NUM}, {WO, NUM}}, act(STR))
	simple("送信する", []TParam{{WO, STR}, {"へ", NUM}}, act(NUM))
	simple("切断する", []TParam{{WO, NUM}}, act(NUM))
	prim("逆順にする", []partReq{req(WO)}, func() Type {
		x := newTVar()
		return &TFun{[]TParam{{WO, x}}, x}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		c.needKind(a.must(WO), []string{"文字列", "リスト"}, line, "「逆順にする」の「を」は文字列かリスト")
		return a.must(WO)
	})
	for _, name := range []string{"先頭取得する", "先頭削除する"} {
		n := name
		prim(n, []partReq{req("から"), req(WO)}, func() Type {
			s := newTVar()
			return &TFun{[]TParam{{"から", s}, {WO, NUM}}, s}
		}, func(c *Checker, a typedArgs, line Pos) Type {
			c.needKind(a.must("から"), []string{"文字列", "リスト"}, line, "「"+n+"」の「から」は文字列かリスト")
			need(c, a, WO, NUM, line, n)
			return a.must("から")
		})
	}
	item := func(c *Checker, seq, it Type, line Pos, name, part string) {
		c.post(&Constraint{T: seq, Line: line, Message: "「" + name + "」", Method: part, Op: "item", Extra: []Type{it}}, c.env)
	}
	prim("番目取得する", []partReq{req("から"), req(WO)}, func() Type {
		e := newTVar()
		return &TFun{[]TParam{{"から", lst(e)}, {WO, NUM}}, e}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, NUM, line, "番目取得する")
		it := newTVar()
		item(c, a.must("から"), it, line, "番目取得する", "から")
		return it
	})
	prim("含有である", []partReq{req(GA), req(WO)}, func() Type {
		e := newTVar()
		return &TFun{[]TParam{{GA, lst(e)}, {WO, e}}, BOOL}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		item(c, a.must(GA), a.must(WO), line, "含有である", "が")
		return BOOL
	})
}

var builtinFuns map[string]func() Type
var primCalls = map[string]typer{}
var primFuns = map[string]func() Type{}
var primNames []string

func prim(name string, parts []partReq, fun func() Type, fn typer) {
	primCalls[name] = func(c *Checker, a typedArgs, line Pos) Type {
		checkParts(name, a, parts, line, c)
		return fn(c, a, line)
	}
	primFuns[name] = fun
	primNames = append(primNames, name)
}

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

// builtinParts は組み込み関数の助詞(エディターの案内に使う)
var builtinParts = map[string][]partReq{}

func builtin(name string, parts []partReq, fn typer) {
	builtinParts[name] = parts
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
	builtin("続表示する", []partReq{req(WO)}, func(c *Checker, a typedArgs, line Pos) Type { return act(newTVar()) })
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
		return &TFun{Params: []TParam{{WO, x}, {"に", lst(x)}}, Result: lst(x)}
	}
	builtinFuns = map[string]func() Type{
		"表示する":   func() Type { return &TFun{Params: []TParam{{WO, newTVar()}}, Result: act(newTVar())} },
		"続表示する":  func() Type { return &TFun{Params: []TParam{{WO, newTVar()}}, Result: act(newTVar())} },
		"入力する":   func() Type { return &TFun{Params: nil, Result: act(STR)} },
		"数値にする":  func() Type { return &TFun{Params: []TParam{{WO, STR}}, Result: NUM} },
		"絶対値にする": func() Type { return &TFun{Params: []TParam{{WO, NUM}}, Result: NUM} },
		"加算する":   func() Type { return &TFun{Params: []TParam{{WO, NUM}, {"に", NUM}}, Result: NUM} },
		"乗算する":   func() Type { return &TFun{Params: []TParam{{WO, NUM}, {"に", NUM}}, Result: NUM} },
		"減算する":   func() Type { return &TFun{Params: []TParam{{"から", NUM}, {WO, NUM}}, Result: NUM} },
		"除算する":   func() Type { return &TFun{Params: []TParam{{WO, NUM}, {"で", NUM}}, Result: NUM} },
		ToString: func() Type { return &TFun{Params: []TParam{{WO, newTVar()}}, Result: STR} },
		UnitName: func() Type {
			x := newTVar()
			return &TFun{Params: []TParam{{WO, x}}, Result: newPureVar(x)}
		},
		"追加する": consFun,
		"挿入する": consFun,
	}

	simple := func(name string, params []TParam, result Type) {
		var parts []partReq
		for _, p := range params {
			parts = append(parts, req(p.Part))
		}
		prim(name, parts, func() Type { return &TFun{Params: append([]TParam{}, params...), Result: result} },
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
	// バイト列と、外部の関数とのやりとり
	addr, bytesT := &TCon{Name: "番地"}, &TCon{Name: "バイト列"}
	simple("バイト列にする", []TParam{{WO, STR}}, bytesT)
	simple("バイト列組立する", []TParam{{WO, lst(NUM)}}, bytesT)
	simple("数列にする", []TParam{{WO, bytesT}}, lst(NUM))
	simple("文字列にする", []TParam{{WO, bytesT}}, STR)
	simple("バイト長にする", []TParam{{WO, bytesT}}, NUM)
	simple("番地にする", []TParam{{WO, NUM}}, addr)
	simple("番地数値にする", []TParam{{WO, addr}}, NUM)
	for _, n := range []string{"ビット積にする", "ビット和にする", "排他的論理和にする", "左シフトする", "右シフトする"} {
		simple(n, []TParam{{WO, NUM}, {"で", NUM}}, NUM)
	}
	simple("バイト列排他和にする", []TParam{{WO, bytesT}, {"で", bytesT}}, bytesT)
	prim("直列化する", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, newTVar()}}, Result: bytesT}
	}, func(c *Checker, a typedArgs, line Pos) Type { return bytesT })
	prim("復元する", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, bytesT}}, Result: newTVar()}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, bytesT, line, "復元する")
		return newTVar()
	})
	prim("固定直列化する", []partReq{req(WO), req("で")}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, x}, {"で", x}}, Result: bytesT}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, x, line, "固定直列化する")
		need(c, a, "で", x, line, "固定直列化する")
		return bytesT
	})
	prim("固定復元する", []partReq{req(WO), req("で")}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, bytesT}, {"で", x}}, Result: x}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, bytesT, line, "固定復元する")
		need(c, a, "で", x, line, "固定復元する")
		return x
	})
	simple("バイト列取得する", []TParam{{"から", addr}, {WO, NUM}}, act(bytesT))
	simple("書込する", []TParam{{WO, bytesT}, {"へ", addr}}, act(NUM))
	simple("エラー番号取得する", nil, act(NUM))
	simple("引数取得する", nil, act(lst(STR)))
	prim("終了する", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, NUM}}, Result: act(newTVar())}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, NUM, line, "終了する")
		return act(newTVar())
	})
	prim("失敗する", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, STR}}, Result: act(newTVar())}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, STR, line, "失敗する")
		return act(newTVar())
	})
	prim("中断する", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, STR}}, Result: newTVar()}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, STR, line, "中断する")
		return newTVar()
	})
	resultT := func(a, e Type) Type { return &TCon{"成否", []Type{a, e}} }
	prim("失敗説明する", []partReq{req(WO), req("で")}, func() Type {
		r := resultT(newTVar(), newTVar())
		return &TFun{Params: []TParam{{WO, r}, {"で", STR}}, Result: r}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		r := resultT(newTVar(), newTVar())
		need(c, a, WO, r, line, "失敗説明する")
		need(c, a, "で", STR, line, "失敗説明する")
		return r
	})
	prim("失敗詳細にする", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, resultT(newTVar(), newTVar())}}, Result: STR}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, resultT(newTVar(), newTVar()), line, "失敗詳細にする")
		return STR
	})
	prim("入力確認する", []partReq{opt(WO)}, func() Type {
		return &TFun{Params: nil, Result: act(&TCon{"有無", []Type{STR}})}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		return act(&TCon{"有無", []Type{STR}})
	})
	prim("数値確認する", []partReq{req(WO)}, func() Type {
		return &TFun{Params: []TParam{{WO, STR}}, Result: resultT(NUM, STR)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, STR, line, "数値確認する")
		return resultT(NUM, STR)
	})
	prim("試算する", []partReq{req(WO)}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, &TFun{Params: nil, Result: x}}}, Result: resultT(x, STR)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		r := newTVar()
		if t, ok := a.get(WO); ok {
			c.unifyOr(t, &TFun{Params: nil, Result: r}, line, func(sa, sb string) string {
				return "「試算する」の「を」には、引数を全部渡した関数の値(「… すること」)が必要ですが、" + sa + "が渡されています"
			})
		}
		return resultT(r, STR)
	})
	prim("試行する", []partReq{req(WO), opt("で")}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, act(x)}, {"で", act(x)}}, Result: act(x)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, act(x), line, "試行する")
		if _, ok := a.get("で"); !ok {
			return act(&TCon{"成否", []Type{x, STR}}) // 「で」を省くと、実行時エラーを失敗(エラーの文)にする
		}
		need(c, a, "で", act(x), line, "試行する")
		return act(x)
	})
	prim("後始末実行する", []partReq{req(WO), req("で")}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, act(x)}, {"で", act(newTVar())}}, Result: act(x)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, act(x), line, "後始末実行する")
		need(c, a, "で", act(newTVar()), line, "後始末実行する")
		return act(x)
	})
	// 通信(「通信」の組み込み)。待受口と接続は番号
	simple("待受開始する", []TParam{{WO, NUM}}, act(NUM))
	simple("接続受付する", []TParam{{"から", NUM}}, act(NUM))
	simple("接続する", []TParam{{"に", STR}, {"で", NUM}}, act(NUM))
	simple("行受信する", []TParam{{"から", NUM}}, act(STR))
	simple("受信する", []TParam{{"から", NUM}, {WO, NUM}}, act(STR))
	simple("バイト列受信する", []TParam{{"から", NUM}, {WO, NUM}}, act(bytesT))
	simple("送信する", []TParam{{WO, STR}, {"へ", NUM}}, act(NUM))
	simple("バイト列送信する", []TParam{{WO, bytesT}, {"へ", NUM}}, act(NUM))
	// スレッド(「スレッド」の組み込み)。並行開始した結果は、合流する(待って結果を返す)動作
	prim("並行開始する", []partReq{req(WO)}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, act(x)}}, Result: act(threadT(x))}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, act(x), line, "並行開始する")
		return act(threadT(x))
	})
	prim("合流する", []partReq{req(WO)}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, threadT(x)}}, Result: act(x)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, threadT(x), line, "合流する")
		return act(x)
	})
	prim("並列写像する", []partReq{req(WO), req("で")}, func() Type {
		x, y := newTVar(), newTVar()
		return &TFun{Params: []TParam{{WO, lst(x)}, {"で", &TFun{Params: []TParam{{WO, x}}, Result: y}}}, Result: lst(y)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		elem := newTVar()
		need(c, a, WO, lst(elem), line, "並列写像する")
		return lst(c.apply(a.must("で"), []Type{elem}, line, "「並列写像する」の「で」"))
	})
	simple("コア数取得する", nil, act(NUM))
	chanPrim := func(name string, params func(x Type) []TParam, result func(x Type) Type) {
		var parts []partReq
		for _, p := range params(newTVar()) {
			parts = append(parts, req(p.Part))
		}
		prim(name, parts, func() Type {
			x := newTVar()
			return &TFun{Params: params(x), Result: result(x)}
		}, func(c *Checker, a typedArgs, line Pos) Type {
			x := newTVar()
			for _, p := range params(x) {
				need(c, a, p.Part, p.T, line, name)
			}
			return result(x)
		})
	}
	chanPrim("通路作成する", func(x Type) []TParam { return []TParam{{"で", NUM}} }, func(x Type) Type { return act(chanT(x)) })
	chanPrim("プロセス間通路作成する", func(x Type) []TParam { return nil }, func(x Type) Type { return act(chanT(x)) })
	chanPrim("名前つき通路作成する", func(x Type) []TParam { return []TParam{{WO, STR}} }, func(x Type) Type { return act(chanT(x)) })
	chanPrim("名前つき通路接続する", func(x Type) []TParam { return []TParam{{WO, STR}} }, func(x Type) Type { return act(chanT(x)) })
	simple("名前つき通路削除する", []TParam{{WO, STR}}, act(NUM))
	chanPrim("通路送信する", func(x Type) []TParam { return []TParam{{WO, x}, {"へ", chanT(x)}} }, func(x Type) Type { return act(x) })
	chanPrim("通路受信する", func(x Type) []TParam { return []TParam{{"から", chanT(x)}} }, func(x Type) Type { return act(x) })
	chanPrim("通路閉鎖する", func(x Type) []TParam { return []TParam{{WO, chanT(x)}} }, func(x Type) Type { return act(chanT(x)) })
	lockT, slotT := &TCon{"ロック", []Type{addr}}, &TCon{"枠", []Type{addr}} // 中身の欄はいつも番地(表示では省かれる)
	boxT := func(t Type) Type { return &TCon{"箱", []Type{t}} }
	simple("ロック作成する", nil, act(lockT))
	simple("枠作成する", []TParam{{"で", NUM}}, act(slotT))
	chanPrim("排他実行する", func(x Type) []TParam { return []TParam{{"で", lockT}, {WO, act(x)}} }, func(x Type) Type { return act(x) })
	chanPrim("枠内実行する", func(x Type) []TParam { return []TParam{{"で", slotT}, {WO, act(x)}} }, func(x Type) Type { return act(x) })
	chanPrim("箱作成する", func(x Type) []TParam { return []TParam{{"で", x}} }, func(x Type) Type { return act(boxT(x)) })
	chanPrim("箱読取する", func(x Type) []TParam { return []TParam{{WO, boxT(x)}} }, func(x Type) Type { return act(x) })
	chanPrim("箱書込する", func(x Type) []TParam { return []TParam{{WO, x}, {"へ", boxT(x)}} }, func(x Type) Type { return act(x) })
	prim("箱更新する", []partReq{req(WO), req("で")}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, boxT(x)}, {"で", &TFun{Params: []TParam{{WO, x}}, Result: x}}}, Result: act(x)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, boxT(x), line, "箱更新する")
		r := c.apply(a.must("で"), []Type{x}, line, "「箱更新する」の「で」")
		c.expect(r, x, line, "「箱更新する」の「で」の関数の値")
		return act(x)
	})
	prim("通路処理する", []partReq{req(WO), req("で")}, func() Type {
		x, y := newTVar(), newTVar()
		return &TFun{Params: []TParam{{WO, chanT(x)}, {"で", &TFun{Params: []TParam{{WO, x}}, Result: act(y)}}}, Result: act(NUM)}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		x := newTVar()
		need(c, a, WO, chanT(x), line, "通路処理する")
		r := c.apply(a.must("で"), []Type{x}, line, "「通路処理する」の「で」")
		c.expect(r, act(newTVar()), line, "「通路処理する」の「で」の関数の値")
		return act(NUM)
	})
	simple("切断する", []TParam{{WO, NUM}}, act(NUM))
	simple("待機時間設定する", []TParam{{WO, NUM}, {"で", NUM}}, act(NUM))
	simple("UDP開始する", []TParam{{WO, NUM}}, act(NUM))
	simple("UDPバイト列送信する", []TParam{{WO, bytesT}, {"から", NUM}, {"に", STR}, {"で", NUM}}, act(NUM))
	simple("UDPバイト列受信する", []TParam{{"から", NUM}}, act(&TCon{"UDP便", []Type{bytesT, STR, NUM}})) // lib/通信.suru の型
	prim("逆順にする", []partReq{req(WO)}, func() Type {
		x := newTVar()
		return &TFun{Params: []TParam{{WO, x}}, Result: x}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		c.needKind(a.must(WO), []string{"文字列", "リスト"}, line, "「逆順にする」の「を」は文字列かリスト")
		return a.must(WO)
	})
	for _, name := range []string{"先頭取得する", "先頭削除する"} {
		n := name
		prim(n, []partReq{req("から"), req(WO)}, func() Type {
			s := newTVar()
			return &TFun{Params: []TParam{{"から", s}, {WO, NUM}}, Result: s}
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
		return &TFun{Params: []TParam{{"から", lst(e)}, {WO, NUM}}, Result: e}
	}, func(c *Checker, a typedArgs, line Pos) Type {
		need(c, a, WO, NUM, line, "番目取得する")
		it := newTVar()
		item(c, a.must("から"), it, line, "番目取得する", "から")
		return it
	})
	prim("含有である", []partReq{req(GA), req(WO)}, func() Type {
		e := newTVar()
		return &TFun{Params: []TParam{{GA, lst(e)}, {WO, e}}, Result: BOOL}
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

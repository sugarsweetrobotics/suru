// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"path/filepath"
	"sort"
	"strings"
)

// --- 定義の登録で見つかる間違い(suru.py の Interpreter.load_program と同じ順で調べる) ---

type builtinInfo struct {
	Name  string
	Parts []string
}

var builtinNames = []string{
	"表示する", "続表示する", "入力する", "実行する", "数値にする", "絶対値にする", "加算する", "乗算する",
	"減算する", "除算する", "追加する", "挿入する", "適用する", "選別する", "畳み込みする",
}

// 標準.suru の中と「標準内の…」でだけ使える組み込み
var stdPrimitives = []builtinInfo{
	{"切捨する", nil}, {"平方根にする", nil}, {"範囲にする", nil}, {"逆順にする", nil},
	{"先頭取得する", nil}, {"先頭削除する", nil}, {"番目取得する", nil}, {"含有である", nil},
	{"文字分解する", nil}, {"分割する", nil}, {"結合する", nil}, {"置換する", nil},
	{"大文字にする", nil}, {"小文字にする", nil}, {"空白除去する", nil},
	{"先頭一致である", nil}, {"末尾一致である", nil},
	{"バイト数にする", nil}, {"文字にする", nil}, {"文字コードにする", nil}, {"試行する", nil}, {"後始末実行する", nil},
	{"バイト列にする", nil}, {"バイト列組立する", nil}, {"数列にする", nil}, {"文字列にする", nil},
	{"バイト長にする", nil}, {"番地にする", nil}, {"番地数値にする", nil}, {"直列化する", nil}, {"復元する", nil}, {"固定直列化する", nil}, {"固定復元する", nil}, {"バイト列取得する", nil},
	{"書込する", nil}, {"エラー番号取得する", nil}, {"失敗する", nil}, {"引数取得する", nil}, {"終了する", nil},
	{"ビット積にする", nil}, {"ビット和にする", nil}, {"排他的論理和にする", nil}, {"左シフトする", nil}, {"右シフトする", nil},
	{"バイト列排他和にする", nil},
}

// 通信.suru の中と「通信内の…」でだけ使える組み込み
var netPrimitives = []builtinInfo{
	{"待受開始する", nil}, {"接続受付する", nil}, {"接続する", nil}, {"行受信する", nil}, {"受信する", nil}, {"バイト列受信する", nil},
	{"送信する", nil}, {"バイト列送信する", nil}, {"切断する", nil}, {"待機時間設定する", nil},
	{"UDP開始する", nil}, {"UDPバイト列送信する", nil}, {"UDPバイト列受信する", nil},
}

// スレッド.suru の中と「スレッド内の…」でだけ使える組み込み
var threadPrimitives = []builtinInfo{
	{"並行開始する", nil}, {"合流する", nil}, {"並列写像する", nil}, {"コア数取得する", nil},
	{"通路作成する", nil}, {"プロセス間通路作成する", nil}, {"名前つき通路作成する", nil}, {"名前つき通路接続する", nil}, {"名前つき通路削除する", nil}, {"通路送信する", nil}, {"通路受信する", nil}, {"通路閉鎖する", nil}, {"通路処理する", nil},
	{"ロック作成する", nil}, {"排他実行する", nil}, {"枠作成する", nil}, {"枠内実行する", nil},
	{"箱作成する", nil}, {"箱読取する", nil}, {"箱更新する", nil}, {"箱書込する", nil},
}

// 基本.suru の中と「基本内の…」(自動で読み込んだときは前置きなしでも)で使える組み込み
var preludePrimitives = []builtinInfo{{"中断する", nil}, {"失敗説明する", nil}, {"失敗詳細にする", nil}, {"数値確認する", nil}, {"入力確認する", nil}, {"試算する", nil}}

// libPrimitives は lib/ のファイルごとの組み込み(suru.py の LIB_PRIMITIVES)
// (同梱のものでも、LibDir(SURU_LIB)のフォルダから読んだものでも)
func libPrimitives(path string) []builtinInfo {
	switch {
	case isLibFile(path, StdPath):
		return stdPrimitives
	case isLibFile(path, NetPath):
		return netPrimitives
	case isLibFile(path, ThreadPath):
		return threadPrimitives
	case isLibFile(path, PreludePath):
		return preludePrimitives
	}
	return nil
}

// isLibFile は path が同梱の lib/ のファイル embedded(StdPath など)か、LibDir の同じ名前のファイルか
func isLibFile(path, embedded string) bool {
	if path == embedded {
		return true
	}
	if LibDir == "" || strings.HasPrefix(path, embeddedLibPrefix) {
		return false
	}
	return absPath(path) == absPath(filepath.Join(LibDir, strings.TrimPrefix(embedded, embeddedLibPrefix)))
}

const (
	Showable = "表示可能"
	ToString = "文字列化する"
	Mappable = "写像可能"
	Monad    = "連鎖可能"
	MapName  = "写像する"
	BindName = "連鎖する"
	UnitName = "結果にする"
)

type traitMethodInfo struct {
	name       string
	parts      []string
	hasDefault bool
}

type loader struct {
	ctx    *ParseContext
	shared map[string]bool
	fixed  map[string]bool
	traits map[string][]traitMethodInfo
	impls  map[[2]string]bool
	loaded map[string]map[string]bool
	order  map[string][]string // env ごとの名前の順(読み込んだファイルの名前を写すため)
}

type env struct {
	vars  map[string]bool
	order []string
}

func newEnv() *env { return &env{vars: map[string]bool{}} }

func (e *env) set(name string) {
	if !e.vars[name] {
		e.order = append(e.order, name)
	}
	e.vars[name] = true
}

func checkDefinitions(program []Node, ctx *ParseContext) {
	l := &loader{ctx: ctx, shared: map[string]bool{}, fixed: map[string]bool{},
		traits: map[string][]traitMethodInfo{}, impls: map[[2]string]bool{}, loaded: map[string]map[string]bool{}}
	for _, b := range builtinNames {
		l.shared[b] = true
	}
	globals := newEnv()
	l.registerTrait(&TraitDecl{Name: Showable, Sigs: []Sig{{ToString, []Param{{Part: WO, Name: "x"}}}}}, globals)
	fparams := []Param{{Part: WO, Name: "m"}, {Part: "で", Name: "f"}}
	l.registerTrait(&TraitDecl{Name: Mappable, Sigs: []Sig{{MapName, fparams}}}, globals)
	l.registerTrait(&TraitDecl{Name: Monad, Sigs: []Sig{{BindName, fparams}, {UnitName, []Param{{Part: WO, Name: "x"}}}}}, globals)
	ms := l.traits[Monad]
	for i := range ms {
		if ms[i].name == UnitName {
			ms[i].hasDefault = true
		}
	}
	l.shared[UnitName] = true
	for _, t := range []string{"リスト", "動作"} {
		l.impls[[2]string{Mappable, t}] = true
		l.impls[[2]string{Monad, t}] = true
	}
	envs := map[string]*env{}
	l.loadProgram(program, globals, envs)
}

func (l *loader) loadProgram(program []Node, e *env, envs map[string]*env) {
	for _, s := range program {
		if imp, ok := s.(*Import); ok {
			mod := l.loadModule(imp.Module, envs)
			for _, name := range mod.order {
				if !containsStr(name, ModuleSep) && !imp.Module.Private[name] {
					e.set(imp.Module.Name + ModuleSep + name)
					if imp.Open {
						e.set(name)
					}
				}
			}
		}
	}
	for _, s := range program {
		if td, ok := s.(*TypeDef); ok {
			for _, c := range td.Ctors {
				if len(c.Fields) == 0 {
					if l.shared[c.Name] {
						raisef(td.Line, "形「%s」は既に別の名前として使われています", c.Name)
					}
					l.shared[c.Name] = true
					l.fixed[c.Name] = true
				}
			}
		}
	}
	for _, s := range program {
		if d, ok := s.(*TraitDecl); ok {
			l.registerTrait(d, e)
		}
	}
	for _, s := range program {
		if d, ok := s.(*TraitImpl); ok {
			l.registerImpl(d)
		}
	}
	for _, s := range program {
		if d, ok := s.(*Define); ok {
			if l.fixed[d.Name] {
				raisef(d.Line, "「%s」は形か性質の関数の名前なので、定義し直せません", d.Name)
			}
			e.set(d.Name)
		}
	}
}

func (l *loader) loadModule(m *Module, envs map[string]*env) *env {
	if e, ok := envs[m.Path]; ok {
		return e
	}
	e := newEnv()
	envs[m.Path] = e
	for _, b := range libPrimitives(m.Path) {
		e.set(b.Name)
	}
	l.loadProgram(m.Program, e, envs)
	return e
}

func (l *loader) registerTrait(decl *TraitDecl, e *env) {
	if _, ok := l.traits[decl.Name]; ok {
		raisef(decl.Line, "性質「%s」は既に定義されています", decl.Name)
	}
	var methods []traitMethodInfo
	has := map[string]bool{}
	add := func(name string, params []Param, deflt bool) {
		if has[name] {
			raisef(decl.Line, "性質「%s」の中で「%s」が2回書かれています", decl.Name, name)
		}
		if l.shared[name] || e.vars[name] {
			raisef(decl.Line, "「%s」は既に使われている名前なので、性質の関数にできません", name)
		}
		has[name] = true
		methods = append(methods, traitMethodInfo{name, paramParts(params), deflt})
	}
	for _, s := range decl.Sigs {
		add(s.Name, s.Params, false)
	}
	for _, d := range decl.Defaults {
		add(d.Name, d.Params, true)
	}
	l.traits[decl.Name] = methods
	for _, m := range methods {
		l.shared[m.name] = true
		l.fixed[m.name] = true
	}
}

func (l *loader) registerImpl(impl *TraitImpl) {
	trait, ok := l.traits[impl.Trait]
	if !ok {
		raisef(impl.Line, "「%s」という性質は定義されていません", impl.Trait)
	}
	if !l.ctx.Types.Has(impl.TypeName) && !builtinTypeSet[impl.TypeName] {
		raisef(impl.Line, "「%s」という型は定義されていません", impl.TypeName)
	}
	key := [2]string{impl.Trait, impl.TypeName}
	if l.impls[key] {
		raisef(impl.Line, "「%s は %s」が2回書かれています", impl.TypeName, impl.Trait)
	}
	fns := map[string]bool{}
	for _, d := range impl.Defs {
		var info *traitMethodInfo
		for i := range trait {
			if trait[i].name == d.Name {
				info = &trait[i]
			}
		}
		if info == nil {
			raisef(d.Line, "「%s」は性質「%s」の関数ではありません", d.Name, impl.Trait)
		}
		if fns[d.Name] {
			raisef(d.Line, "「%s」が2回定義されています", d.Name)
		}
		want := sortedParts(info.parts)
		if !eqStrings(sortedParts(paramParts(d.Params)), want) {
			raisef(d.Line, "「%s」の助詞が性質「%s」での宣言と違います(使う助詞: %s)", d.Name, impl.Trait, joinDot(want))
		}
		fns[d.Name] = true
	}
	for _, m := range trait {
		if !fns[m.name] && !m.hasDefault {
			raisef(impl.Line, "「%s」は性質「%s」の「%s」を定義していません", impl.TypeName, impl.Trait, m.name)
		}
	}
	l.impls[key] = true
}

func joinDot(xs []string) string {
	out := ""
	for i, x := range xs {
		if i > 0 {
			out += "・"
		}
		out += x
	}
	return out
}

func containsStr(s, sub string) bool { return len(sub) > 0 && indexStr(s, sub) >= 0 }

func indexStr(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}

var _ = sort.Strings

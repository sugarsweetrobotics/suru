// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"os"
	"sort"
	"strings"
)

// --- エディター向けの解析(言語サーバーが使う) ---

// Use は名前を使ったところ(Def なら定義したところ)と、そこでの型
type Use struct {
	File string // 読み込んだファイルの絶対パス。本体なら ""
	Pos  Pos
	Name string
	T    Type
	Def  bool
}

func (c *Checker) note(pos Pos, name string, t Type, def bool) {
	if !c.record || pos.Line == 0 || name == Hole {
		return
	}
	c.uses = append(c.uses, Use{c.file, pos, name, t, def})
}

// TypeInfo は本体のファイルの中の、名前とその型の表示
type TypeInfo struct {
	Pos  Pos
	End  int    // 名前の終わりの次の文字目(同じ行)
	Name string // 表示用の名前
	Type string
	Def  bool
}

// Definition は名前を定義したところ(File が "" なら本体)
type Definition struct {
	Name string
	File string
	Pos  Pos
}

// Analysis は Analyze の結果
type Analysis struct {
	Error       *SuruError   // 最初の間違い(なければ nil)
	Errors      []*SuruError // 見つかった間違い全部(型の間違いは、一番外の文ごとに1つまで)
	Types       []TypeInfo   // 位置の順
	Defs        []Definition // 定義の順
	Completions []Completion // 補完の候補
	Words       []Word       // 型・形・性質・フィールドの名前が書かれたところ(色分け用)
	// Starts は行ごとの単語の始まり(何文字目か、昇順)。ホバーの範囲を決めるのに使う
	Starts map[int][]int
}

// Analyze はプログラムを調べて、間違い・名前の型・定義の場所を返す。
// 間違いがあっても、そこまでに分かったことは返す
func Analyze(source, baseDir string) (a *Analysis) {
	a = &Analysis{Starts: map[int][]int{}}
	if lines, err := splitSourceLines(source); err == nil {
		for _, l := range lines {
			for _, t := range l.Tokens {
				if t.Line.Line != 0 && t.Line.Col != 0 {
					a.Starts[t.Line.Line] = append(a.Starts[t.Line.Line], t.Line.Col)
				}
			}
		}
		for k := range a.Starts {
			sort.Ints(a.Starts[k])
		}
	}
	srcLines := SplitLines(source)
	var words []*Token
	if lines, err := splitSourceLines(source); err == nil {
		for _, l := range lines {
			for _, t := range l.Tokens {
				if t.Kind == "WORD" && t.Line.Line != 0 && t.Line.Col != 0 {
					words = append(words, t)
				}
			}
		}
	}
	byPos := map[Pos]TypeInfo{}
	var ctx *ParseContext
	var checker *Checker
	a.Error = try(func() {
		ctx = NewParseContext(baseDir)
		program := ParseProgram(source, ctx)
		a.Defs = collectDefinitions(program, srcLines)
		remember := func(c *Checker) {
			checker = c
			for _, u := range c.uses {
				if u.File != "" {
					continue
				}
				pos := u.Pos
				name := displayName(u.Name)
				if u.Def {
					pos = nameAt(srcLines, pos, name)
				}
				byPos[pos] = TypeInfo{pos, a.spanEnd(srcLines, pos, name), name, show1(u.T), u.Def}
			}
		}
		// 型の間違いが見つかったら、その一番外の文を除いて調べ直し、ほかの間違いも探す
		rest := program
		for round := 0; round < 20; round++ {
			err := typeCheck(rest, ctx, true, remember)
			if err == nil {
				break
			}
			a.Errors = append(a.Errors, err)
			next := withoutStatementAt(rest, err.Line.Line)
			if next == nil {
				break
			}
			rest = next
		}
		if len(a.Errors) == 0 {
			checkDefinitions(program, ctx)
		}
		for _, s := range program {
			if sg, ok := s.(*TypeSig); ok {
				pos := nameAt(srcLines, sg.Line, sg.Name)
				byPos[pos] = TypeInfo{pos, a.spanEnd(srcLines, pos, sg.Name), sg.Name, "", true}
			}
		}
	})
	if a.Error != nil {
		a.Errors = append([]*SuruError{a.Error}, a.Errors...)
	} else if len(a.Errors) > 0 {
		a.Error = a.Errors[0]
	}
	for _, t := range byPos {
		a.Types = append(a.Types, t)
	}
	// 型の宣言の名前には、定義の型を出す
	defType := map[string]string{}
	for _, t := range byPos {
		if t.Def && t.Type != "" {
			defType[t.Name] = t.Type
		}
	}
	for i := range a.Types {
		if a.Types[i].Type == "" {
			a.Types[i].Type = defType[a.Types[i].Name]
		}
	}
	a.collectNames(ctx, checker, words, srcLines)
	sort.Slice(a.Types, func(i, j int) bool {
		x, y := a.Types[i].Pos, a.Types[j].Pos
		return x.Line < y.Line || x.Line == y.Line && x.Col < y.Col
	})
	return a
}

// TypeAt は line 行目 col 文字目(1から)にある名前の型
func (a *Analysis) TypeAt(line, col int) (TypeInfo, bool) {
	var best *TypeInfo
	for i := range a.Types {
		t := &a.Types[i]
		if t.Pos.Line != line || t.Pos.Col > col || t.Pos.Col == 0 {
			continue
		}
		if best == nil || t.Pos.Col >= best.Pos.Col {
			best = t
		}
	}
	if best == nil {
		return TypeInfo{}, false
	}
	if col >= best.End {
		return TypeInfo{}, false
	}
	return *best, true
}

// TokenEnd は line 行目の col 文字目で始まる単語の次の単語の始まり(なければ大きな数)
func (a *Analysis) TokenEnd(line, col int) int {
	for _, s := range a.Starts[line] {
		if s > col {
			return s
		}
	}
	return 1 << 30
}

// DefinitionsOf は名前 name の定義(場合ごとの定義なら全部)
func (a *Analysis) DefinitionsOf(name string) []Definition {
	var out []Definition
	for _, d := range a.Defs {
		if d.Name == name {
			out = append(out, d)
		}
	}
	return out
}

// collectDefinitions は本体と読み込んだファイルの定義(局所定義も)を集める
func collectDefinitions(program []Node, main []string) []Definition {
	var out []Definition
	files := map[string][]string{"": main}
	linesOf := func(file string) []string {
		if ls, ok := files[file]; ok {
			return ls
		}
		b, err := os.ReadFile(file)
		if err != nil {
			files[file] = nil
			return nil
		}
		files[file] = SplitLines(string(b))
		return files[file]
	}
	seen := map[string]bool{}
	var walk func(n Node, file, prefix string)
	walk = func(n Node, file, prefix string) {
		if n == nil {
			return
		}
		switch x := n.(type) {
		case *Define:
			if !strings.HasPrefix(x.Name, "\x00") {
				out = append(out, Definition{prefix + x.Name, file, nameAt(linesOf(file), x.Line, x.Name)})
			}
		case *Import:
			m := x.Module
			if m != nil && !seen[m.Path] {
				seen[m.Path] = true
				for _, s := range m.Program {
					if d, ok := s.(*Define); ok && m.Private[d.Name] {
						continue // 外から見えない名前は、読み込んだ側の定義の一覧に入れない
					}
					walk(s, m.Path, m.Name+ModuleSep)
					if x.Open {
						walk(s, m.Path, "")
					}
				}
			}
			return
		}
		for _, c := range n.Children() {
			walk(c, file, prefix)
		}
	}
	for _, s := range program {
		walk(s, "", "")
	}
	return out
}

// nameAt は定義の行(pos から)で、名前 name が書かれている位置を探す。
// 「…する」は「して」などの形でも書けるので、語幹で探す。見つからなければ pos のまま
func nameAt(lines []string, pos Pos, name string) Pos {
	if pos.Line < 1 || pos.Line > len(lines) {
		return pos
	}
	stem := name
	for _, form := range []string{Dearu, Suru} {
		if strings.HasSuffix(stem, form) && len(stem) > len(form) {
			stem = stem[:len(stem)-len(form)]
			break
		}
	}
	rs := []rune(lines[pos.Line-1])
	from := pos.Col - 1
	if from < 0 {
		from = 0
	}
	if from > len(rs) {
		return pos
	}
	i := strings.Index(string(rs[from:]), stem)
	if i < 0 {
		return pos
	}
	return Pos{pos.Line, from + len([]rune(string(rs[from:])[:i])) + 1}
}

var spanForms = []string{"しましてから", Dearukoto, Shitekara, "しまして", Koto, "します", Dearu, Denai, Shite, Shita, Suru}

// spanEnd は pos から書かれている名前 name の終わり(次の文字目)。
// 「…する」は「して」「します」などの形で書かれていても、その形の終わりまで。分からなければ次の単語の始まりまで
func (a *Analysis) spanEnd(lines []string, pos Pos, name string) int {
	fallback := a.TokenEnd(pos.Line, pos.Col)
	if pos.Line < 1 || pos.Line > len(lines) || pos.Col < 1 {
		return fallback
	}
	rs := []rune(lines[pos.Line-1])
	if pos.Col-1 >= len(rs) {
		return fallback
	}
	text := string(rs[pos.Col-1:])
	quoted := strings.HasPrefix(text, NameOpen)
	if quoted {
		text = strings.TrimPrefix(text, NameOpen)
	}
	stem := name
	for _, form := range []string{Dearu, Suru} {
		if strings.HasSuffix(stem, form) && len(stem) > len(form) {
			stem = stem[:len(stem)-len(form)]
			break
		}
	}
	if !strings.HasPrefix(text, stem) {
		return fallback
	}
	n := len([]rune(stem))
	rest := text[len(stem):]
	if strings.HasPrefix(rest, NameClose) {
		n++
		rest = rest[len(NameClose):]
	}
	if stem != name {
		for _, f := range spanForms {
			if strings.HasPrefix(rest, f) {
				n += len([]rune(f))
				break
			}
		}
	}
	if quoted {
		n++
	}
	return pos.Col + n
}

// withoutStatementAt は line 行目を含む一番外の文を除いたプログラム。除けない文なら nil
func withoutStatementAt(program []Node, line int) []Node {
	if line == 0 {
		return nil
	}
	idx := -1
	for i, s := range program {
		if l := firstLine(s); l.Line != 0 && l.Line <= line {
			idx = i
		}
	}
	if idx < 0 {
		return nil
	}
	var name string
	switch x := program[idx].(type) {
	case *Define:
		name = x.Name
	case *TypeSig:
		name = x.Name
	case nil:
		return nil
	default:
		if isTopLevelOnly(x) {
			return nil // 型や性質の定義・読み込みを除くと、ほかに間違いが出てしまう
		}
	}
	var out []Node
	for i, s := range program {
		if i == idx {
			continue
		}
		// 関数を除くなら、その型の宣言も除く(宣言だけが残ると間違いになる)
		if sg, ok := s.(*TypeSig); ok && name != "" && sg.Name == name {
			continue
		}
		if d, ok := s.(*Define); ok && name != "" && d.Name == name {
			continue
		}
		out = append(out, s)
	}
	return out
}

// Completion は補完の候補
type Completion struct {
	Label  string
	Kind   string // function / value / variable / builtin / type / ctor / field / trait / keyword
	Detail string // 型など
}

// Word は型・形・性質・フィールドの名前が書かれたところ
type Word struct {
	Pos  Pos
	Len  int    // 文字の数(『』を含む)
	Kind string // type / ctor / trait / field
}

var completionKeywords = []string{KwTowa, KwIf, KwThen, KwElse, KwProviso, KwSorekara, KwKatsu, KwMataha,
	KwLambda, KwReturn, KwEmpty, Tejun, Result, "真", "偽", KwKumi, KwSeishitsu, KwToiu,
	KwImport, KwImportTe + " " + KwUse, "先頭", "残り", "最後", "長さ", "それぞれ"}

func (a *Analysis) collectNames(ctx *ParseContext, c *Checker, words []*Token, lines []string) {
	seen := map[string]bool{}
	add := func(label, kind, detail string) {
		if label == "" || strings.HasPrefix(label, "\x00") || seen[label] {
			return
		}
		seen[label] = true
		a.Completions = append(a.Completions, Completion{label, kind, detail})
	}
	defType := map[string]string{}
	for _, t := range a.Types {
		if t.Def && t.Type != "" {
			defType[t.Name] = t.Type
		}
	}
	for _, d := range a.Defs {
		kind := "value"
		if strings.HasSuffix(d.Name, Suru) || strings.HasSuffix(d.Name, Dearu) {
			kind = "function"
		}
		add(d.Name, kind, defType[d.Name])
	}
	for _, t := range a.Types {
		if !t.Def && !strings.HasSuffix(t.Name, Suru) && !strings.HasSuffix(t.Name, Dearu) {
			add(t.Name, "variable", t.Type)
		}
	}
	types := map[string]string{}
	for _, t := range builtinTypes {
		types[t] = "type"
	}
	if ctx != nil {
		for _, t := range ctx.Types.keys {
			types[t] = "type"
		}
		for _, k := range ctx.Ctors.keys {
			info, _ := ctx.Ctors.Get(k)
			types[k] = "ctor"
			add(k, "ctor", info.Type)
			for _, f := range info.Fields {
				if _, ok := types[f]; !ok {
					types[f] = "field"
				}
				add(f, "field", info.Type)
			}
		}
	}
	if c != nil {
		for t := range c.traits {
			types[t] = "trait"
		}
		for m, t := range c.methodTrait {
			add(m, "builtin", "性質「"+t+"」")
		}
	}
	for _, t := range []string{Mappable, Monad, Showable} {
		types[t] = "trait"
	}
	for t, k := range types {
		if k != "field" && k != "ctor" {
			add(t, k, "")
		}
	}
	names := make([]string, 0, len(builtinCalls))
	for n := range builtinCalls {
		names = append(names, n)
	}
	sort.Strings(names)
	for _, n := range names {
		add(n, "builtin", "組み込み")
	}
	for _, k := range completionKeywords {
		add(k, "keyword", "")
	}
	// 色分け: 値や関数として定義した名前は除く(「リスト とは …」の リスト は変数)
	defined := map[string]bool{}
	for _, d := range a.Defs {
		defined[d.Name] = true
	}
	for _, t := range a.Types {
		if !t.Def && types[t.Name] == "" {
			defined[t.Name] = true
		}
	}
	for _, w := range words {
		kind, ok := types[w.S]
		if !ok || defined[w.S] && kind == "type" {
			continue
		}
		n := len([]rune(w.S))
		pos := w.Line
		if w.Quoted {
			n += 2
			// 『 の位置を指していなければ(句読点の書き方)、1つ前が 『
			if pos.Line <= len(lines) {
				rs := []rune(lines[pos.Line-1])
				if pos.Col-1 < len(rs) && rs[pos.Col-1] != '『' {
					pos.Col--
				}
			}
		}
		a.Words = append(a.Words, Word{pos, n, kind})
	}
}

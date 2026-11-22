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
	Error *SuruError   // 最初の間違い(なければ nil)
	Types []TypeInfo   // 位置の順
	Defs  []Definition // 定義の順
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
	a.Error = try(func() {
		ctx := NewParseContext(baseDir)
		program := ParseProgram(source, ctx)
		a.Defs = collectDefinitions(program, srcLines)
		err := typeCheck(program, ctx, true, func(c *Checker) {
			for _, u := range c.uses {
				if u.File != "" {
					continue
				}
				pos := u.Pos
				if u.Def {
					pos = nameAt(srcLines, pos, displayName(u.Name))
				}
				name := displayName(u.Name)
				a.Types = append(a.Types, TypeInfo{pos, a.spanEnd(srcLines, pos, name), name, show1(u.T), u.Def})
			}
		})
		if err != nil {
			panic(err)
		}
		checkDefinitions(program, ctx)
	})
	sort.SliceStable(a.Types, func(i, j int) bool {
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

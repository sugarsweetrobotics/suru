// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"sort"
	"strings"
	"unicode"

	"github.com/sugarsweetrobotics/suru/compiler"
)

// --- 補完 ---

func isHira(r rune) bool { return r >= 'ぁ' && r <= 'ゟ' }

func isNameRune(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsDigit(r) || r == '_' || r == '『'
}

var completionKinds = map[string]int{
	"function": 3, "builtin": 3, "value": 6, "variable": 6, "type": 7, "ctor": 20, "field": 5, "trait": 8, "keyword": 14,
}

// completionStart は補完で置き換える部分の始まり(何文字目か、0から)。
// 句読点の書き方では「nを三倍」のように前の単語とくっついているので、助詞(ひらがな)の後ろから始まるところを候補にして、
// 候補の名前に一番長く合うところを選ぶ
func completionStart(rs []rune, cur int, items []compiler.Completion) int {
	run := cur
	for run > 0 && isNameRune(rs[run-1]) {
		run--
	}
	var starts []int
	for i := run; i < cur; i++ {
		if rs[i] == '『' || !isHira(rs[i]) && (i == run || isHira(rs[i-1]) || rs[i-1] == '』') {
			starts = append(starts, i)
		}
	}
	for _, st := range starts {
		prefix := strings.TrimPrefix(string(rs[st:cur]), "『")
		for _, it := range items {
			if strings.HasPrefix(it.Label, prefix) {
				return st
			}
		}
	}
	if len(starts) > 0 && !isHira(rs[cur-1]) {
		return starts[len(starts)-1]
	}
	return cur
}

func hasHiragana(s string) bool {
	for _, r := range s {
		if isHira(r) {
			return true
		}
	}
	return false
}

func (s *server) complete(p textDocumentPosition) any {
	d := s.docs[p.TextDocument.URI]
	if d == nil {
		return []any{}
	}
	line, col := fromUTF16(d.lines, p.Position)
	rs := []rune(lineText(d.lines, line))
	cur := col - 1
	if cur > len(rs) {
		cur = len(rs)
	}
	// 打っている途中の単語そのもの(まだ定義していない変数として読まれている)は候補にしない
	typing := map[string]bool{}
	for _, t := range d.analysis.Types {
		if t.Pos.Line == line && !t.Def && t.Pos.Col <= cur+1 && cur+1 <= t.End {
			typing[t.Name] = true
		}
	}
	var cands []compiler.Completion
	for _, c := range d.completions {
		if !(c.Kind == "variable" && typing[c.Label]) {
			cands = append(cands, c)
		}
	}
	start := completionStart(rs, cur, cands)
	r := rng{toUTF16(d.lines, line, start+1), toUTF16(d.lines, line, cur+1)}
	typed := string(rs[start:cur])
	items := []map[string]any{}
	for i, c := range cands {
		insert := c.Label
		// ひらがなを含む値の名前は『』で囲む(関数名はそのまま書ける)
		if c.Kind != "keyword" && c.Kind != "function" && c.Kind != "builtin" && hasHiragana(c.Label) && !strings.Contains(c.Label, compiler.ModuleSep) {
			insert = "『" + c.Label + "』"
		}
		item := map[string]any{
			"label":      c.Label,
			"kind":       completionKinds[c.Kind],
			"filterText": c.Label,
			"sortText":   sortKey(c.Kind, i),
			"textEdit":   map[string]any{"range": r, "newText": insert},
		}
		if strings.HasPrefix(typed, "『") {
			item["filterText"] = "『" + c.Label
		}
		if c.Detail != "" {
			item["detail"] = c.Detail
		}
		items = append(items, item)
	}
	return map[string]any{"isIncomplete": false, "items": items}
}

func sortKey(kind string, i int) string {
	order := map[string]string{"variable": "0", "value": "1", "function": "1", "ctor": "2", "field": "2", "builtin": "3", "type": "4", "trait": "4", "keyword": "5"}
	return order[kind] + strings.Repeat("0", 6-len(itoa(i))) + itoa(i)
}

func itoa(i int) string {
	if i == 0 {
		return "0"
	}
	var b []byte
	for i > 0 {
		b = append([]byte{byte('0' + i%10)}, b...)
		i /= 10
	}
	return string(b)
}

// --- 色分け(セマンティックトークン): 型・形・性質・フィールドの名前 ---

var semanticTypes = []string{"type", "enumMember", "interface", "property"}

var semanticIndex = map[string]int{"type": 0, "ctor": 1, "trait": 2, "field": 3}

func (s *server) semanticTokens(uri string) any {
	d := s.docs[uri]
	if d == nil {
		return map[string]any{"data": []int{}}
	}
	words := append([]compiler.Word{}, d.analysis.Words...)
	sort.Slice(words, func(i, j int) bool {
		a, b := words[i].Pos, words[j].Pos
		return a.Line < b.Line || a.Line == b.Line && a.Col < b.Col
	})
	data := []int{}
	prevLine, prevChar := 0, 0
	for _, w := range words {
		start := toUTF16(d.lines, w.Pos.Line, w.Pos.Col)
		end := toUTF16(d.lines, w.Pos.Line, w.Pos.Col+w.Len)
		if start.Line != prevLine {
			prevChar = 0
		}
		data = append(data, start.Line-prevLine, start.Character-prevChar, end.Character-start.Character, semanticIndex[w.Kind], 0)
		prevLine, prevChar = start.Line, start.Character
	}
	return map[string]any{"data": data}
}

// --- 名前の変更 ---

func trimForm(name string) (stem, form string) {
	for _, f := range []string{"である", "する"} {
		if strings.HasSuffix(name, f) && len(name) > len(f) {
			return name[:len(name)-len(f)], f
		}
	}
	return name, ""
}

// renameTarget はカーソルの名前と、このファイルで定義されているか
func (s *server) renameTarget(p textDocumentPosition) (*document, compiler.TypeInfo, string) {
	d := s.docs[p.TextDocument.URI]
	if d == nil {
		return nil, compiler.TypeInfo{}, "ファイルが開かれていません"
	}
	line, col := fromUTF16(d.lines, p.Position)
	t, ok := d.analysis.TypeAt(line, col)
	if !ok {
		return nil, t, "ここには変えられる名前がありません"
	}
	local := 0
	for _, def := range d.analysis.DefinitionsOf(t.Name) {
		if def.File != "" {
			return nil, t, "「" + t.Name + "」は読み込んだファイルで定義されているので、ここでは変えられません"
		}
		local++
	}
	if local == 0 {
		return nil, t, "「" + t.Name + "」はこのファイルで定義した名前ではないので変えられません(引数の名前は、まだ変えられません)"
	}
	if strings.Contains(t.Name, compiler.ModuleSep) {
		return nil, t, "読み込んだファイルの名前は変えられません"
	}
	return d, t, ""
}

func (s *server) prepareRename(p textDocumentPosition) (any, string) {
	d, t, err := s.renameTarget(p)
	if err != "" {
		return nil, err
	}
	stem, _ := trimForm(t.Name)
	start, end, ok := stemSpan(d.lines, t.Pos, stem)
	if !ok {
		return nil, "名前の位置が分かりません"
	}
	return map[string]any{"range": rng{toUTF16(d.lines, t.Pos.Line, start), toUTF16(d.lines, t.Pos.Line, end)}, "placeholder": stem + func() string { _, f := trimForm(t.Name); return f }()}, ""
}

// stemSpan は pos から書かれている語幹 stem の範囲(『』の中)。何文字目か(1から)
func stemSpan(lines []string, pos compiler.Pos, stem string) (int, int, bool) {
	rs := []rune(lineText(lines, pos.Line))
	i := pos.Col - 1
	if i >= 0 && i < len(rs) && rs[i] == '『' {
		i++
	}
	if i < 0 || i > len(rs) || !strings.HasPrefix(string(rs[i:]), stem) {
		return 0, 0, false
	}
	return i + 1, i + 1 + len([]rune(stem)), true
}

func quotedAt(lines []string, line, start, end int) bool {
	rs := []rune(lineText(lines, line))
	return start >= 2 && rs[start-2] == '『' && end-1 < len(rs) && rs[end-1] == '』'
}

func (s *server) rename(p textDocumentPosition, newName string) (any, string) {
	d, t, err := s.renameTarget(p)
	if err != "" {
		return nil, err
	}
	newName = strings.TrimSpace(strings.TrimSuffix(strings.TrimPrefix(strings.TrimSpace(newName), "『"), "』"))
	oldStem, oldForm := trimForm(t.Name)
	newStem, newForm := trimForm(newName)
	if oldForm != "" && newForm == "" {
		// 語幹だけ書いたなら、同じ形を付ける
		newStem, newForm = newName, oldForm
	}
	switch {
	case newStem == "":
		return nil, "新しい名前が空です"
	case newForm != oldForm:
		if oldForm == "" {
			return nil, "値の名前を「" + newForm + "」で終わる名前には変えられません"
		}
		return nil, "「" + oldForm + "」で終わる名前に変えてください"
	case !strings.ContainsFunc(newStem, func(r rune) bool { return !isHira(r) }):
		return nil, "ひらがなだけの名前は使えません"
	case strings.ContainsAny(newStem, " 　、。「」『』（）()・#＃※"):
		return nil, "名前に使えない文字が入っています"
	}
	var edits []map[string]any
	seen := map[compiler.Pos]bool{}
	for _, u := range d.analysis.Types {
		if u.Name != t.Name || seen[u.Pos] {
			continue
		}
		seen[u.Pos] = true
		start, end, ok := stemSpan(d.lines, u.Pos, oldStem)
		if !ok {
			continue
		}
		text := newStem
		if hasHiragana(newStem) && !quotedAt(d.lines, u.Pos.Line, start, end) {
			text = "『" + newStem + "』"
		}
		edits = append(edits, map[string]any{
			"range":   rng{toUTF16(d.lines, u.Pos.Line, start), toUTF16(d.lines, u.Pos.Line, end)},
			"newText": text,
		})
	}
	return map[string]any{"changes": map[string]any{d.uri: edits}}, ""
}

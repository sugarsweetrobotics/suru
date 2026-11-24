// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"math"
	"math/big"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	"golang.org/x/text/unicode/norm"
)

// --- 字句解析(suru.py の「字句解析」と同じ) ---

const (
	KwTo          = "と"
	KwTowa        = "とは"
	KwNo          = "の"
	KwGa          = "が"
	KwIf          = "もし"
	KwThen        = "ならば"
	KwElse        = "そうでなければ"
	KwLambda      = "受け取って"
	KwReturn      = "返すこと"
	KwEmpty       = "空"
	KwProviso     = "ただし"
	KwKa          = "か"
	KwWa          = "は"
	KwToiu        = "という"
	KwKumi        = "組"
	KwSeishitsu   = "性質"
	KwSorekara    = "それから"
	KwKatsu       = "かつ"
	KwMataha      = "または"
	Desu          = "です"
	ModuleMark    = "内"
	ModuleSep     = ModuleMark + "の"
	KwImport      = "読み込む"
	KwImportPolit = "読み込みます"
	KwImportTe    = "読み込んで"
	KwUse         = "使う"
	KwUsePolite   = "使います"
	SourceSuffix  = ".suru"

	WO        = "を"
	GA        = "が"
	Period    = "。"
	Comma     = "、"
	NameOpen  = "『"
	NameClose = "』"

	Suru      = "する"
	Shite     = "して"
	Koto      = "すること"
	Shitekara = "してから"
	Shita     = "した"
	Dearu     = "である"
	Denai     = "でない"
	Dearukoto = "であること"

	Result = "結果"
	// Content は「安全除算した 中身」: 成功(有)なら中の値、失敗(無)ならその失敗を返す(Rust の ?)
	Content = "中身"
	Tejun   = "手順"
	TejunIO = "入出力手順" // 動作(IO)だけの手順。型の検査で値が動作かを確かめる
	Hole    = "\x00前の結果"
)

// 関数の型の宣言の終わりの飾り: 「数 を 階乗する は 数 を 返す」の「を 返す」は読み捨てる
const (
	KwHensu       = "返す"
	KwHensuPolite = "返します"
)

var operators = map[string]string{
	"+": "+", "-": "-", "−": "-", "*": "*", "×": "*", "/": "/", "÷": "/",
	"%": "%", "^": "^", "**": "^",
	"==": "==", "=": "==", "!=": "!=", "≠": "!=",
	"<": "<", ">": ">", "<=": "<=", "≦": "<=", "≤": "<=", ">=": ">=", "≧": ">=", "≥": ">=",
}

var keywords = setOf(
	KwTo, KwTowa, KwNo, KwGa, KwIf, KwThen, KwElse, KwLambda, KwReturn, KwProviso,
	KwKa, KwWa, KwToiu, KwKumi, KwSeishitsu, KwSorekara, KwKatsu, KwMataha, Desu, KwHensu, KwHensuPolite,
	KwImport, KwImportPolit, KwImportTe, KwUse, KwUsePolite,
)
var kanjiKeywords = setOf(KwKumi, KwSeishitsu)
var continuationKeywords = setOf(KwThen, KwElse)
var particles = []string{"より", "から", "を", "に", "で", "へ"}
var particleSet = setOf(particles...)

var politeForms = map[string]string{"します": Suru, "しまして": Shite, "しましてから": Shitekara}

var properties = setOf("先頭", "残り", "最後", "長さ", "それぞれ")

func setOf(xs ...string) map[string]bool {
	m := make(map[string]bool, len(xs))
	for _, x := range xs {
		m[x] = true
	}
	return m
}

// Token の種類: NUM STR OP LP RP WORD KW PART CALL PERIOD SEP
type Token struct {
	Kind    string
	S       string // NUM 以外の値
	N       NumVal // NUM の値
	Line    Pos
	Form    string // CALL のとき する / して / すること など
	Quoted  bool
	Negated bool
	// Qualified は読み込んだファイルの型か形の名前に、そのファイルの前置きを付けたもの(「部品内の点」)
	Qualified bool
}

// Value は Python の str(tok.value) にあたる表示
func (t *Token) Value() string {
	if t.Kind == "NUM" {
		return t.N.String()
	}
	return t.S
}

func isHiragana(c rune) bool { return c >= 'ぁ' && c <= 'ゟ' }

func isAllHiragana(w string) bool {
	if w == "" {
		return false
	}
	for _, c := range w {
		if !isHiragana(c) {
			return false
		}
	}
	return true
}

func hiraganaFunctionError(stem string, line Pos) *SuruError {
	return errAt(line, "「"+stem+"する」のように、ひらがなだけの関数名は使えません。"+
		"「する」の前に漢字かカタカナを入れてください(例:「"+stem+"」→「変換」「ヘンカン」)")
}

func hiraganaNameError(name string, line Pos) *SuruError {
	return errAt(line, "ひらがなだけの名前「"+name+"」は使えません(助詞と区別できないため)。"+
		"漢字かカタカナを使うか、"+NameOpen+name+NameClose+" のように"+NameOpen+NameClose+"で囲んでください")
}

func callToken(stem, form string, line Pos) *Token {
	if form == Dearu || form == Denai {
		return &Token{Kind: "CALL", S: stem + Dearu, Line: line, Form: Suru, Negated: form == Denai}
	}
	if form == Dearukoto {
		return &Token{Kind: "CALL", S: stem + Dearu, Line: line, Form: Koto}
	}
	f := form
	if p, ok := politeForms[form]; ok {
		f = p
	}
	return &Token{Kind: "CALL", S: stem + Suru, Line: line, Form: f}
}

func isPredicate(name string) bool { return strings.HasSuffix(name, Dearu) }

var classifyForms = []string{Dearukoto, Dearu, Denai, Koto, Suru, "しましてから", Shitekara, "しまして", Shite, "します", Shita}

func classifyCall(word string, line Pos) (*Token, error) {
	for _, form := range classifyForms {
		if strings.HasSuffix(word, form) && len(word) > len(form) {
			stem := word[:len(word)-len(form)]
			if isAllHiragana(stem) {
				return nil, hiraganaFunctionError(stem, line)
			}
			return callToken(stem, form, line), nil
		}
	}
	return nil, nil
}

func nfkc(s string) string { return norm.NFKC.String(s) }

// --- Python の int() / float() ---

func isPySpace(r rune) bool {
	switch r {
	case ' ', '\t', '\n', '\r', '\v', '\f', '\x1c', '\x1d', '\x1e', '\x1f', '\u0085':
		return true
	}
	return unicode.Is(unicode.Zs, r) || r == ' ' || r == ' '
}

func pyStrip(s string) string { return strings.TrimFunc(s, isPySpace) }

// 10進の数字(Python の int() は Unicode の数字も受け付ける)
func decDigit(r rune) (int, bool) {
	if r >= '0' && r <= '9' {
		return int(r - '0'), true
	}
	if unicode.Is(unicode.Nd, r) {
		// Nd の数字は 0 から 9 の連続した並び
		base := r
		for base > 0 && unicode.Is(unicode.Nd, base-1) {
			base--
		}
		return int(r-base) % 10, true
	}
	return 0, false
}

// digitPart は「数字 (_? 数字)*」を読んで ASCII の数字にする
func digitPart(rs []rune) (string, bool) {
	if len(rs) == 0 {
		return "", false
	}
	var b strings.Builder
	prevUnderscore := true
	for i, r := range rs {
		if r == '_' {
			if prevUnderscore || i == len(rs)-1 {
				return "", false
			}
			prevUnderscore = true
			continue
		}
		d, ok := decDigit(r)
		if !ok {
			return "", false
		}
		b.WriteByte(byte('0' + d))
		prevUnderscore = false
	}
	return b.String(), true
}

func pyInt(s string) (*big.Int, bool) {
	rs := []rune(pyStrip(s))
	neg := false
	if len(rs) > 0 && (rs[0] == '+' || rs[0] == '-') {
		neg = rs[0] == '-'
		rs = rs[1:]
	}
	d, ok := digitPart(rs)
	if !ok {
		return nil, false
	}
	v, _ := new(big.Int).SetString(d, 10)
	if neg {
		v.Neg(v)
	}
	return v, true
}

func pyFloat(s string) (float64, bool) {
	rs := []rune(pyStrip(s))
	sign := ""
	if len(rs) > 0 && (rs[0] == '+' || rs[0] == '-') {
		if rs[0] == '-' {
			sign = "-"
		}
		rs = rs[1:]
	}
	low := strings.ToLower(string(rs))
	switch low {
	case "inf", "infinity":
		if sign == "-" {
			return math.Inf(-1), true
		}
		return math.Inf(1), true
	case "nan":
		if sign == "-" {
			return math.Copysign(math.NaN(), -1), true
		}
		return math.NaN(), true
	}
	// 仮数部と指数部
	mant, exp := rs, []rune(nil)
	for i, r := range rs {
		if r == 'e' || r == 'E' {
			mant, exp = rs[:i], rs[i+1:]
			if len(exp) == 0 {
				return 0, false
			}
			break
		}
	}
	intPart, fracPart := mant, []rune(nil)
	hasDot := false
	for i, r := range mant {
		if r == '.' {
			intPart, fracPart = mant[:i], mant[i+1:]
			hasDot = true
			break
		}
	}
	var ip, fp string
	var ok bool
	if len(intPart) > 0 {
		if ip, ok = digitPart(intPart); !ok {
			return 0, false
		}
	}
	if len(fracPart) > 0 {
		if fp, ok = digitPart(fracPart); !ok {
			return 0, false
		}
	}
	if ip == "" && fp == "" {
		return 0, false
	}
	str := sign + ip
	if ip == "" {
		str += "0"
	}
	if hasDot {
		str += "." + fp
		if fp == "" {
			str += "0"
		}
	}
	if exp != nil {
		es := ""
		if exp[0] == '+' || exp[0] == '-' {
			es = string(exp[0])
			exp = exp[1:]
		}
		ed, ok := digitPart(exp)
		if !ok {
			return 0, false
		}
		str += "e" + es + ed
	}
	f, err := strconv.ParseFloat(str, 64)
	if err != nil {
		if ne, ok2 := err.(*strconv.NumError); ok2 && ne.Err == strconv.ErrRange {
			return f, true
		}
		return 0, false
	}
	return f, true
}

func numInt(v *big.Int) NumVal            { return NumVal{Kind: NInt, I: v} }
func numFloat(f float64) NumVal           { return NumVal{Kind: NFloat, F: f} }
func numBool(b bool) NumVal               { return NumVal{Kind: NBool, B: b} }
func numEmpty() NumVal                    { return NumVal{Kind: NEmpty} }
func tok(kind, s string, line Pos) *Token { return &Token{Kind: kind, S: s, Line: line} }

func classify(word string, line Pos, quoted bool) ([]*Token, error) {
	if quoted {
		call, err := classifyCall(word, line)
		if err != nil {
			return nil, err
		}
		if call != nil {
			return []*Token{call}, nil
		}
		return []*Token{{Kind: "WORD", S: word, Line: line, Quoted: true}}, nil
	}
	n := nfkc(word)
	if op, ok := operators[n]; ok {
		return []*Token{tok("OP", op, line)}, nil
	}
	if op, ok := operators[word]; ok {
		return []*Token{tok("OP", op, line)}, nil
	}
	if v, ok := pyInt(n); ok {
		return []*Token{{Kind: "NUM", N: numInt(v), Line: line}}, nil
	}
	if f, ok := pyFloat(n); ok {
		return []*Token{{Kind: "NUM", N: numFloat(f), Line: line}}, nil
	}
	if particleSet[word] {
		return []*Token{tok("PART", word, line)}, nil
	}
	if keywords[word] {
		return []*Token{tok("KW", word, line)}, nil
	}
	if strings.HasSuffix(word, Desu) && len(word) > len(Desu) {
		rest, err := classify(word[:len(word)-len(Desu)], line, false)
		if err != nil {
			return nil, err
		}
		return append(rest, tok("KW", Desu, line)), nil
	}
	if word == "真" || word == "偽" {
		return []*Token{{Kind: "NUM", N: numBool(word == "真"), Line: line}}, nil
	}
	if word == KwEmpty {
		return []*Token{{Kind: "NUM", N: numEmpty(), Line: line}}, nil
	}
	for _, p := range particles {
		if strings.HasPrefix(word, p) {
			rest := word[len(p):]
			if rest != "" {
				r0, _ := utf8.DecodeRuneInString(rest)
				if !isHiragana(r0) {
					if rest == KwReturn || rest == KwHensu || rest == KwHensuPolite {
						return []*Token{tok("PART", p, line), tok("KW", rest, line)}, nil
					}
					call, err := classifyCall(rest, line)
					if err != nil {
						return nil, err
					}
					if call != nil {
						return []*Token{tok("PART", p, line), call}, nil
					}
				}
			}
		}
	}
	call, err := classifyCall(word, line)
	if err != nil {
		return nil, err
	}
	if call != nil {
		return []*Token{call}, nil
	}
	return []*Token{tok("WORD", word, line)}, nil
}

func isSpace(c rune) bool   { return c == ' ' || c == '　' || c == '\t' }
func isComment(c rune) bool { return c == '#' || c == '＃' || c == '※' }
func isOpen(c rune) bool    { return c == '(' || c == '（' }
func isClose(c rune) bool   { return c == ')' || c == '）' }
func indentWidth(c rune) int {
	switch c {
	case ' ':
		return 1
	case '　':
		return 2
	case '\t':
		return 4
	}
	return 0
}

func findRune(rs []rune, c rune, from int) int {
	for j := from; j < len(rs); j++ {
		if rs[j] == c {
			return j
		}
	}
	return -1
}

// findStringClose は rs[i] の「に対応する」の位置(なければ -1)。文字列の中の「」は入れ子として数える
// (「失敗: 「abc」は数にできません」は1つの文字列)
func findStringClose(rs []rune, i int) int {
	depth := 0
	for j := i; j < len(rs); j++ {
		switch rs[j] {
		case '「':
			depth++
		case '」':
			depth--
			if depth == 0 {
				return j
			}
		}
	}
	return -1
}

func reservedError(here Pos) *SuruError {
	return errAt(here, "中黒「・」は将来の書き方のために予約されています(文字列の中では使えます)")
}

func tokenizeLine(text string, line int) ([]*Token, error) {
	var tokens []*Token
	rs := []rune(text)
	n := len(rs)
	var buf []rune
	start := 0
	quoted := false
	flush := func() error {
		if len(buf) > 0 {
			ts, err := classify(string(buf), Pos{line, start + 1, curPosFile}, quoted)
			if err != nil {
				return err
			}
			tokens = append(tokens, ts...)
			buf = buf[:0]
		}
		quoted = false
		return nil
	}
	for i := 0; i < n; i++ {
		c := rs[i]
		here := Pos{line, i + 1, curPosFile}
		if len(buf) == 0 && !isSpace(c) {
			start = i
		}
		switch {
		case isSpace(c):
			if err := flush(); err != nil {
				return nil, err
			}
		case isComment(c) && len(buf) == 0:
			i = n
			continue
		case c == '「':
			if err := flush(); err != nil {
				return nil, err
			}
			j := findStringClose(rs, i)
			if j < 0 {
				return nil, errAt(here, "文字列の「に対応する」がありません")
			}
			tokens = append(tokens, tok("STR", string(rs[i+1:j]), here))
			i = j
		case c == '『':
			j, err := findNameClose(rs, i, here)
			if err != nil {
				return nil, err
			}
			buf = append(buf, rs[i+1:j]...)
			quoted = true
			i = j
		case isOpen(c):
			if err := flush(); err != nil {
				return nil, err
			}
			tokens = append(tokens, tok("LP", "(", here))
		case isClose(c):
			if err := flush(); err != nil {
				return nil, err
			}
			tokens = append(tokens, tok("RP", ")", here))
		case c == '・':
			return nil, reservedError(here)
		default:
			buf = append(buf, c)
		}
	}
	if err := flush(); err != nil {
		return nil, err
	}
	return dropDesu(tokens)
}

func joinModuleNames(tokens []*Token, modules map[string]bool) ([]*Token, error) {
	var out []*Token
	i := 0
	for i < len(tokens) {
		t := tokens[i]
		var nxt, name *Token
		if i+1 < len(tokens) {
			nxt = tokens[i+1]
		}
		if i+2 < len(tokens) {
			name = tokens[i+2]
		}
		if t.Kind == "WORD" && strings.HasSuffix(t.S, ModuleMark) && modules[strings.TrimSuffix(t.S, ModuleMark)] &&
			nxt != nil && nxt.Kind == "KW" && nxt.S == KwNo {
			if name == nil || (name.Kind != "WORD" && name.Kind != "CALL") {
				return nil, errAt(t.Line, "「"+t.S+"の」の後には、読み込んだファイルの中の名前を書いてください")
			}
			out = append(out, &Token{Kind: name.Kind, S: t.S + "の" + name.S, Line: t.Line, Form: name.Form, Quoted: name.Quoted, Negated: name.Negated})
			i += 3
			continue
		}
		if t.Kind == "WORD" && strings.HasSuffix(t.S, ModuleSep) && modules[strings.TrimSuffix(t.S, ModuleSep)] &&
			nxt != nil && (nxt.Kind == "WORD" || nxt.Kind == "CALL") {
			out = append(out, &Token{Kind: nxt.Kind, S: t.S + nxt.S, Line: t.Line, Form: nxt.Form, Quoted: nxt.Quoted, Negated: nxt.Negated})
			i += 2
			continue
		}
		out = append(out, t)
		i++
	}
	return out, nil
}

func dropDesu(tokens []*Token) ([]*Token, error) {
	var out []*Token
	for i, t := range tokens {
		if t.Kind == "KW" && t.S == Desu {
			var nxt *Token
			if i+1 < len(tokens) {
				nxt = tokens[i+1]
			}
			if nxt == nil || nxt.Kind == "PERIOD" || nxt.Kind == "SEP" || nxt.Kind == "RP" || isKw(nxt, KwElse) {
				continue
			}
			return nil, errAt(t.Line, "「です」は文の終わり(「。」の前)にだけ書けます")
		}
		out = append(out, t)
	}
	return out, nil
}

func findNameClose(rs []rune, i int, line Pos) (int, error) {
	j := findRune(rs, '』', i+1)
	if j < 0 {
		return 0, errAt(line, "名前の『に対応する』がありません")
	}
	if j == i+1 {
		return 0, errAt(line, "『』の中に名前がありません")
	}
	return j, nil
}

// --- 句読点の書き方 ---

var operatorChars = func() map[rune]bool {
	m := map[rune]bool{}
	for op := range operators {
		for _, c := range nfkc(op) {
			m[c] = true
		}
		if utf8.RuneCountInString(op) == 1 {
			r, _ := utf8.DecodeRuneInString(op)
			m[r] = true
		}
	}
	return m
}()

var mixedWords = []string{"受け取って", "返すこと", KwHensuPolite, KwHensu, "長さ", "残り", KwImportPolit, KwImport, KwImportTe, KwUsePolite, KwUse}
var mixedNames = []string{"畳み込み"}
var mixedAll = append(append([]string{}, mixedWords...), mixedNames...)
var mixedNameSet = setOf(mixedNames...)

var hiraganaWords = func() [][]rune {
	set := setOf(particles...)
	for _, w := range []string{KwTo, KwTowa, KwNo, KwGa, KwIf, KwThen, KwElse, KwProviso, KwKa, KwWa, KwToiu, KwSorekara, KwKatsu, KwMataha,
		"それぞれ", Koto, Suru, Shitekara, Shite, Shita, Dearukoto, Dearu, Denai, Desu} {
		set[w] = true
	}
	for w := range politeForms {
		set[w] = true
	}
	var ws []string
	for w := range set {
		ws = append(ws, w)
	}
	sort.Slice(ws, func(i, j int) bool {
		li, lj := utf8.RuneCountInString(ws[i]), utf8.RuneCountInString(ws[j])
		if li != lj {
			return li > lj
		}
		return ws[i] < ws[j]
	})
	out := make([][]rune, len(ws))
	for i, w := range ws {
		out[i] = []rune(w)
	}
	return out
}()

var callForms = []string{Koto, Suru, Shitekara, Shite, Shita, Dearukoto, Dearu, Denai, "します", "しまして", "しましてから"}
var callFormSet = setOf(callForms...)

func nfkcRune(c rune) rune {
	n := []rune(nfkc(string(c)))
	if len(n) == 1 {
		return n[0]
	}
	return c
}

func charClass(c rune) string {
	if isHiragana(c) {
		return "HIRA"
	}
	n := nfkcRune(c)
	if n >= '0' && n <= '9' {
		return "DIGIT"
	}
	if operatorChars[c] || operatorChars[n] {
		return "OP"
	}
	if unicode.IsLetter(n) || n == '_' {
		return "NAME"
	}
	return "OTHER"
}

func hasPrefixRunes(rs []rune, i int, w []rune) bool {
	if i+len(w) > len(rs) {
		return false
	}
	for k, c := range w {
		if rs[i+k] != c {
			return false
		}
	}
	return true
}

func mixedWordAt(rs []rune, i int) string {
	for _, w := range mixedAll {
		if hasPrefixRunes(rs, i, []rune(w)) {
			return w
		}
	}
	return ""
}

func splitOperators(text string, line Pos) ([]*Token, error) {
	n := []rune(nfkc(text))
	var out []*Token
	i := 0
	for i < len(n) {
		found := false
		for _, size := range []int{2, 1} {
			if i+size <= len(n) {
				op := string(n[i : i+size])
				if v, ok := operators[op]; ok {
					out = append(out, tok("OP", v, line))
					i += size
					found = true
					break
				}
			}
		}
		if !found {
			return nil, errAt(line, "演算子「"+string(n[i:])+"」が分かりません")
		}
	}
	return out, nil
}

func decompose(text []rune) []string {
	if len(text) == 0 {
		return []string{}
	}
	for _, w := range hiraganaWords {
		if hasPrefixRunes(text, 0, w) {
			rest := decompose(text[len(w):])
			if rest != nil {
				return append([]string{string(w)}, rest...)
			}
		}
	}
	return nil
}

func hasAnyPrefix(s string, ps ...string) bool {
	for _, p := range ps {
		if strings.HasPrefix(s, p) {
			return true
		}
	}
	return false
}

func splitHiragana(text string, line Pos, afterName, afterValue bool) ([]string, error) {
	rs := []rune(text)
	if words := decompose(rs); words != nil {
		return words, nil
	}
	start := 0
	if afterValue {
		for _, w := range hiraganaWords {
			if hasPrefixRunes(rs, 0, w) && !callFormSet[string(w)] {
				start = len(w)
				break
			}
		}
	}
	var ends []int
	for e := start + 1; e <= len(rs); e++ {
		if decompose(rs[e:]) != nil {
			ends = append(ends, e)
		}
	}
	end := ends[0]
	for _, e := range ends {
		if !hasAnyPrefix(string(rs[e:]), KwKa, KwWa, KwToiu) {
			end = e
			break
		}
	}
	unknown, rest := string(rs[start:end]), string(rs[end:])
	if afterName && start == 0 {
		return nil, errAt(line, "名前にひらがな「"+unknown+"」が混ざっています。ひらがなを含む名前は "+
			NameOpen+"割った数に"+NameClose+"する のように"+NameOpen+NameClose+"で囲んでください")
	}
	if hasAnyPrefix(rest, callForms...) {
		return nil, hiraganaFunctionError(unknown, line)
	}
	return nil, hiraganaNameError(unknown, line)
}

func hiraganaWordToken(w string, line Pos) (*Token, error) {
	if particleSet[w] {
		return tok("PART", w, line), nil
	}
	if keywords[w] {
		return tok("KW", w, line), nil
	}
	if w == "それぞれ" {
		return tok("WORD", w, line), nil
	}
	return nil, errAt(line, "「"+w+"」の前に関数名(漢字かカタカナ)が必要です")
}

type piece struct {
	text   string
	quoted bool
	col    int
}

func isASCIIRune(c rune) bool { return c < 0x80 }

func segmentRun(pieces []piece, line Pos) ([]*Token, error) {
	type part struct{ cls, text string }
	var parts []part
	var cols []int
	for _, pc := range pieces {
		if pc.quoted {
			parts = append(parts, part{"QNAME", pc.text})
			cols = append(cols, pc.col)
			continue
		}
		rs := []rune(pc.text)
		i := 0
		for i < len(rs) {
			mixed := mixedWordAt(rs, i)
			cols = append(cols, pc.col+i)
			if mixed != "" {
				cls := "MIXED"
				if mixedNameSet[mixed] {
					cls = "NAME"
				}
				parts = append(parts, part{cls, mixed})
				i += utf8.RuneCountInString(mixed)
				continue
			}
			cls := charClass(rs[i])
			if cls == "OTHER" {
				return nil, errAt(Pos{line.Line, pc.col + i, curPosFile}, "「"+string(rs[i])+"」は使えない文字です")
			}
			j := i + 1
			switch cls {
			case "NAME":
				for j < len(rs) && mixedWordAt(rs, j) == "" {
					k := charClass(rs[j])
					if k == "NAME" || (k == "DIGIT" && isASCIIRune(nfkcRune(rs[j-1]))) {
						j++
					} else {
						break
					}
				}
			case "DIGIT":
				for j < len(rs) && (charClass(rs[j]) == "DIGIT" ||
					(nfkcRune(rs[j]) == '.' && j+1 < len(rs) && charClass(rs[j+1]) == "DIGIT")) {
					j++
				}
			default:
				for j < len(rs) && charClass(rs[j]) == cls && mixedWordAt(rs, j) == "" {
					j++
				}
			}
			parts = append(parts, part{cls, string(rs[i:j])})
			i = j
		}
	}

	var tokens []*Token
	for idx, p := range parts {
		here := Pos{line.Line, cols[idx], curPosFile}
		switch p.cls {
		case "NAME", "QNAME":
			switch {
			case p.cls == "NAME" && (p.text == "真" || p.text == "偽"):
				tokens = append(tokens, &Token{Kind: "NUM", N: numBool(p.text == "真"), Line: here})
			case p.cls == "NAME" && p.text == KwEmpty:
				tokens = append(tokens, &Token{Kind: "NUM", N: numEmpty(), Line: here})
			case p.cls == "NAME" && kanjiKeywords[p.text]:
				tokens = append(tokens, tok("KW", p.text, here))
			default:
				tokens = append(tokens, &Token{Kind: "WORD", S: p.text, Line: here, Quoted: p.cls == "QNAME"})
			}
		case "MIXED":
			kind := "WORD"
			if keywords[p.text] {
				kind = "KW"
			}
			tokens = append(tokens, tok(kind, p.text, here))
		case "DIGIT":
			n := nfkc(p.text)
			if strings.Contains(n, ".") {
				f, _ := pyFloat(n)
				tokens = append(tokens, &Token{Kind: "NUM", N: numFloat(f), Line: here})
			} else {
				v, _ := pyInt(n)
				tokens = append(tokens, &Token{Kind: "NUM", N: numInt(v), Line: here})
			}
		case "OP":
			ts, err := splitOperators(p.text, here)
			if err != nil {
				return nil, err
			}
			tokens = append(tokens, ts...)
		default: // HIRA
			afterName := idx > 0 && (parts[idx-1].cls == "NAME" || parts[idx-1].cls == "QNAME")
			words, err := splitHiragana(p.text, here, afterName, idx > 0)
			if err != nil {
				return nil, err
			}
			k := -1
			for n, w := range words {
				if callFormSet[w] {
					k = n
					break
				}
			}
			if k >= 0 {
				stem := strings.Join(words[:k], "")
				if !afterName {
					if stem != "" {
						return nil, hiraganaFunctionError(stem, here)
					}
					return nil, errAt(here, "「"+words[k]+"」の前に関数名(漢字かカタカナ)が必要です")
				}
				nameTok := tokens[len(tokens)-1]
				tokens = tokens[:len(tokens)-1]
				if isAllHiragana(nameTok.Value() + stem) {
					return nil, hiraganaFunctionError(nameTok.Value()+stem, here)
				}
				tokens = append(tokens, callToken(nameTok.Value()+stem, words[k], nameTok.Line))
				words = words[k+1:]
			}
			for _, w := range words {
				if callFormSet[w] {
					return nil, errAt(here, "「"+w+"」の前に関数名(漢字かカタカナ)が必要です")
				}
				t, err := hiraganaWordToken(w, here)
				if err != nil {
					return nil, err
				}
				tokens = append(tokens, t)
			}
		}
	}
	return tokens, nil
}

func tokenizePunctLine(text string, line int) ([]*Token, error) {
	var tokens []*Token
	var run []piece
	var buf []rune
	start := 0
	rs := []rune(text)
	n := len(rs)
	var here Pos
	flush := func() error {
		if len(buf) > 0 {
			run = append(run, piece{string(buf), false, start + 1})
			buf = buf[:0]
		}
		if len(run) > 0 {
			ts, err := segmentRun(run, here)
			if err != nil {
				return err
			}
			tokens = append(tokens, ts...)
			run = run[:0]
		}
		return nil
	}
	for i := 0; i < n; i++ {
		c := rs[i]
		here = Pos{line, i + 1, curPosFile}
		if len(buf) == 0 && !isSpace(c) && c != '『' {
			start = i
		}
		switch {
		case isSpace(c):
			if err := flush(); err != nil {
				return nil, err
			}
		case c == '、':
			if err := flush(); err != nil {
				return nil, err
			}
			tokens = append(tokens, tok("SEP", Comma, here))
		case isComment(c) && len(buf) == 0 && len(run) == 0:
			i = n
			continue
		case c == '「':
			if err := flush(); err != nil {
				return nil, err
			}
			j := findStringClose(rs, i)
			if j < 0 {
				return nil, errAt(here, "文字列の「に対応する」がありません")
			}
			tokens = append(tokens, tok("STR", string(rs[i+1:j]), here))
			i = j
		case c == '『':
			j, err := findNameClose(rs, i, here)
			if err != nil {
				return nil, err
			}
			if len(buf) > 0 {
				run = append(run, piece{string(buf), false, start + 1})
				buf = buf[:0]
			}
			run = append(run, piece{string(rs[i+1 : j]), true, i + 1})
			i = j
		case isOpen(c):
			if err := flush(); err != nil {
				return nil, err
			}
			tokens = append(tokens, tok("LP", "(", here))
		case isClose(c):
			if err := flush(); err != nil {
				return nil, err
			}
			tokens = append(tokens, tok("RP", ")", here))
		case c == '。':
			if err := flush(); err != nil {
				return nil, err
			}
			tokens = append(tokens, tok("PERIOD", Period, here))
		case c == '・':
			return nil, reservedError(here)
		default:
			buf = append(buf, c)
		}
	}
	if err := flush(); err != nil {
		return nil, err
	}
	return tokens, nil
}

func isPunctLine(text string) bool {
	rs := []rune(text)
	n := len(rs)
	atTokenStart := true
	for i := 0; i < n; i++ {
		c := rs[i]
		if c == '「' || c == '『' {
			j := findStringClose(rs, i)
			if c == '『' {
				j = findRune(rs, '』', i+1)
			}
			if j < 0 {
				return false
			}
			i = j
		} else if isComment(c) && atTokenStart {
			return false
		} else if c == '。' || c == '、' {
			return true
		}
		atTokenStart = isSpace(c) || isOpen(c) || isClose(c)
	}
	return false
}

// Line は1行(句読点の書き方では1文)
type Line struct {
	Indent int
	Tokens []*Token
	Number Pos
	Closed bool
}

func depthZeroPeriods(tokens []*Token) []int {
	depth := 0
	var out []int
	for i, t := range tokens {
		switch {
		case t.Kind == "LP":
			depth++
		case t.Kind == "RP":
			depth--
		case t.Kind == "PERIOD" && depth <= 0:
			out = append(out, i)
		}
	}
	return out
}

func splitSentences(tokens []*Token) [][]*Token {
	var out [][]*Token
	start := 0
	for _, i := range depthZeroPeriods(tokens) {
		if i > start {
			out = append(out, tokens[start:i])
		}
		start = i + 1
	}
	return out
}

func stripSeps(tokens []*Token) []*Token {
	i, j := 0, len(tokens)
	for i < j && tokens[i].Kind == "SEP" {
		i++
	}
	for j > i && tokens[j-1].Kind == "SEP" {
		j--
	}
	return tokens[i:j]
}

func nosep(tokens []*Token) []*Token {
	out := make([]*Token, 0, len(tokens))
	for _, t := range tokens {
		if t.Kind != "SEP" {
			out = append(out, t)
		}
	}
	return out
}

func pyRStrip(s string) string { return strings.TrimRightFunc(s, isPySpace) }

func opensPunct(raws []string, k int) bool {
	text := pyRStrip(strings.SplitN(raws[k], "#", 2)[0])
	if text == "" {
		return false
	}
	rs := []rune(text)
	if !isOpen(rs[len(rs)-1]) {
		return false
	}
	for _, r := range raws[k+1:] {
		if strings.TrimFunc(r, isPySpace) != "" {
			return isPunctLine(r)
		}
	}
	return false
}

func splitSourceLines(source string) ([]*Line, error) {
	var lines []*Line
	raws := SplitLines(source)
	k := 0
	for k < len(raws) {
		raw, number := raws[k], k+1
		indent := 0
		for _, c := range raw {
			w := indentWidth(c)
			if w == 0 {
				break
			}
			indent += w
		}
		if !isPunctLine(raw) && !opensPunct(raws, k) {
			tokens, err := tokenizeLine(raw, number)
			if err != nil {
				return nil, err
			}
			if len(tokens) > 0 {
				lines = append(lines, &Line{Indent: indent, Tokens: tokens, Number: Pos{number, 0, curPosFile}})
			}
			k++
			continue
		}
		tokens, err := tokenizePunctLine(raw, number)
		if err != nil {
			return nil, err
		}
		for {
			ends := depthZeroPeriods(tokens)
			if len(tokens) == 0 || (len(ends) > 0 && ends[len(ends)-1] == len(tokens)-1) {
				break
			}
			k++
			if k >= len(raws) {
				first := tokens[0]
				if len(ends) > 0 {
					first = tokens[ends[len(ends)-1]+1]
				}
				return nil, errAt(first.Line, "文の終わりに「。」が必要です(句読点の書き方では文を「。」で終えます)")
			}
			more, err := tokenizePunctLine(raws[k], k+1)
			if err != nil {
				return nil, err
			}
			tokens = append(tokens, more...)
		}
		dd, err := dropDesu(tokens)
		if err != nil {
			return nil, err
		}
		for _, sentence := range splitSentences(dd) {
			sentence = stripSeps(sentence)
			if len(sentence) > 0 {
				lines = append(lines, &Line{Indent: indent, Tokens: sentence, Number: sentence[0].Line, Closed: true})
			}
		}
		k++
	}
	return lines, nil
}

// curPosFile は読み込んだファイルを解析している間、そのファイルの道(字句の Pos.File に入れる)
var curPosFile string

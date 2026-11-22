// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package compiler は「する」のコンパイラ(字句解析・構文解析・型検査・LLVM IR の生成)。
// Python 版(suru.py / suru_check.py / suru_compile.py)と同じ結果になるように書いている。
package compiler

import (
	"fmt"
	"math"
	"math/big"
	"strconv"
	"strings"

	"golang.org/x/text/width"
)

// Pos は行番号と何文字目か。Col が 0 なら「何文字目か」は分からない。Line が 0 なら位置なし。
type Pos struct {
	Line int
	Col  int
}

func (p Pos) IsZero() bool { return p.Line == 0 }

func where(p Pos) string {
	if p.Col != 0 {
		return fmt.Sprintf("%d行目 %d文字目", p.Line, p.Col)
	}
	return fmt.Sprintf("%d行目", p.Line)
}

// SuruError は「する」の構文・型のエラー
type SuruError struct {
	Message string
	Line    Pos
}

func (e *SuruError) Error() string {
	if e.Line.Line != 0 {
		return where(e.Line) + ": " + e.Message
	}
	return e.Message
}

func errAt(line Pos, format string, args ...any) *SuruError {
	if len(args) == 0 {
		return &SuruError{Message: format, Line: line}
	}
	return &SuruError{Message: fmt.Sprintf(format, args...), Line: line}
}

func displayWidth(s string) int {
	n := 0
	for _, r := range s {
		k := width.LookupRune(r).Kind()
		if k == width.EastAsianWide || k == width.EastAsianFullwidth {
			n += 2
		} else {
			n++
		}
	}
	return n
}

// SplitLines は Python の str.splitlines と同じに行に分ける
func SplitLines(s string) []string {
	var out []string
	var b strings.Builder
	rs := []rune(s)
	for i := 0; i < len(rs); i++ {
		c := rs[i]
		switch c {
		case '\n', '\v', '\f', '\x1c', '\x1d', '\x1e', '\u0085', ' ', ' ':
			out = append(out, b.String())
			b.Reset()
		case '\r':
			if i+1 < len(rs) && rs[i+1] == '\n' {
				i++
			}
			out = append(out, b.String())
			b.Reset()
		default:
			b.WriteRune(c)
		}
	}
	if b.Len() > 0 {
		out = append(out, b.String())
	}
	return out
}

// FormatError はエラーの文と、分かれば該当する行と位置の印(^)を返す
func FormatError(e *SuruError, source string, haveSource bool) string {
	out := "エラー: " + e.Error()
	var lines []string
	if haveSource {
		lines = SplitLines(source)
	}
	if e.Line.Line > 0 && e.Line.Line <= len(lines) {
		raw := lines[e.Line.Line-1]
		out += "\n  " + strings.ReplaceAll(raw, "\t", "    ")
		if e.Col() != 0 {
			rs := []rune(raw)
			k := e.Col() - 1
			if k > len(rs) {
				k = len(rs)
			}
			pre := strings.ReplaceAll(string(rs[:k]), "\t", "    ")
			out += "\n  " + strings.Repeat(" ", displayWidth(pre)) + "^"
		}
	}
	return out
}

func (e *SuruError) Col() int { return e.Line.Col }

// NormalizeNewlines は Python のテキストモードの読み込みと同じに改行をそろえる
func NormalizeNewlines(s string) string {
	s = strings.ReplaceAll(s, "\r\n", "\n")
	return strings.ReplaceAll(s, "\r", "\n")
}

// --- Python の数の表示 ---

// pyFloatRepr は Python の repr(float) と同じ文字列
func pyFloatRepr(f float64) string {
	if math.IsInf(f, 1) {
		return "inf"
	}
	if math.IsInf(f, -1) {
		return "-inf"
	}
	if math.IsNaN(f) {
		return "nan"
	}
	s := strconv.FormatFloat(f, 'e', -1, 64) // d.ddde±XX
	neg := false
	if s[0] == '-' {
		neg = true
		s = s[1:]
	}
	mant, expS, _ := strings.Cut(s, "e")
	exp, _ := strconv.Atoi(expS)
	digits := strings.Replace(mant, ".", "", 1)
	var r string
	if exp < -4 || exp >= 16 {
		m := digits[:1]
		if len(digits) > 1 {
			m += "." + digits[1:]
		}
		sign := "+"
		if exp < 0 {
			sign = "-"
			exp = -exp
		}
		r = fmt.Sprintf("%se%s%02d", m, sign, exp)
	} else if exp < 0 {
		r = "0." + strings.Repeat("0", -exp-1) + digits
	} else {
		if len(digits) <= exp+1 {
			r = digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
		} else {
			r = digits[:exp+1] + "." + digits[exp+1:]
		}
	}
	if neg {
		r = "-" + r
	}
	return r
}

// NumKind は数のトークンの値の種類(Python の int / float / bool / ())
type NumKind int

const (
	NInt NumKind = iota
	NFloat
	NBool
	NEmpty
)

// NumVal は数のトークンの値
type NumVal struct {
	Kind NumKind
	I    *big.Int
	F    float64
	B    bool
}

func (v NumVal) String() string {
	switch v.Kind {
	case NInt:
		return v.I.String()
	case NFloat:
		return pyFloatRepr(v.F)
	case NBool:
		if v.B {
			return "True"
		}
		return "False"
	}
	return "()"
}

func (v NumVal) Neg() NumVal {
	switch v.Kind {
	case NInt:
		return NumVal{Kind: NInt, I: new(big.Int).Neg(v.I)}
	case NFloat:
		return NumVal{Kind: NFloat, F: -v.F}
	case NBool:
		if v.B {
			return NumVal{Kind: NInt, I: big.NewInt(-1)}
		}
		return NumVal{Kind: NInt, I: big.NewInt(0)}
	}
	return v
}

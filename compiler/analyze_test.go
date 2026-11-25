// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"os"
	"path/filepath"
	"testing"
)

func TestMain(m *testing.M) {
	LibDir = "../lib"
	os.Exit(m.Run())
}

// examples/ と lib/ は間違いなく解析でき、名前の型が分かる
func TestAnalyzeExamples(t *testing.T) {
	files, _ := filepath.Glob("../examples/*.suru")
	libs, _ := filepath.Glob("../lib/*.suru")
	for _, f := range append(files, libs...) {
		b, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		a := AnalyzeFile(string(b), filepath.Dir(f), f)
		if a.Error != nil {
			t.Errorf("%s: %v", f, a.Error)
		}
		if len(a.Types) == 0 && filepath.Base(f) != "通信.suru" { // 通信 は組み込みだけ
			t.Errorf("%s: 型が1つも分かりません", f)
		}
		for _, ti := range a.Types {
			if ti.End <= ti.Pos.Col {
				t.Errorf("%s: %v の範囲がありません", f, ti)
			}
		}
	}
}

func TestAnalyzeKeepsTypesBeforeError(t *testing.T) {
	a := Analyze("税率 とは 0.1\n税率 + 「a」\n", ".")
	if a.Error == nil || a.Error.Line.Line != 2 {
		t.Fatalf("2行目の間違いが出ていません: %v", a.Error)
	}
	ti, ok := a.TypeAt(1, 2)
	if !ok || ti.Name != "税率" || ti.Type != "数" || !ti.Def {
		t.Fatalf("%v %v", ti, ok)
	}
}

func TestAnalyzeSpans(t *testing.T) {
	a := Analyze("『おやつの数』 とは 3\nnを三倍するとは、n*3。\n5を三倍しまして、表示します。\n", ".")
	ti, ok := a.TypeAt(1, 7) // 』
	if !ok || ti.Name != "おやつの数" || ti.End != 8 {
		t.Fatalf("『』の名前: %v %v", ti, ok)
	}
	ti, ok = a.TypeAt(3, 8) // 「三倍しまして」の「て」
	if !ok || ti.Name != "三倍する" || ti.End != 9 {
		t.Fatalf("丁寧語の形: %v", ti)
	}
}

// 書いている途中(ファイルの先頭から1文字ずつ)のどこでも、解析が止まらない
func TestAnalyzeWhileTyping(t *testing.T) {
	for _, f := range []string{"../examples/punct.suru", "../examples/cases.suru", "../examples/io.suru"} {
		b, err := os.ReadFile(f)
		if err != nil {
			t.Fatal(err)
		}
		rs := []rune(string(b))
		for i := 0; i <= len(rs); i++ {
			func() {
				defer func() {
					if r := recover(); r != nil {
						t.Fatalf("%s の %d 文字目まで: %v", f, i, r)
					}
				}()
				Analyze(string(rs[:i]), "..")
			}()
		}
	}
}

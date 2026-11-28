// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"reflect"
	"strings"
	"testing"
)

// 関数の型の宣言の終わりの「を 返す」「を 返します」は飾りで、「は 型」だけと同じ宣言になる
func TestTypeSigReturns(t *testing.T) {
	plain, err := ParseSource("数 を 階乗する は 数\n", ".")
	if err != nil {
		t.Fatal(err)
	}
	for _, src := range []string{
		"数 を 階乗する は 数 を 返す\n",
		"数 を 階乗する は 数 を 返します\n",
		"数 を 階乗する は 数 を返す\n",
		"数を階乗するは、数を返す。\n",
		"数を階乗するは、数を返します。\n",
	} {
		got, err := ParseSource(src, ".")
		if err != nil {
			t.Fatalf("%q: %v", src, err)
		}
		if !reflect.DeepEqual(got, plain) {
			t.Errorf("%q: 「は 数」だけの宣言と違います", src)
		}
	}
	if _, err := ParseSource("税率 は 数 を 返す\n", "."); err == nil || !strings.Contains(err.Error(), "関数の型の宣言の終わりにだけ") {
		t.Errorf("値の宣言の「を 返す」がエラーになりません: %v", err)
	}
}

// 型の宣言の中の「数 を 返す 動作」は「数 の 動作」と同じ
func TestTypeSigReturnsAction(t *testing.T) {
	pairs := [][2]string{
		{"挨拶する は 数 を 返す 動作\n", "挨拶する は 数 の 動作\n"},
		{"（数 を 返す 動作） を 二回する は 数 を 返す 動作 を 返す\n", "（数 の 動作） を 二回する は 数 の 動作\n"},
		{"f は （数 を 受け取って 数 を 返す 動作 を 返すこと）\n", "f は （数 を 受け取って 数 の 動作 を 返すこと）\n"},
		{"数を数値表示するは、数を返す動作。\n", "数を数値表示するは、数の動作。\n"},
		{"挨拶する は 数 を 返す 入出力動作\n", "挨拶する は 数 の 動作\n"},
		{"挨拶する は 数 の 入出力動作 の リスト\n", "挨拶する は 数 の 動作 の リスト\n"},
	}
	for _, p := range pairs {
		a, err := ParseSource(p[0], ".")
		if err != nil {
			t.Fatalf("%q: %v", p[0], err)
		}
		b, err := ParseSource(p[1], ".")
		if err != nil {
			t.Fatalf("%q: %v", p[1], err)
		}
		if !reflect.DeepEqual(a, b) {
			t.Errorf("%q と %q が違います", p[0], p[1])
		}
	}
}

// 「入出力手順」は動作だけの手順。値が動作でなければ型の検査でエラー
func TestIOTejun(t *testing.T) {
	ok := "挨拶する とは 入出力手順\n  「a」 を 表示する\n  3 を 結果にする\n挨拶する\n"
	prog, err := ParseSource(ok, ".")
	if err != nil {
		t.Fatal(err)
	}
	d, isDo := prog[0].(*Define).Body.(*Do)
	if !isDo || !d.IO {
		t.Fatalf("入出力手順の印がありません: %#v", prog[0])
	}
	div := "a と b を 安全除算する とは\n  もし b が 0 ならば 「0 では割れません」 の 失敗\n  そうでなければ （a / b） の 成功\n"
	if _, err := CompileSource(div+"入出力手順（xとは、10と2を安全除算した結果。x+1を結果にする）。\n", ".", "x.suru", true); err == nil ||
		!strings.Contains(err.Error(), "「入出力手順」の値は動作でなければなりません") {
		t.Errorf("成否の入出力手順がエラーになりません: %v", err)
	}
	if _, err := CompileSource(div+"手順（xとは、10と2を安全除算した結果。x+1を結果にする）。\n", ".", "x.suru", true); err != nil {
		t.Errorf("成否の手順がエラーになりました: %v", err)
	}
}

// パターンの「s という 形」は「s の 形」と同じ
func TestToiuPattern(t *testing.T) {
	shape := "図形 とは 半径 の 円 か 幅 と 高 の 長方形\n"
	pairs := [][2]string{
		{"（半径 という 円） を 面積にする とは 半径\n（幅 と 高 という 長方形） を 面積にする とは 幅\n",
			"（半径 の   円） を 面積にする とは 半径\n（幅 と 高 の   長方形） を 面積にする とは 幅\n"},
		{"x とは もし 5 の 円 が 半径 という 円 ならば 半径 そうでなければ 0\n", "x とは もし 5 の 円 が 半径 の   円 ならば 半径 そうでなければ 0\n"},
		{"x とは もし 5 の 円 が 半径 は r という 円 ならば r そうでなければ 0\n", "x とは もし 5 の 円 が 半径 は r の   円 ならば r そうでなければ 0\n"},
	}
	for _, p := range pairs {
		a, err := ParseSource(shape+p[0], ".")
		if err != nil {
			t.Fatalf("%q: %v", p[0], err)
		}
		b, err := ParseSource(shape+p[1], ".")
		if err != nil {
			t.Fatalf("%q: %v", p[1], err)
		}
		if !reflect.DeepEqual(a, b) {
			t.Errorf("%q と %q が違います", p[0], p[1])
		}
	}
}

// 組のフィールドの型でも「数 を 返す 動作」「… を 返す 入出力動作」を読む(#206)
func TestFieldTypeReturnsAction(t *testing.T) {
	src := "型札 とは 名 は 文字列 で 書込 は （数 を 受け取って 数 を 返す 入出力動作 を 返すこと） で 読込 は 数 を 返す 動作 の 組\n" +
		"数 を 二倍表示する は 数 を 返す 入出力動作\n" +
		"x を 二倍表示する とは x * 2 を 表示する\n" +
		"t とは 名 は 「あ」 で 書込 は 二倍表示すること で 読込 は （1 を 表示する） の 型札\n" +
		"21 に （t の 書込） を 適用する\n"
	if _, err := CompileSource(src, ".", "x.suru", true); err != nil {
		t.Errorf("フィールドの型の「を 返す 入出力動作」が読めません: %v", err)
	}
	// 「数 の 動作」と書いた形と同じ型なので、形ごとに書いても矛盾しない
	if _, err := ParseSource("札 とは 読 は 数 を 返す 動作 の 甲札 か 読 は 数 の 動作 の 乙札\n", "."); err != nil {
		t.Errorf("「数 を 返す 動作」と「数 の 動作」が違う型になりました: %v", err)
	}
}

// C構造体(#241 段階1): フィールドの型は C の型、値はふつうの組
func TestCStructDecl(t *testing.T) {
	src := "時間 とは 秒 は 符号付き64 で ナノ秒 は 符号なし32 の C構造体\n" +
		"品質 とは 期限 は 時間 で 率 は 単精度 で 先 は 番地 の C構造体\n" +
		"（（1 と 2 の 時間） と 0.5 と 空 の 品質） の 率 + 1\n"
	if _, err := CompileSource(src, ".", "x.suru", true); err == nil || !strings.Contains(err.Error(), "番地") {
		// 空 は番地ではないので型の検査で止まる
		t.Errorf("番地のフィールドに 空 が通りました: %v", err)
	}
	ok := strings.Replace(src, "と 空 の 品質", "と （0 を 番地にする） の 品質", 1)
	if _, err := CompileSource("「標準」 を 読み込んで 使う\n"+ok, ".", "x.suru", true); err != nil {
		t.Errorf("C構造体を組として使えません: %v", err)
	}
	// かっこでフィールドの型を書く形(#242)も同じ
	paren := "「標準」 を 読み込んで 使う\n時間 とは 秒 （符号付き64） と ナノ秒 （符号なし32） の C構造体\n" +
		"品質 とは 期限 （時間） と 率 （単精度） と 先 （番地） の C構造体\n" +
		"（（1 と 2 の 時間） と 0.5 と （0 を 番地にする） の 品質） の 率 + 1\n"
	if _, err := CompileSource(paren, ".", "x.suru", true); err != nil {
		t.Errorf("かっこで型を書いた C構造体を使えません: %v", err)
	}
	ctx := NewParseContext(".")
	if err := try(func() {
		ParseProgram("時間とは、秒は符号付き64でナノ秒は符号なし32のC構造体。\n", ctx)
	}); err != nil {
		t.Fatal(err)
	}
	want := []CStructField{{"秒", "符号付き64"}, {"ナノ秒", "符号なし32"}}
	if !reflect.DeepEqual(ctx.CStructs["時間"], want) {
		t.Errorf("C の型: %v", ctx.CStructs["時間"])
	}
	for src, msg := range map[string]string{
		"時間 とは 秒 は 数 の C構造体\n":                       "フィールド「秒」の型「数」は C の型ではありません",
		"時間 とは 秒 と 分 の C構造体\n":                       "C構造体のフィールドには C の型を書いてください",
		"時間 とは 秒 は 符号付き64 の 甲 か 分 は 符号付き64 の C構造体\n": "「C構造体」は形が1つのときだけ使えます",
		"甲 とは 中 は 乙 の C構造体\n乙 とは 中 は 甲 の C構造体\n":     "が自分自身をフィールドに持っています",
	} {
		if _, err := ParseSource(src, "."); err == nil || !strings.Contains(err.Error(), msg) {
			t.Errorf("%q: 「%s」のエラーになりません: %v", src, msg, err)
		}
	}
}

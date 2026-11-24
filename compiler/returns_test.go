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

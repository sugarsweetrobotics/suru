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

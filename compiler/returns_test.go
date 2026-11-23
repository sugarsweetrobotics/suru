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

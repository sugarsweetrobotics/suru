// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"path/filepath"
	"testing"
)

const treeSrc = "木 とは 値 と 左 と 右 の 節 か 葉\n" +
	"t を 合計する とは もし t が\n  v と l と r の 節 ならば v + （l を 合計する） + （r を 合計する）\n  葉 ならば 0\n"

// 自分自身を中に持つフィールドを見つけても、「値」に木を入れた木(木 の 木)の 値 は自分自身を中に持つことにはしない
// (suru_check.py の test_自分自身を中に持つフィールドと入れ子の同じ型 と同じ)
func TestRecursiveFieldAndNestedSameType(t *testing.T) {
	src := treeSrc + "t とは 1 と 葉 と 葉 の 節\n（t と 葉 と 葉 の 節）\n（（「a」 と 葉 と 葉 の 節） と 葉 と 葉 の 節）\n（1 と t と 葉 の 節） を 合計する\n"
	if _, err := CompileSource(src, ".", "木.suru", true); err != nil {
		t.Fatal(err.Message)
	}
}

// lib/構文.suru の 式 は形が多く、多くのフィールドに 式 自身を持つ(前は 写式にする を置かないと型が合わなかった)
func TestManyRecursiveFields(t *testing.T) {
	dir, _ := filepath.Abs("../lib")
	if _, err := CompileSource("「構文」 を 読み込む\n1 を 表示する\n", dir, filepath.Join(dir, "試し.suru"), true); err != nil {
		t.Fatal(err.Message)
	}
}

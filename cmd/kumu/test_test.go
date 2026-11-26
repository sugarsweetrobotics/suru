// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/suru-lang/suru/cmd/internal/native"
)

func TestRunnerSource(t *testing.T) {
	got := runnerSource("../../../試験/二倍", "二倍", []string{"甲試験する", "乙試験する"})
	for _, want := range []string{
		"「../../../試験/二倍」 を 読み込む\n",
		"  もし 引数 の 先頭 = 「1」 ならば （二倍内の甲試験する） を 結果無視する\n",
		"  そうでなければ もし 引数 の 先頭 = 「2」 ならば （二倍内の乙試験する） を 結果無視する\n",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("%q がない:\n%s", want, got)
		}
	}
}

func TestTestAndLint(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がない")
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("KUMU_HOME", t.TempDir())
	dir := t.TempDir()
	k, out, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "計算"}); rc != 0 {
		t.Fatal(errb)
	}
	root := filepath.Join(dir, "計算")
	k, out, errb = newKumu(root)
	if rc := k.run([]string{"試験"}); rc != 0 || !strings.Contains(errb.String(), "試験が見つかりません") {
		t.Fatalf("試験なし: rc=%d %s", rc, errb)
	}
	os.WriteFile(filepath.Join(root, "計算.suru"), []byte("x を 二倍する とは x * 2\nx を 割算する とは 10 / x\n"), 0o644)
	os.MkdirAll(filepath.Join(root, "試験", "下"), 0o755)
	// 試験/ からは、プロジェクトのファイルを「計算」(組.suru の名前)で読み込める
	os.WriteFile(filepath.Join(root, "試験", "二倍.suru"), []byte(
		"「試験」 を 読み込んで 使う\n「計算」 を 読み込む\n"+
			"小さい数試験する とは 手順\n  （2 を 計算内の二倍する） を 4 に 一致確認する\n  1 < 2 を 確認する\n  「途中」 を 表示する\n"+
			"大きい数試験する とは 手順\n  （100 を 計算内の二倍する） を 201 に 一致確認する\n"+
			"零で割る試験する とは 手順\n  （0 を 計算内の割算する） を 0 に 一致確認する\n"+
			"補助 とは 1\n"), 0o644)
	os.WriteFile(filepath.Join(root, "試験", "下", "別.suru"), []byte(
		"「試験」 を 読み込んで 使う\n理由試験する とは 「わざと」 を 不合格にする\n"+
			"「標準」 を 読み込む\n最大試験する とは （空 を 標準内の最大値にする） を 1 に 一致確認する\n"), 0o644)
	out.Reset()
	if rc := k.run([]string{"試験"}); rc != 1 {
		t.Fatalf("不合格があるのに rc=%d\n%s%s", rc, out, errb)
	}
	got := out.String()
	for _, want := range []string{
		"✓ 試験/二倍.suru 小さい数試験する\n",
		"✗ 試験/二倍.suru 大きい数試験する\n    等しくありません: 期待は 201 / 実際は 200\n",
		"✗ 試験/二倍.suru 零で割る試験する\n",
		"✗ 試験/下/別.suru 理由試験する\n    わざと\n",
		// ライブラリの中のエラーは、試験のファイルの呼んだ場所で出す(#154)
		"✗ 試験/下/別.suru 最大試験する\n    エラー: 「別.suru」の4行目 16文字目: 空のリストの最大値はありません(「標準.suru」の",
		"合格 1・不合格 4\n",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("%q がない:\n%s", want, got)
		}
	}
	if strings.Contains(got, "途中") {
		t.Errorf("合格した試験の出力は出さない:\n%s", got)
	}
	// 名前の一部で選ぶ
	out.Reset()
	if rc := k.run([]string{"test", "小さい"}); rc != 0 || !strings.Contains(out.String(), "合格 1・不合格 0") {
		t.Errorf("選んだ試験: rc=%d %s", rc, out)
	}
	// 読めないファイルは不合格
	os.WriteFile(filepath.Join(root, "試験", "壊れ.suru"), []byte("壊試験する とは （\n"), 0o644)
	out.Reset()
	if rc := k.run([]string{"試験", "壊"}); rc != 1 || !strings.Contains(out.String(), "✗ 試験/壊れ.suru(読めません)") {
		t.Errorf("読めない試験: rc=%d %s", rc, out)
	}
	os.Remove(filepath.Join(root, "試験", "壊れ.suru"))
	// 点検は 組.suru と 出力/ を除いた全部のファイル
	out.Reset()
	errb.Reset()
	rc := k.run([]string{"点検"})
	if rc != 1 || !strings.Contains(out.String(), "計算.suru:1:") || !strings.Contains(out.String(), "試験/下/別.suru:") {
		t.Fatalf("点検: rc=%d %s %s", rc, out, errb)
	}
	if strings.Contains(out.String(), "組.suru") || strings.Contains(out.String(), "出力/") {
		t.Errorf("組.suru か 出力/ を点検した: %s", out)
	}
	// --json なら1行に1つの JSON
	out.Reset()
	errb.Reset()
	if rc := k.run([]string{"点検", "--json"}); rc != 1 || !strings.HasPrefix(out.String(), `{"file":"`) ||
		!strings.Contains(out.String(), `"kind":"点検"`) {
		t.Errorf("点検 --json: rc=%d %s %s", rc, out, errb)
	}
}

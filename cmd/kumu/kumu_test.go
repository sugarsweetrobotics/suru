// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

func TestMain(m *testing.M) {
	compiler.LibFS = mustSub()
	os.Exit(m.Run())
}

func TestParseConfig(t *testing.T) {
	p, err := ParseConfig("名前 とは 「挨拶」\n版 とは 「1.2.3」\n入口 とは 「始め.suru」\n", "/x")
	if err != nil {
		t.Fatal(err)
	}
	if p.Name != "挨拶" || p.Version != "1.2.3" || p.Entry != "始め" || p.EntryPath() != filepath.Join("/x", "始め.suru") {
		t.Fatalf("読み違い: %+v", p)
	}
	// 版と入口は書かなくてよい。句読点の書き方も使える
	p, err = ParseConfig("名前とは「挨拶」。\n", "/x")
	if err != nil {
		t.Fatal(err)
	}
	if p.Version != "0.1.0" || p.Entry != "本体" {
		t.Fatalf("既定の値が違う: %+v", p)
	}
}

func TestParseConfigErrors(t *testing.T) {
	cases := []struct{ src, want string }{
		{"版 とは 「1.0.0」\n", "「名前 とは 「…」」がありません"},
		{"名前 とは 「a」\n速さ とは 「1」\n", "「組.suru」の2行目: 「速さ」は 組.suru に書けない項目です"},
		{"名前 とは 3\n", "「名前」には 「…」 の文字列を書きます"},
		{"名前 とは 「a」\n名前 とは 「b」\n", "「名前」が2回書かれています"},
		{"名前 とは 「a b」\n", "プロジェクトの名前に使えません"},
		{"名前 とは 「a」\n入口 とは 「../外」\n", "フォルダの中のファイルの名前"},
		{"名前 とは 「a」\n「x」 を 表示する\n", "定義だけを書きます"},
	}
	for _, c := range cases {
		_, err := ParseConfig(c.src, "/x")
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%q: %v(「%s」のはず)", c.src, err, c.want)
		}
	}
}

func newKumu(dir string) (*kumu, *bytes.Buffer, *bytes.Buffer) {
	var out, errb bytes.Buffer
	return &kumu{dir: dir, stdout: &out, stderr: &errb, stdin: strings.NewReader("")}, &out, &errb
}

func TestNewAndInit(t *testing.T) {
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "挨拶"}); rc != 0 {
		t.Fatalf("新規 が失敗: %s", errb)
	}
	for _, f := range []string{"組.suru", "本体.suru", ".gitignore"} {
		if _, err := os.Stat(filepath.Join(dir, "挨拶", f)); err != nil {
			t.Errorf("%s がない", f)
		}
	}
	if rc := k.run([]string{"new", "挨拶"}); rc != 1 || !strings.Contains(errb.String(), "既にあります") {
		t.Errorf("同じ名前でもう一度作れてしまう: %s", errb)
	}
	// 組.suru は上のフォルダからも見つかる
	sub := filepath.Join(dir, "挨拶", "部品")
	os.MkdirAll(sub, 0o755)
	p, err := FindProject(sub)
	if err != nil || p.Name != "挨拶" {
		t.Fatalf("上のフォルダの 組.suru が見つからない: %v", err)
	}
	// 初期化は今のフォルダに作り、今ある 本体.suru はそのまま
	here := filepath.Join(dir, "道具")
	os.MkdirAll(here, 0o755)
	os.WriteFile(filepath.Join(here, "本体.suru"), []byte("1 を 表示する\n"), 0o644)
	k2, _, errb2 := newKumu(here)
	if rc := k2.run([]string{"初期化"}); rc != 0 {
		t.Fatalf("初期化 が失敗: %s", errb2)
	}
	if b, _ := os.ReadFile(filepath.Join(here, "本体.suru")); string(b) != "1 を 表示する\n" {
		t.Errorf("本体.suru が書きかわった: %q", b)
	}
	if p, err := FindProject(here); err != nil || p.Name != "道具" {
		t.Errorf("初期化の名前がフォルダの名前でない: %v %v", p, err)
	}
	if rc := k2.run([]string{"init"}); rc != 1 {
		t.Errorf("2回目の初期化が通ってしまう")
	}
}

func TestBuildAndRun(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がない")
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	dir := t.TempDir()
	k, out, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "挨拶"}); rc != 0 {
		t.Fatal(errb)
	}
	root := filepath.Join(dir, "挨拶")
	k, out, errb = newKumu(root)
	if rc := k.run([]string{"実行", "-O0"}); rc != 0 || out.String() != "こんにちは\n" {
		t.Fatalf("実行: rc=%d 出力=%q エラー=%s", rc, out, errb)
	}
	exe := filepath.Join(root, "出力", "挨拶")
	st1, err := os.Stat(exe)
	if err != nil {
		t.Fatal(err)
	}
	// 変わっていなければ作り直さない
	time.Sleep(20 * time.Millisecond)
	errb.Reset()
	if rc := k.run([]string{"作る", "-O0"}); rc != 0 || errb.Len() != 0 {
		t.Fatalf("作る: rc=%d %s", rc, errb)
	}
	if st2, _ := os.Stat(exe); !st2.ModTime().Equal(st1.ModTime()) {
		t.Error("変わっていないのに作り直した")
	}
	// 中身を変えると作り直す。引数と終了コードはそのまま渡る。読み込みはプロジェクトのフォルダから
	os.WriteFile(filepath.Join(root, "部品.suru"), []byte("挨拶文 とは 「やあ」\n"), 0o644)
	os.WriteFile(filepath.Join(root, "本体.suru"), []byte(
		"「部品」 を 読み込む\n「環境」 を 読み込む\n部品内の挨拶文 を 表示する\n環境内の引数取得してから 表示する\n3 を 環境内の終了する\n"), 0o644)
	out.Reset()
	errb.Reset()
	if rc := k.run([]string{"run", "-O0", "--", "a", "-O2"}); rc != 3 {
		t.Fatalf("終了コードが渡らない: rc=%d %s", rc, errb)
	}
	if out.String() != "やあ\n（「a」 と 「-O2」）\n" {
		t.Errorf("出力が違う: %q", out)
	}
	if !strings.Contains(errb.String(), "を組みました") {
		t.Errorf("作り直していない: %s", errb)
	}
	// 間違いはファイルと行を付けて知らせる
	os.WriteFile(filepath.Join(root, "本体.suru"), []byte("1 を\n"), 0o644)
	errb.Reset()
	if rc := k.run([]string{"build"}); rc != 1 || !strings.Contains(errb.String(), "1行目") {
		t.Errorf("間違いを知らせない: rc=%d %s", rc, errb)
	}
}

func TestCommands(t *testing.T) {
	k, out, errb := newKumu(t.TempDir())
	if rc := k.run([]string{"版"}); rc != 0 || !strings.HasPrefix(out.String(), "kumu ") {
		t.Errorf("版: %q", out)
	}
	if rc := k.run([]string{"無い命令"}); rc != 2 || !strings.Contains(errb.String(), "という命令はありません") {
		t.Errorf("無い命令: %s", errb)
	}
	errb.Reset()
	if rc := k.run([]string{"作る"}); rc != 1 || !strings.Contains(errb.String(), "が見つかりません") {
		t.Errorf("組.suru なし: %s", errb)
	}
}

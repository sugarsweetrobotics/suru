// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/suru-lang/suru/cmd/internal/native"
)

func TestSourceFromRemote(t *testing.T) {
	for in, want := range map[string]string{
		"https://github.com/someone/計算.git\n": "github.com/someone/計算",
		"git@github.com:someone/計算.git":       "github.com/someone/計算",
		"ssh://git@example.com/a/b":           "example.com/a/b",
		"https://user@example.com/a/b/":       "example.com/a/b",
	} {
		if got := sourceFromRemote(in); got != want {
			t.Errorf("%q → %q(%q のはず)", in, got, want)
		}
	}
}

func TestPublish(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がない")
	}
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git がない")
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("KUMU_HOME", t.TempDir())
	// 公開はタグを付けるので、git の名前がない環境(CI など)でも動くようにする
	for _, k := range []string{"GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"} {
		t.Setenv(k, "t")
	}
	for _, k := range []string{"GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"} {
		t.Setenv(k, "t@example.com")
	}
	dir := t.TempDir()
	k, out, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "計算"}); rc != 0 {
		t.Fatal(errb)
	}
	root := filepath.Join(dir, "計算")
	g := func(args ...string) string {
		cmd := exec.Command("git", append([]string{"-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main"}, args...)...)
		cmd.Dir = root
		b, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %s", args, b)
		}
		return string(b)
	}
	k, out, errb = newKumu(root)
	// Git のリポジトリでなければ付けない
	if rc := k.run([]string{"公開"}); rc != 1 || !strings.Contains(errb.String(), "計算.suru」がありません") {
		t.Fatalf("名前.suru なし: %s", errb)
	}
	os.WriteFile(filepath.Join(root, "計算.suru"), []byte("x を 二倍する とは x * 2\n"), 0o644)
	errb.Reset()
	if rc := k.run([]string{"公開"}); rc != 1 || !strings.Contains(errb.String(), "Git のリポジトリではありません") {
		t.Fatalf("Git なし: %s", errb)
	}
	os.MkdirAll(filepath.Join(root, "試験"), 0o755)
	os.WriteFile(filepath.Join(root, "試験", "二倍.suru"), []byte("「試験」 を 読み込んで 使う\n「計算」 を 読み込む\n"+
		"二倍試験する とは （2 を 計算内の二倍する） を 5 に 一致確認する\n"), 0o644)
	g("init", "-q")
	g("remote", "add", "origin", "https://github.com/someone/計算.git")
	g("add", "-A")
	g("commit", "-q", "-m", "1")
	// 不合格の試験があれば付けない
	errb.Reset()
	if rc := k.run([]string{"公開"}); rc != 1 || !strings.Contains(errb.String(), "不合格の試験があるので") {
		t.Fatalf("不合格: %s", errb)
	}
	if strings.TrimSpace(g("tag")) != "" {
		t.Fatal("不合格なのにタグを付けた")
	}
	os.WriteFile(filepath.Join(root, "試験", "二倍.suru"), []byte("「試験」 を 読み込んで 使う\n「計算」 を 読み込む\n"+
		"二倍試験する とは （2 を 計算内の二倍する） を 4 に 一致確認する\n"), 0o644)
	errb.Reset()
	if rc := k.run([]string{"公開"}); rc != 1 || !strings.Contains(errb.String(), "まだコミットしていない変更") {
		t.Fatalf("変更あり: %s", errb)
	}
	g("commit", "-q", "-am", "2")
	out.Reset()
	errb.Reset()
	if rc := k.run([]string{"公開"}); rc != 0 {
		t.Fatalf("公開: %s %s", out, errb)
	}
	if !strings.Contains(out.String(), "git push origin v0.1.0") || !strings.Contains(out.String(), "kumu 追加 github.com/someone/計算@0.1.0") {
		t.Errorf("案内: %s", out)
	}
	if strings.TrimSpace(g("tag")) != "v0.1.0" {
		t.Errorf("タグ: %s", g("tag"))
	}
	errb.Reset()
	if rc := k.run([]string{"publish", "--試験なし"}); rc != 1 || !strings.Contains(errb.String(), "タグ v0.1.0 はもうあります") {
		t.Errorf("2回目: %s", errb)
	}
}

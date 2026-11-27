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

// runInstalled は入れたコマンドを動かして標準出力を返す
func runInstalled(t *testing.T, exe string) string {
	t.Helper()
	b, err := exec.Command(exe).Output()
	if err != nil {
		t.Fatalf("%s が動かない: %v", exe, err)
	}
	return string(b)
}

// kumu 導入: 今のプロジェクト・フォルダ・Git のタグから。既定は ~/.local/bin、--先 で変えられる
func TestInstall(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がない")
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("KUMU_HOME", t.TempDir())
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("PATH", os.Getenv("PATH"))
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "挨拶"}); rc != 0 {
		t.Fatal(errb)
	}
	root := filepath.Join(dir, "挨拶")

	// 今のプロジェクトを ~/.local/bin に。PATH になければ注意を出す
	k, _, errb = newKumu(root)
	if rc := k.run([]string{"導入", "-O0"}); rc != 0 {
		t.Fatalf("導入: %s", errb)
	}
	bin := filepath.Join(home, ".local", "bin")
	exe := native.ExePath(filepath.Join(bin, "挨拶"))
	if got := runInstalled(t, exe); got != "こんにちは\n" {
		t.Errorf("入れたコマンドの出力が違う: %q", got)
	}
	msg := errb.String()
	if !strings.Contains(msg, "「挨拶」0.1.0 を ~"+string(filepath.Separator)+filepath.Join(".local", "bin", filepath.Base(exe))+" に入れました") || !strings.Contains(msg, "PATH にありません") {
		t.Errorf("知らせが違う: %s", msg)
	}

	// 置き換えられる。PATH にあれば注意は出ない
	os.WriteFile(filepath.Join(root, "本体.suru"), []byte("「やあ」 を 表示する\n"), 0o644)
	t.Setenv("PATH", bin+string(filepath.ListSeparator)+os.Getenv("PATH"))
	errb.Reset()
	if rc := k.run([]string{"install", "-O0"}); rc != 0 {
		t.Fatalf("2回目の導入: %s", errb)
	}
	if got := runInstalled(t, exe); got != "やあ\n" {
		t.Errorf("置き換わっていない: %q", got)
	}
	if strings.Contains(errb.String(), "PATH") {
		t.Errorf("PATH にあるのに注意を出す: %s", errb)
	}

	// フォルダを指して、--先 の場所へ(相対なら今のフォルダから)
	k, _, errb = newKumu(dir)
	if rc := k.run([]string{"導入", "./挨拶", "--先", "道具", "-O0"}); rc != 0 {
		t.Fatalf("フォルダの導入: %s", errb)
	}
	if got := runInstalled(t, native.ExePath(filepath.Join(dir, "道具", "挨拶"))); got != "やあ\n" {
		t.Errorf("--先 に入っていない: %q", got)
	}

	// Git のタグから。版なしなら一番新しいタグ、@版 でその版
	repo := t.TempDir()
	gitRepo(t, repo, "v1.0.0", map[string]string{
		"組.suru":  "名前 とは 「数える」\n版 とは 「1.0.0」\n",
		"本体.suru": "「いち」 を 表示する\n",
	})
	gitRepo(t, repo, "v1.1.0", map[string]string{
		"組.suru":  "名前 とは 「数える」\n版 とは 「1.1.0」\n",
		"本体.suru": "「に」 を 表示する\n",
	})
	to := filepath.Join(dir, "外")
	errb.Reset()
	if rc := k.run([]string{"導入", "file://" + repo, "--dir", to, "-O0"}); rc != 0 {
		t.Fatalf("Git からの導入: %s", errb)
	}
	cmd := native.ExePath(filepath.Join(to, "数える"))
	if got := runInstalled(t, cmd); got != "に\n" || !strings.Contains(errb.String(), "「数える」1.1.0 を") {
		t.Errorf("一番新しいタグでない: %q %s", got, errb)
	}
	if rc := k.run([]string{"導入", "file://" + repo + "@1.0.0", "--先", to, "-O0"}); rc != 0 {
		t.Fatalf("@版 の導入: %s", errb)
	}
	if got := runInstalled(t, cmd); got != "いち\n" {
		t.Errorf("@1.0.0 でない: %q", got)
	}
	errb.Reset()
	if rc := k.run([]string{"導入", "file://" + repo + "@9.9.9", "--先", to}); rc != 1 || !strings.Contains(errb.String(), "導入するもの「file://") {
		t.Errorf("無い版: rc=%d %s", rc, errb)
	}
	if left, _ := filepath.Glob(filepath.Join(os.TempDir(), "kumu-install-*")); len(left) != 0 {
		t.Errorf("仮のフォルダが残っている: %v", left)
	}
}

func TestInstallErrors(t *testing.T) {
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"導入", "--速く"}); rc != 2 || !strings.Contains(errb.String(), "導入 に使えないオプション") {
		t.Errorf("知らないオプション: rc=%d %s", rc, errb)
	}
	errb.Reset()
	if rc := k.run([]string{"導入"}); rc != 1 || !strings.Contains(errb.String(), "が見つかりません") {
		t.Errorf("組.suru なし: %s", errb)
	}
	os.WriteFile(filepath.Join(dir, "組.suru"), []byte("名前 とは 「keisan」\n種類 とは 「共有ライブラリ」\n"), 0o644)
	errb.Reset()
	if rc := k.run([]string{"導入"}); rc != 1 || !strings.Contains(errb.String(), "導入できません") {
		t.Errorf("共有ライブラリ: %s", errb)
	}
	os.WriteFile(filepath.Join(dir, "組.suru"), []byte("名前 とは 「点滅」\n対象 とは 「arduino-uno」\n"), 0o644)
	errb.Reset()
	if rc := k.run([]string{"導入"}); rc != 1 || !strings.Contains(errb.String(), "マイコン向け") {
		t.Errorf("マイコン向け: %s", errb)
	}
}

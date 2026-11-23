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
	"github.com/suru-lang/suru/compiler"
)

// gitRepo は dir に Git のリポジトリを作り、files を書いて tag を付ける(何度でも呼べる)
func gitRepo(t *testing.T, dir, tag string, files map[string]string) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git がない")
	}
	os.MkdirAll(filepath.Join(dir, "部品"), 0o755)
	run := func(args ...string) {
		cmd := exec.Command("git", append([]string{"-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main"}, args...)...)
		cmd.Dir = dir
		if b, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %s", args, b)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, ".git")); err != nil {
		run("init", "-q")
	}
	for name, body := range files {
		os.WriteFile(filepath.Join(dir, name), []byte(body), 0o644)
	}
	run("add", "-A")
	run("commit", "-q", "-m", tag)
	run("tag", tag)
}

func TestParseDeps(t *testing.T) {
	p, err := ParseConfig("名前 とは 「a」\n依存 とは 「github.com/x/計算@v1.2.0」 と 「../部品」\n", "/x")
	if err != nil {
		t.Fatal(err)
	}
	if len(p.Deps) != 2 || p.Deps[0] != (Dep{"github.com/x/計算", "1.2.0"}) || p.Deps[1] != (Dep{"../部品", ""}) {
		t.Fatalf("依存の読み違い: %+v", p.Deps)
	}
	for src, want := range map[string]string{
		"名前 とは 「a」\n依存 とは 「github.com/x/y」\n":            "版がありません",
		"名前 とは 「a」\n依存 とは 「x.com/y@1」 と 「x.com/y@2」\n": "2回書かれています",
		"名前 とは 「a」\n依存 とは 3\n":                           "「依存」には",
	} {
		if _, err := ParseConfig(src, "/x"); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: %v(「%s」のはず)", src, err, want)
		}
	}
	if compareVersions("1.10.0", "1.9.3") <= 0 || compareVersions("2", "2.0.0") != 0 || compareVersions("1.0.0", "1.0.1") >= 0 {
		t.Error("版の比べ方が違う")
	}
}

func TestDependencies(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がない")
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("KUMU_HOME", t.TempDir())
	w := t.TempDir()
	calc := filepath.Join(w, "計算")
	gitRepo(t, calc, "v1.0.0", map[string]string{"組.suru": "名前 とは 「計算」\n", "計算.suru": "x を 二倍する とは x * 2\n"})
	gitRepo(t, calc, "v1.1.0", map[string]string{"計算.suru": "x を 二倍する とは x * 2\nx を 三倍する とは x * 3\n"})
	// 表示道具 は 計算 の 1.0.0 を使う(アプリは 1.1.0 を使うので、1.1.0 になる)
	show := filepath.Join(w, "表示道具")
	gitRepo(t, show, "v0.2.0", map[string]string{
		"組.suru":    "名前 とは 「表示道具」\n依存 とは 「file://" + calc + "@1.0.0」\n",
		"表示道具.suru":  "「計算」 を 読み込む\n「部品/装飾」 を 読み込む\nx を 二倍表示する とは x を 計算内の二倍して 装飾内の装飾して 表示する\n",
		"部品/装飾.suru": "x を 装飾する とは x + 1000\n",
	})
	gitRepo(t, show, "v0.3.0", map[string]string{"説明.txt": "0.3.0\n"})

	k, out, errb := newKumu(w)
	if rc := k.run([]string{"新規", "アプリ"}); rc != 0 {
		t.Fatal(errb)
	}
	app := filepath.Join(w, "アプリ")
	k, out, errb = newKumu(app)
	// 版を書かなければ一番新しいタグ
	if rc := k.run([]string{"追加", "file://" + calc, "file://" + show + "@0.3.0"}); rc != 0 {
		t.Fatalf("追加: %s", errb)
	}
	cfg, _ := os.ReadFile(filepath.Join(app, "組.suru"))
	if !strings.Contains(string(cfg), "依存 とは 「file://"+calc+"@1.1.0」 と 「file://"+show+"@0.3.0」\n") {
		t.Fatalf("組.suru の依存: %s", cfg)
	}
	lock := compiler.ReadLock(app)
	if len(lock) != 2 || lock[0].Name != "表示道具" || lock[1].Name != "計算" || lock[1].Version != "1.1.0" || len(lock[1].Commit) != 40 || !strings.HasPrefix(lock[1].Hash, "sha256-") {
		t.Fatalf("組.lock: %+v", lock)
	}
	os.WriteFile(filepath.Join(app, "本体.suru"), []byte("「計算」 を 読み込む\n「表示道具」 を 読み込む\n4 を 計算内の三倍して 表示する\n5 を 表示道具内の二倍表示する\n"), 0o644)
	out.Reset()
	errb.Reset()
	if rc := k.run([]string{"実行", "-O0"}); rc != 0 || out.String() != "12\n1010\n" {
		t.Fatalf("実行: rc=%d %q %s", rc, out, errb)
	}
	// インタプリタも 組.lock から依存を探す
	if py, err := exec.LookPath("python3"); err == nil {
		cmd := exec.Command(py, filepath.Join("..", "..", "suru.py"), filepath.Join(app, "本体.suru"))
		if b, err := cmd.CombinedOutput(); err != nil || string(b) != "12\n1010\n" {
			t.Errorf("suru.py: %v %s", err, b)
		}
	}
	// 取ってきた中身が変わっていたら知らせる
	cached := compiler.PackageDir(app, "file://"+calc, "1.1.0")
	os.WriteFile(filepath.Join(cached, "計算.suru"), []byte("x を 二倍する とは x * 2\nx を 三倍する とは x * 4\n"), 0o644)
	errb.Reset()
	if rc := k.run([]string{"作る", "-O0"}); rc != 1 || !strings.Contains(errb.String(), "の中身が 組.lock と違います") {
		t.Fatalf("中身の違いを知らせない: %s", errb)
	}
	os.RemoveAll(cached)
	os.Remove(cached + ".commit")
	errb.Reset()
	if rc := k.run([]string{"取得"}); rc != 0 || !strings.Contains(errb.String(), "を取ってきました") {
		t.Fatalf("取り直せない: %s", errb)
	}
	// 更新は一番新しいタグにする
	gitRepo(t, calc, "v1.2.0", map[string]string{"計算.suru": "x を 二倍する とは x * 2\nx を 三倍する とは x * 3\nx を 四倍する とは x * 4\n"})
	errb.Reset()
	if rc := k.run([]string{"更新", "計算"}); rc != 0 || !strings.Contains(errb.String(), "1.1.0 から 1.2.0") {
		t.Fatalf("更新: %s", errb)
	}
	if l := compiler.ReadLock(app); l[1].Version != "1.2.0" {
		t.Fatalf("更新した版が 組.lock にない: %+v", l)
	}
	// 削除。依存がなくなれば 組.lock も消す
	if rc := k.run([]string{"削除", "計算", "表示道具"}); rc != 0 {
		t.Fatalf("削除: %s", errb)
	}
	if _, err := os.Stat(filepath.Join(app, "組.lock")); err == nil {
		t.Error("組.lock が残った")
	}
	if cfg, _ := os.ReadFile(filepath.Join(app, "組.suru")); strings.Contains(string(cfg), "依存") {
		t.Errorf("依存が残った: %s", cfg)
	}
	// 手元のフォルダの依存
	local := filepath.Join(w, "手元")
	os.MkdirAll(local, 0o755)
	os.WriteFile(filepath.Join(local, "組.suru"), []byte("名前 とは 「手元」\n"), 0o644)
	os.WriteFile(filepath.Join(local, "手元.suru"), []byte("挨拶文 とは 「やあ」\n"), 0o644)
	os.WriteFile(filepath.Join(app, "本体.suru"), []byte("「手元」 を 読み込む\n手元内の挨拶文 を 表示する\n"), 0o644)
	out.Reset()
	if rc := k.run([]string{"add", "../手元"}); rc != 0 {
		t.Fatalf("手元の追加: %s", errb)
	}
	if rc := k.run([]string{"run", "-O0"}); rc != 0 || out.String() != "やあ\n" {
		t.Fatalf("手元の依存: %q %s", out, errb)
	}
	// 標準のライブラリと同じ名前・失敗したら 組.suru を戻す
	std := filepath.Join(w, "偽標準")
	os.MkdirAll(std, 0o755)
	os.WriteFile(filepath.Join(std, "組.suru"), []byte("名前 とは 「標準」\n"), 0o644)
	os.WriteFile(filepath.Join(std, "標準.suru"), []byte("a とは 1\n"), 0o644)
	before, _ := os.ReadFile(filepath.Join(app, "組.suru"))
	errb.Reset()
	if rc := k.run([]string{"追加", "../偽標準"}); rc != 1 || !strings.Contains(errb.String(), "標準のライブラリと同じです") {
		t.Fatalf("標準と同じ名前: %s", errb)
	}
	if after, _ := os.ReadFile(filepath.Join(app, "組.suru")); string(after) != string(before) {
		t.Errorf("失敗したのに 組.suru が変わった: %s", after)
	}
	// 無いタグ
	errb.Reset()
	if rc := k.run([]string{"追加", "file://" + calc + "@9.9.9"}); rc != 1 || !strings.Contains(errb.String(), "取ってこられません") {
		t.Errorf("無いタグ: %s", errb)
	}
}

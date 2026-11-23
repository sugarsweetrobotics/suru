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

func TestParseSysDeps(t *testing.T) {
	p, err := ParseConfig("名前 とは 「a」\n外部依存 とは 「libpcre2-8@10.30」 と 「zlib」\n導入案内 とは 「brew install pcre2」\n", "/x")
	if err != nil {
		t.Fatal(err)
	}
	if len(p.SysDeps) != 2 || p.SysDeps[0] != (SysDep{"libpcre2-8", "10.30"}) || p.SysDeps[1] != (SysDep{"zlib", ""}) || len(p.Guide) != 1 {
		t.Fatalf("読み違い: %+v %v", p.SysDeps, p.Guide)
	}
	for src, want := range map[string]string{
		"名前 とは 「a」\n外部依存 とは 3\n":          "「外部依存」には 「…」 の文字列",
		"名前 とは 「a」\n外部依存 とは 「a b」\n":      "pkg-config の名前で書きます",
		"名前 とは 「a」\n外部依存 とは 「zlib@新しい」\n": "版は数と点で書きます",
		"名前 とは 「a」\n導入案内 とは 「x」 と 1\n":    "「導入案内」には",
	} {
		if _, err := ParseConfig(src, "/x"); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: %v(「%s」のはず)", src, err, want)
		}
	}
}

// fakeSysLib は普通でないフォルダに libsurukumu.so と、それを指す surukumu.pc(版 ver)を作り、
// PKG_CONFIG_PATH をそこにする
func fakeSysLib(t *testing.T, ver string) string {
	t.Helper()
	if compiler.PkgConfig() == "" {
		t.Skip("pkg-config がない")
	}
	cc := native.FindCC()
	if cc == "" {
		t.Skip("clang がない")
	}
	w := t.TempDir()
	lib := filepath.Join(w, "変な場所", "lib")
	os.MkdirAll(lib, 0o755)
	src := filepath.Join(w, "surukumu.c")
	os.WriteFile(src, []byte("long long surukumu_triple(long long x) { return 3 * x; }\n"), 0o644)
	if b, err := exec.Command(cc, "-shared", "-fPIC", "-o", filepath.Join(lib, "libsurukumu.so"), src).CombinedOutput(); err != nil {
		t.Fatalf("共有ライブラリを作れない: %s", b)
	}
	pcDir := filepath.Join(w, "pc")
	os.MkdirAll(pcDir, 0o755)
	os.WriteFile(filepath.Join(pcDir, "surukumu.pc"), []byte("libdir="+lib+"\n\nName: surukumu\nDescription: test\nVersion: "+ver+"\nLibs: -L${libdir} -lsurukumu\n"), 0o644)
	t.Setenv("PKG_CONFIG_PATH", pcDir)
	return w
}

func TestSysDeps(t *testing.T) {
	w := fakeSysLib(t, "1.2.0")
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	t.Setenv("KUMU_HOME", t.TempDir())
	// C のライブラリを包む依存(手元のフォルダ)
	wrap := filepath.Join(w, "三倍")
	os.MkdirAll(wrap, 0o755)
	writeWrap := func(req string) {
		os.WriteFile(filepath.Join(wrap, "組.suru"), []byte("名前 とは 「三倍」\n外部依存 とは 「"+req+"」\n導入案内 とは 「macOS: brew install surukumu」 と 「Debian: apt install libsurukumu-dev」\n"), 0o644)
	}
	writeWrap("surukumu@1.0")
	os.WriteFile(filepath.Join(wrap, "三倍.suru"), []byte("外部の「surukumu」 を 読み込む\n数 を 三倍する は 数\nx を 三倍する とは 外部の「surukumu_triple」\n"), 0o644)

	k, _, errb := newKumu(w)
	if rc := k.run([]string{"新規", "アプリ"}); rc != 0 {
		t.Fatal(errb)
	}
	app := filepath.Join(w, "アプリ")
	os.WriteFile(filepath.Join(app, "本体.suru"), []byte("「三倍」 を 読み込む\n14 を 三倍内の三倍して 表示する\n"), 0o644)
	k, out, errb := newKumu(app)
	if rc := k.run([]string{"追加", "../三倍"}); rc != 0 {
		t.Fatalf("追加: %s", errb)
	}
	// 普通は探さないフォルダのライブラリを、pkg-config で見つけてリンクする(rpath も付ける)
	if rc := k.run([]string{"実行", "-O0"}); rc != 0 || out.String() != "42\n" {
		t.Fatalf("実行: rc=%d %q %s", rc, out, errb)
	}
	// インタプリタも pkg-config で見つける
	if py, err := exec.LookPath("python3"); err == nil {
		cmd := exec.Command(py, filepath.Join("..", "..", "suru.py"), filepath.Join(app, "本体.suru"))
		if b, err := cmd.CombinedOutput(); err != nil || string(b) != "42\n" {
			t.Errorf("suru.py: %v %s", err, b)
		}
	}
	// 版が足りない
	writeWrap("surukumu@2.0")
	errb.Reset()
	if rc := k.run([]string{"作る", "-O0"}); rc != 1 ||
		!strings.Contains(errb.String(), "「surukumu」 2.0 以上が要りますが、入っているのは 1.2.0 です(依存「三倍」が使います)") ||
		!strings.Contains(errb.String(), "入れ方(「三倍」の導入案内):\n  macOS: brew install surukumu\n  Debian: apt install libsurukumu-dev") {
		t.Fatalf("版が足りないのを知らせない: %s", errb)
	}
	// 入っていない
	writeWrap("surukumu-無い")
	errb.Reset()
	if rc := k.run([]string{"取得"}); rc != 1 || !strings.Contains(errb.String(), "システムのライブラリが足りません:\n  「surukumu-無い」が見つかりません(依存「三倍」が使います)") {
		t.Fatalf("無いのを知らせない: %s", errb)
	}
	// pkg-config が無ければ、知らせだけ出して進む
	writeWrap("surukumu")
	t.Setenv("PKG_CONFIG", "")
	t.Setenv("PATH", t.TempDir())
	compiler.ResetPkgConfigCache()
	errb.Reset()
	if rc := k.run([]string{"取得"}); rc != 0 || !strings.Contains(errb.String(), "pkg-config が無いので、外部依存(surukumu)が入っているかを確かめずに進みます") {
		t.Fatalf("pkg-config が無いとき: rc=%d %s", rc, errb)
	}
}

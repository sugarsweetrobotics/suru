// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/suru-lang/suru/cmd/internal/mcu"
)

func TestConfigTarget(t *testing.T) {
	p, err := ParseConfig("名前 とは 「点滅」\n対象 とは 「arduino-uno」\n", "/x")
	if err != nil || p.Target != "arduino-uno" {
		t.Fatalf("対象 が読めない: %+v %v", p, err)
	}
	if _, err := ParseConfig("名前 とは 「点滅」\n対象 とは 「z80」\n", "/x"); err == nil || !strings.Contains(err.Error(), "「z80」というマイコンの対象はありません") {
		t.Errorf("知らない対象が通る: %v", err)
	}
}

func TestNewMCUProject(t *testing.T) {
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "点滅", "--対象", "arduino-uno"}); rc != 0 {
		t.Fatalf("新規 --対象 が失敗: %s", errb)
	}
	if !strings.Contains(errb.String(), "kumu 書き込む") {
		t.Errorf("次にすることの案内が違う: %s", errb)
	}
	p, err := FindProject(filepath.Join(dir, "点滅"))
	if err != nil || p.Target != "arduino-uno" {
		t.Fatalf("組.suru に対象がない: %+v %v", p, err)
	}
	body, _ := os.ReadFile(filepath.Join(dir, "点滅", "本体.suru"))
	if !strings.Contains(string(body), "「マイコン」 を 読み込んで 使う") {
		t.Errorf("マイコンの雛形でない: %s", body)
	}
	// 実行・試験は案内して止まる
	k2, _, errb2 := newKumu(filepath.Join(dir, "点滅"))
	if rc := k2.run([]string{"実行"}); rc != 1 || !strings.Contains(errb2.String(), "kumu 書き込む") {
		t.Errorf("実行 の案内が違う: %d %s", rc, errb2)
	}
	if rc := k2.run([]string{"新規", "x", "--対象", "z80"}); rc != 1 {
		t.Errorf("知らない対象で新規できてしまう")
	}
}

func TestFlashNeedsTarget(t *testing.T) {
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "挨拶"}); rc != 0 {
		t.Fatal(errb)
	}
	k2, _, errb2 := newKumu(filepath.Join(dir, "挨拶"))
	if rc := k2.run([]string{"書き込む"}); rc != 1 || !strings.Contains(errb2.String(), "マイコンの対象 が要ります") {
		t.Errorf("対象なしで書き込める: %s", errb2)
	}
}

// 道具(AVR の clang・avr-gcc)があれば、雛形を作って .hex までできるか
func TestBuildMCUProject(t *testing.T) {
	if _, err := mcu.FindTools(false); err != nil {
		t.Skip(err)
	}
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "点滅", "--対象", "arduino-uno"}); rc != 0 {
		t.Fatal(errb)
	}
	k2, _, errb2 := newKumu(filepath.Join(dir, "点滅"))
	if rc := k2.run([]string{"作る"}); rc != 0 {
		t.Fatalf("作る が失敗: %s", errb2)
	}
	hex := filepath.Join(dir, "点滅", "出力", "arduino-uno", "点滅.hex")
	if b, err := os.ReadFile(hex); err != nil || !strings.HasPrefix(string(b), ":") {
		t.Fatalf(".hex ができていない: %v", err)
	}
	if !strings.Contains(errb2.String(), "フラッシュ") {
		t.Errorf("大きさが出ていない: %s", errb2)
	}
}

func TestNewWebProject(t *testing.T) {
	dir := t.TempDir()
	k, _, errb := newKumu(dir)
	if rc := k.run([]string{"新規", "店", "--対象", "web"}); rc != 0 {
		t.Fatalf("新規 --対象 web が失敗: %s", errb)
	}
	if !strings.Contains(errb.String(), "http://localhost:8080/") {
		t.Errorf("次にすることの案内が違う: %s", errb)
	}
	app := filepath.Join(dir, "店")
	p, err := FindProject(app)
	if err != nil || p.Target != "" || p.Entry != "本体" || len(p.Deps) != 1 || p.Deps[0] != (Dep{"github.com/suru-lang/web", webVersion}) {
		t.Fatalf("組.suru が違う: %+v %v", p, err)
	}
	for name, want := range map[string]string{
		"本体.suru":     "「店」 を 読み込んで 使う",
		"店.suru":      "以下の【道】です",
		"試験/道.suru":   "「店」 を 読み込んで 使う",
		"画面/配置.html":  "{{ 中身 を 生にする }}",
		"画面/トップ.html": "{{ 名前 }}",
		"公開/見た目.css":  "font-family",
		".gitignore":  "/出力/",
	} {
		b, err := os.ReadFile(filepath.Join(app, filepath.FromSlash(name)))
		if err != nil || !strings.Contains(string(b), want) {
			t.Errorf("%s に「%s」がない: %v %s", name, want, err, b)
		}
	}
	for _, bad := range []string{"屋台", "JSON"} {
		if rc := k.run([]string{"新規", bad, "--対象", "web"}); rc != 1 {
			t.Errorf("読み込みの名前と同じ「%s」で作れてしまう", bad)
		}
		if _, err := os.Stat(filepath.Join(dir, bad)); err == nil {
			t.Errorf("作れなかった「%s」のフォルダが残っている", bad)
		}
	}
	// 初期化 --対象 web は、今あるファイルを残して足りないものを書く
	other := filepath.Join(dir, "既存")
	os.MkdirAll(other, 0o755)
	os.WriteFile(filepath.Join(other, "本体.suru"), []byte("「やあ」 を 表示する\n"), 0o644)
	k2, _, errb2 := newKumu(other)
	if rc := k2.run([]string{"初期化", "--対象", "web"}); rc != 0 {
		t.Fatalf("初期化 --対象 web が失敗: %s", errb2)
	}
	if b, _ := os.ReadFile(filepath.Join(other, "本体.suru")); string(b) != "「やあ」 を 表示する\n" {
		t.Errorf("今ある本体.suru を書き換えた: %s", b)
	}
	if _, err := os.Stat(filepath.Join(other, "既存.suru")); err != nil {
		t.Errorf("道のファイルがない: %v", err)
	}
}

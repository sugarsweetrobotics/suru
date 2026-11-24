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

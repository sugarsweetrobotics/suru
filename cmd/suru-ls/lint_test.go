// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"

	"github.com/suru-lang/suru/cmd/internal/native"
)

func TestParseLint(t *testing.T) {
	out := "/a/b.suru:3:5: 未使用の定義: 「x」は定義されていますが、使われていません\n/other.suru:1:1: x: y\nゴミ\n"
	notes := parseLint(out, "/a/b.suru")
	if len(notes) != 1 || notes[0] != (lintNote{3, 5, "未使用の定義", "「x」は定義されていますが、使われていません"}) {
		t.Fatalf("読み方が違います: %v", notes)
	}
}

func TestSilenceEdit(t *testing.T) {
	lines := []string{"x とは 1", "y とは 2  # 点検しない: 行末の空白", "z とは 3 # 点検しない"}
	if _, text, ok := silenceEdit(lines, 1, "未使用の定義"); !ok || text != "  # 点検しない: 未使用の定義" {
		t.Fatalf("新しく書く: %q %v", text, ok)
	}
	if _, text, ok := silenceEdit(lines, 2, "未使用の定義"); !ok || text != " 未使用の定義" {
		t.Fatalf("規則を足す: %q %v", text, ok)
	}
	if _, _, ok := silenceEdit(lines, 3, "未使用の定義"); ok {
		t.Fatal("全部を黙らせている行には足さない")
	}
}

// 点検のバイナリを作って、知らせが警告として出ること・黙らせるクイックフィックスを確かめる(clang がなければ飛ばす)
func TestLintDiagnostics(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がありません")
	}
	t.Setenv("XDG_CACHE_HOME", t.TempDir())
	setupLib()
	exe, err := lintBinary()
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "点検.suru")
	u := pathToURI(path)
	src := "未使用 とは 1\n2 を 表示する\n"
	msgs := talkWith(t, exe, open(u, src))
	d := diagnostics(t, msgs)
	if len(d) != 1 || d[0]["source"] != "点検" || d[0]["code"] != "未使用の定義" || d[0]["severity"] != float64(2) {
		t.Fatalf("点検の警告が出ていません: %v", d)
	}
	b, _ := json.Marshal(d[0]["range"])
	if string(b) != `{"end":{"character":3,"line":0},"start":{"character":0,"line":0}}` {
		t.Fatalf("範囲が違います: %s", b)
	}
	action := map[string]any{"id": 2, "method": "textDocument/codeAction", "params": map[string]any{
		"textDocument": map[string]any{"uri": u},
		"range":        d[0]["range"],
		"context":      map[string]any{"diagnostics": d}}}
	msgs = talkWith(t, exe, open(u, src), action)
	r := result(t, msgs, 2)
	if !strings.Contains(r, `"newText":"  # 点検しない: 未使用の定義"`) || !strings.Contains(r, `"character":8,"line":0`) {
		t.Fatalf("クイックフィックスが違います: %s", r)
	}
	// 「ドキュメントのフォーマット」は空白を整えた全体に置きかえる(#250)
	messy := "x  とは   1   \nx を 表示する\n"
	format := map[string]any{"id": 3, "method": "textDocument/formatting", "params": map[string]any{
		"textDocument": map[string]any{"uri": u}, "options": map[string]any{"tabSize": 2, "insertSpaces": true}}}
	r = result(t, talkWith(t, exe, open(u, messy), format), 3)
	if !strings.Contains(r, `"newText":"x とは 1\nx を 表示する\n"`) || !strings.Contains(r, `"end":{"character":0,"line":2}`) {
		t.Fatalf("整えた結果が違います: %s", r)
	}
	// 書き換えている途中は前の知らせを使い、保存したら調べ直す
	fixed := "x とは 1\nx を 表示する\n"
	change := map[string]any{"method": "textDocument/didChange", "params": map[string]any{
		"textDocument":   map[string]any{"uri": u, "version": 2},
		"contentChanges": []map[string]any{{"text": fixed}}}}
	save := map[string]any{"method": "textDocument/didSave", "params": map[string]any{"textDocument": map[string]any{"uri": u}}}
	if d := diagnostics(t, talkWith(t, exe, open(u, src), change)); len(d) != 1 {
		t.Fatalf("書き換えの途中で知らせが消えました: %v", d)
	}
	if d := diagnostics(t, talkWith(t, exe, open(u, src), change, save)); len(d) != 0 {
		t.Fatalf("保存しても知らせが残っています: %v", d)
	}
}

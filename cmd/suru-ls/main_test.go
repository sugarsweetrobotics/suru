// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// talk はメッセージを順に渡し、サーバーが送ったものを返す
func talk(t *testing.T, msgs ...map[string]any) []message {
	t.Helper()
	var buf bytes.Buffer
	w := bufio.NewWriter(&buf)
	s := &server{out: w, docs: map[string]*document{}}
	for _, m := range msgs {
		m["jsonrpc"] = "2.0"
		b, _ := json.Marshal(m)
		var msg message
		if err := json.Unmarshal(b, &msg); err != nil {
			t.Fatal(err)
		}
		s.handle(msg)
	}
	w.Flush()
	var out []message
	r := bufio.NewReader(&buf)
	for {
		body, err := readMessage(r)
		if err != nil {
			break
		}
		var m message
		if err := json.Unmarshal(body, &m); err != nil {
			t.Fatal(err)
		}
		out = append(out, m)
	}
	return out
}

func open(uri, text string) map[string]any {
	return map[string]any{"method": "textDocument/didOpen", "params": map[string]any{
		"textDocument": map[string]any{"uri": uri, "languageId": "suru", "version": 1, "text": text}}}
}

func at(id int, method, uri string, line, ch int) map[string]any {
	return map[string]any{"id": id, "method": method, "params": map[string]any{
		"textDocument": map[string]any{"uri": uri}, "position": map[string]any{"line": line, "character": ch}}}
}

func result(t *testing.T, msgs []message, id int) string {
	t.Helper()
	for _, m := range msgs {
		if m.ID != nil && string(*m.ID) == strings.TrimSpace(string(rune('0'+id))) {
			b, _ := json.Marshal(m.Result)
			return string(b)
		}
	}
	t.Fatalf("id %d の返事がありません", id)
	return ""
}

func diagnostics(t *testing.T, msgs []message) []map[string]any {
	t.Helper()
	for i := len(msgs) - 1; i >= 0; i-- {
		if msgs[i].Method == "textDocument/publishDiagnostics" {
			var p struct {
				Diagnostics []map[string]any `json:"diagnostics"`
			}
			json.Unmarshal(msgs[i].Params, &p)
			return p.Diagnostics
		}
	}
	t.Fatal("publishDiagnostics がありません")
	return nil
}

const uri = "file:///tmp/テスト.suru"

func TestErrorWhileTyping(t *testing.T) {
	msgs := talk(t, open(uri, "nを三倍するとは、n*3。\n「a」を三倍する。\n"))
	d := diagnostics(t, msgs)
	if len(d) != 1 || !strings.Contains(d[0]["message"].(string), "文字列が渡されています") {
		t.Fatalf("間違いが出ていません: %v", d)
	}
	b, _ := json.Marshal(d[0]["range"])
	// 2行目 5文字目の「三倍する」(0から数えて 4〜8)
	if string(b) != `{"end":{"character":8,"line":1},"start":{"character":4,"line":1}}` {
		t.Fatalf("範囲が違います: %s", b)
	}
	// 直すと消える
	msgs = talk(t, open(uri, "nを三倍するとは、n*3。\n「a」を三倍する。\n"),
		map[string]any{"method": "textDocument/didChange", "params": map[string]any{
			"textDocument":   map[string]any{"uri": uri, "version": 2},
			"contentChanges": []map[string]any{{"text": "nを三倍するとは、n*3。\n5を三倍する。\n"}}}})
	if d := diagnostics(t, msgs); len(d) != 0 {
		t.Fatalf("間違いが残っています: %v", d)
	}
}

func TestHoverAndDefinition(t *testing.T) {
	src := "nを三倍するとは、n*3。\n5を三倍して、表示する。\n"
	msgs := talk(t, open(uri, src),
		at(1, "textDocument/hover", uri, 1, 3), // 2行目の「三倍して」
		at(2, "textDocument/hover", uri, 0, 3), // 定義の「三倍する」
		at(3, "textDocument/definition", uri, 1, 3),
		at(4, "textDocument/hover", uri, 1, 1), // 「を」の上には何も出さない
		at(5, "textDocument/hover", uri, 1, 8), // 組み込みの「表示する」
		at(6, "textDocument/hover", uri, 1, 5)) // 「三倍して」の「て」
	if h := result(t, msgs, 1); !strings.Contains(h, "三倍する は （数 を 受け取って 数 を 返すこと）") {
		t.Fatalf("ホバー: %s", h)
	}
	if h := result(t, msgs, 2); !strings.Contains(h, `"range":{"end":{"character":6,"line":0},"start":{"character":2,"line":0}}`) {
		t.Fatalf("定義のホバーの範囲: %s", h)
	}
	if h := result(t, msgs, 2); !strings.Contains(h, "三倍する は （数 を 受け取って 数 を 返すこと）") || !strings.Contains(h, "定義の型") {
		t.Fatalf("定義のホバー: %s", h)
	}
	if d := result(t, msgs, 3); d != `[{"range":{"end":{"character":6,"line":0},"start":{"character":2,"line":0}},"uri":"file:///tmp/テスト.suru"}]` {
		t.Fatalf("定義へ移動: %s", d)
	}
	if h := result(t, msgs, 6); !strings.Contains(h, "三倍する は") {
		t.Fatalf("「して」の上: %s", h)
	}
	if h := result(t, msgs, 4); h != "null" {
		t.Fatalf("助詞の上: %s", h)
	}
	if h := result(t, msgs, 5); !strings.Contains(h, "表示する は （数 を 受け取って") {
		t.Fatalf("組み込み: %s", h)
	}
}

func TestDefinitionInImportedFile(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "数学.suru"), []byte("x を 二乗する とは x * x\n"), 0o644)
	main := filepath.Join(dir, "本体.suru")
	u := pathToURI(main)
	msgs := talk(t, open(u, "「数学」 を 読み込む\n3 を 数学内の二乗する\n"),
		at(1, "textDocument/definition", u, 1, 10))
	d := result(t, msgs, 1)
	if !strings.Contains(d, "%E6%95%B0%E5%AD%A6.suru") || !strings.Contains(d, `"start":{"character":4,"line":0}`) {
		t.Fatalf("読み込んだファイルの定義: %s", d)
	}
}

func TestSymbols(t *testing.T) {
	msgs := talk(t, open(uri, "税率 とは 0.1\nn を 三倍する とは n * 3\n"),
		map[string]any{"id": 1, "method": "textDocument/documentSymbol", "params": map[string]any{"textDocument": map[string]any{"uri": uri}}})
	s := result(t, msgs, 1)
	if !strings.Contains(s, `"name":"税率"`) || !strings.Contains(s, `"name":"三倍する"`) || !strings.Contains(s, `"kind":12`) {
		t.Fatalf("定義の一覧: %s", s)
	}
}

func TestUTF16(t *testing.T) {
	lines := []string{"𠮷を三倍する"}
	if p := toUTF16(lines, 1, 2); p.Character != 2 {
		t.Fatalf("%v", p)
	}
	if l, c := fromUTF16(lines, position{0, 2}); l != 1 || c != 2 {
		t.Fatalf("%d %d", l, c)
	}
}

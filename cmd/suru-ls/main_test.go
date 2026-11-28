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
	return talkWith(t, "", msgs...)
}

// talkWith は点検のバイナリ lintExe を使うサーバーと話す
func talkWith(t *testing.T, lintExe string, msgs ...map[string]any) []message {
	t.Helper()
	var buf bytes.Buffer
	w := bufio.NewWriter(&buf)
	s := &server{out: w, docs: map[string]*document{}, lintExe: lintExe}
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

// 定義のすぐ上の注釈が説明としてホバーに出る(読み込んだファイルの定義も、#209)
func TestHoverDescription(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "数学.suru"), []byte("# 数学\n\n# 2乗した値です。\nx を 二乗する とは x * x\n"), 0o644)
	main := filepath.Join(dir, "本体.suru")
	u := pathToURI(main)
	msgs := talk(t, open(u, "「数学」 を 読み込む\n\n# 3倍した値です。\nn を 三倍する とは n * 3\n3 を 数学内の二乗する\n4 を 三倍する\n"),
		at(1, "textDocument/hover", u, 4, 10),
		at(2, "textDocument/hover", u, 5, 4))
	if h := result(t, msgs, 1); !strings.Contains(h, "2乗した値です。") {
		t.Fatalf("読み込んだファイルの説明: %s", h)
	}
	if h := result(t, msgs, 2); !strings.Contains(h, "3倍した値です。") {
		t.Fatalf("説明: %s", h)
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

func items(t *testing.T, msgs []message, id int) []map[string]any {
	t.Helper()
	var r struct {
		Items []map[string]any `json:"items"`
	}
	json.Unmarshal([]byte(result(t, msgs, id)), &r)
	return r.Items
}

func find(items []map[string]any, label string) map[string]any {
	for _, it := range items {
		if it["label"] == label {
			return it
		}
	}
	return nil
}

func TestCompletion(t *testing.T) {
	src := "nを三倍するとは、n*3。\n『おやつ』とは、1。\n5を三倍\n"
	msgs := talk(t, open(uri, src), at(1, "textDocument/completion", uri, 2, 4))
	its := items(t, msgs, 1)
	it := find(its, "三倍する")
	if it == nil {
		t.Fatalf("三倍する がありません: %v", its)
	}
	b, _ := json.Marshal(it["textEdit"])
	// 「5を」の後ろの「三倍」(2〜4)を置き換える
	if string(b) != `{"newText":"三倍する","range":{"end":{"character":4,"line":2},"start":{"character":2,"line":2}}}` {
		t.Fatalf("置き換える範囲: %s", b)
	}
	if find(its, "表示する") == nil || find(its, "もし") == nil {
		t.Fatal("組み込みやキーワードがありません")
	}
	if o := find(its, "おやつ"); o == nil || o["textEdit"].(map[string]any)["newText"] != "『おやつ』" {
		t.Fatalf("ひらがなの名前は『』で囲む: %v", o)
	}
}

func TestCompletionKeepsNamesWhileBroken(t *testing.T) {
	msgs := talk(t, open(uri, "nを三倍するとは、n*3。\n"),
		map[string]any{"method": "textDocument/didChange", "params": map[string]any{
			"textDocument":   map[string]any{"uri": uri, "version": 2},
			"contentChanges": []map[string]any{{"text": "nを三倍するとは、n*3。\n（5を三\n"}}}},
		at(1, "textDocument/completion", uri, 1, 4))
	if find(items(t, msgs, 1), "三倍する") == nil {
		t.Fatal("構文が崩れていると補完が消えます")
	}
}

func TestSeveralErrors(t *testing.T) {
	msgs := talk(t, open(uri, "nを三倍するとは、n*3。\n「a」を三倍する。\n1 + 「b」\n"))
	if d := diagnostics(t, msgs); len(d) != 2 {
		t.Fatalf("間違いが2つ出ていません: %v", d)
	}
}

func TestSemanticTokens(t *testing.T) {
	msgs := talk(t, open(uri, "点 とは 横 と 縦 の 組\n数 を 倍する は 数\nx を 倍する とは x * 2\nリスト とは 3 と 4 の 点\n"),
		map[string]any{"id": 1, "method": "textDocument/semanticTokens/full", "params": map[string]any{"textDocument": map[string]any{"uri": uri}}})
	// 点(形) 横・縦(フィールド) / 数 数(型) / 点(形)。変数の「リスト」は型にしない
	if r := result(t, msgs, 1); r != `{"data":[0,0,1,1,0,0,5,1,3,0,0,4,1,3,0,1,0,1,0,0,0,10,1,0,0,2,15,1,1,0]}` {
		t.Fatalf("%s", r)
	}
}

func TestRename(t *testing.T) {
	src := "数 を 三倍する は 数\nn を 三倍する とは n * 3\n5を三倍して、表示する。\n"
	msgs := talk(t, open(uri, src),
		map[string]any{"id": 1, "method": "textDocument/rename", "params": map[string]any{
			"textDocument": map[string]any{"uri": uri}, "position": map[string]any{"line": 2, "character": 3}, "newName": "四倍する"}},
		map[string]any{"id": 2, "method": "textDocument/rename", "params": map[string]any{
			"textDocument": map[string]any{"uri": uri}, "position": map[string]any{"line": 2, "character": 3}, "newName": "よんばいする"}},
		map[string]any{"id": 3, "method": "textDocument/prepareRename", "params": map[string]any{
			"textDocument": map[string]any{"uri": uri}, "position": map[string]any{"line": 2, "character": 9}}})
	r := result(t, msgs, 1)
	for _, want := range []string{
		`{"newText":"四倍","range":{"end":{"character":6,"line":0},"start":{"character":4,"line":0}}}`,
		`{"newText":"四倍","range":{"end":{"character":6,"line":1},"start":{"character":4,"line":1}}}`,
		`{"newText":"四倍","range":{"end":{"character":4,"line":2},"start":{"character":2,"line":2}}}`,
	} {
		if !strings.Contains(r, want) {
			t.Fatalf("%s がありません: %s", want, r)
		}
	}
	for _, m := range msgs {
		if m.ID != nil && string(*m.ID) == "2" && (m.Error == nil || !strings.Contains(m.Error.Message, "ひらがなだけ")) {
			t.Fatalf("ひらがなだけの名前を断っていません: %v", m.Error)
		}
		if m.ID != nil && string(*m.ID) == "3" && m.Error == nil {
			t.Fatalf("組み込みの「表示する」は変えられないはず")
		}
	}
}

func TestUsage(t *testing.T) {
	src := "a を b で 割合にする とは a / b\n10 を 2 で 割合にする\n"
	msgs := talk(t, open(uri, src),
		at(1, "textDocument/hover", uri, 1, 9),
		at(2, "textDocument/completion", uri, 1, 9))
	if h := result(t, msgs, 1); !strings.Contains(h, "使い方: `a を b で 割合にする`") {
		t.Fatalf("ホバーの使い方: %s", h)
	}
	its := items(t, msgs, 2)
	if it := find(its, "加算する"); it == nil || !strings.Contains(it["documentation"].(map[string]any)["value"].(string), "… を （… に） 加算する") {
		t.Fatalf("組み込みの使い方: %v", it)
	}
}

func TestRenameParameter(t *testing.T) {
	src := "n を 三倍する とは n * 3\nx を 二倍する とは\n  n * 0 + x * 2\nn とは 5\n"
	msgs := talk(t, open(uri, src),
		map[string]any{"id": 1, "method": "textDocument/rename", "params": map[string]any{
			"textDocument": map[string]any{"uri": uri}, "position": map[string]any{"line": 0, "character": 0}, "newName": "値"}},
		map[string]any{"id": 2, "method": "textDocument/rename", "params": map[string]any{
			"textDocument": map[string]any{"uri": uri}, "position": map[string]any{"line": 2, "character": 10}, "newName": "かず"}})
	r := result(t, msgs, 1)
	// 1行目の n だけ(4行目の値 n は変えない)
	if strings.Count(r, `"newText":"値"`) != 2 || strings.Contains(r, `"line":3`) {
		t.Fatalf("引数の名前の変更: %s", r)
	}
	r = result(t, msgs, 2)
	if strings.Count(r, `"newText":"『かず』"`) != 2 || !strings.Contains(r, `"line":1`) || !strings.Contains(r, `"line":2`) {
		t.Fatalf("字下げした本体の中も変え、ひらがなは『』で囲む: %s", r)
	}
}

func TestSeveralSyntaxErrors(t *testing.T) {
	msgs := talk(t, open(uri, "x とは （1 +\nnを三倍するとは、n*3。\ny とは 「a\n「b」を三倍する。\n"))
	d := diagnostics(t, msgs)
	if len(d) != 3 {
		t.Fatalf("構文の間違い2つと型の間違い1つが出ていません: %v", d)
	}
}

func TestTestSymbols(t *testing.T) {
	// 試験のまとまりと例は、表示の名前で定義の一覧に出す(中だけの名前「《例》3」は出さない #193)
	setupLib()
	src := "数 を 二倍する は 数\nx を 二倍する とは x * 2\n例えば （2 を 二倍する） は 4 です\n\n以下は「二倍」の試験です\n  （2 を 二倍する） を 4 に 一致確認する\n  以上です\n"
	msgs := talk(t, open(uri, src),
		map[string]any{"id": 1, "method": "textDocument/documentSymbol", "params": map[string]any{"textDocument": map[string]any{"uri": uri}}},
		at(2, "textDocument/hover", uri, 5, 9))
	s := result(t, msgs, 1)
	if !strings.Contains(s, `"name":"二倍するの例(3行)"`) || !strings.Contains(s, `"detail":"試験","kind":12,"location":{"range":{"end":{"character":12,"line":4},"start":{"character":0,"line":4}}`) || strings.Contains(s, "《") {
		t.Fatalf("定義の一覧: %s", s)
	}
	if h := result(t, msgs, 2); !strings.Contains(h, "二倍する は （数 を 受け取って 数 を 返すこと）") {
		t.Fatalf("試験のまとまりの中のホバー: %s", h)
	}
	// 定義のホバーには、その定義の例を見せる
	msgs = talk(t, open(uri, src), at(3, "textDocument/hover", uri, 1, 5))
	if h := result(t, msgs, 3); !strings.Contains(h, "例:\\n```suru\\n例えば （2 を 二倍する） は 4 です\\n```") {
		t.Fatalf("例を見せるホバー: %s", h)
	}
}

// かっこで型を後ろに書いた組(#242): かっこの中の型も型として色を付け、空白なしの「の組」も型の定義
func TestSemanticTokensParenFieldTypes(t *testing.T) {
	msgs := talk(t, open(uri, "品 とは 番号 （数） と 場所 （点 の リスト） の組\n点 とは 横 と 縦 の 組\n（1 と 空 の 品） の 番号\n"),
		map[string]any{"id": 1, "method": "textDocument/semanticTokens/full", "params": map[string]any{"textDocument": map[string]any{"uri": uri}}})
	if d := diagnostics(t, msgs); len(d) != 0 {
		t.Fatalf("間違いが出ています: %v", d)
	}
	// 品(形) 番号(フィールド) 数(型) 場所(フィールド) 点(形) リスト(型) / 点 横 縦 / 品 番号
	if r := result(t, msgs, 1); r != `{"data":[0,0,1,1,0,0,5,2,3,0,0,4,1,0,0,0,5,2,3,0,0,4,1,1,0,0,4,3,0,0,1,0,1,1,0,0,5,1,3,0,0,4,1,3,0,1,9,1,1,0,0,5,2,3,0]}` {
		t.Fatalf("%s", r)
	}
}

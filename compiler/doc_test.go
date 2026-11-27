package compiler

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDocComments(t *testing.T) {
	src := `# SPDX-License-Identifier: MIT
# Copyright (c) 2026 だれか
# 計算のライブラリ
#
#   n を 二倍する … 2倍

# 数を2倍します。
#
# 負の数もそのまま2倍します。
数 を 二倍する は 数 を 返す
n を 二倍する とは n * 2 です

例えば 3 を 二倍する は 6 です

# これは説明ではない(空行がある)

n を 三倍する とは n * 3 です

# 円周率の近い値
# 点検しない: 未使用の定義
円周率 とは 3.14 です

# 図形の形
図形 とは 半径 の 円 か 幅 と 高 の 長方形 です
`
	prog := ParseProgram(src, NewParseContext("."))
	mod, names := DocComments(src, prog)
	if want := "計算のライブラリ\n\n  n を 二倍する … 2倍"; mod != want {
		t.Errorf("ファイルの説明 = %q, want %q", mod, want)
	}
	want := map[string]string{
		"二倍する": "数を2倍します。\n\n負の数もそのまま2倍します。",
		"円周率":  "円周率の近い値",
		"図形":   "図形の形",
	}
	for k, v := range want {
		if names[k] != v {
			t.Errorf("%s の説明 = %q, want %q", k, names[k], v)
		}
	}
	if d, ok := names["三倍する"]; ok {
		t.Errorf("三倍する に説明が付いた: %q", d)
	}
}

// 頭の注釈のすぐ下の定義には、頭の注釈を説明として付けない
func TestDocCommentsHeadOnly(t *testing.T) {
	src := "# ファイルの説明\nn を 二倍する とは n * 2\n"
	mod, names := DocComments(src, ParseProgram(src, NewParseContext(".")))
	if mod != "ファイルの説明" || len(names) != 0 {
		t.Errorf("mod=%q names=%v", mod, names)
	}
}

// 読み込んだファイルの説明は「名前内の…」で引ける(言語サーバーのホバーで使う)
func TestAnalyzeDocsOfImport(t *testing.T) {
	dir := t.TempDir()
	lib := "# 数学\n\n# 2乗します\n数 を 二乗する は 数\nn を 二乗する とは n * n\n\n# 内緒\nn を 内緒する とは n\n\n内緒する は 非公開とする\n"
	if err := os.WriteFile(filepath.Join(dir, "数学.suru"), []byte(lib), 0o644); err != nil {
		t.Fatal(err)
	}
	a := Analyze("「数学」 を 読み込む\n3 を 数学内の二乗して 表示する\n", dir)
	if a.Error != nil {
		t.Fatal(a.Error)
	}
	if got := a.Docs["数学"+ModuleSep+"二乗する"]; got != "2乗します" {
		t.Errorf("説明 = %q", got)
	}
	if _, ok := a.Docs["数学"+ModuleSep+"内緒する"]; ok {
		t.Error("非公開の名前に説明が付いた")
	}
}

// API ドキュメント(段階2)。tests/test_doc.py の API_SRC・API_MD と同じ
const apiSrc = `# 計算のライブラリです。

# 数を2倍した値です。
数 を 二倍する は 数 を 返す
x を 二倍する とは x * 2 です
例えば （3 を 二倍する） は 6 です
例えば （0 を 二倍する） は 0 です

# 円周率の近い値です。
円周率 とは 3.14 です

# 図形です。
図形 とは
  半径 の 円
    か 幅 と 高 の 長方形

a と b を 足す計算する とは a + b です

n を 内緒する とは n です

内緒する は 非公開とする
`

const apiMD = "# 「計算」\n\n計算のライブラリです。\n\n## 二倍する\n\n```suru\n数 を 二倍する は 数 を 返す\n```\n\nUsage: `x を 二倍する`\n\n数を2倍した値です。\n\nExamples:\n\n```suru\n例えば （3 を 二倍する） は 6 です\n例えば （0 を 二倍する） は 0 です\n```\n\n## 円周率\n\n円周率の近い値です。\n\n## 図形\n\n```suru\n図形 とは\n  半径 の 円\n    か 幅 と 高 の 長方形\n```\n\n図形です。\n\n## 足す計算する\n\nUsage: `a と b を 足す計算する`\n"

func TestDocumentMarkdown(t *testing.T) {
	prog := ParseProgram(apiSrc, NewParseContext("."))
	d := Document(apiSrc, prog, privateNames(prog))
	d.Module = "計算"
	if got := d.Markdown(); got != apiMD {
		t.Errorf("Markdown:\n%s\nwant:\n%s", got, apiMD)
	}
	kinds := map[string]string{}
	for _, it := range d.Items {
		kinds[it.Name] = it.Kind
	}
	want := map[string]string{"二倍する": "関数", "円周率": "値", "図形": "型", "足す計算する": "関数"}
	if len(kinds) != len(want) {
		t.Fatalf("種類: %v", kinds)
	}
	for k, v := range want {
		if kinds[k] != v {
			t.Errorf("%s の種類 = %q, want %q", k, kinds[k], v)
		}
	}
}

func TestDocCommand(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "計算.suru"), []byte(apiSrc), 0o644); err != nil {
		t.Fatal(err)
	}
	var out, errb strings.Builder
	if st := DocCommand([]string{dir}, &out, &errb); st != 0 || out.String() != apiMD {
		t.Fatalf("status=%d err=%s out=%s", st, errb.String(), out.String())
	}
	od := filepath.Join(dir, "出力")
	if st := DocCommand([]string{"--json", "--出力", od, filepath.Join(dir, "計算.suru")}, &out, &errb); st != 0 {
		t.Fatalf("status=%d err=%s", st, errb.String())
	}
	b, err := os.ReadFile(filepath.Join(od, "計算.json"))
	if err != nil || !strings.Contains(string(b), `"module":"計算"`) {
		t.Fatalf("JSON: %s %v", b, err)
	}
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics
package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// kumu 文書: 依存(手元のフォルダ)を読み込むファイルも文書にし、試験/ と 組.suru は文書にしない(#209)
func TestDoc(t *testing.T) {
	dir := t.TempDir()
	write := func(p, s string) {
		t.Helper()
		os.MkdirAll(filepath.Dir(p), 0o755)
		if err := os.WriteFile(p, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	lib := filepath.Join(dir, "部品")
	write(filepath.Join(lib, "組.suru"), "名前 とは 「部品」\n版 とは 「0.1.0」\n")
	write(filepath.Join(lib, "部品.suru"), "# 部品です。\n\n数 を 一足する は 数\nn を 一足する とは n + 1\n")
	app := filepath.Join(dir, "計算")
	write(filepath.Join(app, "組.suru"), "名前 とは 「計算」\n版 とは 「1.2.0」\n依存 とは 「../部品」\n")
	write(filepath.Join(app, "計算.suru"), "# 計算のライブラリです。\n「部品」 を 読み込む\n\n# 2を足した値です。\n数 を 二足する は 数 を 返す\nn を 二足する とは （n を 部品内の一足する） + 1 です\n例えば （1 を 二足する） は 3 です\n")
	write(filepath.Join(app, "試験", "計算.suru"), "# 試験\n1 を 表示する\n")

	k, _, errb := newKumu(app)
	if rc := k.run([]string{"文書"}); rc != 0 {
		t.Fatalf("文書 が失敗: %s", errb)
	}
	b, err := os.ReadFile(filepath.Join(app, "docs", "api", "計算.md"))
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"# 「計算」", "計算のライブラリです。", "## 二足する", "数 を 二足する は 数 を 返す", "2を足した値です。", "例えば （1 を 二足する） は 3 です"} {
		if !strings.Contains(string(b), want) {
			t.Errorf("「%s」がない:\n%s", want, b)
		}
	}
	es, _ := os.ReadDir(filepath.Join(app, "docs", "api"))
	if len(es) != 1 {
		t.Errorf("計算.md のほかのファイルも書いた: %v", es)
	}

	// 雛形: 名前と版を入れて書き、2回目は今あるファイルを変えない
	if rc := k.run([]string{"文書", "--雛形"}); rc != 0 {
		t.Fatalf("文書 --雛形 が失敗: %s", errb)
	}
	conf, _ := os.ReadFile(filepath.Join(app, "docs", "conf.py"))
	idx, _ := os.ReadFile(filepath.Join(app, "docs", "index.md"))
	rtd, _ := os.ReadFile(filepath.Join(app, ".readthedocs.yaml"))
	gi, _ := os.ReadFile(filepath.Join(app, ".gitignore"))
	if !strings.Contains(string(conf), `project = "計算"`) || !strings.Contains(string(idx), "計算のライブラリです。") {
		t.Errorf("conf.py・index.md:\n%s\n%s", conf, idx)
	}
	if !strings.Contains(string(rtd), "/v"+version+"/suru-"+version+"-linux-amd64.tar.gz") || !strings.Contains(string(rtd), "kumu 文書 --出力 docs/api") {
		t.Errorf(".readthedocs.yaml:\n%s", rtd)
	}
	if !strings.Contains(string(gi), "/docs/api/") || !strings.Contains(string(gi), "__pycache__/") {
		t.Errorf(".gitignore:\n%s", gi)
	}
	if _, err := os.Stat(filepath.Join(app, "docs", "_ext", "suru_lexer.py")); err != nil {
		t.Error(err)
	}
	write(filepath.Join(app, "docs", "index.md"), "自分で書いた\n")
	if rc := k.run([]string{"文書", "--雛形"}); rc != 0 || !strings.Contains(errb.String(), "docs/index.md はもうあるので変えません") {
		t.Fatalf("2回目の雛形: %s", errb)
	}
	if b, _ := os.ReadFile(filepath.Join(app, "docs", "index.md")); string(b) != "自分で書いた\n" {
		t.Errorf("index.md が書きかわった: %s", b)
	}
	if rc := k.run([]string{"文書", "--雛形", "--json"}); rc != 2 {
		t.Errorf("--雛形 と --json を一緒に使えてしまう")
	}
}

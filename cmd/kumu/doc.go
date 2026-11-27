// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics
package main

import (
	"embed"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// 「kumu 文書」(#209): プロジェクトの一番上の .suru(組.suru を除く)の公開の名前の API ドキュメントを、
// 依存を取ってきてから作る。--雛形 は Sphinx(MyST)と Read the Docs の設定を、なければ書く

//go:embed docs_template
var docsTemplate embed.FS

// DocsDir は雛形を書くフォルダ、DocsAPIDir は既定の出力先
const (
	DocsDir    = "docs"
	DocsAPIDir = "docs/api"
)

const docUsage = "使い方: kumu 文書 [--json] [--出力 フォルダ](既定は docs/api)\n       kumu 文書 --雛形(Sphinx と Read the Docs の設定を書く)"

func (k *kumu) doc(args []string) int {
	scaffold := false
	out := ""
	asJSON := false
	for i := 0; i < len(args); i++ {
		switch a := args[i]; {
		case a == "--雛形" || a == "--init":
			scaffold = true
		case a == "--json" || a == "--JSON":
			asJSON = true
		case (a == "--出力" || a == "--out" || a == "-o") && i+1 < len(args):
			out = args[i+1]
			i++
		default:
			fmt.Fprintln(k.stderr, docUsage)
			return 2
		}
	}
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	if scaffold {
		if out != "" || asJSON {
			fmt.Fprintln(k.stderr, docUsage)
			return 2
		}
		return k.docScaffold(p)
	}
	if _, err := Resolve(p, k.stderr); err != nil {
		return k.fail(err)
	}
	files, err := docFiles(p.Root)
	if err != nil {
		return k.fail(err)
	}
	if len(files) == 0 {
		fmt.Fprintln(k.stderr, "文書にするファイルがありません")
		return 0
	}
	if out == "" {
		out = filepath.Join(p.Root, filepath.FromSlash(DocsAPIDir))
	} else if !filepath.IsAbs(out) {
		out = filepath.Join(k.dir, out)
	}
	cmd := []string{"--出力", out}
	if asJSON {
		cmd = append(cmd, "--json")
	}
	st := compiler.DocCommand(append(cmd, files...), k.stdout, k.stderr)
	if st == 0 {
		fmt.Fprintf(k.stderr, "%d 個のファイルの API ドキュメントを %s に書きました\n", len(files), k.rel(out))
	}
	return st
}

// docFiles はプロジェクトの一番上の .suru(組.suru を除く)。試験/ や 例/ の下は API ではないので見ない
func docFiles(root string) ([]string, error) {
	es, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}
	var files []string
	for _, e := range es {
		if !e.IsDir() && strings.HasSuffix(e.Name(), compiler.SourceSuffix) && e.Name() != ConfigName {
			files = append(files, filepath.Join(root, e.Name()))
		}
	}
	return files, nil
}

// docScaffold は docs/ の Sphinx の設定と .readthedocs.yaml を、まだなければ書く(あるファイルは変えない)
func (k *kumu) docScaffold(p *Project) int {
	// 説明は、プロジェクトと同じ名前のファイル(ライブラリ)か入口のファイルの頭の注釈
	desc := ""
	for _, f := range []string{filepath.Join(p.Root, p.Name+compiler.SourceSuffix), p.EntryPath()} {
		if d, err := compiler.DocumentFile(f); err == nil && d.Description != "" {
			desc = d.Description
			break
		}
	}
	repl := strings.NewReplacer("{{名前}}", p.Name, "{{説明}}", desc, "{{kumu の版}}", version)
	files := []struct{ src, dst string }{
		{"conf.py", "docs/conf.py"},
		{"index.md", "docs/index.md"},
		{"requirements.txt", "docs/requirements.txt"},
		{"suru_lexer.py", "docs/_ext/suru_lexer.py"},
		{"readthedocs.yaml", ".readthedocs.yaml"},
	}
	for _, f := range files {
		dst := filepath.Join(p.Root, filepath.FromSlash(f.dst))
		if _, err := os.Stat(dst); err == nil {
			fmt.Fprintf(k.stderr, "%s はもうあるので変えません\n", f.dst)
			continue
		}
		b, err := docsTemplate.ReadFile("docs_template/" + f.src)
		if err != nil {
			return k.fail(err)
		}
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			return k.fail(err)
		}
		if err := os.WriteFile(dst, []byte(repl.Replace(string(b))), 0o644); err != nil {
			return k.fail(err)
		}
		fmt.Fprintf(k.stderr, "%s を書きました\n", f.dst)
	}
	if err := addGitignore(p.Root, []string{"/docs/api/", "/docs/_build/"}); err != nil {
		return k.fail(err)
	}
	fmt.Fprintln(k.stderr, "kumu 文書 で docs/api を作り、sphinx-build docs docs/_build で HTML にできます")
	return 0
}

// addGitignore は .gitignore に、まだない行を足す
func addGitignore(root string, lines []string) error {
	path := filepath.Join(root, ".gitignore")
	b, _ := os.ReadFile(path)
	have := map[string]bool{}
	for _, l := range strings.Split(string(b), "\n") {
		have[strings.TrimSpace(l)] = true
	}
	text := string(b)
	for _, l := range lines {
		if !have[l] {
			if text != "" && !strings.HasSuffix(text, "\n") {
				text += "\n"
			}
			text += l + "\n"
		}
	}
	if text == string(b) {
		return nil
	}
	return os.WriteFile(path, []byte(text), 0o644)
}

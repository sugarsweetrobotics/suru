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

// 「kumu 文書」(#209): プロジェクトの一番上の .suru(組.suru を除く。組.suru の「文書」「文書から除く」で選べる、#235)の公開の名前の API ドキュメントを、
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
	files, err := docFiles(p)
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
	// フォルダごとに書く(「型/geometry_msgs.suru」は 出力/型/geometry_msgs.md に)
	var dirs []string
	byDir := map[string][]string{}
	for _, f := range files {
		rel, _ := filepath.Rel(p.Root, f)
		d := filepath.Dir(rel)
		if _, ok := byDir[d]; !ok {
			dirs = append(dirs, d)
		}
		byDir[d] = append(byDir[d], f)
	}
	st := 0
	for _, d := range dirs {
		cmd := []string{"--出力", filepath.Join(out, d)}
		if asJSON {
			cmd = append(cmd, "--json")
		}
		if s := compiler.DocCommand(append(cmd, byDir[d]...), k.stdout, k.stderr); s != 0 {
			st = s
		}
	}
	if st == 0 {
		fmt.Fprintf(k.stderr, "%d 個のファイルの API ドキュメントを %s に書きました\n", len(files), k.rel(out))
	}
	return st
}

// docFiles は文書にするファイル。組.suru に「文書」がなければプロジェクトの一番上の .suru(組.suru を除く)で、
// 試験/ や 例/ の下は API ではないので見ない。「文書」のフォルダ(「型/」)は下のフォルダも見る。
// 「文書から除く」に書いたファイルとフォルダの下は除く(#235)
func docFiles(p *Project) ([]string, error) {
	root := p.Root
	var files []string
	seen := map[string]bool{}
	add := func(f string) {
		if !seen[f] {
			seen[f] = true
			files = append(files, f)
		}
	}
	if len(p.Docs) == 0 {
		es, err := os.ReadDir(root)
		if err != nil {
			return nil, err
		}
		for _, e := range es {
			if !e.IsDir() && strings.HasSuffix(e.Name(), compiler.SourceSuffix) && e.Name() != ConfigName {
				add(filepath.Join(root, e.Name()))
			}
		}
	}
	for _, it := range p.Docs {
		full := filepath.Join(root, filepath.FromSlash(it))
		st, err := os.Stat(full)
		if err != nil {
			return nil, fmt.Errorf("「%s」の文書の「%s」がありません", ConfigName, it)
		}
		if strings.HasSuffix(it, "/") != st.IsDir() {
			if st.IsDir() {
				return nil, fmt.Errorf("「%s」の文書の「%s」はフォルダです(「%s/」と書きます)", ConfigName, it, it)
			}
			return nil, fmt.Errorf("「%s」の文書の「%s」はファイルです(終わりの / を取ります)", ConfigName, it)
		}
		if !st.IsDir() {
			add(full)
			continue
		}
		var found []string
		err = filepath.WalkDir(full, func(f string, e os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if !e.IsDir() && strings.HasSuffix(e.Name(), compiler.SourceSuffix) && f != filepath.Join(root, ConfigName) {
				found = append(found, f)
			}
			return nil
		})
		if err != nil {
			return nil, err
		}
		for _, f := range found {
			add(f)
		}
	}
	var out []string
	for _, f := range files {
		rel, _ := filepath.Rel(root, f)
		rel = filepath.ToSlash(rel)
		skip := false
		for _, s := range p.DocsSkip {
			if rel == s || (strings.HasSuffix(s, "/") && strings.HasPrefix(rel, s)) {
				skip = true
			}
		}
		if !skip {
			out = append(out, f)
		}
	}
	return out, nil
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
	if err := addGitignore(p.Root, []string{"/docs/api/", "/docs/_build/", "__pycache__/"}); err != nil {
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

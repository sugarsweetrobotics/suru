// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package testrun は、する のファイルの試験(試験のまとまり・例・「…試験する」)をバイナリにして動かす
// (suruc --試験。suru --試験 と同じ知らせ方)
package testrun

import (
	"bytes"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// Files は道がファイルならそれ、フォルダなら下の .suru(出力/ と . で始まるフォルダは除く)
func Files(path string) ([]string, error) {
	st, err := os.Stat(path)
	if err != nil {
		return nil, err
	}
	if !st.IsDir() {
		return []string{path}, nil
	}
	var files []string
	err = filepath.WalkDir(path, func(p string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.IsDir() && p != path && (e.Name() == "出力" || strings.HasPrefix(e.Name(), ".")) {
			return filepath.SkipDir
		}
		if !e.IsDir() && strings.HasSuffix(e.Name(), compiler.SourceSuffix) {
			// 道は書いたフォルダの後ろに続ける(「.」なら「./計算.suru」。suru --試験 と同じ)
			rel, _ := filepath.Rel(path, p)
			files = append(files, strings.TrimSuffix(path, string(filepath.Separator))+string(filepath.Separator)+rel)
		}
		return nil
	})
	sort.Strings(files)
	return files, err
}

// Runner は試験を動かす。結果を Out に書き、合格と不合格を数える
type Runner struct {
	Out     io.Writer
	Opt     string   // clang の最適化(ふつうは -O0。作るのが速い)
	Filters []string // 名前かファイルの道にどれかを含む試験だけ(空なら全部)
	WorkDir string   // 試験用のバイナリを置くフォルダ
	Extra   []string // リンクするオブジェクトや引数(kumu の Cソース)
	Passed  int
	Failed  int
}

func (r *Runner) match(file string) func(string) bool {
	if len(r.Filters) == 0 {
		return nil
	}
	return func(label string) bool {
		for _, f := range r.Filters {
			if strings.Contains(label, f) || strings.Contains(file, f) {
				return true
			}
		}
		return false
	}
}

func indent(s string) string {
	return "    " + strings.ReplaceAll(s, "\n", "\n    ")
}

// File は1つのファイルの試験を、1つのバイナリにして1つずつ別のプロセスで動かす(file は表示に使う道)
func (r *Runner) File(file string) {
	data, err := os.ReadFile(file)
	if err != nil {
		fmt.Fprintf(r.Out, "✗ %s(読めません)\n%s\n", file, indent(err.Error()))
		r.Failed++
		return
	}
	source := compiler.NormalizeNewlines(string(data))
	abs, _ := filepath.Abs(file)
	ir, cases, serr := compiler.CompileTests(source, filepath.Dir(abs), abs, file, r.match(file))
	if serr != nil {
		fmt.Fprintf(r.Out, "✗ %s(読めません)\n%s\n", file, indent(compiler.FormatError(serr, source, true)))
		r.Failed++
		return
	}
	if len(cases) == 0 {
		return
	}
	rel := strings.TrimSuffix(filepath.ToSlash(file), compiler.SourceSuffix)
	rel = strings.ReplaceAll(strings.TrimLeft(rel, "./"), "../", "")
	exe := native.ExePath(filepath.Join(r.WorkDir, filepath.FromSlash(rel)))
	if err := os.MkdirAll(filepath.Dir(exe), 0o755); err != nil {
		fmt.Fprintf(r.Out, "✗ %s(作れません)\n%s\n", file, indent(err.Error()))
		r.Failed += len(cases)
		return
	}
	ll := exe + ".ll"
	if err := os.WriteFile(ll, []byte(ir), 0o644); err != nil {
		fmt.Fprintf(r.Out, "✗ %s(作れません)\n%s\n", file, indent(err.Error()))
		r.Failed += len(cases)
		return
	}
	defer os.Remove(ll)
	if err := native.BuildWith(ll, exe, r.Opt, r.Extra); err != nil {
		fmt.Fprintf(r.Out, "✗ %s(作れません)\n%s\n", file, indent(strings.TrimPrefix(err.Error(), "エラー: ")))
		r.Failed += len(cases)
		return
	}
	for _, c := range cases {
		var out bytes.Buffer
		cmd := exec.Command(exe, strconv.Itoa(c.Number))
		cmd.Stdout, cmd.Stderr = &out, &out
		if err := cmd.Run(); err != nil {
			fmt.Fprintf(r.Out, "✗ %s %s\n", file, c.Label)
			if s := strings.TrimRight(out.String(), "\n"); s != "" {
				fmt.Fprintln(r.Out, indent(s))
			}
			r.Failed++
			continue
		}
		fmt.Fprintf(r.Out, "✓ %s %s\n", file, c.Label)
		r.Passed++
	}
}

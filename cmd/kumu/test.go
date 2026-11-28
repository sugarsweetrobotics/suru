// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"bytes"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/suru-lang/suru/cmd/internal/lintbin"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/cmd/internal/testrun"
	"github.com/suru-lang/suru/compiler"
)

// TestDir は試験のファイルを置くフォルダの名前
const TestDir = "試験"

// testSuffix で終わる名前の、引数のない定義が試験
const testSuffix = "試験する"

// suruFiles は dir の下の .suru のファイル(出力/ と . で始まるフォルダは除く)を並べて返す
func suruFiles(dir string) ([]string, error) {
	var files []string
	err := filepath.WalkDir(dir, func(path string, e fs.DirEntry, err error) error {
		if err != nil {
			if errors.Is(err, fs.ErrNotExist) {
				return filepath.SkipDir
			}
			return err
		}
		if e.IsDir() && path != dir && (e.Name() == OutDir || strings.HasPrefix(e.Name(), ".")) {
			return filepath.SkipDir
		}
		// 自分の 組.suru を持つ下のフォルダは別のプロジェクトなので、その中は集めない(例/ や結合試験/ のプロジェクト)
		if e.IsDir() && path != dir {
			if _, err := os.Stat(filepath.Join(path, ConfigName)); err == nil {
				return filepath.SkipDir
			}
		}
		if !e.IsDir() && strings.HasSuffix(e.Name(), compiler.SourceSuffix) {
			files = append(files, path)
		}
		return nil
	})
	sort.Strings(files)
	return files, err
}

// testNames はファイルの一番外の「…試験する」(引数なし)の名前を、書いた順に返す
func testNames(program []compiler.Node) []string {
	var names []string
	seen := map[string]bool{}
	for _, n := range program {
		d, ok := n.(*compiler.Define)
		if ok && strings.HasSuffix(d.Name, testSuffix) && len(d.Params) == 0 && !seen[d.Name] {
			seen[d.Name] = true
			names = append(names, d.Name)
		}
	}
	return names
}

// runnerSource は試験のファイル(module の名前で読み込む)の n 番目の試験を、引数で選んで行うプログラム
func runnerSource(importPath, module string, names []string) string {
	var b strings.Builder
	fmt.Fprintf(&b, "# kumu 試験 が作ったファイルです\n「%s」 を 読み込む\n「標準」 を 読み込む\n", importPath)
	b.WriteString("m を 結果無視する とは m を （x を 受け取って （0 を 結果にする） を 返すこと） で 連鎖する\n\n")
	b.WriteString("引数 を 試験選択する とは\n")
	for i, n := range names {
		kw := "もし"
		if i > 0 {
			kw = "そうでなければ もし"
		}
		fmt.Fprintf(&b, "  %s 引数 の 先頭 = 「%d」 ならば （%s内の%s） を 結果無視する\n", kw, i+1, module, n)
	}
	b.WriteString("  そうでなければ 0 を 結果にする\n\n標準内の引数取得してから 試験選択する\n")
	return b.String()
}

// test は 試験/ のファイルの試験を1つずつ別のプロセスで動かす。filters があれば、名前かファイルの道にどれかを含むものだけ
func (k *kumu) test(p *Project, filters []string, opt string, check bool, cb *CBuild) int {
	files, err := suruFiles(filepath.Join(p.Root, TestDir))
	if err != nil {
		return k.fail(err)
	}
	match := func(file, name string) bool {
		if len(filters) == 0 {
			return true
		}
		for _, f := range filters {
			if strings.Contains(name, f) || strings.Contains(file, f) {
				return true
			}
		}
		return false
	}
	passed, failed, total := 0, 0, 0
	// プロジェクトのソースのファイル(試験/・組.suru・出力/ を除く)の、試験のまとまりと例(#193)。
	// ファイルごとに1つのバイナリにして、そのファイルの中で動かす(非公開の名前も使える)
	srcs, err := suruFiles(p.Root)
	if err != nil {
		return k.fail(err)
	}
	r := &testrun.Runner{Out: k.stdout, Opt: opt, Filters: filters, WorkDir: filepath.Join(p.Root, OutDir, TestDir, "ソース"),
		Extra: cb.Args(), Dir: p.Root}
	testsDir := filepath.Join(p.Root, TestDir) + string(filepath.Separator)
	for _, f := range srcs {
		if f == filepath.Join(p.Root, ConfigName) || strings.HasPrefix(f, testsDir) {
			continue
		}
		r.FileAt(f, k.rel(f))
	}
	passed, failed, total = r.Passed, r.Failed, r.Passed+r.Failed
	for _, file := range files {
		rel := k.rel(file)
		data, err := os.ReadFile(file)
		if err != nil {
			return k.fail(err)
		}
		source := compiler.NormalizeNewlines(string(data))
		program, serr := compiler.ParseSource(source, filepath.Dir(file))
		if serr != nil {
			fmt.Fprintf(k.stdout, "✗ %s(読めません)\n%s\n", rel, indent(compiler.FormatError(serr, source, true)))
			failed++
			continue
		}
		var names []string
		for _, n := range testNames(program) {
			if match(rel, n) {
				names = append(names, n)
			}
		}
		if len(names) == 0 {
			continue
		}
		total += len(names)
		// 試験のファイルを読み込むプログラムを 出力/試験/… に作る
		inTests, _ := filepath.Rel(filepath.Join(p.Root, TestDir), file)
		stem := strings.TrimSuffix(inTests, compiler.SourceSuffix)
		runDir := filepath.Join(p.Root, OutDir, TestDir, stem)
		runPath := filepath.Join(runDir, "実行"+compiler.SourceSuffix)
		imp, _ := filepath.Rel(runDir, strings.TrimSuffix(file, compiler.SourceSuffix))
		module := filepath.Base(stem)
		src := runnerSource(filepath.ToSlash(imp), module, names)
		if err := os.MkdirAll(runDir, 0o755); err != nil {
			return k.fail(err)
		}
		if err := os.WriteFile(runPath, []byte(src), 0o644); err != nil {
			return k.fail(err)
		}
		exe := native.ExePath(filepath.Join(runDir, "実行"))
		if _, err := compileTo(src, runPath, exe, opt, check, cb); err != nil {
			fmt.Fprintf(k.stdout, "✗ %s(作れません)\n%s\n", rel, indent(strings.TrimPrefix(err.Error(), "エラー: ")))
			failed += len(names)
			continue
		}
		for i, n := range names {
			var out bytes.Buffer
			c := exec.Command(exe, strconv.Itoa(i+1))
			c.Dir = p.Root
			c.Stdout, c.Stderr = &out, &out
			if err := c.Run(); err != nil {
				fmt.Fprintf(k.stdout, "✗ %s %s\n", rel, n)
				if s := strings.TrimRight(out.String(), "\n"); s != "" {
					fmt.Fprintln(k.stdout, indent(s))
				}
				failed++
				continue
			}
			fmt.Fprintf(k.stdout, "✓ %s %s\n", rel, n)
			passed++
		}
	}
	if total == 0 && failed == 0 {
		fmt.Fprintf(k.stderr, "試験が見つかりません(%s/ のファイルに「…%s」の手順を書くか、ソースのファイルに「以下は「名前」の試験です」・「例えば … は … です」を書きます)\n", TestDir, testSuffix)
		return 0
	}
	fmt.Fprintf(k.stdout, "\n合格 %d・不合格 %d\n", passed, failed)
	if failed > 0 {
		return 1
	}
	return 0
}

func indent(s string) string {
	return "    " + strings.ReplaceAll(s, "\n", "\n    ")
}

// lint はプロジェクトのファイル(組.suru と 出力/ は除く)を点検する
// (--json を付けると、知らせを1行に1つの JSON で出す)
func (k *kumu) lint(args []string) int {
	asJSON := len(args) == 1 && (args[0] == "--json" || args[0] == "--JSON")
	if len(args) != 0 && !asJSON {
		fmt.Fprintln(k.stderr, "使い方: kumu 点検 [--json]")
		return 2
	}
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	files, err := suruFiles(p.Root)
	if err != nil {
		return k.fail(err)
	}
	var paths []string
	for _, f := range files {
		if f != filepath.Join(p.Root, ConfigName) {
			paths = append(paths, k.rel(f))
		}
	}
	if len(paths) == 0 {
		fmt.Fprintln(k.stderr, "点検するファイルがありません")
		return 0
	}
	exe, err := lintbin.Binary("kumu-" + version)
	if err != nil {
		return k.fail(err)
	}
	if asJSON {
		paths = append([]string{"--json"}, paths...)
	}
	c := exec.Command(exe, paths...)
	c.Dir = k.dir
	c.Stdout, c.Stderr = k.stdout, k.stderr
	if err := c.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode()
		}
		return k.fail(err)
	}
	if asJSON {
		return 0
	}
	fmt.Fprintf(k.stderr, "%d 個のファイルを点検しました。知らせることはありません\n", len(paths))
	return 0
}

// format は「kumu 整える [--確認]」: プロジェクトの .suru の空白を整える(点検と同じバイナリの lib/整形.suru。#250)
func (k *kumu) format(args []string) int {
	check := len(args) == 1 && (args[0] == "--確認" || args[0] == "--check")
	if len(args) != 0 && !check {
		fmt.Fprintln(k.stderr, "使い方: kumu 整える [--確認]")
		return 2
	}
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	files, err := suruFiles(p.Root)
	if err != nil {
		return k.fail(err)
	}
	paths := []string{"--整える"}
	if check {
		paths = append(paths, "--確認")
	}
	for _, f := range files {
		if f != filepath.Join(p.Root, ConfigName) {
			paths = append(paths, k.rel(f))
		}
	}
	exe, err := lintbin.Binary("kumu-" + version)
	if err != nil {
		return k.fail(err)
	}
	c := exec.Command(exe, paths...)
	c.Dir = k.dir
	c.Stdout, c.Stderr = k.stdout, k.stderr
	if err := c.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode()
		}
		return k.fail(err)
	}
	return 0
}

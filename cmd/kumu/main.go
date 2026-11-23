// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// kumu(組む)は「する」のプロジェクト管理とビルドの道具。
//
//	kumu 新規 名前     # 名前 のフォルダに雛形を作る(new)
//	kumu 初期化        # 今のフォルダに雛形を作る(init)
//	kumu 作る          # 出力/名前 のバイナリを作る(build)
//	kumu 実行 -- 引数  # 作って実行する(run)
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	suru "github.com/sugarsweetrobotics/suru"
	"github.com/sugarsweetrobotics/suru/cmd/internal/native"
	"github.com/sugarsweetrobotics/suru/compiler"
)

const version = "0.1.0"

const usage = `使い方: kumu <命令> [オプション]

命令:
  新規 名前   名前 のフォルダに雛形を作る(new)
  初期化      今のフォルダに雛形を作る(init)
  作る        出力/ にバイナリを作る(build)
  実行        作って実行する。-- の後ろはプログラムへの引数(run)
  版          kumu の版を出す(version)
  助け        この案内を出す(help)

作る・実行 のオプション:
  -O0 〜 -O3  clang の最適化の強さ(既定は -O2)
  --検査なし  型の検査をしない(--no-check)
`

// commands は命令の名前(日本語と英語の別名)→ 正の名前
var commands = map[string]string{
	"新規": "新規", "new": "新規",
	"初期化": "初期化", "init": "初期化",
	"作る": "作る", "build": "作る",
	"実行": "実行", "run": "実行",
	"版": "版", "version": "版", "--版": "版", "--version": "版",
	"助け": "助け", "help": "助け", "-h": "助け", "--help": "助け",
}

// kumu は1回の呼び出し。テストのために出力先と今のフォルダを持つ
type kumu struct {
	dir            string
	stdout, stderr io.Writer
	stdin          io.Reader
}

func (k *kumu) run(args []string) int {
	if len(args) == 0 {
		fmt.Fprint(k.stderr, usage)
		return 2
	}
	cmd, ok := commands[args[0]]
	if !ok {
		fmt.Fprintf(k.stderr, "「%s」という命令はありません\n\n%s", args[0], usage)
		return 2
	}
	rest := args[1:]
	switch cmd {
	case "版":
		fmt.Fprintf(k.stdout, "kumu %s(する のプロジェクト管理)\n", version)
		return 0
	case "助け":
		fmt.Fprint(k.stdout, usage)
		return 0
	case "新規":
		if len(rest) != 1 {
			fmt.Fprintln(k.stderr, "使い方: kumu 新規 名前")
			return 2
		}
		name := rest[0]
		if err := CreateProject(filepath.Join(k.dir, name), filepath.Base(name), true); err != nil {
			return k.fail(err)
		}
		fmt.Fprintf(k.stderr, "「%s」を作りました(cd %s してから kumu 実行)\n", filepath.Base(name), name)
		return 0
	case "初期化":
		if len(rest) != 0 {
			fmt.Fprintln(k.stderr, "使い方: kumu 初期化")
			return 2
		}
		abs, err := filepath.Abs(k.dir)
		if err != nil {
			return k.fail(err)
		}
		if err := CreateProject(abs, filepath.Base(abs), false); err != nil {
			return k.fail(err)
		}
		fmt.Fprintf(k.stderr, "「%s」を作りました\n", filepath.Base(abs))
		return 0
	}
	// 作る・実行
	opt, check := "-O2", true
	var progArgs []string
	for i := 0; i < len(rest); i++ {
		a := rest[i]
		switch {
		case a == "--":
			progArgs = append(progArgs, rest[i+1:]...)
			i = len(rest)
		case a == "-O0" || a == "-O1" || a == "-O2" || a == "-O3" || a == "-Os":
			opt = a
		case a == "--検査なし" || a == "--no-check":
			check = false
		case cmd == "実行":
			progArgs = append(progArgs, a)
		default:
			fmt.Fprintf(k.stderr, "「%s」は 作る に使えないオプションです\n", a)
			return 2
		}
	}
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	exe, err := k.build(p, opt, check)
	if err != nil {
		return k.fail(err)
	}
	if cmd == "作る" {
		return 0
	}
	c := exec.Command(exe, progArgs...)
	c.Stdin, c.Stdout, c.Stderr = k.stdin, k.stdout, k.stderr
	if err := c.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			return ee.ExitCode()
		}
		return k.fail(err)
	}
	return 0
}

func (k *kumu) fail(err error) int {
	msg := err.Error()
	if !strings.HasPrefix(msg, "エラー") && !strings.HasPrefix(msg, "「"+ConfigName) {
		msg = "エラー: " + msg
	}
	fmt.Fprintln(k.stderr, msg)
	return 1
}

// build は入口のファイルをコンパイルして 出力/名前 を作る。
// IR・最適化・実行時ライブラリが前と同じなら clang を呼ばない
func (k *kumu) build(p *Project, opt string, check bool) (string, error) {
	path := p.EntryPath()
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("入口のファイル「%s」が読めません", p.Entry+compiler.SourceSuffix)
	}
	source := compiler.NormalizeNewlines(string(data))
	ir, serr := compiler.CompileSource(source, filepath.Dir(path), path, check)
	if serr != nil {
		return "", errors.New(compiler.FormatError(serr, source, true))
	}
	out := filepath.Join(p.Root, OutDir)
	if err := os.MkdirAll(out, 0o755); err != nil {
		return "", err
	}
	exe := filepath.Join(out, p.Name)
	h := sha256.New()
	for _, part := range []string{version, opt, ir, string(suru.Runtime)} {
		fmt.Fprintf(h, "%d:%s", len(part), part)
	}
	digest := hex.EncodeToString(h.Sum(nil))
	stamp := filepath.Join(out, "."+p.Name+".stamp")
	if old, err := os.ReadFile(stamp); err == nil && string(old) == digest {
		if _, err := os.Stat(exe); err == nil {
			return exe, nil
		}
	}
	llPath := exe + ".ll"
	if err := os.WriteFile(llPath, []byte(ir), 0o644); err != nil {
		return "", err
	}
	defer os.Remove(llPath)
	if err := native.Build(llPath, exe, opt); err != nil {
		return "", err
	}
	if err := os.WriteFile(stamp, []byte(digest), 0o644); err != nil {
		return "", err
	}
	rel, _ := filepath.Rel(k.dir, exe)
	if rel == "" || strings.HasPrefix(rel, "..") {
		rel = exe
	}
	fmt.Fprintf(k.stderr, "「%s」%s を組みました(%s)\n", p.Name, p.Version, rel)
	return exe, nil
}

func main() {
	compiler.LibFS = mustSub()
	if d := os.Getenv("SURU_LIB"); d != "" {
		compiler.LibDir = d
	}
	dir, err := os.Getwd()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	k := &kumu{dir: dir, stdout: os.Stdout, stderr: os.Stderr, stdin: os.Stdin}
	os.Exit(k.run(os.Args[1:]))
}

func mustSub() fs.FS {
	sub, err := fs.Sub(suru.Lib, "lib")
	if err != nil {
		panic(err)
	}
	return sub
}

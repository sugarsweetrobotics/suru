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

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// version はリリースのときに -ldflags "-X main.version=…" で書きかえる
var version = "0.10.1"

const usage = `使い方: kumu <命令> [オプション]

命令:
  新規 名前   名前 のフォルダに雛形を作る(new)
  初期化      今のフォルダに雛形を作る(init)
  作る        出力/ にバイナリを作る(build)
  実行        作って実行する。-- の後ろはプログラムへの引数(run)
  追加 場所   依存を足す。場所@版 か、版なしなら一番新しいタグ(add)
  削除 名前   依存を外す。名前か場所で書く(remove)
  更新 [名前] 依存を一番新しいタグにする。名前がなければ全部(update)
  取得        依存を取ってきて 組.lock を書く(fetch)
  試験 [名前] 試験/ の「…試験する」を1つずつ動かす(test。名前の一部で選べる)
  点検        プロジェクトの全部のファイルを点検する(check。--json で知らせを JSON で出す)
  公開        確かめて Git のタグ v版 を付ける。push はしない(publish)
  文書        公開の名前の API ドキュメントを docs/api に書く(doc。--雛形 で Sphinx と Read the Docs の設定を書く)
  書き込む    マイコン向けに作って、USB でつないだ基板に書き込む(flash)
  版          kumu の版を出す(version)
  助け        この案内を出す(help)

作る・実行・試験 のオプション:
  -O0 〜 -O3  clang の最適化の強さ(既定は -O2。試験は -O0)
  --検査なし  型の検査をしない(--no-check)

マイコン向け(組.suru に「対象 とは 「arduino-uno」」と書くか、--対象 で選ぶ):
  --対象 名前  基板を選ぶ(--target。` + "arduino-uno・arduino-nano・arduino-nano-old" + `)
  --ポート 道  書き込むシリアルポート(--port。なければ見つけたもの)
  新規・初期化 にも --対象 を付けられます(L チカの雛形を作る)

ウェブアプリ:
  kumu 新規 名前 --対象 web  屋台(suru-lang/web)のウェブアプリの雛形を作る

他の言語から呼ぶ共有ライブラリ(組.suru に「種類 とは 「共有ライブラリ」」と書く):
  kumu 新規 名前 --共有ライブラリ  雛形を作る(--shared)
  kumu 作る  出力/ に lib名前.so(macOS は .dylib、Windows は .dll と .dll.a)と 名前.h を作る
`

// commands は命令の名前(日本語と英語の別名)→ 正の名前
var commands = map[string]string{
	"新規": "新規", "new": "新規",
	"初期化": "初期化", "init": "初期化",
	"作る": "作る", "build": "作る",
	"実行": "実行", "run": "実行",
	"追加": "追加", "add": "追加",
	"削除": "削除", "remove": "削除",
	"更新": "更新", "update": "更新",
	"取得": "取得", "fetch": "取得",
	"試験": "試験", "test": "試験",
	"点検": "点検", "check": "点検", "lint": "点検",
	"公開": "公開", "publish": "公開",
	"文書": "文書", "doc": "文書", "docs": "文書",
	"書き込む": "書き込む", "flash": "書き込む", "upload": "書き込む",
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
		rest, target, ok := targetOption(rest)
		rest, target, ok = sharedOption(rest, target, ok)
		if !ok || len(rest) != 1 {
			fmt.Fprintln(k.stderr, "使い方: kumu 新規 名前 [--対象 基板か web | --共有ライブラリ]")
			return 2
		}
		name := rest[0]
		if err := CreateProject(filepath.Join(k.dir, name), filepath.Base(name), true, target); err != nil {
			return k.fail(err)
		}
		next := "kumu 実行"
		if target == WebTarget {
			next = "kumu 実行。http://localhost:8080/ を開きます"
		} else if target == SharedTarget {
			next = "kumu 作る。出力/ にライブラリとヘッダができます"
		} else if target != "" {
			next = "kumu 書き込む"
		}
		fmt.Fprintf(k.stderr, "「%s」を作りました(cd %s してから %s)\n", filepath.Base(name), name, next)
		return 0
	case "初期化":
		rest, target, ok := targetOption(rest)
		rest, target, ok = sharedOption(rest, target, ok)
		if !ok || len(rest) != 0 {
			fmt.Fprintln(k.stderr, "使い方: kumu 初期化 [--対象 基板か web | --共有ライブラリ]")
			return 2
		}
		abs, err := filepath.Abs(k.dir)
		if err != nil {
			return k.fail(err)
		}
		if err := CreateProject(abs, filepath.Base(abs), false, target); err != nil {
			return k.fail(err)
		}
		fmt.Fprintf(k.stderr, "「%s」を作りました\n", filepath.Base(abs))
		return 0
	case "追加", "削除", "更新", "取得":
		return k.deps(cmd, rest)
	case "点検":
		return k.lint(rest)
	case "公開":
		return k.publish(rest)
	case "文書":
		return k.doc(rest)
	}
	// 作る・実行
	opt, check := "-O2", true
	if cmd == "試験" {
		opt = "-O0"
	}
	var progArgs []string
	target, port := "", ""
	for i := 0; i < len(rest); i++ {
		a := rest[i]
		switch {
		case (a == "--対象" || a == "--target") && i+1 < len(rest) && cmd != "試験":
			target = rest[i+1]
			i++
		case (a == "--ポート" || a == "--port") && i+1 < len(rest) && cmd == "書き込む":
			port = rest[i+1]
			i++
		case a == "--":
			progArgs = append(progArgs, rest[i+1:]...)
			i = len(rest)
		case a == "-O0" || a == "-O1" || a == "-O2" || a == "-O3" || a == "-Os":
			opt = a
		case a == "--検査なし" || a == "--no-check":
			check = false
		case cmd == "実行" || cmd == "試験" && !strings.HasPrefix(a, "-"):
			progArgs = append(progArgs, a)
		default:
			fmt.Fprintf(k.stderr, "「%s」は %s に使えないオプションです\n", a, cmd)
			return 2
		}
	}
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	deps, err := Resolve(p, k.stderr)
	if err != nil {
		return k.fail(err)
	}
	if err := CheckSysDeps(p, deps, k.stderr); err != nil {
		return k.fail(err)
	}
	if p.SharedLib() && target != "" {
		return k.fail(fmt.Errorf("種類が「%s」のプロジェクトは、--対象 で作れません", KindShared))
	}
	if target == "" {
		target = p.Target
	}
	if target != "" {
		return k.mcu(cmd, p, target, port)
	}
	cb, err := PrepareC(p, deps, k.stderr)
	if err != nil {
		return k.fail(err)
	}
	if cmd == "書き込む" {
		return k.fail(fmt.Errorf("書き込む には マイコンの対象 が要ります(%s に「対象 とは 「arduino-uno」」と書くか、--対象 で選んでください)", ConfigName))
	}
	if cmd == "試験" {
		return k.test(p, progArgs, opt, check, cb)
	}
	if p.SharedLib() {
		if cmd == "実行" {
			return k.fail(fmt.Errorf("種類が「%s」のプロジェクトは実行できません。kumu 作る で 出力/ にライブラリとヘッダを作り、ほかの言語から呼びます(試験は kumu 試験)", KindShared))
		}
		if _, err := k.buildShared(p, opt, check, cb); err != nil {
			return k.fail(err)
		}
		return 0
	}
	exe, err := k.build(p, opt, check, cb)
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
func (k *kumu) build(p *Project, opt string, check bool, cb *CBuild) (string, error) {
	path := p.EntryPath()
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("入口のファイル「%s」が読めません", p.Entry+compiler.SourceSuffix)
	}
	exe := native.ExePath(filepath.Join(p.Root, OutDir, p.Name))
	built, err := compileTo(string(data), path, exe, opt, check, cb)
	if err != nil {
		return "", err
	}
	if built {
		fmt.Fprintf(k.stderr, "「%s」%s を組みました(%s)\n", p.Name, p.Version, k.rel(exe))
	}
	return exe, nil
}

// buildShared は入口のファイルを共有ライブラリにして 出力/lib名前.so(.dylib・.dll と .dll.a)と 出力/名前.h を作る(#208)。
// IR・最適化・実行時ライブラリ・Cソースが前と同じなら clang を呼ばない
func (k *kumu) buildShared(p *Project, opt string, check bool, cb *CBuild) (string, error) {
	base, err := p.LibBase()
	if err != nil {
		return "", err
	}
	path := p.EntryPath()
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("入口のファイル「%s」が読めません", p.Entry+compiler.SourceSuffix)
	}
	source := compiler.NormalizeNewlines(string(data))
	ir, serr := compiler.CompileLibrary(source, filepath.Dir(path), path, check)
	if serr != nil {
		return "", errors.New(compiler.FormatError(serr, source, true))
	}
	lib := native.LibPath(filepath.Join(p.Root, OutDir, "lib"+base))
	header := native.HeaderPath(lib, base)
	if err := os.MkdirAll(filepath.Dir(lib), 0o755); err != nil {
		return "", err
	}
	digest := buildDigest(opt, ir, cb, "shared")
	stamp := filepath.Join(filepath.Dir(lib), "."+filepath.Base(lib)+".stamp")
	if old, err := os.ReadFile(stamp); err == nil && string(old) == digest {
		if allExist(native.SharedOutputs(lib, header)) {
			return lib, nil
		}
	}
	llPath := lib + ".ll"
	if err := os.WriteFile(llPath, []byte(ir), 0o644); err != nil {
		return "", err
	}
	defer os.Remove(llPath)
	if _, err := native.BuildSharedWith(llPath, lib, opt, cb.Args()); err != nil {
		return "", err
	}
	if err := os.WriteFile(stamp, []byte(digest), 0o644); err != nil {
		return "", err
	}
	fmt.Fprintf(k.stderr, "「%s」%s を共有ライブラリに組みました(%s・%s)\n", p.Name, p.Version, k.rel(lib), k.rel(header))
	return lib, nil
}

// allExist はファイルが全部あるか
func allExist(paths []string) bool {
	for _, p := range paths {
		if _, err := os.Stat(p); err != nil {
			return false
		}
	}
	return true
}

// buildDigest は作り直しの判定に使う値(kumu の版・最適化・IR・実行時ライブラリ・リンク・Cソース・印)
func buildDigest(opt, ir string, cb *CBuild, mark string) string {
	h := sha256.New()
	cdigest := ""
	if cb != nil {
		cdigest = cb.Digest
	}
	parts := []string{version, opt, ir, string(suru.Runtime), strings.Join(compiler.LinkFlags(ir), " "), cdigest}
	if mark != "" {
		parts = append(parts, mark)
	}
	for _, part := range parts {
		fmt.Fprintf(h, "%d:%s", len(part), part)
	}
	return hex.EncodeToString(h.Sum(nil))
}

// rel は今のフォルダからの道(上に出るなら絶対パス)
func (k *kumu) rel(path string) string {
	rel, err := filepath.Rel(k.dir, path)
	if err != nil || rel == "" || strings.HasPrefix(rel, "..") {
		return path
	}
	return rel
}

// compileTo は path(中身は source)をコンパイルして exe を作る。
// IR・最適化・実行時ライブラリ・Cソースが前と同じなら clang を呼ばない(built が false)
func compileTo(source, path, exe, opt string, check bool, cb *CBuild) (built bool, err error) {
	source = compiler.NormalizeNewlines(source)
	ir, serr := compiler.CompileSource(source, filepath.Dir(path), path, check)
	if serr != nil {
		return false, errors.New(compiler.FormatError(serr, source, true))
	}
	if err := os.MkdirAll(filepath.Dir(exe), 0o755); err != nil {
		return false, err
	}
	digest := buildDigest(opt, ir, cb, "")
	stamp := filepath.Join(filepath.Dir(exe), "."+filepath.Base(exe)+".stamp")
	if old, err := os.ReadFile(stamp); err == nil && string(old) == digest {
		if _, err := os.Stat(exe); err == nil {
			return false, nil
		}
	}
	llPath := exe + ".ll"
	if err := os.WriteFile(llPath, []byte(ir), 0o644); err != nil {
		return false, err
	}
	defer os.Remove(llPath)
	if err := native.BuildWith(llPath, exe, opt, cb.Args()); err != nil {
		return false, err
	}
	return true, os.WriteFile(stamp, []byte(digest), 0o644)
}

func main() {
	compiler.LibFS = mustSub()
	native.InstallExpander()
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

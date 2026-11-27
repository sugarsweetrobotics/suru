// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"time"

	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// その場でコンパイルして動かす(#229)。
//
//	suruc --実行 [--検査なし] [--json] [-O0|…] prog.suru 引数…   # キャッシュにバイナリを作って動かす
//	suruc --実行準備 [--検査なし] [--json] [-O0|…] prog.suru     # バイナリを作って、その道を1行で出す(suru の起動口が使う)
//
// バイナリは キャッシュ/run-<キー> に置き、キーは suruc の版・最適化・対象・C コンパイラ・IR・リンクの引数から作る。
// IR には読み込んだファイル(lib・依存も)が全部入るので、どれかが変われば作り直す。
// --実行準備 は、ここでは作れない(C コンパイラがない・kumu の Cソース を使う)とき、終了コード exitNeedInterpreter で終わる。

// exitNeedInterpreter は「ここではコンパイルできないので、インタプリタで動かしてほしい」の終了コード(--実行準備 だけ)
const exitNeedInterpreter = 3

// runCacheKeep は使われないまま、これより古くなったバイナリを消す
const runCacheKeep = 30 * 24 * time.Hour

type runOptions struct {
	check  bool
	asJSON bool
	opt    string
}

// parseRunArgs は --実行 の引数を、オプション・プログラムのファイル・プログラムに渡す引数に分ける
func parseRunArgs(args []string) (runOptions, string, []string, bool) {
	o := runOptions{check: true, opt: "-O0"}
	for i, a := range args {
		switch {
		case a == "--検査なし" || a == "--no-check":
			o.check = false
		case a == "--json" || a == "--JSON":
			o.asJSON = true
		case a == "-O0" || a == "-O1" || a == "-O2" || a == "-O3" || a == "-Os":
			o.opt = a
		case strings.HasPrefix(a, "-"):
			return o, "", nil, false
		default:
			return o, a, args[i+1:], true
		}
	}
	return o, "", nil, false
}

// runCommand は --実行(prepareOnly なら --実行準備)
func runCommand(args []string, prepareOnly bool) int {
	o, src, progArgs, ok := parseRunArgs(args)
	if !ok || (prepareOnly && len(progArgs) > 0) {
		if prepareOnly {
			fmt.Fprintln(os.Stderr, "使い方: suruc --実行準備 [--検査なし] [--json] [-O0|-O1|-O2|-O3] プログラム.suru")
		} else {
			fmt.Fprintln(os.Stderr, "使い方: suruc --実行 [--検査なし] [--json] [-O0|-O1|-O2|-O3] プログラム.suru 引数…")
		}
		return 2
	}
	exe, code := prepareRun(src, o, prepareOnly)
	if exe == "" {
		return code
	}
	if prepareOnly {
		fmt.Println(exe)
		return 0
	}
	if o.asJSON {
		// 実行時のエラーも1行の JSON で(runtime/suru_rt.c の fail_msg)
		os.Setenv("SURU_ERROR_JSON", src)
	}
	return execProgram(exe, progArgs)
}

// prepareRun はキャッシュのバイナリを用意して、その道を返す。できなければ "" と終了コード
func prepareRun(src string, o runOptions, prepareOnly bool) (string, int) {
	data, err := os.ReadFile(src)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ファイル「%s」が読めません: %v\n", src, err)
		return "", 1
	}
	source := compiler.NormalizeNewlines(string(data))
	abs, _ := filepath.Abs(src)
	baseDir := filepath.Dir(abs)
	cc := native.FindCC()
	reason := ""
	if cc == "" {
		reason = "C コンパイラ(clang)がありません"
	} else if usesCSources(baseDir) {
		reason = "kumu の Cソース・リンク引数を使うプロジェクトです(kumu 作る で作れます)"
	}
	if reason != "" {
		if prepareOnly {
			if cc == "" {
				hintOnce()
			}
			return "", exitNeedInterpreter
		}
		fmt.Fprintln(os.Stderr, "エラー: その場でコンパイルできません: "+reason)
		return "", 1
	}
	ir, serr := compiler.CompileSource(source, baseDir, abs, o.check)
	if serr != nil {
		// 実行の前の検査のエラー: suru(インタプリタ)と同じ形で出す
		if o.asJSON {
			fmt.Fprintln(os.Stderr, compiler.ErrorJSON(serr, "型", src))
		} else {
			fmt.Fprintln(os.Stderr, compiler.FormatError(serr, source, true))
		}
		return "", 1
	}
	exe, err := cachedBinary(ir, cc, o.opt)
	if err != nil {
		fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
		return "", 1
	}
	return exe, 0
}

// cachedBinary は ir のバイナリをキャッシュから返す(なければ作る)
func cachedBinary(ir, cc, opt string) (string, error) {
	h := sha256.New()
	for _, s := range []string{version, opt, compiler.Target(), cc, runtime.GOOS, runtime.GOARCH,
		strings.Join(compiler.LinkFlags(ir), "\x00"), ir} {
		h.Write([]byte(s))
		h.Write([]byte{0})
	}
	key := hex.EncodeToString(h.Sum(nil))[:24]
	dir := filepath.Join(native.CacheDir(), "run")
	exe := native.ExePath(filepath.Join(dir, key))
	if _, err := os.Stat(exe); err == nil {
		now := time.Now()
		os.Chtimes(exe, now, now) // 使った印(古いものを消すときに使う)
		return exe, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	pruneRunCache(dir)
	tmp := filepath.Join(dir, fmt.Sprintf("%s.%d.tmp", key, os.Getpid()))
	llPath := tmp + ".ll"
	if err := os.WriteFile(llPath, []byte(ir), 0o644); err != nil {
		return "", err
	}
	defer os.Remove(llPath)
	if err := native.Build(llPath, tmp, opt); err != nil {
		return "", err
	}
	// 同時に作っていても、できあがったものを置き換えるだけ
	if err := os.Rename(native.ExePath(tmp), exe); err != nil {
		os.Remove(native.ExePath(tmp))
		if _, serr := os.Stat(exe); serr == nil {
			return exe, nil
		}
		return "", err
	}
	return exe, nil
}

// pruneRunCache は長く使っていないバイナリと、残った作りかけを消す
func pruneRunCache(dir string) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return
	}
	for _, e := range entries {
		info, err := e.Info()
		if err != nil {
			continue
		}
		old := time.Since(info.ModTime())
		if old > runCacheKeep || (strings.Contains(e.Name(), ".tmp") && old > time.Hour) {
			os.Remove(filepath.Join(dir, e.Name()))
		}
	}
}

var cSourceLine = regexp.MustCompile(`(?m)^[ \t　]*(Cソース|リンク引数)[ \t　]+とは`)

// usesCSources は baseDir のプロジェクトか依存が kumu の Cソース・リンク引数を使うか
// (suruc はそれをつながないので、インタプリタか kumu 作る で動かす)
func usesCSources(baseDir string) bool {
	for _, p := range compiler.FindPackages(baseDir) {
		data, err := os.ReadFile(filepath.Join(p.Dir, compiler.ProjectConfig))
		if err == nil && cSourceLine.Match(data) {
			return true
		}
	}
	return false
}

// hintOnce は C コンパイラがないことを、1回だけ知らせる(印をキャッシュに置く)
func hintOnce() {
	mark := filepath.Join(native.CacheDir(), "no-cc-hint")
	if _, err := os.Stat(mark); err == nil {
		return
	}
	msg := "お知らせ: clang を入れると、suru はプログラムをコンパイルして速く動かします(今はインタプリタで動かします)。"
	switch runtime.GOOS {
	case "darwin":
		msg += "\n  macOS: xcode-select --install"
	case "windows":
		msg += "\n  Windows: MSYS2 の UCRT64 で pacman -S mingw-w64-ucrt-x86_64-clang mingw-w64-ucrt-x86_64-lld"
	default:
		msg += "\n  Linux: sudo apt install clang(Debian・Ubuntu)など"
	}
	fmt.Fprintln(os.Stderr, msg+"\n  このお知らせは1回だけ出します。")
	if os.MkdirAll(filepath.Dir(mark), 0o755) == nil {
		os.WriteFile(mark, nil, 0o644)
	}
}

// waitProgram は exe を動かして、その終了コードを返す(標準入出力はそのまま渡す)
func waitProgram(exe string, args []string) int {
	cmd := exec.Command(exe, args...)
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			if ee.ExitCode() >= 0 {
				return ee.ExitCode()
			}
			return 1
		}
		fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
		return 1
	}
	return 0
}

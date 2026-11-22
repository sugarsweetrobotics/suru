// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// suruc は「する」のコンパイラ(Go 版)。する のプログラムを LLVM IR にして、clang でバイナリにする。
//
//	suruc prog.suru            # → prog(実行ファイル)
//	suruc prog.suru -o 名前    # 出力の名前
//	suruc --ll prog.suru       # LLVM IR(prog.ll)だけを出す
//	suruc -O0 prog.suru        # clang の最適化の強さ(-O0 〜 -O3、既定は -O2)
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"runtime/debug"
	"strings"

	suru "github.com/sugarsweetrobotics/suru"
	"github.com/sugarsweetrobotics/suru/compiler"
)

const version = "0.1.0"

const usage = "使い方: suruc [--ll] [--検査なし] [-O0|-O1|-O2|-O3] プログラム.suru [-o 出力]"

func findCC() string {
	for _, name := range []string{os.Getenv("CC"), "clang"} {
		if name == "" {
			continue
		}
		if p, err := exec.LookPath(name); err == nil && p != "" {
			return name
		}
	}
	return ""
}

func cacheDir() string {
	if d := os.Getenv("XDG_CACHE_HOME"); d != "" {
		return filepath.Join(d, "suru")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "suru")
	}
	return filepath.Join(home, ".cache", "suru")
}

// runtimeObject は実行時ライブラリをコンパイルしたもの(中身が変わらなければ作り直さない)
func runtimeObject(cc string) (string, error) {
	sum := sha256.Sum256(append(append([]byte{}, suru.Runtime...), []byte(cc)...))
	digest := hex.EncodeToString(sum[:])[:16]
	dir := cacheDir()
	obj := filepath.Join(dir, "suru_rt-"+digest+".o")
	if _, err := os.Stat(obj); err == nil {
		return obj, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	src := filepath.Join(dir, "suru_rt-"+digest+".c")
	if err := os.WriteFile(src, suru.Runtime, 0o644); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.%d.tmp", obj, os.Getpid())
	out, err := exec.Command(cc, "-O2", "-w", "-c", "-x", "c", src, "-o", tmp).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("実行時ライブラリのコンパイルに失敗しました:\n%s", out)
	}
	return obj, os.Rename(tmp, obj)
}

func build(llPath, out, opt string) error {
	cc := findCC()
	if cc == "" {
		return fmt.Errorf("バイナリを作るには clang が必要です(LLVM IR だけなら --ll を付けてください)")
	}
	rt, err := runtimeObject(cc)
	if err != nil {
		return err
	}
	ir, err := os.ReadFile(llPath)
	if err != nil {
		return err
	}
	args := append([]string{opt, "-w", llPath, rt, "-o", out}, compiler.LinkFlags(string(ir))...)
	cmd := exec.Command(cc, append(args, "-lm", "-lpthread")...)
	if b, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("clang でのビルドに失敗しました:\n%s", b)
	}
	return nil
}

func run(args []string) int {
	if len(args) >= 1 && (args[0] == "--version" || args[0] == "--版") {
		fmt.Printf("する %s(Go 版コンパイラ)\n", version)
		return 0
	}
	llOnly := false
	check := true
	opt := "-O2"
	out := ""
	var files []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--ll":
			llOnly = true
		case a == "--検査なし" || a == "--no-check":
			check = false
		case a == "-O0" || a == "-O1" || a == "-O2" || a == "-O3" || a == "-Os":
			opt = a
		case a == "-o":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, usage)
				return 2
			}
			out = args[i+1]
			i++
		case strings.HasPrefix(a, "--"):
		default:
			files = append(files, a)
		}
	}
	if len(files) != 1 {
		fmt.Fprintln(os.Stderr, usage)
		return 2
	}
	srcPath := files[0]
	data, err := os.ReadFile(srcPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ファイル「%s」が読めません: %v\n", srcPath, err)
		return 1
	}
	source := compiler.NormalizeNewlines(string(data))
	abs, _ := filepath.Abs(srcPath)
	baseDir := filepath.Dir(abs)
	stem := strings.TrimSuffix(srcPath, filepath.Ext(srcPath))
	ir, serr := compiler.CompileSource(source, baseDir, abs, check)
	if serr != nil {
		fmt.Fprintln(os.Stderr, compiler.FormatError(serr, source, true))
		return 1
	}
	llPath := stem + ".ll"
	if llOnly && out != "" {
		llPath = out
	}
	if err := os.WriteFile(llPath, []byte(ir), 0o644); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if !llOnly {
		if out == "" {
			out = stem
		}
		if err := build(llPath, out, opt); err != nil {
			fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
			return 1
		}
		os.Remove(llPath)
	}
	return 0
}

func main() {
	// すぐ終わるプログラムなので、ごみ集めは控えめにする
	debug.SetGCPercent(400)
	compiler.LibFS = mustSub()
	if d := os.Getenv("SURU_LIB"); d != "" {
		compiler.LibDir = d
	}
	os.Exit(run(os.Args[1:]))
}

func mustSub() fs.FS {
	sub, err := fs.Sub(suru.Lib, "lib")
	if err != nil {
		panic(err)
	}
	return sub
}

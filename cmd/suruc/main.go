// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// suruc は「する」のコンパイラ(Go 版)。する のプログラムを LLVM IR にして、clang でバイナリにする。
//
//	suruc prog.suru            # → prog(実行ファイル)
//	suruc prog.suru -o 名前    # 出力の名前
//	suruc --ll prog.suru       # LLVM IR(prog.ll)だけを出す
//	suruc -O0 prog.suru        # clang の最適化の強さ(-O0 〜 -O3、既定は -O2)
//	suruc --検査 prog.suru      # 構文と型だけを調べる(suru --検査 と同じ)
//	suruc --json prog.suru     # エラーを1行の JSON で出す(suru --json と同じ形)
package main

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/cmd/internal/mcu"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// version はリリースのときに -ldflags "-X main.version=…" で書きかえる
var version = "0.8.0"

const usage = "使い方: suruc [--ll] [--検査 | --検査なし] [--json] [-O0|-O1|-O2|-O3] [--対象 基板] プログラム.suru [-o 出力]"

func run(args []string) int {
	if len(args) >= 1 && (args[0] == "--version" || args[0] == "--版") {
		fmt.Printf("する %s(Go 版コンパイラ)\n", version)
		return 0
	}
	llOnly := false
	check := true
	checkOnly := false
	asJSON := false
	opt := "-O2"
	out := ""
	target := ""
	var files []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--ll":
			llOnly = true
		case a == "--検査なし" || a == "--no-check":
			check = false
		case a == "--検査" || a == "--check":
			checkOnly = true
		case a == "--json" || a == "--JSON":
			asJSON = true
		case a == "-O0" || a == "-O1" || a == "-O2" || a == "-O3" || a == "-Os":
			opt = a
		case a == "-o":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, usage)
				return 2
			}
			out = args[i+1]
			i++
		case a == "--対象" || a == "--target":
			if i+1 >= len(args) {
				fmt.Fprintln(os.Stderr, usage)
				return 2
			}
			target = args[i+1]
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
	report := func(e *compiler.SuruError) int {
		if asJSON {
			fmt.Fprintln(os.Stderr, compiler.ErrorJSON(e, "コンパイル", srcPath))
		} else {
			fmt.Fprintln(os.Stderr, compiler.FormatError(e, source, true))
		}
		return 1
	}
	if checkOnly {
		if serr := compiler.CheckSource(source, baseDir, srcPath); serr != nil {
			return report(serr)
		}
		if !asJSON {
			fmt.Println("型の検査で問題は見つかりませんでした")
		}
		return 0
	}
	if target != "" {
		return buildMCU(source, abs, stem, out, target, llOnly)
	}
	ir, serr := compiler.CompileSource(source, baseDir, abs, check)
	if serr != nil {
		return report(serr)
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
		if err := native.Build(llPath, out, opt); err != nil {
			fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
			return 1
		}
		os.Remove(llPath)
	}
	return 0
}

// buildMCU はマイコン向けの .hex(--ll なら IR)を作る
func buildMCU(source, abs, stem, out, target string, llOnly bool) int {
	b, err := mcu.Lookup(target)
	if err != nil {
		fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
		return 1
	}
	ir, err := mcu.Compile(source, abs, b)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	if llOnly {
		if out == "" {
			out = stem + ".ll"
		}
		if err := os.WriteFile(out, []byte(ir), 0o644); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		return 0
	}
	tools, err := mcu.FindTools(false)
	if err != nil {
		fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
		return 1
	}
	if out == "" {
		out = stem
	}
	out = strings.TrimSuffix(out, ".hex")
	r, err := mcu.Build(ir, out, b, tools)
	if err != nil {
		fmt.Fprintln(os.Stderr, "エラー: "+err.Error())
		return 1
	}
	if s := r.Summary(); s != "" {
		fmt.Fprintln(os.Stderr, s)
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

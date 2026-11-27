// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"path/filepath"
	"strings"
)

// LinkFlags は IR の始めの「; suru-link: 」の行から、外部のライブラリをリンクする clang の引数を作る
func LinkFlags(ir string) []string {
	var flags []string
	for _, line := range strings.Split(ir, "\n") {
		if !strings.HasPrefix(line, ";") {
			break
		}
		if strings.HasPrefix(line, LinkMark) {
			lib := strings.TrimPrefix(line, LinkMark)
			if filepath.IsAbs(lib) {
				flags = append(flags, lib)
				if !TargetWindows() { // Windows の DLL は .exe と同じフォルダか PATH から探す
					flags = append(flags, "-Wl,-rpath,"+filepath.Dir(lib))
				}
			} else if lib != "c" && !(TargetWindows() && windowsNoLibs[lib]) {
				flags = append(append(flags, pkgConfigLinkFlags(lib)...), "-l"+lib)
			}
		}
	}
	return flags
}

// ExportSymbols は IR の始めの「; suru-export: 」の行から、外部に出す関数の C の名前を読む(#208)
func ExportSymbols(ir string) []string {
	var out []string
	for _, e := range Exports(ir) {
		out = append(out, e.Symbol)
	}
	return out
}

// CompileSource は する のプログラムを LLVM IR の文字列にする。間違いがあれば *SuruError
// (Kind に 構文・型・コンパイル のどれかの印を付ける)
func CompileSource(source, baseDir, path string, check bool) (ir string, err *SuruError) {
	return compileSource(source, baseDir, path, check, false, nil)
}

// CompileSourceWith は依存(名前 → Package)を決めて CompileSource する。nil なら baseDir から探す。
// 展開・導出の関数は、それを読み込んだプロジェクトの依存で探す(依存の中には 組.lock がないため)
func CompileSourceWith(source, baseDir, path string, check bool, pkgs map[string]Package) (ir string, err *SuruError) {
	return compileSource(source, baseDir, path, check, false, pkgs)
}

// CompileLibrary は共有ライブラリにするプログラムを LLVM IR にする(#208)。
// 「以下は外部に出す関数です」が要り、一番外には定義だけを書ける(読み込んだだけで何かが行われないように)
func CompileLibrary(source, baseDir, path string, check bool) (ir string, err *SuruError) {
	return compileSource(source, baseDir, path, check, true, nil)
}

// checkLibrary は共有ライブラリにするプログラムの一番外を調べる
func checkLibrary(program []Node) {
	found := false
	for _, s := range program {
		if _, ok := s.(*Export); ok {
			found = true
		}
	}
	if !found {
		raise(Pos{}, "共有ライブラリにするには、「"+KwIkaExport+"です」で外部に出す関数を書きます"+
			"(「"+KwIkaExport+"です」「  二倍する は 「nibai」」「以上です」)")
	}
	for _, s := range program {
		if _, ok := s.(*Define); ok || isTopLevelOnly(s) {
			continue
		}
		raise(firstLine(s), "共有ライブラリにするファイルの一番外には、定義だけを書きます(一番外の文は、ライブラリを読み込んだときに行われてしまいます)")
	}
}

func compileSource(source, baseDir, path string, check, lib bool, pkgs map[string]Package) (ir string, err *SuruError) {
	ctx := NewParseContext(baseDir)
	if pkgs != nil {
		ctx.Packages = pkgs
	}
	ctx.Path = filePath(path)
	var program []Node
	if err = tagged("構文", func() { program = ParseProgram(source, ctx) }); err != nil {
		return
	}
	if check {
		if err = tagged("型", func() { TypeCheck(program, ctx) }); err != nil {
			return
		}
	}
	program = DropTests(program) // 試験のまとまりと例は通常のビルドでは捨てる(#193)
	err = tagged("コンパイル", func() {
		if lib {
			checkLibrary(program)
		}
		checkDefinitions(program, ctx)
		setLineBase(ctx, source)
		ir = newCompiler(ctx, source).compile(program, path)
	})
	return
}

// CheckSource は する のプログラムの構文と型だけを調べる(suru --検査 と同じ)。間違いがあれば *SuruError
func CheckSource(source, baseDir, path string) *SuruError {
	ctx := NewParseContext(baseDir)
	ctx.Path = filePath(path)
	var program []Node
	if err := tagged("構文", func() { program = ParseProgram(source, ctx) }); err != nil {
		return err
	}
	return tagged("型", func() { TypeCheck(program, ctx) })
}

// tagged は f を動かして、エラーがあれば kind の印を付けて返す
func tagged(kind string, f func()) *SuruError {
	err := try(f)
	if err != nil && err.Kind == "" {
		err.Kind = kind
	}
	return err
}

// filePath は解析するファイルの絶対パス(ファイルでなければ "")
func filePath(path string) string {
	if path == "" || strings.HasPrefix(path, "<") {
		return ""
	}
	return absPath(path)
}

// ParseSource は する のプログラムを構文解析だけする(型の検査はしない)。間違いがあれば *SuruError
func ParseSource(source, baseDir string) (program []Node, err *SuruError) {
	err = try(func() {
		program = ParseProgram(source, NewParseContext(baseDir))
	})
	return
}

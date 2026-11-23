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
				flags = append(flags, lib, "-Wl,-rpath,"+filepath.Dir(lib))
			} else if lib != "c" {
				flags = append(append(flags, pkgConfigLinkFlags(lib)...), "-l"+lib)
			}
		}
	}
	return flags
}

// CompileSource は する のプログラムを LLVM IR の文字列にする。間違いがあれば *SuruError
func CompileSource(source, baseDir, path string, check bool) (ir string, err *SuruError) {
	err = try(func() {
		ctx := NewParseContext(baseDir)
		program := ParseProgram(source, ctx)
		if check {
			TypeCheck(program, ctx)
		}
		checkDefinitions(program, ctx)
		ir = newCompiler(ctx, source).compile(program, path)
	})
	return
}

// ParseSource は する のプログラムを構文解析だけする(型の検査はしない)。間違いがあれば *SuruError
func ParseSource(source, baseDir string) (program []Node, err *SuruError) {
	err = try(func() {
		program = ParseProgram(source, NewParseContext(baseDir))
	})
	return
}

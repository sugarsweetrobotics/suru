// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package lintbin は点検(lib/点検.suru、する で書いた linter)をバイナリにする(suru-ls と kumu で使う)。
// バイナリは初めの1回だけ作ってキャッシュに置く(点検が使う lib のファイル・実行時ライブラリ・C コンパイラが変われば作り直す)。
package lintbin

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// lintSource は点検を動かすだけのプログラム(suru.py の LINT_SOURCE と同じ)
const lintSource = "「点検」 を 読み込む\n点検内の点検実行する\n"

var importRe = regexp.MustCompile(`(?m)^[ \t　]*「([^「」]+)」[ \t　]*を[ \t　]*読み込`)

// readLib は lib のファイルを読む(LibDir があればそこ、なければ埋め込んだもの)
func readLib(name string) ([]byte, bool) {
	if compiler.LibDir != "" {
		b, err := os.ReadFile(filepath.Join(compiler.LibDir, name))
		return b, err == nil
	}
	if compiler.LibFS != nil {
		b, err := fs.ReadFile(compiler.LibFS, name)
		return b, err == nil
	}
	return nil, false
}

// libFiles は点検が使う lib のファイルの名前(点検.suru から「「X」 を 読み込む」をたどったものと 基本.suru。suru.py の
// lint_lib_files と同じ)。キャッシュの名前はこのファイルだけで決めるので、ほかの lib のファイルを変えても作り直さない
func libFiles() []string {
	found := map[string]bool{}
	todo := []string{"点検", "基本"}
	for len(todo) > 0 {
		name := todo[len(todo)-1]
		todo = todo[:len(todo)-1]
		if found[name] {
			continue
		}
		b, ok := readLib(name + compiler.SourceSuffix)
		if !ok {
			continue
		}
		found[name] = true
		for _, m := range importRe.FindAllStringSubmatch(string(b), -1) {
			todo = append(todo, m[1])
		}
	}
	var names []string
	for n := range found {
		names = append(names, n+compiler.SourceSuffix)
	}
	sort.Strings(names)
	return names
}

// Binary は点検のバイナリの道。salt は呼ぶ側の名前と版(キャッシュの名前を分ける)
func Binary(salt string) (string, error) {
	cc := native.FindCC()
	if cc == "" {
		return "", fmt.Errorf("clang がないので点検はしません")
	}
	h := sha256.New()
	h.Write([]byte(salt + "\x00" + cc + "\x00"))
	h.Write(suru.Runtime)
	for _, n := range libFiles() {
		b, _ := readLib(n)
		h.Write([]byte(n + "\x00"))
		h.Write(b)
	}
	dir := native.CacheDir()
	exe := filepath.Join(dir, "点検-"+hex.EncodeToString(h.Sum(nil))[:16])
	if _, err := os.Stat(exe); err == nil {
		return exe, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	base := compiler.LibDir
	if base == "" {
		base = "\x00lib"
	}
	ir, serr := compiler.CompileSource(lintSource, base, filepath.Join(base, "点検実行.suru"), true)
	if serr != nil {
		return "", fmt.Errorf("点検をコンパイルできません: %s", serr.Message)
	}
	tmp := fmt.Sprintf("%s.%d", exe, os.Getpid())
	if err := os.WriteFile(tmp+".ll", []byte(ir), 0o644); err != nil {
		return "", err
	}
	defer os.Remove(tmp + ".ll")
	if err := native.Build(tmp+".ll", tmp, "-O2"); err != nil {
		return "", err
	}
	return exe, os.Rename(tmp, exe)
}

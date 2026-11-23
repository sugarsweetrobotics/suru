// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package lintbin は点検(lib/点検.suru、する で書いた linter)をバイナリにする(suru-ls と kumu で使う)。
// バイナリは初めの1回だけ作ってキャッシュに置く(lib・実行時ライブラリ・C コンパイラが変われば作り直す)。
package lintbin

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// lintSource は点検を動かすだけのプログラム(suru.py の LINT_SOURCE と同じ)
const lintSource = "「点検」 を 読み込む\n点検内の点検実行する\n"

// Binary は点検のバイナリの道。salt は呼ぶ側の名前と版(キャッシュの名前を分ける)
func Binary(salt string) (string, error) {
	cc := native.FindCC()
	if cc == "" {
		return "", fmt.Errorf("clang がないので点検はしません")
	}
	h := sha256.New()
	h.Write([]byte(salt + "\x00" + cc + "\x00"))
	h.Write(suru.Runtime)
	var names []string
	files := map[string][]byte{}
	if compiler.LibFS != nil {
		_ = fs.WalkDir(compiler.LibFS, ".", func(p string, e fs.DirEntry, err error) error {
			if err == nil && !e.IsDir() && strings.HasSuffix(p, compiler.SourceSuffix) {
				if b, err := fs.ReadFile(compiler.LibFS, p); err == nil {
					names = append(names, p)
					files[p] = b
				}
			}
			return nil
		})
	}
	if compiler.LibDir != "" {
		ents, _ := os.ReadDir(compiler.LibDir)
		names = names[:0]
		for _, e := range ents {
			if strings.HasSuffix(e.Name(), compiler.SourceSuffix) {
				if b, err := os.ReadFile(filepath.Join(compiler.LibDir, e.Name())); err == nil {
					names = append(names, e.Name())
					files[e.Name()] = b
				}
			}
		}
	}
	sort.Strings(names)
	for _, n := range names {
		h.Write([]byte(n + "\x00"))
		h.Write(files[n])
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

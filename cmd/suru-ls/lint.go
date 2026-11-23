// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// 点検(lib/点検.suru、する で書いた linter)をバイナリにして、知らせを「警告」として出す。
// バイナリは初めの1回だけ作ってキャッシュに置く(lib・実行時ライブラリ・C コンパイラが変われば作り直す)。
// clang がなければ点検の知らせは出さない(型の間違いはこれまでどおり出す)。

// lintSource は点検を動かすだけのプログラム(suru.py の LINT_SOURCE と同じ)
const lintSource = "「点検」 を 読み込む\n点検内の点検実行する\n"

// lintNote は点検の知らせ1つ
type lintNote struct {
	Line, Col int
	Rule      string
	Message   string
}

// lintBinary は点検のバイナリの道。作れなければ ""
func lintBinary() (string, error) {
	cc := native.FindCC()
	if cc == "" {
		return "", fmt.Errorf("clang がないので点検はしません")
	}
	h := sha256.New()
	h.Write([]byte(version + "\x00" + cc + "\x00"))
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
	exe := filepath.Join(dir, "点検-ls-"+hex.EncodeToString(h.Sum(nil))[:16])
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

// runLint は text を path のファイルとして点検する(保存していない中身は一時ファイルに書いて渡す)
func runLint(exe, path, text string) ([]lintNote, error) {
	f, err := os.CreateTemp("", "suru-ls-*.suru")
	if err != nil {
		return nil, err
	}
	defer os.Remove(f.Name())
	if _, err := f.WriteString(text); err != nil {
		f.Close()
		return nil, err
	}
	f.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, exe, "--代わり", f.Name(), path)
	cmd.Env = os.Environ()
	if compiler.LibDir != "" {
		cmd.Env = append(cmd.Env, "SURU_LIB="+compiler.LibDir)
	}
	out, err := cmd.Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); !ok || ee.ExitCode() != 1 {
			return nil, err // 1 は「知らせがあった」
		}
	}
	return parseLint(string(out), path), nil
}

// parseLint は「道:行:桁: 規則: 説明」の行を読む
func parseLint(out, path string) []lintNote {
	var notes []lintNote
	for _, l := range strings.Split(out, "\n") {
		rest, ok := strings.CutPrefix(l, path+":")
		if !ok {
			continue
		}
		parts := strings.SplitN(rest, ": ", 3)
		if len(parts) != 3 {
			continue
		}
		lc := strings.SplitN(parts[0], ":", 2)
		if len(lc) != 2 {
			continue
		}
		line, err1 := strconv.Atoi(lc[0])
		col, err2 := strconv.Atoi(lc[1])
		if err1 != nil || err2 != nil {
			continue
		}
		notes = append(notes, lintNote{line, col, parts[1], parts[2]})
	}
	return notes
}

// lintDiagnostics は点検の知らせを LSP の警告にする
func lintDiagnostics(d *document) []map[string]any {
	out := []map[string]any{}
	for _, n := range d.lint {
		if n.Line < 1 || n.Line > len(d.lines) {
			continue
		}
		r := wordRange(d.analysis, d.lines, n.Line, n.Col)
		out = append(out, map[string]any{"range": r, "severity": 2, "source": "点検", "code": n.Rule, "message": n.Message})
	}
	return out
}

// silenceEdit は「# 点検しない: 規則」をその行の終わりに足す編集。「点検しない:」がもうあれば規則だけを足す。
// 「# 点検しない」(全部を黙らせる)がもう書いてあれば、足すものはない(ok が false)
func silenceEdit(lines []string, line int, rule string) (r rng, text string, ok bool) {
	src := lineText(lines, line)
	end := toUTF16(lines, line, len([]rune(src))+1)
	switch {
	case strings.Contains(src, "点検しない:") || strings.Contains(src, "点検しない："):
		return rng{end, end}, " " + rule, true
	case strings.Contains(src, "点検しない"):
		return rng{}, "", false
	}
	return rng{end, end}, "  # 点検しない: " + rule, true
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package native は LLVM IR を clang でバイナリにする(suruc と suru-ls で使う)。
package native

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/compiler"
)

// FindCC は使える C コンパイラ($CC か clang)。なければ ""
func FindCC() string {
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

// CacheDir は作ったものを置くフォルダ($XDG_CACHE_HOME/suru か ~/.cache/suru)
func CacheDir() string {
	if d := os.Getenv("XDG_CACHE_HOME"); d != "" {
		return filepath.Join(d, "suru")
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "suru")
	}
	return filepath.Join(home, ".cache", "suru")
}

// RuntimeObject は実行時ライブラリをコンパイルしたもの(中身が変わらなければ作り直さない)
func RuntimeObject(cc string) (string, error) {
	sum := sha256.Sum256(append(append([]byte{}, suru.Runtime...), []byte(cc)...))
	digest := hex.EncodeToString(sum[:])[:16]
	dir := CacheDir()
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

// Build は llPath の LLVM IR を、実行時ライブラリとつないで out のバイナリにする
func Build(llPath, out, opt string) error { return BuildWith(llPath, out, opt, nil) }

// BuildWith は Build に、リンクするオブジェクトや引数(kumu の Cソース・リンク引数)を足したもの
func BuildWith(llPath, out, opt string, extra []string) error {
	cc := FindCC()
	if cc == "" {
		return fmt.Errorf("バイナリを作るには clang が必要です(LLVM IR だけなら --ll を付けてください)")
	}
	rt, err := RuntimeObject(cc)
	if err != nil {
		return err
	}
	ir, err := os.ReadFile(llPath)
	if err != nil {
		return err
	}
	args := append(append([]string{opt, "-w", llPath, rt, "-o", out}, extra...), compiler.LinkFlags(string(ir))...)
	cmd := exec.Command(cc, append(args, "-lm", "-lpthread")...)
	if b, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("clang でのビルドに失敗しました:\n%s", b)
	}
	return nil
}

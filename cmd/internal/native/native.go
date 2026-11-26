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
	"strings"

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

// TargetArgs は clang に渡す対象(SURU_TARGET があるときだけ)
func TargetArgs() []string {
	if t := compiler.Target(); t != "" {
		return []string{"--target=" + t}
	}
	return nil
}

// ExePath は作るプログラムの道。Windows 向けなら .exe を付ける
func ExePath(out string) string {
	if compiler.TargetWindows() && !strings.EqualFold(filepath.Ext(out), ".exe") {
		return out + ".exe"
	}
	return out
}

// RuntimeObject は実行時ライブラリをコンパイルしたもの(中身が変わらなければ作り直さない)
func RuntimeObject(cc string) (string, error) {
	sum := sha256.Sum256(append(append([]byte{}, suru.Runtime...), []byte(cc+"\x00"+compiler.Target())...))
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
	out, err := exec.Command(cc, append(TargetArgs(), "-O2", "-w", "-c", "-x", "c", src, "-o", tmp)...).CombinedOutput()
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
	args := append(TargetArgs(), opt, "-w", llPath, rt, "-o", ExePath(out))
	args = append(append(args, extra...), compiler.LinkFlags(string(ir))...)
	if compiler.TargetWindows() {
		// pthread(winpthreads)は中に入れて、libwinpthread-1.dll なしで動くようにする
		args = append(args, "-lm", "-Wl,-Bstatic", "-lpthread", "-Wl,-Bdynamic", "-lws2_32")
		if m := manifestObject(); m != "" {
			args = append(args, m)
		}
	} else {
		args = append(args, "-lm", "-lpthread")
	}
	cmd := exec.Command(cc, args...)
	if b, err := cmd.CombinedOutput(); err != nil {
		return fmt.Errorf("clang でのビルドに失敗しました:\n%s", b)
	}
	return nil
}

// windowsManifest は Windows のプログラムに埋め込む印。ファイルの道などの文字を UTF-8 で扱うようにする
// (activeCodePage。Windows 10 1903 以降。これで fopen などに日本語の道をそのまま渡せる)
const windowsManifest = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
    </windowsSettings>
  </application>
</assembly>
`

// manifestObject は windowsManifest をリソースにしたオブジェクト(windres で作り、置いておく)。
// windres がなければ "" (埋め込まずに作る)
func manifestObject() string {
	var tools []string
	if t := compiler.Target(); t != "" {
		tools = append(tools, t+"-windres")
	}
	tools = append(tools, "llvm-windres", "windres")
	tool := ""
	for _, name := range tools {
		if p, err := exec.LookPath(name); err == nil && p != "" {
			tool = name
			break
		}
	}
	if tool == "" {
		return ""
	}
	sum := sha256.Sum256([]byte(windowsManifest + "\x00" + tool))
	dir := filepath.Join(CacheDir(), "manifest-"+hex.EncodeToString(sum[:])[:16])
	obj := filepath.Join(dir, "manifest.o")
	if _, err := os.Stat(obj); err == nil {
		return obj
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return ""
	}
	if os.WriteFile(filepath.Join(dir, "suru.manifest"), []byte(windowsManifest), 0o644) != nil ||
		os.WriteFile(filepath.Join(dir, "manifest.rc"), []byte("1 24 \"suru.manifest\"\n"), 0o644) != nil {
		return ""
	}
	tmp := fmt.Sprintf("%s.%d.tmp", obj, os.Getpid())
	c := exec.Command(tool, "-O", "coff", "-i", "manifest.rc", "-o", filepath.Base(tmp))
	c.Dir = dir
	if c.Run() != nil || os.Rename(tmp, obj) != nil {
		return ""
	}
	return obj
}

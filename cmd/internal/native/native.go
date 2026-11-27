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
	"runtime"
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
func RuntimeObject(cc string) (string, error) { return runtimeObject(cc, "suru_rt-", nil) }

// libFlags は共有ライブラリの形の実行時ライブラリ(main なし、名前を隠す)を作る引数(#208)
var libFlags = []string{"-DSURU_LIB", "-fPIC", "-fvisibility=hidden"}

func runtimeObject(cc, prefix string, flags []string) (string, error) {
	sum := sha256.Sum256(append(append([]byte{}, suru.Runtime...), []byte(cc+"\x00"+compiler.Target())...))
	digest := hex.EncodeToString(sum[:])[:16]
	dir := CacheDir()
	obj := filepath.Join(dir, prefix+digest+".o")
	if _, err := os.Stat(obj); err == nil {
		return obj, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	src := filepath.Join(dir, prefix+digest+".c")
	if err := os.WriteFile(src, suru.Runtime, 0o644); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.%d.tmp", obj, os.Getpid())
	args := append(append(TargetArgs(), flags...), "-O2", "-w", "-c", "-x", "c", src, "-o", tmp)
	out, err := exec.Command(cc, args...).CombinedOutput()
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
	exe := ExePath(out)
	linkOut, done := exe, func() error { return nil }
	if compiler.TargetWindows() && !windowsLLD() && !isASCII(exe) {
		// GNU ld は Windows で日本語の道に書けないので、一時フォルダに作ってから移す
		linkOut, done = asciiTemp(exe)
	}
	args := append(TargetArgs(), opt, "-w", llPath, rt, "-o", linkOut)
	args = append(append(args, extra...), compiler.LinkFlags(string(ir))...)
	if compiler.TargetWindows() {
		if windowsLLD() {
			// lld は日本語の道も読み書きできる(GNU ld は Windows の ANSI の道しか扱えない)
			args = append(args, "-fuse-ld=lld")
		}
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
	return done()
}

// LibPrefix は共有ライブラリの道から、補助の関数の頭の名前を決める(libkeisan.so → keisan)。C の名前にできなければエラー
func LibPrefix(out string) (string, error) {
	base := filepath.Base(out)
	for _, ext := range []string{".so", ".dylib", ".dll"} {
		if strings.HasSuffix(base, ext) {
			base = strings.TrimSuffix(base, ext)
			break
		}
	}
	base = strings.TrimPrefix(base, "lib")
	ok := base != ""
	for i, c := range base {
		alpha := (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_'
		if !(alpha || (i > 0 && c >= '0' && c <= '9')) {
			ok = false
		}
	}
	if !ok {
		return "", fmt.Errorf("共有ライブラリの名前「%s」から補助の関数の名前(「名前_last_error」など)を作れません。"+
			"-o には英字・数字・「_」だけの名前を付けてください(「-o libkeisan.so」)", filepath.Base(out))
	}
	return base, nil
}

// LibPath は共有ライブラリの道。拡張子がなければ OS に合わせて付ける(.so・.dylib・.dll)
func LibPath(out string) string {
	ext := ".so"
	if compiler.TargetWindows() {
		ext = ".dll"
	} else if targetDarwin() {
		ext = ".dylib"
	}
	switch filepath.Ext(out) {
	case ".so", ".dylib", ".dll":
		return out
	}
	return out + ext
}

func targetDarwin() bool {
	t := compiler.Target()
	if t == "" {
		return runtime.GOOS == "darwin"
	}
	return strings.Contains(t, "apple") || strings.Contains(t, "darwin")
}

// BuildShared は llPath の LLVM IR を、共有ライブラリの形の実行時ライブラリとつないで共有ライブラリにし、
// 同じ所に C のヘッダ(頭の名前.h)も書く(#208)。
// 外に見せるのは、出す関数と補助の関数だけ(実行時ライブラリの名前は隠すので、する のライブラリが2つあってもぶつからない)
func BuildShared(llPath, out, opt string) (string, error) {
	cc := FindCC()
	if cc == "" {
		return "", fmt.Errorf("共有ライブラリを作るには clang が必要です(LLVM IR だけなら --ll を付けてください)")
	}
	if compiler.TargetWindows() {
		return "", fmt.Errorf("Windows の共有ライブラリ(.dll)はまだ作れません")
	}
	lib := LibPath(out)
	prefix, err := LibPrefix(lib)
	if err != nil {
		return "", err
	}
	rt, err := runtimeObject(cc, "suru_rt_lib-", libFlags)
	if err != nil {
		return "", err
	}
	ir, err := os.ReadFile(llPath)
	if err != nil {
		return "", err
	}
	syms := append(compiler.ExportSymbols(string(ir)), compiler.LibHelperSymbols(prefix)...)
	dir, err := os.MkdirTemp("", "suru-lib-")
	if err != nil {
		return "", err
	}
	defer os.RemoveAll(dir)
	shim := filepath.Join(dir, "shim.c")
	if err := os.WriteFile(shim, []byte(compiler.LibShim(prefix)), 0o644); err != nil {
		return "", err
	}
	args := append(TargetArgs(), opt, "-w", "-fPIC", llPath, rt, shim, "-o", lib)
	if targetDarwin() {
		list := filepath.Join(dir, "exports.txt")
		var b strings.Builder
		for _, s := range syms {
			b.WriteString("_" + s + "\n")
		}
		if err := os.WriteFile(list, []byte(b.String()), 0o644); err != nil {
			return "", err
		}
		args = append(args, "-dynamiclib", "-Wl,-install_name,@rpath/"+filepath.Base(lib), "-Wl,-exported_symbols_list,"+list)
	} else {
		script := filepath.Join(dir, "exports.map")
		if err := os.WriteFile(script, []byte("{\n  global:\n    "+strings.Join(syms, ";\n    ")+";\n  local: *;\n};\n"), 0o644); err != nil {
			return "", err
		}
		args = append(args, "-shared", "-Wl,--version-script="+script)
	}
	args = append(append(args, compiler.LinkFlags(string(ir))...), "-lm", "-lpthread")
	if b, err := exec.Command(cc, args...).CombinedOutput(); err != nil {
		return "", fmt.Errorf("clang でのビルドに失敗しました:\n%s", b)
	}
	if err := os.WriteFile(HeaderPath(lib, prefix), []byte(compiler.ExportHeader(string(ir), prefix)), 0o644); err != nil {
		return "", err
	}
	return lib, nil
}

// HeaderPath は共有ライブラリと同じ所に置く C のヘッダの道(libkeisan.so → keisan.h、#208 段階2)
func HeaderPath(lib, prefix string) string {
	return filepath.Join(filepath.Dir(lib), prefix+".h")
}

// windowsLLD は Windows 向けのリンクに lld(ld.lld)を使えるか
func windowsLLD() bool {
	_, err := exec.LookPath("ld.lld")
	return err == nil
}

func isASCII(s string) bool {
	for i := 0; i < len(s); i++ {
		if s[i] >= 0x80 {
			return false
		}
	}
	return true
}

// asciiTemp は一時フォルダの ASCII の道と、そこから dst へ移す関数
func asciiTemp(dst string) (string, func() error) {
	dir, err := os.MkdirTemp("", "suru-link-")
	if err != nil {
		return dst, func() error { return nil }
	}
	tmp := filepath.Join(dir, "out.exe")
	return tmp, func() error {
		defer os.RemoveAll(dir)
		b, err := os.ReadFile(tmp)
		if err != nil {
			return err
		}
		return os.WriteFile(dst, b, 0o755)
	}
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

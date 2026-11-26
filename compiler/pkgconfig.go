// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
)

// システムの C のライブラリを pkg-config で探す。
// Homebrew(/opt/homebrew/lib)のように、リンカーや dlopen が普通は探さないフォルダにある
// ライブラリを、外部の関数の短い名前(「pcre2-8」)から見つけるために使う。suru.py の _pkgconfig_libdir と同じ。

// noPkgConfigLibs は pkg-config で探さない名前(どこにでもある C のライブラリ)
var noPkgConfigLibs = map[string]bool{"c": true, "m": true, "pthread": true, "dl": true, "rt": true}

var pkgConfigCache sync.Map // 名前 → フォルダ("" なら見つからない)

// PkgConfig は pkg-config の命令の名前($PKG_CONFIG か pkg-config)。なければ ""
func PkgConfig() string {
	for _, name := range []string{os.Getenv("PKG_CONFIG"), "pkg-config", "pkgconf"} {
		if name == "" {
			continue
		}
		if p, err := exec.LookPath(name); err == nil {
			return p
		}
	}
	return ""
}

// PkgConfigLibDir は短い名前のライブラリ(lib名前.so・lib名前.dylib)があるフォルダを、
// pkg-config の「lib名前」か「名前」の libdir から探す。見つからなければ ""
func PkgConfigLibDir(name string) string {
	if noPkgConfigLibs[name] || strings.ContainsAny(name, `/\`) {
		return ""
	}
	if d, ok := pkgConfigCache.Load(name); ok {
		return d.(string)
	}
	dir := ""
	if pc := PkgConfig(); pc != "" {
		for _, module := range []string{"lib" + name, name} {
			out, err := exec.Command(pc, "--variable=libdir", module).Output()
			d := strings.TrimSpace(string(out))
			if err != nil || d == "" {
				continue
			}
			if hasSharedLib(d, name) {
				dir = d
				break
			}
		}
	}
	pkgConfigCache.Store(name, dir)
	return dir
}

func hasSharedLib(dir, name string) bool {
	exts := []string{".so", ".dylib", ".a"}
	if runtime.GOOS == "darwin" {
		exts = []string{".dylib", ".so", ".a"}
	} else if runtime.GOOS == "windows" {
		exts = []string{".dll.a", ".a", ".lib"} // MinGW の DLL を使うためのライブラリ(DLL そのものは bin にある)
	}
	for _, ext := range exts {
		if _, err := os.Stat(filepath.Join(dir, "lib"+name+ext)); err == nil {
			return true
		}
	}
	return false
}

// standardLibDir はリンカーと dlopen が普通に探すフォルダか(rpath を足さない)
func standardLibDir(dir string) bool {
	dir = filepath.Clean(dir)
	for _, d := range []string{"/lib", "/lib64", "/usr/lib", "/usr/lib64"} {
		if dir == d || filepath.Dir(dir) == d && strings.Contains(filepath.Base(dir), "-linux-") {
			return true
		}
	}
	return false
}

// pkgConfigLinkFlags は短い名前のライブラリを、pkg-config のフォルダから探す clang の引数
func pkgConfigLinkFlags(name string) []string {
	dir := PkgConfigLibDir(name)
	if dir == "" || standardLibDir(dir) {
		return nil
	}
	if TargetWindows() {
		return []string{"-L" + dir}
	}
	return []string{"-L" + dir, "-Wl,-rpath," + dir}
}

// ResetPkgConfigCache は覚えた探した結果を忘れる(試験で使う)
func ResetPkgConfigCache() { pkgConfigCache = sync.Map{} }

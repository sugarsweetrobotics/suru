// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"os"
	"path/filepath"
	"strings"
)

// プロジェクトの依存(kumu が取ってきたライブラリ)を、読み込みで探せるようにする。
// suru.py の find_packages と同じ決まりで探す。

// ProjectConfig はプロジェクトの設定ファイルの名前
const ProjectConfig = "組" + SourceSuffix

// ProjectLock は依存を固めたファイルの名前(kumu が書く)
const ProjectLock = "組.lock"

// Package は依存の1つ(名前で読み込む)
type Package struct {
	Name string
	Dir  string // 中身のフォルダ(まだ取ってきていなければ無い)
}

// KumuHome は kumu が取ってきたものを置くフォルダ($KUMU_HOME か ~/.kumu)
func KumuHome() string {
	if d := os.Getenv("KUMU_HOME"); d != "" {
		return d
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return filepath.Join(os.TempDir(), "kumu")
	}
	return filepath.Join(home, ".kumu")
}

// IsLocalSource は依存の場所がフォルダのパス(「../部品集」など)か
func IsLocalSource(src string) bool {
	return strings.HasPrefix(src, ".") || filepath.IsAbs(src) || strings.HasPrefix(src, "/")
}

// PackageDir は依存の中身を置くフォルダ。root はプロジェクトのフォルダ
func PackageDir(root, src, version string) string {
	if IsLocalSource(src) {
		if filepath.IsAbs(src) {
			return filepath.Clean(src)
		}
		return filepath.Join(root, src)
	}
	key := src
	if i := strings.Index(key, "://"); i >= 0 {
		key = key[:i] + "/" + strings.TrimLeft(key[i+3:], "/")
	}
	key = strings.TrimSuffix(strings.ReplaceAll(key, ":", "_"), ".git")
	return filepath.Join(KumuHome(), "依存", filepath.FromSlash(key)+"@"+version)
}

// ReadLock は 組.lock の中身を読む。行は「名前 場所 版 コミット ハッシュ」をタブで区切ったもの
func ReadLock(root string) []LockEntry {
	data, err := os.ReadFile(filepath.Join(root, ProjectLock))
	if err != nil {
		return nil
	}
	var out []LockEntry
	for _, line := range strings.Split(NormalizeNewlines(string(data)), "\n") {
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		f := strings.Split(line, "\t")
		if len(f) < 3 {
			continue
		}
		e := LockEntry{Name: f[0], Source: f[1], Version: f[2]}
		if len(f) >= 5 {
			e.Commit, e.Hash = f[3], f[4]
		}
		out = append(out, e)
	}
	return out
}

// LockEntry は 組.lock の1行
type LockEntry struct {
	Name, Source, Version, Commit, Hash string
}

// FindPackages は dir から上へ 組.suru を探し、隣の 組.lock に書いた依存を返す(名前 → Package)
func FindPackages(dir string) map[string]Package {
	out := map[string]Package{}
	if dir == "" || strings.HasPrefix(dir, embeddedLibPrefix) || dir == strings.TrimSuffix(embeddedLibPrefix, "/") {
		return out
	}
	d := absPath(dir)
	for {
		if data, err := os.ReadFile(filepath.Join(d, ProjectConfig)); err == nil {
			// プロジェクト自身も、組.suru の名前で読み込める(試験/ のファイルから使う)
			if name := projectName(string(data)); name != "" {
				out[name] = Package{name, d}
			}
			for _, e := range ReadLock(d) {
				out[e.Name] = Package{e.Name, PackageDir(d, e.Source, e.Version)}
			}
			return out
		}
		parent := filepath.Dir(d)
		if parent == d {
			return out
		}
		d = parent
	}
}

// packagePath は読み込む名前「X」「X/部品」が依存のものなら、そのファイルのパス
func packagePath(name string, ctx *ParseContext, line Pos) (string, bool) {
	if ctx.Packages == nil {
		ctx.Packages = FindPackages(ctx.BaseDir)
	}
	first, rest, _ := strings.Cut(filepath.ToSlash(strings.TrimSuffix(name, SourceSuffix)), "/")
	pkg, ok := ctx.Packages[first]
	if !ok {
		return "", false
	}
	if _, err := os.Stat(pkg.Dir); err != nil {
		raise(line, "依存の「"+first+"」がまだ取ってきてありません(kumu 作る か kumu 取得 で取ってきます)")
	}
	if rest == "" {
		rest = first
	}
	return absPath(filepath.Join(pkg.Dir, filepath.FromSlash(rest)+SourceSuffix)), true
}

// projectName は 組.suru の「名前 とは 「…」」(読めなければ "")
func projectName(source string) (name string) {
	_ = try(func() {
		for _, n := range ParseProgram(NormalizeNewlines(source), NewParseContext(".")) {
			if d, ok := n.(*Define); ok && d.Name == "名前" {
				if s, ok := d.Body.(*Str); ok {
					name = s.Value
				}
			}
		}
	})
	return
}

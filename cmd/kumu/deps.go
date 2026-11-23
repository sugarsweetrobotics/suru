// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// 依存を集める。
//
// 依存は Git のリポジトリ(版は Git のタグ「v1.2.0」か「1.2.0」)か、手元のフォルダ。
// 取ってきたものは KumuHome()/依存/ に置き、プロジェクトごとには写さない。
// 同じ場所の依存を違う版で求められたら、一番新しい版を使う(Go の最小版選択と同じ)。
// 組.lock には、使う版とコミットと中身のハッシュを書き、次からは中身が同じかを確かめる。

// Resolved は使うことに決めた依存の1つ
type Resolved struct {
	Name, Source, Version, Commit, Hash, Dir string
}

type resolver struct {
	root     *Project
	stderr   io.Writer
	selected map[string]string // 場所 → 版(Git のもの)
	locals   map[string]bool   // 手元のフォルダの場所
	configs  map[string]*Project
}

// Resolve は p の依存を(足りなければ取ってきて)集め、組.lock を書く
func Resolve(p *Project, stderr io.Writer) ([]Resolved, error) {
	r := &resolver{root: p, stderr: stderr, selected: map[string]string{}, locals: map[string]bool{}, configs: map[string]*Project{}}
	for _, d := range p.Deps {
		if err := r.visit(d, true, ""); err != nil {
			return nil, err
		}
	}
	var out []Resolved
	byName := map[string]string{}
	add := func(src, ver string) error {
		dir := compiler.PackageDir(p.Root, src, ver)
		cfg := r.configs[src+"@"+ver]
		if prev, ok := byName[cfg.Name]; ok {
			return fmt.Errorf("依存「%s」と「%s」が、どちらも「%s」という名前です", prev, src, cfg.Name)
		}
		byName[cfg.Name] = src
		if isLibName(cfg.Name) {
			return fmt.Errorf("依存「%s」の名前「%s」は標準のライブラリと同じです", src, cfg.Name)
		}
		if _, err := os.Stat(filepath.Join(dir, cfg.Name+compiler.SourceSuffix)); err != nil {
			return fmt.Errorf("依存「%s」に「%s%s」がありません(ライブラリは、名前と同じファイルを読み込まれるファイルにします)", src, cfg.Name, compiler.SourceSuffix)
		}
		res := Resolved{Name: cfg.Name, Source: src, Version: ver, Dir: dir}
		if ver != "" {
			res.Version = ver
			if b, err := os.ReadFile(dir + ".commit"); err == nil {
				res.Commit = strings.TrimSpace(string(b))
			}
			h, err := hashDir(dir)
			if err != nil {
				return err
			}
			res.Hash = h
		} else {
			res.Version, res.Commit, res.Hash = "-", "-", "-"
		}
		out = append(out, res)
		return nil
	}
	for src := range r.locals {
		if err := add(src, ""); err != nil {
			return nil, err
		}
	}
	for src, ver := range r.selected {
		if err := add(src, ver); err != nil {
			return nil, err
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	// 前の 組.lock と、同じ版のコミットと中身が同じかを確かめる
	for _, old := range compiler.ReadLock(p.Root) {
		for _, n := range out {
			if n.Source == old.Source && n.Version == old.Version && n.Version != "-" {
				if old.Commit != "" && n.Commit != "" && old.Commit != n.Commit {
					return nil, fmt.Errorf("依存「%s」%s のコミットが %s と違います(%s → %s)。タグが動かされたかもしれません", n.Source, n.Version, compiler.ProjectLock, short(old.Commit), short(n.Commit))
				}
				if old.Hash != "" && old.Hash != n.Hash {
					return nil, fmt.Errorf("依存「%s」%s の中身が %s と違います(%s を消すと取り直します)", n.Source, n.Version, compiler.ProjectLock, n.Dir)
				}
			}
		}
	}
	return out, writeLock(p.Root, out)
}

func short(c string) string {
	if len(c) > 12 {
		return c[:12]
	}
	return c
}

func (r *resolver) visit(d Dep, fromRoot bool, parent string) error {
	if d.Version == "" {
		if !fromRoot {
			return fmt.Errorf("依存「%s」の中の「%s」はフォルダのパスです(フォルダのパスはプロジェクトの 組.suru でだけ使えます)", parent, d.Source)
		}
		if r.locals[d.Source] {
			return nil
		}
		dir := compiler.PackageDir(r.root.Root, d.Source, "")
		cfg, err := FindProjectAt(dir)
		if err != nil {
			return fmt.Errorf("依存「%s」: %v", d.Source, err)
		}
		r.locals[d.Source] = true
		r.configs[d.Source+"@"] = cfg
		for _, sub := range cfg.Deps {
			if err := r.visit(sub, false, d.Source); err != nil {
				return err
			}
		}
		return nil
	}
	if cur, ok := r.selected[d.Source]; ok && compareVersions(cur, d.Version) >= 0 {
		return nil
	}
	dir, err := r.fetch(d)
	if err != nil {
		return err
	}
	cfg, err := FindProjectAt(dir)
	if err != nil {
		return fmt.Errorf("依存「%s」: %v", d, err)
	}
	r.selected[d.Source] = d.Version
	r.configs[d.String()] = cfg
	for _, sub := range cfg.Deps {
		if err := r.visit(sub, false, d.String()); err != nil {
			return err
		}
	}
	return nil
}

// FindProjectAt は dir の 組.suru を読む(上のフォルダは探さない)
func FindProjectAt(dir string) (*Project, error) {
	data, err := os.ReadFile(filepath.Join(dir, ConfigName))
	if err != nil {
		return nil, fmt.Errorf("「%s」がありません", ConfigName)
	}
	return ParseConfig(string(data), dir)
}

// gitURL は依存の場所から git に渡す URL を作る
func gitURL(src string) string {
	if strings.Contains(src, "://") {
		return src
	}
	return "https://" + src
}

func git(args ...string) (string, error) {
	cmd := exec.Command("git", args...)
	cmd.Env = append(os.Environ(), "GIT_TERMINAL_PROMPT=0")
	b, err := cmd.CombinedOutput()
	if err != nil {
		if errors.Is(err, exec.ErrNotFound) {
			return "", errors.New("依存を取ってくるには git が必要です")
		}
		return string(b), err
	}
	return string(b), nil
}

// fetch は Git の依存を(まだなければ)取ってきて、そのフォルダを返す
func (r *resolver) fetch(d Dep) (string, error) {
	dir := compiler.PackageDir(r.root.Root, d.Source, d.Version)
	if _, err := os.Stat(dir); err == nil {
		return dir, nil
	}
	if err := os.MkdirAll(filepath.Dir(dir), 0o755); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.tmp-%d", dir, os.Getpid())
	os.RemoveAll(tmp)
	defer os.RemoveAll(tmp)
	var lastOut string
	ok := false
	for _, tag := range []string{"v" + d.Version, d.Version} {
		out, err := git("-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", tag, gitURL(d.Source), tmp)
		if err == nil {
			ok = true
			break
		}
		if out == "" {
			return "", err
		}
		lastOut = out
		os.RemoveAll(tmp)
	}
	if !ok {
		return "", fmt.Errorf("依存「%s」を取ってこられません(タグ v%s か %s があるか確かめてください):\n%s", d, d.Version, d.Version, strings.TrimSpace(lastOut))
	}
	commit, err := git("-C", tmp, "rev-parse", "HEAD")
	if err != nil {
		return "", fmt.Errorf("依存「%s」のコミットがわかりません: %s", d, commit)
	}
	if err := os.RemoveAll(filepath.Join(tmp, ".git")); err != nil {
		return "", err
	}
	if err := os.WriteFile(dir+".commit", []byte(strings.TrimSpace(commit)+"\n"), 0o644); err != nil {
		return "", err
	}
	if err := os.Rename(tmp, dir); err != nil {
		return "", err
	}
	fmt.Fprintf(r.stderr, "「%s」を取ってきました\n", d)
	return dir, nil
}

// LatestVersion は Git のタグから一番新しい版を探す
func LatestVersion(src string) (string, error) {
	out, err := git("ls-remote", "--tags", "--refs", gitURL(src))
	if err != nil {
		if out == "" {
			return "", err
		}
		return "", fmt.Errorf("「%s」のタグを読めません:\n%s", src, strings.TrimSpace(out))
	}
	best := ""
	for _, line := range strings.Split(out, "\n") {
		_, ref, ok := strings.Cut(strings.TrimSpace(line), "refs/tags/")
		if !ok {
			continue
		}
		v := strings.TrimPrefix(ref, "v")
		if !isVersion(v) {
			continue
		}
		if best == "" || compareVersions(v, best) > 0 {
			best = v
		}
	}
	if best == "" {
		return "", fmt.Errorf("「%s」に版のタグ(v1.0.0 など)がありません", src)
	}
	return best, nil
}

func isVersion(v string) bool {
	parts := strings.Split(v, ".")
	for _, p := range parts {
		if _, err := strconv.Atoi(p); err != nil {
			return false
		}
	}
	return len(parts) >= 1
}

// compareVersions は版を比べる(数の部分は数として)。a が新しければ正
func compareVersions(a, b string) int {
	pa, pb := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < len(pa) || i < len(pb); i++ {
		x, y := "0", "0"
		if i < len(pa) {
			x = pa[i]
		}
		if i < len(pb) {
			y = pb[i]
		}
		nx, ex := strconv.Atoi(x)
		ny, ey := strconv.Atoi(y)
		switch {
		case ex == nil && ey == nil && nx != ny:
			if nx > ny {
				return 1
			}
			return -1
		case (ex != nil || ey != nil) && x != y:
			return strings.Compare(x, y)
		}
	}
	return 0
}

// hashDir はフォルダの中身のハッシュ(.git と 出力 は除く)
func hashDir(dir string) (string, error) {
	h := sha256.New()
	var files []string
	err := filepath.WalkDir(dir, func(path string, e fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if e.IsDir() && path != dir && (e.Name() == ".git" || e.Name() == OutDir) {
			return filepath.SkipDir
		}
		if e.Type().IsRegular() {
			rel, _ := filepath.Rel(dir, path)
			files = append(files, filepath.ToSlash(rel))
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	sort.Strings(files)
	for _, f := range files {
		b, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(f)))
		if err != nil {
			return "", err
		}
		fmt.Fprintf(h, "%d:%s%d:", len(f), f, len(b))
		h.Write(b)
	}
	return "sha256-" + hex.EncodeToString(h.Sum(nil)), nil
}

func isLibName(name string) bool {
	if compiler.LibDir != "" {
		if _, err := os.Stat(filepath.Join(compiler.LibDir, name+compiler.SourceSuffix)); err == nil {
			return true
		}
	}
	if compiler.LibFS != nil {
		if _, err := fs.Stat(compiler.LibFS, name+compiler.SourceSuffix); err == nil {
			return true
		}
	}
	return false
}

const lockHeader = "# kumu が書いたファイルです。手で書きかえないでください(名前・場所・版・コミット・中身のハッシュ)\n"

// writeLock は 組.lock を書く(依存がなければ消す。中身が同じなら書かない)
func writeLock(root string, deps []Resolved) error {
	path := filepath.Join(root, compiler.ProjectLock)
	if len(deps) == 0 {
		if err := os.Remove(path); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		return nil
	}
	var b strings.Builder
	b.WriteString(lockHeader)
	for _, d := range deps {
		fmt.Fprintf(&b, "%s\t%s\t%s\t%s\t%s\n", d.Name, d.Source, d.Version, d.Commit, d.Hash)
	}
	if old, err := os.ReadFile(path); err == nil && string(old) == b.String() {
		return nil
	}
	return os.WriteFile(path, []byte(b.String()), 0o644)
}

// deps は 追加・削除・更新・取得
func (k *kumu) deps(cmd string, args []string) int {
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	cfgPath := filepath.Join(p.Root, ConfigName)
	before, err := os.ReadFile(cfgPath)
	if err != nil {
		return k.fail(err)
	}
	deps := append([]Dep{}, p.Deps...)
	names := map[string]string{} // 名前 → 場所(組.lock から)
	for _, e := range compiler.ReadLock(p.Root) {
		names[e.Name] = e.Source
	}
	find := func(arg string) int {
		src := arg
		if s, ok := names[arg]; ok {
			src = s
		}
		src = strings.TrimSuffix(filepath.ToSlash(src), "/")
		for i, d := range deps {
			if d.Source == src {
				return i
			}
		}
		return -1
	}
	switch cmd {
	case "追加":
		if len(args) == 0 {
			fmt.Fprintln(k.stderr, "使い方: kumu 追加 場所[@版] …")
			return 2
		}
		for _, a := range args {
			d, err := ParseDep(a)
			if err != nil && !compiler.IsLocalSource(a) && !strings.Contains(a, "@") {
				d = Dep{Source: strings.TrimSuffix(a, "/")}
				if d.Version, err = LatestVersion(d.Source); err != nil {
					return k.fail(err)
				}
			} else if err != nil {
				return k.fail(err)
			}
			if i := find(d.Source); i >= 0 {
				deps[i] = d
			} else {
				deps = append(deps, d)
			}
			fmt.Fprintf(k.stderr, "依存に「%s」を足しました\n", d)
		}
	case "削除":
		if len(args) == 0 {
			fmt.Fprintln(k.stderr, "使い方: kumu 削除 名前 …")
			return 2
		}
		for _, a := range args {
			i := find(a)
			if i < 0 {
				return k.fail(fmt.Errorf("依存に「%s」はありません", a))
			}
			fmt.Fprintf(k.stderr, "依存から「%s」を外しました\n", deps[i])
			deps = append(deps[:i], deps[i+1:]...)
		}
	case "更新":
		targets := map[int]bool{}
		for _, a := range args {
			i := find(a)
			if i < 0 {
				return k.fail(fmt.Errorf("依存に「%s」はありません", a))
			}
			targets[i] = true
		}
		for i, d := range deps {
			if d.Version == "" || (len(args) > 0 && !targets[i]) {
				continue
			}
			v, err := LatestVersion(d.Source)
			if err != nil {
				return k.fail(err)
			}
			if v != d.Version {
				fmt.Fprintf(k.stderr, "「%s」を %s から %s にしました\n", d.Source, d.Version, v)
				deps[i].Version = v
			}
		}
	case "取得":
		if len(args) != 0 {
			fmt.Fprintln(k.stderr, "使い方: kumu 取得")
			return 2
		}
	}
	if cmd != "取得" {
		if err := p.WriteDeps(deps); err != nil {
			return k.fail(err)
		}
	}
	if _, err := Resolve(p, k.stderr); err != nil {
		os.WriteFile(cfgPath, before, 0o644) // 集められなければ 組.suru を元に戻す
		return k.fail(err)
	}
	return 0
}

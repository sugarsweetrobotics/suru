// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// プロジェクトと依存の C のソースを一緒に作る。
//
// 組.suru に「Cソース とは 「c/包み.c」」と書くと、kumu はそのファイルを clang でオブジェクトにして、
// する のプログラムと一緒にリンクする。「C引数」はそのプロジェクトの C のソースをコンパイルするときだけ、
// 「リンク引数」は(依存のものも全部)リンクするときに使う。どちらも ${名前} は環境変数で、展開してから空白で分ける。
// オブジェクトは 出力/.c/ に置き、ソースと同じフォルダのヘッダー(.h)・引数・C コンパイラが同じなら作り直さない。

// CBuild はリンクに足すもの
type CBuild struct {
	Objects   []string // 作ったオブジェクト
	LinkFlags []string // リンクの引数
	Digest    string   // 作り直しの判定に使う(ソース・ヘッダー・引数)
}

// Args は clang に足す引数
func (c *CBuild) Args() []string {
	if c == nil {
		return nil
	}
	return append(append([]string{}, c.Objects...), c.LinkFlags...)
}

var envRe = regexp.MustCompile(`\$\{([A-Za-z_][A-Za-z0-9_]*)\}`)

// expandFlags は ${名前} を環境変数にして、空白で分ける
func expandFlags(items []string, key, project string) ([]string, error) {
	var out []string
	for _, it := range items {
		var missing string
		s := envRe.ReplaceAllStringFunc(it, func(m string) string {
			name := envRe.FindStringSubmatch(m)[1]
			v, ok := os.LookupEnv(name)
			if !ok && missing == "" {
				missing = name
			}
			return v
		})
		if missing != "" {
			return nil, fmt.Errorf("「%s」の%s「%s」に使う環境変数「%s」がありません", project, key, it, missing)
		}
		out = append(out, strings.Fields(s)...)
	}
	return out, nil
}

// cUnit は C のソースを持つプロジェクト1つ
type cUnit struct {
	name, root    string
	sources       []string
	cflags, links []string
}

// PrepareC はプロジェクトと依存の C のソースをオブジェクトにする(C のソースが1つもなければ nil)
func PrepareC(p *Project, deps []Resolved, stderr io.Writer) (*CBuild, error) {
	units := []cUnit{{p.Name, p.Root, p.CSources, p.CFlags, p.LinkFlags}}
	for _, d := range deps {
		if d.Config != nil {
			units = append(units, cUnit{d.Name, d.Dir, d.Config.CSources, d.Config.CFlags, d.Config.LinkFlags})
		}
	}
	any := false
	for _, u := range units {
		if len(u.sources) > 0 || len(u.links) > 0 {
			any = true
		}
	}
	if !any {
		return nil, nil
	}
	cc := native.FindCC()
	if cc == "" {
		return nil, fmt.Errorf("Cソースを作るには clang が必要です")
	}
	cb := &CBuild{}
	all := sha256.New()
	objDir := filepath.Join(p.Root, OutDir, ".c")
	for _, u := range units {
		cflags, err := expandFlags(u.cflags, "C引数", u.name)
		if err != nil {
			return nil, err
		}
		links, err := expandFlags(u.links, "リンク引数", u.name)
		if err != nil {
			return nil, err
		}
		cb.LinkFlags = append(cb.LinkFlags, links...)
		fmt.Fprintf(all, "%s\x00%s\x00", u.name, strings.Join(links, "\x00"))
		for _, src := range u.sources {
			path := filepath.Join(u.root, filepath.FromSlash(src))
			key, err := cSourceKey(cc, path, cflags)
			if err != nil {
				return nil, fmt.Errorf("「%s」のCソース「%s」が読めません", u.name, src)
			}
			fmt.Fprintf(all, "%s\x00", key)
			obj := filepath.Join(objDir, strings.TrimSuffix(filepath.Base(src), filepath.Ext(src))+"-"+key[:16]+".o")
			cb.Objects = append(cb.Objects, obj)
			if _, err := os.Stat(obj); err == nil {
				continue
			}
			if err := os.MkdirAll(objDir, 0o755); err != nil {
				return nil, err
			}
			tmp := fmt.Sprintf("%s.%d.tmp", obj, os.Getpid())
			args := append(native.TargetArgs(), "-O2", "-c", path, "-o", tmp)
			if !compiler.TargetWindows() { // Windows の DLL にしないので要らない(clang は受け付けない)
				args = append(args, "-fPIC")
			}
			args = append(args, cflags...)
			if out, err := exec.Command(cc, args...).CombinedOutput(); err != nil {
				return nil, fmt.Errorf("「%s」のCソース「%s」のコンパイルに失敗しました:\n%s", u.name, src, out)
			}
			if err := os.Rename(tmp, obj); err != nil {
				return nil, err
			}
			fmt.Fprintf(stderr, "Cソース「%s」をコンパイルしました\n", src)
		}
	}
	cb.Digest = hex.EncodeToString(all.Sum(nil))
	return cb, nil
}

// cSourceKey は C のソース・同じフォルダのヘッダー・引数・C コンパイラから作る印
func cSourceKey(cc, path string, cflags []string) (string, error) {
	h := sha256.New()
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	fmt.Fprintf(h, "%s\x00%s\x00%s\x00%d:%s", cc, compiler.Target(), strings.Join(cflags, "\x00"), len(data), data)
	headers, _ := filepath.Glob(filepath.Join(filepath.Dir(path), "*.h"))
	sort.Strings(headers)
	for _, hp := range headers {
		if b, err := os.ReadFile(hp); err == nil {
			fmt.Fprintf(h, "%s:%d:%s", filepath.Base(hp), len(b), b)
		}
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

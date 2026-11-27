// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// install は kumu 導入。プロジェクトを作って、できたコマンドを ~/.local/bin(--先 で変えられる)に写す。
//
//	kumu 導入                          今のプロジェクト
//	kumu 導入 ../surl                  フォルダのプロジェクト
//	kumu 導入 github.com/suru-lang/surl[@0.1.0]  Git のタグから(版なしなら一番新しいタグ)
func (k *kumu) install(args []string) int {
	opt, check, dest, spec := "-O2", true, "", ""
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case (a == "--先" || a == "--dir") && i+1 < len(args):
			dest = args[i+1]
			i++
		case a == "-O0" || a == "-O1" || a == "-O2" || a == "-O3" || a == "-Os":
			opt = a
		case a == "--検査なし" || a == "--no-check":
			check = false
		case !strings.HasPrefix(a, "-") && spec == "":
			spec = a
		default:
			fmt.Fprintf(k.stderr, "「%s」は 導入 に使えないオプションです\n使い方: kumu 導入 [場所[@版]] [--先 フォルダ]\n", a)
			return 2
		}
	}
	if dest == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return k.fail(fmt.Errorf("ホームフォルダがわかりません。--先 で入れる場所を選んでください"))
		}
		dest = filepath.Join(home, ".local", "bin")
	} else if !filepath.IsAbs(dest) {
		dest = filepath.Join(k.dir, dest)
	}

	var p *Project
	var err error
	switch {
	case spec == "":
		p, err = FindProject(k.dir)
	case compiler.IsLocalSource(spec):
		dir := spec
		if !filepath.IsAbs(dir) {
			dir = filepath.Join(k.dir, dir)
		}
		p, err = FindProjectAt(dir)
	default:
		var tmp, dir string
		tmp, dir, err = k.cloneForInstall(spec)
		if tmp != "" {
			defer os.RemoveAll(tmp)
		}
		if err == nil {
			p, err = FindProjectAt(dir)
		}
	}
	if err != nil {
		return k.fail(err)
	}
	if p.SharedLib() {
		return k.fail(fmt.Errorf("種類が「%s」のプロジェクトは導入できません(コマンドではないので、kumu 作る でできたライブラリを使います)", KindShared))
	}
	if p.Target != "" {
		return k.fail(fmt.Errorf("マイコン向け(対象「%s」)のプロジェクトは導入できません(kumu 書き込む で基板に書き込みます)", p.Target))
	}
	deps, err := Resolve(p, k.stderr)
	if err != nil {
		return k.fail(err)
	}
	if err := CheckSysDeps(p, deps, k.stderr); err != nil {
		return k.fail(err)
	}
	cb, err := PrepareC(p, deps, k.stderr)
	if err != nil {
		return k.fail(err)
	}
	exe, err := k.build(p, opt, check, cb)
	if err != nil {
		return k.fail(err)
	}
	to := filepath.Join(dest, filepath.Base(exe))
	if err := copyExecutable(exe, to); err != nil {
		return k.fail(fmt.Errorf("「%s」に入れられません: %v", to, err))
	}
	fmt.Fprintf(k.stderr, "「%s」%s を %s に入れました\n", p.Name, p.Version, homeShort(to))
	if !inPath(dest) {
		fmt.Fprintf(k.stderr, "注意: %s が PATH にありません。", homeShort(dest))
		if runtime.GOOS == "windows" {
			fmt.Fprintln(k.stderr, "「環境変数」の設定で、ユーザーの Path にこのフォルダを足してください")
		} else {
			fmt.Fprintf(k.stderr, "シェルの設定(~/.bashrc・~/.zshrc など)に export PATH=\"%s:$PATH\" と書いてください\n", homeVar(dest))
		}
	}
	return 0
}

// cloneForInstall は「場所@版」(版なしなら一番新しいタグ)を仮のフォルダに取ってくる。
// 仮のフォルダ(呼んだ側で消す。失敗しても空でなければ返す)と、取ってきたプロジェクトのフォルダを返す
func (k *kumu) cloneForInstall(spec string) (tmp, dir string, err error) {
	d := Dep{Source: strings.TrimSuffix(spec, "/")}
	if i := strings.LastIndex(spec, "@"); i > 0 {
		if d, err = ParseDep(spec); err != nil {
			return "", "", err
		}
	} else {
		if d.Version, err = LatestVersion(d.Source); err != nil {
			return "", "", err
		}
	}
	if tmp, err = os.MkdirTemp("", "kumu-install-"); err != nil {
		return "", "", err
	}
	// clone は空でないフォルダに入れられないので、その中に作る
	dir = filepath.Join(tmp, "src")
	if err := cloneTag(d, dir, "導入するもの"); err != nil {
		return tmp, "", err
	}
	fmt.Fprintf(k.stderr, "「%s」を取ってきました\n", d)
	return tmp, dir, nil
}

// copyExecutable は from を to に写して実行できるようにする。同じフォルダに書いてから名前を変えるので、
// 動いている古いコマンドを置き換えても壊れない
func copyExecutable(from, to string) error {
	if err := os.MkdirAll(filepath.Dir(to), 0o755); err != nil {
		return err
	}
	src, err := os.Open(from)
	if err != nil {
		return err
	}
	defer src.Close()
	tmp, err := os.CreateTemp(filepath.Dir(to), "."+filepath.Base(to)+".tmp-")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := io.Copy(tmp, src); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Chmod(tmp.Name(), 0o755); err != nil {
		return err
	}
	if runtime.GOOS == "windows" {
		os.Remove(to) // Windows の Rename は上書きしない
	}
	return os.Rename(tmp.Name(), to)
}

// inPath は dir が PATH にあるか
func inPath(dir string) bool {
	want := samePathKey(dir)
	for _, p := range filepath.SplitList(os.Getenv("PATH")) {
		if p != "" && samePathKey(p) == want {
			return true
		}
	}
	return false
}

func samePathKey(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	p = filepath.Clean(p)
	if runtime.GOOS == "windows" {
		p = strings.ToLower(p)
	}
	return p
}

// homeShort はホームフォルダの下なら ~/… と書く(知らせを短くする)
func homeShort(p string) string {
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		if rel, err := filepath.Rel(home, p); err == nil && rel != "." && !strings.HasPrefix(rel, "..") {
			return "~" + string(filepath.Separator) + rel
		}
	}
	return p
}

// homeVar はホームフォルダの下なら $HOME/… と書く(シェルの設定にそのまま書ける形)
func homeVar(p string) string {
	if s := homeShort(p); strings.HasPrefix(s, "~"+string(filepath.Separator)) {
		return "$HOME" + s[1:]
	}
	return p
}

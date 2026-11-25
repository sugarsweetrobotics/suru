// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// ライブラリを公開する: 確かめてから、Git のタグ v版 を付ける。
// push はしない(外に出すのは使う人が自分で git push する)。

var semverRe = regexp.MustCompile(`^[0-9]+(\.[0-9]+)*$`)

// sourceFromRemote は git の remote の URL から、kumu 追加 に書く場所を作る
func sourceFromRemote(url string) string {
	url = strings.TrimSpace(url)
	url = strings.TrimSuffix(strings.TrimSuffix(url, "/"), ".git")
	if rest, ok := strings.CutPrefix(url, "git@"); ok { // git@github.com:someone/計算
		return strings.Replace(rest, ":", "/", 1)
	}
	for _, p := range []string{"https://", "http://", "ssh://git@", "ssh://"} {
		if rest, ok := strings.CutPrefix(url, p); ok {
			if p == "https://" || p == "ssh://git@" {
				if i := strings.Index(rest, "@"); i >= 0 && i < strings.Index(rest+"/", "/") {
					rest = rest[i+1:]
				}
			}
			return rest
		}
	}
	return url
}

func (k *kumu) publish(args []string) int {
	runTests := true
	for _, a := range args {
		switch a {
		case "--試験なし", "--no-test":
			runTests = false
		default:
			fmt.Fprintln(k.stderr, "使い方: kumu 公開 [--試験なし]")
			return 2
		}
	}
	p, err := FindProject(k.dir)
	if err != nil {
		return k.fail(err)
	}
	if !semverRe.MatchString(p.Version) {
		return k.fail(fmt.Errorf("版「%s」はタグにできません(「1.2.0」のように数と点で書きます)", p.Version))
	}
	if _, err := os.Stat(filepath.Join(p.Root, p.Name+compiler.SourceSuffix)); err != nil {
		return k.fail(fmt.Errorf("「%s%s」がありません(ライブラリは、名前と同じファイルを読み込まれるファイルにします)", p.Name, compiler.SourceSuffix))
	}
	for _, d := range p.Deps {
		if d.Version == "" {
			return k.fail(fmt.Errorf("依存「%s」は手元のフォルダなので、使う人は取ってこられません(Git の場所@版 にします)", d.Source))
		}
	}
	if out, err := git("-C", p.Root, "rev-parse", "--show-toplevel"); err != nil {
		return k.fail(fmt.Errorf("「%s」は Git のリポジトリではありません: %s", p.Root, strings.TrimSpace(out)))
	} else if top := strings.TrimSpace(out); !samePath(top, p.Root) {
		return k.fail(fmt.Errorf("組.suru はリポジトリの一番上に置きます(今は %s の下)", top))
	}
	if out, err := git("-C", p.Root, "status", "--porcelain"); err != nil {
		return k.fail(err)
	} else if strings.TrimSpace(out) != "" {
		return k.fail(fmt.Errorf("まだコミットしていない変更があります:\n%s", strings.TrimRight(out, "\n")))
	}
	tag := "v" + p.Version
	if out, _ := git("-C", p.Root, "tag", "--list", tag); strings.TrimSpace(out) != "" {
		return k.fail(fmt.Errorf("タグ %s はもうあります(組.suru の版を上げてください)", tag))
	}
	deps, err := Resolve(p, k.stderr)
	if err != nil {
		return k.fail(err)
	}
	if runTests {
		cb, err := PrepareC(p, deps, k.stderr)
		if err != nil {
			return k.fail(err)
		}
		if rc := k.test(p, nil, "-O0", true, cb); rc != 0 {
			return k.fail(fmt.Errorf("不合格の試験があるので、タグを付けませんでした(--試験なし で試験を飛ばせます)"))
		}
	}
	// 試験で 組.lock が書きかわったかもしれないので、もう一度確かめる
	if out, _ := git("-C", p.Root, "status", "--porcelain"); strings.TrimSpace(out) != "" {
		return k.fail(fmt.Errorf("組.lock などが書きかわりました。コミットしてから、もう一度 kumu 公開 してください:\n%s", strings.TrimRight(out, "\n")))
	}
	if out, err := git("-C", p.Root, "tag", "-a", tag, "-m", p.Name+" "+p.Version); err != nil {
		return k.fail(fmt.Errorf("タグを付けられません: %s", strings.TrimSpace(out)))
	}
	where := "<リポジトリの場所>"
	if out, err := git("-C", p.Root, "remote", "get-url", "origin"); err == nil && strings.TrimSpace(out) != "" {
		where = sourceFromRemote(out)
	}
	fmt.Fprintf(k.stdout, "「%s」%s にタグ %s を付けました。\n", p.Name, p.Version, tag)
	fmt.Fprintf(k.stdout, "公開するには: git push origin %s\n", tag)
	fmt.Fprintf(k.stdout, "使う人は: kumu 追加 %s@%s\n", where, p.Version)
	return 0
}

func samePath(a, b string) bool {
	ea, err1 := filepath.EvalSymlinks(a)
	eb, err2 := filepath.EvalSymlinks(b)
	if err1 != nil || err2 != nil {
		return filepath.Clean(a) == filepath.Clean(b)
	}
	return ea == eb
}

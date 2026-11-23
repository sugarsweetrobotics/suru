// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"errors"
	"fmt"
	"io"
	"os/exec"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// 外部依存(システムの C のライブラリ)を確かめる。
//
// ライブラリは 組.suru に「外部依存 とは 「libpcre2-8」」と、無いときの「導入案内」を書く。
// kumu はプロジェクトと全部の依存の外部依存を pkg-config で確かめ、足りなければ
// どの依存が使うのかと入れ方を見せて止める。pkg-config が無ければ知らせだけ出して進む。

type sysNeed struct {
	dep   SysDep
	owner string   // 使うもの(「このプロジェクト」か「依存「正規表現」」)
	guide []string // その持ち主の導入案内
	name  string   // 持ち主の名前(案内の見出し)
}

// CheckSysDeps はプロジェクトと依存の外部依存がシステムにあるかを確かめる
func CheckSysDeps(p *Project, deps []Resolved, stderr io.Writer) error {
	var needs []sysNeed
	for _, d := range p.SysDeps {
		needs = append(needs, sysNeed{d, "このプロジェクト", p.Guide, p.Name})
	}
	for _, r := range deps {
		if r.Config == nil {
			continue
		}
		for _, d := range r.Config.SysDeps {
			needs = append(needs, sysNeed{d, "依存「" + r.Name + "」", r.Config.Guide, r.Name})
		}
	}
	if len(needs) == 0 {
		return nil
	}
	pc := compiler.PkgConfig()
	if pc == "" {
		var mods []string
		for _, n := range needs {
			mods = append(mods, n.dep.Module)
		}
		fmt.Fprintf(stderr, "注意: pkg-config が無いので、外部依存(%s)が入っているかを確かめずに進みます\n", strings.Join(unique(mods), "・"))
		return nil
	}
	var lines []string
	var guides []string
	seenGuide := map[string]bool{}
	checked := map[string]string{} // 名前@版 → 足りないわけ(足りていれば "")
	for _, n := range needs {
		key := n.dep.String()
		why, ok := checked[key]
		if !ok {
			why = checkSysDep(pc, n.dep)
			checked[key] = why
		}
		if why == "" {
			continue
		}
		lines = append(lines, fmt.Sprintf("  「%s」%s(%sが使います)", n.dep.Module, why, n.owner))
		if len(n.guide) > 0 && !seenGuide[n.name] {
			seenGuide[n.name] = true
			guides = append(guides, fmt.Sprintf("入れ方(「%s」の導入案内):", n.name))
			for _, g := range n.guide {
				guides = append(guides, "  "+g)
			}
		}
	}
	if len(lines) == 0 {
		return nil
	}
	msg := []string{"システムのライブラリが足りません:"}
	msg = append(msg, lines...)
	msg = append(msg, guides...)
	msg = append(msg, "(pkg-config で探しました。普通でない場所に入れたなら、その .pc ファイルのフォルダを PKG_CONFIG_PATH に足します)")
	return errors.New(strings.Join(msg, "\n"))
}

// checkSysDep は1つの外部依存を確かめ、足りなければそのわけ(足りていれば "")
func checkSysDep(pc string, d SysDep) string {
	if exec.Command(pc, "--exists", d.Module).Run() != nil {
		if d.MinVersion != "" {
			return fmt.Sprintf(" %s 以上が見つかりません", d.MinVersion)
		}
		return "が見つかりません"
	}
	if d.MinVersion == "" {
		return ""
	}
	if exec.Command(pc, "--atleast-version="+d.MinVersion, d.Module).Run() == nil {
		return ""
	}
	have, _ := exec.Command(pc, "--modversion", d.Module).Output()
	return fmt.Sprintf(" %s 以上が要りますが、入っているのは %s です", d.MinVersion, strings.TrimSpace(string(have)))
}

func unique(xs []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, x := range xs {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}

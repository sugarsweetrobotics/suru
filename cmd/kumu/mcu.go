// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/suru-lang/suru/cmd/internal/mcu"
	"github.com/suru-lang/suru/compiler"
)

// targetOption は 新規・初期化 の「--対象 基板」を取り出す
func targetOption(args []string) (rest []string, target string, ok bool) {
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--対象" || a == "--target" {
			if i+1 >= len(args) {
				return nil, "", false
			}
			target = args[i+1]
			i++
			continue
		}
		rest = append(rest, a)
	}
	return rest, target, true
}

// mcu はマイコン向けの 作る・書き込む(実行・試験はできないので案内する)
func (k *kumu) mcu(cmd string, p *Project, target, port string) int {
	b, err := mcu.Lookup(target)
	if err != nil {
		return k.fail(err)
	}
	switch cmd {
	case "実行":
		return k.fail(fmt.Errorf("マイコン向け(%s)のプログラムはこの計算機では動かせません。kumu 書き込む で基板に書き込んでください", b.Display))
	case "試験":
		return k.fail(fmt.Errorf("マイコン向け(%s)のプロジェクトの試験はまだできません", b.Display))
	}
	tools, err := mcu.FindTools(cmd == "書き込む")
	if err != nil {
		return k.fail(err)
	}
	path := p.EntryPath()
	data, err := os.ReadFile(path)
	if err != nil {
		return k.fail(fmt.Errorf("入口のファイル「%s」が読めません", p.Entry+compiler.SourceSuffix))
	}
	ir, err := mcu.Compile(string(data), path, b)
	if err != nil {
		return k.fail(err)
	}
	out := filepath.Join(p.Root, OutDir, b.Name, p.Name)
	r, err := mcu.Build(ir, out, b, tools)
	if err != nil {
		return k.fail(err)
	}
	fmt.Fprintf(k.stderr, "「%s」%s を %s 向けに組みました(%s)\n", p.Name, p.Version, b.Display, k.rel(r.Hex))
	if s := r.Summary(); s != "" {
		fmt.Fprintln(k.stderr, "  "+s)
	}
	if cmd != "書き込む" {
		return 0
	}
	dev, err := mcu.ChoosePort(port)
	if err != nil {
		return k.fail(err)
	}
	fmt.Fprintf(k.stderr, "%s に書き込みます(%s)\n", dev, b.Display)
	if err := mcu.Flash(r.Hex, dev, b, tools, k.stdout, k.stderr); err != nil {
		return k.fail(err)
	}
	fmt.Fprintln(k.stderr, "書き込みました。シリアル(9600)で「表示する」の出力が見られます")
	return 0
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// ConfigName はプロジェクトの設定ファイルの名前
const ConfigName = "組" + compiler.SourceSuffix

// OutDir は作ったものを置くフォルダの名前(プロジェクトのフォルダの中)
const OutDir = "出力"

// Project は 組.suru に書いたプロジェクトの設定
type Project struct {
	Root    string // 組.suru のあるフォルダ(絶対パス)
	Name    string // 名前(作るバイナリの名前にもなる)
	Version string // 版
	Entry   string // 入口のファイルの名前(.suru なし)
}

// EntryPath は入口のファイルのパス
func (p *Project) EntryPath() string {
	return filepath.Join(p.Root, p.Entry+compiler.SourceSuffix)
}

// configKeys は 組.suru に書ける項目(書く順)
var configKeys = []string{"名前", "版", "入口"}

// ParseConfig は 組.suru の中身を読む。する の定義「名前 とは 「…」」だけを書ける
func ParseConfig(source, root string) (*Project, error) {
	source = compiler.NormalizeNewlines(source)
	program, serr := compiler.ParseSource(source, root)
	if serr != nil {
		return nil, configError(serr, source)
	}
	p := &Project{Root: root, Version: "0.1.0", Entry: "本体"}
	seen := map[string]bool{}
	for _, node := range program {
		d, ok := node.(*compiler.Define)
		if !ok {
			return nil, configError(&compiler.SuruError{Message: "「" + ConfigName + "」には「名前 とは 「…」」の形の定義だけを書きます", Line: linePos(node)}, source)
		}
		pos := d.Line
		if !contains(configKeys, d.Name) {
			return nil, configError(&compiler.SuruError{Message: fmt.Sprintf("「%s」は %s に書けない項目です(書けるのは %s)", d.Name, ConfigName, strings.Join(configKeys, "・")), Line: pos}, source)
		}
		if seen[d.Name] {
			return nil, configError(&compiler.SuruError{Message: fmt.Sprintf("「%s」が2回書かれています", d.Name), Line: pos}, source)
		}
		seen[d.Name] = true
		s, ok := d.Body.(*compiler.Str)
		if !ok || len(d.Params) > 0 || d.IsFunction {
			return nil, configError(&compiler.SuruError{Message: fmt.Sprintf("「%s」には 「…」 の文字列を書きます", d.Name), Line: pos}, source)
		}
		switch d.Name {
		case "名前":
			if err := checkName(s.Value); err != nil {
				return nil, configError(&compiler.SuruError{Message: err.Error(), Line: pos}, source)
			}
			p.Name = s.Value
		case "版":
			if s.Value == "" {
				return nil, configError(&compiler.SuruError{Message: "版が空です(「0.1.0」のように書きます)", Line: pos}, source)
			}
			p.Version = s.Value
		case "入口":
			e := strings.TrimSuffix(s.Value, compiler.SourceSuffix)
			if e == "" || filepath.IsAbs(e) || strings.HasPrefix(filepath.Clean(e), "..") {
				return nil, configError(&compiler.SuruError{Message: "入口には、プロジェクトのフォルダの中のファイルの名前を書きます", Line: pos}, source)
			}
			p.Entry = e
		}
	}
	if p.Name == "" {
		return nil, fmt.Errorf("「%s」に「名前 とは 「…」」がありません", ConfigName)
	}
	return p, nil
}

func linePos(n compiler.Node) compiler.Pos {
	if l, ok := n.(compiler.Lined); ok {
		return l.GetLine()
	}
	return compiler.Pos{}
}

func configError(e *compiler.SuruError, source string) error {
	return errors.New("「" + ConfigName + "」の" + strings.TrimPrefix(compiler.FormatError(e, source, true), "エラー: "))
}

// checkName はプロジェクトの名前に使えるかを調べる(バイナリとフォルダの名前になる)
func checkName(name string) error {
	if name == "" {
		return errors.New("名前が空です")
	}
	if strings.ContainsAny(name, `/\:*?"<>| 　`) || strings.HasPrefix(name, ".") || strings.HasPrefix(name, "-") {
		return fmt.Errorf("「%s」はプロジェクトの名前に使えません(空白・/・. で始まる名前などは使えません)", name)
	}
	return nil
}

func contains(xs []string, x string) bool {
	for _, y := range xs {
		if y == x {
			return true
		}
	}
	return false
}

// FindProject は dir から上へ 組.suru を探して読む
func FindProject(dir string) (*Project, error) {
	dir, err := filepath.Abs(dir)
	if err != nil {
		return nil, err
	}
	for d := dir; ; d = filepath.Dir(d) {
		path := filepath.Join(d, ConfigName)
		if data, err := os.ReadFile(path); err == nil {
			return ParseConfig(string(data), d)
		}
		if filepath.Dir(d) == d {
			break
		}
	}
	return nil, fmt.Errorf("「%s」が見つかりません(このフォルダか上のフォルダに置きます。新しく作るなら kumu 新規 名前)", ConfigName)
}

// 雛形のファイル
func configTemplate(name string) string {
	return "名前 とは 「" + name + "」\n版 とは 「0.1.0」\n入口 とは 「本体」\n"
}

const entryTemplate = "「こんにちは」 を 表示する\n"
const gitignoreTemplate = "/" + OutDir + "/\n"

// CreateProject は dir に雛形を書く。fresh なら dir は新しく作る(既にあればエラー)
func CreateProject(dir, name string, fresh bool) error {
	if err := checkName(name); err != nil {
		return err
	}
	if fresh {
		if _, err := os.Stat(dir); err == nil {
			return fmt.Errorf("「%s」は既にあります", dir)
		}
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	} else if _, err := os.Stat(filepath.Join(dir, ConfigName)); err == nil {
		return fmt.Errorf("「%s」は既にあります", filepath.Join(dir, ConfigName))
	}
	files := []struct{ name, body string }{
		{ConfigName, configTemplate(name)},
		{"本体" + compiler.SourceSuffix, entryTemplate},
		{".gitignore", gitignoreTemplate},
	}
	for _, f := range files {
		path := filepath.Join(dir, f.name)
		if _, err := os.Stat(path); err == nil {
			continue // 初期化では、今あるファイルはそのまま
		}
		if err := os.WriteFile(path, []byte(f.body), 0o644); err != nil {
			return err
		}
	}
	return nil
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/suru-lang/suru/cmd/internal/mcu"
	"github.com/suru-lang/suru/compiler"
)

// ConfigName はプロジェクトの設定ファイルの名前
const ConfigName = "組" + compiler.SourceSuffix

// OutDir は作ったものを置くフォルダの名前(プロジェクトのフォルダの中)
const OutDir = "出力"

// Project は 組.suru に書いたプロジェクトの設定
type Project struct {
	Root      string   // 組.suru のあるフォルダ(絶対パス)
	Name      string   // 名前(作るバイナリの名前にもなる)
	Version   string   // 版
	Entry     string   // 入口のファイルの名前(.suru なし)
	Deps      []Dep    // 依存(書いた順)
	depLine   int      // 「依存 とは …」の行(なければ 0)
	SysDeps   []SysDep // 外部依存: システムの C のライブラリ(pkg-config の名前)
	Guide     []string // 導入案内: 外部依存が無いときに見せる入れ方
	Target    string   // 対象: マイコンの基板(「arduino-uno」など。空ならこの計算機)
	CSources  []string // Cソース: 一緒に作る C のファイル(プロジェクトのフォルダからの道)
	CFlags    []string // C引数: C のソースをコンパイルするときの引数(${…} は環境変数。空白で分ける)
	LinkFlags []string // リンク引数: リンクするときの引数(依存のものも全部使う)
}

// SysDep は 組.suru の外部依存の1つ。「libpcre2-8」か、最低の版を付けた「libpcre2-8@10.30」
type SysDep struct {
	Module     string // pkg-config の名前
	MinVersion string // 最低の版(なければ空)
}

func (d SysDep) String() string {
	if d.MinVersion == "" {
		return d.Module
	}
	return d.Module + "@" + d.MinVersion
}

// EntryPath は入口のファイルのパス
func (p *Project) EntryPath() string {
	return filepath.Join(p.Root, p.Entry+compiler.SourceSuffix)
}

// configKeys は 組.suru に書ける項目(書く順)
var configKeys = []string{"名前", "版", "入口", "依存", "外部依存", "導入案内", "対象", "Cソース", "C引数", "リンク引数"}

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
		if d.Name == "依存" {
			deps, err := parseDeps(d)
			if err != nil {
				return nil, configError(&compiler.SuruError{Message: err.Error(), Line: pos}, source)
			}
			p.Deps, p.depLine = deps, pos.Line
			continue
		}
		if d.Name == "外部依存" || d.Name == "導入案内" || d.Name == "Cソース" || d.Name == "C引数" || d.Name == "リンク引数" {
			items, err := stringList(d)
			if err != nil {
				return nil, configError(&compiler.SuruError{Message: err.Error(), Line: pos}, source)
			}
			switch d.Name {
			case "Cソース":
				for _, it := range items {
					if it == "" || filepath.IsAbs(it) || strings.HasPrefix(filepath.Clean(it), "..") {
						return nil, configError(&compiler.SuruError{Message: fmt.Sprintf("Cソース「%s」には、プロジェクトのフォルダの中のファイルを書きます", it), Line: pos}, source)
					}
				}
				p.CSources = items
				continue
			case "C引数":
				p.CFlags = items
				continue
			case "リンク引数":
				p.LinkFlags = items
				continue
			}
			if d.Name == "導入案内" {
				p.Guide = items
				continue
			}
			for _, it := range items {
				sd, err := ParseSysDep(it)
				if err != nil {
					return nil, configError(&compiler.SuruError{Message: err.Error(), Line: pos}, source)
				}
				p.SysDeps = append(p.SysDeps, sd)
			}
			continue
		}
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
		case "対象":
			if _, err := mcu.Lookup(s.Value); err != nil {
				return nil, configError(&compiler.SuruError{Message: err.Error(), Line: pos}, source)
			}
			p.Target = s.Value
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
func configTemplate(name, target string) string {
	s := "名前 とは 「" + name + "」\n版 とは 「0.1.0」\n入口 とは 「本体」\n"
	if target != "" {
		s += "対象 とは 「" + target + "」\n"
	}
	return s
}

const entryTemplate = "「こんにちは」 を 表示する\n"

// testTemplate は 試験/例.suru の雛形(kumu 試験 で動かす。#155)
const testTemplate = `「試験」 を 読み込んで 使う

# 「…試験する」で終わる名前の手順が、1つの試験です。kumu 試験 で動かします
# プロジェクトのファイルは、組.suru の名前で読み込めます(「計算」 を 読み込む → 計算内の二倍する)
足し算試験する は 真偽 の 動作
足し算試験する とは 以下の手順です
  1 + 2 を 3 に 一致確認する
  1 < 2 を 確認する
  以上です
`

// mcuEntryTemplate はマイコン向けの雛形(基板の LED を点滅させ、シリアルに挨拶する)
const mcuEntryTemplate = `「マイコン」 を 読み込んで 使う

点滅する とは 以下の手順です
  内蔵灯 を 反転出力する
  500 を ミリ秒待機する
  点滅する
  以上です

内蔵灯 を 出力設定する
「こんにちは」 を 表示する
点滅する
`
const gitignoreTemplate = "/" + OutDir + "/\n"

// CreateProject は dir に雛形を書く。fresh なら dir は新しく作る(既にあればエラー)
func CreateProject(dir, name string, fresh bool, target string) error {
	if err := checkName(name); err != nil {
		return err
	}
	// ウェブアプリは道のファイル「名前.suru」を読み込むので、標準や屋台の依存と同じ名前は使えない
	if target == WebTarget && (isLibName(name) || contains(webDepNames, name)) {
		return fmt.Errorf("「%s」は読み込みの名前と重なるので、ウェブアプリの名前に使えません", name)
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
	if target == WebTarget {
		return writeFiles(dir, webFiles(name))
	}
	if target != "" {
		if _, err := mcu.Lookup(target); err != nil {
			return err
		}
	}
	entry := entryTemplate
	if target != "" {
		entry = mcuEntryTemplate
	}
	files := []struct{ name, body string }{
		{ConfigName, configTemplate(name, target)},
		{"本体" + compiler.SourceSuffix, entry},
		{".gitignore", gitignoreTemplate},
	}
	if fresh && target == "" {
		// マイコン向けは試験を動かせないので作らない
		if err := os.MkdirAll(filepath.Join(dir, TestDir), 0o755); err != nil {
			return err
		}
		files = append(files, struct{ name, body string }{filepath.Join(TestDir, "例"+compiler.SourceSuffix), testTemplate})
	}
	return writeFiles(dir, files)
}

// writeFiles は雛形のファイルを書く(初期化では、今あるファイルはそのまま)
func writeFiles(dir string, files []struct{ name, body string }) error {
	for _, f := range files {
		path := filepath.Join(dir, f.name)
		if _, err := os.Stat(path); err == nil {
			continue
		}
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return err
		}
		if err := os.WriteFile(path, []byte(f.body), 0o644); err != nil {
			return err
		}
	}
	return nil
}

// Dep は 組.suru の依存の1つ。「場所@版」か、フォルダのパス「../部品集」
type Dep struct {
	Source  string // github.com/someone/部品集、https://…、file://…、../部品集
	Version string // 「1.2.0」(フォルダのパスなら空)
}

func (d Dep) String() string {
	if d.Version == "" {
		return d.Source
	}
	return d.Source + "@" + d.Version
}

// ParseDep は「場所@版」を読む
func ParseDep(spec string) (Dep, error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return Dep{}, errors.New("依存が空です")
	}
	if compiler.IsLocalSource(spec) {
		return Dep{Source: filepath.ToSlash(spec)}, nil
	}
	i := strings.LastIndex(spec, "@")
	if i <= 0 || i == len(spec)-1 {
		return Dep{}, fmt.Errorf("依存「%s」に版がありません(「%s@1.0.0」のように書きます。kumu 追加 なら一番新しい版を選びます)", spec, spec)
	}
	src, ver := spec[:i], strings.TrimPrefix(spec[i+1:], "v")
	if strings.ContainsAny(src, " \t") {
		return Dep{}, fmt.Errorf("依存「%s」の場所に空白は使えません", spec)
	}
	return Dep{Source: strings.TrimSuffix(src, "/"), Version: ver}, nil
}

// stringList は「…」か、それを と でつないだものを読む(外部依存・導入案内)
func stringList(d *compiler.Define) ([]string, error) {
	bad := fmt.Errorf("「%s」には 「…」 の文字列か、それを と でつないだものを書きます", d.Name)
	var items []compiler.Node
	switch b := d.Body.(type) {
	case *compiler.Str:
		items = []compiler.Node{b}
	case *compiler.ListLit:
		items = b.Items
	default:
		return nil, bad
	}
	if len(d.Params) > 0 || d.IsFunction {
		return nil, bad
	}
	var out []string
	for _, it := range items {
		s, ok := it.(*compiler.Str)
		if !ok {
			return nil, bad
		}
		out = append(out, s.Value)
	}
	return out, nil
}

// ParseSysDep は外部依存の「名前」か「名前@最低の版」を読む
func ParseSysDep(spec string) (SysDep, error) {
	spec = strings.TrimSpace(spec)
	module, ver, _ := strings.Cut(spec, "@")
	if module == "" || strings.ContainsAny(module, " \t/") {
		return SysDep{}, fmt.Errorf("外部依存「%s」は pkg-config の名前で書きます(「libpcre2-8」、版を決めるなら「libpcre2-8@10.30」)", spec)
	}
	if strings.Contains(spec, "@") && !isVersion(strings.TrimPrefix(ver, "v")) {
		return SysDep{}, fmt.Errorf("外部依存「%s」の版は数と点で書きます(「%s@10.30」)", spec, module)
	}
	return SysDep{Module: module, MinVersion: strings.TrimPrefix(ver, "v")}, nil
}

func parseDeps(d *compiler.Define) ([]Dep, error) {
	var items []compiler.Node
	switch b := d.Body.(type) {
	case *compiler.Str:
		items = []compiler.Node{b}
	case *compiler.ListLit:
		items = b.Items
	default:
		return nil, errors.New("「依存」には 「場所@版」 の文字列か、それを と でつないだものを書きます")
	}
	var out []Dep
	seen := map[string]bool{}
	for _, it := range items {
		s, ok := it.(*compiler.Str)
		if !ok || len(d.Params) > 0 || d.IsFunction {
			return nil, errors.New("「依存」には 「場所@版」 の文字列か、それを と でつないだものを書きます")
		}
		dep, err := ParseDep(s.Value)
		if err != nil {
			return nil, err
		}
		if seen[dep.Source] {
			return nil, fmt.Errorf("依存「%s」が2回書かれています", dep.Source)
		}
		seen[dep.Source] = true
		out = append(out, dep)
	}
	return out, nil
}

// depsLine は 組.suru に書く「依存 とは …」の行
func depsLine(deps []Dep) string {
	var parts []string
	for _, d := range deps {
		parts = append(parts, "「"+d.String()+"」")
	}
	return "依存 とは " + strings.Join(parts, " と ")
}

// WriteDeps は 組.suru の「依存 とは …」を書きかえる(なければ終わりに足す)
func (p *Project) WriteDeps(deps []Dep) error {
	path := filepath.Join(p.Root, ConfigName)
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	lines := strings.Split(compiler.NormalizeNewlines(string(data)), "\n")
	if len(lines) > 0 && lines[len(lines)-1] == "" {
		lines = lines[:len(lines)-1]
	}
	var out []string
	if p.depLine == 0 {
		if len(deps) == 0 {
			return nil
		}
		out = append(lines, depsLine(deps))
	} else {
		start := p.depLine - 1
		end := start + 1 // 字下げした続きの行も「依存」のもの
		for end < len(lines) && (strings.HasPrefix(lines[end], " ") || strings.HasPrefix(lines[end], "\t") || strings.HasPrefix(lines[end], "　")) {
			end++
		}
		out = append(append(append([]string{}, lines[:start]...), depsLine(deps)), lines[end:]...)
		if len(deps) == 0 {
			out = append(append([]string{}, lines[:start]...), lines[end:]...)
		}
	}
	if err := os.WriteFile(path, []byte(strings.Join(out, "\n")+"\n"), 0o644); err != nil {
		return err
	}
	np, err := ParseConfig(strings.Join(out, "\n")+"\n", p.Root)
	if err != nil {
		return err
	}
	*p = *np
	return nil
}

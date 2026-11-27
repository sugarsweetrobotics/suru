package compiler

import (
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// 定義の説明(#209): 定義の型の宣言(なければ定義)のすぐ上に、空行をはさまずに書いた注釈の行がその説明。
// ファイルの頭の注釈(SPDX-License-Identifier と Copyright の行を除く)がファイル(モジュール)の説明。
// 「# 点検しない」の行は説明に入れない。

// DocComments は source の頭の説明と、一番外の名前ごとの説明を返す(program は source を解析したもの)
func DocComments(source string, program []Node) (module string, names map[string]string) {
	lines := SplitLines(source)
	names = map[string]string{}
	headEnd := 0 // ファイルの頭の注釈の最後の行(1 から。なければ 0)
	for headEnd < len(lines) {
		if _, ok := commentText(lines[headEnd]); !ok {
			break
		}
		headEnd++
	}
	if headEnd > 0 {
		module = docText(lines[:headEnd], true)
	}
	first := map[string]int{}
	var order []string
	var add func(n Node)
	add = func(n Node) {
		name, line := "", 0
		switch x := n.(type) {
		case *Define:
			if x.Test != "" || strings.HasPrefix(x.Name, "\x00") {
				return
			}
			name, line = x.Name, x.Line.Line
		case *TypeSig:
			name, line = x.Name, x.Line.Line
		case *TypeDef:
			name, line = x.Name, x.Line.Line
		case *TraitDecl:
			name, line = x.Name, x.Line.Line
		case *Block:
			for _, s := range x.Statements {
				add(s)
			}
			return
		default:
			return
		}
		if name == "" || line <= 0 {
			return
		}
		if l, ok := first[name]; !ok || line < l {
			if !ok {
				order = append(order, name)
			}
			first[name] = line
		}
	}
	for _, s := range program {
		add(s)
	}
	for _, name := range order {
		idx := first[name] - 1 // 定義の行(0 から)
		if idx > len(lines) {
			continue
		}
		start := idx
		for start > 0 {
			if _, ok := commentText(lines[start-1]); !ok {
				break
			}
			start--
		}
		// 上の注釈がファイルの頭まで続いていれば、それはファイルの説明
		if start == idx || start == 0 {
			continue
		}
		if d := docText(lines[start:idx], false); d != "" {
			names[name] = d
		}
	}
	return module, names
}

// commentText は注釈だけの行なら、注釈の印と、その後の空白1つを除いた中身を返す
func commentText(line string) (string, bool) {
	t := strings.TrimLeft(line, " \t　")
	for _, m := range []string{"#", "＃", "※"} {
		if strings.HasPrefix(t, m) {
			t = strings.TrimPrefix(t, m)
			if strings.HasPrefix(t, " ") {
				t = t[1:]
			} else if strings.HasPrefix(t, "　") {
				t = strings.TrimPrefix(t, "　")
			}
			return strings.TrimRight(t, " \t　\r"), true
		}
	}
	return "", false
}

// docText は注釈の行をつないで説明にする(頭の注釈なら SPDX と Copyright の行を除く)。前後の空の行は除く
func docText(lines []string, head bool) string {
	var out []string
	for _, l := range lines {
		t, _ := commentText(l)
		if strings.HasPrefix(t, "点検しない") {
			continue
		}
		if head && (strings.HasPrefix(t, "SPDX-License-Identifier:") || strings.HasPrefix(t, "Copyright") || strings.HasPrefix(t, "!")) {
			continue
		}
		out = append(out, t)
	}
	for len(out) > 0 && out[0] == "" {
		out = out[1:]
	}
	for len(out) > 0 && out[len(out)-1] == "" {
		out = out[:len(out)-1]
	}
	return strings.Join(out, "\n")
}

// DocItem は API ドキュメントの1つの名前(#209)
type DocItem struct {
	Name        string   `json:"name"`
	Kind        string   `json:"kind"` // 関数・値・型・性質
	Line        int      `json:"line"`
	Signature   string   `json:"signature"`   // 書いた型の宣言(型・性質なら定義)。なければ ""
	Usage       string   `json:"usage"`       // 関数の使い方(「x を 二倍する」)。関数でなければ ""
	Description string   `json:"description"` // すぐ上の注釈
	Examples    []string `json:"examples"`    // 「例えば … は … です」
}

// DocFile は1つのファイルの API ドキュメント
type DocFile struct {
	File        string    `json:"file"`
	Module      string    `json:"module"` // 読み込むときの名前(ファイルの名前から .suru を除いたもの)
	Description string    `json:"description"`
	Items       []DocItem `json:"items"`
}

// DocumentFile は path のファイルを解析して、公開の名前の API ドキュメントを作る
func DocumentFile(path string) (doc *DocFile, err error) {
	b, rerr := os.ReadFile(path)
	if rerr != nil {
		return nil, rerr
	}
	source := string(b)
	c := NewParseContext(filepath.Dir(absPath(path)))
	c.Path = filePath(path)
	var program []Node
	if e := try(func() { program = ParseProgram(source, c) }); e != nil {
		return nil, e
	}
	var private map[string]bool
	if e := try(func() { private = privateNames(program) }); e != nil {
		return nil, e
	}
	d := Document(source, program, private)
	d.File = path
	d.Module = strings.TrimSuffix(filepath.Base(path), ".suru")
	return d, nil
}

// Document は解析したプログラムから API ドキュメントを作る(private は外から見えない名前)
func Document(source string, program []Node, private map[string]bool) *DocFile {
	lines := SplitLines(source)
	module, descs := DocComments(source, program)
	d := &DocFile{Description: module, Items: []DocItem{}}
	index := map[string]int{}
	item := func(name string, line int) *DocItem {
		if i, ok := index[name]; ok {
			if line < d.Items[i].Line {
				d.Items[i].Line = line
			}
			return &d.Items[i]
		}
		index[name] = len(d.Items)
		d.Items = append(d.Items, DocItem{Name: name, Line: line, Description: descs[name], Examples: []string{}})
		return &d.Items[len(d.Items)-1]
	}
	var examples []*Define
	var add func(n Node)
	add = func(n Node) {
		switch x := n.(type) {
		case *Block:
			for _, s := range x.Statements {
				add(s)
			}
		case *Define:
			if x.Example != nil && x.Test != "" {
				examples = append(examples, x)
				return
			}
			if x.Test != "" || strings.HasPrefix(x.Name, "\x00") || private[x.Name] {
				return
			}
			it := item(x.Name, x.Line.Line)
			if x.IsFunction {
				it.Kind = DocKindFunction
				simple := true
				for _, p := range x.Params {
					if p.Pat != nil {
						simple = false
					}
				}
				if it.Usage == "" || simple && strings.Contains(it.Usage, "…") {
					it.Usage = docUsage(x.Name, x.Params)
				}
			} else if it.Kind == "" {
				it.Kind = DocKindValue
			}
		case *TypeSig:
			if private[x.Name] {
				return
			}
			it := item(x.Name, x.Line.Line)
			it.Signature = statementText(lines, x.Line.Line)
			if x.HasParams {
				it.Kind = DocKindFunction
			} else if it.Kind == "" {
				it.Kind = DocKindValue
			}
		case *TypeDef:
			it := item(x.Name, x.Line.Line)
			it.Kind, it.Signature = DocKindType, statementText(lines, x.Line.Line)
		case *TraitDecl:
			it := item(x.Name, x.Line.Line)
			it.Kind, it.Signature = DocKindTrait, statementText(lines, x.Line.Line)
		}
	}
	for _, s := range program {
		add(s)
	}
	for _, x := range examples {
		if i, ok := index[strings.TrimSuffix(x.Test, "の例")]; ok {
			d.Items[i].Examples = append(d.Items[i].Examples, statementText(lines, x.Line.Line))
		}
	}
	sort.SliceStable(d.Items, func(i, j int) bool { return d.Items[i].Line < d.Items[j].Line })
	return d
}

// docUsage は usage と同じ使い方を作る。引数の名前に付いた「表内の」は除く(読み込んだファイルの形と同じ名前の引数)
func docUsage(name string, params []Param) string {
	ps := make([]Param, len(params))
	for i, p := range params {
		ps[i] = p
		ps[i].Name = shortName(p.Name)
		if p.Names != nil {
			ps[i].Names = make([]string, len(p.Names))
			for j, n := range p.Names {
				ps[i].Names[j] = shortName(n)
			}
		}
	}
	return usage(name, ps)
}

// shortName は引数の名前から「表内の」を除く。外部の関数のまとまりで付けた「引数1」などは「…」にする
func shortName(n string) string {
	if i := strings.LastIndex(n, ModuleSep); i >= 0 {
		n = n[i+len(ModuleSep):]
	}
	if d := strings.TrimPrefix(n, "引数"); d != n && d != "" && strings.Trim(d, "0123456789") == "" {
		return "…"
	}
	if strings.HasPrefix(n, "（") { // 場合ごとの定義をまとめたときの引数(「（を）」)
		return "…"
	}
	return n
}

// 名前の種類
const (
	DocKindFunction = "関数"
	DocKindValue    = "値"
	DocKindType     = "型"
	DocKindTrait    = "性質"
)

// statementText は line(1 から)から始まる一番外の文の字句: その行と、続く字下げした行
func statementText(lines []string, line int) string {
	if line < 1 || line > len(lines) {
		return ""
	}
	first := lines[line-1]
	if t := strings.TrimLeft(first, " \t　"); t != first {
		// まとまり(以下は外部の…です)の中の行は、その1行だけ
		return strings.TrimRight(t, " \t\r")
	}
	out := []string{strings.TrimRight(first, " \t\r")}
	for i := line; i < len(lines); i++ {
		l := lines[i]
		if strings.TrimSpace(l) == "" || !(strings.HasPrefix(l, " ") || strings.HasPrefix(l, "\t") || strings.HasPrefix(l, "　")) {
			break
		}
		if _, ok := commentText(l); ok {
			break
		}
		out = append(out, strings.TrimRight(l, " \t\r"))
	}
	return strings.Join(out, "\n")
}

// Markdown は API ドキュメントを Markdown(MyST でも読める形)にする
func (d *DocFile) Markdown() string {
	var b strings.Builder
	b.WriteString("# 「" + d.Module + "」\n")
	if d.Description != "" {
		b.WriteString("\n" + d.Description + "\n")
	}
	for _, it := range d.Items {
		b.WriteString("\n## " + it.Name + "\n")
		if it.Signature != "" {
			b.WriteString("\n```suru\n" + it.Signature + "\n```\n")
		}
		if it.Usage != "" {
			b.WriteString("\n使い方: `" + it.Usage + "`\n")
		}
		if it.Description != "" {
			b.WriteString("\n" + it.Description + "\n")
		}
		if len(it.Examples) > 0 {
			b.WriteString("\n例:\n\n```suru\n" + strings.Join(it.Examples, "\n") + "\n```\n")
		}
	}
	return b.String()
}

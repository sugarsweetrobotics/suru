package compiler

import "strings"

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

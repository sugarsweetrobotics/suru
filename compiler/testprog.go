// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"fmt"
	"strings"
)

// TestSuffix で終わる名前の、一番外の引数のない定義も試験(kumu 試験 の 試験/ のファイルと同じ)
const TestSuffix = "試験する"

// TestCase はファイルの試験の1つ(試験のまとまり・例・「…試験する」)
type TestCase struct {
	// Label は表示の名前(「二倍」「二倍するの例(4行)」「二倍試験する」)
	Label string
	// Number は試験用のバイナリに渡す番号(1 から)
	Number int
}

// testLabel は試験の表示の名前(suru.py の test_label と同じ)
func testLabel(d *Define) string {
	if d.Example != nil {
		return fmt.Sprintf("%s(%d行)", d.Test, d.Line.Line)
	}
	if d.Test != "" {
		return d.Test
	}
	return d.Name
}

// isTestName は試験のまとまりと例に付ける、プログラムには書けない名前か(「《試験》二倍」「《例》4」)
func isTestName(name string) bool {
	return strings.HasPrefix(name, testPrefix) || strings.HasPrefix(name, examplePrefix)
}

// isTestCase は試験として動かす定義か(試験のまとまり・例・一番外の引数のない「…試験する」)
func isTestCase(d *Define) bool {
	return d.Test != "" || d.IsFunction && len(d.Params) == 0 && strings.HasSuffix(d.Name, TestSuffix) && !strings.Contains(d.Name, ModuleSep)
}

// testRunName は試験用のプログラムの中で k 番目の試験に付ける名前(カタカナだけにして、書いた名前とぶつからないようにする)
func testRunName(k int, part string) string {
	digits := []string{"ア", "イ", "ウ", "エ", "オ", "カ", "キ", "ク", "ケ", "コ"}
	var b strings.Builder
	b.WriteString("シケンジッコウ")
	for _, c := range fmt.Sprint(k) {
		b.WriteString(digits[c-'0'])
	}
	b.WriteString(part)
	b.WriteString("する")
	return b.String()
}

// CompileTests は、ファイルの試験を引数の番号で選んで動かすプログラムの LLVM IR を作る(suruc --試験・kumu 試験)。
// 一番外の行うこと(式)は行わない。試験は同じファイルの中で動くので、非公開の名前も使える。
// display はエラーの知らせに書くファイルの道。match が nil でなければ、合う名前の試験だけを入れる。
// 試験が1つもなければ ir は ""
func CompileTests(source, baseDir, path, display string, match func(label string) bool) (ir string, cases []TestCase, err *SuruError) {
	ctx := NewParseContext(baseDir)
	ctx.Path = filePath(path)
	var program []Node
	if err = tagged("構文", func() { program = ParseProgram(source, ctx) }); err != nil {
		return
	}
	if err = tagged("型", func() { TypeCheck(program, ctx) }); err != nil {
		return
	}
	var kept []Node
	var disp strings.Builder
	for _, s := range program {
		d, ok := s.(*Define)
		if !ok {
			if isTopLevelOnly(s) {
				kept = append(kept, s)
			}
			continue // 一番外の行うことは行わない
		}
		if !isTestCase(d) {
			kept = append(kept, d)
			continue
		}
		label := testLabel(d)
		if match != nil && !match(label) {
			if d.Test == "" {
				kept = append(kept, d) // 「…試験する」はほかの定義から呼ばれるかもしれない
			}
			continue
		}
		k := len(cases) + 1
		cases = append(cases, TestCase{label, k})
		kw := "そうでなければ もし"
		if k == 1 {
			kw = "もし"
		}
		if d.Example != nil {
			actual, expected := testRunName(k, "ジッサイ"), testRunName(k, "キタイ")
			kept = append(kept, &Define{actual, nil, d.Example[0], true, d.Line, "", nil},
				&Define{expected, nil, d.Example[1], true, d.Line, "", nil})
			fmt.Fprintf(&disp, "  %s 引数 の 先頭 = 「%d」 ならば （%s） を （%s） に 「%s」 で 例確認する\n", kw, k, actual, expected, escapeQuote(fmt.Sprintf("%s:%d", display, d.Line.Line)))
		} else {
			name := d.Name
			if d.Test == "" {
				kept = append(kept, d)
			} else {
				name = testRunName(k, "")
				kept = append(kept, &Define{name, nil, d.Body, true, d.Line, "", nil})
			}
			fmt.Fprintf(&disp, "  %s 引数 の 先頭 = 「%d」 ならば （%s） を 結果無視する\n", kw, k, name)
		}
	}
	if len(cases) == 0 {
		return "", nil, nil
	}
	// 引数で試験を選ぶ部分。行の番号はファイルの後ろに続ける(エラーの表示で、ファイルの行と混ざらないように)
	text := strings.Repeat("\n", lineCount(source)) + "# 試験を引数の番号で選んで行う(suruc --試験 が作った部分です)\n" +
		"「標準」 を 読み込む\n「環境」 を 読み込む\n\n" +
		"m を 結果無視する とは m を （x を 受け取って （0 を 結果にする） を 返すこと） で 連鎖する\n\n" +
		"文字列 を 例不合格にする は 数 の 動作\n" +
		"文 を 例不合格にする とは 以下の手順です\n  文 を 環境内のエラー出力する\n  1 を 環境内の終了する\n  以上です\n\n" +
		"甲 を 甲 に 文字列 で 例確認する は 数 の 動作\n" +
		"実際 を 期待 に 場所 で 例確認する とは\n" +
		"  もし 実際 = 期待 ならば 0 を 結果にする\n" +
		"  そうでなければ （場所 + 「: 等しくありません: 期待は 」 + （期待 を 文字列化する） + 「 / 実際は 」 + （実際 を 文字列化する）） を 例不合格にする\n\n" +
		"引数 を 試験選択する とは\n" + disp.String() + "  そうでなければ 0 を 結果にする\n\n" +
		"標準内の引数取得してから 試験選択する\n"
	full := source + text[lineCount(source)-1:]
	err = tagged("コンパイル", func() {
		extra := ParseProgram(text, ctx)
		var imports, rest []Node
		for _, s := range extra {
			if _, ok := s.(*Import); ok {
				imports = append(imports, s)
			} else {
				rest = append(rest, s)
			}
		}
		all := append(append(imports, kept...), rest...)
		TypeCheck(all, ctx)
		checkDefinitions(all, ctx)
		setLineBase(ctx, full)
		ir = newCompiler(ctx, full).compile(all, path)
	})
	return
}

// escapeQuote は「」の中に書ける文字列にする(文字列の中の「」は入れ子として数えるので、対になっていれば書ける)
func escapeQuote(s string) string {
	if strings.Count(s, "「") == strings.Count(s, "」") {
		return s
	}
	return strings.NewReplacer("「", "[", "」", "]").Replace(s)
}

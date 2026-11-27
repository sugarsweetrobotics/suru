package compiler

import (
	"strconv"
	"strings"
)

// ExportInfo は外部に出す関数の1つ(IR の始めの「; suru-export: 」の行から読む、#208)
type ExportInfo struct {
	Symbol string // C の名前
	Codes  string // 型の字(引数の字の後に値の字、動作なら最後に「!」。字は exportCodes)
	Name   string // する の名前
}

// Exports は IR の始めの「; suru-export: C の名前 型の字 する の名前」の行を読む
func Exports(ir string) []ExportInfo {
	var out []ExportInfo
	for _, line := range strings.Split(ir, "\n") {
		if !strings.HasPrefix(line, ";") {
			break
		}
		if !strings.HasPrefix(line, ExportMark) {
			continue
		}
		f := strings.SplitN(strings.TrimPrefix(line, ExportMark), " ", 3)
		e := ExportInfo{Symbol: f[0]}
		if len(f) == 3 {
			e.Codes, e.Name = f[1], f[2]
		}
		out = append(out, e)
	}
	return out
}

// LibHelper は共有ライブラリが出す補助の関数(頭の名前_init など)の1つ。
// 実行時ライブラリの rt_lib_名前 を呼ぶ。型の「V」はヘッダでは 頭の名前_value、包みの C では void になる(#208)
type LibHelper struct {
	Ret    string
	Name   string
	Params [][2]string
	En, Ja string
}

// LibHelpers は補助の関数(Python 版の LIB_HELPERS と同じ)
var LibHelpers = []LibHelper{
	{"int", "init", nil, "Initializes the library (the first call also does it). 0 on success, -1 on failure.",
		"ライブラリを用意します(最初の呼び出しでも行います)。うまくいけば 0、失敗なら -1。"},
	{"const char *", "last_error", nil, "The error message of the last call on this thread, or NULL. The library owns it;\n * it stays valid until the next call on this thread (do not free it).",
		"このスレッドで最後に呼んだ関数のエラーの文(なければ NULL)。ライブラリのもので、\n * このスレッドで次に呼ぶまで使えます(解放しません)。"},
	{"void", "free", [][2]string{{"void *", "p"}}, "Frees a string, a list or a バイト列 returned by this library.",
		"このライブラリが返した文字列・リスト・バイト列を解放します。"},
	{"void", "release", [][2]string{{"V *", "h"}}, "Releases a handle (NULL is ignored). Any thread may call it at any time.",
		"手札を手放します(NULL なら何もしません)。どのスレッドからいつでも呼べます。"},
	{"const char *", "type", [][2]string{{"const V *", "h"}}, "The Suru type of the value (リスト, 数, 文字列, a record type ...). Do not free it.",
		"値の する の型の名前(リスト・数・文字列・組の型の名前など)。解放しません。"},
	{"char *", "show", [][2]string{{"const V *", "h"}}, "The value as 表示する shows it. Free it with {free}.",
		"表示する と同じ形の文字列。{free} で解放します。"},
	{"int64_t", "len", [][2]string{{"const V *", "h"}}, "The length of a list or a バイト列.",
		"リストかバイト列の長さ。"},
	{"V *", "get", [][2]string{{"const V *", "h"}, {"int64_t", "i"}}, "Item i (from 0) of a list, as a new handle.",
		"リストの i 番目(0 から)を新しい手札で返します。"},
	{"V *", "field", [][2]string{{"const V *", "h"}, {"const char *", "name"}}, "The field name of a record, as a new handle.",
		"組の項目 name を新しい手札で返します。"},
	{"int64_t", "to_int", [][2]string{{"const V *", "h"}}, "The value as a 数.", "値を 数 として読みます。"},
	{"double", "to_double", [][2]string{{"const V *", "h"}}, "The value as a 小数.", "値を 小数 として読みます。"},
	{"int", "to_bool", [][2]string{{"const V *", "h"}}, "The value as a 真偽 (0 or 1).", "値を 真偽(0 か 1)として読みます。"},
	{"char *", "to_string", [][2]string{{"const V *", "h"}}, "The value as a 文字列. Free it with {free}.",
		"値を 文字列 として読みます。{free} で解放します。"},
	{"V *", "from_int", [][2]string{{"int64_t", "x"}}, "A new handle holding the 数 x.", "数 x の新しい手札。"},
	{"V *", "from_double", [][2]string{{"double", "x"}}, "A new handle holding the 小数 x.", "小数 x の新しい手札。"},
	{"V *", "from_bool", [][2]string{{"int", "x"}}, "A new handle holding the 真偽 x.", "真偽 x の新しい手札。"},
	{"V *", "from_string", [][2]string{{"const char *", "s"}}, "A new handle holding a copy of the UTF-8 string s.",
		"UTF-8 の文字列 s の写しの新しい手札。"},
	{"V *", "list", [][2]string{{"V *const *", "items"}, {"int64_t", "n"}}, "A new handle holding the list of the n handles in items.",
		"items の n 個の手札のリストの新しい手札。"},
	{"V *", "call", [][2]string{{"const V *", "f"}, {"V *const *", "args"}, {"int64_t", "n"}},
		"Calls the function f with n handles. An action result is carried out. A new handle.",
		"関数 f を n 個の手札で呼びます。値が動作なら行います。新しい手札で返します。"},
}

// LibShim は補助の関数(頭の名前_init など)を出す小さな C のファイルの中身(Python 版の lib_shim と同じ)
func LibShim(prefix string) string {
	var b strings.Builder
	b.WriteString("#include <stdint.h>\n#define E __attribute__((visibility(\"default\")))\n")
	for _, h := range LibHelpers {
		var ps, as []string
		for _, p := range h.Params {
			ps = append(ps, cDecl(strings.ReplaceAll(p[0], "V", "void"), p[1]))
			as = append(as, p[1])
		}
		params := strings.Join(ps, ", ")
		if params == "" {
			params = "void"
		}
		ret := strings.ReplaceAll(h.Ret, "V", "void")
		call := "rt_lib_" + h.Name + "(" + strings.Join(as, ", ") + ");"
		if ret != "void" {
			call = "return " + call
		}
		b.WriteString(cDecl(ret, "rt_lib_"+h.Name) + "(" + params + ");\n")
		b.WriteString("E " + cDecl(ret, prefix+"_"+h.Name) + "(" + params + ") { " + call + " }\n")
	}
	return b.String()
}

// LibHelperSymbols は補助の関数の C の名前
func LibHelperSymbols(prefix string) []string {
	var out []string
	for _, h := range LibHelpers {
		out = append(out, prefix+"_"+h.Name)
	}
	return out
}

// headerTypes は型の字 → ヘッダに書く引数の C の型・値の C の型・する の型
// (y・L・D・S は番地と長さの2つで渡し、値なら長さを out_len に書く、#208 段階3)
var headerTypes = map[byte][3]string{
	'l': {"int64_t", "int64_t", "数"}, 'i': {"int", "int", "整数"}, 'd': {"double", "double", "小数"}, 'f': {"float", "float", "単精度"},
	'b': {"int", "int", "真偽"}, 's': {"const char *", "char *", "文字列"}, 'h': {"V *", "V *", "(手札)"}, 'p': {"void *", "void *", "番地"}, 'v': {"void", "void", "無"},
	'y': {"const uint8_t *", "uint8_t *", "バイト列"}, 'L': {"const int64_t *", "int64_t *", "数 の リスト"},
	'D': {"const double *", "double *", "小数 の リスト"}, 'S': {"const char *const *", "char **", "文字列 の リスト"},
}

func headerSeq(c byte) bool {
	return strings.IndexByte("yLDS", c) >= 0
}

// cDecl は C の型と名前を並べる(「int64_t a1」「const char *a1」)
func cDecl(t, name string) string {
	if strings.HasSuffix(t, "*") {
		return t + name
	}
	return t + " " + name
}

// ExportHeader は共有ライブラリの C のヘッダ(頭の名前.h)の中身を作る(#208 段階2)。
// Python 版の export_header と同じ文字を出す
func ExportHeader(ir, prefix string) string {
	guard := strings.ToUpper(prefix) + "_H"
	var b strings.Builder
	b.WriteString("/* " + prefix + ".h: generated by suruc. Do not edit.\n" +
		" * 「する」のコンパイラが作ったヘッダです。直さないでください。\n" +
		" *\n" +
		" * Errors: a call that fails returns 0, 0.0 or NULL, and " + prefix + "_last_error()\n" +
		" *   returns its message (NULL when the last call on this thread succeeded).\n" +
		" * Strings: string arguments are UTF-8 and are copied. A returned char * is\n" +
		" *   yours: free it with " + prefix + "_free().\n" +
		" * Numbers: 数 (int64_t) must be within +-2^62; larger values are an error.\n * Lists and バイト列: an argument is a pointer and a length (aN, aN_len) and is copied;\n *   a result is a new block whose length is written to *out_len.\n * Threads: any thread may call these functions, also at the same time.\n" +
		" *\n" +
		" * エラー: 失敗した呼び出しは 0・0.0・NULL を返し、" + prefix + "_last_error() で文を読めます\n" +
		" *   (このスレッドの最後の呼び出しがうまくいったときは NULL)。\n" +
		" * 文字列: 引数の文字列は UTF-8 で、写し取ります。返った char * は呼んだ側のもので、\n" +
		" *   " + prefix + "_free() で解放します。\n" +
		" * 数: 数(int64_t)は ±2^62 までです。超えるとエラーになります。\n * リストとバイト列: 引数は番地と長さ(aN と aN_len)で渡し、写し取ります。\n *   値は新しい塊で、長さを *out_len に書きます。\n * スレッド: どのスレッドからも、同時にでも呼べます。\n" +
		" */\n" +
		"#ifndef " + guard + "\n#define " + guard + "\n\n#include <stdint.h>\n\n" +
		"#ifdef __cplusplus\nextern \"C\" {\n#endif\n")
	for k, h := range LibHelpers {
		if k == 3 {
			b.WriteString("\n/* Handles: a value that is not a number, a string, a バイト列 or a list of numbers,\n" +
				" * decimals or strings (a record, another list, a function ...) is passed as a\n" +
				" * " + prefix + "_value *. A handle you get stays alive until " + prefix + "_release(); a handle\n" +
				" * you pass in is only borrowed.\n" +
				" * 手札: 数・文字列・バイト列・数や小数や文字列のリストで渡せない値(組・ほかのリスト・関数など)は\n" +
				" * " + prefix + "_value * で渡します。受け取った手札は " + prefix + "_release() まで使えます。\n" +
				" * 渡した手札は借りるだけです。 */\n" +
				"typedef struct " + prefix + "_value " + prefix + "_value;\n")
		}
		var ps []string
		for _, p := range h.Params {
			ps = append(ps, cDecl(strings.ReplaceAll(p[0], "V", prefix+"_value"), p[1]))
		}
		args := strings.Join(ps, ", ")
		if args == "" {
			args = "void"
		}
		doc := strings.ReplaceAll("\n/* "+h.En+"\n * "+h.Ja+" */\n", "{free}", prefix+"_free()")
		b.WriteString(doc +
			cDecl(strings.ReplaceAll(h.Ret, "V", prefix+"_value"), prefix+"_"+h.Name) + "(" + args + ");\n")
	}
	for _, e := range Exports(ir) {
		codes := strings.TrimSuffix(e.Codes, "!")
		action := codes != e.Codes
		if codes == "" {
			continue
		}
		params := codes[:len(codes)-1]
		var cps, sps []string
		for k := 0; k < len(params); k++ {
			t := headerTypes[params[k]]
			a := "a" + strconv.Itoa(k+1)
			cps = append(cps, cDecl(strings.ReplaceAll(t[0], "V", prefix+"_value"), a))
			if headerSeq(params[k]) {
				cps = append(cps, "int64_t "+a+"_len")
			}
			sps = append(sps, t[2])
		}
		rc := codes[len(codes)-1]
		res := headerTypes[rc]
		if headerSeq(rc) {
			cps = append(cps, "int64_t *out_len")
		}
		args := strings.Join(cps, ", ")
		if args == "" {
			args = "void"
		}
		sig := strings.Join(sps, " と ")
		if sig == "" {
			sig = "(なし)"
		}
		b.WriteString("\n/* する: " + e.Name + "  " + sig + " → " + res[2])
		if action {
			b.WriteString("(入出力動作)")
		}
		switch {
		case rc == 's':
			b.WriteString("\n * The result is yours: free it with " + prefix + "_free(). / 値は " + prefix + "_free() で解放します。")
		case rc == 'S':
			b.WriteString("\n * The result is an array of out_len strings ending with NULL, in one block: free it once with " + prefix + "_free().\n" +
				" * 値は out_len 個の文字列の並び(最後に NULL)で、1つの塊です。" + prefix + "_free() で1回だけ解放します。")
		case rc == 'h':
			b.WriteString("\n * The result is a new handle: release it with " + prefix + "_release(). / 値は新しい手札で、" + prefix + "_release() で手放します。")
		case headerSeq(rc):
			b.WriteString("\n * The result has *out_len items (out_len may be NULL); free it with " + prefix + "_free().\n" +
				" * 値の長さは *out_len に書きます(out_len は NULL でもよい)。" + prefix + "_free() で解放します。")
		}
		b.WriteString(" */\n")
		b.WriteString(cDecl(strings.ReplaceAll(res[1], "V", prefix+"_value"), e.Symbol) + "(" + args + ");\n")
	}
	b.WriteString("\n#ifdef __cplusplus\n}\n#endif\n\n#endif /* " + guard + " */\n")
	return b.String()
}

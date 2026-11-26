package compiler

// 外部の関数を1行で書く(#173)・外部の関数のまとまり(#174)。suru.py の expand_externs と同じ。
// 字下げの木にする前に、型の宣言の行と定義の行の2行(今までの書き方)に直す

import "fmt"

const extOneLineExample = "「n を 確保する とは 外部の「SDL_malloc」 で 数 を 受け取って 番地 を 返す 入出力動作です」"
const extBlockLineHelp = "1行に1つ、「数 を 確保する は 「SDL_malloc」 で 番地 を 返します」か、" +
	"名前を付けて「r を 読取する とは 「SDL_RenderReadPixels」（r と 0） で 番地 を 受け取って 番地 を 返します」の形で書きます"

// topLevelIndexes は括弧の外で pred に合う字句の位置
func topLevelIndexes(tokens []*Token, pred func(*Token) bool) []int {
	depth := 0
	var out []int
	for i, t := range tokens {
		switch {
		case t.Kind == "LP":
			depth++
		case t.Kind == "RP":
			depth--
		case depth == 0 && pred(t):
			out = append(out, i)
		}
	}
	return out
}

func topParticles(tokens []*Token) []*Token {
	var out []*Token
	for _, i := range topLevelIndexes(tokens, func(t *Token) bool { return t.Kind == "PART" }) {
		out = append(out, tokens[i])
	}
	return out
}

// closeParenAfter は tokens[k] の「（」に対応する「）」の次の位置(なければ -1)
func closeParenAfter(tokens []*Token, k int) int {
	depth := 0
	for i := k; i < len(tokens); i++ {
		switch tokens[i].Kind {
		case "LP":
			depth++
		case "RP":
			depth--
			if depth == 0 {
				return i + 1
			}
		}
	}
	return -1
}

func extName(head []*Token) *Token {
	calls := topLevelIndexes(head, func(t *Token) bool { return t.Kind == "CALL" })
	if len(calls) == 0 {
		return nil
	}
	return head[calls[len(calls)-1]]
}

func isPartS(t *Token, v string) bool { return t.Kind == "PART" && t.S == v }

func cat(parts ...[]*Token) []*Token {
	var out []*Token
	for _, p := range parts {
		out = append(out, p...)
	}
	return out
}

// ioResult はまとまり「以下は外部の入出力動作です」の値の型「番地 を 返します」を「番地 を 返す 入出力動作」にする
func ioResult(res []*Token, word string) []*Token {
	line := res[0].Line
	if n := len(res); n >= 2 && isPartS(res[n-2], "を") && (isKw(res[n-1], KwHensu) || isKw(res[n-1], KwHensuPolite)) {
		res = res[:n-2]
	}
	if len(res) == 0 {
		raise(line, "値の型がありません(「番地 を 返します」のように書きます)")
	}
	last := res[len(res)-1]
	if last.Kind == "WORD" && !last.Quoted && (last.S == "動作" || last.S == "入出力動作") {
		raise(last.Line, "「"+word+"です」の中では、値の型に「"+last.S+"」を書きません(「番地 を 返します」のように書きます)")
	}
	return cat(res, []*Token{tok("PART", "を", line), tok("KW", KwHensu, line), tok("WORD", "入出力動作", line)})
}

// typedExtern は「頭 とは 外部の「f」 で 型」を、型の宣言の行と定義の行にする。word はまとまりの言葉(まとまりの外なら "")
func typedExtern(ln *Line, head []*Token, towa *Token, ext, typ []*Token, word string) []*Line {
	name := extName(head)
	if name == nil {
		at := towa.Line
		if len(head) > 0 {
			at = head[0].Line
		}
		raise(at, "型を後ろに書けるのは関数の定義だけです("+extOneLineExample+")")
	}
	if len(typ) == 0 {
		raise(towa.Line, "「で」の後に型を書きます("+extOneLineExample+")")
	}
	args, res := []*Token(nil), typ
	if lam := topLevelIndexes(typ, func(t *Token) bool { return isKw(t, KwLambda) }); len(lam) > 0 {
		args, res = typ[:lam[0]], typ[lam[0]+1:]
	}
	var want, got []string
	for _, t := range topParticles(head) {
		want = append(want, t.S)
	}
	for _, t := range topParticles(args) {
		got = append(got, t.S)
	}
	same := len(want) == len(got)
	for i := 0; same && i < len(want); i++ {
		same = want[i] == got[i]
	}
	if !same || (len(args) > 0 && args[len(args)-1].Kind != "PART") {
		order := "なし"
		if len(want) > 0 {
			order = joinStrings(want, "・")
		}
		raise(typ[0].Line, "「"+name.S+"」の型の引数は、定義と同じ助詞を同じ順に書き、最後に「受け取って」を書きます(定義の助詞: "+order+")")
	}
	if len(res) == 0 {
		raise(typ[len(typ)-1].Line, "「受け取って」の後に値の型を書きます("+extOneLineExample+")")
	}
	if extIOWords[word] {
		res = ioResult(res, word)
	}
	sig := cat(args, []*Token{name, tok("KW", KwWa, name.Line)}, res)
	def := cat(head, []*Token{towa}, ext)
	return []*Line{{0, sig, ln.Number, ln.Closed}, {0, def, ln.Number, ln.Closed}}
}

func joinStrings(xs []string, sep string) string {
	out := ""
	for i, x := range xs {
		if i > 0 {
			out += sep
		}
		out += x
	}
	return out
}

// extSplit は「「f」（…） で 型」を「「f」（…）」と型に分ける(合わなければ ok = false)
func extSplit(after []*Token) (ext, typ []*Token, ok bool) {
	if len(after) < 2 || after[0].Kind != "STR" {
		return nil, nil, false
	}
	k := 1
	if after[k].Kind == "LP" {
		k = closeParenAfter(after, k)
		if k < 0 {
			return nil, nil, false
		}
	}
	if k >= len(after) || !isPartS(after[k], "で") {
		return nil, nil, false
	}
	return after[:k], after[k+1:], true
}

func isExternWord(t *Token) bool { return t.Kind == "WORD" && t.S == KwExtern && !t.Quoted }

// externOneLine は「n を 確保する とは 外部の「SDL_malloc」 で 数 を 受け取って 番地 を 返す 入出力動作です」(#173)
func externOneLine(ln *Line) []*Line {
	ts := nosep(ln.Tokens)
	towa := findTopLevel(ts, KwTowa)
	if towa < 0 {
		return nil
	}
	after := ts[towa+1:]
	if len(after) == 0 || !isExternWord(after[0]) {
		return nil
	}
	ext, typ, ok := extSplit(after[1:])
	if !ok {
		return nil
	}
	return typedExtern(ln, ts[:towa], ts[towa], cat([]*Token{after[0]}, ext), typ, "")
}

// externBlockLine はまとまりの中の1行を、型の宣言の行と定義の行にする
func externBlockLine(ln *Line, word string) []*Line {
	ts := nosep(ln.Tokens)
	if towa := findTopLevel(ts, KwTowa); towa >= 0 {
		// 名前を付けた定義の形: 「r を 読取する とは 「f」（r と 0） で 番地 を 受け取って 番地 を 返します」
		after := ts[towa+1:]
		extTok := tok("WORD", KwExtern, ts[towa].Line)
		if len(after) > 0 && isExternWord(after[0]) {
			extTok, after = after[0], after[1:]
		}
		ext, typ, ok := extSplit(after)
		if !ok {
			raise(ln.Number, "「"+word+"です」の中には、"+extBlockLineHelp)
		}
		return typedExtern(ln, ts[:towa], ts[towa], cat([]*Token{extTok}, ext), typ, word)
	}
	wa := topLevelIndexes(ts, func(t *Token) bool { return isKw(t, KwWa) })
	if len(wa) == 0 {
		raise(ln.Number, "「"+word+"です」の中には、"+extBlockLineHelp)
	}
	before, after := ts[:wa[0]], ts[wa[0]+1:]
	name := extName(before)
	if name == nil || len(after) < 3 || after[0].Kind != "STR" || !isPartS(after[1], "で") {
		if name != nil && len(after) >= 2 && after[0].Kind == "STR" && after[1].Kind == "LP" {
			raise(after[1].Line, "C に渡す引数を並べて書くときは、名前を付けた定義の形で書きます"+
				"(「r を 読取する とは 「SDL_RenderReadPixels」（r と 0） で 番地 を 受け取って 番地 を 返します」)")
		}
		raise(ln.Number, "「"+word+"です」の中には、"+extBlockLineHelp)
	}
	res := after[2:]
	if extIOWords[word] {
		res = ioResult(res, word)
	}
	// 定義の引数の名前は使わないので、「引数1」「引数2」… にする
	ni := 0
	for i, t := range before {
		if t == name {
			ni = i
		}
	}
	var head []*Token
	for k, p := range topParticles(before[:ni]) {
		head = append(head, tok("WORD", fmt.Sprintf("引数%d", k+1), p.Line), p)
	}
	head = append(head, name)
	sig := cat(before, []*Token{ts[wa[0]]}, res)
	def := cat(head, []*Token{tok("KW", KwTowa, name.Line), tok("WORD", KwExtern, after[0].Line), after[0]})
	return []*Line{{0, sig, ln.Number, ln.Closed}, {0, def, ln.Number, ln.Closed}}
}

// opensExtBlock は「以下は外部の入出力動作です」「以下は外部の関数です」(「以下の外部の…」も)だけの行か
func opensExtBlock(ln *Line) bool {
	ts := nosep(ln.Tokens)
	return len(ts) == 1 && ts[0].Kind == "KW" && extBlockWords[ts[0].S]
}

// expandExterns は外部の関数の1行の書き方とまとまりを、型の宣言と定義の2行ずつにする(一番外だけ)
func expandExterns(lines []*Line) []*Line {
	var out []*Line
	for i := 0; i < len(lines); {
		ln := lines[i]
		if opensExtBlock(ln) {
			word := nosep(ln.Tokens)[0].S
			if ln.Indent != 0 {
				raise(ln.Number, "「"+word+"です」は一番外(字下げなし)に書きます")
			}
			i++
			names := map[string]int{}
			count := 0
			deep := i < len(lines) && lines[i].Indent > 0
			for i < len(lines) && !isIjou(lines[i]) {
				b := lines[i]
				if deep && b.Indent == 0 {
					break // 深い行のまとまりの後に、頭と同じ字下げの行: 「以上」を書き忘れた
				}
				pair := externBlockLine(b, word)
				d := nosep(pair[1].Tokens)
				name := d[findTopLevel(d, KwTowa)-1].S
				if at, ok := names[name]; ok {
					raise(b.Number, fmt.Sprintf("「%s」がまとまりの中で2回書かれています(%d行目と%d行目)", name, at, b.Number.Line))
				}
				names[name] = b.Number.Line
				out = append(out, pair...)
				count++
				i++
			}
			if i >= len(lines) || !isIjou(lines[i]) {
				raise(ln.Number, "「"+word+"です」を閉じる「"+KwIjou+"」がありません(最後の関数の行の後に「"+KwIjou+"」だけの行を書きます)")
			}
			if count == 0 {
				raise(ln.Number, "「"+word+"です」と「"+KwIjou+"」の間に関数がありません")
			}
			i++
			continue
		}
		if ln.Indent == 0 {
			if pair := externOneLine(ln); pair != nil {
				out = append(out, pair...)
				i++
				continue
			}
		}
		out = append(out, ln)
		i++
	}
	return out
}

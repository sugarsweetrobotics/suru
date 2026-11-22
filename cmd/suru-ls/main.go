// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// suru-ls は「する」の言語サーバー(Language Server Protocol)。標準入出力で話す。
// エディターに、書いている途中の間違い・名前の型(ホバー)・定義へ移動・定義の一覧を出す。
//
//	suru-ls            # エディターから起動する
//	suru-ls --version
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"unicode/utf16"

	suru "github.com/sugarsweetrobotics/suru"
	"github.com/sugarsweetrobotics/suru/compiler"
)

const version = "0.1.0"

// --- JSON-RPC ---

type message struct {
	JSONRPC string           `json:"jsonrpc"`
	ID      *json.RawMessage `json:"id,omitempty"`
	Method  string           `json:"method,omitempty"`
	Params  json.RawMessage  `json:"params,omitempty"`
	Result  any              `json:"result,omitempty"`
	Error   *rpcError        `json:"error,omitempty"`
}

type rpcError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

func readMessage(r *bufio.Reader) ([]byte, error) {
	length := -1
	for {
		line, err := r.ReadString('\n')
		if err != nil {
			return nil, err
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			break
		}
		if k, v, ok := strings.Cut(line, ":"); ok && strings.EqualFold(strings.TrimSpace(k), "Content-Length") {
			length, err = strconv.Atoi(strings.TrimSpace(v))
			if err != nil {
				return nil, err
			}
		}
	}
	if length < 0 {
		return nil, fmt.Errorf("Content-Length がありません")
	}
	body := make([]byte, length)
	_, err := io.ReadFull(r, body)
	return body, err
}

type server struct {
	out      io.Writer
	docs     map[string]*document
	shutdown bool
}

type document struct {
	uri         string
	text        string
	lines       []string
	analysis    *compiler.Analysis
	completions []compiler.Completion
}

func (s *server) send(m message) {
	m.JSONRPC = "2.0"
	b, err := json.Marshal(m)
	if err != nil {
		return
	}
	fmt.Fprintf(s.out, "Content-Length: %d\r\n\r\n%s", len(b), b)
}

func (s *server) reply(id *json.RawMessage, result any) {
	if id == nil {
		return
	}
	if result == nil {
		result = json.RawMessage("null")
	}
	s.send(message{ID: id, Result: result})
}

func (s *server) notify(method string, params any) {
	b, _ := json.Marshal(params)
	s.send(message{Method: method, Params: b})
}

// --- 位置: する は1から数えた文字(コードポイント)、LSP は0から数えた UTF-16 ---

type position struct {
	Line      int `json:"line"`
	Character int `json:"character"`
}

type rng struct {
	Start position `json:"start"`
	End   position `json:"end"`
}

type location struct {
	URI   string `json:"uri"`
	Range rng    `json:"range"`
}

func lineText(lines []string, line int) string {
	if line < 1 || line > len(lines) {
		return ""
	}
	return lines[line-1]
}

// toUTF16 は line 行目の col 文字目(1から)を LSP の位置にする
func toUTF16(lines []string, line, col int) position {
	rs := []rune(lineText(lines, line))
	if col-1 > len(rs) {
		col = len(rs) + 1
	}
	if col < 1 {
		col = 1
	}
	return position{line - 1, len(utf16.Encode(rs[:col-1]))}
}

// fromUTF16 は LSP の位置を (行, 文字目) にする(どちらも1から)
func fromUTF16(lines []string, p position) (int, int) {
	rs := []rune(lineText(lines, p.Line+1))
	units := 0
	for i, r := range rs {
		if units >= p.Character {
			return p.Line + 1, i + 1
		}
		units += len(utf16.Encode([]rune{r}))
	}
	return p.Line + 1, len(rs) + 1
}

func isBreak(r rune) bool {
	return r == ' ' || r == '　' || r == '\t' || r == '、' || r == '。'
}

// wordRange は col 文字目から、次の単語の始まり(か空白・句読点)までの範囲
func wordRange(a *compiler.Analysis, lines []string, line, col int) rng {
	rs := []rune(lineText(lines, line))
	end := a.TokenEnd(line, col)
	if end > len(rs)+1 {
		end = len(rs) + 1
	}
	for end > col+1 && isBreak(rs[end-2]) {
		end--
	}
	if end <= col {
		end = col + 1
	}
	return rng{toUTF16(lines, line, col), toUTF16(lines, line, end)}
}

// --- URI とパス ---

func uriToPath(uri string) string {
	u, err := url.Parse(uri)
	if err != nil || u.Scheme != "file" {
		return ""
	}
	p := u.Path
	if runtime.GOOS == "windows" {
		p = strings.TrimPrefix(p, "/")
	}
	return filepath.FromSlash(p)
}

func pathToURI(path string) string {
	p := filepath.ToSlash(path)
	if !strings.HasPrefix(p, "/") {
		p = "/" + p
	}
	return (&url.URL{Scheme: "file", Path: p}).String()
}

// --- 解析と間違いの表示 ---

func (s *server) update(uri, text string) {
	d := &document{uri: uri, text: text, lines: compiler.SplitLines(text)}
	base := "."
	if p := uriToPath(uri); p != "" {
		base = filepath.Dir(p)
	}
	d.analysis = analyze(text, base)
	// 書いている途中で構文が崩れているときは、前に分かった名前で補完する
	d.completions = d.analysis.Completions
	if old := s.docs[uri]; old != nil && len(d.analysis.Defs) == 0 && d.analysis.Error != nil {
		d.completions = old.completions
	}
	s.docs[uri] = d
	diags := []map[string]any{}
	errs := d.analysis.Errors
	if len(errs) == 0 && d.analysis.Error != nil {
		errs = []*compiler.SuruError{d.analysis.Error}
	}
	for _, e := range errs {
		var r rng
		if e.Line.Line == 0 {
			r = rng{position{0, 0}, toUTF16(d.lines, 1, len([]rune(lineText(d.lines, 1)))+1)}
		} else if e.Line.Col == 0 {
			text := lineText(d.lines, e.Line.Line)
			indent := len([]rune(text)) - len([]rune(strings.TrimLeft(text, " 　\t")))
			r = rng{toUTF16(d.lines, e.Line.Line, indent+1), toUTF16(d.lines, e.Line.Line, len([]rune(text))+1)}
		} else {
			r = wordRange(d.analysis, d.lines, e.Line.Line, e.Line.Col)
		}
		diags = append(diags, map[string]any{"range": r, "severity": 1, "source": "する", "message": e.Message})
	}
	s.notify("textDocument/publishDiagnostics", map[string]any{"uri": uri, "diagnostics": diags})
}

// analyze はコンパイラの中で思わぬ panic が起きても、サーバーを止めない
func analyze(text, base string) (a *compiler.Analysis) {
	defer func() {
		if r := recover(); r != nil {
			a = &compiler.Analysis{Error: &compiler.SuruError{Message: fmt.Sprintf("解析の途中で問題が起きました: %v", r)}}
		}
	}()
	return compiler.Analyze(text, base)
}

// --- 要求 ---

type textDocumentPosition struct {
	TextDocument struct {
		URI string `json:"uri"`
	} `json:"textDocument"`
	Position position `json:"position"`
}

func (s *server) hover(p textDocumentPosition) any {
	d := s.docs[p.TextDocument.URI]
	if d == nil {
		return nil
	}
	line, col := fromUTF16(d.lines, p.Position)
	t, ok := d.analysis.TypeAt(line, col)
	if !ok {
		return nil
	}
	label := "使ったところの型"
	if t.Def {
		label = "定義の型"
	}
	return map[string]any{
		"contents": map[string]any{
			"kind":  "markdown",
			"value": "```suru\n" + t.Name + " は " + t.Type + "\n```\n" + label,
		},
		"range": rng{toUTF16(d.lines, t.Pos.Line, t.Pos.Col), toUTF16(d.lines, t.Pos.Line, t.End)},
	}
}

func (s *server) definition(p textDocumentPosition) any {
	d := s.docs[p.TextDocument.URI]
	if d == nil {
		return nil
	}
	line, col := fromUTF16(d.lines, p.Position)
	t, ok := d.analysis.TypeAt(line, col)
	if !ok {
		return nil
	}
	defs := d.analysis.DefinitionsOf(t.Name)
	locs := []location{}
	other := map[string][]string{}
	for _, def := range defs {
		uri, lines := d.uri, d.lines
		if def.File != "" {
			uri = pathToURI(def.File)
			if _, ok := other[def.File]; !ok {
				b, _ := os.ReadFile(def.File)
				other[def.File] = compiler.SplitLines(string(b))
			}
			lines = other[def.File]
		}
		start := toUTF16(lines, def.Pos.Line, max(def.Pos.Col, 1))
		name := def.Name
		if i := strings.LastIndex(name, compiler.ModuleSep); i >= 0 {
			name = name[i+len(compiler.ModuleSep):]
		}
		end := toUTF16(lines, def.Pos.Line, max(def.Pos.Col, 1)+len([]rune(name)))
		locs = append(locs, location{uri, rng{start, end}})
	}
	if len(locs) == 0 {
		return nil
	}
	return locs
}

func (s *server) symbols(uri string) any {
	d := s.docs[uri]
	if d == nil {
		return []any{}
	}
	out := []map[string]any{}
	seen := map[string]bool{}
	for _, t := range d.analysis.Types {
		key := t.Name + "@" + strconv.Itoa(t.Pos.Line)
		if !t.Def || seen[key] {
			continue
		}
		seen[key] = true
		kind := 13 // Variable
		if strings.HasSuffix(t.Type, "返すこと）") {
			kind = 12 // Function
		}
		r := rng{toUTF16(d.lines, t.Pos.Line, t.Pos.Col), toUTF16(d.lines, t.Pos.Line, t.End)}
		out = append(out, map[string]any{
			"name": t.Name, "detail": t.Type, "kind": kind,
			"location": location{uri, r},
		})
	}
	return out
}

func (s *server) handle(m message) {
	switch m.Method {
	case "initialize":
		s.reply(m.ID, map[string]any{
			"capabilities": map[string]any{
				"textDocumentSync":       map[string]any{"openClose": true, "change": 1},
				"hoverProvider":          true,
				"definitionProvider":     true,
				"documentSymbolProvider": true,
				"completionProvider":     map[string]any{"triggerCharacters": []string{"の"}},
				"renameProvider":         map[string]any{"prepareProvider": true},
				"semanticTokensProvider": map[string]any{
					"legend": map[string]any{"tokenTypes": semanticTypes, "tokenModifiers": []string{}},
					"full":   true,
				},
			},
			"serverInfo": map[string]any{"name": "suru-ls", "version": version},
		})
	case "initialized", "$/cancelRequest", "$/setTrace", "workspace/didChangeConfiguration":
	case "shutdown":
		s.shutdown = true
		s.reply(m.ID, nil)
	case "exit":
		if s.shutdown {
			os.Exit(0)
		}
		os.Exit(1)
	case "textDocument/didOpen":
		var p struct {
			TextDocument struct {
				URI  string `json:"uri"`
				Text string `json:"text"`
			} `json:"textDocument"`
		}
		if json.Unmarshal(m.Params, &p) == nil {
			s.update(p.TextDocument.URI, p.TextDocument.Text)
		}
	case "textDocument/didChange":
		var p struct {
			TextDocument struct {
				URI string `json:"uri"`
			} `json:"textDocument"`
			ContentChanges []struct {
				Text string `json:"text"`
			} `json:"contentChanges"`
		}
		if json.Unmarshal(m.Params, &p) == nil && len(p.ContentChanges) > 0 {
			s.update(p.TextDocument.URI, p.ContentChanges[len(p.ContentChanges)-1].Text)
		}
	case "textDocument/didSave":
		// 読み込んでいるファイルが変わったかもしれないので、開いているものを全部調べ直す
		for uri, d := range s.docs {
			s.update(uri, d.text)
		}
	case "textDocument/didClose":
		var p struct {
			TextDocument struct {
				URI string `json:"uri"`
			} `json:"textDocument"`
		}
		if json.Unmarshal(m.Params, &p) == nil {
			delete(s.docs, p.TextDocument.URI)
			s.notify("textDocument/publishDiagnostics", map[string]any{"uri": p.TextDocument.URI, "diagnostics": []any{}})
		}
	case "textDocument/hover", "textDocument/definition":
		var p textDocumentPosition
		if err := json.Unmarshal(m.Params, &p); err != nil {
			s.send(message{ID: m.ID, Error: &rpcError{-32602, err.Error()}})
			return
		}
		if m.Method == "textDocument/hover" {
			s.reply(m.ID, s.hover(p))
		} else {
			s.reply(m.ID, s.definition(p))
		}
	case "textDocument/completion":
		var p textDocumentPosition
		_ = json.Unmarshal(m.Params, &p)
		s.reply(m.ID, s.complete(p))
	case "textDocument/semanticTokens/full":
		var p struct {
			TextDocument struct {
				URI string `json:"uri"`
			} `json:"textDocument"`
		}
		_ = json.Unmarshal(m.Params, &p)
		s.reply(m.ID, s.semanticTokens(p.TextDocument.URI))
	case "textDocument/prepareRename":
		var p textDocumentPosition
		_ = json.Unmarshal(m.Params, &p)
		r, err := s.prepareRename(p)
		if err != "" {
			s.send(message{ID: m.ID, Error: &rpcError{-32803, err}})
			return
		}
		s.reply(m.ID, r)
	case "textDocument/rename":
		var p struct {
			textDocumentPosition
			NewName string `json:"newName"`
		}
		_ = json.Unmarshal(m.Params, &p)
		r, err := s.rename(p.textDocumentPosition, p.NewName)
		if err != "" {
			s.send(message{ID: m.ID, Error: &rpcError{-32803, err}})
			return
		}
		s.reply(m.ID, r)
	case "textDocument/documentSymbol":
		var p struct {
			TextDocument struct {
				URI string `json:"uri"`
			} `json:"textDocument"`
		}
		_ = json.Unmarshal(m.Params, &p)
		s.reply(m.ID, s.symbols(p.TextDocument.URI))
	default:
		if m.ID != nil {
			s.send(message{ID: m.ID, Error: &rpcError{-32601, "対応していない要求です: " + m.Method}})
		}
	}
}

func main() {
	if len(os.Args) >= 2 && (os.Args[1] == "--version" || os.Args[1] == "--版") {
		fmt.Println("suru-ls " + version)
		return
	}
	setupLib()
	s := &server{out: bufio.NewWriter(os.Stdout), docs: map[string]*document{}}
	r := bufio.NewReader(os.Stdin)
	for {
		body, err := readMessage(r)
		if err != nil {
			if err == io.EOF {
				os.Exit(0)
			}
			fmt.Fprintln(os.Stderr, "suru-ls:", err)
			os.Exit(1)
		}
		var m message
		if err := json.Unmarshal(body, &m); err != nil {
			fmt.Fprintln(os.Stderr, "suru-ls: 読めないメッセージ:", err)
			continue
		}
		s.handle(m)
		s.out.(*bufio.Writer).Flush()
	}
}

// setupLib は標準ライブラリの場所を決める。SURU_LIB があればそこ、なければ同梱の lib/ を
// キャッシュのフォルダに書き出して使う(「定義へ移動」でファイルを開けるように)
func setupLib() {
	sub, err := fs.Sub(suru.Lib, "lib")
	if err == nil {
		compiler.LibFS = sub
	}
	if d := os.Getenv("SURU_LIB"); d != "" {
		compiler.LibDir = d
		return
	}
	if sub == nil {
		return
	}
	h := sha256.New()
	files := map[string][]byte{}
	_ = fs.WalkDir(sub, ".", func(p string, e fs.DirEntry, err error) error {
		if err != nil || e.IsDir() {
			return nil
		}
		b, err := fs.ReadFile(sub, p)
		if err == nil {
			files[p] = b
			h.Write([]byte(p))
			h.Write(b)
		}
		return nil
	})
	base, err := os.UserCacheDir()
	if err != nil {
		return
	}
	dir := filepath.Join(base, "suru", "lib-"+hex.EncodeToString(h.Sum(nil))[:16])
	for p, b := range files {
		target := filepath.Join(dir, filepath.FromSlash(p))
		if old, err := os.ReadFile(target); err == nil && string(old) == string(b) {
			continue
		}
		if os.MkdirAll(filepath.Dir(target), 0o755) != nil || os.WriteFile(target, b, 0o644) != nil {
			return // 書けなければ同梱のものをそのまま使う
		}
	}
	compiler.LibDir = dir
}

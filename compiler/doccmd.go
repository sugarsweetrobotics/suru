package compiler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// DocUsage は「--文書」の使い方
const DocUsage = "使い方: --文書 [--json] [--出力 フォルダ] ファイルかフォルダ …"

// DocCommand は「suruc --文書 …」(#209): ファイル(フォルダなら中の .suru)の公開の名前の API ドキュメントを、
// Markdown(--json なら1ファイル1行の JSON)で出す。--出力 があれば、ファイルごとに「名前.md」(「名前.json」)を書く
func DocCommand(args []string, stdout, stderr io.Writer) int {
	asJSON := false
	out := ""
	var paths []string
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--json" || a == "--JSON":
			asJSON = true
		case a == "--出力" || a == "--out" || a == "-o":
			if i+1 >= len(args) {
				fmt.Fprintln(stderr, DocUsage)
				return 2
			}
			out = args[i+1]
			i++
		case strings.HasPrefix(a, "--"):
			fmt.Fprintln(stderr, DocUsage)
			return 2
		default:
			paths = append(paths, a)
		}
	}
	files, err := docSourceFiles(paths)
	if err != nil || len(files) == 0 {
		if err != nil {
			fmt.Fprintln(stderr, err)
		}
		fmt.Fprintln(stderr, DocUsage)
		return 2
	}
	if out != "" {
		if err := os.MkdirAll(out, 0o755); err != nil {
			fmt.Fprintln(stderr, err)
			return 1
		}
	}
	status := 0
	first := true
	for _, f := range files {
		d, err := DocumentFile(f)
		if err != nil {
			if se, ok := err.(*SuruError); ok {
				if asJSON {
					fmt.Fprintln(stderr, ErrorJSON(se, "構文", f))
				} else {
					src, _ := os.ReadFile(f)
					fmt.Fprintln(stderr, f+": "+FormatError(se, string(src), true))
				}
			} else {
				fmt.Fprintln(stderr, err)
			}
			status = 1
			continue
		}
		text := d.Markdown()
		ext := ".md"
		if asJSON {
			text, ext = d.JSON(), ".json"
		}
		if out != "" {
			if err := os.WriteFile(filepath.Join(out, d.Module+ext), []byte(text), 0o644); err != nil {
				fmt.Fprintln(stderr, err)
				status = 1
			}
			continue
		}
		if !first && !asJSON {
			fmt.Fprintln(stdout)
		}
		first = false
		fmt.Fprint(stdout, text)
	}
	return status
}

// JSON は API ドキュメントを1行の JSON にする(終わりに改行)
func (d *DocFile) JSON() string {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	enc.Encode(d)
	return b.String()
}

// docSourceFiles はファイルとフォルダ(中の .suru。下のフォルダは見ない)から、文書にするファイルを並べる
func docSourceFiles(paths []string) ([]string, error) {
	var out []string
	for _, p := range paths {
		st, err := os.Stat(p)
		if err != nil {
			return nil, fmt.Errorf("「%s」が見つかりません", p)
		}
		if !st.IsDir() {
			out = append(out, p)
			continue
		}
		ms, _ := filepath.Glob(filepath.Join(p, "*.suru"))
		sort.Strings(ms)
		out = append(out, ms...)
	}
	return out, nil
}

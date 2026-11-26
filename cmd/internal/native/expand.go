// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package native

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/suru-lang/suru/compiler"
)

// 準クォート(#192)の展開の関数を、小さなバイナリにして動かす。Rust の手続きマクロと同じく、展開の関数を
// 先にコンパイルし(同じものは取っておく)、中身を渡して動かし、出てきた する のソースを使う

// expanderSource は展開の関数 fname(ファイル stem の中)を動かす入口。最後の引数のファイルの中身を渡し、
// 「成功:」か「失敗:」に続けて結果を出す
func expanderSource(stem, fname string) string {
	return "「ファイル」 を 読み込む\n" +
		"「環境」 を 読み込む\n" +
		"「" + stem + "」 を 読み込む\n" +
		"\n" +
		"展開実行する は 数 を 返す 入出力動作\n" +
		"展開実行する とは 以下の手順です\n" +
		"  引数群 とは 環境内の引数取得した 結果\n" +
		"  本文 とは 引数群 の 最後 を ファイル内の読込した 結果\n" +
		"  もし （本文 を " + stem + compiler.ModuleSep + fname + "） が\n" +
		"    s の 成功 ならば 「成功:」 + s を 続表示する\n" +
		"    e の 失敗 ならば 「失敗:」 + e を 続表示する\n" +
		"以上です\n" +
		"\n" +
		"展開実行する\n"
}

// deriverSource は導出の関数 fname(ファイル stem の中)に型の記述 desc(する の式のソース)を渡して動かす入口
func deriverSource(stem, fname, desc string) string {
	return "「導出」 を 読み込んで 使う\n" +
		"「" + stem + "」 を 読み込む\n" +
		"\n" +
		"導出実行する は 数 を 返す 入出力動作\n" +
		"導出実行する とは 以下の手順です\n" +
		"  もし （" + desc + " を " + stem + compiler.ModuleSep + fname + "） が\n" +
		"    s の 成功 ならば 「成功:」 + s を 続表示する\n" +
		"    e の 失敗 ならば 「失敗:」 + e を 続表示する\n" +
		"以上です\n" +
		"\n" +
		"導出実行する\n"
}

// InstallExpander は compiler が準クォートの展開と導出をできるようにする(suruc・kumu・suru-ls が呼ぶ)
func InstallExpander() {
	compiler.Expander = runExpander
	compiler.Deriver = runDeriver
}

func runExpander(mod *compiler.Module, fname, body string) (bool, string, error) {
	exe, err := expanderBinary(mod, expanderSource(mod.Name, fname))
	if err != nil {
		return false, "", err
	}
	f, err := os.CreateTemp("", "suru-quasi-*.txt")
	if err != nil {
		return false, "", err
	}
	defer os.Remove(f.Name())
	if _, err := f.WriteString(body); err != nil {
		f.Close()
		return false, "", err
	}
	f.Close()
	return runDriver(exe, f.Name())
}

func runDeriver(mod *compiler.Module, fname, desc string) (bool, string, error) {
	exe, err := expanderBinary(mod, deriverSource(mod.Name, fname, desc))
	if err != nil {
		return false, "", err
	}
	return runDriver(exe)
}

// runDriver は展開・導出の入口のバイナリを動かし、「成功:」「失敗:」に続く結果を読む
func runDriver(exe string, args ...string) (bool, string, error) {
	cmd := exec.Command(exe, args...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return false, "", fmt.Errorf("%s", msg)
	}
	out := stdout.String()
	switch {
	case strings.HasPrefix(out, "成功:"):
		return true, strings.TrimPrefix(out, "成功:"), nil
	case strings.HasPrefix(out, "失敗:"):
		return false, strings.TrimPrefix(out, "失敗:"), nil
	}
	return false, "", fmt.Errorf("展開の関数の出力が読めません: %q", out)
}

// expanderBinary は展開・導出の関数を動かす入口 src のバイナリの道。同じ IR なら前に作ったものを使う
func expanderBinary(mod *compiler.Module, src string) (string, error) {
	// 展開は手元で動かすものなので、SURU_TARGET で別の OS 向けにしていても手元向けに作る
	if t, ok := os.LookupEnv("SURU_TARGET"); ok {
		os.Unsetenv("SURU_TARGET")
		defer os.Setenv("SURU_TARGET", t)
	}
	base := filepath.Dir(mod.Path)
	ir, serr := compiler.CompileSource(src, base, filepath.Join(base, "\x00展開の入口.suru"), true)
	if serr != nil {
		return "", fmt.Errorf("展開の関数をコンパイルできません: %s", serr.Message)
	}
	cc := FindCC()
	if cc == "" {
		return "", fmt.Errorf("展開の関数を動かすには clang が必要です")
	}
	h := sha256.Sum256([]byte(cc + "\x00" + ir))
	dir := CacheDir()
	name := filepath.Join(dir, "展開-"+hex.EncodeToString(h[:])[:16])
	exe := ExePath(name)
	if _, err := os.Stat(exe); err == nil {
		return exe, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.%d", name, os.Getpid())
	if err := os.WriteFile(tmp+".ll", []byte(ir), 0o644); err != nil {
		return "", err
	}
	defer os.Remove(tmp + ".ll")
	if err := Build(tmp+".ll", tmp, "-O1"); err != nil {
		return "", err
	}
	return exe, os.Rename(ExePath(tmp), exe)
}

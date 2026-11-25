// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/suru-lang/suru/cmd/internal/native"
)

func TestParseConfigCSources(t *testing.T) {
	p, err := ParseConfig("名前 とは 「包み」\nCソース とは 「c/包み.c」 と 「c/他.c」\nC引数 とは 「-I${ROS}/include」\nリンク引数 とは 「-L/x -lrcl」\n", "/x")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(p.CSources, ",") != "c/包み.c,c/他.c" || p.CFlags[0] != "-I${ROS}/include" || p.LinkFlags[0] != "-L/x -lrcl" {
		t.Fatalf("読み違い: %+v", p)
	}
	for _, src := range []string{"名前 とは 「a」\nCソース とは 「../外.c」\n", "名前 とは 「a」\nCソース とは 「/abs.c」\n"} {
		if _, err := ParseConfig(src, "/x"); err == nil || !strings.Contains(err.Error(), "プロジェクトのフォルダの中のファイル") {
			t.Errorf("%q: %v", src, err)
		}
	}
}

func TestExpandFlags(t *testing.T) {
	t.Setenv("SURU_TEST_PREFIX", "/opt/ros/jazzy")
	got, err := expandFlags([]string{"-L${SURU_TEST_PREFIX}/lib -lrcl", "-Wl,-rpath,${SURU_TEST_PREFIX}/lib"}, "リンク引数", "包み")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Join(got, " ") != "-L/opt/ros/jazzy/lib -lrcl -Wl,-rpath,/opt/ros/jazzy/lib" {
		t.Fatalf("%q", got)
	}
	os.Unsetenv("SURU_TEST_NO_SUCH")
	if _, err := expandFlags([]string{"-I${SURU_TEST_NO_SUCH}"}, "C引数", "包み"); err == nil || !strings.Contains(err.Error(), "「包み」のC引数「-I${SURU_TEST_NO_SUCH}」に使う環境変数「SURU_TEST_NO_SUCH」がありません") {
		t.Fatalf("%v", err)
	}
}

// プロジェクトと手元の依存の両方が C のソースを持ち、外部の関数を読み込みなしで呼ぶ
func TestBuildWithCSources(t *testing.T) {
	if native.FindCC() == "" {
		t.Skip("clang がない")
	}
	t.Setenv("KUMU_HOME", t.TempDir())
	t.Setenv("SURU_TEST_SCALE", "3")
	dir := t.TempDir()
	lib := filepath.Join(dir, "部品")
	app := filepath.Join(dir, "本")
	write := func(path, s string) {
		t.Helper()
		os.MkdirAll(filepath.Dir(path), 0o755)
		if err := os.WriteFile(path, []byte(s), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(lib, "組.suru"), "名前 とは 「部品」\nCソース とは 「c/部品.c」\nC引数 とは 「-DSCALE=${SURU_TEST_SCALE}」\n")
	write(filepath.Join(lib, "c", "部品.c"), "#include \"部品.h\"\nlong long buhin_scale(long long x) { return x * SCALE + OFFSET; }\n")
	write(filepath.Join(lib, "c", "部品.h"), "#define OFFSET 1\n")
	write(filepath.Join(lib, "部品.suru"), "数 を 拡大する は 数\nx を 拡大する とは 外部の「buhin_scale」\n")
	write(filepath.Join(app, "組.suru"), "名前 とは 「本」\n依存 とは 「../部品」\nCソース とは 「包み.c」\nリンク引数 とは 「-lm」\n")
	write(filepath.Join(app, "包み.c"), "long long hon_twice(long long x) { return 2 * x; }\n")
	write(filepath.Join(app, "本体.suru"), "「部品」 を 読み込む\n数 を 二倍する は 数\nx を 二倍する とは 外部の「hon_twice」\n（5 を 部品内の拡大する） を 二倍する\n")
	k, out, errb := newKumu(app)
	if rc := k.run([]string{"実行"}); rc != 0 {
		t.Fatalf("実行 が失敗: %s", errb)
	}
	if out.String() != "32\n" {
		t.Fatalf("出力が違う: %q(%s)", out, errb)
	}
	// ヘッダーを変えると作り直す
	write(filepath.Join(lib, "c", "部品.h"), "#define OFFSET 2\n")
	k, out, errb = newKumu(app)
	if rc := k.run([]string{"実行"}); rc != 0 || out.String() != "34\n" {
		t.Fatalf("ヘッダーを変えても作り直さない: %q %s", out, errb)
	}
	// C のコンパイルの失敗
	write(filepath.Join(app, "包み.c"), "this is not C\n")
	k, _, errb = newKumu(app)
	if rc := k.run([]string{"作る"}); rc != 1 || !strings.Contains(errb.String(), "「本」のCソース「包み.c」のコンパイルに失敗しました") {
		t.Fatalf("失敗を知らせない: %s", errb)
	}
}

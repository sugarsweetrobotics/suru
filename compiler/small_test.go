// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"strings"
	"testing"
)

func compileSmall(t *testing.T, src string) (string, *SuruError) {
	t.Helper()
	return CompileSmall(src, t.TempDir(), "試し.suru", SmallTarget{Name: "Arduino Uno"})
}

func TestSmallBlink(t *testing.T) {
	ir, err := compileSmall(t, "「マイコン」 を 読み込んで 使う\n\n点滅する とは 手順\n  内蔵灯 を 反転出力する\n  500 を ミリ秒待機する\n  点滅する\n\n内蔵灯 を 出力設定する\n点滅する\n")
	if err != nil {
		t.Fatal(FormatError(err, "", false))
	}
	for _, s := range []string{"declare void @mcu_pin_toggle(i32) addrspace(1)", "call addrspace(1) void @mcu_delay_ms(i32 500)", "br label %body", "define void @suru_main() addrspace(1)"} {
		if !strings.Contains(ir, s) {
			t.Errorf("IR に「%s」がない:\n%s", s, ir)
		}
	}
	if strings.Contains(ir, "@rt_") {
		t.Errorf("普通の実行時ライブラリを使っている:\n%s", ir)
	}
}

func TestSmallStrings(t *testing.T) {
	ir, err := compileSmall(t, "n とは 3\n「n = 」 + （n を 文字列化する） を 表示する\n")
	if err != nil {
		t.Fatal(FormatError(err, "", false))
	}
	if !strings.Contains(ir, "addrspace(1) constant") || !strings.Contains(ir, "@suru_put_int") || !strings.Contains(ir, "@suru_put_str") {
		t.Errorf("文字列をフラッシュに置いて、つないで表示していない:\n%s", ir)
	}
}

func TestSmallUnsupported(t *testing.T) {
	cases := []struct{ src, want string }{
		{"1 と 2 を 表示する\n", "リスト"},
		{"1.5 を 表示する\n", "小数"},
		{"（x を 受け取って x * 2 を 返すこと） を 3 に 適用する\n", "「適用する」は使えません"},
		{"g とは （x を 受け取って x * 2 を 返すこと）\ng を 表示する\n", "無名関数"},
		{"（（「a」 を 文字列化する） の 長さ） を 表示する\n", "マイコン向けでは"},
		{"2147483648 を 表示する\n", "2147483647 まで"},
		{"「a」 を 入力する\n", "「入力する」は使えません"},
	}
	for _, c := range cases {
		_, err := compileSmall(t, c.src)
		if err == nil || !strings.Contains(err.Message, c.want) {
			msg := "通ってしまう"
			if err != nil {
				msg = err.Message
			}
			t.Errorf("%q: %s(「%s」のはず)", c.src, msg, c.want)
		}
	}
}

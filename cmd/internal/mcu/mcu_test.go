// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package mcu

import (
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"testing"
	"time"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/compiler"
)

func TestMain(m *testing.M) {
	sub, err := fs.Sub(suru.Lib, "lib")
	if err != nil {
		panic(err)
	}
	compiler.LibFS = sub
	os.Exit(m.Run())
}

func TestFlashArgs(t *testing.T) {
	b, _ := Lookup("arduino-uno")
	got := strings.Join(FlashArgs("a.hex", "/dev/ttyACM0", b), " ")
	want := "-p m328p -c arduino -P /dev/ttyACM0 -b 115200 -D -U flash:w:a.hex:i"
	if got != want {
		t.Errorf("avrdude の引数: %s(%s のはず)", got, want)
	}
	if p, err := ChoosePort("/dev/x"); err != nil || p != "/dev/x" {
		t.Errorf("指定したポートを使わない: %s %v", p, err)
	}
	if _, err := Lookup("z80"); err == nil {
		t.Errorf("知らない基板が見つかる")
	}
}

// simavr で動かし、シリアルの出力を集める(simavr が無ければ飛ばす)
func simulate(t *testing.T, elf string, d time.Duration) string {
	sim, err := exec.LookPath("simavr")
	if err != nil {
		t.Skip("simavr がありません")
	}
	cmd := exec.Command(sim, "-m", "atmega328p", "-f", "16000000", elf)
	var out strings.Builder
	cmd.Stdout, cmd.Stderr = &out, &out
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	time.Sleep(d)
	cmd.Process.Signal(syscall.SIGINT)
	cmd.Wait()
	// simavr は行ごとに色を付け、CR を . にする
	s := regexp.MustCompile("\x1b\\[[0-9;]*m").ReplaceAllString(out.String(), "")
	var lines []string
	for _, l := range strings.Split(s, "\n") {
		if strings.HasPrefix(l, "Loaded ") || strings.HasPrefix(l, "signal caught") || l == "" {
			continue
		}
		lines = append(lines, strings.TrimSuffix(strings.TrimSuffix(l, "."), "."))
	}
	return strings.Join(lines, "\n")
}

const program = `「マイコン」 を 読み込んで 使う

数 を フィボナッチにする は 数
0 を フィボナッチにする とは 0
1 を フィボナッチにする とは 1
n を フィボナッチにする とは （n - 1 を フィボナッチにする） + （n - 2 を フィボナッチにする）

n を 判定する とは もし n % 2 == 0 ならば 「偶数」 そうでなければ 「奇数」

n を 三倍加算する とは n を 三倍して 調整する
ただし x を 三倍する とは x * 3
ただし x を 調整する とは x + n

n から 計数する とは
  もし n > 3 ならば 「おわり」 を 表示する
  そうでなければ n から 一段計数する

n から 一段計数する とは 手順
  「n = 」 + （n を 文字列化する） を 表示する
  n + 1 から 計数する

確認する とは 手順
  t とは 経過ミリ秒取得した 結果
  100 を ミリ秒待機する
  u とは 経過ミリ秒取得した 結果
  「待った: 」 + （u - t >= 100 を 文字列化する） を 表示する
  内蔵灯 を 出力設定する
  内蔵灯 を 高出力する
  「13番: 」 + （内蔵灯 を 読取した 結果 を 文字列化する） を 表示する

20 を フィボナッチにする
7 を 判定して 表示する
5 を 三倍加算する
3 > 2 かつ 1 == 1
-7 / 2
-7 % 2
2 ^ 10
1 から 計数する
確認する
`

const want = `6765
奇数
20
真
-4
1
1024
n = 1
n = 2
n = 3
おわり
待った: 真
13番: 真`

func TestBuildAndSimulate(t *testing.T) {
	tools, err := FindTools(false)
	if err != nil {
		t.Skip(err)
	}
	b, _ := Lookup("arduino-uno")
	dir := t.TempDir()
	src := filepath.Join(dir, "試し.suru")
	os.WriteFile(src, []byte(program), 0o644)
	ir, err := Compile(program, src, b)
	if err != nil {
		t.Fatal(err)
	}
	r, err := Build(ir, filepath.Join(dir, "試し"), b, tools)
	if err != nil {
		t.Fatal(err)
	}
	if r.RAMBytes > 64 {
		t.Errorf("最初から使う RAM が多すぎる(文字列がフラッシュにない?): %d", r.RAMBytes)
	}
	got := simulate(t, r.ELF, 3*time.Second)
	if got != want {
		t.Errorf("シリアルの出力が違います:\n%s\n--- のはず:\n%s", got, want)
	}
}

// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package mcu はマイコン(Arduino など)向けのビルドと書き込み(kumu と suruc で使う)。
//
// する → 小さい LLVM IR(compiler.CompileSmall)→ AVR に対応した clang でオブジェクト →
// avr-gcc で実行時ライブラリ(runtime/avr)とつなぐ → avr-objcopy で .hex → avrdude で書き込む。
package mcu

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"

	suru "github.com/suru-lang/suru"
	"github.com/suru-lang/suru/cmd/internal/native"
	"github.com/suru-lang/suru/compiler"
)

// Board はマイコンの基板
type Board struct {
	Name       string // 組.suru の 対象 に書く名前
	Display    string // 表示用
	MCU        string // avr-gcc・clang の -mmcu
	Part       string // avrdude の -p
	Programmer string // avrdude の -c
	Baud       int    // ブートローダーの速さ
	FCPU       int    // クロック(Hz)
	Flash      int    // プログラムに使えるフラッシュ(ブートローダーの分を除く、バイト)
	RAM        int    // RAM(バイト)
}

// Boards は使える基板(名前 → 基板)
var Boards = map[string]Board{
	"arduino-uno":      {"arduino-uno", "Arduino Uno", "atmega328p", "m328p", "arduino", 115200, 16000000, 32256, 2048},
	"arduino-nano":     {"arduino-nano", "Arduino Nano", "atmega328p", "m328p", "arduino", 115200, 16000000, 30720, 2048},
	"arduino-nano-old": {"arduino-nano-old", "Arduino Nano(古いブートローダー)", "atmega328p", "m328p", "arduino", 57600, 16000000, 30720, 2048},
}

// Names は基板の名前の一覧(並べたもの)
func Names() []string {
	var out []string
	for k := range Boards {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Lookup は名前から基板を探す
func Lookup(name string) (Board, error) {
	b, ok := Boards[name]
	if !ok {
		return Board{}, fmt.Errorf("「%s」というマイコンの対象はありません(使えるのは %s)", name, strings.Join(Names(), "・"))
	}
	return b, nil
}

// --- 道具を探す ---

// guide は道具が無いときの入れ方
func guide() string {
	switch runtime.GOOS {
	case "darwin":
		return "入れ方(macOS、Homebrew): brew install llvm avrdude && brew tap osx-cross/avr && brew install avr-gcc"
	case "linux":
		return "入れ方(Ubuntu・Debian): sudo apt install clang gcc-avr avr-libc avrdude"
	}
	return "clang(AVR 対応)・avr-gcc・avrdude を入れてください"
}

func homeGlob(pattern string) []string {
	home, err := os.UserHomeDir()
	if err != nil {
		return nil
	}
	m, _ := filepath.Glob(filepath.Join(home, pattern))
	sort.Sort(sort.Reverse(sort.StringSlice(m)))
	return m
}

// arduinoTools は Arduino IDE が入れた道具のフォルダ(新しいものから)
func arduinoTools(tool string) []string {
	var dirs []string
	for _, base := range []string{"Library/Arduino15", ".arduino15", "AppData/Local/Arduino15"} {
		dirs = append(dirs, homeGlob(filepath.Join(base, "packages/arduino/tools", tool, "*", "bin"))...)
	}
	return dirs
}

func findTool(env, name string, extraDirs []string) string {
	if v := os.Getenv(env); v != "" {
		return v
	}
	if p, err := exec.LookPath(name); err == nil {
		return p
	}
	for _, d := range extraDirs {
		p := filepath.Join(d, name)
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p
		}
	}
	return ""
}

// supportsAVR は clang が AVR の機械語を作れるか
func supportsAVR(clang string) bool {
	out, err := exec.Command(clang, "-print-targets").CombinedOutput()
	if err != nil {
		return false
	}
	return strings.Contains(string(out), "avr")
}

// FindClang は AVR に対応した clang を探す($SURU_AVR_CLANG、PATH の clang、Homebrew の llvm、Linux の llvm-*)
func FindClang() string {
	if v := os.Getenv("SURU_AVR_CLANG"); v != "" {
		return v
	}
	cands := []string{}
	if p, err := exec.LookPath("clang"); err == nil {
		cands = append(cands, p)
	}
	cands = append(cands, "/opt/homebrew/opt/llvm/bin/clang", "/usr/local/opt/llvm/bin/clang")
	cands = append(cands, homeGlob(".homebrew/opt/llvm/bin/clang")...)
	ll, _ := filepath.Glob("/usr/lib/llvm-*/bin/clang")
	sort.Sort(sort.Reverse(sort.StringSlice(ll)))
	cands = append(cands, ll...)
	for _, c := range cands {
		if _, err := os.Stat(c); err == nil && supportsAVR(c) {
			return c
		}
	}
	return ""
}

// Tools はマイコン向けのビルドと書き込みに使う道具
type Tools struct {
	Clang, GCC, Objcopy, Size, Avrdude string
}

// FindTools は道具を探す。flash なら avrdude も要る
func FindTools(flash bool) (Tools, error) {
	t := Tools{
		Clang:   FindClang(),
		GCC:     findTool("SURU_AVR_GCC", "avr-gcc", arduinoTools("avr-gcc")),
		Objcopy: findTool("SURU_AVR_OBJCOPY", "avr-objcopy", arduinoTools("avr-gcc")),
		Size:    findTool("SURU_AVR_SIZE", "avr-size", arduinoTools("avr-gcc")),
		Avrdude: findTool("SURU_AVRDUDE", "avrdude", arduinoTools("avrdude")),
	}
	var missing []string
	if t.Clang == "" {
		missing = append(missing, "AVR に対応した clang(Apple の clang は AVR を作れません)")
	}
	if t.GCC == "" {
		missing = append(missing, "avr-gcc(と avr-libc)")
	}
	if t.Objcopy == "" {
		missing = append(missing, "avr-objcopy")
	}
	if flash && t.Avrdude == "" {
		missing = append(missing, "avrdude")
	}
	if len(missing) > 0 {
		return t, fmt.Errorf("マイコン向けのビルドに要る道具がありません: %s\n%s", strings.Join(missing, "・"), guide())
	}
	return t, nil
}

// --- ビルド ---

// Result は作ったもの
type Result struct {
	Hex, ELF   string
	Text, Data int // フラッシュ(.text+.data)と、RAM の初めから使う分(.data+.bss)
	FlashBytes int
	RAMBytes   int
	Board      Board
}

func runtimeObject(t Tools, b Board) (string, error) {
	key := append(append([]byte{}, suru.RuntimeAVR...), []byte(t.GCC+b.MCU+strconv.Itoa(b.FCPU))...)
	sum := sha256.Sum256(key)
	digest := hex.EncodeToString(sum[:])[:16]
	dir := native.CacheDir()
	obj := filepath.Join(dir, "suru_avr-"+digest+".o")
	if _, err := os.Stat(obj); err == nil {
		return obj, nil
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	src := filepath.Join(dir, "suru_avr-"+digest+".c")
	if err := os.WriteFile(src, suru.RuntimeAVR, 0o644); err != nil {
		return "", err
	}
	tmp := fmt.Sprintf("%s.%d.tmp", obj, os.Getpid())
	out, err := exec.Command(t.GCC, "-mmcu="+b.MCU, "-DF_CPU="+strconv.Itoa(b.FCPU)+"UL", "-Os", "-c", src, "-o", tmp).CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("マイコン向けの実行時ライブラリのコンパイルに失敗しました:\n%s", out)
	}
	return obj, os.Rename(tmp, obj)
}

// Compile は する のプログラムをマイコン向けの LLVM IR にする
func Compile(source, path string, b Board) (string, error) {
	source = compiler.NormalizeNewlines(source)
	ir, serr := compiler.CompileSmall(source, filepath.Dir(path), path, compiler.SmallTarget{Name: b.Display})
	if serr != nil {
		return "", errors.New(compiler.FormatError(serr, source, true))
	}
	return ir, nil
}

// Build は IR から out.hex(と out.elf)を作る
func Build(ir, out string, b Board, t Tools) (*Result, error) {
	if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
		return nil, err
	}
	rt, err := runtimeObject(t, b)
	if err != nil {
		return nil, err
	}
	ll, obj, elf, hexPath := out+".ll", out+".o", out+".elf", out+".hex"
	if err := os.WriteFile(ll, []byte(ir), 0o644); err != nil {
		return nil, err
	}
	defer os.Remove(ll)
	defer os.Remove(obj)
	if o, err := exec.Command(t.Clang, "--target=avr", "-mmcu="+b.MCU, "-Os", "-Wno-override-module", "-c", ll, "-o", obj).CombinedOutput(); err != nil {
		return nil, fmt.Errorf("clang(AVR)でのコンパイルに失敗しました:\n%s", o)
	}
	if o, err := exec.Command(t.GCC, "-mmcu="+b.MCU, "-Os", "-Wl,--gc-sections", obj, rt, "-o", elf).CombinedOutput(); err != nil {
		return nil, fmt.Errorf("avr-gcc でのリンクに失敗しました:\n%s", o)
	}
	if o, err := exec.Command(t.Objcopy, "-O", "ihex", "-R", ".eeprom", elf, hexPath).CombinedOutput(); err != nil {
		return nil, fmt.Errorf("avr-objcopy に失敗しました:\n%s", o)
	}
	r := &Result{Hex: hexPath, ELF: elf, Board: b}
	if t.Size != "" {
		if o, err := exec.Command(t.Size, elf).Output(); err == nil {
			lines := strings.Split(strings.TrimSpace(string(o)), "\n")
			if len(lines) == 2 {
				f := strings.Fields(lines[1])
				if len(f) >= 3 {
					text, _ := strconv.Atoi(f[0])
					data, _ := strconv.Atoi(f[1])
					bss, _ := strconv.Atoi(f[2])
					r.FlashBytes, r.RAMBytes = text+data, data+bss
				}
			}
		}
	}
	if r.FlashBytes > b.Flash {
		return r, fmt.Errorf("プログラムが大きすぎます(%d バイト、%s に入るのは %d バイトまで)", r.FlashBytes, b.Display, b.Flash)
	}
	return r, nil
}

// Summary は大きさの1行
func (r *Result) Summary() string {
	if r.FlashBytes == 0 {
		return ""
	}
	return fmt.Sprintf("フラッシュ %d / %d バイト、RAM(最初から使う分)%d / %d バイト", r.FlashBytes, r.Board.Flash, r.RAMBytes, r.Board.RAM)
}

// --- 書き込み ---

// FindPorts は USB でつないだ基板らしいシリアルポート
func FindPorts() []string {
	var pats []string
	switch runtime.GOOS {
	case "darwin":
		pats = []string{"/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/cu.wchusbserial*"}
	default:
		pats = []string{"/dev/ttyACM*", "/dev/ttyUSB*"}
	}
	var out []string
	for _, p := range pats {
		m, _ := filepath.Glob(p)
		out = append(out, m...)
	}
	sort.Strings(out)
	return out
}

// ChoosePort はポートを決める(指定がなければ、1つだけ見つかったもの)
func ChoosePort(given string) (string, error) {
	if given != "" {
		return given, nil
	}
	ps := FindPorts()
	switch len(ps) {
	case 0:
		return "", errors.New("基板のシリアルポートが見つかりません。USB でつないでいるか確かめるか、--ポート で指定してください")
	case 1:
		return ps[0], nil
	}
	return "", fmt.Errorf("シリアルポートが %d 個あります。--ポート で選んでください: %s", len(ps), strings.Join(ps, "・"))
}

// FlashArgs は avrdude の引数
func FlashArgs(hexPath, port string, b Board) []string {
	return []string{"-p", b.Part, "-c", b.Programmer, "-P", port, "-b", strconv.Itoa(b.Baud), "-D", "-U", "flash:w:" + hexPath + ":i"}
}

// Flash は avrdude で書き込む(ブートローダー経由)
func Flash(hexPath, port string, b Board, t Tools, stdout, stderr io.Writer) error {
	args := FlashArgs(hexPath, port, b)
	// Arduino IDE の avrdude は設定ファイルを横に持つ
	if conf := filepath.Join(filepath.Dir(filepath.Dir(t.Avrdude)), "etc", "avrdude.conf"); fileExists(conf) {
		args = append([]string{"-C", conf}, args...)
	}
	cmd := exec.Command(t.Avrdude, args...)
	cmd.Stdout, cmd.Stderr = stdout, stderr
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("avrdude での書き込みに失敗しました(%v)。ポート %s が合っているか、ほかのプログラム(シリアルモニターなど)が使っていないか確かめてください", err, port)
	}
	return nil
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

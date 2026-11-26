// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"os"
	"runtime"
	"strings"
)

// Target は作るプログラムの対象(clang の --target に渡すもの)。環境変数 SURU_TARGET で、
// 手元と違う OS 向けに作れる(x86_64-w64-mingw32 など。試験に使う)。空なら手元と同じ
func Target() string { return strings.TrimSpace(os.Getenv("SURU_TARGET")) }

// TargetWindows は Windows 向けに作るか(手元が Windows か、SURU_TARGET が Windows のもの)
func TargetWindows() bool {
	t := Target()
	if t == "" {
		return runtime.GOOS == "windows"
	}
	return strings.Contains(t, "windows") || strings.Contains(t, "mingw")
}

// windowsNoLibs は Windows にはなく C の標準のライブラリに入っているものと、作るときに必ず入れる pthread
var windowsNoLibs = map[string]bool{"dl": true, "rt": true, "pthread": true}

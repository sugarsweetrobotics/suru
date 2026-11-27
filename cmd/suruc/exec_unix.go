// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

//go:build !windows

package main

import (
	"os"
	"syscall"
)

// execProgram は suruc をプログラムに置き換える(シグナル・標準入出力・終了コードがそのまま通る)
func execProgram(exe string, args []string) int {
	err := syscall.Exec(exe, append([]string{exe}, args...), os.Environ())
	// 置き換えられなかったときだけ戻ってくる
	_ = err
	return waitProgram(exe, args)
}

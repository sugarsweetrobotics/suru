// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

//go:build windows

package main

// execProgram は Windows ではプログラムを子プロセスで動かして、終了を待つ
func execProgram(exe string, args []string) int {
	return waitProgram(exe, args)
}

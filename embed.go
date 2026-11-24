// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

// Package suru は、Go 版コンパイラ(cmd/suruc)に同梱する標準ライブラリと実行時ライブラリを持つ。
package suru

import "embed"

// Lib は lib/ の中身(「標準」 を 読み込む などで使う)
//
//go:embed lib/*.suru
var Lib embed.FS

// Runtime は実行時ライブラリ(C)のソース
//
//go:embed runtime/suru_rt.c
var Runtime []byte

// RuntimeAVR はマイコン(AVR)向けの小さい実行時ライブラリ(C)のソース
//
//go:embed runtime/avr/suru_avr.c
var RuntimeAVR []byte

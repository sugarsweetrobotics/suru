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

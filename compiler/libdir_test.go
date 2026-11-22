// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package compiler

import (
	"path/filepath"
	"testing"
)

// SURU_LIB(LibDir)のフォルダから読んだ「標準」「通信」にも、そのファイルの組み込みがあるか
func TestLibPrimitivesWithLibDir(t *testing.T) {
	old := LibDir
	defer func() { LibDir = old }()
	LibDir = ""
	if libPrimitives(StdPath) == nil || libPrimitives(NetPath) == nil {
		t.Fatal("同梱の標準・通信に組み込みがありません")
	}
	LibDir = t.TempDir()
	if libPrimitives(filepath.Join(LibDir, "標準"+SourceSuffix)) == nil {
		t.Fatal("LibDir の標準に組み込みがありません")
	}
	if libPrimitives(filepath.Join(LibDir, "通信"+SourceSuffix)) == nil {
		t.Fatal("LibDir の通信に組み込みがありません")
	}
	if libPrimitives(filepath.Join(t.TempDir(), "標準"+SourceSuffix)) != nil {
		t.Fatal("ほかのフォルダの「標準」は標準ライブラリではありません")
	}
}

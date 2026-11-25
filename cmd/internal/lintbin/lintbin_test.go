// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (c) 2026 sugarsweetrobotics

package lintbin

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/suru-lang/suru/compiler"
)

// 点検が使う lib のファイルだけをたどる(suru.py の lint_lib_files と同じもの)
func TestLibFiles(t *testing.T) {
	dir, _ := filepath.Abs("../../../lib")
	old := compiler.LibDir
	compiler.LibDir = dir
	defer func() { compiler.LibDir = old }()
	got := strings.Join(libFiles(), " ")
	for _, want := range []string{"点検.suru", "字句.suru", "構文.suru", "表.suru", "基本.suru", "標準.suru"} {
		if !strings.Contains(got, want) {
			t.Errorf("%s がありません: %s", want, got)
		}
	}
	for _, not := range []string{"通信.suru", "スレッド.suru"} {
		if strings.Contains(got, not) {
			t.Errorf("%s は使っていません: %s", not, got)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "通信.suru")); err != nil {
		t.Fatal(err)
	}
}

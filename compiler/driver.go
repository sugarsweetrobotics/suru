package compiler

// CompileSource は する のプログラムを LLVM IR の文字列にする。間違いがあれば *SuruError
func CompileSource(source, baseDir, path string, check bool) (ir string, err *SuruError) {
	err = try(func() {
		ctx := NewParseContext(baseDir)
		program := ParseProgram(source, ctx)
		if check {
			TypeCheck(program, ctx)
		}
		checkDefinitions(program, ctx)
		ir = newCompiler(ctx, source).compile(program, path)
	})
	return
}

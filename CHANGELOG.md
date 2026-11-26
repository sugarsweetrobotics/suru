# Changelog

[日本語](CHANGELOG_jp.md)

Changes to Suru itself (`suru`, `suruc`, `suru-ls`, `kumu` and the bundled `lib/`). Versions before 0.7.0 are listed on [GitHub Releases](https://github.com/suru-lang/suru/releases). The VS Code extension has its own version.

## Unreleased

### New

1. **`外部の（f）`, which calls through a function pointer, can be written on one line or in a block.** `p を f で 呼出する とは 外部の（f） で 番地 を 番地 で 受け取って 無 を 返す 入出力動作です` fits on one line. Inside `以下は外部の入出力動作です` it is `p を f で 呼出する とは （f） で 番地 を 番地 で 受け取って 無 を 返します` (#189).
2. **`そうでなければ` can follow `もし … ならば 以下の手順です`.** After the procedure is closed by a deeper `以上`, a `そうでなければ …` line can come at the indent of the `もし` line. Previously the long branch had to be moved to the `そうでなければ` side (#190).
3. **Record definitions can give field types.** Write `field は type` separated by `で`, as in `会員 とは 番号 は 数 で 名前 は 文字列 の 組`. Values are checked against the written types, and `甲`, `乙` … become the type's parameters. This is the first stage of the plan for deriving and quasi-quotes (#192).
4. **Quasi-quotes.** `以下は【X】です` … `以上です` (top level) and `x とは 以下の【X】です` … `以上です` hand the block to `X展開する` (`文字列 を X展開する は 文字列 の 成否`, defined in a file the program reads) and put the returned Suru code in its place. `suruc` compiles the expander into a cached program. `suru --展開` and `suruc --展開` print the expanded source. `【` and `】` outside strings are now reserved for this (#192).
5. **Tests in the same file, and examples.** A `以下は「二倍」の試験です … 以上です` block at the top level is a test that can use the file's private names, and `例えば （2 を 二倍する） は 4 です` under a definition is an example. Both are always type checked, are dropped in a normal run or build, and are ignored when the file is imported (#193).
6. **`suru --試験 ファイルかフォルダ [名前]` runs tests.** It runs the test blocks, the examples and the top-level `…試験する` procedures of the files, and reports like `kumu 試験`. Words that are not paths select tests by part of their name (#193).
7. **Deriving.** `会員 は 【JSON】 と 【表】 を 導出する` hands a description of the type (`型記述` from the new `lib/導出.suru`) to `JSON導出する` and `表導出する` from a file the program reads, and puts the definitions they return in place of the line. The type must be defined in the same file with field types (#192).
8. **Deriving JSON.** `会員 は 【JSON】 を 導出する` defines `会員JSON化する` and `会員JSON復元する` (`（会員 と 文字列） の 成否`). Records become objects, and types with several forms get a `形` item. Fields can be `数`, `文字列`, `真偽`, `JSON`, `X の リスト` and other types that derive 【JSON】 (#192).

### Fixed

1. **The interpreter shows what it printed before it waits.** Like a compiled program, it now flushes standard output before waiting for a connection (`接続受付する`) or for data from a connection, so a server whose output goes to a pipe shows `ポート 9000 で待っています` right away (#195).
2. **A deadlock between threads is always reported.** When two threads started waiting at almost the same moment (for example `合流する` and `通路受信する`), a compiled program could sometimes hang instead of failing with 「すべてのスレッドが待っていて、先に進めません」 (#195).

## 0.9.1

### New

1. **The external function block can start with 「以下は」.** `以下は外部の関数です` / `以下は外部の入出力動作です` (and `以下 は 外部 の …`) read like the start of a sentence, and are now the documented form. The 0.9.0 spelling `以下の外部の…` keeps working with the same meaning. Programs that use `以下は外部の…` need this release (#186).

### Improved

1. **The bundled `lib/` writes its C functions in the new way.** The two-line external definitions are now one-line definitions or `以下は外部の入出力動作です` … `以上です` blocks. Nothing changes for programs that use the library.
2. **The test runner that `kumu 試験` writes leaves a blank line between definitions,** so `suru --点検` on it no longer reports 「定義の間の空行」.

The VS Code extension 0.9.1 highlights `以下は外部の入出力動作` and `以下は外部の関数` too.

## 0.9.0

### Changes that need edits when moving from 0.8

1. **New lint rule 「定義の間の空行」 (blank line between definitions).** `suru --点検` and `kumu 点検` report a function definition of two or more lines that is followed on the very next line by another function's definition. Add a blank line, or write `# 点検しない: 定義の間の空行` on that line (#175).
2. **`以下の外部の入出力動作` and `以下の外部の関数` are read as one word.** `以下 の 外部 の 入出力動作` also works (#174).

### New

1. **External functions with their type on one line.** Writing the type after the definition, as in `n を 確保する とは 外部の「SDL_malloc」 で 数 を 受け取って 番地 を 返す 入出力動作です`, names the function only once (#173).
2. **A block of external functions.** Between `以下の外部の入出力動作です` and `以上です`, write one function per line, as in `数 を 確保する は 「SDL_malloc」 で 番地 を 返します`. Functions that are not actions go in `以下の外部の関数です` (#174).
3. **The lint rule 「定義の間の空行」** (#175).

### Improved

1. **The libm functions in `lib/算術.suru` are written with `以下の外部の関数です`, and the definitions in `lib/` are separated by blank lines.**
2. **The parser written in する (`lib/構文.suru`) reads `外部の「f」（a と 0）`, which lists the arguments passed to C.**

The VS Code extension 0.9.0 highlights `以下の外部の入出力動作` and `以下の外部の関数`.

## 0.8.0

### New

1. **Windows support (MSYS2 UCRT64).** `suruc`, `kumu 作る` and `suru --翻訳` make Windows .exe files, and `SURU_TARGET` (for example `x86_64-w64-mingw32`) builds them from Linux or macOS. Use MSYS2's clang and lld (`pacman -S mingw-w64-ucrt-x86_64-clang mingw-w64-ucrt-x86_64-lld`). A built .exe needs no extra DLLs and handles UTF-8 paths and text (#176, #177, #180).
2. **The standard library works in Windows programs.** 「ファイル」, 「時間」, 「乱数」, 「動的リンク」, 「共有メモリ」, 「環境」, 「プロセス」 (through `cmd.exe`) and the others work. `分岐する`, `子実行する`, the System V semaphores and 「シグナル」 say 「…は Windows ではまだ使えません」 ("not available on Windows yet") when called (#178, #181).
3. **GitHub Releases has `suruc.exe` and `kumu.exe` for Windows** (amd64 and arm64), next to `suru-ls.exe`. The release workflow runs them on Windows before publishing (#182).

### Fixed

1. **The lint binary is always built for the machine you are on**, even when `SURU_TARGET` is set (#177).

The libraries regex, sqlite, http and gui-sdl3 also run their tests on Windows now, and their READMEs explain the MSYS2 packages.

## 0.7.0

### Changes that need edits when moving from 0.6

1. **`以上` is a reserved word.** `以上` can no longer be used as a name, and `以下の手順` / `以下の入出力手順` are read as one word (#161, #162).
2. **Indentation ends a nested case analysis.** A line back at the indent of the outer cases ends the inner `もし 値 が`. Before, the inner one took the outer cases after it (`2 ならば …`, `そうでなければ …`) as its own, so a program that relied on that reading now means something else (#162).
3. **Undefined names are type errors.** Typos in branches or functions that never run are reported by `suru --検査`, `suruc` and `kumu 作る` before running. A program that ran before because the typo was never reached now fails the check (#149).
4. **A sentence in a procedure whose value is a list of actions is an error.** `xs の それぞれ を 表示する` in a procedure did nothing; write `（xs の それぞれ を 表示する） を 実行する` (#151).
5. **A procedure local that holds an action cannot go into a record.** `番号 とは n を 番号作成する` (without 「した 結果」) followed by `番号 の 数値` is an error at the definition. Write `n を 番号作成した 結果`, or write the action directly in the record if you mean to store it (#168).
6. **`整列する` sorts numbers or strings only.** It is now a builtin stable merge sort. Elements must be all numbers or all strings; other element types are type errors (#153).
7. **Runtime errors inside libraries are shown at the caller's position.** The line and column in the message and in `--json` point to your program, with the library position in parentheses. Tools that read these positions see different numbers (#154).
8. **New lint rule 「値の再定義」.** `suru --点検` and `kumu 点検` report the second definition of the same value (#155).

### New

1. **`X とは 以下の手順です` … `以上`** for procedures, and `以上` to close a nested `もし 値 が` on one line (#161, #162).
2. **`基準整列する`** sorts by a key, and `整列する` sorts strings (#153).
3. **`kumu 試験` shows the line of a failed check**, and `kumu 新規` writes `試験/例.suru`. The new builtin `呼出場所取得する` (「標準」) returns the caller's position (#155).

### Improved

1. **Hints on errors**: close names for typos, missing `読み込んで 使う`, spaces around operators (#149); 「それぞれ」 with an anonymous function, a call in 「もし 値 が」, indented 「ただし」, a constructor used as a function (#155).
2. **`a と b を 受け取って`**: a and b may have different types, so folds with a different accumulator type work (#150).
3. **Deep recursion in the interpreter** runs about 200,000 levels, and stops with a Suru error instead of a Python traceback (#152).
4. **`整列する` is O(n log n)** in the interpreter and compiled code (#153).
5. **The type checker sees names opened by a loaded file**, as running does (#149).
6. **`最大値にする` / `最小値にする` of an empty list** explain the error (#154).

### Fixed

1. **「プロセス」 and 「ファイル」 can be loaded together** (and so can http and 「プロセス」). Both declared C `fread` with different types, so compiling failed. When two files declare the same C function with different types, the error now also shows where the other declaration is (#120).

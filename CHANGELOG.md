# Changelog

[日本語](CHANGELOG_jp.md)

Changes to Suru itself (`suru`, `suruc`, `suru-ls`, `kumu` and the bundled `lib/`). Versions before 0.7.0 are listed on [GitHub Releases](https://github.com/suru-lang/suru/releases). The VS Code extension has its own version.

## Unreleased

### New

1. **Build shared libraries that other languages can call.** List exported functions and their C names with `以下は外部に出す関数です` … `二倍する は 「nibai」` … `以上です`, and build a .so or .dylib with `suruc --共有ライブラリ 計算.suru -o libkeisan.so` (`suru --翻訳 --共有ライブラリ` in the Python version). Types come from the type declaration (数, 整数, 小数, 単精度, 真偽, 文字列, 番地, 無), and the functions can be called from Python's ctypes, C and so on. Runtime errors return 0 and can be read with `keisan_last_error()`, and calls work from any thread. This is stage 1 of #208.
2. **`suruc --共有ライブラリ` also writes a C header.** Building `libkeisan.so` writes `keisan.h` next to it, with the prototypes, the Suru name and types of each function, and notes on errors and freeing strings. `examples/他の言語から/` has examples that call the library from Python, C, C++, Go and Rust. This is stage 2 of #208.
3. **SHA-256 and HMAC-SHA256 in 「ハッシュ」.** `b を ハッシュ内のSHA256にする` and `b を 鍵 で ハッシュ内のHMACSHA256にする` give 32 bytes, the same in the interpreter and compiled binaries. They are for signing cookies in suru-lang/web (#192).
4. **`kumu 新規 店 --対象 web` creates a web app for 屋台 (suru-lang/web).** It writes `組.suru` (depending on `github.com/suru-lang/web@0.1.0`), `店.suru` with routes in 【道】, `本体.suru` that opens the server on port 8080, pages in `画面/`, a stylesheet in `公開/` and tests of the routes in `試験/道.suru`. `kumu 初期化 --対象 web` works the same in the current folder (#192).
5. **Lists, byte sequences and handles cross the boundary.** `バイト列` and lists of numbers, decimals or strings are passed as a pointer and a length (results as a new block plus `int64_t *out_len`), and any other value (records, functions, other lists) as a `keisan_value *` handle with helper functions (`keisan_get`, `keisan_field`, `keisan_to_int`, `keisan_call`, `keisan_release` and so on). Libraries that use self-recursive functions, such as ones that load 「標準」, now link as shared libraries too. This is stage 3 of #208.
6. **kumu builds shared libraries.** Write `種類 とは 「共有ライブラリ」` in 組.suru and `kumu 作る` writes `出力/libNAME.so` (or `.dylib`) and `出力/NAME.h` (`ライブラリ名 とは 「…」` sets NAME when the project name isn't ASCII). `kumu 新規 NAME --共有ライブラリ` creates a library project with a test. A library whose code doesn't use self-recursion now also builds at `-O0`. This is stage 4 of #208.
7. **Shared libraries on Windows.** `suruc --共有ライブラリ` (and kumu) now builds a `.dll` on Windows (MSYS2 UCRT64), together with the import library `libNAME.dll.a` for linking and the header. Only the exported and helper functions are exported. The shared library tests run on Windows in CI. This is stage 5 of #208.
8. **`docs/AIの手引き.md` explains shared libraries.** A new section shows how to export functions, the type mapping, errors and kumu, and the remaining ideas are listed in `docs/今後/共有ライブラリ.md`. This is stage 6 of #208.

### Fixed

1. **A quasi-quote head written in a comment is no longer read as code.** A line like `# 例: 道群 とは 以下の【道】です` (or with `＃`/`※` before `とは`) used to start a quasi-quote and then fail with 「中身は頭より深く字下げして…」. The interpreter, `suruc` and `suru --点検` now treat it as a comment (#192).
2. **`suru --点検` reads type declarations with `と` between parameter types.** `lib/構文.suru` now reads `数 を 数 と 数 と 数 で 三回転和にする は 数` (a list whose items have their own types, added in #119) like `suru.py`, instead of failing on the whole file.
3. **A deriver or expander from a dependency can read that dependency's own dependencies.** `suruc` and `kumu` compiled the expander with the packages of the dependency's folder, which has no `組.lock`, so `会員 は 【表】 を 導出する` with only suru-lang/orm as a dependency failed with 「ファイル「蔵.suru」が見つかりません」. The expander now uses the packages of the program being built (#192).

## 0.10.1

### Fixed

1. **`kumu 試験` and `kumu 点検` skip folders that are projects of their own.** A folder below the project with its own `組.suru` (such as a project in `例/`) is a separate project, so its files are no longer tested or linted with the outer project's dependencies. Since 0.10.0 such files made `kumu 試験` fail with 「ファイル「蔵.suru」が見つかりません」 (#193).

## 0.10.0

### New

1. **`外部の（f）`, which calls through a function pointer, can be written on one line or in a block.** `p を f で 呼出する とは 外部の（f） で 番地 を 番地 で 受け取って 無 を 返す 入出力動作です` fits on one line. Inside `以下は外部の入出力動作です` it is `p を f で 呼出する とは （f） で 番地 を 番地 で 受け取って 無 を 返します` (#189).
2. **`そうでなければ` can follow `もし … ならば 以下の手順です`.** After the procedure is closed by a deeper `以上`, a `そうでなければ …` line can come at the indent of the `もし` line. Previously the long branch had to be moved to the `そうでなければ` side (#190).
3. **Record definitions can give field types.** Write `field は type` separated by `で`, as in `会員 とは 番号 は 数 で 名前 は 文字列 の 組`. Values are checked against the written types, and `甲`, `乙` … become the type's parameters. This is the first stage of the plan for deriving and quasi-quotes (#192).
4. **Quasi-quotes.** `以下は【X】です` … `以上です` (top level) and `x とは 以下の【X】です` … `以上です` hand the block to `X展開する` (`文字列 を X展開する は 文字列 の 成否`, defined in a file the program reads) and put the returned Suru code in its place. `suruc` compiles the expander into a cached program. `suru --展開` and `suruc --展開` print the expanded source. `【` and `】` outside strings are now reserved for this (#192).
5. **Tests in the same file, and examples.** A `以下は「二倍」の試験です … 以上です` block at the top level is a test that can use the file's private names, and `例えば （2 を 二倍する） は 4 です` under a definition is an example. Both are always type checked, are dropped in a normal run or build, and are ignored when the file is imported (#193).
6. **`suru --試験 ファイルかフォルダ [名前]` runs tests.** It runs the test blocks, the examples and the top-level `…試験する` procedures of the files, and reports like `kumu 試験`. Words that are not paths select tests by part of their name (#193).
7. **Deriving.** `会員 は 【JSON】 と 【表】 を 導出する` hands a description of the type (`型記述` from the new `lib/導出.suru`) to `JSON導出する` and `表導出する` from a file the program reads, and puts the definitions they return in place of the line. The type must be defined in the same file with field types (#192).
8. **`suruc --試験 ファイルかフォルダ [名前]` runs the same tests with the Go compiler.** Each file becomes one test binary (built with -O0 unless another -O is given), and each test runs in its own process. The output is the same as `suru --試験` (#193).
9. **Deriving JSON.** `会員 は 【JSON】 を 導出する` defines `会員JSON化する` and `会員JSON復元する` (`（会員 と 文字列） の 成否`). Records become objects, and types with several forms get a `形` item. Fields can be `数`, `文字列`, `真偽`, `JSON`, `X の リスト` and other types that derive 【JSON】 (#192).
10. **`kumu 試験` also runs the test blocks and examples in the project's source files.** Each source file (other than `組.suru` and the files in `試験/` and `出力/`) with tests becomes one test binary, linked with the project's C sources, and runs in the project folder. `kumu 試験 名前` selects them by name as before (#193).
11. **The interactive mode (REPL) reads quasi-quotes and deriving.** It waits for `以上です` before running a `以下は【X】です` block, and finds expanders, derivers and types from earlier inputs, so `「道」 を 読み込む` and `会員 とは …` can be typed before the line that uses them (#192).
12. **The tools read test blocks and examples.** `lib/字句.suru` and `lib/構文.suru` (and so `suru --点検`) read `以下は「二倍」の試験です … 以上です` and `例えば … は … です` like `suru.py`, so files in `lib/` can now have tests. The language server lists test blocks and examples in the outline by their test names (`二倍`, `二倍するの例(4行)`), and the VS Code grammar highlights the test head and `例えば` (#193).
13. **`lib/` has tests in the same file.** `lib/算術.suru`, `lib/乱数.suru` and the number and string formatting of `lib/標準.suru` now have examples and test blocks, which `suru --試験 lib/` and `suruc --試験 lib/` run on every PR. `suru --試験` on a file of `lib/` itself (such as `lib/標準.suru`) can use that file's built-in primitives. The language server shows a definition's examples when hovering over its name (#193).

### Fixed

1. **The interpreter shows what it printed before it waits.** Like a compiled program, it now flushes standard output before waiting for a connection (`接続受付する`) or for data from a connection, so a server whose output goes to a pipe shows `ポート 9000 で待っています` right away (#195).
2. **A deadlock between threads is always reported.** When two threads started waiting at almost the same moment (for example `合流する` and `通路受信する`), a compiled program could sometimes hang instead of failing with 「すべてのスレッドが待っていて、先に進めません」 (#195).
3. **A program inside the repository's `lib/` folder could not use `標準内の…` built-ins when compiled with `suruc`.** The compiled program stopped with 「「標準内の引数取得する」は定義されていません」 because `lib/標準.suru` was read from that folder instead of the bundled copy. Now a file with the same contents as the bundled one gets the same built-ins (#193).

The VS Code extension 0.10.0 highlights quasi-quotes (`以下は【X】です` … `以上です`, with the block left uncolored as another language), `【X】` and `導出する`.

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

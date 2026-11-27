English | [日本語](README_jp.md)

# Suru (「する」): a functional programming language in Japanese (prototype)

Suru is a programming language whose programs read like Japanese sentences. Function names end in する ("to do"), arguments are marked with Japanese case particles (を, に, で, から, へ, より) instead of being placed by position, and you can write either with spaces between words or packed tightly with Japanese punctuation (「。」 and 「、」).

The interpreter runs on Python 3.10 or later alone (no external libraries; the tests use pytest).

```sh
python3 suru.py examples/basic.suru   # check types, then run (prints the value of each top-level expression on its own line)
python3 suru.py --検査 examples/basic.suru  # look for type errors without running (--check also works)
python3 suru.py --検査なし examples/basic.suru  # run without checking types (--no-check also works)
python3 suru.py                       # interactive mode (type one line at a time and see its value and type right away)
python3 suru.py --対話 examples/数学.suru  # load a file, then enter interactive mode (-i also works)
python3 suru.py --翻訳 examples/basic.suru  # build the binary examples/basic (--compile also works; needs clang)
python3 -m pytest tests               # tests
```

### Installing

| Method | How to install | What you get |
|---|---|---|
| pip | `pip install suru-lang` | `suru` |
| Homebrew (macOS, Linux) | `brew install suru-lang/suru/suru` | `suru`, `suruc`, `suru-ls`, `kumu` |
| Binaries | `suru-VERSION-OS-CPU.tar.gz` (`.zip` for Windows) from [GitHub Releases](https://github.com/suru-lang/suru/releases) | `suruc`, `suru-ls`, `kumu` |
| VS Code | Search for 「する」 in the Extensions view | The extension (bundles `suru-ls`) |

Building binaries (`suru --翻訳`, `suruc`) needs clang on your machine, whichever method you use. On macOS install it with `xcode-select --install`; on Ubuntu and similar, with `sudo apt install clang`. On Windows, use the MSYS2 UCRT64 shell and install clang and lld with `pacman -S mingw-w64-ucrt-x86_64-clang mingw-w64-ucrt-x86_64-lld` (see "Building programs for Windows").

### Installing with pip

```sh
pip install suru-lang   # for the latest repository: pip install git+https://github.com/suru-lang/suru (or pip install . in a cloned folder)
suru examples/basic.suru          # same as python3 suru.py (--検査, --検査なし and --翻訳 work too)
suru --version
```

The standard library (`lib/標準.suru`) and the compiler's runtime library (`runtime/suru_rt.c`) are installed along with it. `--翻訳` needs clang separately.

### Fast compiler (Go version)

You can do the same thing as `--翻訳` with `suruc`, a compiler written in Go. It emits LLVM IR identical to the Python version, character for character, and gets to the IR about 14 to 35 times faster (requires Go 1.23 or later).

```sh
go install github.com/suru-lang/suru/cmd/suruc@latest   # or go build ./cmd/suruc in a cloned folder
suruc examples/basic.suru          # build the binary examples/basic (needs clang)
suruc -O0 examples/basic.suru      # weaker clang optimization for a faster build (-O0 to -O3; the default is -O2)
suruc --ll examples/basic.suru     # emit only the LLVM IR
```

`suruc` is a single executable with the standard library and the runtime library built in (`SURU_LIB` changes where lib/ is looked up).

### Building projects (kumu)

`kumu` (組む, "to assemble") is one tool that creates project skeletons, builds and runs (something like cargo). It contains the Go compiler, so you don't need `suruc` separately (you do need clang).

```sh
go install github.com/suru-lang/suru/cmd/kumu@latest   # or go build ./cmd/kumu in a cloned folder
kumu 新規 挨拶      # create 組.suru, 本体.suru and .gitignore in 挨拶/ (new)
cd 挨拶
kumu 実行           # build 出力/挨拶 and run it (run; arguments after -- go to the program)
kumu 作る           # only build 出力/挨拶 (build; -O0 to -O3 and --検査なし work too)
kumu 初期化         # create the skeleton in the current folder (init)
kumu 新規 店 --対象 web   # create a web app for 屋台 (suru-lang/web) in 店/
kumu 追加 github.com/someone/計算   # add a dependency; without a version, the newest tag (add; …@1.2.0 picks a version)
kumu 更新           # move dependencies to their newest tags (update; kumu 更新 計算 updates just one)
kumu 削除 計算      # remove a dependency (remove)
kumu 取得           # fetch dependencies and write 組.lock (fetch; 作る and 実行 do this too)
kumu 試験           # run the tests of the source files, then each 「…試験する」 in 試験/ (test; kumu 試験 二倍 picks by part of the name)
kumu 点検           # lint every file in the project (check)
kumu 公開           # check, then put the Git tag vVERSION (publish; push it yourself)
kumu 文書           # write API documentation of the public names to docs/api (doc; --雛形 writes Sphinx and Read the Docs settings)
```

Tests can be written in the same file as the code they test, as test blocks and examples ("Tests in the same file and examples"):

```
数 を 二倍する は 数
x を 二倍する とは x * 2
例えば （2 を 二倍する） は 4 です

以下は「二倍」の試験です
  （0 を 二倍する） を 0 に 一致確認する
  以上です
```

Tests can also be written in files in the `試験/` ("tests") folder, as procedures whose names end in 「試験する」.

```
「試験」 を 読み込んで 使う
「計算」 を 読み込む                       # load a project file by its name in 組.suru

二倍試験する とは 以下の手順です
  （2 を 計算内の二倍する） を 4 に 一致確認する
  1 < 2 を 確認する
  以上です
```

The steps for publishing a library are in [docs/ライブラリを公開する.md](docs/ライブラリを公開する.md) (in Japanese). You can also run kumu's commands from the command palette of the VS Code extension.

A project's settings are written in `組.suru` as Suru definitions.

```
名前 とは 「挨拶」
版 とは 「0.1.0」
入口 とは 「本体」
依存 とは 「github.com/someone/計算@1.2.0」 と 「../手元の部品」
```

(名前 = name, 版 = version, 入口 = entry file, 依存 = dependencies.) Dependencies are loaded just like ordinary files, with `「計算」 を 読み込む`, and used as `計算内の二倍する`.

### Flashing a microcontroller (Arduino)

You can build for the Arduino Uno and Nano (ATmega328P) and write the program to a board connected over USB through its bootloader. The microcontroller has only 2KB of RAM, so what you can write is limited to constants of numbers, booleans and strings ("Small Suru for microcontrollers" below).

```sh
kumu 新規 点滅 --対象 arduino-uno   # create a skeleton that blinks the board's LED
cd 点滅
kumu 作る           # build 出力/arduino-uno/点滅.hex (also prints the flash and RAM sizes)
kumu 書き込む       # build, then write to the serial port it finds with avrdude (flash; choose with --ポート /dev/cu.usbmodem1101)
```

```
「マイコン」 を 読み込んで 使う

点滅する とは 以下の手順です
  内蔵灯 を 反転出力する
  500 を ミリ秒待機する
  点滅する
  以上です

内蔵灯 を 出力設定する
「こんにちは」 を 表示する      # goes to the serial port (9600)
点滅する
```

Writing `対象 とは 「arduino-uno」` in 組.suru makes 作る and 書き込む target the microcontroller (`arduino-nano` and `arduino-nano-old`, for the old bootloader, are also available). `suruc --対象 arduino-uno 点滅.suru` also builds the .hex. The tools needed are a clang that supports AVR, avr-gcc (avr-libc) and avrdude. On macOS, install them with `brew install llvm avrdude` and `brew tap osx-cross/avr && brew install avr-gcc` (Apple's clang can't build for AVR, so kumu looks for the clang of Homebrew's llvm). On Ubuntu, use `sudo apt install clang gcc-avr avr-libc avrdude`. kumu also finds and uses the avr-gcc and avrdude installed by the Arduino IDE.

### VS Code extension

There is a VS Code extension in `editors/vscode/`. It offers syntax highlighting (function names, case particles, keywords, strings, names in 『』 and so on, in both the spaced style and the punctuation style), type checking as you type (errors get squiggly underlines), type hovers, go to definition, a list of definitions, completion, rename, coloring of type names, running with ▷ or F5, and building binaries. Checking as you type, hovers and go to definition are handled by the language server `suru-ls` (`cmd/suru-ls`), which uses the Go version's checker. Installation is described in [editors/vscode/README.md](editors/vscode/README.md).

## Examples

```
数 と 数 を 加算する は 数 を 返す
a と b を 加算する とは a + b です

数 を 三倍する は 数 を 返す
引数 を 三倍する とは 引数 と 引数 を 加算して 引数 を 加算する

1 と 2 を 加算する      # → 3
5 を 三倍する           # → 15
```

This defines 加算する ("add") taking a list `a と b` ("a and b") marked with を, and 三倍する ("triple") built as a pipeline: add the argument to itself, then (して, "and then") add the argument again. A type declaration ends with `… を 返す` ("returns …"), and the です ("is") at the end of a definition only makes it read as a sentence.

```
a を b で 割った数にする とは a / b です
2 で 10 を 割った数にする              # → 5 (the particles decide the arguments, so word order is free)

リスト とは 1 と 2 と 3 です
リスト の それぞれ を 三倍する        # → （3 と 6 と 9）
リスト から 偶数判定すること で 選別する
5 に （1 を 加算すること） を 適用する  # → 6
```

Here リスト の それぞれ ("each of the list") maps a function over a list, …すること ("the act of doing …") turns a function into a value, and 選別する ("select") is filter.

You can also write without spaces or line breaks, packed tightly with punctuation (you may mix both styles in the same file).

```
aとbを加算するとは、a+bです。引数を三倍するとは、引数と引数を加算して、引数を加算する。
1と2を加算する。5を三倍する。                         # → 3、15
aとbを平均するとは、合計/2です。ただし、合計とは、a+bです。   # local definitions use 「ただし」 ("where")
```

Records (named tuples), types with alternatives, pattern matching and traits (type classes) are available too.

```
図形 とは 半径 の 円 か 幅 と 高 の 長方形 です

図形 を 面積にする は 数 を 返す
形 を 面積にする とは
  もし 形 が
    半径 の 円 ならば 3 * 半径 ^ 2 です
    幅 と 高 の 長方形 ならば 幅 * 高 です

5 の 円 を 面積にする                        # → 75
幅 は 2 で 高 は 3 の 長方形 を 面積にする    # → 6
```

(A 図形 "shape" is either a 円 "circle" with a 半径 "radius", or (か) a 長方形 "rectangle" with a 幅 "width" and 高 "height". もし … が … ならば reads "if … is … then".)

Writing values or shapes in place of arguments defines a function case by case. Patterns can take a condition with 「かつ」 ("and").

```
数 を 階乗する は 数 を 返す
0 を 階乗する とは 1 です
n を 階乗する とは n * （n - 1 を 階乗する） です

空 を 合計する とは 0 です
先頭 は x で 残り は 他 を 合計する とは x + （他 を 合計する） です

図形 を 分類する は 文字列 を 返す
形 を 分類する とは
  もし 形 が
    半径 の 円 かつ 半径 >= 10 ならば 「大きい円」 です
    半径 の 円 ならば 「円」 です
    そうでなければ 「長方形」 です
```

A name ending in 「…である」 ("is …") is a predicate (a function returning true or false), and takes its subject with 「が」.

```
n が 偶数である とは n % 2 が 0 です
もし n が 偶数である ならば 「偶」 そうでなければ 「奇」
3 が 偶数でない                                # → 真
リスト から 偶数であること で 選別する
```

Side effects such as printing and input are handled as values called 「入出力動作」 ("input/output actions"), and carried out in order by the sentences from 「以下の手順です」 ("the steps below") to 「以上です」 ("that is all"). A type declaration writes them as `… を 返す 入出力動作` ("an input/output action that returns …").

```
挨拶するは、数を返す入出力動作。
挨拶するとは、以下の手順です。
  名前とは、「お名前は? 」を入力した結果。     # 「…した 結果」 ("the result of having done …") receives an action's result
  「こんにちは、」+名前+「さん」を表示する。
  名前の長さを結果にする。
  以上です。
挨拶してから、表示する。                       # 「してから」 ("after doing") passes the previous action's result to 「を」
「はじめ」を表示する。それから、「おわり」を表示する。
```

In the spaced style it looks like this. To pack a procedure into one line, you can also write `手順（文。文。）`.

```
文字列 を 歓迎する は 無 を 返す 入出力動作
名前 を 歓迎する とは 以下の手順です
  「こんにちは、」 + 名前 + 「さん」 を 表示する
  「ようこそ」 を 表示する
  以上です
```

More examples: `examples/stdlib.suru` and `examples/stdlib_open.suru` show the standard library, `examples/predicate.suru` predicates, `examples/cases.suru` case-by-case function definitions and pattern conditions, `examples/io.suru` actions and procedures, `examples/blocks.suru` 「以下の手順です … 以上」 and nested case analysis, `examples/fib_input.suru` asks for a count and prints the Fibonacci sequence, `examples/data.suru` records, pattern matching and traits, `examples/punct.suru` the punctuation style, `examples/more.suru` line breaks and indentation, local definitions, conditionals and recursion, and long pipelines, and `examples/list.suru` particle arguments, lists and higher-order functions. `examples/通信/` has TCP and UDP echo servers and echo clients (run them in two terminals).

## Grammar summary

| Syntax | Meaning |
|---|---|
| `a を b で 除算する とは a / b` | A function definition. Each parameter name is followed by a **case particle** (を, に, で, から, へ, より). Function names end in 「する」 |
| `10 を 2 で 除算する` / `2 で 10 を 除算する` | A call. Arguments are matched by particle, so word order is free |
| `答えする とは 42` | A function with no arguments |
| `税率 とは 0.1` | A value definition (a name that does not end in 「する」) |
| `10 を 2 で 除算して 3 に 加算する` | A pipeline. The result of 「…して」 goes into the next function's **「を」** |
| `1 と 2 と 3`, `空` | A list, the empty list |
| `a と b を 加算する とは a + b` | Takes a list as 「を」, destructured into a and b |
| `リスト の 先頭` `の 残り` `の 最後` `の 長さ` | List properties (head, rest, last, length) |
| `x を リスト に 追加する` / `挿入する` | A new list with x added at the end / front |
| `もし リスト が 空 ならば …` | 「が」 tests equality (same as `==`) |
| `n が 偶数である とは …` | A predicate (function returning a boolean) definition. The subject takes 「が」 |
| `4 が 偶数である` / `3 が 偶数でない` / `偶数であること` | Calling a predicate / its negation / the predicate itself (as a value) |
| `三倍すること`, `1 を 加算すること` | A function itself (as a value). With missing arguments it is a partial application |
| `x を 受け取って x * 2 を 返すこと` | An anonymous function ("take x and return x * 2") |
| `リスト の それぞれ を 三倍する` | Calls the function for each element and returns the list of results (map) |
| `もし 条件 ならば 式 そうでなければ 式` | A conditional (an expression, so it always returns a value) |
| `+ - * / % ^`, `× ÷`, full-width `＋－＊／` | Arithmetic (`^` is exponentiation). `+` on two lists concatenates |
| `== != < > <= >=`, `= ≠ ≦ ≧` | Comparison. The result is `真` (true) / `偽` (false). Ordering (`<` etc.) works between numbers or between strings (by character code) |
| `条件 かつ 条件`, `条件 または 条件` | Boolean "and" and "or" (the right side is not evaluated if the left decides) |
| `( … )` `（ … ）` | Parentheses. Also used to embed a call in arithmetic or in an argument |
| `「文字列」` | A string. Concatenate with `+` |
| `#`, `＃`, `※` | Comment to end of line |
| `5を三倍する。` | The punctuation style. 「。」 ends a sentence and 「、」 separates. You can write packed without spaces |
| `5を三倍します。`, `5を三倍しまして、表示します。`, `p とは 3 と 4 の 点 です。` | Polite sentence endings. 「します」 is the same as 「する」, 「しまして」 as 「して」. A trailing 「です」 is ignored |
| `数 を 階乗する は 数 を 返す`, `数を階乗するは、数を返します。` | The trailing 「を 返す」 / 「を 返します」 ("returns …") of a function's type declaration is decoration for readability (same as `… は 数`) |
| `挨拶する は 数 を 返す 動作`, `… は 数 を 返す 入出力動作` | The type 「数 を 返す 動作」 ("action returning a number") is the same as 「数 の 動作」. 「入出力動作」 ("IO action") is another name for 「動作」 |
| `… とは 入出力手順` + deeper lines / `入出力手順（文。文。）` | A procedure of actions (IO) only. A value that is not an action is a type error |
| `… とは、本体。ただし、合計とは、a+b。` | 「ただし」 ("where") adds local definitions to the definition just before |
| `（合計とは、a+b。合計/2）` | A block of sentences separated by 「。」 inside parentheses (the last sentence is the value) |
| `『おやつの数』` | A name containing hiragana (enclosed in 『』) |
| `点 とは 横 と 縦 の 組` | Defining a record (named tuple) type |
| `図形 とは 半径 の 円 か 幅 と 高 の 長方形`, `信号 とは 赤 か 黄 か 青` | A type with alternatives (shapes listed with 「か」, "or") |
| `3 と 4 の 点` / `横 は 3 で 縦 は 4 の 点` | Building a record (positional / named) |
| `p の 横`, `横 は 10 の p` | Reading a field, making a new record with one field changed |
| `もし 形 が` + deeper lines like `半径 の 円 ならば …` | Pattern matching (case analysis) |
| `…、2 ならば 「b」 以上です、…` | 「以上」 closes the innermost case analysis (when nesting on one line) |
| `先頭 は x で 残り は 他 ならば …` | Splits a non-empty list into its head and rest |
| `半径 の 円 かつ 半径 > 10 ならば …` | A pattern condition (guard) |
| `（s という JSON文字列） を …`, `半径 という 円 ならば …` | In patterns, 「の 形名」 can also be written 「という 形名」 |
| `0 を 階乗する とは 1` + `n を 階乗する とは …` | Case-by-case function definitions (patterns in the parameters, tried from the top) |
| `比較可能 という 性質 とは …` / `点 は 比較可能` | Defining and implementing a trait (type class) |
| `x を 表示する`, `入力する` | Make actions (side effects). Written at the top level, they are carried out |
| `手順（文。文。…）` / `… とは 手順` + deeper lines | Carry out sentences in order (do notation). The last sentence is the action of the whole |
| `… とは 以下の手順です` + sentences + `以上` | A procedure written with a closing word. 「以上」 is required. `以下の入出力手順です` too |
| `名前 とは 入力した 結果` | Inside a procedure, carry out an action and name its result (bind) |
| `入力してから 表示する` | Pass the previous action's result to the next function's 「を」 (bind) |
| `（入力する） の 結果 を 数値にする` | Apply a function to an action's result (map) |
| `x を 結果にする` | An action that does nothing and has x as its result (pure / return) |
| `…。それから、…。` | Carry on after the previous sentence ("and then") |

### Built-in functions

| Call | Meaning |
|---|---|
| `x を 表示する` | An action that prints x (its result is x) |
| `x を 続表示する` | An action that prints without a newline (its result is x) |
| `入力する`, `「質問」 を 入力する` | An action that reads one line (its result is a string). With 「を」, prints it first |
| `「12」 を 数値にする` | Turns a string into a number (full-width digits are fine; an error if it isn't a number) |
| `動作のリスト を 実行する` | An action that carries out actions in order (its result is the list of results) |
| `x を 結果にする` | An action that does nothing and has x as its result |
| `m を f で 連鎖する` | Carries out m and passes the result to f (a function of the trait 「連鎖可能」, chainable; for lists it joins the results of f) |
| `x を 絶対値にする` | Absolute value |
| `xs を 加算する`, `x を y に 加算する` | Sum (if 「を」 is a list, adds everything; 「に」 can be left out) |
| `xs を 乗算する`, `x を y に 乗算する` | Product |
| `a から b を 減算する` | a - b |
| `a を b で 除算する` | a / b |
| `x を リスト に 追加する` / `挿入する` | The list with x added at the end / front |
| `関数 を x に 適用する` | Applies the function to x (without 「に」, calls it with no arguments) |
| `リスト から 関数 で 選別する` | The list of elements for which the function returns 真 (filter) |
| `リスト を 関数 で 写像する` | The list with the function applied to each element (map). A function of the trait 「写像可能」 (mappable), so it works on actions too |
| `リスト を 初期値 から 関数 で 畳み込みする` | Left fold |

If you define a function with the same name as a built-in, your definition is used.

## Decisions (points the spec left open)

1. **Arguments are distinguished by case particles.** The particles are 「を・に・で・から・へ・より」. A function can use each particle at most once (a second one is an error, both in definitions and calls). Missing arguments, or particles the function does not take, are errors.
2. **Particles may be attached to the function name.** `を加算する` and `を 加算する` are the same, as are `で除算する`, `を返すこと` and so on. **Function names made only of hiragana are not allowed** (`へんかんする` is an error; there must be a kanji or katakana before 「する」).
3. **「…して」 is function composition (a pipeline).** The previous result goes into the next function's 「を」. When the next segment also has a 「を」 argument, the two become **a list with the previous result first**. `引数 と 引数 を加算して 引数 を加算する` is `加算(を = (加算(を = (引数, 引数)) と 引数))`. An expression always ends with 「…する」 (ending with 「…して」 is an error).
4. **「と」 builds a list.** `1 と 2 と 3` is a three-element list. Arithmetic and comparison bind tighter than 「と」, so `1 + 1 と 2 * 3` is `（2 と 6）`. A one-element list is made with `1 を 空 に 追加する`. Lists are immutable values and print as `（1 と 2 と 3）`.
5. **「a と b を」 in a definition destructures a list.** If the list passed in has the wrong length, it is an error. This keeps the first example, `a と b を加算する とは a + b`, working as before.
6. **The reading comma 「、」 is the separator of the punctuation style, and the middle dot 「・」 is reserved.** 「、」 is not used to separate list items (see item 20 onward). 「・」 outside a string is an error.
7. **After 「の」 comes a list property or a field name.** 先頭・残り・最後・長さ・それぞれ (head, rest, last, length, each) are list properties; any other name is a record field (`p の 横`). It binds tighter than arithmetic (`リスト の 先頭 + 1` is `(リスト の 先頭) + 1`). Only when the name after 「の」 is the name of a type's shape does it mean building a record, and the binding changes (item 28).
8. **「が」 tests equality.** `リスト が 空` is the same as `リスト == 空`. A 「が」 right after 「もし」 becomes pattern matching, but when the patterns are just values the meaning is the same (item 31).
9. **「〜すること」 is a function value.** A 「こと」 at the end of a segment takes the arguments before it and becomes a partial application (`1 を 加算すること`). A 「こと」 followed by a particle is itself an argument of the outer call, and the arguments before it belong to the outer call (in `リスト を 0 から 加算すること で 畳み込みする`, `0 から` is an argument of 畳み込み). To pass a partially applied function to an outer argument, wrap it in parentheses: `5 に （1 を 加算すること） を 適用する`.
10. **Passing values to a function value fills the not-yet-given arguments in definition order.** For built-ins, the order is the one in the table (for 加算する, を then に). If required arguments remain, the result is again a partial application. In a fold, a function with two or more required arguments receives the "accumulator" and the "element" separately, and a function with one receives them as the list `（累積値 と 要素）`.
11. **「それぞれ」 applies to one call only.** `リスト の それぞれ を 三倍する` returns the list of tripled results. With two 「それぞれ」 in the same call, the elements at the same positions are paired (different lengths are an error). `リスト の それぞれ` written anywhere other than a call argument is just the list.
12. **Anonymous functions** are `x を 受け取って 本体 を 返すこと`. Parameters are written as in a definition (`a と b を 受け取って` also works, and a and b may have different types). They capture outer variables (closures). Wrap one in parentheses when it comes before other arguments.
13. **Reserved names.** Words ending in 「する」, 「して」 or 「すること」 are always treated as functions, so they can't be variable names. `と` `とは` `の` `が` `を` `に` `で` `から` `へ` `より` `もし` `ならば` `そうでなければ` `受け取って` `返すこと` `ただし` `か` `は` `という` `組` `性質` `それから` `かつ` `または` `読み込む` `読み込んで` `使う` `真` `偽` `空` `以上` are also reserved (`以下の手順` and `以下の入出力手順` are read as one word too). Words ending in 「…した」 (`入力した`) and words ending in 「…してから」 are function calls too. Words ending in 「…である」, 「…でない」 or 「…であること」 are predicate calls (item 47). `結果` and `手順` are not reserved; they have a special meaning only in fixed positions (item 36 onward).
14. **Arithmetic binds tighter than calls.** To use a call's result in a calculation, wrap it in parentheses: `( 1 と 2 を加算する ) * 3`.
15. **In the spaced style, tokens are separated by spaces.** Writing `a+b` packed together makes it one name. As exceptions, parentheses and 「」『』 separate tokens even when packed. To write packed, use the punctuation style ("Punctuation style" below).
16. **The off-side rule.** The indentation width at the start of a line decides the structure (a half-width space = 1, a full-width space = 2, a tab = 4).
   - When a line ends with 「とは」, the following deeper lines form the body block. A block can hold local definitions, and **the expression on its last line is the value**.
   - When the body is written on the same line after 「とは」, or when deeper lines follow an ordinary expression line, the deeper lines **continue** the expression.
   - A line at the same depth starting with `ならば` / `そうでなければ` is taken as a continuation of the previous line (so conditionals can be laid out vertically).
   - A line whose depth matches no earlier block is an error.
17. **Definitions can come in any order.** All top-level definitions are registered first, so a definition may come after where it is used, and mutual recursion works.
18. **Division.** Dividing integers gives an integer when it divides evenly, otherwise a decimal. Dividing by 0 is an error.
19. **Errors are in Japanese, with the line number and the column.** They look like `2行目 6文字目: 「存在しない数にする」は定義されていません` ("line 2, column 6: 「存在しない数にする」 is not defined"); when running a file or in interactive mode, the line itself and a marker (`^`) under the position are shown too. Full-width characters count as two columns when placing the marker. A runtime error points at the start of its expression (for arithmetic, the operator).

### Punctuation style

1. **A line containing 「。」 or 「、」 uses the punctuation style.** Sentences starting on that line end with 「。」. A sentence may span line breaks up to its 「。」 (indentation is free too), and a line may hold any number of sentences. Reaching the end without a closing 「。」 is an error. 「、」 is a separator just like a space; it may go anywhere and has no meaning except as the separator between cases of a pattern match (item 31) (it reads well after `とは、` or `して、`). 「。」 and 「、」 inside strings don't count. Lines without 「。」 or 「、」 keep the spaced, indented style, so both styles can be mixed in one file.
2. **Words are split where the kind of character changes.** A run of kanji, katakana or Latin letters is a name (digits after Latin letters continue the name: `x1`), a run of digits is a number, and a run of symbols is an operator. A run of hiragana is split into particles (を・に・で・から・へ・より), keywords (と・とは・の・が・もし・ならば・そうでなければ・それぞれ・ただし・か・は・という) and 「する/して/すること」. `長さ` `残り` `受け取って` `返すこと` and the built-in `畳み込み` contain hiragana but are read as fixed words.
3. **A function name is the name right before 「する」.** `リストを三倍する` is `リスト を 三倍する`. Any part of the same hiragana run before 「する」 goes into the function name (`三倍にする`, `絶対値にする`).
4. **Names are written in kanji, katakana and Latin letters.** Hiragana such as okurigana can't be told apart from particles, so a name containing hiragana is enclosed in 『』, like 『おやつの数』 (「」 already means a string, so 『』 was chosen). A function name with hiragana mixed in can be written like 『割った数に』する (the same function as `割った数にする` in the spaced style).
5. **Names made only of hiragana are errors.** In either style, defining a hiragana-only name (`するめいか とは 3`, `あ を 受け取って …`) gives an error suggesting to use kanji or katakana or to enclose it in 『』. Enclosed in 『』, a hiragana-only variable name is fine, but **a hiragana-only function name is not allowed even in 『』**.
6. **Local definitions are added with 「ただし」.** In `aとbを平均するとは、合計/2。ただし、合計とは、a+b。`, the 「ただし」 sentence becomes a local definition inside the preceding (non-ただし) definition. You can write as many in a row as you like. The spaced style can use it too, as a line `ただし 合計 とは a + b`. 「ただし」 after a sentence that is not a definition is an error.
7. **Sentences can be listed inside parentheses.** If there is a 「。」 or 「とは」 inside parentheses, they are read as a sequence of sentences separated by 「。」 (a block), and the value of the last sentence is the value of the parentheses: `（積とは、a*b。積^0.5）`. Use this for local definitions inside local definitions, or to name something in the middle of an expression.
8. **「もし」 needs no closing.** 「もし … ならば … そうでなければ …」 always has both branches, so even nested, the boundaries are unambiguous. What follows 「そうでなければ」 runs to the end of the sentence (or a closing parenthesis), so wrap it in parentheses to end it earlier. Case analysis by pattern matching (item 31) may leave out 「そうでなければ」 when all shapes are covered.

### Records, pattern matching and traits

1. **Record types are defined with 「… の 組」, and types with alternatives with 「か」.** `点 とは 横 と 縦 の 組` is a type 「点」 ("point") with 横 and 縦 (the shape is also named 「点」). `図形 とは 半径 の 円 か 幅 と 高 の 長方形` is a type taking the shape of either a circle or a rectangle. Listing only shapes without contents gives an enumeration (`信号 とは 赤 か 黄 か 青`; `赤` is a value as it is). Type definitions go at the outermost level and may come after any use. Type names, shape names and field names follow the same rules as variable names (in 『』 if they contain hiragana), and a shape name can belong to only one type in the whole program. A field name equal to a type or shape name is an error.
2. **Building records.** Positionally `3 と 4 の 点`, with names `横 は 3 で 縦 は 4 の 点` (any order; all fields are required). **「… の SHAPE」 applies to the whole of the values listed with 「と」 on its left** (`3 と 4 の 点` is `（3 と 4） の 点`). So to list records with 「と」, wrap them in parentheses: `（1 と 2 の 点） と （3 と 4 の 点）` (without them you get an error with a hint). Passing one list, as in `（3 と 4） の 点`, also works. The 「で」 after `名前 は 値` is read as continuing the record only when another `名前 は` follows.
3. **Records are immutable values.** Read a field with `p の 横`, and make a new record with only 横 changed with `横 は 10 の p` (p stays as it was). Records with the same contents are equal under `が`. They print as `（横 は 3 で 縦 は 4 の 点）`, which can be written back as is.
4. **Pattern matching is 「もし 値 が パターン ならば …」.** After `もし 形 が`, list `パターン ならば 式` on deeper lines (separated by 「、」 in the punctuation style); the first case that matches, from the top, is used. A final `そうでなければ …` matches everything else. A single case can be written on one line: `もし 形 が 半径 の 円 ならば 半径 そうでなければ 0`. Wrap a case body in parentheses to continue the expression past a separator, or to put another case analysis inside it.
   - Only the names in a pattern's `… の SHAPE` and `名前 は …` become new variables, usable in that case's expression. `空`, numbers, strings, `真`/`偽`, shapes without contents (`赤`), existing variables and values like `a と b` test for equality (so the old `もし xs が 空 ならば …` keeps its meaning).
   - Nesting uses parentheses: `（x と y の 点） と r の 円`. Using the same name twice is an error.
   - `先頭 は x で 残り は 他` splits a non-empty list into its head and rest. Named patterns may leave out `の SHAPE`, and then they match "any value that has those fields".
   - If a case analysis over a type with alternatives misses a shape and has no `そうでなければ`, loading gives the error 「「長方形」の場合がありません」 ("there is no case for 「長方形」"). A value that matches nothing is a runtime error.
5. **Traits (type classes) are defined with 「… という 性質 とは」.** On deeper lines, list function declarations (without bodies: `a と b を 比較する`) and default implementations (`… とは …`). In the punctuation style, add them with 「ただし」, as in `比較可能という性質とは、aとbを比較する。ただし、…とは、…。` (declarations without bodies may follow 「ただし」 too).
6. **A trait is implemented with 「型 は 性質」.** On deeper lines under `点 は 比較可能` (「ただし」 in the punctuation style), define the functions for that type. The particles must match the declaration. Leaving a declared-only function undefined is an error. The built-in type names are `数` (number), `文字列` (string), `真偽` (boolean), `リスト` (list) and `関数` (function).
7. **Which implementation is used depends on the type of the 「を」 value.** For a function that destructures 「を」 as `a と b`, it is the type of the first element (for a function without 「を」, the first argument). Calling with a type that has no implementation gives 「「文字列」は性質「比較可能」を持っていません」 ("「文字列」 does not have the trait 「比較可能」"). Like ordinary functions, a trait's function can be made a value with `比較すること`. Trait functions and shape names without contents can't be overridden by other definitions.
8. **The built-in trait 「表示可能」 (showable).** Its single function is `x を 文字列化する`, and every type has it without implementing it (it returns the usual printed string). If you implement it, `表示する`, printing top-level results and printing inside lists use it.

### Actions (side effects) and procedures

1. **Side effects are values called 「動作」 (actions).** `x を 表示する` and `入力する` do nothing on the spot; they return an **action** that prints or reads. If the value of a top-level sentence is an action, it is carried out there (its result is not printed). Values that are not actions are printed as before. The type name of actions is `動作`. An action that is made but not used, as in `（「a」 を 表示する） と 1`, is not carried out.
2. **「…してから」 is bind.** `入力してから 数値にして 表示する` reads input and passes the result to the 「を」 of 「数値にして 表示する」. Everything after 「してから」 is a continuation receiving the previous result. If the previous result is not an action, it is an error (use 「して」 for pure values). If the continuation returns a value that is not an action, that becomes the result of the whole.
3. **「手順（文。文。…）」 is do notation.** It carries out the sentences from the top, and the last sentence is the action (value) of the whole. In the spaced style, list the sentences on deeper lines after `挨拶する とは 手順`. Sentences in the middle of a procedure must be actions (a sentence that only computes a value is an error). When a line with only 「手順（」 is followed by punctuation-style lines, those lines are read in the punctuation style too. Calling yourself in a procedure's last sentence gives a loop (`n + 1 を 数え上げする` at the end of `n を 数え上げする とは 手順`). A loop that carries out an action such as printing or input on each round can go on any number of times, both in the interpreter and when compiled (the shape of a server's accept loop).
4. **「…した 結果」 is the result of carrying out an action inside a procedure.** `名前 とは 入力した 結果` names the result (with 「とは」, as in ordinary definitions). It is a noun, so it can go anywhere in a procedure's sentence, as in `入力した結果を数値にして、表示する。`, and the ones written earlier in the sentence are carried out first. Writing it outside a procedure, in a function body or a branch of 「もし」, is an error (wrap that part in 「手順（…）」). To use it in arithmetic, wrap it in parentheses: `（入力した結果）+1`.
5. **「の 結果」 is map.** `（入力する） の 結果 を 数値にする` is an action that turns the input's result into a number (the same shape as 「の それぞれ」, which calls for each element of a list). It can only be written as a call argument. Written on two or more arguments, they are carried out from the front. For a record with a field named `結果`, it is still a field access.
6. **「。それから、」 carries on.** `「やあ」を表示する。それから、「またね」を表示する。` is one sentence that does the two in order. Written after a definition, it continues the body (it attaches to the sentence just before, like `ただし`). In the spaced style, write it as a line `それから …`.
7. **The traits 「写像可能」 (mappable) and 「連鎖可能」 (chainable).** These are built-in traits: `写像可能` has `m を f で 写像する`, and `連鎖可能` has `m を f で 連鎖する` and `x を 結果にする`. Lists and actions implement them (chaining a list joins the results of f). For your own type, declaring `『たぶん』 は 連鎖可能` and defining `連鎖する` lets you use procedures, 「してから」 and 「の 結果」 with it. `結果にする` can't choose by the type of 「を」, so it always makes a "do nothing" action and adapts to the other side's type when chained (if `x を 結果にする` is defined for that type, that one is used).

### Case-by-case function definitions and pattern conditions

1. **A pattern condition uses 「かつ」.** In a case analysis, `パターン かつ 条件 ならば 式` uses that case only when the pattern matches and the condition is 真. The condition can use the names bound by the pattern (`半径 の 円 かつ 半径 > 10 ならば …`). If the condition is 偽, matching moves on to the next case. Cases with conditions don't count when checking whether all shapes are covered (item 31).
2. **「かつ」 and 「または」 compute booleans.** They bind weaker than comparison and tighter than 「と」, and 「かつ」 binds tighter than 「または」 (`a または b かつ c` is `a または （b かつ c）`). If the left side decides the result, the right side is not computed. Both sides must be 真 or 偽, otherwise it is an error. A 「かつ」 right after a pattern is read as the start of a condition, so `もし n が 0 かつ m > 1 ならば …` means "if n is 0 and also m > 1" (either reading gives the same result).
3. **Writing values or shapes as parameters defines a function case by case.** As in `0 を 階乗する とは 1`, a pattern (a number, a string, `空`, `真`/`偽`, a shape without contents, `… の SHAPE`, `名前 は …`) can stand in place of a parameter name. Shapes that need parentheses are wrapped, as in `（r の 円） を 面積にする`. Only the names in a pattern are new variables, and a parameter that is just a name matches any value. `a と b を` still splits a two-element list, but inside case-by-case definitions a different length moves on to the next definition.
4. **Definitions of the same function are written in a row and tried from the top.** Consecutive definitions of the same name form one function; a call uses the first definition all of whose parameters match. All definitions use the same particles (otherwise it is an error). Another definition after one whose parameters are all plain names is an error (it would never be used). If there is one parameter and it is a case analysis over shapes, a missing shape gives the error 「「面積にする」に「長方形」の場合の定義がありません」 ("「面積にする」 has no definition for the 「長方形」 case") at load time, and a value matching nothing is a runtime error. Defining the same function again somewhere else is an error. This works in local definitions (ただし) and trait implementations too.

### Predicates

1. **A name ending in 「…である」 is a predicate.** As in `n が 偶数である とは n % 2 が 0`, it is a function that takes its subject with 「が」 and returns true or false (it may take arguments with other particles too: `a が b で 割切である`). Returning anything other than a boolean is a runtime error. The naming rules are the same as for 「する」 functions: there must be a kanji or katakana before 「である」.
2. **Calls are 「…である」 and 「…でない」, the value is 「…であること」.** `4 が 偶数である` is 真, and `3 が 偶数でない` is the negation (「でない」 works without being defined; defining 「…でない とは」 is an error). `偶数であること` is the predicate itself, like 「すること」, and can be passed as in `リスト から 偶数であること で 選別する`. Partial application works too.
3. **The 「が」 before a predicate is the subject.** Reading on after 「が」, if the call ends in a predicate, that 「が」 is the subject particle. Otherwise it is equality as before (`リスト が 空` is unchanged). `もし n が 偶数である ならば …` can be written as it is. The result of 「…して」 goes into 「が」 rather than 「を」 for a predicate (`5 を 三倍して 偶数である`).
4. **Predicates are joined with 「かつ」 and 「または」.** Conditions containing calls are joined the same way, as in `n が 正である かつ n が 偶数でない` (the same binding strength as item 44). They can be written in pattern conditions (item 43) too.

### Type checking

1. **Types are always checked before running.** `python3 suru.py FILE` first looks for type errors and, if it finds any, prints them without running anything. Types are inferred without being written (Hindley–Milner). `--検査` only checks and does not run, and `--検査なし` runs without checking (for trying code that runs but doesn't pass the type check, such as a list mixing types). Interactive mode checks types for every input too ("Interactive mode").
2. **Type names.** `数`, `文字列`, `真偽`, `数 の リスト` (list of numbers), `文字列 の 動作` (action of a string), records and types with alternatives by their type names, and functions are shown as `（数 を 受け取って 数 を 返すこと）`. Types not yet determined are 甲・乙・丙 … (like a, b, c).
3. **List elements must have the same type.** `1 と 「a」` is an error. Use a record or a type with alternatives to group values of different types.
4. **「+」 works between values of the same type.** Numbers, strings and lists can be added only to the same type. To join a number to a string, use `（x を 文字列化する）` (at runtime, joining still works as before). Ordering comparisons such as `<` are between numbers, and `が`/`==` between the same type.
5. **Calls are checked particle by particle.** Particles the function does not take, missing arguments and arguments of the wrong type are errors before running. When passing a function value (`三倍すること`), arguments are matched by order, not by particle. `加算する` is checked specially: it adds everything if 「を」 is a list, and adds two values if 「に」 is present.
6. **Definitions are polymorphic.** `x を 恒等にする とは x` can be used for numbers and strings alike. Outermost and 「ただし」 definitions that call each other are inferred together. Calls to themselves or to each other have their argument types checked too.
7. **Trait functions are checked against the implementing type (stage 2).** A call of a trait function such as `a と b を 比較する` is matched against the type of that type's implementation (or the default implementation) once the type of the 「を」 value (decided as in item 34) is known. Calling with a type without an implementation gives 「文字列は性質「比較可能」を持っていません」. A polymorphic function using a trait function (`a と b を 大きい方にする`) gets a type with the condition "any type that has this trait", checked where it is called. An implementation of `表示可能`'s `文字列化する` must return a string.
8. **Type conditions are also checked where they are called.** A polymorphic function restricted to certain kinds of types, such as `x の 長さ` (a string or a list) or `a + b` (a number, string or list), carries that restriction in its type, and it is checked at the call site (`「測る数にする」に渡した値: …`).
9. **Your own types take type parameters (stage 3).** You write them as before, and the type of each field is inferred. `（1 の 在）` is `数 の たぶん` and `（「a」 の 在）` is `文字列 の たぶん` (values of the type `『たぶん』` in 『』), and both can be used in the same program (with two or more fields, `（数 と 文字列） の 点`). Put in the same list, though, their contents must have the same type.
10. **Types that contain themselves.** A field holding the type itself (or a list of it), like 「左」 and 「右」 in `木 とは 値 と 左 と 右 の 節 か 葉`, is not a type parameter but "that type" (`数 の 木`). This is not decided from the definition; when inference finds the type would go on forever, that field is made that type and inference is redone.
11. **Fields always used with the same type are shown by the type name only.** For a type whose fields are used in only one way, like 「半径」 always used as a number in the program, errors show `図形` rather than `（数 と 数 と 数） の 図形`. Parameters that can be any type are left out too.
12. **Action types (stage 3).** `「?」 を 入力する` is `文字列 の 動作`, `x を 表示する` is an action, and `動作のリスト を 実行する` is an action of the list of results. `… してから …`, `… した 結果` in procedures and sentences in the middle of procedures are checked by making sure the previous value is an action (or a chainable type) and passing its result type on to the continuation (`入力してから 三倍する` gives 「「三倍する」の「を」には数が必要ですが、文字列が渡されています」, "「三倍する」's 「を」 needs a number, but a string is passed"). If the last value of a procedure is not an action, it becomes a do-nothing action.
13. **`結果にする` takes the type of what it is chained with.** `x を 結果にする` has the type "x made into a result", and it unifies with actions, lists or your own chainable types as long as the result type matches the type of x (if your type defines `結果にする`, it is checked with that type).
14. **`の 結果`, `写像する` and `連鎖する` are type-checked too.** Besides lists and actions, your own types implementing `写像可能` or `連鎖可能` are checked with the types of their implementations (`連鎖する`, `写像する`). Using them on a type with neither gives an error such as 「数は性質「写像可能」を持っていません」. Computing on an action directly with `+` and the like gives an error telling you to use 「…してから」 or 「の 結果」.

### Polite sentence endings

1. **「します」 and 「しまして」 are the same as 「する」 and 「して」.** `5を三倍します。` means the same as `5を三倍する。`, and `5を三倍しまして、表示します。` the same as `5を三倍して、表示する。`. 「しましてから」 is the same as 「してから」. Both styles accept them (in the spaced style, `5 を 三倍します`). Function names still end in 「する」, and definitions can be written as `n を 三倍する とは …` (writing `n を 三倍します とは …` is fine too).
2. **A sentence-final 「です」 is ignored.** A 「です」 written before 「。」, 「、」, 「）」 or 「そうでなければ」, or at the end of a line in the spaced style, as in `p とは 3 と 4 の 点 です。`, `x とは 7です。` or `もしn>0ならば「正」です、そうでなければ「負」です。`, is skipped as decoration. Anywhere else (`3 です と 4`) it is an error. 「です」 and 「ます」 are hiragana, so thanks to the rule that names containing hiragana go in 『』 (item 23), they never clash with names.

### Type declarations (stage 4)

1. **Types may be declared.** Before (or after) a definition, write type names in place of parameter names, and the value's type after 「は」: `数 を 階乗する は 数`, `税率 は 数`, `数 が 偶数である は 真偽`, `挨拶する は 数 の 動作`. In the punctuation style it is `数を階乗するは、数。`. Declarations are used only by the type checker and do not affect running. They are optional.
2. **How types are written.** `数`, `文字列`, `真偽`, `数 の リスト`, `文字列 の 動作`, functions as `（数 を 受け取って 数 を 返すこと）` (with several particles, `（数 を 数 で 受け取って 数 を 返すこと）`), and your own types as `点` (field types left to inference), `（数 と 数） の 点` or `数 の 『たぶん』` (type parameters are in field order; fields holding the type itself are not counted). If what follows 「は」 is a trait, as in `点 は 比較可能`, it is a trait implementation as before.
3. **A declaration that disagrees with the definition is an error.** Different particles in the declaration and definition, a different value type (「「税率」は文字列と宣言されていますが、数になっています」, "「税率」 is declared as a string, but it is a number"), a declaration without a definition, and declaring the same name twice are all errors. The declared type is also used for calls to itself inside the definition.
4. **甲 and 乙 mean "any type".** `甲 を 恒等にする は 甲` declares a function usable with any type. If 甲 turns into a specific type, for example because the definition only works with numbers, or 甲 and 乙 turn into the same type, it is an error. Declarations can only be written for outermost definitions.

### Loading files

1. **`「数学」 を 読み込む` loads `数学.suru` from the same folder.** Write it at the outermost level (`「数学」を読み込む。` in the punctuation style, `読み込みます` politely). The folder is searched from the folder of the file being run (subfolders can be written as `「部品/数学」`). File names are written in kanji, katakana and Latin letters, like variable names. The same file is read only once, however many times it is loaded. Loading that would end up loading the file itself is an error.
2. **Names inside are used as 「FILE内の NAME」.** The outermost definitions of a loaded file are used with the file name and 「内の」 ("inside") in front: `数学内の円周率`, `3 を 数学内の二乗する`, `数学内の二乗すること` (in the spaced style, `数学内の円周率` or `数学内の 円周率`). If 「数学」 is not loaded, `数学内` is an ordinary name. Writing `円周率` without the prefix does not refer to the loaded definition, so defining the same name in your own file causes no clash. Names from files that the loaded file loads in turn are not available; to use them, load that file too.
3. **Types, shapes and traits are used without 「内の」.** Types (`図形`), shapes (`（2 の 円）`), traits with their functions, and trait implementations defined in a loaded file can be used as they are. A type or shape name can belong to only one type in the whole program, loaded files included.
4. **Loaded files contain only definitions.** Any sentence other than definitions, types, traits, type declarations and loads (such as `x を 表示する`) is an error. Errors inside a loaded file are reported at the loading line, with the file name and line, as in 「「数学.suru」の2行目: …」 ("line 2 of 「数学.suru」: …"). Type checking covers loaded files too.

5. **`「数学」 を 読み込んで 使う` lets you use the names without a prefix.** Names inside can be used as they are, like `円周率` and `3 を 二乗する` (`数学内の円周率` also works). `「数学」を読み込んで使う。` in the punctuation style, `読み込んで使います` politely. If you define the same name yourself, your definition is used, and the loaded file's one is available as `数学内の…`. If two files loaded with 「読み込んで 使う」 have the same name, it is an error unless you define it yourself (load one of them with 「読み込む」 instead, or use the prefix).
6. **Files not found are looked up in the standard folder.** If a file is not in the folder of the file being run, it is looked up in the `lib` folder next to `suru.py`. This is how the standard library `lib/標準.suru` is loaded.

### Standard library

1. **`「標準」 を 読み込む` gives you the standard library.** Use it with the prefix, as in `標準内の逆順にする`; with `「標準」 を 読み込んで 使う` no prefix is needed. It is written in Suru in `lib/標準.suru` (with type declarations); only what can't be written in Suru, such as string operations, is built in. The built-ins too are available only when the standard library is loaded.
2. **Positions count from 1.** `xs から 1 を 番目取得する` is the first element. Out of range is an error.
3. **逆順にする, 先頭取得する, 先頭削除する, 番目取得する and 含有である work on strings too.** The elements of a string are one-character strings.

| Syntax | Result |
|---|---|
| `3.7 を 切捨する` / `3.2 を 切上する` / `2.5 を 四捨五入する` | 3 / 4 / 3 (floor / ceiling / round) |
| `16 を 平方根にする`, `7 を 2 で 商にする` | 4, 3 (the remainder is `7 % 2`) |
| `3 と 7 と 5 を 最大値にする` / `最小値にする`, `2 と 4 を 平均する` | 7 / 3, 3 |
| `1 から 5 を 範囲にする` | （1 と 2 と 3 と 4 と 5） |
| `n が 偶数である` / `奇数である` / `正である` / `負である` | True or false (even / odd / positive / negative) |
| `xs を 逆順にする` | Reversed |
| `xs から 3 を 先頭取得する` / `先頭削除する` | The first 3 / the rest without the first 3 |
| `xs から 2 を 番目取得する` | The 2nd element |
| `xs が x を 含有である` | Whether x is an element (for strings, whether it contains the substring) |
| `xs から x を 除去する`, `xs を 一意にする` | The list without x, the list without duplicates |
| `xs を 整列する` | In ascending order (a list of numbers or a list of strings) |
| `xs を f で 基準整列する` | In ascending order of the number or string f gives for each element |
| `（1 と 2） と （3 と 4） を 連結する` | （1 と 2 と 3 と 4） |
| `xs から 偶数であること で 計数する` | The number of matching elements |
| `xs が 偶数であること で 全部真である` / `一部真である` | Whether all / any match |
| `0 を 3 で 複製する` | （0 と 0 と 0） |
| `「abc」 を 文字分解する` | （「a」 と 「b」 と 「c」） |
| `「a,b」 を 「,」 で 分割する`, `xs を 「,」 で 結合する` | （「a」 と 「b」）, 「a,b」 (split, join) |
| `s を 「a」 から 「b」 へ 置換する` | The string with every 「a」 replaced by 「b」 |
| `s を 大文字にする` / `小文字にする` / `空白除去する` | Upper case / lower case / the string with leading and trailing spaces removed |
| `s が 「ab」 で 先頭一致である` / `末尾一致である` | Whether it starts / ends with 「ab」 |
| `「aあ」 を バイト数にする` | 4 (the number of bytes in UTF-8) |
| `12354 を 文字にする` / `「あ」 を 文字コードにする` | 「あ」 / 12354 |
| `m を 代わり で 試行する` | An action that carries out m and, if a runtime error occurs, writes the error message to standard error and carries out 代わり instead (both are actions) |
| `改行`, `復帰改行` | A newline character, and the two characters carriage return and newline (they can't be written inside 「」, so they are used by name) |

### Compiler

1. **`python3 suru.py --翻訳 prog.suru` builds an executable.** `suru_compile.py` turns the Suru program into LLVM IR, and clang makes it, together with the runtime library (`runtime/suru_rt.c`), into one executable `prog`. `-o NAME` sets the output name, and `--ll` emits only the LLVM IR (`prog.ll`) (`python3 suru_compile.py --ll prog.suru`). `CC` selects a different clang.
2. **The results are the same as the interpreter's.** It compiles after type checking (`--検査なし` turns that off). Every construct works: loading, the standard library, traits, actions and procedures, case-by-case definitions and so on. Runtime errors have the same messages as the interpreter, with exit code 1. The tests (`tests/test_compile.py`) compile the example programs and others and check that the output matches the interpreter's.
3. **Fast, and deep recursion works.** Functions become machine-code functions, and integer arithmetic is done inline. Recursion runs on a 1GB stack, so depths at which the interpreter stops (such as 300,000 levels) work.
4. **Differences from the interpreter.** Integers go up to ±4611686018427387903 (2^62 − 1); beyond that you get the error 「整数が大きすぎます」 ("integer too large") (the interpreter can go arbitrarily large). `大文字にする` / `小文字にする` change only Latin letters (half-width and full-width). Memory no longer in use is cleaned up by a GC (conservative mark-and-sweep). Every value on the stack or in registers that might point to an object is treated as in use, and objects are never moved (the 「メモリ」 section of `runtime/suru_rt.c`). It runs every 8MB allocated, or every time twice the amount left last time has been allocated. `SURU_GC_LOG=1` prints the amount left after each GC, and `SURU_GC_MIN=KB` changes the lower limit of the interval (`0` runs it on every allocation, for testing). There is no interactive mode.

### Distribution

1. **It can be installed with pip.** `pip install .` (or the GitHub URL) installs the `suru` command. It contains three modules, `suru.py`, `suru_check.py` and `suru_compile.py`, plus `lib/` and `runtime/` placed in `suru_data/`. Running `python3 suru.py` straight from the repository still works (`data_path` looks for `lib/` next to it or for `suru_data/lib/`). The version is written in `__version__` in `suru.py`. Packaging uses hatchling (`python -m build` makes the wheel and sdist).

2. **The license is split in two.** The interpreter, type checker and compiler (`suru.py`, `suru_check.py`, `suru_compile.py`) are GPL-3.0-or-later (`LICENSE`). The runtime library (`runtime/`) and the standard library (`lib/`) are MIT (`runtime/LICENSE`, `lib/LICENSE`). These two end up inside compiled programs and Suru programs, so they are MIT to keep the GPL from reaching the programs you make.

### The Go compiler

1. **The Go compiler `suruc`.** `compiler/` (lexing, parsing, type checking, IR generation) and `cmd/suruc/` (calling clang) are written in Go and produce the same IR and the same error messages as the Python version. `tests/test_go_compiler.py` checks that the output matches the Python version for the examples and every program written in the tests (including ones that are errors) (it is skipped when go is not installed). When the Python version is fixed, fix the Go version the same way.
2. **Type checking takes time proportional to the number of lines.** The Python version scanned the types of all earlier definitions each time it inferred one, so it took time quadratic in the number of definitions. The Go version remembers and reuses the free type variables in the environment (rebuilding only when a type variable that was generalized gets determined later). For an 8,000-line program, checking went from 10.2 seconds to 0.03 seconds.
3. **Most of the time is clang.** For an 8,000-line program, getting to the IR takes 13.6 seconds in the Python version and 0.4 seconds in the Go version, and getting to the binary takes 28 seconds → 18 seconds (-O2) / 2.4 seconds (-O0). The next step to cut clang's time is to make the IR smaller.

### Networking

1. **`「通信」 を 読み込む` gives you TCP networking.** There are eight built-ins, all returning actions. Listeners and connections are represented by numbers starting from 1 (the same numbers in the interpreter and compiled programs).

| Syntax | Result (of the action) |
|---|---|
| `8080 を 通信内の待受開始する` | The listener number (listens on that port of 0.0.0.0) |
| `8080 を 「127.0.0.1」 に 通信内の待受開始する` | The listener number (listens only on that address; with `「127.0.0.1」`, only from the same machine) |
| `口 から 通信内の接続受付する` | The connection number (waits until the next connection arrives) |
| `接続 から 通信内の行受信する` | One line as a string (including the trailing newline; 「」 if the other side has closed) |
| `接続 から 100 を 通信内の受信する` | A string of up to 100 bytes (read as UTF-8) |
| `文字列 を 接続 へ 通信内の送信する` | The number of bytes sent |
| `バイト列 を 接続 へ 通信内のバイト列送信する` | The number of bytes sent (sends images and the like as they are) |
| `番号 を 通信内の切断する` | Closes a connection or listener (the result is the number) |

2. **Networking failures are runtime errors.** When the other side disconnects, for example, you get 「「送信する」で通信に失敗しました(Broken pipe)」 ("communication failed in 「送信する」 (Broken pipe)"). A number that is not open is an error. Compiled programs flush what has been printed so far before waiting for a connection and before receiving (so logs don't come out late).
3. **Built-ins belong to files in lib/.** `LIB_PRIMITIVES` in `suru.py` (`libPrimitives` in the Go version) decides which file each one is visible in. Inside the runtime library, the built-ins of the standard library and of networking share one table.
4. **Byte sequences are sent with `バイト列送信する`.** `送信する` sends a string as UTF-8, and `バイト列送信する` sends a byte sequence as it is (to return images over HTTP). The interpreter and compiled programs behave the same.

### HTTP

1. **The HTTP server moved out of the standard library to [suru-lang/http](https://github.com/suru-lang/http).** The main repository's `lib/HTTP.suru` is gone. In a project that uses it, add it with `kumu 追加 github.com/suru-lang/http` and write `「HTTP」 を 読み込む` as before (names such as `待受する`, `動作待受する`, `並行待受する` and `本文応答する` are unchanged). The HTTP client goes in that repository too.
2. **Static file serving of a whole folder lives in suru-lang/http.** `8080 を （「public」 を HTTP内の配信すること） で HTTP内の動作待受する` serves the files under public by path (Content-Type from the extension, %XX decoded, 403 outside the folder, index.html for folders, GET and HEAD). See that repository's README for usage.
3. **Response bodies became byte sequences.** To return images and the like, `本文応答する` and friends put strings into the body as UTF-8 bytes. `応答文にする` still returns a string.
4. **The main repository's tests use a copy of HTTP.suru.** `tests/http/HTTP.suru` is a copy from suru-lang/http, kept so the main tests can check that networking, threads, the GC and `試行する` really work as a server (answering 10,000 requests in a row, answering each connection in parallel, and so on). When HTTP.suru changes, update this copy to match.

### Foreign functions (calling C, C++ and Go)

1. **`外部の「m」 を 読み込む` and `… とは 外部の「cos」` call C functions.** The type declaration decides the C types, and the definition's body is `外部の「C NAME」` (外部の = "external"). Arguments are passed to C in the order written in the definition. libc functions (`strlen` and so on) can be used without loading anything. See `examples/ffi.suru`.

```
外部の「m」 を 読み込む
小数 を 小数 で 累乗する は 小数
x を y で 累乗する とは 外部の「pow」
2 を 10 で 累乗する                    # 1024
```

2. **Type mapping.** `数` is `int64_t`, `小数` is `double`, `整数` is `int`, `真偽` is `int` (0 or 1), `文字列` is `const char *` (UTF-8), `番地` is `void *`, `バイト列` is `const uint8_t *` (arguments only), and `無` is `void` (return values only). Inside Suru, `小数` and `整数` are the same type as `数`. `番地` ("address") is an opaque value, printed as `番地(0x…)` and comparable with `=`. Lists, records and functions can't be passed. A returned `int64_t` beyond ±2^62 is a runtime error (the integer range of compiled programs). A NULL string returned by C becomes 「」.
3. **If the value is an action, the call happens when it is carried out.** Declaring `数 を 加算記録する は 数 の 動作` makes a call only build an action, and the C function is called when it is carried out in a procedure or at the top level. With a non-action type, it is treated as a pure function called on the spot (whether it really has no side effects is up to whoever wrote the declaration).
4. **Library names.** A short name like `「m」` is looked up the way the OS looks it up (compiled programs link with `-lm`). A name containing `/` or ending in `.so` or `.dylib` is a path relative to the file (compiled programs link that file and load it from the same place at runtime).
5. **Calling your own C, C++ and Go.** Build C with `cc -shared -fPIC -o libあれ.so あれ.c`, C++ the same way with the exported functions marked `extern "C"`, and Go with `//export NAME` and `go build -buildmode=c-shared -o libあれ.so`, then use it with `外部の「./libあれ.so」 を 読み込む`.
6. **Implementation.** The interpreter uses Python's `ctypes`; the compilers (Python and Go) write `declare` into the IR, and values are converted by `rt_ffi_*` in the runtime library. A string passed to C is valid only during the call (keep anything C holds on to as a `番地`). Calling Suru functions back from C is covered in "Callbacks from C".
7. **Byte sequences.** An immutable sequence of bytes, printed as `バイト列（e3 81 82）` and compared by contents with `=`. Standard built-ins make and unpack them: `s を バイト列にする` (UTF-8), `（65 と 66） を バイト列組立する` (from a list of numbers 0 to 255), `b を 数列にする`, `b を 文字列にする` (a runtime error if it isn't UTF-8) and `b を バイト長にする`. A `バイト列` argument of a foreign function is `const uint8_t *` (pass the length as a separate argument; C must not modify it).
8. **Exchanging with C memory.** `n を 番地にする` and `p を 番地数値にする` convert between numbers and addresses (`0 を 番地にする` is NULL), `p から n を バイト列取得する` copies n bytes out of C memory, and `b を p へ 書込する` writes into it (both are actions). Memory is allocated by declaring `malloc` and `free` as foreign functions. For a C function without a value (`void`), declare the value type as `無` (it becomes 0 in Suru).
9. **Handling failure.** `エラー番号取得する` is an action whose result is the errno left by the foreign function called just before (it is set to 0 before the call). `文 を 失敗する` is an action that becomes a runtime error with that message, which `試行する` can catch. The standard `m を 「開くの」 で 失敗確認する` turns a negative return from a C function into the runtime error 「開くのに失敗しました(No such file or directory)」 ("failed to open (…)") (`e を エラー文にする` is strerror).

### Files and the environment

1. **`「ファイル」 を 読み込む` reads and writes files.** It is written in Suru in `lib/ファイル.suru` and calls C's stdio (`fopen`, `fread`, `fwrite` and so on) as foreign functions. All of these are actions.

| Syntax | Result (of the action) |
|---|---|
| `道 を ファイル内の読込する` | The whole file as a string (UTF-8) |
| `道 を ファイル内のバイト列読込する` | The whole file as a byte sequence |
| `道 を ファイル内の行分割読込する` | A list of line strings (without the trailing newlines) |
| `文字列 を 道 へ ファイル内の書出する` | The number of bytes written (the file is recreated) |
| `文字列 を 道 へ ファイル内の追記する` | The number of bytes written (appended at the end) |
| `バイト列 を 道 へ ファイル内のバイト列書出する` | The number of bytes written |
| `道 を ファイル内の存在確認する` | 真 if the file or folder exists |
| `道 を ファイル内のフォルダ確認する` | 真 if it is a folder (or a symbolic link to one) |
| `道 を ファイル内の読取可能確認する` | 真 if it is readable |
| `道 を ファイル内の実道取得する` | `有` of the absolute path with symbolic links and `..` resolved, or `無` if it doesn't exist (C's realpath) |
| `道 を ファイル内の削除する`, `道 を ファイル内のフォルダ作成する` | 0 (delete, make a folder) |

2. **Failures are runtime errors.** With messages like 「ファイル『a.txt』を開くのに失敗しました(No such file or directory)」, catchable with `試行する`. Paths (道) are relative to the current folder (not to the program's file).
3. **`「環境」 を 読み込む` gives access to the program's environment.** `環境内の引数取得する` (the list of a and b in `suru 例.suru a b` or `./例 a b`), `「HOME」 を 環境内の環境変数取得する` (「」 if unset), `3 を 環境内の終了する` (exits after flushing output), `「…」 を 環境内のエラー出力する` (one line to standard error), `環境内の今のフォルダ取得する` (current folder), and `環境内のOS名取得する` (the uname name, such as 「Linux」 or 「Darwin」). Only the arguments and exit are built-ins (the standard `引数取得する` and `終了する`); the rest are foreign functions.

### Arithmetic and random numbers

1. **`「算術」 を 読み込む` gives trigonometric, exponential and logarithmic functions.** It is written in Suru in `lib/算術.suru`, and the calculations call C's libm as foreign functions: `円周率` and `ネイピア数` (π and e), `x を 正弦にする`, `余弦にする`, `正接にする` (sin, cos, tan in radians), `逆正弦にする`, `逆余弦にする`, `逆正接にする`, `y を x で 偏角にする` (atan2), `双曲線正弦にする` and friends, `指数関数にする`, `自然対数にする`, `常用対数にする`, `x を 底 で 対数にする`, `x を y で 累乗する`, `立方根にする`, `度にする` and `ラジアンにする`, `a を b で 最大公約数にする` and `最小公倍数にする` (gcd, lcm), `n を 階乗する`, and `x を 符号にする` (sign). Outside the domain (`-1 を 自然対数にする`) the result is nan.
2. **`「乱数」 を 読み込む` gives random numbers.** Random numbers are pure functions of a "seed" (1 to 2147483646), and the same seed always gives the same value (in the interpreter and binaries alike): `s を 種更新する` (the next seed, MINSTD), `s を 一様にする` (at least 0 and below 1), `1 から 6 を s で 整数乱数にする`, `n を s で 乱数列作成する`, `xs を s で 混合する` (shuffle) and `xs から s で 選択する` (choose). For different values every run, make the first seed with `OS乱数取得する` (an action, getentropy). Don't use them for cryptography.

### Time and calendars

1. **`「時間」 を 読み込む` gives times and calendars.** It is written in Suru in `lib/時間.suru`. A time is the number of seconds (a decimal) since 1970-01-01 00:00:00 (UTC), and a date-time is the type `日時`, a record `年 と 月 と 日 と 時 と 分 と 秒 と 時差 の 組` (year, month, day, hour, minute, second and UTC offset; the offset is in seconds, 32400 for Japan). See `examples/time.suru`.

| Syntax | Result |
|---|---|
| `時間内の現在時刻取得する`, `t を 時間内の経過秒取得する` | The current time, seconds since t (actions, clock_gettime) |
| `0.5 を 時間内の待機する` | Waits 0.5 seconds (an action, nanosleep) |
| `t を 時間内の時差取得する`, `t を 時間内の現地日時取得する`, `時間内の現在日時取得する` | The UTC offset of this machine's region (`TZ`), the date-time at that offset (actions, localtime_r) |
| `t を 32400 で 時間内の日時にする`, `t を 時間内の世界日時にする`, `d を 時間内の時刻にする` | Converting between times and date-times (pure) |
| `（2026 と 11 と 22） を 時間内の日付作成する` | The date-time at 0:00 of that day (offset 0) |
| `2024 が 時間内の閏年である`, `d を 時間内の月日数にする` | Whether it is a leap year, the number of days in that month |
| `d を 時間内の曜日にする`, `d を 時間内の曜日番号にする` | 「日」 to 「土」 (Sunday to Saturday), 0 (Sunday) to 6 |
| `d を n で 時間内の秒数加算する`, `日数加算する`, `月数加算する`, `年数加算する` | The date-time moved forward by n (the end of a month is clamped: one month after January 31 is February 29 or 28) |
| `a から b を 時間内の日数差にする`, `a から b を 時間内の秒数差にする` | Difference in dates, difference in times |
| `d を 時間内の日付文字列にする`, `時刻文字列にする`, `国際書式にする` | 「2026-11-22」, 「19:31:12」, 「2026-11-22T19:31:12+09:00」 |
| `d を 「%Y年%m月%d日（%a）」 で 時間内の書式にする` | The string with %Y %m %d %H %M %S %a (weekday) %z (offset) replaced |
| `d を 時間内の和暦にする` | 「令和元年5月1日」 (Japanese era; before the calendar reform of Meiji 6, the Western year) |

2. **The calendar is pure arithmetic on the proleptic Gregorian calendar.** Adding days keeps the UTC offset as it is, so it doesn't cross daylight saving transitions (if needed, use `時刻にする` and then `現地日時取得する`). Time zone names (「JST」) and parsing date-times from strings are not available yet.

### Character classes and lexing (written in Suru)

1. **`「文字」 を 読み込む` checks the kind of a character.** `c が 文字内の平仮名である`, `片仮名である`, `漢字である`, `英字である` (half-width and full-width), `数字である` (half-width and full-width) and `空白である` (hiragana, katakana, kanji, Latin letter, digit, space), `c を 文字内の半角にする` (full-width letters, digits, symbols and the full-width space to half-width), and `s を 文字内の半角変換する`. It is written in `lib/文字.suru` with ranges of character codes.
2. **`「字句」 を 読み込む` lexes Suru programs.** `行のリスト を 字句内の字句解析する` returns a list of logical lines (`段`, `字句列`, `番号`, `閉`) using the same rules as `suru.py` (spaced style, punctuation style, indentation, 「です」). A token is a record with `種類` (kind: number, string, operator, open, close, name, reserved word, particle, call, period, separator), `値`, `行`, `桁`, `形`, `囲` and `否定`. Where `suru.py` would give an error, the token's kind is 「誤り」 (error) and the rest of that line (sentence) is not read. It is the base for writing the linter in Suru, and `tests/test_lexer.py` checks that it gives the same tokens as `suru.py` for the examples and every library file.

### Linter (「点検」, written in Suru)

1. **`suru --点検 FILE.suru …` points out code that is not an error but would read better if fixed.** It prints `FILE:LINE:COLUMN: RULE: DESCRIPTION`, and exits with code 1 if there is at least one. It is written in Suru in `lib/点検.suru` (and `lib/字句.suru`), and with clang available it is built into a binary only the first time and cached (`~/.cache/suru/`) (`SURU_LINT_INTERP=1` always runs it in the interpreter).

| Rule | What it reports |
|---|---|
| 行末の空白 (trailing space) | A space at the end of a line |
| 字下げの混在 (mixed indentation) | Indentation with a character different from the first one used for indentation in the file (half-width space, full-width space, tab) |
| 全角半角の混在 (mixed widths) | For each of parentheses, symbols and digits, the width (full or half) used less in the file |
| 丁寧語の混在 (mixed politeness) | When there are both sentences ending in 「する」 and in 「します」, the less common ones |
| 不要な二重かぎ (needless 『』) | A name without hiragana enclosed in 『』 |
| 字句の誤り (lexing error) | A line that fails lexing (`suru --検査` also reports it) |
| 未使用の定義 (unused definition) | A name defined but never used. Outermost definitions are checked only in programs (files with expression sentences at the outermost level), not in libraries. `x とは …` inside functions is always checked. A function that only calls itself counts as unused |
| 未使用の引数 (unused parameter) | A parameter not used in the function body. Functions split into several definitions, as with `先頭 は x で …` or `空 を …`, and `外部の「…」` functions are not checked |
| 未使用の読み込み (unused load) | `「X」 を 読み込む` with neither `X内の…` nor X's types used. With `読み込んで 使う`, none of the names in X used either (X is looked up in the same folder as the checked file or in lib/, and not checked if not found) |
| 組み込みの上書き (built-in override) | An outermost definition with the same name as a built-in function (`加算する` and so on) or a function in a file loaded with `読み込んで 使う` |
| 型の宣言なし (missing type declaration) | An outermost function in a library (a file without expression sentences at the outermost level) without a type declaration such as `数 を 三倍する は 数`. The declaration may be anywhere in the file |
| 書き方の混在 (mixed styles) | One file has both punctuation-style and spaced-style sentences. Reported once, at the first sentence of the less common style |
| 値の再定義 (value redefined) | The same value name is defined twice at the outermost level (the later definition is used). Functions are not checked, since they can be defined case by case |
| 定義の間の空行 (blank line between definitions) | A function definition at the outermost level (its type declaration and all its definitions) is followed on the very next line by another function's definition. Reported only when one of the two is two or more lines ("Blank lines between definitions (lint)") |

2. **Silencing reports.** Writing `# 点検しない` ("don't lint") at the end of a line, or on a comment-only line just before it, silences all reports for that line; `# 点検しない: RULE RULE` silences only those rules.
3. **It shows up in the editor too.** The language server `suru-ls` (VS Code extension) lints when a file is opened and saved, and shows the reports as warnings. A quick fix adds `# 点検しない: RULE` (clang is required). For an unsaved file, pass its contents as `suru --点検 --代わり CONTENTS_FILE REAL_PATH` to check them as the file at the real path.

### Parsing (written in Suru)

1. **`「構文」 を 読み込む` turns Suru programs into syntax trees.** `論理行群 を 形群 で 型群 に 構文内の構文解析する` reads a list of logical lines lexed by `lib/字句.suru` as a program and returns the list of outermost sentences as a `群解` (`群値` and `群読`). If it can't be read, `g が 構文内の群誤である` is true and `g を 構文内の群誤文にする` is the explanation. 形群 is the shapes of loaded files (records `形項` of `形名` and `形数`), and 型群 is the list of their type names; the types and shapes of the file itself are collected automatically. To read a single expression, use `字句群 を 形群 で 構文内の字句式解析する`. It is written in `lib/構文.suru` with the same rules as `suru.py`.
2. **The syntax tree is one type, 式.** Expressions are shapes such as `数式`, `名式`, `演式` (operations, 「かつ」 and 「または」), `呼式`, `参式` (すること), `関式` (受け取って), `若式` (もし), `場式` (case analysis), `作式` and `欄式`; patterns are `束型`, `型型`, `名型型` and so on; sentences are `定義式`, `塊式` (block), `順式` (procedure), `型定式`, `宣式` (type declaration), `性質式`, `実装式`, `読込式`, `公開式` and so on. Call arguments are `引式` (a particle and an expression). `e を 構文内の式表示文にする` gives a printed form for checking.
3. **It groups things the same way as suru.py.** Consecutive case-by-case function definitions become one pattern match on the arguments, 「ただし」 definitions go into the block of the previous definition, and 「それから」 sentences are attached after the previous sentence. Loaded files are not read. It does not do semantic checks such as the number of a shape's fields, whether all cases are written, whether definitions of the same name are apart, or the names and types of foreign functions.
4. **It is checked to give the same syntax tree as suru.py.** `tests/test_syntax.py` checks, for hand-picked expressions and programs and for every example and library file (both whole programs and every logical line), that the tree equals `suru.py`'s, and that what `suru.py` can't read can't be read by 構文 either.

### Linter rules on the syntax tree

1. **Four rules use the syntax tree.** `suru --点検` parses the file with `lib/構文.suru` and also reports the following. It reads the types and shapes of loaded files before checking. For files that can't be parsed (which would be errors when run), these four are not checked.

| Rule | What it reports |
|---|---|
| 冗長な真偽 (redundant boolean) | `もし c ならば 真 そうでなければ 偽` (just `c` will do), `もし c ならば 偽 そうでなければ 真` (`c = 偽` will do), `x = 真` and `x != 偽` (just `x` will do), `もし x が 真 ならば` (`もし x ならば` will do). `x = 偽` is the only way to negate a value, so it is not reported |
| 同じ枝 (identical branches) | The expressions after 「ならば」 and after 「そうでなければ」 of a 「もし」 are the same |
| 自分との比較 (self comparison) | Comparing an expression with itself, as in `x = x`, `x < x`, `もし x が x ならば` (the result is always the same) |
| 不要な括弧 (needless parentheses) | Parentheses around a single token, as in `（x）`, and the outer parentheses of `（（…））`, when removing them doesn't change the syntax tree. Each outermost sentence is reparsed with the parentheses removed and the trees are compared (ignoring line numbers), so parentheses that decide how something is read, as in `（a の b） の （r）`, are not reported |

2. **Columns come from a nearby token.** ("Columns for syntax-tree rules, and more rules" gave `若式`, `演式` and `場式` their own columns. Now reports use the column of the expression's 「もし」 or comparison symbol.)
3. **構文 provides helpers for the linter.** `e を 構文内の子式群にする` (the directly contained expressions), `e を 構文内の中式行取得する` (the expression's line), `e を 構文内の無行表示文にする` (the printed form without line numbers, for comparing whether expressions have the same shape), `論理行群 を 形群 で 型群 に 構文内の外せる括弧群にする` (pairs of opening and closing tokens of parentheses whose removal doesn't change the tree), and `論理行群 を 構文内の定義形群にする` / `構文内の定義型名群にする` (the shape and type names defined in that file).
4. **A file's own types can be used after load sentences.** Previously `lib/構文.suru` read sentences after a load sentence in the state before the file's types and shapes were collected, which gave the error 「『点』という型はありません」 ("there is no type 『点』"). `tests/test_syntax.py` gained tests that check without passing types and shapes from outside.

### Columns for syntax-tree rules, and more rules

1. **Syntax-tree expressions carry columns.** In `lib/構文.suru`, `若式` (もし) carries the line and column of its 「もし」 (`若行`, `若桁`), `演式` the column of its operator (`演桁`; 「が」 when comparing with 「が」), and `場式` (case analysis) the column of its 「もし」 (`場桁`; 0 for grouped case-by-case function definitions). The linter reports at these columns, so even with two 「もし」 on the same line, each is reported at its own 「もし」. `式表示文にする` doesn't print columns, so `tests/test_syntax.py` still compares with `suru.py`'s trees as before.
2. **Identical branches extended to case analysis.** If the bodies of all cases of a case analysis and the part after 「そうでなければ」 are the same expression, 「同じ枝」 is reported. When a case's pattern binds names (`半径 の 円 ならば …`), expressions that look the same can have different values, so it is not reported.
3. **Constant conditions.** A 「もし」 whose condition is true or false itself, as in `もし 真 ならば …` or `もし 偽 ならば …`, is reported.
4. **Needless parentheses extended to the left side of operators of the same strength.** Parentheses like `（a + b） + c`, `（a * b） / c` and `（a かつ b） かつ c`, where an operator comes right after the closing parenthesis and all outermost operators inside are of the same strength (the four groups + and -; *, / and %; かつ; または), are reported if reparsing without them leaves the tree unchanged. Parentheses around operators of different strength, as in `（x * 2） + 1`, are often written for readability, so they are not checked.

### Building the linter binary faster

1. **Type checking no longer recounts closed types.** Most of the first run of `suru --点検` (which builds the binary) is the Python type checker, which recounted the free type variables in the types of every definition in the environment each time it generalized a definition's type. Types without free type variables (closed types) never change later, so they are remembered, and definitions with no type variables to generalize skip the count. In this environment, generating the linter's IR went from about 40 seconds to about 12 seconds, and the first run takes about 17 seconds in all. The Go version (`suru-ls`, `kumu 点検`) already took about 2 seconds.
2. **The cache name depends only on the files the linter uses.** The name of the cache (`~/.cache/suru/点検-<hash>`) is decided not by all of lib/ but only by the files reached from `点検.suru` through 「「X」 を 読み込む」 plus `基本.suru` (both in `suru.py` and in the Go version). Editing lib files the linter doesn't use no longer triggers a rebuild.

### Checking self-containing types with many shapes

1. **For a field's type that contains the type itself, every inner occurrence of the same type becomes "the type itself".** The type checker (both `suru_check.py` and the Go version) redoes inference with a field marked "contains itself" once it finds the field's type of your own type would go on forever. Previously, when recording that field's type, only the one place found to go on forever became "the type itself", and other occurrences of the same type were recorded with the type parameters of that moment. When another field later turned out to contain itself too, the number of type parameters changed and no longer matched what was recorded, so types with many shapes, like 式 in `lib/構文.suru`, got errors like 「式が必要ですが…の式が渡されています」 ("式 is required, but … の 式 is passed"). Now every inner occurrence of the same type is recorded as "the type itself", so `写式にする`, a function in `lib/構文.suru` that only deep-copied every shape, was removed.
2. **Other fields of the same value are found together.** If other fields of the value found to go on forever already hold the same type that can be unified, they are marked as containing themselves too, reducing the number of redos (from 54 to 35 in `lib/構文.suru`). The same type with different type parameters, as in `（1 と 葉 と 葉 の 節） と 葉 と 葉 の 節` (a tree with a tree as its value), is a different nested type, so it is excluded.

### Processes, pipes and shared memory

1. **`「プロセス」 を 読み込む` runs other programs.** It is written in Suru in `lib/プロセス.suru` and calls C's `system`, `popen`, `pipe` and so on as foreign functions. All of these are actions. A command given as a string is passed to `/bin/sh`; items given as a list are each wrapped in `'…'` before being passed (spaces and symbols become arguments as they are). Output printed so far is flushed before starting, so the order of output doesn't get mixed up. See `examples/process.suru`.

| Syntax | Result (of the action) |
|---|---|
| `「make test」 を プロセス内の命令実行する` | Waits until it finishes and gives the exit code (128+number if ended by a signal) |
| `（「ls」 と 「-l」） を プロセス内の引数実行する` | The same, with a list of arguments |
| `「date」 を プロセス内の命令出力取得する`, `（「git」 と 「log」） を プロセス内の出力取得する` | A record of standard output and exit code, `（出力 は 「…」 で 終了コード は 0 の 実行結果）` |
| `入力 を 「sort」 で プロセス内の命令変換する` | The same record, with the input passed to standard input |
| `「tail -f a.log」 を 「r」 で プロセス内の命令開始する`, `「cat」 を プロセス内の書込命令開始する` | A handle (address) of a command started without waiting for it to end |
| `h から プロセス内の行読込する`, `s を h へ プロセス内の命令書込する`, `h を プロセス内の命令終了待機する` | One line (with its newline; 「」 at the end), the number of bytes written, the exit code |
| `プロセス内のパイプ作成する` | The file descriptors `（読む口 と 書く口）` (read end and write end) |
| `b を fd へ プロセス内の口書込する`, `fd から 100 を プロセス内の口読込する`, `fd を プロセス内の口閉鎖する` | The number of bytes written, the bytes read (empty at the end), 0 |
| `プロセス内のプロセス番号取得する`, `s を プロセス内の引用する` | getpid, the string quoted for sh (pure) |

2. **`「共有メモリ」 を 読み込む` shares memory with another process.** `lib/共有メモリ.suru` calls POSIX `shm_open` and `mmap`. `「/suru-例」 を 4096 で 共有メモリ内の共有メモリ作成する` creates and attaches it (a `共有メモリ` record: name, location, size), and another process attaches to the same memory with `… を 4096 で 共有メモリ内の共有メモリ接続する`. Then `b を 位置 で m へ 共有メモリ内の共有書込する`, `m から n を 位置 で 共有メモリ内の共有読込する` (out of range is a runtime error), `m を 共有メモリ内の共有メモリ解除する` (detach) and `名前 を 共有メモリ内の共有メモリ削除する` (delete). There is no ordering (locking) for simultaneous writes yet.

### Signals

1. **`「シグナル」 を 読み込む` receives and sends signals.** `lib/シグナル.suru` calls C's `sigprocmask`, `sigwait`, `sigpending`, `kill` and so on. Suru functions can't be passed to C, so instead of handlers, signals held back by **受付** ("accept") are received by waiting for them or checking for them. Signals are written by name without SIG, as in `「INT」` `「TERM」` `「HUP」` `「USR1」`, and those whose numbers differ by OS (such as USR1) can be used the same way by name. All of these are actions. See `examples/signal.suru`.

| Syntax | Result (of the action) |
|---|---|
| `（「INT」 と 「TERM」） を シグナル内のシグナル受付する` | Holds them back so the program doesn't end when they arrive (`シグナル受付解除する` undoes it) |
| `シグナル内のシグナル待機する` | Waits until an accepted signal arrives, and gives its name (「TERM」) |
| `シグナル内のシグナル確認する` | The list of names of accepted signals that have arrived and are pending (doesn't wait; received ones are cleared) |
| `「TERM」 を pid へ シグナル内のシグナル送信する`, `「USR1」 を シグナル内のシグナル発生する` | Send to another process (kill), send to itself (raise) |
| `「HUP」 を シグナル内のシグナル無視する`, `「HUP」 を シグナル内のシグナル既定化する` | Do nothing when it arrives, restore the default behavior (usually exiting) |
| `「TERM」 を シグナル内のシグナル番号取得する` | Its number on this OS |

2. **Output is flushed first.** Output printed so far is flushed before waiting and before sending (so it survives even if a signal ends the program). Compiled programs run the program on a separate thread, so the original thread blocks signals, making signals sent to the process handled as accepted.

### String ordering and tables

1. **`<` `>` `<=` `>=` work between strings too.** They compare by character code (Unicode) order, that is, lexicographically (`「ab」 < 「abc」`, `「Z」 < 「a」`). Both sides must have the same type; numbers and strings can't be compared. A function like `a と b を 小さい方にする とは もし a < b ならば …` works for both numbers and strings.
2. **`「表」 を 読み込む` gives tables (associative arrays).** It is a balanced tree (AVL tree) written in Suru in `lib/表.suru`, and tables are immutable values. Keys are numbers or strings.

| Syntax | Result |
|---|---|
| `空表` | An empty table |
| `t を 鍵 から 値 へ 表内の登録する` | A new table with the value stored at the key (the same key is replaced; can be chained with `…して`) |
| `t から 鍵 を 既定 で 表内の既定取得する` | The key's value (or 既定, the default, if absent) |
| `t が 鍵 を 表内の鍵含有である` | Whether the key is present |
| `t を 表内の件数にする`, `t を 表内の鍵一覧にする`, `t を 表内の値一覧にする` | The count, and the list of keys / values in ascending key order |
| `（鍵 と 値 の 対） のリスト を 表内の対表化する` | Builds a table (for the same key, the later one wins) |

### Dynamic linking

1. **`… とは 外部の（f）` calls the C function at the address in parameter f.** The type declaration is the same as for `外部の「…」`, with f as a `番地`. f is not passed to C; the other arguments are passed in definition order. A NULL address is a runtime error. If the value is an action, the call happens when it is carried out.

```
小数 を 番地 で 番地余弦にする は 小数
x を f で 番地余弦にする とは 外部の（f）
```

2. **`「動的リンク」 を 読み込む` opens libraries at runtime.** `lib/動的リンク.suru` calls `dlopen`, `dlsym` and `dlclose`: `「libm.so.6」 を 動的リンク内のライブラリ開封する` (a path if it contains `/`), `h から 「cos」 を 動的リンク内の記号取得する` (the function's address), `h を 動的リンク内のライブラリ閉鎖する`, and `動的リンク内の自分取得する` (the program itself and the libraries already linked). All of these are actions, and failures are runtime errors with dlerror's message. See `examples/dynlink.suru`. Like plugins, this lets you use libraries not decided when the program was written.

### fork and semaphores

1. **`プロセス内の分岐する` forks.** The result is 0 in the child and the child's process number in the parent (output is flushed first, so nothing is printed twice). `pid を プロセス内の子終了待機する` waits until the child ends and gives its exit code (waitpid), `（「ls」 と 「-l」） を プロセス内の置換実行する` replaces this process with another program (execvp; returning is a runtime error), and `n を プロセス内の子終了する` flushes output and exits immediately (_exit; used at the end of a forked child). See `examples/fork.suru`.

2. **`「セマフォ」 を 読み込む` orders processes.** `lib/セマフォ.suru` calls System V semaphores (`semget`, `semop`) (avoiding variadic functions, and using values that are the same on Linux and macOS): `「名前」 を 1 で セマフォ内のセマフォ作成する` (initial value; a runtime error if the name already exists), `「名前」 を セマフォ内のセマフォ接続する`, `s を セマフォ内のセマフォ待機する` (decrement by 1; waits at 0), `s を セマフォ内のセマフォ試行する` (真 if it could decrement without waiting), `s を セマフォ内のセマフォ解放する` (increment by 1) and `s を セマフォ内のセマフォ削除する`. With an initial value of 1 it works as a lock, so shared memory can be updated in turn.

3. **Libraries' helper functions are private.** The FFI libraries in `lib/` mark their C function declarations (`確保する` and so on) and helper functions with `… は 非公開とする` at the end of the file ("Public and private"), so names don't clash even when several libraries are loaded with 「読み込んで 使う」 (`tests/test_lib_together.py`).

### Public and private

1. **`確保する と 解放する は 非公開とする` hides names from files that load this one.** It is an outermost sentence, by convention gathered at the end of the file (`確保すると解放するは非公開とする。` in the punctuation style, `非公開とします` politely). Private names can be used normally inside the file, and can't be used from a loading file even as `部品内の確保する`. Private names don't clash even between files loaded with 「読み込んで 使う」. Without any such sentence, everything is public.
2. **With `… は 公開とする`, only the names written there are public.** If a file has even one `二倍する と 円周率 は 公開とする`, only the names written there are visible from outside and everything else is private (a list of exported names). Names not defined in the file, and names written as both public and private, are errors. Types, shapes and traits stay visible everywhere as before.
3. **Using a private name is an error before running.** The type checker (interpreter, `suruc`, `kumu 作る`, `kumu 試験`) reports a loaded file's private name, even inside a function never called, as `「成功にする」は定義されていません(「標準」で非公開とされています)` ("「成功にする」 is not defined (it is private in 「標準」)"). Defining the same name in your own file makes yours usable. Other unknown names are also errors before running ("Undefined names and lists of actions").

### JSON and number formatting

1. **`「JSON」 を 読み込んで 使う` reads and writes JSON.** `lib/JSON.suru` is written in Suru, and all its names start with JSON. Values have the type with alternatives `JSON`: `JSON無` (null), `真 の JSON真偽`, `1.5 の JSON数`, `「a」 の JSON文字列`, `xs の JSON配列`, and `ps の JSON物` (an object: a list of `「名前」 と v の JSON項目`, kept in written order). Pattern matching takes them apart.
2. **Reading.** `s を JSON解析する` gives `v の 成功` or `理由 の 失敗` (a `（JSON と 文字列） の 成否`; for example 「JSON を読めません(『]』をここには書けません)」, "can't read the JSON (『]』 can't be written here)"). `s を JSON読取する` is an action whose result is the JSON, and a runtime error if it can't be read (catchable with `試行する`). `\uXXXX` and surrogate pairs are decoded too. It advances one token at a time with a fold, so long arrays and strings don't make recursion deep.
3. **Writing and accessing.** `v を JSON文字列にする` gives one-line JSON, and `v を JSON整形する` JSON indented by two spaces. `v から 「名前」 を JSON取得する` gives an object's item (`JSON無` if absent), and `v から n を JSON番目取得する` the nth element of an array (from 1; `JSON無` if absent). See `examples/json.suru`.
4. **Number formatting is in 標準.** `1234567 を 桁区切りする` gives 「1,234,567」, `42 を 5 で 零詰する` 「00042」, `3.14159 を 2 で 小数書式にする` 「3.14」 (rounded), `s を 8 で 右詰する` and `左詰する` pad with spaces to a width, and `「ab」 を 3 で 反復する` gives 「ababab」. `「{}さん、{}歳」 を （「花子」 と 「12」） で 差込する` puts strings into the 「{}」 in order from the front.

### Threads

1. **`「スレッド」 を 読み込む` carries out actions on separate threads.** These are built-ins of `lib/スレッド.suru`. Suru values are never modified, so threads holding the same value can't corrupt it.

| Syntax | Result |
|---|---|
| `動作 を スレッド内の並行開始する` | An action that starts the action on another thread and returns the thread without waiting (its type is `数 の スレッド` and so on) |
| `t を スレッド内の合流する` | An action that waits until the thread ends and returns the action's result (join) |
| `動作のリスト を スレッド内の並行実行する` | An action that starts each on its own thread, waits for all, and returns the list of results |
| `xs を f で スレッド内の並列写像する` | The same list of results as `それぞれ` (pure; the elements are split across the CPUs) |
| `スレッド内のコア数取得する` | An action returning the number of available CPUs |

```
「スレッド」 を 読み込んで 使う
試す とは 以下の手順です
  t とは （30 を 重く計算して 結果にする） を 並行開始した 結果
  「計算中」 を 表示する
  t を 合流してから 表示する
  以上です
```

2. **An error inside a thread ends only that thread.** The message is written to standard error right away. Joining it gives the runtime error `並行開始した動作はエラーで終わりました` ("the started action ended with an error"), catchable with `試行する`. An error inside `並列写像する` is the same error as when computed in order.
3. **When the outermost action ends, threads not joined end without being waited for.** Join threads you want to run to the end.
4. **Threads really run at the same time.** Computation runs in parallel up to the number of CPUs ("Parallel execution of threads"). The interpreter runs on Python threads, and its `並列写像する` computes in order.
5. **Accept signals and fork before starting threads.** A new thread inherits the signal acceptance of the thread that started it. Calling `分岐する` while threads exist leaves only the calling thread in the child.
6. **New threads have a 256MB stack.** It is virtual memory, so only what is used is actually consumed (deep recursion works).
7. **Threads pass values through channels (通路).** A channel is a record carrying the type of the values inside, like `数 の 通路`, and those values must have the same type.

| Syntax | Result |
|---|---|
| `容量 で スレッド内の通路作成する` | An action returning a new channel. With capacity 0, the sender waits until the value is received |
| `x を c へ スレッド内の通路送信する` | Send (if full, waits until there is room). The result is x |
| `c から スレッド内の通路受信する` | Receive (if empty, waits until something arrives). A runtime error if closed and empty |
| `c を スレッド内の通路閉鎖する` | Announces nothing more will be sent. Values already there can be received; sending to a closed channel is a runtime error |
| `c を f で スレッド内の通路処理する` | Carries out action f for each value that arrives, until closed. The result is how many were handled |

8. **It is an error when no thread can make progress.** When every thread is waiting on a channel or join and none can move on, instead of hanging forever you get the runtime error `すべてのスレッドが待っていて、先に進めません(通路や合流の待ち)` ("all threads are waiting and can't proceed (waiting on channels or joins)"). Threads waiting in foreign functions or input are not counted, since they may move on eventually.
9. **Names avoid clashing with 通信.** So they can be loaded with 「読み込んで 使う」 together with `通信`'s `送信する` and `受信する`, channel functions are named `通路…する`. The inside of a channel is built so its kind can be swapped, so that pipes between processes can use the same functions (planned).
10. **Locks and slots take the form "carry out an action only while holding it".** So that nobody forgets to release, taking and releasing are not written separately. Even if the action inside exits with an error, it is always released.

| Syntax | Result |
|---|---|
| `スレッド内のロック作成する` | An action returning a new lock |
| `l で 動作 を スレッド内の排他実行する` | Carries out the action holding the lock (waits if another thread holds it). The same thread can hold it again (reentrant). The result is the action's result |
| `n で スレッド内の枠作成する` | Slots usable by up to n at a time (a semaphore within the process; between processes use 「セマフォ」) |
| `w で 動作 を スレッド内の枠内実行する` | Carries out the action using one slot (waits if none is free) |

11. **Boxes are mutable values shared between threads.** They carry the type of the value inside, like `数 の 箱`. Suru values don't change, so reading needs no lock and `箱読取する` never waits.

| Syntax | Result |
|---|---|
| `x で スレッド内の箱作成する` | An action returning a new box with initial value x |
| `b を スレッド内の箱読取する` | The current value |
| `b を f で スレッド内の箱更新する` | Replaces the current value with the pure function f applied to it (without clashing with other threads). The result is the new value |
| `x を b へ スレッド内の箱書込する` | Replaces it with x |

12. **Putting an action into a channel or box makes that action be carried out when it is taken out** (because an action whose result is an action is carried out in turn). To pass the action itself, wrap it in a record.
13. **Making the HTTP server answer each connection in parallel.** `8080 を 案内すること で HTTP内の並行待受する` in [suru-lang/http](https://github.com/suru-lang/http) (`HTTP内の動作並行待受する` for functions returning actions) passes accepted connections through a channel to 16 threads, each answering one at a time (`HTTP内の同時接続数`). Requests that take a second, or clients that connect and send nothing, don't hold up other requests. Sending one request at a time in order to the binary handles about 1,800 per second, and the RSS measured every 5,000 requests stays at about 13MB without growing.

### Parallel execution of threads

1. **The global lock is gone, and threads run Suru code at the same time up to the number of CPUs.** On a 4-core machine, giving `並列写像する` eight Fibonacci computations (which don't allocate) is about 3.9 times faster than computing in order (1.12 seconds → 0.28 seconds). Computations that allocate a lot are about 2.5 times faster. Measured, the GC is about 5% of the whole, and most of the missing speed-up came from using more fresh memory in parallel (time to allocate pages, and cache misses).
2. **The GC runs after stopping every thread.** A thread whose allocation exceeds a set amount raises a stop flag and waits for the other threads to stop at a "safepoint" (function entries and allocation sites), then scans every thread's stack and registers. Threads waiting in foreign functions, input, networking or channels count as stopped, so the GC can run without waiting for them. Stopping with signals is not used.
3. **Safepoints at function entries.** The compiler (the same in the Python and Go versions) emits IR that reads the flag (`rt_gc_stop`) at function entry and calls `rt_safepoint` if it is raised. Even endless recursion that never allocates doesn't hold up the GC. Functions that call no other functions (leaves: functions that only compute or allocate, like `x を 加一する とは x + 1`) don't get one. Every recursion cycle must include a function that calls other functions, so it can stop there. Even in programs without threads, the computation with the most calls (recursive Fibonacci) was about 15% slower (thinning it out for self-recursion is in "Speed improvements").
4. **Allocation comes from per-thread blocks.** Each thread has blocks of its own for each size, and only when one runs out does it take the lock to get the next block from the shared chain. The blocks of finished threads go back to the shared pool.
5. **`箱更新する` replaces with compare-and-swap.** It applies the function to the current value and replaces it if no other thread changed the box meanwhile; otherwise it retries with the new value. The function is pure, so the result is the same however many times it is applied (the function may be called more than once). `箱読取する` and `箱書込する` never wait.
6. **The state of channels, locks, slots and joins is protected by one lock.** While waiting, a thread releases that lock and sleeps, and is woken when the state changes. `表示する` writes one line at a time as a unit, so output of different threads doesn't mix within a line.
7. **Checked with ThreadSanitizer.** The runtime was built with `-fsanitize=thread`, and the thread test programs and the parallel HTTP server hit from 8 connections showed no race reports (the places where the GC reads other threads' stacks happen only while they are stopped, so they are excluded).
8. **Only waiting threads that can now make progress are woken.** A thread that changes the state of a channel, lock, slot or join checks the conditions of waiting threads and wakes only those that can proceed. With eight threads waiting on other channels, a hand-off over a capacity-0 channel went from about 83 µs to about 22 µs each.

### Speed improvements (comparison branches, safepoints in recursion, allocation chunks, channel spinning)

1. **When the condition of `もし` is an integer comparison, it branches without building a boolean.** `もし n < 2 ならば …` branches directly on the comparison when both sides are integers, and only otherwise compares in the runtime library as before. The same goes for `かつ`, `または`, `でない` and case conditions (after `かつ`). A binary computing fib(35) eight times went from about 1.0 seconds to about 0.46 seconds (#80).
2. **Functions that only call themselves look at the safepoint once every 64 calls.** A function that calls no other Suru function but itself (such as recursive Fibonacci) decrements a per-thread counter and looks at the GC flag only when it reaches 0. The GC is held up for at most 64 non-allocating calls. Reading the flag also takes one instruction less. fib's instruction count drops by about 8% (#81).
3. **Blocks for small objects are cut from 2MB chunks taken with mmap.** Instead of mapping each block (256KB), on Linux it asks for huge pages (2MB) (`MADV_HUGEPAGE`, effective when THP is `madvise` or `always`). mmapped memory is zero, so objects used for the first time are not zero-filled. `並列写像する` with eight jobs each making 300,000 strings went from about 0.25 seconds to about 0.18 seconds (4 cores, #82).
4. **When waiting on channels, locks, slots and joins, a thread spins briefly before sleeping.** For hand-offs where the other side arrives soon, this is faster than sleeping and being woken (two thread switches). The spin lasts 1 to 16 µs, longer when it pays off and shorter when it doesn't (the length of the pause instruction differs by CPU, so it is bounded by time, not count). While spinning it still checks the GC flag and sleeps at once if it is raised. With a single CPU it doesn't spin. Passing 100,000 values over a capacity-0 channel went from about 2.7 seconds to about 0.3 seconds (#83).
5. **Benchmark programs were added in `tests/bench`.** `フィボナッチ.suru`, `並列の文字列.suru` and `通路の受け渡し.suru` (`python3 tests/bench/run.py`).

### Value serialization and セマフォ内実行する

1. **`x を 標準内の直列化する` turns a value into bytes, and `b を 標準内の復元する` turns it back.** Numbers, decimals, booleans, strings, byte sequences, lists and records (nested too) are put in a form that can be passed to other processes through shared memory or pipes. Functions, actions and addresses can't be passed, so they are runtime errors. The interpreter and compiled programs produce the same bytes (it starts with `SURU` and version 1; numbers are 8 bytes little-endian, lengths are 4 bytes, and records carry their shape and field names).
2. **The type of a restored value is decided by writing it.** The result of `復元する` can be any type, so declare it, as in `ps は 点 の リスト`, or use it inside a function with a fixed type. Records are restored by shape name, and it is a runtime error if this program has no such shape or the field names or count differ (「形『点』のフィールドが違うので復元できません」, "can't restore because the fields of shape 『点』 differ"). Reading it as a different type only gives a runtime error where the value is used; it never produces a corrupted value.
3. **`s で 動作 を セマフォ内のセマフォ内実行する` carries out an action only inside the lock.** It waits, carries out the action, and releases when done. Even if the action fails, it releases first and then raises the runtime error 「セマフォ『名前』の中の動作はエラーで終わりました」. Waiting and releasing use SEM_UNDO, so if the process crashes or exits inside, the OS restores the lock. `セマフォ待機する` and `セマフォ解放する` don't use it (otherwise the count would drop when a process that only releases exits).


### Shared boxes

1. **`「共有箱」 を 読み込む` shares one value between processes.** `lib/共有箱.suru` is a box that serializes the value into shared memory, protected by a reader-writer lock ("Value serialization and セマフォ内実行する"). Its type is written with the type of its contents, like `点 の 共有箱`. `「/名前」 を 初期値 で 容量 に 共有箱内の共有箱作成する` (capacity is the upper limit in bytes of the serialization; an existing one with the same name is recreated), `「/名前」 を 共有箱内の共有箱接続する` (the contents' type is decided by declaration), `b を 共有箱内の共有箱読取する`, `x を b へ 共有箱内の共有箱書込する`, `b を 関数 で 共有箱内の共有箱更新する` (nothing else can cut in between reading, applying the function and writing), `b を 共有箱内の共有箱解除する` and `b を 共有箱内の共有箱削除する`. All of these are actions.
2. **To enclose the range of use, use `共有箱使用する`.** `「/名前」 を 初期値 で （b を 受け取って … を 返すこと） に 共有箱内の共有箱使用する` creates the box, carries out the action, and deletes the box when done (even on error). The capacity is four times the initial value's serialization (at least 4096 bytes).
3. **Reads happen together, writes one at a time.** The reader-writer lock inside is two System V semaphores (a writer's mark and the number of readers), all with SEM_UNDO, so the OS restores them if a process crashes inside the lock. While a writer is waiting, new readers are not let in. If the function inside the lock fails, the lock is released first, then the runtime error 「共有箱『名前』を書く途中でエラーになりました」 is raised.
4. **Writes go to the unused side.** There are two places for the contents; it writes to the unused one and then switches, so if the writer crashes midway, the previous contents can still be read. The shared memory size is 128 + capacity × 2 bytes.

### Reader-writer locks

1. **`「読書ロック」 を 読み込む` lets readers share and gives writers sole access.** `lib/読書ロック.suru` is a lock for protecting things outside shared boxes (files, shared memory of byte sequences, C memory and so on) between processes (shared boxes hold the same lock inside). `「/名前」 を 読書ロック内の読書ロック作成する` (an existing one with the same name is recreated), `「/名前」 を 読書ロック内の読書ロック接続する`, `l で 動作 を 読書ロック内の読取実行する` (together with other readers; waits if there is a writer), `l で 動作 を 読書ロック内の書込実行する` (waits until everyone else is gone), `l を 読書ロック内の読書ロック解除する` and `l を 読書ロック内の読書ロック削除する`. All of these are actions.
2. **Locks only take the form of passing an action.** Taking and releasing can't be written separately. If the action fails, the lock is released first and then the runtime error 「読み書きロック『名前』で書く途中でエラーになりました」 is raised, and if the process crashes inside, SEM_UNDO lets the OS restore it. While a writer is waiting, new readers are not let in.
3. **No hiragana in the name.** File and function names are written in kanji and katakana, so it is 「読書」 rather than 「読み書き」.

### Pipe channels and 子実行する

1. **`スレッド内のプロセス間通路作成する` makes a channel between forked processes.** It is a pipe inside, with the same type as thread channels (`点 の 通路`) and the same `通路送信する`, `通路受信する`, `通路閉鎖する` and `通路処理する`. Values are serialized and sent with their length in front ("Value serialization and セマフォ内実行する"). Create it before forking.
2. **One direction per process.** A process that sends first closes the read end, and a process that receives first closes the write end. When all senders have called `通路閉鎖する` or exited, the receiver sees the channel as closed (`通路処理する` ends), and with no receiving process, sending gives the runtime error 「受け取る相手がいないので、通路に送れません」 ("no one to receive, so can't send on the channel"). Trying to receive in a process that sent is an error.
3. **`動作 を プロセス内の子実行する` hands an action to a child process.** It forks, carries out the action in the child, and the child then exits (on error, it writes the message and exits with code 1). In the parent, the result is the child's process number, so you can wait with `子終了待機する`.

```
c とは プロセス間通路作成した 結果
pid とは （c を （p を 受け取って p の 横 を 表示する を 返すこと） で 通路処理する） を 子実行した 結果
（1 と 2 の 点） を c へ 通路送信する
c を 通路閉鎖する
```

### Named channels

1. **`スレッド内の名前つき通路作成する` and `名前つき通路接続する` make channels between unrelated (separately started) programs.** Inside is a named pipe (FIFO); pass a file path, as in `「/tmp/仕事」 を 名前つき通路作成した 結果`. The type and verbs are the same as pipe channels ("Pipe channels and 子実行する"), and values are serialized when sent, so they can pass between the interpreter and binaries too.
2. **Create makes it if absent and uses it if present. Connect works only on existing ones.** An ordinary file or the like at the path is an error. Delete it with `名前つき通路削除する` (the program that created it deletes it).
3. **It is opened at the first send or receive.** It waits until the other side opens. Each process has one direction (decided by the first operation). When all senders close, the receiver sees it as closed, so with several senders, make sure they have all opened (are waiting) before the receiver opens.
4. **However many senders there are, a single value never gets mixed.** A sender holds a file lock (flock) while sending, so even values too large for the pipe to take at once don't interleave with others'.

```
c とは 「/tmp/仕事」 を 名前つき通路作成した 結果
c を （p を 受け取って p の 横 を 表示する を 返すこと） で 通路処理する
「/tmp/仕事」 を 名前つき通路削除する
```

### Project management (kumu)

1. **The project tool is `kumu` (組む).** Named after its three roles: assembling (組む) projects, combining (組み合わせる) dependencies, and putting things together (組み立てる) in builds. It is a separate command from `suru`, a single executable written in Go (`cmd/kumu/`), and uses the Go compiler inside.
2. **Commands are in Japanese, with English aliases.** `新規` (new), `初期化` (init), `作る` (build), `実行` (run), `版` (version), `助け` (help).
3. **Settings are written in `組.suru` as Suru definitions.** You can write `名前` (required), `版` (default 「0.1.0」) and `入口` (default 「本体」), all as strings `… とは 「…」`. kumu only reads `組.suru` without running it; sentences other than definitions, unknown items, non-string values and items written twice are errors (reported with the line). The punctuation style (`名前とは「挨拶」。`) works too. `組.suru` is searched for from the current folder upward.
4. **Build output goes in `出力/名前`.** The entry file's folder is the starting point for loading, so files inside the project are used with `「部品」 を 読み込む` as before. `新規` writes `/出力/` into `.gitignore`. If the LLVM IR, optimization level, runtime library and kumu version are the same as before, the previous binary is reused without calling clang (recorded in `出力/.名前.stamp`).
5. **`実行` passes arguments and I/O straight to the built binary and returns its exit code as is.** Everything after `--` is arguments to the program. kumu's messages (「…を組みました」, "built …") go to standard error, so they don't mix with the program's output.
6. **Dependencies are written in `依存` in `組.suru` as 「LOCATION@VERSION」.** One is `依存 とは 「github.com/someone/計算@1.2.0」`; several are joined with `と`. The location is a Git repository (`github.com/…` is fetched over https; `https://…` and `file://…` are used as is), and the version is a Git tag (`v1.2.0` or `1.2.0`). Version ranges (such as "1.2 or later") can't be written; you always write one version. A location starting with `.` or `/` is a local folder (no version), usable only in the project's 組.suru. `kumu 追加`, `更新` and `削除` rewrite this line.
7. **Dependencies are loaded by the name in their 組.suru.** A library makes the file with its own name (`計算.suru`) the file to be loaded. `「計算」 を 読み込む` loads that file, and `「計算/道具」` loads `道具.suru` inside the library (the prefix is the file name, `計算内の` or `道具内の`, as in "Loading files"). It is an error if a dependency's name equals a standard library's (「標準」, 「通信」 and so on) or if two dependencies have the same name.
8. **Files to load are searched in the order: own folder → dependencies → standard lib.** The interpreter (`suru`), the Go compiler (`suruc`) and the language server (`suru-ls`) search upward from the folder of the file being run for 組.suru and use the dependencies written in the `組.lock` next to it (they work without kumu as long as the dependencies have been fetched). Files inside dependencies can load the project's dependencies too. Loading a dependency listed in `組.lock` but not yet fetched gives the error 「まだ取ってきてありません」 ("not fetched yet").
9. **Fetched dependencies are kept in `~/.kumu/依存/`.** Each is fetched once into a folder `LOCATION@VERSION` (`.git` is removed) and not copied per project. `KUMU_HOME` changes the location.
10. **When the same library is required at different versions, the newest is used.** Dependencies of dependencies are followed and collected, and when several versions of the same location appear, the newest wins (the same idea as Go's minimal version selection, so the result is always the same). Versions are compared by the dot-separated numbers from the left.
11. **`組.lock` records the name, location, version, commit and content hash of each dependency used.** kumu writes this file; keep it in the repository. On the next collection, if the commit or contents for the same version differ from `組.lock` (a tag was moved, a fetched copy was edited), it is an error. When there are no dependencies left, `組.lock` is deleted. If collecting fails, a 組.suru rewritten by `追加` and the like is restored.
12. **Tests are 「…試験する」 in files in `試験/`.** Each outermost, argument-less definition whose name ends in 「試験する」 in .suru files under `試験/` (subfolders included) is one test (names can't contain hiragana, so it is `二倍試験する`, not 「二倍を試験する」). The body is usually a `手順`, using the assertion functions of `「試験」 を 読み込んで 使う`. Other definitions (helper functions and so on) are not tests.
13. **The assertion functions are the 「試験」 library.** `実際 を 期待 に 一致確認する` (if not equal: 「等しくありません: 期待は 4 / 実際は 5」, "not equal: expected 4 / actual 5"), `条件 を 確認する` (if not true: 「真ではありません」), and `理由 を 不合格にする` (fail). All are actions; on failure they write the reason to standard error and exit with code 1. They are written in Suru in `lib/試験.suru` and work without kumu.
14. **Each test runs in its own process.** For each test file, kumu builds a program in `出力/試験/` that loads the file and picks a test by number (compiled with `-O0`), and runs it once per test. Exit code 0 means pass; whether an assertion fails or a runtime error occurs, only that test stops. Only failing tests show their output (standard output and standard error), indented. At the end it prints 「合格 3・不合格 1」 ("3 passed, 1 failed"), and exits with code 1 if anything failed. A test file that can't be read or doesn't type-check counts as that file failing. `kumu 試験 二倍` runs only the tests whose name or file path contains that text.
15. **A project can load itself by the name in 組.suru.** If there is no `計算.suru` in your own folder, `「計算」 を 読み込む` reads `計算.suru` in the folder of the project whose 組.suru name is 「計算」 (`「計算/道具」` reads `道具.suru`). This lets files in `試験/` load the project's files the same way users do. The interpreter, the Go compiler and the language server behave the same.
16. **`kumu 点検` covers every file in the project.** It runs the same lint as `suru --点検` on every .suru file except 組.suru, `出力/` and folders starting with `.` (the linter is built into a binary only the first time and cached; clang is required). It exits with code 1 if there are reports.
17. **`kumu 公開` only tags; it doesn't push.** It checks that the version is only digits and dots, that `名前.suru` exists, that no dependency is a local folder, that 組.suru is at the top of the repository, that there are no uncommitted changes, that no tag for the same version exists, and that all tests pass, then puts the annotated tag `v版`. Publishing it is up to you: `git push origin v版`. At the end it prints the `kumu 追加 LOCATION@VERSION` that users will write (the location is made from the URL of `origin`).
18. **kumu can be used from VS Code too.** The command palette's 「プロジェクトを実行する(kumu 実行)」, 「プロジェクトを組む」, 「プロジェクトを試験する」, 「プロジェクトを点検する」 and 「依存を取ってくる」 (run, build, test, lint the project, fetch dependencies) run kumu in the folder of the 組.suru found searching upward from the open file. In files in `試験/`, 「▷ 試験する」 appears above each 「…試験する とは」 line to run just that test (`kumu 試験 名前`). kumu's location is the setting `suru.kumu` (if empty, PATH and `~/go/bin`).

### External dependencies (system C libraries)

1. **A library wrapping a C library writes `外部依存` in 組.suru.** Write pkg-config names, as in `外部依存 とは 「libpcre2-8」`, joining several with `と`. `「libpcre2-8@10.30」` means "10.30 or later" (unlike the `@` of dependencies, this is a lower bound). The name to link is written as before with `外部の「pcre2-8」 を 読み込む`.

```
名前 とは 「正規表現」
版 とは 「0.1.0」
外部依存 とは 「libpcre2-8@10.30」
導入案内 とは 「macOS: brew install pcre2」 と 「Debian・Ubuntu: sudo apt install libpcre2-dev」
```

2. **kumu checks external dependencies before building.** In `作る`, `実行`, `試験`, `取得`, `追加`, `更新` and `削除`, it checks the external dependencies of the project and all its dependencies with `pkg-config --exists` (`--atleast-version` when a version is given). If any are missing, it stops with the error 「システムのライブラリが足りません」 ("system libraries are missing"), showing which are missing, which dependency uses them, and that dependency's `導入案内` (installation hints). A dependency added with `追加` stays in 組.suru even if its external dependencies are missing (install them and retry with `kumu 作る`).
3. **Without pkg-config, nothing is checked.** It says 「pkg-config が無いので、…確かめずに進みます」 ("pkg-config not found, so … proceeding without checking") and goes on; anything missing fails at link time. `PKG_CONFIG` changes the pkg-config command.
4. **Short names of foreign libraries are also looked up in pkg-config's folders.** If `外部の「pcre2-8」` isn't found the usual OS way, it is looked up in the `libdir` of pkg-config's `libpcre2-8` or `pcre2-8`. This is for libraries in folders that the linker and dlopen don't usually search, like Homebrew's `/opt/homebrew/lib`. The interpreter (ctypes) opens that file, and the compilers (Python and Go) add `-L` and `-Wl,-rpath` (not for ordinary folders like `/usr/lib`). The same holds outside kumu.
5. **PCRE2 regular expressions are in [suru-lang/regex](https://github.com/suru-lang/regex).** An example of a non-standard library wrapping a C library. Add it with `kumu 追加 github.com/suru-lang/regex`, and use `正規検索する`, `正規全検索する`, `正規置換する`, `正規分割する` and others via `「正規表現」 を 読み込んで 使う` (see that repository's README for usage). An example project using it is `examples/正規表現/` (`kumu 実行`).

### Argument lists for foreign functions

1. **`外部の「NAME」（a と 0 と b）` lists the arguments passed to C.** There are six particles, so a definition has at most six parameters, but the C function receives any number, in the order written inside the parentheses. Inside them, join the definition's parameter names or integers with `と`; integers are passed as `int64_t` (`0` for a NULL address of an unused context, `-1` for `(size_t)-1` such as `PCRE2_ZERO_TERMINATED`). Every parameter of the definition must be written at least once. The interpreter and both the Python and Go compilers behave the same.

```
番地 を 番地 で 数 に 数 から 整数 へ 番地 より 照合呼出する は 整数 の 動作
符号 を 対象 で 長さ に 開始 から 選択 へ 一致 より 照合呼出する とは 外部の「pcre2_match_8」（符号 と 対象 と 長さ と 開始 と 選択 と 一致 と 0）
```

### Releases and distribution

1. **Distributed four ways.** PyPI (`suru-lang`), GitHub Releases (`suruc`, `suru-ls` and `kumu` per OS), a Homebrew tap (`suru-lang/homebrew-suru`) and the VS Code Marketplace (the extension). In each case GitHub Actions builds and publishes from a tag. The steps, and what to prepare first (PyPI Trusted Publishing, Trusted Publishing for the Marketplace publisher and so on), are in [docs/リリース.md](docs/リリース.md) (in Japanese).

2. **The PyPI name is `suru-lang`.** `suru` was taken by someone else, so only the package name differs. The installed command and module are still named `suru`.

3. **Two kinds of tags.** Tags like `v0.1.0` release the main package (PyPI, GitHub Releases, Homebrew), and tags like `vscode-v0.4.0` release the VS Code extension. The extension's version is raised separately from the main one. If the tag doesn't match the version in `suru.py` and the Go programs (`cmd/suruc`, `cmd/suru-ls`, `cmd/kumu`), `packaging/check_version.py` stops the release. The version of the Go binaries is set to the tag's at build time with `-X main.version=…`.

4. **Windows gets the same three programs.** `suruc.exe`, `suru-ls.exe` and `kumu.exe` are packed in a `.zip` for amd64 and arm64. The release workflow runs the amd64 ones on windows-latest with MSYS2's clang and lld, building and running a small program with `suruc` and `kumu`, before publishing. What doesn't work on Windows yet is in "Standard library on Windows".

5. **Homebrew builds from source.** The formula (made by `packaging/homebrew/make_formula.py`) builds `suruc`, `suru-ls` and `kumu` with Go from the tag's source, and puts the Python `suru` in libexec, run through a wrapper. It doesn't install clang; the caveats explain it (on macOS it comes with the Xcode command line tools).

6. **Nothing depends on the owner's name.** The workflows get the owner name used for the tap and release notes from GitHub. When moving to an organization or the like, `packaging/move_owner.py` rewrites the URLs, Go module paths, tap and publisher together (the steps are in 「organization などに移すとき」 in [docs/リリース.md](docs/リリース.md)).

### Interactive mode

1. **Start it with `suru` and no arguments.** Each input is type-checked and then run, and the value and type are shown side by side as "VALUE は TYPE", as in `3 を 二乗する` → `9 は 数`. If there is a type error, it doesn't run. `suru --検査なし` runs without checking types and shows only the value. When you enter a definition, its type is shown in the form of a type declaration, like `数 を 二乗する は 数`.
2. **What counts as one input.** One line is one input. If a line's last word is `とは`, `が`, `ならば` or `そうでなければ`, indented continuation lines are expected, and a blank line completes it. A line ending in `と`, `ただし`, `それから`, `かつ` or `または` continues on the next line. With unclosed parentheses it reads until they close, and punctuation-style lines are read until they end with 「。」.
3. **Definitions, types and loads from earlier inputs stay available.** Type checking includes the definitions from earlier inputs. Redefining a name replaces the earlier definition (it doesn't become a case-by-case definition as it would in a file). Definitions from an input with a type error are not kept. Types and shapes can't be redefined.
4. **Commands start with 「:」.** `:助け` (usage), `:型 EXPR` (only the type, without running), `:読む FILE` (load a file's definitions; `.suru` can be left out; loads inside are searched from that file's folder), `:一覧` (names and types defined in this session), and `:終わる` (Ctrl-D also exits). The full-width 「：」 and full-width spaces work too, so you can type them with Japanese input on. There are English aliases (`:help` `:type` `:load` `:names` `:quit`). `suru --対話 FILE …` loads the files before starting.
5. **Line editing, history and completion.** If Python has readline (macOS, Linux), you get arrow-key editing, recall of earlier inputs, and Tab completion of names (built-ins, defined names, commands). History is kept in `~/.local/state/suru/history` (changeable with `XDG_STATE_HOME` or `SURU_HISTORY`). Ctrl-C cancels the input in progress, or interrupts a running evaluation.
6. **Interpreter only.** The compilers (Python and Go) have no interactive mode.

### Fixed layouts and fixed regions

1. **`x を 見本 で 標準内の固定直列化する` turns a record into bytes laid out like a C struct.** The layout is decided by the sample (見本) record, and fields may only be numbers and booleans (nested records are flattened). Each is 8 bytes: int64_t if the sample's field is an integer, double if it is a decimal, and int64_t 0 or 1 for a boolean (little-endian). `b を 見本 で 固定復元する` turns it back, and the result has the same type as the sample. A value whose layout differs from the sample, or a decimal for an integer field, is an error. Putting an integer into a decimal field is fine.
2. **`lib/固定領域.suru` places fixed-layout values in shared memory.** `名前 を 見本 で 固定領域作成する` (creates it if absent, with the sample as its contents), `固定領域接続する`, `固定領域読取する`, `固定領域書込する`, `固定領域解除する` and `固定領域削除する`. There is no serialization, so C programs using a struct with the same layout can read and write it too.
3. **No lock and no header.** Unlike shared boxes ("Shared boxes"), nothing is put at the start, to keep the same layout as C. When several writers exist, protect it with `セマフォ内実行する` or the like.

```
点 とは 横 と 縦 の 組
r とは 「/suru-例」 を （0 と 0.0 の 点） で 固定領域作成した 結果
（7 と 2.5 の 点） を r へ 固定領域書込する
```

### Negative addresses

1. **`-1 を 番地にする` is a two's-complement address.** Negative integers can become addresses too, so that markers like C's `(void *)-1` (SQLite's `SQLITE_TRANSIENT`, `mmap`'s `MAP_FAILED` and so on) can be made. `番地数値にする` gives a signed number (`-1`) in both the interpreter and compiled programs. Non-integer numbers are errors.
2. **SQLite is a non-standard library.** The library 「SQLite」 for SQLite databases is in [suru-lang/sqlite](https://github.com/suru-lang/sqlite); use it with `kumu 追加 github.com/suru-lang/sqlite` (libsqlite3 is an external dependency in its 組.suru).

### 成否 and 有無 (returning failure as a value)

1. **`成否` is the result of a computation that may fail, and `有無` is a value that may or may not be there.** `成否 とは 値 の 成功 か 理由 の 失敗` (Rust's Result: success or failure) and `有無 とは 値 の 有 か 無` (Option / Maybe: some or none) are written in `lib/基本.suru`. Their types are `（数 と 文字列） の 成否` and `数 の 有無`. Build them with `（a / b） の 成功`, `「0 では割れません」 の 失敗`, `3 の 有` and `無`, and take them apart with a `もし r が` case analysis.
2. **Writing them loads them automatically.** If a program mentions `成否` `有無` `成功` `失敗` `有` `無` (except in the `… は 無` type of foreign functions), or `成否にする` `有無にする` `中断する` `失敗説明する` `失敗詳細にする` `数値確認する` `試算する`, or `試行する` without 「で」, it is as if `「基本」 を 読み込んで 使う` had been written (`基本内の有無にする` also works). Without them nothing is loaded, so existing programs don't change. The bundled `lib/基本.suru` is always used (a `基本.suru` in the same folder is not). Using `成功` and the like as shape names of your own types is an error.
3. **Functions.** `r を 取出する` is the inner value on success (有), and a runtime error on failure (無) (unwrap). `o を 「ない」 で 成否にする` turns 有 into success and 無 into `「ない」 の 失敗`. `r を 有無にする` turns success into 有 and failure into 無. `文 を 中断する` becomes a runtime error with that message on the spot (it is not an action, so it can be used inside pure functions). `取出する` is a function of the trait 「取出可能」, so programs using 基本 can't redefine it.
4. **Mappable and chainable.** `（10 と 2 を 安全除算する） の 結果 を 倍化する` doubles the contents on success and returns a failure unchanged. `した 結果` in a procedure skips the rest as soon as a failure (無) appears, and makes that failure (無) the value of the whole.
5. **「…した 中身」 is Rust's `?`.** In `（x と y を 安全除算した 中身） と z を 安全除算する`, a success (有) becomes the inner value, and on failure (無) the innermost function containing it (a 「とは」 function or an anonymous function) returns that failure (無) immediately. Like 「した 結果」 it is a noun, so it can go anywhere in an expression, and is checked in written order. To use it in arithmetic, wrap it in parentheses: `（… した 中身） + 1`. 成否 and 有無 can't be mixed (convert with `成否にする` and `有無にする`). When the type of the previous value is not determined, it is taken as 成否.
6. **Type checking.** The value of a function containing 「中身」 must be a 成否 (有無) with the same failure type as that 成否 (有無) (`「計算する」の値の型が合いません(（甲 と 文字列） の 成否 と 数)`, "the value type of 「計算する」 doesn't match"). Writing it outside a function (such as an outermost value definition) or inside the continuation of 「してから」 is an error.
7. **Inside a procedure, an action is carried out before looking.** `x とは 道 を 読取した 中身` in a procedure's sentence carries out `読取する` if it is an action and looks at the resulting 成否. On failure the procedure ends there, with that failure as its result (`（甲 と 乙） の 成否 の 動作`). It also works on computations (not actions) that just return a 成否. In a procedure's sentence it can't go in a branch of a conditional (as with 「した 結果」, wrap that part in 「手順（…）」).
8. **「ただし」 value definitions are computed in written order.** Value definitions are normally computed when used, but value definitions using 「中身」 are computed before the body, in written order (`ただし、pとは、xとyを安全除算した中身。`).
9. **A failure in the outermost procedure ends with an error.** If an outermost procedure (`手順（…）。`) uses 「中身」 and its result is a failure, the reason is written to standard error as `エラー: 0 では割れません` ("error: can't divide by 0") and the program exits with code 1 (like Rust's main returning Err).
10. **`m を 試行する` (without 「で」) turns runtime errors into failures.** Leaving out the 「で」 of the standard `試行する` gives an action that carries out m and results in `結果 の 成功` on success, or `エラーの文 の 失敗` (the error message) on a runtime error (`（甲 と 文字列） の 成否 の 動作`). The message is not written to standard error. Existing functions that raise errors can thus be used with 「中身」, as in `本文 とは （道 を ファイル内の読込する） を 試行した 中身`. `m を 代わり で 試行する` is unchanged.
11. **Failures remember where they passed.** Each time 「中身」 returns a failure, its line and function name (`一番外` for the outermost level, `無名関数` for anonymous functions) are added to the failure value as an invisible "path". Comparing and printing ignore the path, so `r が （「a」 の 失敗）` works as before.
12. **`r を 「設定を読む」 で 失敗説明する` layers a description.** On failure it adds the description 「設定を読む」 ("reading the settings"); a success (or a 有無) is returned unchanged. Use it with 「中身」, as in `（（s を 設定読込する） を 「設定を読む」 で 失敗説明した 中身）`.
13. **`r を 失敗詳細にする` turns everything into a string.** The first line is the outermost description followed by 「のに失敗しました」 ("failed to …") (or the reason if there is no description), followed by `  原因: REASON` (cause, when there is a description) and, under `  経路:` (path), the places passed through, from the inside out. Passing a value that is not a failure is a runtime error. When the outermost procedure ends in failure, it is written to standard error in this form too.

```
エラー: 設定を読むのに失敗しました
  原因: 番号は 1〜65535 です
  経路:
    5行目 設定読込する
    6行目 起動準備する
    17行目 一番外
```
14. **`s を 数値確認する` checks whether a string can be a number.** If it can, `数 の 成功`; otherwise `「「abc」は数値にできません」 の 失敗` (`（数 と 文字列） の 成否`). It can be used as `（x を 数値確認した 中身） + 1`. `数値にする` is unchanged: a runtime error if it can't.
15. **`JSON解析する` returns a 成否 too.** `s を JSON解析する` in `「JSON」` is a `（JSON と 文字列） の 成否`. The old `JSON結果` (`JSON成功`, `JSON失敗`) is gone. You can write `（s を JSON解析した 中身） から 「a」 を JSON取得する`.
16. **`f を 試算する` turns runtime errors of pure computations into failures.** f is a function value with all its arguments given (`（「12」 を 番号読取すること）`); it calls it and returns `値 の 成功` on success or `エラーの文 の 失敗` on a runtime error (`（甲 と 文字列） の 成否`). It is not an action, so it can be used inside pure functions, as in `（（s を 番号読取すること） を 試算した 中身） + 1`. It is for converting functions that don't return a 成否 into one on the caller's side.
17. **Caught errors remember where they happened.** A failure caught by `試算する` or by `試行する` without 「で」 has the line and column where the error happened at the head of its path, as `2行目 19文字目(ここで実行時エラー)` ("line 2, column 19 (runtime error here)"). The reason is only the error message, so it can be compared, as in `r が （「「x」は数値にできません」 の 失敗）`.
18. **「xs の それぞれ を f した 中身」 is the list of values if all succeed.** `行 の それぞれ を 数値確認した 中身` becomes the list of inner values if all succeed (有), and returns the first failure (無) immediately if any fail (Rust's `collect::<Result<Vec<_>, _>>()?`). An empty list gives an empty list.

### Connecting out over the network

1. **`ホスト に ポート で 通信内の接続する` connects to a peer.** The result is a connection number (an action), used afterwards like an accepted connection with `行受信する`, `受信する`, `送信する` and `切断する`. The host may be a name (`「localhost」`) or an IP address, and both IPv4 and IPv6 are tried in turn. It is for programs that start the conversation, such as HTTP clients.

```
「通信」 を 読み込む
「標準」 を 読み込んで 使う

始めする とは 以下の手順です
  接続 とは 「localhost」 に 11434 で 通信内の接続した 結果
  「GET / HTTP/1.0」 + 復帰改行 + 復帰改行 を 接続 へ 通信内の送信する
  接続 から 通信内の行受信した 結果 を 表示する
  接続 を 通信内の切断する
  以上です
始めする
```
2. **Outgoing connections have no wait limit.** Accepted connections give up after 5 seconds, but outgoing connections wait until the peer answers. This is because some peers, like a local LLM, take tens of seconds to give the first response.
3. **Failing to connect is a runtime error.** An unresolvable name gives 「「接続する」で通信に失敗しました(Name or service not known)」, and a peer not listening gives 「…(Connection refused)」. Catchable with `試行する`.

### Printing without a newline

1. **`x を 続表示する` prints without adding a newline.** Like `表示する` it is an action whose result is x. It is written out immediately, so you can wait for input after `「あなた> 」 を 続表示する`, or print an answer that arrives bit by bit as one piece. It goes into the same stream as `表示する` lines, in order (the same in the interpreter and compiled binaries).
2. **The name is kanji only.** 「続けて表示する」 ("keep printing") has the hiragana 「けて」 and would need 『』 in the packed style, so it became `続表示する`.

### Calling received functions by name

1. **A parameter that receives a function can be called as its name + 「する」.** If parameter `処理` is a function, it can be called with the particles written in its function type, as in `累 を 行 で 処理する` (the same as `（処理 を 累 に 適用する） を 行 に 適用した 結果`). `処理して`, `処理した 結果` and `処理すること` work too. The same goes for parameters of anonymous functions, local definitions and names bound by patterns.
2. **Parameter names are looked up before outer definitions.** Writing `処理する` inside a function uses a local function `処理する` of the same name if there is one, and otherwise the parameter (or local name) `処理`. Parameters `処理` and `表示` come before outermost definitions in the file and built-in functions (`表示する` and so on).
3. **Type checking checks each particle.** For a parameter with a declared type, `初め を 行 の 先頭 に 処理する` gives 「「処理」は「に」の引数を受け取りません」 ("「処理」 doesn't take a 「に」 argument").

### Cleanup that always runs

1. **`m を 後始末 で 標準内の後始末実行する` carries out 後始末 (cleanup) whether m succeeds or hits a runtime error.** It is a built-in of 「標準」, and both m and 後始末 are actions. The result is m's result; if m hits a runtime error, the cleanup is carried out and the same error (same line and column) continues. Caught with `試行する`, it becomes a failure. Even if reading fails partway after opening a connection, it can be closed with `（接続 を 通信内の切断する）` (finally in other languages).

```
「通信」 を 読み込む
「標準」 を 読み込んで 使う

接続 を 読込する とは 接続 から 通信内の行受信してから 表示する
始めする とは 以下の手順です
  接続 とは 「localhost」 に 8080 で 通信内の接続した 結果
  （接続 を 読込する） を （接続 を 通信内の切断する） で 後始末実行する
  以上です
始めする
```
2. **The cleanup's result is discarded.** The result type of the cleanup action can be anything. If the cleanup itself hits an error, that error continues.
3. **`終了する` doesn't run cleanups.** It is for ending the program on the spot.

### End of input and receiving bytes

1. **`入力確認する` returns the end of input as a 有無.** `「? 」 を 入力確認する` is an action giving `文字列 の 有` if a line could be read, and `無` at the end of input (Ctrl-D) (`文字列 の 有無 の 動作`). `入力する` is unchanged: a runtime error at the end. It is a name from 「基本」, so it can be used without loading anything.
2. **`接続 から n を 通信内のバイト列受信する` receives bytes as they are.** `受信する` makes a UTF-8 string each time it receives, so it breaks when the peer splits in the middle of a character. Receive bytes, join them with `数列にする`, and at the end turn the whole into a string with `バイト列組立して 文字列にする`.

### した 結果 in branches of もし

1. **「した 結果」 can be written in the branches of a 「もし」 in a procedure's sentence.** Writing `本文 とは もし 方法 が 「HEAD」 ならば 「」 そうでなければ 接続 から 長さ を 受信した 結果` carries out only the 「した 結果」 of the chosen branch. That sentence and the rest of the procedure are read as a separate procedure per branch (`もし c ならば 手順（…A…、残り） そうでなければ 手順（…B…、残り）`). The same goes for a 「もし」 comparing with 「が」 (patterns).
2. **「した 結果」 in the condition is carried out first.** The 「した 結果」 in the condition is carried out before choosing a branch. In branches of a 「もし」 in a function body (outside a procedure), it still can't be written (wrap that part in 「手順（…）」).
3. **The same goes for 「した 中身」.** `（a と b を 安全除算した 中身）` in a branch of a 「もし」 in a procedure's sentence is carried out only if chosen, and on failure (無) the procedure ends there with that as its result.

### Error locations inside loaded files

1. **Runtime errors inside loaded files carry the file name.** They look like 「エラー: 「部品.suru」の2行目 7文字目: 「a」は数値にできません」 ("error: line 2, column 7 of 「部品.suru」: 「a」 can't be made a number"), followed by that file's line and a position marker. The same holds inside the standard libraries and 「基本」 (「「基本.suru」の33行目…: 無を取り出しました」, "took out 無"). Interpreter and compiled binaries behave the same.
2. **In binaries, lines of loaded files are counted on after the main file's lines.** The position passed to the runtime library (20 bits for the line) is unchanged, and a table of where each file starts (`suru_file_base` and so on) maps it back to the line within that file. Lines in failure paths (places of 「した 中身」 and `試行する`) are also lines within that file.

### Type names are per file

1. **Types and shapes from a loaded file can also be written as `部品内の応答`.** As with functions, the file name and 「内の」 can be put in front (`（200 と 「ok」 の HTTP内の応答）`, `HTTP内の応答 を 送る は 数`). Inside the same file, no prefix.
2. **Without clashes with other files, no prefix is needed.** You can still write `（5 の 応答）`. Only when two files have a type or shape with the same name do you get the error 「「応答」は「甲」と「乙」の両方にある型か形の名前です。「甲内の応答」のように…」 ("「応答」 is a type or shape name in both 「甲」 and 「乙」. Like 「甲内の応答」…"). Loading both alone is not an error.
3. **Values are printed without prefixes.** As in `（番号 は 5 の 応答）`. Type error messages distinguish them with prefixes like `乙内の応答`.
4. **Types of files in lib/ (the standard libraries) keep a single name.** `成否`, `有無`, `ロック` and the like remain unprefixed names, and `スレッド内のロック` also works. Prefixes apply to types in files you write yourself and in project dependencies (kumu).

### Variables named like types

1. **A word used as a variable or parameter name is read as a variable even if two files have a type of that name.** Words used in that file as variable or parameter names, as in `応答 とは …` or `s に 要求 を 接続 で 案内する とは …`, don't trigger the "Type names are per file" error even when two loaded files have a type of the same name. Where it is used as a type, write it with the prefix, `HTTP内の応答` (the Go version behaves the same).

### Particles of functions called with particles

1. **When a received function is called with particles, the particles of the passed function are checked.** For a function that calls a received function with particles, as in `x を 処理 で 呼出する とは x を 10 で 処理する`, passing a function with different particles (say the rest of `（t で 案内すること）` is 「を」 and 「に」) is a type error (「…が渡されています(受け取る関数は、助詞を付けて呼ばれるので、残りの引数の助詞もそろえてください)」, "… is passed (the received function is called with particles, so make the particles of the remaining arguments match)"). The error points at the line where it was passed. This rule also carries over to functions that only pass the received function on to other functions (`中継する`).
2. **Without particles, matching is by order as before.** Functions that only pass arguments in order, through `適用する` or `畳み込みする`, can receive functions with different particles. Function parameters without declared types are not checked.

### 「を 返す」 at the end of type declarations

1. **A function's type declaration may end with 「を 返す」 ("returns").** `発言 を 発言JSONにする は JSON を 返す` means the same as `発言 を 発言JSONにする は JSON`. Like polite endings, it is decoration for readability with no meaning. The polite `を 返します` works too. In the punctuation style, `数を階乗するは、数を返す。`, and with the particle attached, `数 を返す`, are the same. It can follow any type, as in `（数 と 数） の 点 を 返す` or `数 の 動作 を 返す`.
2. **It can only be written at the end of a function's type declaration.** Writing it in a value's type declaration (`税率 は 数 を 返す`) is an error (「「を 返す」は関数の型の宣言の終わりにだけ書けます」, "「を 返す」 can only be written at the end of a function's type declaration"). So 「返す」 and 「返します」 became reserved words and can't be names (they contain hiragana, so they couldn't be names without 『』 anyway). `… を 返すこと` in anonymous functions and function types is unchanged.
3. **The Go version, the linter and the VS Code extension do the same.** `suruc` (Go) and the lexer and parser written in Suru (`lib/字句.suru`, `lib/構文.suru`) read it the same way, and the VS Code extension colors 「返す」 like 「は」 and 「です」.

### The type 「数 を 返す 動作」

1. **In type declarations, `数 の 動作` can also be written `数 を 返す 動作`.** `WebSocket内の伝言 を WebSocket内の相手 で 返答する は 数 を 返す 動作` means the same as `… は 数 の 動作`. It is a way of writing that reads as "an action returning a number". In the punctuation style, `挨拶するは、数を返す動作。`.
2. **It can be written anywhere in a type declaration.** Also inside parameter types (`（数 を 返す 動作） を 二回する は …`) and function types (`（数 を 受け取って 数 を 返す 動作 を 返すこと）`). Together with the trailing decoration, `… は 数 を 返す 動作 を 返す` works too. Error messages still show `数 の 動作`.
3. **「入出力動作」 is another name for 「動作」.** Actions correspond to Haskell's IO, so to stress in a declaration that something does I/O, you can write `… は 数 を 返す 入出力動作` or `数 の 入出力動作 の リスト`. As a type it is the same as 「動作」, and error messages show 「動作」. The old 「動作」 still works as is.
4. **The Go version and the linter do the same.** `suruc` (Go) and the parser written in Suru (`lib/構文.suru`) read it the same way.

### IO procedures (入出力手順)

1. **「入出力手順」 is a procedure used only for actions (IO).** It is written in the same places and the same way as 「手順」, as in `問い を 接続 で 案内する とは 入出力手順` + deeper lines, or `入出力手順（「a」を表示する。3を結果にする。）`. What it does is the same as 「手順」.
2. **A value that is not an action is a type error.** 「手順」 works with any chainable type (成否, 有無, lists, your own types), but 「入出力手順」 gives an error like 「「入出力手順」の値は動作でなければなりませんが、（数 と 文字列） の 成否になっています」 ("the value of 「入出力手順」 must be an action, but it is a （数 と 文字列） の 成否") if its value is not an action. It reads as a procedure that does I/O, and the checker confirms it. Use it paired with the declaration `… は 数 を 返す 入出力動作`. Procedures over 成否 and the like are still written with 「手順」.
3. **The Go version, the linter and the VS Code extension do the same.** `suruc` does the same check, and the parser written in Suru (`lib/構文.suru`) reads it like 「手順」. The VS Code extension gives it the same color as 「手順」.

### 「という」 in patterns

1. **In patterns, 「s の JSON文字列」 can also be written 「s という JSON文字列」.** In the parameters of case-by-case function definitions and the cases of 「もし … が」, the 「の」 before a shape name can be 「という」 ("called"), as in `（s という JSON文字列） を 文字値取得する とは s`, `もし 形 が` + a deeper line `半径 という 円 ならば …`, `（幅 と 高 という 長方形） を 面積にする とは …` and `横 は a という 点 ならば …`. The meaning is the same. It reads as "take out the contents, naming them s". In the punctuation style, `（半径という円）を面積にするとは、…。`.
2. **Building values uses only 「の」.** As in `「a」 の JSON文字列` and `3 と 4 の 点`, building is still written with 「の」 (「3と4という点」 would read as "a point named 3 and 4"). It doesn't clash with the other use of 「という」, `比較可能 という 性質 とは …`.
3. **The Go version and the linter do the same.** `suruc` and the parser written in Suru (`lib/構文.suru`) read it the same way.

### Bitwise operations, Base64 and SHA-1

Added for the WebSocket (suru-lang/http) handshake and masking. All give the same results in the interpreter and compiled binaries.

```
「標準」 を 読み込んで 使う
「ハッシュ」 を 読み込む

12 を 10 で ビット積にする                       # → 8
「foo」 を バイト列にして Base64符号化する       # → Zm9v
「abc」 を バイト列にして ハッシュ内のSHA1にして ハッシュ内の十六進表記にする  # → a9993e36…
```

1. **Bitwise operations are built-ins of 「標準」.** `a を b で ビット積にする` (AND), `ビット和にする` (OR), `排他的論理和にする` (XOR), and `x を n で 左シフトする` and `右シフトする` (shifts). Integers are treated as two's-complement bit patterns, and right shifts of negative numbers keep the sign. n is 0 to 63, and non-integer numbers are runtime errors. Integers in compiled binaries go up to ±2^62, so left shifts beyond that give 「整数が大きすぎます」 (the interpreter keeps big integers).
2. **`b を 鍵 で バイト列排他和にする` XORs byte sequences.** The key is repeated to the length of b (WebSocket masking uses a 4-byte key). Computing it byte by byte in Suru is slow, so it is a built-in. An empty key is a runtime error.
3. **Base64 is written in Suru in 「標準」.** `b を Base64符号化する` (bytes → string) and `s を Base64復号する` (`（バイト列 と 文字列） の 成否`). Decoding strips surrounding spaces, accepts trailing `=` or its absence, and reads the URL-safe `-` and `_`. Invalid characters or lengths are failures.
4. **SHA-1 is written in Suru in the new 「ハッシュ」.** `b を SHA1にする` gives 20 bytes, and `b を 十六進表記にする` a lowercase hexadecimal string. It is for the WebSocket handshake; collisions have been found, so don't use it for signatures or passwords.
5. **`n を 乱数内の乱数バイト列取得する` gives n bytes (1 to 256) of OS randomness.** An action calling getentropy. Used for the masks and keys of WebSocket clients.
6. **`接続 を 秒 で 通信内の待機時間設定する` changes how many seconds receives and sends wait.** Accepted connections give up after 5 seconds, but connections kept open a long time, like WebSockets, are set to `0` (wait forever). Fractional seconds work. After a timeout failure, reading from the same connection can continue (the binary clears the read flag, and the interpreter recreates its reader).

### SHA-256 and HMAC

Added for signing cookies in the web framework (suru-lang/web). They give the same results in the interpreter and compiled binaries.

```
「標準」 を 読み込んで 使う
「ハッシュ」 を 読み込む

「abc」 を バイト列にして ハッシュ内のSHA256にして ハッシュ内の十六進表記にする  # → ba7816bf…
（「本文」 を バイト列にする） を （「鍵」 を バイト列にする） で ハッシュ内のHMACSHA256にする
```

1. **SHA-256 and HMAC-SHA256 are also written in Suru in 「ハッシュ」.** `b を SHA256にする` and `b を 鍵 で HMACSHA256にする` (RFC 2104) both give 32 bytes. A key longer than 64 bytes is hashed with SHA-256 first.
2. **Not for passwords.** A single hash is too fast for storing passwords. Use a slow function made for it, such as bcrypt or Argon2.

### Small Suru for microcontrollers

1. **Microcontroller targets use a separate code generator with no heap and no GC.** `kumu 作る` (with a target) and `suruc --対象 …` decide value types from the type checker's results and generate LLVM IR with numbers as 32-bit integers, booleans as 0 and 1, and string constants as addresses placed in flash. The runtime library is `runtime/avr/suru_avr.c` (main, clock, pins, PWM, A/D conversion, serial). To fit in the Uno's 2KB of RAM, constructs that build values on the heap are not available.
2. **What you can use: definitions, もし, case-by-case definitions (on number and boolean values), ただし, 手順, した 結果, してから, recursion, and arithmetic on numbers and booleans.** Anything else (lists, decimals, anonymous functions, すること, それぞれ, records, traits, 入力する, string concatenation and so on) gives a compile error such as 「マイコン向けでは、リストは使えません」 ("lists can't be used for microcontrollers").
3. **Actions are carried out right where they are called.** The result is the same as carrying them out in a procedure or at the top level. Passing actions as arguments or putting them in lists to carry out later is not available. An action given a name, as in `挨拶 とは 「やあ」 を 表示する`, is carried out each time it is used.
4. **Loops that call themselves at the end of a function become loops.** The final `点滅する` in `点滅する とは 手順` uses no stack. Loops of two functions calling each other also become loops through clang's optimization.
5. **Numbers are 32 bits.** From -2147483648 to 2147483647, wrapping on overflow (no error). There are no decimals, so `/` is truncating division (`-7 / 2` is -4), and `%` is the remainder in the same direction as the interpreter. Dividing by 0 prints an error on the serial port and stops.
6. **Printing goes to the serial port.** `表示する` writes to serial (9600, lines end with CR LF). Only inside the 「を」 of `表示する` can strings be joined with +, and `文字列化する` can be used, as in `「温度: 」 + （t を 文字列化する） を 表示する` (they are just sent in order; no joined string is built). Booleans print as 「真」 and 「偽」.
7. **Functions without a fixed type are generated per argument type.** Calling `x を 二回表示する` with a number and with a string makes two functions.
8. **Pin numbers are the same as Arduino's.** `lib/マイコン.suru` has functions for pin direction, output, reading, A/D conversion, PWM, waiting, elapsed time and serial, plus `内蔵灯` (13), the pin of the board's LED. C functions can be declared with `外部の「…」` and called directly (string arguments are flash addresses, so read them in C with pgm_read_byte).
9. **It doesn't run in the interpreter.** The microcontroller library's functions exist only on the board, so they can't run with `suru` or `kumu 実行` (`kumu 実行` tells you to flash instead). Currently only the Go `suruc` and kumu can build for it.

### Networking examples (echo server and client)

`examples/通信/` has two programs using 「通信」 (TCP). Run `suru examples/通信/エコーサーバー.suru` in one terminal and `suru examples/通信/エコークライアント.suru` in another, and the lines you type come straight back (`nc localhost 9000` also connects).

1. **The server handles each connection on its own thread.** It passes `口 から 通信内の接続受付した 結果` to `スレッド内の並行開始する`, so any number of clients can connect at once. Accepted connections give up after 5 seconds, so it sets `通信内の待機時間設定する` to 0 (wait forever). If a client drops midway, `試行する` catches it, and `後始末実行する` always closes the connection.
2. **The client keeps going until the end of input.** It reads line by line with `入力確認する` and ends on Ctrl-D (`無`). If the server closes, it prints 「相手が閉じました」 ("the other side closed") and ends.
3. **They wait forever, so they aren't directly in examples/.** The tests compare the output of examples/*.suru, so these are in a subfolder. `tests/test_net_examples.py` switches them to a free port and really connects, with both the interpreter and compiled programs (they are also included in type checking, linting and comparing the Go version's IR).

### UDP

`「通信」 を 読み込む` also gives you UDP, just like TCP. UDP makes no connection; it sends and receives messages (datagrams) one at a time. They may not arrive, and may arrive out of order.

```
「通信」 を 読み込んで 使う

口 を 返し続けする とは 以下の入出力手順です
  便 とは 口 から UDP受信した 結果
  （便 の 中身） を 口 から 便 へ UDP返信する
  口 を 返し続けする
  以上です

始めする とは 以下の入出力手順です
  口 とは 9001 を UDP開始した 結果
  口 を 返し続けする
  以上です
始めする
```

| Syntax | Result (all are actions) |
|---|---|
| `ポート を 通信内のUDP開始する` | The number of a UDP socket (receives on that port of 0.0.0.0; with 0 the OS picks one) |
| `文字列 を 口 から ホスト に ポート で 通信内のUDP送信する` | The number of bytes sent (the host is a name or an IPv4 address) |
| `バイト列 を 口 から ホスト に ポート で 通信内のUDPバイト列送信する` | The number of bytes sent |
| `口 から 通信内のUDP受信する` | A `UDP便` holding the next whole message (contents as a UTF-8 string) |
| `口 から 通信内のUDPバイト列受信する` | A `UDP便` whose contents are bytes |
| `文字列 を 口 から 便 へ 通信内のUDP返信する` | Sends to the message's sender (bytes with `UDPバイト列返信する`) |

1. **Received messages are `UDP便` records.** `UDP便 とは 中身 と 送り主 と ポート の 組`: the sender is an IP address string (`「127.0.0.1」`), and the port is the sender's port. Depending on the contents, the type is `（文字列 と 文字列 と 数） の UDP便` or `（バイト列 と 文字列 と 数） の UDP便` (declarations can just say `UDP便`). One receive takes one whole message (up to 65536 bytes).
2. **Sockets share the number table with TCP.** `口 を 秒 で 通信内の待機時間設定する` sets how many seconds a receive waits; a timeout is a runtime error (catch it with `試行する`). Close with `口 を 通信内の切断する`. One socket can send to anyone and receive from anyone. To only send, make a socket with `0 を UDP開始する`.
3. **Failures are runtime errors.** They look like 「「UDPバイト列送信する」で通信に失敗しました(Name or service not known)」. The string versions `UDP送信する` and `UDP受信する` are written in Suru in lib/通信.suru, so errors show the names of the built-ins they call (`UDPバイト列送信する`, `UDPバイト列受信する`).
4. **There are three built-ins.** `UDP開始する`, `UDPバイト列送信する` and `UDPバイト列受信する` are built-ins (interpreter, runtime library, the Go type checker, the linter); the rest is written in Suru in lib/通信.suru. IPv6 is in "Broadcast, multicast and IPv6".
5. **Examples are `examples/通信/UDPエコーサーバー.suru` and `UDPエコークライアント.suru`.** The server sends each received message back to its sender, and the client sends the lines you type and prints the reply (if there is no reply within 2 seconds, 「(返事がありません)」, "(no reply)"). `nc -u localhost 9001` can send too. The tests are in `tests/test_udp.py`.

### Getting listening addresses and ports

Additions for TCP listeners and connections and UDP sockets (stage 2 of #123).

```
「通信」 を 読み込んで 使う

始めする とは 以下の入出力手順です
  口 とは 0 を 「127.0.0.1」 に 待受開始した 結果   # only from this machine; the OS picks the port
  「ポート 」 + （口 を ポート取得して 文字列化する） + 「 で待っています」 を 表示する
  受 とは 口 から 接続受付した 結果
  「相手: 」 + （受 を 相手アドレス取得した 結果） を 表示する
  以上です
```

1. **`ポート を アドレス に 待受開始する` chooses the address to listen on.** With `「127.0.0.1」`, only the same machine can connect. Leaving out 「に」 gives 0.0.0.0 (all) as before. UDP can be written `ポート を アドレス に UDP開始する` too. The address is an IPv4 address or a name (`「localhost」`); if it can't be resolved, you get the runtime error 「「待受開始する」で通信に失敗しました(…)」.
2. **`口 を ポート取得する` is the local port.** It works on listeners, connections and UDP sockets (getsockname). Use it to learn the port chosen when you opened port 0 and let the OS pick (as when tests use a free port).
3. **`接続 を 相手アドレス取得する` and `接続 を 相手ポート取得する` give the connected peer.** The peer's IP address as a string, and its port (getpeername). Useful for logs and access restrictions. On an unconnected UDP socket it is 「通信に失敗しました(Transport endpoint is not connected)」 (a UDP sender is in the received `UDP便`).
4. **All are actions and built-ins.** The same in the interpreter, runtime library, the Go type checker and the linter. The tests are in `tests/test_net_addr.py`.

### Foreign functions called on the main thread, and single precision

Added to wrap GUI libraries (SDL3 and others). macOS windows can only be operated from the process's first thread (the main thread). Compiled programs run on a separate thread with a large stack for deep recursion, so as is they can't create windows.

```
外部の「SDL3」 を 主スレッドで 読み込む

整数 を 初期化する は 真偽
フラグ を 初期化する とは 外部の「SDL_Init」
単精度 を 単精度 で 番地 に 点描画する は 真偽
x を y で 描き手 に 点描画する とは 外部の「SDL_RenderPoint」（描き手 と x と y）
```

1. **Foreign functions in a file that writes `外部の「m」 を 主スレッドで 読み込む` ("load on the main thread") are called on the main thread.** Every foreign function in that file is called on the main thread (it is per file, not per library, so keep the wrapping library in its own file). In compiled programs, the main thread waits for work, and the program's thread passes the arguments and waits for completion. Calls from code running concurrently also happen on the main thread. errno (`エラー番号取得する`) is carried back to the calling thread too. Each call goes back and forth between threads, so it is a little slower than an ordinary foreign function (a few microseconds).
2. **The interpreter can call them only from the first thread.** The interpreter runs the program on the first thread, so it calls them directly. Calling from concurrently running code is a runtime error (compiled programs can).
3. **In a forked child, they are called on the spot.** No main thread is left in a child process.
4. **`単精度` is C's `float`.** Like `小数`, it is the same type as `数` inside Suru. Passed as an argument it is rounded to float, and return values are converted back to double. It was added for functions taking floats by value, such as SDL3's coordinates. The interpreter and both the Python and Go compilers behave the same.

### Broadcast, multicast and IPv6

Additions for UDP sockets and listeners (stage 3 of #123).

```
「通信」 を 読み込んで 使う

始めする とは 以下の入出力手順です
  受 とは 9002 を UDP開始した 結果
  受 を 「239.1.2.3」 に マルチキャスト参加する      # also receive messages sent to this group
  送 とは 0 を UDP開始した 結果
  「みなさん」 を 送 から 「239.1.2.3」 に 9002 で UDP送信する
  送 を ブロードキャスト許可する
  「全員」 を 送 から 「255.255.255.255」 に 9002 で UDP送信する
  以上です
```

1. **`口 を ブロードキャスト許可する` allows sending to broadcast addresses.** Sending to addresses such as `255.255.255.255` or `192.168.1.255` from a socket that hasn't allowed it gives 「通信に失敗しました(Permission denied)」 (SO_BROADCAST). The result is the socket.
2. **`口 を アドレス に マルチキャスト参加する` receives a group's messages.** `口 を アドレス から マルチキャスト離脱する` leaves it. The address is an IPv4 address from `224.0.0.0` to `239.255.255.255`, or an IPv6 address starting with `ff`. Anything else is the runtime error 「「10.0.0.1」はマルチキャストのアドレスではありません(…)」 ("「10.0.0.1」 is not a multicast address"). The receiving socket must have done `UDP開始する` on the port being sent to. Sending to multicast is the usual `UDP送信する` (its reach is the OS default, only within the same network).
3. **For IPv6, write an IPv6 address in 「に」.** `0 を 「::1」 に UDP開始する` and `8080 を 「::」 に 待受開始する` make IPv6 sockets. IPv6 UDP sockets send to IPv6 addresses (`「::1」` or names). Senders and `相手アドレス取得する` show addresses like `::1`. Without 「に」, or with a name, it is IPv4 as before. The outgoing `接続する` already tries both IPv4 and IPv6.
4. **All are actions and built-ins.** The same in the interpreter, runtime library, the Go type checker and the linter. The tests are in `tests/test_udp_multicast.py` (skipped on machines where multicast to oneself doesn't arrive, and on machines without IPv6).

### 「」 inside strings

1. **「」 inside a string are counted as nesting.** `「失敗: 「abc」は数にできません」` is one string. Each 「 goes one level deeper and each 」 one level shallower, and the string ends at the 」 matching the first 「. To include a single unmatched 「 or 」, make it with `12300 を 文字にする` (「) or `12301 を 文字にする` (」). The VS Code highlighting and the 「字句」 library (used by the linter) read them the same way. `「「」` (a one-character string 「), which used to be writable, is now an unclosed-string error.

### Test files with the same name

1. **When loading a file with the same name as itself, the file skips itself in the search.** `「会話帳」 を 読み込む` in `試験/会話帳.suru` looks for `会話帳.suru` not in itself but in dependencies, then the top of the project (the folder with 組.suru), then the standard lib. If none is found, it is the error 「自分自身を読み込むことになります」 ("this would load itself"). The interpreter, the Go compiler and the language server behave the same.

### 「と」 in type declarations

1. **Joining parameter types with 「と」 accepts things whose elements have different types.** Declaring `文字列 と JSON を 一項目にする は JSON` makes 「名」 in the definition `名 と 値 を 一項目にする とは …` a string and 「値」 a JSON. At the call site, `「a」 と v を 一項目にする` is checked element by element too. Without a declaration, a parameter with 「と」 is a same-typed list as before. Such types are printed as `（文字列 と JSON）`.

### Function names not ending in 「する」

1. **If a function name doesn't end in 「する」, the error names it.** `数 で 流す は 数 を 返す 入出力動作` (a type declaration) and `x で 流す とは x` (a definition) give 「関数名は「する」で終わる必要があります(「流す」)」 ("function names must end in 「する」 (「流す」)").

### Typed reads and writes of C memory

Added to build C struct fields and `char **` arrays (for reading and writing `rmw_qos_profile_t` and the like in rclsuru). Previously you copied with `p から n を バイト列取得する` and then assembled byte by byte.

```
「標準」 を 読み込んで 使う
-5 を p へ 8 で 符号付き32書込する
p から 8 で 符号付き32読取する          # -5
（p を 8 で 番地加算する） から 0 で 符号なし8読取する
```

1. **`p から 位置 で TYPE読取する` and `x を p へ 位置 で TYPE書込する` read and write one value at 位置 bytes past address p.** The types are `符号付き8`, `符号付き16`, `符号付き32`, `符号付き64` (signed), `符号なし8`, `符号なし16`, `符号なし32`, `符号なし64` (unsigned), `単精度` (float), `小数` (double), `番地` (pointer), `真偽` (a 1-byte C bool; true if not 0) and `C文字列`, written followed by the verb, as in `符号付き32読取する` and `符号付き32書込する`. They are standard built-ins and all actions. The offset is an integer number of bytes and may be negative. The result of a write is the number of bytes written.
2. **`C文字列` is NUL-terminated UTF-8 laid out at that place.** `C文字列読取する` reads from the offset up to the NUL, and `C文字列書込する` writes the UTF-8 bytes and a NUL (the result is the byte count including the NUL). For a struct's `char *` field, read the address with `番地読取する`, then read from that address with `C文字列読取する`. Strings containing character code 0 can't be written. It isn't named `文字列読取する` to avoid clashing with the function of that name in the 「字句」 library.
3. **Numbers that don't fit are errors.** `256 を p へ 0 で 符号なし8書込する` gives 「「256」は符号なし8に入りません(0 から 255 までの整数です)」 ("「256」 doesn't fit in 符号なし8 (it is an integer from 0 to 255)"), and `1.5` for an integer type gives the same error (integral decimals like `2.0` are fine).
4. **64-bit integers are limited to the integer range of compiled programs (±2^62).** `符号付き64` and `符号なし64` can't write numbers beyond ±2^62, and reading a value beyond it is the runtime error 「符号なし64の値 … が大きすぎます」 ("the 符号なし64 value … is too large") (the same as `int64_t` values of foreign functions).
5. **Address 0x0 is never read or written.** Reading from NULL gives 「番地(0x0)からは読み取れません」 and writing to NULL gives 「番地(0x0)へは書き込めません」. Other addresses are not validated (as in C, mistakes crash).
6. **`p を n で 番地加算する` is the address n bytes ahead.** The same as `（p を 番地数値にする） + n を 番地にする`; a pure function.
7. **The interpreter and both the Python and Go compilers behave the same.** The interpreter reads and writes with `ctypes` and `struct`, compiled programs with the runtime library. Only little-endian (x86-64, arm64) is considered.

### Shapes of C structs (C形)

Added to move whole C structs to and from records. Layouts mixing `int32_t`, `uint8_t`, `float`, pointers, fixed-length arrays and nested structs, with alignment and padding, can be read and written without counting field offsets by hand. `固定直列化する` in "Fixed layouts and fixed regions" handles only layouts where every field is 8 bytes.

```
「標準」 を 読み込んで 使う
時間 とは 秒 と ナノ秒 の 組
時間形 とは （0 と 0 の 時間） を （「符号付き32」 と 「符号なし32」） で C形作成する
品質 とは 履歴 と 深さ と 期限 と 印 の 組
品質形 とは （0 と 0 と （0 と 0 の 時間） と 空 の 品質） を （「符号付き32」 と 「符号なし64」 と 「構造体」 と 「符号なし8[3]」） で C形作成して 3 で 時間形 に 入れ子設定する
品質形 を C大きさにする                       # 32 (sizeof)
x とは p から 0 で 品質形 を 構造体読取した 結果     # inside a procedure
```

1. **`見本 を 欄の型の一覧 で C形作成する` makes a "C形" (C shape) linking a record type to a C layout.** The sample is a record with fields, and values of its shape (`時間` in the example above) are read and written. Field types are written as strings in the order of the sample's fields; the available types are the same as in "Typed reads and writes of C memory", `符号付き8` to `符号付き64`, `符号なし8` to `符号なし64`, `単精度`, `小数`, `番地`, `真偽` (1 byte), plus `構造体` (struct). Adding `[COUNT]`, as in `「符号なし8[16]」`, makes a fixed-length array, and that field is a list of that many elements (COUNT is 1 to 1048576). It is an error if the number of field types differs from the number of fields, or if a sample field doesn't suit its type (a string for a `符号付き32` field and so on).
2. **A `構造体` field gets its inner shape from `形 を 番号 で 中の形 に 入れ子設定する`.** The number is the field's number counting from 1, and the result is a new C形 with the inner shape set (they can be chained: `…して 3 で 時間形 に 入れ子設定して 4 で 時間形 に 入れ子設定する`). `「構造体[2]」` is an array of two records of the inner shape. Asking for the size of, or reading and writing, a shape whose inner shape isn't set is an error. C形 values can't go into a list of a single type, so nesting is set field by field like this.
3. **The layout follows C's rules.** Each field is placed at a multiple of its size (for arrays, the element's; for structs, the largest inside), and the total size is a multiple of the largest alignment. `形 を C大きさにする` is sizeof, `形 を C揃えにする` the alignment, and `形 を 番号 で C位置にする` the number corresponding to offsetof. Only the ordinary rules of today's OSes and CPUs (x86-64 and arm64) are handled, not `#pragma pack` or bit fields.
4. **`p から 位置 で 形 を 構造体読取する` and `x を p へ 位置 で 形 に 構造体書込する` move to and from memory.** Both are actions. A write writes the whole including padding (padding is 0), and its result is the number of bytes written. Address 0x0 is never read or written.
5. **`x を 形 で C直列化する` and `b を 形 で C復元する` move to and from byte sequences.** A byte sequence whose length differs from the C形's size is an error. Values out of range (300 for `符号なし8` and so on) or arrays with the wrong number of elements give errors naming the field.
6. **The type is `時間 の C形`.** It can be written in type declarations too, as in `時間 の C形 を 大きさ取得する は 数`. Passing a record of another shape to `C直列化する` is caught by the type checker. C形 values print as `<C形 時間>` and can't be serialized ("Value serialization and セマフォ内実行する").
7. **The interpreter and both the Python and Go compilers behave the same.** The tests check that results match the sizeof and offsetof decided by the C compiler.

### Callbacks from C

C functions that take function addresses (the comparison function of `qsort`, event watchers, ROS 2 rcl's "call this when a new message arrives" functions and so on) can now be used. There are two forms, called in different ways.

```
「標準」 を 読み込んで 使う
f とは 比較すること を 「番地 と 番地」 で 「整数」 に 呼び戻し番地作成した 結果   # inside a procedure
p を 5 で 8 に f から 並べ替えする                                          # qsort(p, 5, 8, f)
f を 呼び戻し解放する

「スレッド」 を 読み込んで 使う
新着 とは 相手 と 件数 の 組
c とは プロセス間通路作成した 結果
g とは （0 と 0 の 新着） を c へ 「番地 と 数」 で 通路送り番地作成した 結果
（c から 通路受信した 結果） を 表示する      # （相手 は 42 で 件数 は 1 の 新着）
```

1. **`f を 「ARGUMENT TYPES」 で 「VALUE TYPE」 に 呼び戻し番地作成する` makes the address of a C function that calls the Suru function f.** It is a standard built-in and an action. The argument types are `数` (int64_t), `整数` (int), `小数` (double), `単精度` (float), `真偽` (int), `文字列` (const char *; NULL is 「」) and `番地`, joined with `と` (at least one), and the value type is one of them (except 文字列) or `無` (void). When called from C, it passes the arguments to f in definition order (a and b for `a を b で 比較する`), carries out f's value if it is an action, and returns the result to C converted to the value type.
2. **It can only be called on the same thread, while a foreign function is being called.** This is the form where a C function called from Suru calls back before returning, as qsort does. If it is called from a thread Suru doesn't know or after the foreign function has returned, it prints 「呼び戻しの番地が、外部の関数を呼んでいる途中ではないところ(ほかのスレッドなど)から呼ばれました」 ("the callback address was called from outside a foreign function call (another thread or the like)") and stops the program. Callbacks from functions called on the main thread ("Foreign functions called on the main thread, and single precision") fall into this case too.
3. **Errors inside a callback become errors after the foreign function returns.** These are runtime errors inside f, or values that don't fit the value type (「外部の関数「呼び戻し」の「を」には数が必要です」, "the 「を」 of the foreign function 「呼び戻し」 needs a number"). Compiled programs don't show the error location.
4. **`見本 を 通路 へ 「ARGUMENT TYPES」 で 通路送り番地作成する` is an address that, when called, just sends its arguments as a record to a channel.** It is a built-in of 「スレッド」 and an action. It can be called even from threads Suru doesn't know (such as DDS's receive thread). No Suru code runs on the C thread: it serializes a record of the same shape as the sample (with the arguments put in its fields in definition order), writes it to the pipe, and returns at once (the value is `無`). The Suru side receives with `通路受信する` or `通路処理する` as usual, so the threading rules don't change. Make the channel with `プロセス間通路作成する`, and use one that has not yet received anything (it holds a duplicate of the pipe's write end). `番地` arguments arrive as numbers made with 番地数値にする, so make that field of the sample a number (convert back with `番地にする`). If nobody receives, they are discarded.
5. **When done, release it with `p を 呼び戻し解放する`.** A created address is protected from the GC until released. Addresses use entry points prepared in advance, so there can be at most 32 at a time per kind of return value (integer kinds, `小数`, `単精度`).
6. **Implementation.** The entry points are C functions in the runtime library that take 8 integer-register arguments and 8 floating-point-register arguments, picked out in the order of the declared types. So arguments are limited to 6 of the integer kinds and 8 of 小数/単精度 (the range passed in registers), and only x86-64 (System V) and arm64 are supported. Callbacks that take structs by value or variadic callbacks can't be made. The interpreter makes them with ctypes' `CFUNCTYPE`. The interpreter and both the Python and Go compilers behave the same.

### kumu's Cソース, C引数 and リンク引数

Suru libraries that wrap C libraries can now carry small C files with them (wrapping functions that pass structs by value, or macros). Users can use them with just `kumu 追加`, without first building a .so with `cc -shared`. Libraries without pkg-config, such as ROS 2, can be linked by writing the arguments directly.

```
名前 とは 「rcl」
版 とは 「0.1.0」
Cソース とは 「c/包み.c」
C引数 とは 「-I${ROS_PREFIX}/include/rcl」
リンク引数 とは 「-L${ROS_PREFIX}/lib -lrcl -Wl,-rpath,${ROS_PREFIX}/lib」
```

1. **kumu compiles the C files listed in `Cソース` (C sources) in 組.suru with clang and links them in.** Paths are from the project folder; several are joined with `と`. The Cソース of the project and all its dependencies are used. Functions inside can be called with `x を 包む とは 外部の「wrap_x」` without writing `外部の「…」 を 読み込む`. The same goes for `作る`, `実行`, `試験` and the tests of `公開`.
2. **`C引数` (C arguments) is used only when compiling that project's Cソース, and `リンク引数` (link arguments) when linking.** All リンク引数 of dependencies are used too. In both, `${NAME}` is replaced by the environment variable, then the result is split on spaces and passed to clang. If an environment variable used is unset, it is the error 「「rcl」のC引数「…」に使う環境変数「ROS_PREFIX」がありません」 ("the environment variable 「ROS_PREFIX」 used in 「rcl」's C引数 「…」 is not set") (going ahead with it empty would lead to confusing link errors). There is no syntax for splitting `:`-separated values like `AMENT_PREFIX_PATH`.
3. **Built objects go in `出力/.c/` and aren't rebuilt if nothing changed.** A fingerprint is made from the C source, headers (`.h`) in the same folder, C引数 and the C compiler. Changes to headers in other folders aren't seen, so delete `出力/.c/` in that case. The binary rebuild check (stamp) now includes Cソース, headers and arguments. The content hash of dependencies (組.lock) already covered every file in the folder, so C sources are included.
4. **It works in the interpreter (`suru`) too.** It searches upward from the program's folder for 組.suru, builds the Cソース of that project and of the dependencies in 組.lock into one shared library in `~/.kumu/C/` (`KUMU_HOME`), and also looks up foreign functions there (after loaded libraries, before libc). If the contents are the same, it isn't rebuilt.
5. **`suru --翻訳` and `suruc` don't use Cソース.** Only kumu and the interpreter read project settings. Projects for microcontrollers (`対象`) can't use it yet.
6. **It can be written separately from external dependencies (pkg-config).** What pkg-config can check goes in `外部依存` ("External dependencies (system C libraries)"), and what it can't goes in リンク引数.

### JSON output for errors and lint reports

1. **With `--json`, errors and lint reports are printed as one JSON per line.** It works with `suru --検査 --json a.suru`, `suru --点検 --json a.suru`, `suru --json a.suru` (run), `suru --翻訳 --json`, the Go `suruc --json`, and `kumu 点検 --json`. The form is `{"file":"a.suru","line":3,"column":7,"kind":"型","rule":null,"message":"…"}`. This lets AI, editors and scripts fix errors without parsing the text output.
2. **Keys are English, kind values are Japanese.** `kind` is one of `構文` (syntax), `型` (type), `実行` (runtime), `コンパイル` (compile) and `点検` (lint), and `rule` is the name of the lint rule (only for lint; otherwise `null`). `line` and `column` count the same way as the usual 「何行目 何文字目」 (line N, column M), and are `null` when unknown.
3. **Errors inside loaded files give that file's position.** The text output still reports at the loading line, as 「「部品.suru」の2行目 15文字目: …」, but in JSON `file` is the path of 部品.suru and `line` and `column` are the position inside it.
4. **Output streams and exit codes are the same as without it.** Errors go to standard error and lint reports to standard output, with exit code 1 if there are problems. With no problems nothing is printed (not even `--検査`'s 「型の検査で問題は見つかりませんでした」, "no problems found in type checking"). When running, write `--json` before the program file (what follows are arguments to the program).
5. **The Python and Go versions behave the same.** `suruc --検査` was added so the Go version can check only syntax and types. Both print the same JSON. For lint, `lib/点検.suru`, written in Suru, takes `--json` and prints it.

### Undefined names and lists of actions

1. **Undefined names are type errors.** Typos inside branches or functions that are never called are reported before running by `suru --検査`, `suruc` and `kumu 作る`, as `「三培する」は定義されていません(「三倍する」のことですか)` ("「三培する」 is not defined (did you mean 「三倍する」?)") (#149). Previously they were errors only when execution reached that line, so you couldn't notice even by building a binary.
2. **Errors come with hints on how to fix them.** If the name contains an operator, 「演算子の前後に空白を入れてください」 ("put spaces around the operator") (because packing `x*2` in the spaced style makes it one name); if it is a built-in of 「標準」, 「通信」 or 「スレッド」 that isn't loaded, 「「標準」 を 読み込んで 使う と書くと使えます」 ("write 「標準」 を 読み込んで 使う to use it"); if there is a close name, 「「…」のことですか」 ("did you mean 「…」?"). The close name is the nearest among visible names and built-ins whose differing characters are at most a third of the name's length (at least 1 character) (on a tie, the one first in character-code order). The Python and Go versions pick the same one.
3. **When checking a file in lib/ itself, its built-ins are visible.** Checking `suru --検査 lib/標準.suru`, for example, treats built-ins such as `切捨する` as available (the Go version does so also for files with the same contents as the bundled ones).
4. **Names loaded by a loaded file are visible to the type checker too.** At runtime, if 部品.suru in `「部品」 を 読み込んで 使う` itself writes `「標準」 を 読み込んで 使う`, the standard names (built-ins included) can be used without a prefix. The type checker follows this and doesn't treat them as undefined.
5. **A sentence in a procedure that is a "list of actions" is an error.** `xs の それぞれ を 表示する` only builds a list of print actions, so writing it in a procedure printed nothing (silently ending as the last sentence, or giving a confusing error in the middle). If the value of a procedure's sentence is a list of actions, it is now 「この文は動作のリストを作るだけで、行いません。行うには「を 実行する」を付けてください」 ("this sentence only builds a list of actions and doesn't carry them out; add 「を 実行する」 to do so") (#151).

### 「と」 parameters of anonymous functions

1. **In `a と b を 受け取って`, a and b may have different types.** The 「と」 parameters of an anonymous function are checked as a list whose elements each have their own type (the same thing as 「文字列 と 数 を」 in type declarations). This allows folds whose accumulator and element types differ, as in `（「a」 と 「bb」） を 0 から （n と s を 受け取って n + （s の 長さ） を 返すこと） で 畳み込みする` (#150). Previously a and b were forced to the same type, giving errors such as 「初期値(数)と要素(文字列)の型が違います」 ("the initial value (number) and the elements (string) have different types").
2. **They also unify with lists whose elements share one type.** A list with per-element types and a list of same-typed elements unify when the element types agree. Passing `a と b を 受け取って` as "a function taking a list of numbers" still works. A function declared as `数 と 数 を …` can also be given a list-of-numbers value (the length is checked at runtime).

### Deep recursion in the interpreter

1. **The interpreter also runs recursion about 200,000 levels deep.** Previously Python's recursion limit was 10000, and Suru recursion stopped at about 3000 levels (the standard `整列する` stopped on a reversed list of 2000 items). From Python 3.12, calling a Python function no longer uses the C stack, so the limit is now 1,000,000 (one Suru level is roughly 3 to 4 Python levels) (#152). Stopping takes about 1GB of memory and a few seconds. Up to Python 3.11 it stays at 10000 so the C stack doesn't overflow.
2. **When it stops, it is a Suru error.** Previously the Python traceback (over 1MB) was printed as is. When running a file and with `--検査`, it now prints `エラー: 再帰が深すぎます(もっと深い再帰は、suruc か suru --翻訳 でコンパイルすると動きます)` ("recursion too deep; deeper recursion works when compiled with suruc or suru --翻訳"), the same as the interactive mode, and with `--json` it prints JSON (`line` and `column` are `null`).

### Sorting (整列する and 基準整列する)

1. **`整列する` is a builtin stable merge sort.** It was a quicksort written in Suru in `lib/標準.suru`. Because lists are arrays, each step copied the list, and a sorted list of 40000 numbers took a long time (and on the interpreter, a reversed list of 2000 items exceeded the recursion limit) (#153). It now takes O(n log n) in the interpreter, `suruc` and `suru --翻訳`. Equal elements keep their original order.
2. **Lists of strings can be sorted too.** `（「b」 と 「a」） を 整列する` gives `（「a」 と 「b」）`. Strings compare the same way as 「<」 (by character code). Elements must be all numbers or all strings; other element types are type errors (「「整列する」のリストの要素は数か文字列です」).
3. **`基準整列する` sorts by a key.** `xs を f で 基準整列する` sorts in ascending order of the value f returns for each element, which must be a number or a string. For example, `（「bb」 と 「a」 と 「ccc」） を （s を 受け取って s の 長さ を 返すこと） で 基準整列する` gives `（「a」 と 「bb」 と 「ccc」）`. f is called once per element. For descending order, use a key like `0 - x`, or `逆順にする` after sorting.

### Guide for AI

1. **A guide for AI to read first is in [docs/AIの手引き.md](docs/AIの手引き.md).** It gathers the essentials of the grammar, common mistakes and how to fix them, and how to run checks, lint and tests, in one file (in Japanese). `CLAUDE.md` and `AGENTS.md` point to it.
2. **The guide's code examples are verified by tests.** `tests/test_ai_guide.py` checks that ` ```suru ` examples pass the type check and that ` ```suru-誤り ` examples are errors, so the guide doesn't drift from the language.

### The steps below and 以上

1. **The sentences from `X とは 以下の手順です` to `以上` are a procedure.** Write the sentences on deeper lines, or continue at the same indent. Write `以上` as the last deeper line or on a line at the indent of the head. Unlike `手順（…）`, no parenthesis stays open over many lines, and the start and end read like a Japanese document ("the steps below are … that is all") (#161). `以下 の 手順` (without です), `以下の入出力手順です` (checked like 「入出力手順」) and `以上です` work too. `手順（…）` and `… とは 手順` + deeper lines work as before.
2. **「以上」 is required.** 「以下の手順です」 and 「以上」 are a pair, so forgetting it gives 「「以下の手順です」を閉じる「以上」がありません」 ("there is no 以上 closing 以下の手順です"), no sentences between them give 「「以下の手順です」と「以上」の間に文がありません」, and a 「以上」 with no 「以下の手順です」 gives 「対応する「以下の手順です」のない「以上」があります」.
3. **In the punctuation style, sentences separate them.** As in `挨拶するとは、以下の手順です。「a」を表示する。「b」を表示する。以上です。`, the sentences up to 「以上。」 are the procedure's sentences. The lines after 「以下の手順です。」 may be indented.
4. **It can be written in a branch of a case analysis.** As in `そうでなければ 以下の手順です` + deeper lines + `以上`, it can go anywhere an expression can (the same as writing `手順（…）` there). For the `ならば` branch, see "そうでなければ after a procedure in the `ならば` branch".
5. **「以上」 also closes the innermost 「もし 値 が」.** It is optional, and used to write a nested case analysis on one line or in the punctuation style. In `もしxが1ならば、もしyが1ならば「a」、2ならば「b」以上です、2ならば「c」、そうでなければ「d」。` the inner case analysis ends at 「以上」, and `2ならば「c」` is a case of the outer one.
6. **Indentation also ends a nested case analysis.** When a line shallower than the cases of the inner 「もし 値 が」, at the indent of the outer cases, comes, the inner one ends there. Previously the inner case analysis took the outer cases after it (`2 ならば 「c」` or `そうでなければ …`) as its own.
7. **Everything reads it the same way.** The Python version, the Go version (`suruc`), the lexer and parser written in Suru (`lib/字句.suru`, `lib/構文.suru`), the linter, the VS Code extension's highlighting and the interactive mode (which reads up to 「以上」 before running) treat it the same. The example is `examples/blocks.suru`.
8. **そうでなければ after a procedure in the `ならば` branch.** After `もし … ならば 以下の手順です` + deeper lines + a deeper `以上`, a `そうでなければ …` line can follow at the indent of the `もし` line (#190). The procedure is closed by the deeper `以上`, and the case analysis continues from the next `そうでなければ`. Previously a `そうでなければ` after a `以下の手順です` line was not read as the continuation of the sentence before it, so the long branch had to be moved to the end.

```suru
n を 報告する とは 以下の手順です
  もし n > 10 ならば 以下の手順です
    「多い: 」 を 続表示する
    n を 表示する
    以上です
  そうでなければ 「少ない」 を 表示する
  以上です
```

Only `そうでなければ …` (and `ならば …`) lines may follow that `以上`; any other sentence is still the error 「「以上」の後に文があります」 ("there is a sentence after 以上"). When `以上` is written at the indent of the `もし` line, it closes the procedure, so `そうでなければ` cannot follow. The old form `ならば 手順` + deeper lines, like `そうでなければ 手順`, is not available inside an expression.

### Errors inside libraries

1. **A runtime error inside a library is shown at the place in your program that called it.** For example, `（空 を 最大値にする） を 表示する` gives `エラー: 3行目 6文字目: 空のリストの最大値はありません(「標準.suru」の45行目 35文字目)` and marks the line in your program. The position inside the library is added at the end in parentheses (#154). Previously only the line inside the library (such as `lib/標準.suru`) was shown, so you couldn't tell which call in your program caused it. The interpreter, `suruc` and `suru --翻訳` show the same thing.
2. **Libraries are the bundled `lib/` files and dependencies.** Files of dependencies in 組.lock, and files those load, are libraries. Your own files (the main file and files of your project, including ones loaded by the project name from `試験/`) are your program, and an error inside them is shown at its own position as before. In `kumu 試験`, an error inside a library is shown at the line of the test file.
3. **The place is the innermost call from your program.** It is the call from your program into a library function that is still running, including calls through function values (`xs を 最大値にすること で 写像する`). An action made by a library function (such as `ファイル内の読込する`) uses the place where that function was called, even when the action is carried out later. The 「(ここで実行時エラー)」 line of the trace of `試行する` and `試算する` and `--json` (`line` and `column`) also use this place, and the reason of the failure (理由) stays the message alone.
4. **`最大値にする` and `最小値にする` of an empty list explain the error.** They give 「空のリストの最大値はありません」 ("an empty list has no maximum") instead of 「「空」は「最大値にする」のどの定義にも当てはまりません」.

### Small inconveniences (#155)

1. **Errors show how to write it.** `xs の それぞれ を （x を 受け取って … を 返すこと）` explains that 「それぞれ」 takes a function name ending in 「する」 and suggests `xs を （…） で 写像する`. `もし s を JSON解析する が` explains that a call in 「もし 値 が」 needs parentheses (`もし （s を JSON解析する） が`). An indented 「ただし」 explains that it goes at the same indent as the definition it adds to. Using a constructor name as a function (`xs の それぞれ を JSON数にする`) explains that 「JSON数」 is a constructor and suggests `（x を 受け取って x の JSON数 を 返すこと）`. The interpreter and `suruc` give the same messages.
2. **The linter reports values defined twice.** The new rule 「値の再定義」 reports the second definition of `x とは 3` / `x とは 4` (the later one is used). Functions are not reported, since they can be defined case by case.
3. **`kumu 試験` shows the line of the failed check.** A failed `一致確認する`, `確認する` or `不合格にする` writes the place in the test file first, as in `「計算.suru」の6行目 3文字目: 等しくありません: 期待は 7 / 実際は 6`. The place is the one from "Errors inside libraries", which the new built-in `呼出場所取得する` (in 「標準」, an action) returns as a string (empty when there is none).
4. **`kumu 新規` makes an example test.** It writes `試験/例.suru` with one test (not for microcontroller targets, which can't run tests), so `kumu 試験` works right after creating a project.

### Actions stored in records from a procedure

1. **Putting a procedure's local that holds an action into a record is an error at its definition.** In a procedure, `番号 とは n を 番号作成する` without 「した 結果」 binds the action itself, not its result. Since the fields of a record can hold any type, putting that local into a record (`番号 の 数値`, `中身 は 番号 の 数値`, or an update) passed the type check, and the action only failed much later, far from the cause (#168). Now the definition line gives 「「番号」には動作そのものが入っていて、行われていません(それを「数値」の「中身」に入れています)。動作を行った結果を使うなら「番号 とは …を 番号作成した 結果」と書いてください。動作のまま入れるなら、「数値」の「中身」に直接書いてください」 ("「番号」 holds the action itself, which is not carried out (it is put into 「中身」 of 「数値」); to use the result, write 「番号 とは …を 番号作成した 結果」; to store the action as is, write it directly in 「中身」 of 「数値」"). The Python and Go versions give the same error.
2. **Storing an action on purpose is written in the record itself.** `名前 は 「a」 で 処理 は （「押した」 を 表示する） の ボタン` still passes, and so do locals that hold a function value (`…すること`) or an anonymous function.

### Runtime library on Windows

1. **The runtime library (`runtime/suru_rt.c`) also builds for Windows (MinGW-w64).** Build it with `clang --target=x86_64-w64-mingw32` and link with `-lpthread -lws2_32`. Threads use MinGW-w64's winpthreads as they are, and only the parts that differ are split with `#ifdef _WIN32` (GC memory with `VirtualAlloc`, sockets with Winsock2, and console output switched to UTF-8 at startup). How `suruc` and `kumu` make Windows .exe files is in "Building programs for Windows" (the remaining plan is in `docs/今後/Windows.md`).
2. **Receiving from sockets uses our own reader on every OS.** A Windows socket can't be made into a `FILE`, so receiving goes through a reader (`SockIn`) that reads in chunks with `recv` and hands out one character or a block at a time. Linux and macOS use the same reader. Timeouts (`待機時間設定する`) are set in each OS's own form.
3. **What doesn't work on Windows yet gives a clear error.** Named channels (FIFOs) and callback addresses say 「Windows ではまだ使えません」 ("not available on Windows yet"). Callback entry points receive arguments in the Linux/macOS calling convention.
4. **`tests/test_windows.py` checks it.** With MinGW-w64 it builds the runtime library for Windows, and with wine it runs the built .exe and checks that arithmetic, threads with GC, a million-deep recursion and the TCP echo server behave the same as on Linux (on Ubuntu, `apt install mingw-w64 wine`). Without them the tests are skipped.

### Building programs for Windows

1. **`suruc`, `suru --翻訳` and `kumu 作る` make Windows .exe files.** On Windows they build for Windows; on other OSes, setting the environment variable `SURU_TARGET` (for example `x86_64-w64-mingw32`) passes it to clang's `--target` and builds for that OS. The name gets `.exe` added (`-o 窓` makes `窓.exe`; `kumu 作る` makes `出力/<name>.exe`). The tools are MSYS2's clang (MinGW-w64).
2. **A built .exe needs no extra DLLs.** winpthreads is linked in, and Winsock2 (`-lws2_32`) is added. `dl`, `rt` and `pthread`, which libraries list for Linux, are skipped on Windows, and no rpath is written.
3. **File paths and text are UTF-8 on Windows too.** When `windres` (`x86_64-w64-mingw32-windres`, `llvm-windres` or `windres`) is available, the .exe gets a manifest that sets the active code page to UTF-8, so Japanese file names work with the C functions as they are. It is built once and cached.
4. **Lint is always built for your own machine.** The lint binary (`suru --点検`, `kumu 点検`, the language server) runs on your machine, so it ignores `SURU_TARGET`.
5. **The interpreter also starts on Windows.** `suru.py` doesn't load `fcntl` on Windows, and for external libraries it looks for `<name>.dll` (`c` and `m` mean `msvcrt`). Standard library modules that call C functions are covered in "Standard library on Windows" (compiled programs only, for now).
6. **`tests/test_windows.py` checks it.** With `SURU_TARGET=x86_64-w64-mingw32` it makes .exe files with `suruc`, `suru --翻訳` and `kumu 作る` and runs them under wine.
7. **Linking uses lld when it is installed.** GNU ld on Windows can't read or write paths with Japanese characters (such as `出力/`), so when `ld.lld` is found the link uses `-fuse-ld=lld` (in MSYS2, `pacman -S mingw-w64-ucrt-x86_64-lld`). Without lld, the program is linked in the temp folder and then copied to its place, but C sources in folders with Japanese names still need lld.

### Standard library on Windows

1. **The standard library modules also work in Windows programs.** The `.suru` files in `lib/` can't be split by OS, so they keep calling the POSIX names (`realpath`, `uname`, `localtime_r`, `getentropy`, `dlopen`, `shm_open`, `mmap` and so on). On Windows the runtime library provides those names itself, built on the Windows API. `環境内のOS名取得する` returns 「Windows」.
2. **What each module does on Windows.** 「ファイル」 handles UTF-8 paths and `実道取得する` returns a path separated by `/` (like `C:/Users/…`), with symbolic links resolved. 「時間」 reads the clock and the time zone offset. 「乱数」 uses `rand_s`. 「動的リンク」 uses `LoadLibrary` (a name like `kernel32.dll`). 「共有メモリ」 and 「固定領域」 map a file `suru-shm-<name>` in the temp folder, so other processes share it.
3. **「プロセス」 uses cmd.exe.** Commands go to cmd.exe instead of `/bin/sh`. When arguments are given as a list, only those with spaces or symbols are quoted with `"…"`, and the exit code is returned as is. Temporary files go in `%TEMP%`. The output of other programs is in their own encoding (cmd's `echo` uses the console code page).
4. **What isn't available yet gives a clear error.** `分岐する`, `子終了待機する` and `子実行する` (fork), 「セマフォ」, 「共有箱」 and 「読書ロック」 (System V semaphores), and 「シグナル」 say 「…は Windows ではまだ使えません」 ("not available on Windows yet") when called. Loading the module and linking still work.
5. **`tests/test_windows.py` checks it.** It builds a program that uses files, time, environment, random numbers, dynamic linking, shared memory and processes, and runs it under wine. It also checks the error messages for semaphores, signals and fork.

### Writing external functions on one line or in a block

When many external functions are written as a type declaration plus a definition, it is hard to see where each definition starts and ends. Two ways of writing them with the name only once were added (#172, #173, #174). The two-line form still works.

```suru
外部の「m」 を 読み込む

x を y で 累乗する とは 外部の「pow」 で 小数 を 小数 で 受け取って 小数 を 返します
s を 字数計測する とは 外部の「strlen」 で 文字列 を 受け取って 整数 を 返す 入出力動作です

以下は外部の関数です
  小数 を 余弦にする は 「cos」 で 小数 を 返します
  x を y で 逆累乗する とは 「pow」（y と x） で 小数 を 小数 で 受け取って 小数 を 返します
以上です

以下は外部の入出力動作です
  文字列 を 文字列 で 比較する は 「strcmp」 で 整数 を 返します
  文字列 を 一行出力する は 「puts」 で 整数 を 返します
以上です
```

1. **The type goes after the definition.** `n を 確保する とは 外部の「SDL_malloc」 で 数 を 受け取って 番地 を 返す 入出力動作です` means the same as the two lines `数 を 確保する は 番地 を 返す 入出力動作` and `n を 確保する とは 外部の「SDL_malloc」`. The type starts at the `で` after `外部の「…」` (and the C argument list `（…）`, if any), in the same shape as a function type: `type particle … 受け取って type を 返す`. With no arguments, `受け取って` is left out (`低終了する とは 外部の「SDL_Quit」 で 無 を 返す 入出力動作です`). The ending decorations are the same as in type declarations, so `… を 返します` also works.
2. **The type's particles are the definition's, in the same order.** Otherwise it is the error 「「累乗する」の型の引数は、定義と同じ助詞を同じ順に書き、最後に「受け取って」を書きます(定義の助詞: を・で)」 ("write the same particles as the definition, in the same order, then 受け取って"). This form is only for definitions whose body is `外部の「…」` (an ordinary body is an expression, where `で` would clash with an argument).
3. **Between `以下は外部の入出力動作です` and `以上です`, write one function per line.** Every function in it returns an action, so lines don't repeat `入出力動作` (writing it is an error). Functions that are not actions (like `cos`) go in `以下は外部の関数です`. `以下 は 外部 の 入出力動作` (without です) and `以上` also work. The block is only allowed at the outermost level.
4. **Lines are written like type declarations.** As in `数 を 確保する は 「SDL_malloc」 で 番地 を 返します`, the C name and `で` come after the declaration's 「は」. Arguments go to C in declaration order. To reorder the arguments passed to C or add constants, write the line as a definition with names: `r を 読取する とは 「SDL_RenderReadPixels」（r と 0） で 番地 を 受け取って 番地 を 返します`.
5. **Lines are deeper than the header, or at the same indent.** The same as `以下の手順です`. Comment lines and blank lines are allowed inside. A missing `以上`, an empty block, a line in neither shape, and the same name twice are errors. In the punctuation style it is `以下は外部の入出力動作です。文字列を字数計測するは、「strlen」で整数を返します。以上です。`.
6. **Everything reads them the same way.** Before building the indentation tree, they are turned into the two lines (declaration and definition). The interpreter, the Python and Go compilers, the lexer and parser written in する (`lib/字句.suru`, `lib/構文.suru`), the linter, the REPL (which reads until 「以上」) and the VS Code highlighting all do the same. The libm functions in `lib/算術.suru` are written with `以下は外部の関数です`.
7. **The header starts with 「以下は」.** The header begins a sentence, so it reads `以下は外部の関数です` / `以下は外部の入出力動作です`, while `以下の手順です` stays as it is because it comes after `とは` in the middle of a sentence. The 0.9.0 spelling `以下の外部の関数です` / `以下の外部の入出力動作です` (and `以下 の 外部 の …`) still works with the same meaning. Error messages quote the header as you wrote it.
8. **`外部の（f）`, which calls through a function pointer, can also be written on one line or in a block.** `p を f で 呼出する とは 外部の（f） で 番地 を 番地 で 受け取って 無 を 返す 入出力動作です` means the same as the two lines `番地 を 番地 で 呼出する は 無 を 返す 入出力動作` and `p を f で 呼出する とは 外部の（f）` (#189). The rules are those of `外部の「…」`: the types follow the definition's particles in order, and f has the type `番地` (f is not passed to C). In a block, use the definition form with names: `p を f で 呼出する とは （f） で 番地 を 番地 で 受け取って 無 を 返します`. The short `は` form has no parameter names, so it cannot say which argument is the pointer, and `（f）` is not allowed there (the error points to the definition form).

### Blank lines between definitions (lint)

1. **The linter reports a function definition followed by another function's definition with no blank line.** This is the new rule 「定義の間の空行」 (#175). At the outermost level, a type declaration together with all definitions of that function (including case-by-case definitions) is one group. When a group starts on the line right after the previous group, the first line of the later group gets 「「解放する」の定義は、前の「確保する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります」 ("a blank line between this definition of 「解放する」 and the previous definition of 「確保する」 makes it easier to see where the new definition starts").
2. **Only when at least one of the groups is two or more lines.** A run of one-line definitions (external functions written on one line, or `x を 二倍する とは x * 2`) reads like a table and is not reported. A `以下は外部の入出力動作です … 以上です` block is one group.
3. **Comments directly above a group belong to it.** The blank line goes above the comments. Value, type and trait definitions, loads, and expression statements are not groups and are not checked. As with other rules, `# 点検しない: 定義の間の空行` silences it.

### Field types in records

```suru
会員 とは 番号 は 数 で 名前 は 文字列 で 年齢 は 数 の 組
木 とは 値 は 甲 で 左 は 木 で 右 は 木 の 節 か 葉

（1 と 「花子」 と 20 の 会員） の 名前 を 表示する
（1 と 葉 と 葉 の 節） の 値 を 表示する
```

1. **A record definition can give each field a type.** `会員 とは 番号 は 数 で 名前 は 文字列 で 年齢 は 数 の 組` has the same shape as building a record by field name (`横 は 3 で 縦 は 4 の 点`): `field は type`, separated by `で`. Types are written as in type declarations (`数`, `数 の リスト`, `（数 を 受け取って 数 を 返すこと）`, other record types, including ones defined later in the file). This is the first stage of the plan for deriving and quasi-quotes (#192): deriving needs to know the field types.
2. **All fields or none.** Within one type, either every field has a type or none does (forms without fields, like `葉`, do not count). The old form `番号 と 名前 の 組` keeps inferring field types as before. Fields with the same name in different forms of one type must be given the same type.
3. **Values are checked against the written types.** `（「1」 と 「花子」 と 20 の 会員）` is an error: 「「会員」の「番号」は数ですが、文字列が渡されています」. In error messages and type declarations such a type is just its name (`会員`).
4. **甲・乙 … are the type's parameters.** In `木` above, `値 は 甲` makes `木` take one type parameter, so the type is written `数 の 木`. Type parameters are numbered by the order 甲・乙 … first appear in the field types (not by field order as in inferred records). A field whose type is the type itself without parameters (`左 は 木`) has the same parameters as the value it is in.
5. **The same everywhere.** The interpreter, both compilers (Python and Go `suruc`), the language server, and the する-written parser `lib/構文.suru` (used by 点検) read this form.

### Quasi-quotes

```suru
「道」 を 読み込む

以下は【定】です
  x 10
  y x * 2
以上です

z とは 以下の【式】です
  y + 3
以上です
```

1. **A block written in another notation becomes Suru code.** `以下は【X】です` … `以上です` hands the lines in between (with their common indentation removed) to the function `X展開する` as one string, and puts the Suru code it returns in place of the block. This is the second and third stages of the plan for deriving and quasi-quotes (#192). Libraries will use it for things like table definitions (【表】) and routes (【道】).
2. **The expander is an ordinary function.** `X展開する` has the type `文字列 を X展開する は 文字列 の 成否` and must be defined in a file the program reads (`「道」 を 読み込む`). If no file read has it, or two do, it is an error. It returns the code with `成功`, or an explanation with `失敗`. When the explanation starts with `N行目:`, the error points at the N-th line of the block.
3. **Two forms.** `以下は【X】です` at the top level (not indented) is replaced by the definitions and statements the expander returns. `x とは 以下の【X】です` makes the returned code the value of `x` (one line becomes an expression; several lines become the indented body of `x`). The body must be indented deeper than the header, and `以上です` must have the same indentation as the header. `です` and `。` can be left out, as with other `以上`.
4. **When it runs.** Quasi-quotes are expanded while the program is read, before type checking, so errors in the expanded code are reported like other errors (at the header line). The expanded code may contain quasi-quotes itself (up to 20 levels), but not `読み込む`. The interpreter runs the expander in-process. `suruc` compiles the expander into a small program, keeps it in the cache folder (the same IR is not built again), and runs it; `kumu` and the language server do the same.
5. **Seeing the result.** `suru --展開 prog.suru` and `suruc --展開 prog.suru` (also `--expand`) print the program with every quasi-quote replaced by its expansion.
6. **【 and 】 are reserved.** Outside strings, `【` and `】` can only be used in a quasi-quote header. 点検 (`lib/字句.suru` and `lib/構文.suru`) reads the header without expanding it: the file that defines `X展開する` counts as used, and so do names written in the block.

### Deriving

```suru
「写」 を 読み込む

会員 とは 番号 は 数 で 名前 は 文字列 で 好物 は 文字列 の リスト の 組
会員 は 【記述】 と 【数え】 を 導出する
```

1. **Functions made from the shape of a type.** `会員 は 【記述】 と 【数え】 を 導出する` hands a description of `会員` to the functions `記述導出する` and `数え導出する`, and puts the definitions they return in place of the line. This is the fourth stage of the plan for deriving and quasi-quotes (#192). Libraries will use it to make, for example, JSON conversion (【JSON】) and row conversion for the O/R mapper (【表】) without runtime reflection.
2. **The deriver receives a type description.** `X導出する` has the type `型記述 を X導出する は 文字列 の 成否` and must be defined in a file the program reads. The types come from `lib/導出.suru` (`「導出」 を 読み込んで 使う`): `型記述` (type name, type parameters 甲・乙 …, forms), `形記述` (form name and fields), `欄記述` (field name and type) and `型式` (a type: `名型` with a name and arguments, such as `数`, `数 の リスト`, `甲` or the type itself, or `他型` with the written text, such as a function type). `型式文にする` gives the written text (`数 の リスト`).
3. **Only typed records in the same file.** The type must be defined in the same file, and its fields must have types (`番号 は 数 で … の 組`; forms without fields, like `赤 か 青`, need none). The line must be at the top level. Several derivers can be joined with `と`, and `導出します` also works.
4. **Same as quasi-quotes.** Deriving runs while the program is read, like quasi-quotes: the derived code is type checked, its errors point at the deriving line, it may contain quasi-quotes and deriving lines but not `読み込む`, and `suru --展開` / `suruc --展開` show it. `suruc`, `kumu` and the language server compile the deriver into a small program and keep it in the cache folder. 点検 counts the file that defines `X導出する` as used.

### Deriving JSON

```suru
「JSON」 を 読み込んで 使う

会員 とは 番号 は 数 で 名前 は 文字列 で 好物 は 文字列 の リスト の 組
会員 は 【JSON】 を 導出する

m とは （番号 は 1 で 名前 は 「花子」 で 好物 は （「茶」 と 「餅」） の 会員）
m を 会員JSON化して JSON文字列にして 表示する
（m を 会員JSON化する） を 会員JSON復元して 表示する
```

1. **【JSON】 makes the conversion to and from JSON.** `会員 は 【JSON】 を 導出する` (with `「JSON」 を 読み込んで 使う` or `「JSON」 を 読み込む`) defines `会員 を 会員JSON化する は JSON` and `JSON を 会員JSON復元する は （会員 と 文字列） の 成否`. This is the fifth stage of the plan for deriving and quasi-quotes (#192), and the first deriver in the standard library (`JSON導出する` in `lib/JSON.suru`).
2. **The JSON shape.** A record (one form) becomes an object with one item per field: `{"番号":1,"名前":"花子","好物":["茶","餅"]}`. A type with several forms adds a `形` item with the form's name: `{"形":"長方形","幅":2,"高":3}`, and `{"形":"点"}` for a form without fields.
3. **Field types.** `数`, `文字列`, `真偽`, `JSON` (kept as it is), `X の リスト`, and other types that also derive 【JSON】 (their `…JSON化する` and `…JSON復元する` are used). Other field types, and types with parameters (甲・乙 …), are errors when deriving.
4. **Failures name the field.** `会員JSON復元する` returns `失敗` with a message such as 「番号が数ではありません」 or 「「形」が三角の形はありません」. The helpers it uses, `JSON数復元する`, `JSON文字列復元する`, `JSON真偽復元する` and `JSONリスト復元する`, can also be used by hand.

### Tests in the same file and examples

```suru
# x の2倍を返します。
数 を 二倍する は 数
x を 二倍する とは x * 2
例えば （2 を 二倍する） は 4 です
例えば （-3 を 二倍する） は -6 です

数 を 加一する は 数
x を 加一する とは x + 1

以下は「二倍」の試験です
  （0 を 加一して 二倍する） を 2 に 一致確認する
  1 < 2 を 確認する
  以上です

加一する は 非公開とする
```

```
suru --試験 計算.suru             # run the tests of a file with the interpreter (a folder runs every file in it)
suruc --試験 計算.suru 二倍       # the same with the Go compiler, only tests whose name contains 二倍
```

1. **Test blocks.** `以下は「二倍」の試験です` … `以上です` at the top level is a test named 「二倍」. The body is a procedure. It can use the file's private names, and the assertion functions of 「試験」 (`一致確認する`, `確認する`, `不合格にする`) without loading it. `以下 は 「二倍」 の 試験 です` also works. Two test blocks in one file can't have the same name.
2. **Examples.** `例えば 式 は 期待する値 です` at the top level is an example of the definition just above it (the `です` can be left out). It passes when both sides are equal (`=`), and its name is 「二倍するの例(4行)」 (the definition's name and the line). It is a statement, not a comment, so a typo in it is an error. The language server shows a definition's examples when hovering over its name.
3. **Always type checked, never run by a normal run.** Test blocks and examples are type checked with the rest of the file (`suru --検査`, `suruc --検査`, the language server), are skipped in a normal run and dropped from a build, and are ignored when the file is loaded by another file.
4. **Running tests.** `suru --試験 ファイルかフォルダ … [名前 …]` runs the test blocks, the examples and the top-level `…試験する` procedures with the interpreter. `suruc --試験 …` does the same with the Go compiler, building one test binary per file (with -O0 unless another -O is given) and running each test in its own process. Words that are not paths pick tests by part of their name or path. The output is the same as `kumu 試験`: ✓ or ✗ for each test, the reason and what a failing test printed indented below it, and 「合格 3・不合格 1」 ("3 passed, 1 failed") at the end. The exit code is 1 if anything failed.
5. **`kumu 試験` runs them too.** Before the files in `試験/`, it runs the test blocks and examples in the project's source files (not `組.suru`, `試験/` or `出力/`), one binary per file, linked with the project's `Cソース`.
6. **`lib/` is tested this way.** `lib/算術.suru`, `lib/乱数.suru` and the formatting functions of `lib/標準.suru` have examples and test blocks, and the CI runs `suru --試験 lib/` and `suruc --試験 lib/` on every pull request, next to pytest and `go test`. pytest and `go test` stay for testing the interpreter and the compilers themselves.

### Calling from other languages (shared libraries)

Functions written in Suru can now be used from Python, C, C++, Go, Rust and any other language that can call the C calling convention. `suruc --共有ライブラリ` builds a shared library (.so, .dylib). The plan is #208, and this covers its stages 1 and 2.

```suru
数 を 二倍する は 数 を 返す
x を 二倍する とは x * 2 です

文字列 を 挨拶文にする は 文字列 を 返す
名前 を 挨拶文にする とは 「こんにちは、」 + 名前 + 「さん」 です

以下は外部に出す関数です
  二倍する は 「nibai」
  挨拶文にする は 「aisatsu」
以上です
```

```sh
suruc --共有ライブラリ 計算.suru -o libkeisan.so   # also writes keisan.h
```

```python
import ctypes
lib = ctypes.CDLL("./libkeisan.so")
lib.nibai.argtypes = [ctypes.c_int64]
lib.nibai.restype = ctypes.c_int64
print(lib.nibai(21))   # 42
```

1. **Between `以下は外部に出す関数です` and `以上です`, write one exported function and its C name per line.** `二倍する は 「nibai」` exports `二倍する`, defined in this file, as the C function `nibai`. It can only be written at the top level. In the punctuation style it is `以下は外部に出す関数です。二倍するは、「nibai」。以上です。`, and it can also be split with spaces as `以下 は 外部 に 出す 関数 です`.
2. **Types come from the type declaration.** An exported function needs a type declaration. The arguments become C arguments in the order written in the definition (`hikizan(a, b)` for `a を b から 引き算する`). The type mapping is the same as for foreign functions: `数` is `int64_t`, `整数` `int`, `小数` `double`, `単精度` `float`, `真偽` `int` (0 or 1), `文字列` `const char *` (UTF-8), `番地` `void *` and `無` `void` (values only). Lists, records, functions and byte sequences can't be passed yet. A function whose value is an action (`… を 返す 入出力動作`) is carried out when called.
3. **Rules for C names.** A name starts with a letter or `_` and contains only letters, digits and `_`. Names starting with `rt_`, `suru_` or `gc_`, and `main`, can't be used because they clash with the runtime library. The same name as a foreign function used in the same file, or writing the same function or the same C name twice in the block, is also an error.
4. **Build with `suruc --共有ライブラリ FILE.suru -o libkeisan.so`.** Without `-o` the name is `lib` + the file name (`libkeisan.so`), and without an extension `.so` is added on Linux and `.dylib` on macOS. The Python version builds the same with `suru --翻訳 --共有ライブラリ`. Only definitions can be written at the top level of the file (statements such as printing are an error, so that loading the library doesn't do anything). A file without `以下は外部に出す関数です` is an error too. When building an executable or in the interpreter, the block is skipped.
5. **Helper functions.** `keisan_init`, `keisan_last_error` and `keisan_free`, prefixed with the library's name (`keisan` for `libkeisan.so`), are exported too. Give `-o` a name of only letters, digits and `_`. String values are `malloc`ed copies, so the caller frees them with `keisan_free`. `keisan_init` initializes and returns 0 (without it, initialization happens on the first call).
6. **Runtime errors don't stop the process.** A runtime error inside an exported function (dividing by 0, a number beyond ±2^62 and so on) doesn't end the caller's process; the function returns 0 (NULL). `keisan_last_error()` is the error message of the last function called on that thread (`32行目 16文字目: 0 で割ることはできません`), or NULL if there was none.
7. **They can be called from any thread.** They run on the caller's thread and stack (very deep recursion is limited by the caller's stack size). A thread is registered with the runtime library on its first call, and the GC looks at its stack only while a call is running. Several threads can call at the same time. Nesting also works: an exported function calls a foreign function, which calls an exported function again.
8. **Other names are hidden.** The runtime library's names aren't visible from outside, so two Suru shared libraries can be loaded together, and a Suru executable can load one with `外部の「./libkeisan.so」 を 読み込む`, without clashes (each has its own GC).
9. **A C header is written next to the library.** `suruc --共有ライブラリ … -o libkeisan.so` also writes `keisan.h` in the same folder, with the prototypes of the exported functions (`int64_t nibai(int64_t a1);`) and of the helper functions, the Suru name and types of each function (`する: 二倍する  数 → 数`, with `入出力動作` for actions) and notes on errors, freeing strings and threads. It can be included from C and C++ (it has `extern "C"`). The Go and Python versions write the same header.
10. **Examples for other languages.** `examples/他の言語から/` calls the functions of `examples/export.suru` from Python (`ctypes`), C, C++, Go (cgo) and Rust, including freeing strings and reading `keisan_last_error()`. Each example prints the same output, and the tests run all of them (each is skipped when its compiler is missing).
11. **Not yet.** Lists, records and byte sequences (stage 3), kumu (stage 4) and Windows .dll (stage 5) are later stages of #208. The example is `examples/export.suru`.

### Descriptions of definitions

```suru
# SPDX-License-Identifier: MIT
# 計算のライブラリです。
# 数を何倍かにする関数があります。

# 数を2倍した値です。
#
# 負の数もそのまま2倍します。
数 を 二倍する は 数 を 返す
x を 二倍する とは x * 2 です
例えば （3 を 二倍する） は 6 です
```

1. **The comment right above a definition is its description.** The comment lines (`#`, `＃`, `※`) written directly above the type declaration (or the definition, when there is none), with no blank line between, are the description of that definition. No new syntax was added, so existing comments already work as descriptions. The text after the comment mark and one space is joined line by line as Markdown; a line with only `#` is an empty line (a paragraph break). `# 点検しない` lines are left out (#209).
2. **The comment at the head of a file describes the file.** The comment lines starting at line 1 are the description of the file (module), without the `SPDX-License-Identifier:` and `Copyright` lines. Even when a definition follows the head comment with no blank line, that comment is not the definition's description.
3. **Shown on hover in the language server.** Hovering a name shows its description after the type, also for public definitions of imported files (such as `数学内の二乗する`). The Python version (`doc_comments` in `suru.py`) and the Go version (`compiler.DocComments`) read them by the same rules. API documentation is made from the descriptions with `--文書` (see "API documentation (--文書)").

### API documentation (--文書)

```
suru --文書 lib/算術.suru                  # Markdown を画面に出す
suruc --文書 --出力 文書/api lib/          # フォルダの中の .suru ごとに 文書/api/名前.md を書く
suru --文書 --json lib/算術.suru           # 同じ中身を1ファイル1行の JSON で出す
```

1. **Lists the public names one by one.** `suru --文書` and `suruc --文書` (also `--doc`) write API documentation listing the public types, traits, values and functions of a file (for a folder, the `.suru` files in it; subfolders are not read) in the order they are written. Names in `… は 非公開とする`, test groups and examples are not listed as names (#209).
2. **What each name shows.** The type declaration as written (for types and traits, the definition, with its indented continuation lines), for functions the usage (`x を 二倍する`, from the parameter names of a definition without patterns), the description (see "Descriptions of definitions") and the examples of that definition (`例えば … は … です`). Functions and values without a type declaration get no type. A declaration inside an `以下は外部の…です` block is that one line.
3. **Markdown layout.** The file name as the title (`# 「算術」`), then the file description, then one `## 名前` section per name. Code is fenced with ` ```suru `, so Sphinx's MyST reads it too. `--json` gives JSON with `file`, `module`, `description` and `items` (`name`, `kind` (関数・値・型・性質), `line`, `signature`, `usage`, `description`, `examples`).
4. **`--出力 フォルダ` writes files.** One `名前.md` per file (`名前.json` with `--json`). Without it, everything goes to standard output. A file that cannot be read (a syntax error, an imported file not found, …) is reported and skipped, and the exit code is 1.
5. **The Python and Go versions give the same output.** `tests/test_doc.py` checks that both give the same Markdown and JSON for every file in `lib/`. `kumu 文書` and publishing on Read the Docs are in "kumu 文書 and Read the Docs".

### kumu 文書 and Read the Docs

```sh
kumu 文書 --雛形    # docs/conf.py・docs/index.md・docs/requirements.txt・docs/_ext/suru_lexer.py・.readthedocs.yaml を書く
kumu 文書           # docs/api/ にファイルごとの API のページ(Markdown)を書く
pip install -r docs/requirements.txt && sphinx-build docs docs/_build   # 手元で HTML にする
```

1. **`kumu 文書` documents the top-level files of the project.** After fetching the dependencies (like `取得`), it writes the `.suru` files at the top of the project folder (except `組.suru`) to `docs/api/名前.md`, in the same form as `suru --文書`. Files under `試験/` or `例/` are not API, so they are not read. `--出力 フォルダ` chooses where to write and `--json` writes JSON (#209).
2. **`kumu 文書 --雛形` writes Sphinx and Read the Docs settings.** Sphinx reads MyST (Markdown), with `language = "ja"` (Japanese search) and the furo theme. `docs/_ext/suru_lexer.py` is a Pygments lexer that highlights Suru code, registered by `conf.py`. The project name is filled in when the files are written; the version is read from `組.suru` on every build. `index.md` gets the head comment of the file named after the project (or else the entry file). Existing files are left as they are, and `/docs/api/` and `/docs/_build/` are added to `.gitignore`.
3. **Read the Docs only needs the repository connected.** On every build, `.readthedocs.yaml` downloads the Linux kumu of the same version as the one that wrote the files from GitHub Releases, runs `kumu 文書 --出力 docs/api`, then builds the HTML with Sphinx. The generated pages are not committed. Import the GitHub repository on readthedocs.org and it is published on every push and tag.
4. **The folder is named docs.** Instead of a Japanese folder name like `試験/`, it uses `docs/`, which Read the Docs and Sphinx tools expect.

### Web app skeleton (kumu 新規 --対象 web)

1. **`kumu 新規 店 --対象 web` creates a web app for 屋台 ([suru-lang/web](https://github.com/suru-lang/web)).** `組.suru` depends on `github.com/suru-lang/web@0.1.0`. `店.suru` has the routes (【道】) and handlers, and `本体.suru` reads it and opens the server on port 8080. The pages are in `画面/` (a layout and a top page), static files are in `公開/`, and `試験/道.suru` tests the routes without starting a server. `kumu 実行` runs it, `kumu 試験` runs the tests, and `kumu 作る` makes the binary `出力/店`. The binary reads `画面/` and `公開/` from the folder it runs in, so ship those folders with it. `kumu 初期化 --対象 web` writes the same files into the current folder and keeps files that already exist.
2. **`web` is not a microcontroller target.** `--対象 web` only chooses the skeleton, so `組.suru` gets no `対象` line and the app is built for this computer. The app's name must not be the name of a standard library or of 屋台 and its dependencies (屋台, HTTP, 雛形, 台帳, 蔵), because the routes file is loaded by that name.

### Documentation of Suru itself (Read the Docs)

```sh
python suru.py --文書 --出力 docs/api lib   # 標準ライブラリの API のページを作る
pip install -r docs/requirements.txt && sphinx-build docs docs/_build
```

1. **This repository is published on Read the Docs too.** It has `docs/conf.py` (Sphinx + MyST, `language = "ja"`, furo) and `.readthedocs.yaml`, which on every build runs `python suru.py --文書 --出力 docs/api lib` to make the API pages of every file in `lib/`. Unlike a kumu project there are no dependencies, so kumu is not used (#209).
2. **What it contains.** The standard library API, the built-in functions (the table of "Built-in functions" in README_jp.md is included), `docs/AIの手引き.md` and `docs/ライブラリを公開する.md`. `docs/今後/` and `docs/リリース.md` are not for users, so they are left out. The version is read from `__version__` in `suru.py`.
3. **Same highlighting as the kumu scaffold.** It uses `cmd/kumu/docs_template/suru_lexer.py`. `suru-誤り` code (the examples in the AI guide that fail the check) is highlighted the same way.
4. **Parameters of external functions are "…".** Functions in an `以下は外部の…です` block have no parameter names, so their usage is written like `… を 正弦にする`.

## License

- The core (`suru.py`, `suru_check.py`, `suru_compile.py`, and the Go `compiler/` and `cmd/`): [GPL-3.0-or-later](LICENSE)
- The runtime library (`runtime/`) and standard library (`lib/`): [MIT](runtime/LICENSE)

The Suru programs you write, and the LLVM IR and executables made with `suru --翻訳`, are yours. You may distribute them under any license you like. An additional permission at the top of `suru_compile.py` and `compiler/compile.go` states that the parts the compiler writes into its output are not covered by the GPL either (the runtime library and standard library that go inside are MIT, so keeping their copyright notice is enough).

## Future work

Candidates are written in files in [docs/今後/](docs/今後/), one file per area (so that work going on at the same time doesn't rewrite the same lines). They are in Japanese.

English | [日本語](README_jp.md)

# VS Code extension for Suru (「する」)

An extension for writing Suru (`.suru`), a functional programming language in Japanese, in VS Code.

- **Syntax highlighting**: function names (「…する」, 「…して」, 「…すること」, 「…である」 and so on), built-in functions, case particles (を・に・で・から・へ・より・と・の・が), keywords (とは・もし・ならば・そうでなければ・ただし・手順 …), strings 「…」, names in 『』, numbers, comments, and names of loaded files (`数学内の`). Both the spaced style and the punctuation style (lines containing 「。」 or 「、」) are supported. The reserved 「・」 is shown in red.
- **Type checking as you type**: the language server `suru-ls` (using the Go version's lexer, parser and type checker) underlines mistakes with squiggles while you type and lists them in the Problems panel. One error is reported per outermost sentence (definition or expression), for both syntax and type errors. Sentences with syntax errors are skipped and the rest is still checked, so hovers and completion keep working in other sentences. Without the language server, files are checked with `suru --検査` when opened and saved.
- **Lint reports**: reports from `lib/点検.suru` (the linter written in Suru, the same as `suru --点検`) appear as warnings (yellow squiggles) when a file is opened and saved. The light-bulb quick fix 「この行の「…」を黙らせる」 ("silence 「…」 on this line") adds `# 点検しない: RULE` at the end of the line. The linter is built into a binary the first time it is used, so clang is required (without it, only the lint reports are missing).
- **Format Document**: Shift+Alt+F (or "Format Document" in the command palette) tidies the white space with `lib/整形.suru`, the same as `suru --整える`: one space between words, no spaces at line ends, half-width indentation, at most two blank lines in a row. It needs clang, like the lint reports.
- **Type hovers**: hovering over a name or function shows its type (`三倍する は （数 を 受け取って 数 を 返すこと）`). Functions also show how to pass arguments, with which particles (`n を 三倍する`, or for built-ins `… を （… に） 加算する`, where parentheses mark optional ones). At a definition you see the defined type; at a use, the type there. Built-in functions and `標準内の…` get hovers too.
- **Go to definition** (F12, Ctrl+click): jumps to the definition of a function or value. Case-by-case definitions show all of them. It can also jump into loaded files (`数学内の…`, `標準内の…`).
- **List of definitions**: the Outline and Ctrl+Shift+O list the definitions and types in the file.
- **Completion** (Ctrl+Space): offers defined functions and values, parameters, built-in functions, names of types, shapes and fields, names from loaded files (`標準内の…`) and keywords, with their types. Even when the word is attached to the previous one in the punctuation style, as in `5を三倍`, it completes the `三倍` part. Value names containing hiragana are inserted enclosed in 『』. Function candidates also show how to call them (particles).
- **Rename** (F2): renames a function or value defined in this file at its definition, its type declaration and every use. Forms like `三倍して` and `三倍しまして` have only their stem changed. Parameter names are renamed only within that definition (other definitions taking a parameter of the same name are left alone). Names from loaded files and names of types, shapes and fields can't be renamed yet.
- **Coloring of type names**: names of types, shapes, traits and fields are colored (names defined as values, as in `リスト とは …`, are not).
- **Run**: ▷ at the top right of the editor, or F5, runs the file in a terminal (you can answer `入力する` prompts there too).
- **Build a binary**: runs `suru --翻訳` (clang is required).
- **kumu (project management)**: in a project with 組.suru, runs `kumu 実行`, `作る`, `試験`, `点検` and `取得` (run, build, test, lint, fetch) from the command palette. In files in `試験/`, 「▷ 試験する」 above a 「…試験する とは」 line runs just that test. Install `kumu` separately (`brew install suru-lang/suru/suru`, GitHub Releases, or `go install github.com/suru-lang/suru/cmd/kumu@latest`).
- Auto-closing of （）, 「」 and 『』, comment toggling with `#` (Ctrl+/), and indentation after 「とは」 and 「もし … が」.

The command palette (Ctrl+Shift+P) has 「する: このファイルを実行する」 (run this file), 「する: 型を検査する」 (check types), 「する: バイナリを作る」 (build a binary), 「する: 言語サーバーを再起動する」 (restart the language server), and kumu's commands such as 「する: プロジェクトを実行する(kumu 実行)」 (run the project).

## Installing

1. Install Suru itself: `pip install suru-lang` or `brew install suru-lang/suru/suru` (this provides the `suru` command; from the repository, `pip install .` at the top).
   Even without installing, if you open the repository folder in VS Code, the `suru.py` at the top is run with `python3`.
2. Install the extension. Search for 「する」 in the Extensions view, or, if you have `suru-0.1.0.vsix`, choose it under "…" → "Install from VSIX…" in the Extensions view (or from the command line, `code --install-extension suru-0.1.0.vsix`).

The `.vsix` can be built as follows (Node.js and Go are required). `build_server.sh` builds `suru-ls` for Linux, macOS and Windows into `server/`, and it is bundled in the `.vsix`.

```sh
cd editors/vscode
npm install
./build_server.sh
npx @vscode/vsce package
```

To install only the language server: `go install github.com/suru-lang/suru/cmd/suru-ls@latest` (the extension also looks for `~/go/bin/suru-ls`).

During development, open this folder in VS Code and press F5 to open another window of VS Code with the extension installed.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `suru.command` | (empty) | The command that runs Suru, e.g. `suru` or `python3 /path/to/suru.py`. If empty, the `suru.py` at the top of the open folder, or else `suru` |
| `suru.python` | (empty) | The Python that runs `suru.py`. If empty, `python` on Windows and `python3` elsewhere |
| `suru.languageServer` | (empty) | Location of the language server `suru-ls`. If empty, the bundled one, then PATH, then `~/go/bin`. `off` disables it |
| `suru.kumu` | (empty) | Location of `kumu`, the project manager. If empty, PATH, then `~/go/bin` |
| `suru.checkOnSave` | `true` | Without the language server, check with `suru --検査` when a file is opened and saved |

## Changing the highlighting grammar

`syntaxes/suru.tmLanguage.json` is generated by `make_grammar.py` from the lists of keywords and built-in functions in `suru.py`. After adding words to the language, run the following at the top of the repository (the tests fail if it is stale).

```sh
python3 editors/vscode/make_grammar.py
```

## About the language server

`cmd/suru-ls` is the language server. Inside it is the Go compiler's `compiler.Analyze`, which remembers the types where names are used and defined while type checking. Parsing and type checking stop at the first error, so for a syntax error it blanks the lines of that outermost sentence and rereads, and for a type error it rechecks without that sentence, to find errors in other sentences too (up to 20 of each). Loaded files are read as saved (saving rechecks every open file). The bundled standard library is written out to the cache folder (`~/.cache/suru/` on Linux) so that go to definition can reach it. If `SURU_LIB` is set, that is used instead.

For linting, `lib/点検.suru` is built into a binary with the Go compiler and clang only the first time, and placed in the cache folder as `点検-…` (rebuilt when lib or the runtime library changes). While it is being built (a few seconds) only type errors are shown; once ready, open files are linted. Unsaved contents are written to a temporary file and passed as `--代わり TEMP_FILE REAL_PATH`, so files loaded with 「読み込んで 使う」 are looked up from the real path's folder.

## License

GPL-3.0-or-later ([LICENSE](../../LICENSE) of the repository).

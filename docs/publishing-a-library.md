# Publishing a Suru library

[日本語](https://github.com/suru-lang/suru/blob/main/docs/ライブラリを公開する.md)

You publish a Suru library by putting a tag on its Git repository. Then other people can use it with `kumu 追加`. There is no central registry.

## 1. Make the library

```sh
kumu 新規 計算
cd 計算
```

The `名前` in `組.suru` is the name people use to load the library. The file that gets loaded is the one with the same name, `計算.suru` (in a library you can delete the scaffold's `本体.suru`).

```
# 計算.suru
x を 二倍する とは x * 2
x を 三倍する とは x * 3
```

Other files inside can be loaded as `「計算/道具」` (that loads `道具.suru`). To hide definitions from users, write a line such as `補助 は 非公開とする` at the end of the file (see "Public and private" in README.md).

## 2. Write tests

In the `試験/` folder, write procedures whose names end in `試験する`. The library loads itself as `「計算」`, the same way its users do.

```
# 試験/二倍.suru
「試験」 を 読み込んで 使う
「計算」 を 読み込む

二倍試験する とは 以下の手順です
  （2 を 計算内の二倍する） を 4 に 一致確認する
  （0 を 計算内の二倍する） を 0 に 一致確認する
  以上です
```

```sh
kumu 試験
kumu 点検
```

## Wrapping a C library

If your library calls a C library such as PCRE2 through external functions, write in `組.suru` what has to be installed on the system, by its pkg-config name. Before building, the user's kumu checks for it. If it is missing, kumu shows `導入案内` and stops (see "External dependencies (system C libraries)" in README.md).

```
名前 とは 「正規表現」
外部依存 とは 「libpcre2-8@10.30」
導入案内 とは 「macOS: brew install pcre2」 と 「Debian・Ubuntu: sudo apt install libpcre2-dev」
```

Inside the library you still write `外部の「pcre2-8」 を 読み込む`. kumu does not compile C code in a library, so you cannot write small C helpers. Wrap the library so that Suru's external functions alone can call it.

## 3. Choose a version and tag it

Write `版` in `組.suru` as numbers and dots, like `「1.0.0」`. Commit, then run `kumu 公開`.

```sh
git add -A && git commit -m "1.0.0"
kumu 公開
git push origin v1.0.0
```

`kumu 公開` checks the following, then puts an annotated tag `v1.0.0` on the commit (it does not push):

- `名前.suru` exists.
- No dependency is a local folder (`「../…」`), because users cannot fetch it.
- 組.suru is at the top of the repository, and there are no uncommitted changes.
- There is no tag for the same version yet.
- All tests pass (skip them with `--試験なし`).

## 4. Let people use it

```sh
kumu 追加 github.com/someone/計算        # the newest tag
kumu 追加 github.com/someone/計算@1.0.0  # a fixed version
```

```
「計算」 を 読み込む
3 を 計算内の二倍して 表示する
```

## Raising the version

Never move a tag once you have pushed it. A user's `組.lock` records the commit and a hash of the contents. If the tag moves, the user's kumu stops with the error "コミットが 組.lock と違います" (the commit differs from 組.lock). To fix something, raise the version and put on a new tag.

- A fix that does not change how the library is used: `1.0.0` → `1.0.1`
- You added functions: `1.0.0` → `1.1.0`
- You changed a function's name or parameters: `1.0.0` → `2.0.0`

When the same library is required at different versions, the newest version is used (a rule from kumu stage 2). Your library may then be used together with libraries written for an older version, so raise the major number (the leftmost) whenever the usage changes.

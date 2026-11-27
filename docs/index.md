# 「する」のドキュメント

「する」は、日本語で書く関数型のプログラミング言語です。このサイトには、標準ライブラリ(`lib/`)の API と、組み込みの関数、手引きがあります。言語の全体と決めたことは [README](https://github.com/suru-lang/suru/blob/main/README_jp.md) にあります。

API のページは、各ファイルの公開の名前を、定義のすぐ上の注釈(説明)・型の宣言・使い方・例(`例えば … は … です`)とともに並べたものです。`suru --文書` で作っています。

```{toctree}
:maxdepth: 1
:caption: 手引き

組み込み関数
AIの手引き
ライブラリを公開する
```

```{toctree}
:maxdepth: 1
:caption: 標準ライブラリ
:glob:

api/*
```

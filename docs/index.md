# Suru documentation

Suru (「する」) is a functional programming language written in Japanese. This site has the API of the standard library (`lib/`), the built-in functions and guides. The whole language and its decisions are in the [README](https://github.com/suru-lang/suru/blob/main/README.md).

Each API page lists the public names of a file with their description (the comment right above the definition), type declaration, usage and examples (`例えば … は … です`). The pages are made by `suru --文書`.

```{toctree}
:maxdepth: 1
:caption: Guides

組み込み関数
AIの手引き
ライブラリを公開する
```

```{toctree}
:maxdepth: 1
:caption: Standard library
:glob:

api/*
```

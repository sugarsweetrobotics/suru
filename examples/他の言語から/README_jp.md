# する を他の言語から呼ぶ

[English](README.md)

[`examples/export.suru`](../export.suru) の関数(`nibai`・`hikizan`・`aisatsu`・`hanbun`・`sei`・`kiroku`)を、ほかの言語から呼ぶ例です。先に、このフォルダにライブラリとヘッダを作ります。

```sh
suruc --共有ライブラリ ../export.suru -o libkeisan.so   # keisan.h も作る
```

macOS ではライブラリは `libkeisan.dylib` です。

| 言語 | フォルダ | 動かし方 |
|---|---|---|
| Python(`ctypes`) | `python/` | `python3 python/main.py ./libkeisan.so` |
| C | `c/` | `cc c/main.c -I. -L. -lkeisan -Wl,-rpath,$PWD -o main && ./main` |
| C++ | `cpp/` | `c++ -std=c++17 cpp/main.cpp -I. -L. -lkeisan -Wl,-rpath,$PWD -o main && ./main` |
| Go(cgo) | `go/` | `cd go && CGO_CFLAGS=-I$PWD/.. CGO_LDFLAGS="-L$PWD/.. -lkeisan -Wl,-rpath,$PWD/.." go run .` |
| Rust | `rust/` | `cd rust && cargo run`(ライブラリがほかの所にあれば `KEISAN_LIB_DIR` を付ける) |

どの例も同じ行を表示します。

```
nibai(21) = 42
hikizan(3, 10) = 7
aisatsu = こんにちは、世界さん
hanbun(5) = 2.5
sei(-1) = 0
記録します
nibai(2^62) = 0 error: yes
```

気を付けること(`keisan.h` にも書いてあります):

1. **返った文字列は解放する。** ライブラリが返した `char *` は呼んだ側のものなので、`keisan_free` で解放します。
2. **呼んだ後にエラーを確かめる。** 失敗した呼び出しは 0 か NULL を返し、`keisan_last_error()` で文を読めます(うまくいけば NULL)。エラーはスレッドごとなので、Go では `runtime.LockOSThread` で goroutine を1つの OS のスレッドに留めます。
3. **どのスレッドからでも呼べる。** 呼んだ側のスレッドとスタックで動きます。

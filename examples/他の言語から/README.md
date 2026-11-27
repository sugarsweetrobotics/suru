# Calling Suru from other languages

[日本語](README_jp.md)

These examples call the functions of [`examples/export.suru`](../export.suru) (`nibai`, `hikizan`, `aisatsu`, `hanbun`, `sei` and `kiroku`) from other languages. First build the library and its header in this folder:

```sh
suruc --共有ライブラリ ../export.suru -o libkeisan.so   # also writes keisan.h
```

On macOS the library is `libkeisan.dylib`.

| Language | Folder | Run |
|---|---|---|
| Python (`ctypes`) | `python/` | `python3 python/main.py ./libkeisan.so` |
| C | `c/` | `cc c/main.c -I. -L. -lkeisan -Wl,-rpath,$PWD -o main && ./main` |
| C++ | `cpp/` | `c++ -std=c++17 cpp/main.cpp -I. -L. -lkeisan -Wl,-rpath,$PWD -o main && ./main` |
| Go (cgo) | `go/` | `cd go && CGO_CFLAGS=-I$PWD/.. CGO_LDFLAGS="-L$PWD/.. -lkeisan -Wl,-rpath,$PWD/.." go run .` |
| Rust | `rust/` | `cd rust && cargo run` (set `KEISAN_LIB_DIR` if the library is elsewhere) |

Every example prints the same lines:

```
nibai(21) = 42
hikizan(3, 10) = 7
aisatsu = こんにちは、世界さん
hanbun(5) = 2.5
sei(-1) = 0
記録します
nibai(2^62) = 0 error: yes
```

Things to keep in mind (also written in `keisan.h`):

1. **Free returned strings.** A `char *` returned by the library belongs to the caller; free it with `keisan_free`.
2. **Check errors after a call.** A failed call returns 0 or NULL, and `keisan_last_error()` returns the message (NULL on success). The error is per thread, so in Go keep the goroutine on one OS thread with `runtime.LockOSThread`.
3. **Any thread can call.** Calls run on the caller's thread and stack.

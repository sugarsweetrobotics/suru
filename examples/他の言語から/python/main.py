"""する のライブラリ(examples/export.suru)を Python の ctypes から呼ぶ例 / Call a Suru library from Python (ctypes)

    suruc --共有ライブラリ examples/export.suru -o libkeisan.so
    python3 main.py ./libkeisan.so
"""

import ctypes
import sys

lib = ctypes.CDLL(sys.argv[1] if len(sys.argv) > 1 else "./libkeisan.so")

# keisan.h の宣言と同じ型を書く / the same types as in keisan.h
lib.nibai.argtypes = [ctypes.c_int64]
lib.nibai.restype = ctypes.c_int64
lib.hikizan.argtypes = [ctypes.c_int64, ctypes.c_int64]
lib.hikizan.restype = ctypes.c_int64
lib.aisatsu.argtypes = [ctypes.c_char_p]
lib.aisatsu.restype = ctypes.c_void_p  # 自分で解放するので c_char_p ではなく番地で受け取る / keep the pointer to free it
lib.hanbun.argtypes = [ctypes.c_double]
lib.hanbun.restype = ctypes.c_double
lib.sei.argtypes = [ctypes.c_int64]
lib.sei.restype = ctypes.c_int
lib.kiroku.argtypes = [ctypes.c_char_p]
lib.kiroku.restype = None
lib.keisan_last_error.restype = ctypes.c_char_p
lib.keisan_free.argtypes = [ctypes.c_void_p]


def aisatsu(name: str) -> str:
    p = lib.aisatsu(name.encode("utf-8"))
    try:
        return ctypes.string_at(p).decode("utf-8")
    finally:
        lib.keisan_free(p)


print("nibai(21) =", lib.nibai(21))
print("hikizan(3, 10) =", lib.hikizan(3, 10))
print("aisatsu =", aisatsu("世界"))
print("hanbun(5) =", lib.hanbun(5.0))
print("sei(-1) =", lib.sei(-1))
sys.stdout.flush()
lib.kiroku("記録します".encode("utf-8"))

# 失敗すると 0 を返し、keisan_last_error に文が入る / a failed call returns 0 and sets keisan_last_error
r = lib.nibai(1 << 62)
err = lib.keisan_last_error()
print("nibai(2^62) =", r, "error:", "yes" if err else "no")

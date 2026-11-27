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
lib.goukei.argtypes = [ctypes.POINTER(ctypes.c_int64), ctypes.c_int64]  # 数 の リスト は番地と長さ / a pointer and a length
lib.goukei.restype = ctypes.c_int64
lib.ten.argtypes = [ctypes.c_int64, ctypes.c_int64]
lib.ten.restype = ctypes.c_void_p  # 点 は手札(keisan_value *) / a handle
lib.keisan_show.argtypes = [ctypes.c_void_p]
lib.keisan_show.restype = ctypes.c_void_p
lib.keisan_field.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
lib.keisan_field.restype = ctypes.c_void_p
lib.keisan_to_int.argtypes = [ctypes.c_void_p]
lib.keisan_to_int.restype = ctypes.c_int64
lib.keisan_release.argtypes = [ctypes.c_void_p]
lib.kiroku.argtypes = [ctypes.c_char_p]
lib.kiroku.restype = None
lib.keisan_last_error.restype = ctypes.c_char_p
lib.keisan_free.argtypes = [ctypes.c_void_p]


def take_string(p: int) -> str:
    """ライブラリが返した文字列を読んで解放する / read and free a string from the library"""
    try:
        return ctypes.string_at(p).decode("utf-8")
    finally:
        lib.keisan_free(p)


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
xs = (ctypes.c_int64 * 4)(1, 2, 3, 4)
print("goukei([1, 2, 3, 4]) =", lib.goukei(xs, len(xs)))
p = lib.ten(3, 4)  # 手札は keisan_release で手放す / release handles with keisan_release
print("ten(3, 4) =", take_string(lib.keisan_show(p)))
y = lib.keisan_field(p, "縦".encode("utf-8"))
print("ten(3, 4).縦 =", lib.keisan_to_int(y))
lib.keisan_release(y)
lib.keisan_release(p)
sys.stdout.flush()
lib.kiroku("記録します".encode("utf-8"))

# 失敗すると 0 を返し、keisan_last_error に文が入る / a failed call returns 0 and sets keisan_last_error
r = lib.nibai(1 << 62)
err = lib.keisan_last_error()
print("nibai(2^62) =", r, "error:", "yes" if err else "no")

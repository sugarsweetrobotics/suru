"""他の言語から呼べる共有ライブラリ(「以下は外部に出す関数です」と suruc --共有ライブラリ、#208)のテスト

Python 版(suru_compile.py)と Go 版(cmd/suruc)で作った共有ライブラリを、Python の ctypes と C から呼ぶ。
clang がなければ作るテストは飛ばす(Go 版は go がなければ飛ばす)。
"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_compile  # noqa: E402
from suru import SuruError  # noqa: E402

needs_clang = pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")
WIN = sys.platform == "win32"
SO = ".dll" if WIN else ".dylib" if sys.platform == "darwin" else ".so"  # 共有ライブラリの拡張子
EXE = ".exe" if WIN else ""


def rpath(d: pathlib.Path) -> list[str]:
    """共有ライブラリを探す所を実行ファイルに書く引数(Windows では DLL を .exe と同じフォルダから探すので要らない)"""
    return [] if WIN else [f"-Wl,-rpath,{d}"]

LIB = """数 を 二倍する は 数 を 返す
x を 二倍する とは x * 2 です

数 を 数 から 引き算する は 数 を 返す
a を b から 引き算する とは b - a です

文字列 を 挨拶文にする は 文字列 を 返す
名前 を 挨拶文にする とは 「こんにちは、」 + 名前 + 「さん」 です

小数 を 半分にする は 小数 を 返す
x を 半分にする とは x / 2 です

単精度 を 単精度半分にする は 単精度 を 返す
x を 単精度半分にする とは x / 2 です

整数 を 整数二倍する は 整数 を 返す
x を 整数二倍する とは x * 2 です

数 を 正であるか判定する は 真偽 を 返す
x を 正であるか判定する とは x > 0 です

真偽 を 反転する は 真偽 を 返す
b を 反転する とは もし b ならば 偽 そうでなければ 真 です

番地 を 番地素通しする は 番地 を 返す
p を 番地素通しする とは p です

文字列 を 記録する は 無 を 返す 入出力動作
文 を 記録する とは 文 を 表示する です

数 を 零割りする は 数 を 返す
x を 零割りする とは x / 0 です

答えする は 数 を 返す
答えする とは 42 です

番地 を 数 で 適用する は 数 を 返す 入出力動作
f を x で 適用する とは f を x で 呼出する です

f を x で 呼出する とは 外部の（f） で 番地 を 数 で 受け取って 数 を 返す 入出力動作です

以下は外部に出す関数です
  二倍する は 「nibai」
  引き算する は 「hikizan」
  挨拶文にする は 「aisatsu」
  半分にする は 「hanbun」
  単精度半分にする は 「hanbun_f」
  整数二倍する は 「nibai_i」
  正であるか判定する は 「sei」
  反転する は 「hanten」
  番地素通しする は 「sudoushi」
  記録する は 「kiroku」
  零割りする は 「zerowari」
  答えする は 「kotae」
  適用する は 「tekiyou」
以上です
"""

CALLER = r"""
import ctypes, sys, threading
lib = ctypes.CDLL(sys.argv[1])
L, D, F, I, P, S = ctypes.c_int64, ctypes.c_double, ctypes.c_float, ctypes.c_int, ctypes.c_void_p, ctypes.c_char_p
def sig(name, args, res):
    f = getattr(lib, name); f.argtypes = args; f.restype = res; return f
nibai = sig("nibai", [L], L)
hikizan = sig("hikizan", [L, L], L)
aisatsu = sig("aisatsu", [S], P)
hanbun = sig("hanbun", [D], D)
hanbun_f = sig("hanbun_f", [F], F)
nibai_i = sig("nibai_i", [I], I)
sei = sig("sei", [L], I)
hanten = sig("hanten", [I], I)
sudoushi = sig("sudoushi", [P], P)
kiroku = sig("kiroku", [S], None)
zerowari = sig("zerowari", [L], L)
kotae = sig("kotae", [], L)
last_error = sig("keisan_last_error", [], S)
free = sig("keisan_free", [P], None)
init = sig("keisan_init", [], I)
print(init(), nibai(21), hikizan(3, 10), hanbun(5.0), hanbun_f(3.0), nibai_i(-4), sei(5), sei(-1), hanten(1), hanten(0), kotae())
print(sudoushi(12345))
p = aisatsu("花子".encode()); print(ctypes.string_at(p).decode()); free(p)
p = aisatsu(None); print(ctypes.string_at(p).decode()); free(p)
sys.stdout.flush()
kiroku("記録です".encode())
print(zerowari(1), last_error().decode())
print(nibai(2), last_error())
print(nibai(1 << 62), last_error().decode())
CB = ctypes.CFUNCTYPE(L, L)
cb = CB(lambda x: nibai(x) + 1)
print(sig("tekiyou", [CB, L], L)(cb, 5))
def work():
    for i in range(int(sys.argv[2])):
        p = aisatsu(("x" * (i % 40)).encode()); s = ctypes.string_at(p); free(p)
        assert s.decode() == "こんにちは、" + "x" * (i % 40) + "さん", s
        assert nibai(i) == 2 * i
ts = [threading.Thread(target=work) for _ in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
print("スレッドも大丈夫")
"""

EXPECTED = """0 42 7 2.5 1.5 -8 1 0 0 1 42
12345
こんにちは、花子さん
こんにちは、さん
記録です
0 32行目 16文字目: 0 で割ることはできません
4 None
0 43行目 3文字目: 「二倍する」に渡した数 4611686018427387904 が大きすぎます(数は ±4611686018427387903 までです)
11
スレッドも大丈夫
"""

HOST_C = r"""
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
int64_t nibai(int64_t); int64_t tekiyou(int64_t (*)(int64_t), int64_t); int64_t zerowari(int64_t);
const char *keisan_last_error(void);
static int64_t cb(int64_t x) { return nibai(x) + 1; }
static void *run(void *a) {
    (void)a;
    for (int i = 0; i < 3000; i++)
        if (tekiyou(cb, i) != 2 * i + 1) printf("違います\n");
    return 0;
}
int main(void) {
    pthread_t t[4];
    for (int i = 0; i < 4; i++) pthread_create(&t[i], 0, run, 0);
    for (int i = 0; i < 4; i++) pthread_join(t[i], 0);
    printf("%lld %lld\n", (long long)tekiyou(cb, 5), (long long)zerowari(3));
    printf("%s\n", keisan_last_error());
    return 0;
}
"""


@pytest.fixture(scope="module")
def suruc(tmp_path_factory):
    if shutil.which("go") is None:
        pytest.skip("go がありません")
    exe = tmp_path_factory.mktemp("go") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return exe


def build_py(src: pathlib.Path, out: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), "--翻訳", "--共有ライブラリ", str(src), "-o", str(out)],
                          capture_output=True, text=True)


def build_go(suruc: pathlib.Path, src: pathlib.Path, out: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(suruc), "--共有ライブラリ", str(src), "-o", str(out)], capture_output=True, text=True)


def run_caller(lib: pathlib.Path, n: int = 2000, env: dict | None = None) -> str:
    r = subprocess.run([sys.executable, "-c", CALLER, str(lib), str(n)], capture_output=True, text=True, timeout=600,
                       env={**os.environ, **(env or {})})
    assert r.returncode == 0, r.stderr
    return r.stdout


def parse_error(source: str) -> str:
    with pytest.raises(SuruError) as e:
        suru.parse_program(source, suru.ParseContext())
    return str(e.value)


# --- 書き方と型の検査 ---

def test_インタプリタは出す関数のまとまりを読み飛ばす():
    out: list[str] = []
    it = suru.Interpreter(out=lambda s: out.append(s))
    it.run("数 を 二倍する は 数\nx を 二倍する とは x * 2\n以下は外部に出す関数です\n  二倍する は 「nibai」\n以上です\n"
           "（3 を 二倍する） を 表示する\n")
    assert out == ["6"]


def test_句読点と空白の書き方でも読める():
    for src in ("数を二倍するは、数を返す。\nxを二倍するとは、x*2です。\n以下は外部に出す関数です。\n二倍するは、「nibai」。\n以上です。\n",
                "数 を 二倍する は 数\nx を 二倍する とは x * 2\n以下 は 外部 に 出す 関数 です\n  二倍する は 「nibai」\n以上\n"):
        prog = suru.parse_program(src, suru.ParseContext())
        e = [s for s in prog if isinstance(s, suru.Export)]
        assert [(x.name, x.symbol, x.params, x.result) for x in e] == [("二倍する", "nibai", ["i64"], "i64")]


def test_型の宣言から_C_の型を決める():
    prog = suru.parse_program(LIB, suru.ParseContext())
    got = {x.symbol: (x.params, x.result, x.action) for x in prog if isinstance(x, suru.Export)}
    assert got["hikizan"] == (["i64", "i64"], "i64", False)
    assert got["aisatsu"] == (["str"], "str", False)
    assert got["hanbun_f"] == (["f32"], "f32", False)
    assert got["sei"] == (["i64"], "bool", False)
    assert got["kiroku"] == (["str"], "void", True)
    assert got["kotae"] == ([], "i64", False)
    assert got["tekiyou"] == (["ptr", "i64"], "i64", True)


HEAD = "数 を 二倍する は 数\nx を 二倍する とは x * 2\n"


@pytest.mark.parametrize("body, message", [
    ("  三倍する は 「a」\n", "「三倍する」はこのファイルで定義していないので、外部に出せません"),
    ("  二倍する は 「2bai」\n", "「2bai」は C の名前にできません"),
    ("  二倍する は 「二倍」\n", "「二倍」は C の名前にできません"),
    ("  二倍する は 「rt_x」\n", "C の名前「rt_x」は「rt_」で始まるので使えません"),
    ("  二倍する は 「suru_main」\n", "C の名前「suru_main」は「suru_」で始まるので使えません"),
    ("  二倍する は 「main」\n", "C の名前「main」は使えません"),
    ("  二倍する は 「a」\n  二倍する は 「b」\n", "「二倍する」がまとまりの中で2回書かれています"),
    ("  二倍する は 「a」\n  三倍する は 「a」\n", "C の名前「a」がまとまりの中で2回書かれています"),
    ("  二倍する\n", "「以下は外部に出す関数です」の中には、1行に1つ"),
    ("  税率 は 「a」\n", "「税率」は関数ではないので、外部に出せません"),
])
def test_まとまりの間違い(body, message):
    assert message in parse_error(HEAD + "以下は外部に出す関数です\n" + body + "以上です\n")


@pytest.mark.parametrize("source, message", [
    ("x を 三倍する とは x * 3\n以下は外部に出す関数です\n  三倍する は 「a」\n以上です\n",
     "外部に出す関数「三倍する」には型の宣言が必要です"),
    ("無 を 空読みする は 数\nx を 空読みする とは 1\n以下は外部に出す関数です\n  空読みする は 「a」\n以上です\n",
     "外部に出す関数「空読みする」の「を」に 無 は使えません"),
    ("文字列 を 長さ計測する は 数\ns を 長さ計測する とは 外部の「strlen」\n以下は外部に出す関数です\n  長さ計測する は 「a」\n以上です\n",
     "「長さ計測する」は外部の関数なので、外部に出せません"),
    ("文字列 を 長さ計測する は 数\ns を 長さ計測する とは 外部の「strlen」\n" + HEAD
     + "以下は外部に出す関数です\n  二倍する は 「strlen」\n以上です\n",
     "C の名前「strlen」は、このファイルで読み込む外部の関数と同じです"),
    (HEAD + "以下は外部に出す関数です\n  二倍する は 「a」\n", "「以下は外部に出す関数です」を閉じる「以上」がありません"),
    (HEAD + "以下は外部に出す関数です\n以上です\n", "「以下は外部に出す関数です」と「以上」の間に関数がありません"),
])
def test_出せない関数(source, message):
    assert message in parse_error(source)


def test_実行ファイルでは出す関数があっても動く(tmp_path):
    if suru_compile.find_cc() is None:
        pytest.skip("clang がありません")
    src = tmp_path / "prog.suru"
    src.write_text(HEAD + "以下は外部に出す関数です\n  二倍する は 「nibai」\n以上です\n（4 を 二倍する） を 表示する\n", encoding="utf-8")
    exe = tmp_path / "prog"
    subprocess.run([sys.executable, str(ROOT / "suru.py"), "--翻訳", str(src), "-o", str(exe)], check=True)
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout == "8\n"


# --- 共有ライブラリを作る ---

@needs_clang
def test_一番外の文は共有ライブラリにできない(tmp_path):
    src = tmp_path / "keisan.suru"
    src.write_text(HEAD + "「やあ」 を 表示する\n以下は外部に出す関数です\n  二倍する は 「nibai」\n以上です\n", encoding="utf-8")
    r = build_py(src, tmp_path / ("libkeisan" + SO))
    assert r.returncode == 1
    assert "共有ライブラリにするファイルの一番外には、定義だけを書きます" in r.stderr


@needs_clang
def test_出す関数がなければ共有ライブラリにできない(tmp_path):
    src = tmp_path / "keisan.suru"
    src.write_text(HEAD, encoding="utf-8")
    r = build_py(src, tmp_path / ("libkeisan" + SO))
    assert r.returncode == 1
    assert "共有ライブラリにするには、「以下は外部に出す関数です」で外部に出す関数を書きます" in r.stderr


@needs_clang
def test_ライブラリの名前は_C_の名前にする(tmp_path):
    src = tmp_path / "keisan.suru"
    src.write_text(HEAD + "以下は外部に出す関数です\n  二倍する は 「nibai」\n以上です\n", encoding="utf-8")
    r = build_py(src, tmp_path / ("lib計算" + SO))
    assert r.returncode == 1
    assert "-o には英字・数字・「_」だけの名前を付けてください" in r.stderr


@needs_clang
def test_Pythonから呼ぶ(tmp_path):
    src = tmp_path / "keisan.suru"
    src.write_text(LIB, encoding="utf-8")
    r = build_py(src, tmp_path / "libkeisan")
    assert r.returncode == 0, r.stderr
    lib = tmp_path / ("libkeisan" + SO)
    assert run_caller(lib) == EXPECTED


@needs_clang
def test_GCを何度も動かしても大丈夫(tmp_path):
    src = tmp_path / "keisan.suru"
    src.write_text(LIB, encoding="utf-8")
    lib = tmp_path / ("libkeisan" + SO)
    assert build_py(src, lib).returncode == 0
    assert run_caller(lib, 300, {"SURU_GC_MIN": "0"}) == EXPECTED


@needs_clang
def test_Go版で作ってPythonから呼ぶ(suruc, tmp_path):
    src = tmp_path / "keisan.suru"
    src.write_text(LIB, encoding="utf-8")
    lib = tmp_path / ("libkeisan" + SO)
    r = build_go(suruc, src, lib)
    assert r.returncode == 0, r.stderr
    assert run_caller(lib) == EXPECTED


@needs_clang
def test_Cから呼んで呼び戻す(tmp_path):
    """C → する(適用する)→ C(cb)→ する(二倍する)と入れ子に呼ぶ。いくつものスレッドから"""
    src = tmp_path / "keisan.suru"
    src.write_text(LIB, encoding="utf-8")
    assert build_py(src, tmp_path / ("libkeisan" + SO)).returncode == 0
    (tmp_path / "host.c").write_text(HOST_C, encoding="utf-8")
    cc = suru_compile.find_cc()
    subprocess.run([cc, "host.c", f"-L{tmp_path}", "-lkeisan", *rpath(tmp_path), "-lpthread", "-o", "host" + EXE],
                   cwd=tmp_path, check=True)
    r = subprocess.run([str(tmp_path / ("host" + EXE))], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "11 0\n32行目 16文字目: 0 で割ることはできません\n"


@needs_clang
def test_する_のライブラリ2つと実行ファイル(tmp_path):
    """実行時ライブラリの名前は隠すので、する のライブラリを2つ読み込んでも、する の実行ファイルから読み込んでもぶつからない"""
    src = tmp_path / "keisan.suru"
    src.write_text(LIB, encoding="utf-8")
    assert build_py(src, tmp_path / ("libkeisan" + SO)).returncode == 0
    (tmp_path / "b.suru").write_text("数 を 三倍する は 数\nx を 三倍する とは x * 3\n以下は外部に出す関数です\n  三倍する は 「sanbai」\n以上です\n",
                                     encoding="utf-8")
    assert build_py(tmp_path / "b.suru", tmp_path / ("libb" + SO)).returncode == 0
    code = (f"import ctypes\na = ctypes.CDLL(r'{tmp_path / ('libkeisan' + SO)}'); b = ctypes.CDLL(r'{tmp_path / ('libb' + SO)}')\n"
            "a.nibai.restype = b.sanbai.restype = ctypes.c_int64\n"
            "a.nibai.argtypes = b.sanbai.argtypes = [ctypes.c_int64]\nprint(a.nibai(5), b.sanbai(5))\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout == "10 15\n", r.stderr
    prog = tmp_path / "使う.suru"
    # Windows では import ライブラリ(lib名前.dll.a)をリンクし、DLL は .exe と同じフォルダから読む
    link = "libkeisan.dll.a" if WIN else "libkeisan" + SO
    prog.write_text(f"外部の「./{link}」 を 読み込む\n\n以下は外部の関数です\n  数 を 外の二倍する は 「nibai」 で 数 を 返します\n以上です\n\n"
                    "（21 を 外の二倍する） を 表示する\n", encoding="utf-8")
    exe = tmp_path / "使う"
    subprocess.run([sys.executable, str(ROOT / "suru.py"), "--翻訳", str(prog), "-o", str(exe)], check=True)
    assert subprocess.run([str(exe) + EXE], capture_output=True, text=True, cwd=tmp_path).stdout == "42\n"
    nm = shutil.which("nm")
    if nm and sys.platform.startswith("linux"):
        syms = subprocess.run([nm, "-D", "--defined-only", str(tmp_path / ("libb" + SO))], capture_output=True, text=True).stdout
        names = sorted(line.split()[-1] for line in syms.splitlines())
        assert names == sorted(["sanbai"] + suru_compile.lib_helper_symbols("b"))
        assert not [n for n in names if n.startswith(("rt_", "gc_", "suru_"))]


# --- ヘッダとほかの言語の例(#208 段階2) ---

EXAMPLES = ROOT / "examples" / "他の言語から"
EXAMPLE_OUT = ("nibai(21) = 42\nhikizan(3, 10) = 7\naisatsu = こんにちは、世界さん\nhanbun(5) = 2.5\nsei(-1) = 0\n"
               "goukei([1, 2, 3, 4]) = 10\nten(3, 4) = （横 は 3 で 縦 は 4 の 点）\nten(3, 4).縦 = 4\n"
               "記録します\nnibai(2^62) = 0 error: yes\n")


def test_ヘッダの形():
    ir = suru_compile.compile_source((ROOT / "examples" / "export.suru").read_text(encoding="utf-8"),
                                     str(ROOT / "examples"), str(ROOT / "examples" / "export.suru"), True, lib=True)
    h = suru_compile.export_header(ir, "keisan")
    assert h.startswith("/* keisan.h: generated by suruc. Do not edit.\n")
    assert "#ifndef KEISAN_H\n#define KEISAN_H\n" in h and h.endswith("#endif /* KEISAN_H */\n")
    assert 'extern "C" {' in h
    for decl in ("int keisan_init(void);", "const char *keisan_last_error(void);", "void keisan_free(void *p);",
                 "/* する: 二倍する  数 → 数 */\nint64_t nibai(int64_t a1);",
                 "/* する: 引き算する  数 と 数 → 数 */\nint64_t hikizan(int64_t a1, int64_t a2);",
                 "char *aisatsu(const char *a1);", "double hanbun(double a1);", "int sei(int64_t a1);",
                 "/* する: 記録する  文字列 → 無(入出力動作) */\nvoid kiroku(const char *a1);"):
        assert decl in h, decl
    assert "/* する: 合計する  数 の リスト → 数 */\nint64_t goukei(const int64_t *a1, int64_t a1_len);" in h
    assert "keisan_value *ten(int64_t a1, int64_t a2);" in h
    assert "typedef struct keisan_value keisan_value;" in h
    for name in suru_compile.lib_helper_symbols("keisan"):
        assert f" {name}(" in h or f"*{name}(" in h, name
    assert suru_compile.export_symbols(ir) == ["nibai", "hikizan", "aisatsu", "hanbun", "sei", "goukei", "ten", "kiroku"]


def test_ヘッダの型と引数なし():
    src = ("単精度 を 単精度半分にする は 単精度 を 返す\nx を 単精度半分にする とは x / 2 です\n"
           "整数 を 番地 で 整数足しする は 整数 を 返す\nx を p で 整数足しする とは x + 1 です\n"
           "答え返却する は 数 を 返す\n答え返却する とは 42 です\n"
           "以下は外部に出す関数です\n  単精度半分にする は 「f」\n  整数足しする は 「g」\n  答え返却する は 「h」\n以上です\n")
    h = suru_compile.export_header(suru_compile.compile_source(src, ".", "x.suru", True, lib=True), "x")
    assert "float f(float a1);" in h
    assert "/* する: 整数足しする  整数 と 番地 → 整数 */\nint g(int a1, void *a2);" in h
    assert "/* する: 答え返却する  (なし) → 数 */\nint64_t h(void);" in h


@needs_clang
def test_ヘッダは_C_と_C_plus_plus_で通る(tmp_path):
    assert build_py(ROOT / "examples" / "export.suru", tmp_path / ("libkeisan" + SO)).returncode == 0
    h = tmp_path / "keisan.h"
    assert h.exists()
    cc = suru_compile.find_cc()
    (tmp_path / "t.c").write_text('#include "keisan.h"\nint main(void) { return 0; }\n', encoding="utf-8")
    subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic", "-c", "t.c"], cwd=tmp_path, check=True)
    cxx = shutil.which("clang++") or shutil.which("c++")
    if cxx:
        (tmp_path / "t.cpp").write_text('#include "keisan.h"\nint main() { return 0; }\n', encoding="utf-8")
        subprocess.run([cxx, "-Wall", "-Wextra", "-Werror", "-c", "t.cpp"], cwd=tmp_path, check=True)


@needs_clang
def test_Go版とPython版のヘッダは同じ(suruc, tmp_path):
    (tmp_path / "py").mkdir()
    (tmp_path / "go").mkdir()
    assert build_py(ROOT / "examples" / "export.suru", tmp_path / "py" / ("libkeisan" + SO)).returncode == 0
    r = build_go(suruc, ROOT / "examples" / "export.suru", tmp_path / "go" / ("libkeisan" + SO))
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "go" / "keisan.h").read_text(encoding="utf-8") == (tmp_path / "py" / "keisan.h").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def keisan(tmp_path_factory):
    """examples/export.suru から作った libkeisan とヘッダのある所"""
    if suru_compile.find_cc() is None:
        pytest.skip("共有ライブラリを作れません")
    d = tmp_path_factory.mktemp("keisan")
    r = build_py(ROOT / "examples" / "export.suru", d / "libkeisan")
    assert r.returncode == 0, r.stderr
    return d


def libfile(d: pathlib.Path) -> pathlib.Path:
    return d / ("libkeisan" + SO)


def test_例_Python(keisan):
    r = subprocess.run([sys.executable, str(EXAMPLES / "python" / "main.py"), str(libfile(keisan))],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXAMPLE_OUT


def test_例_C(keisan):
    cc = suru_compile.find_cc()
    subprocess.run([cc, str(EXAMPLES / "c" / "main.c"), f"-I{keisan}", f"-L{keisan}", "-lkeisan", *rpath(keisan),
                    "-o", str(keisan / ("main_c" + EXE))], check=True)
    r = subprocess.run([str(keisan / ("main_c" + EXE))], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXAMPLE_OUT


def test_例_C_plus_plus(keisan):
    cxx = shutil.which("clang++") or shutil.which("c++")
    if cxx is None:
        pytest.skip("C++ のコンパイラがありません")
    subprocess.run([cxx, "-std=c++17", str(EXAMPLES / "cpp" / "main.cpp"), f"-I{keisan}", f"-L{keisan}", "-lkeisan",
                    *rpath(keisan), "-o", str(keisan / ("main_cpp" + EXE))], check=True)
    r = subprocess.run([str(keisan / ("main_cpp" + EXE))], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXAMPLE_OUT


def test_例_Go(keisan):
    if shutil.which("go") is None:
        pytest.skip("go がありません")
    env = {**os.environ, "CGO_ENABLED": "1", "CGO_CFLAGS": f"-I{keisan}",
           "CGO_LDFLAGS": " ".join([f"-L{keisan}", "-lkeisan", *rpath(keisan)])}
    subprocess.run(["go", "build", "-o", str(keisan / ("main_go" + EXE)), "."], cwd=EXAMPLES / "go", env=env, check=True)
    r = subprocess.run([str(keisan / ("main_go" + EXE))], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXAMPLE_OUT


def test_例_Rust(keisan):
    if shutil.which("cargo") is None:
        pytest.skip("cargo がありません")
    env = {**os.environ, "KEISAN_LIB_DIR": str(keisan), "CARGO_TARGET_DIR": str(keisan / "rust-target")}
    r = subprocess.run(["cargo", "run", "-q", "--offline"], cwd=EXAMPLES / "rust", env=env, capture_output=True, text=True,
                       timeout=600)
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXAMPLE_OUT


# --- バイト列・リスト・手札(#208 段階3) ---

SEQ_LIB = """「標準」 を 読み込んで 使う

数 の リスト を 合計する は 数 を 返す
xs を 合計する とは xs を 加算する です

小数 の リスト を 平均する は 小数 を 返す
xs を 平均する とは （xs を 加算する） / （xs の 長さ） です

文字列 の リスト を 横線結合する は 文字列 を 返す
xs を 横線結合する とは xs を 「-」 で 結合する です

数 を 二乗する は 数 を 返す
x を 二乗する とは x * x です

数 の リスト を 二乗並びにする は 数 の リスト を 返す
xs を 二乗並びにする とは xs の それぞれ を 二乗する です

文字列 の リスト を 逆並びにする は 文字列 の リスト を 返す
xs を 逆並びにする とは xs を 逆順にする です

小数 を 半分にする は 小数 を 返す
x を 半分にする とは x / 2 です

小数 の リスト を 半分並びにする は 小数 の リスト を 返す
xs を 半分並びにする とは xs の それぞれ を 半分にする です

バイト列 を 長さ数えする は 数 を 返す
b を 長さ数えする とは b を バイト長にする です

文字列 を バイト変換する は バイト列 を 返す
s を バイト変換する とは s を バイト列にする です

数 を 内階乗する は 数 を 返す
0 を 内階乗する とは 1 です
n を 内階乗する とは n * （n - 1 を 内階乗する） です

数 を 階乗する は 数 を 返す
n を 階乗する とは n を 内階乗する です

点 とは 横 と 縦 の 組

数 を 数 で 点にする は 点 を 返す
x を y で 点にする とは （x と y の 点） です

点 を 横を読みする は 数 を 返す
p を 横を読みする とは p の 横 です

数 を 加算器にする は （数 を 受け取って 数 を 返すこと） を 返す
n を 加算器にする とは （x を 受け取って x + n を 返すこと） です

以下は外部に出す関数です
  合計する は 「goukei」
  平均する は 「heikin」
  横線結合する は 「tsunagu」
  二乗並びにする は 「nijou」
  逆並びにする は 「gyaku」
  半分並びにする は 「hanbun」
  長さ数えする は 「nagasa」
  バイト変換する は 「baito」
  階乗する は 「kaijou」
  点にする は 「ten」
  横を読みする は 「yoko」
  加算器にする は 「kasanki」
以上です
"""

SEQ_HOST = r"""
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include "seq.h"

#define ERR (seq_last_error() ? seq_last_error() : "ok")

static void *work(void *arg) {
    long k = (long)arg;
    for (int64_t i = 0; i < 2000; i++) {
        int64_t xs[3] = {i, k, 1};
        if (goukei(xs, 3) != i + k + 1) return "goukei";
        const char *ss[2] = {"a", "b"};
        char *t = tsunagu(ss, 2);
        if (strcmp(t, "a-b") != 0) return "tsunagu";
        seq_free(t);
        int64_t n;
        char **g = gyaku(ss, 2, &n);
        if (n != 2 || strcmp(g[0], "b") != 0 || g[2] != NULL) return "gyaku";
        seq_free(g);
        seq_value *p = ten(i, k);
        if (yoko(p) != i) return "yoko";
        seq_value *y = seq_field(p, "縦");
        if (seq_to_int(y) != k) return "field";
        seq_release(y);
        seq_release(p);
        seq_value *f = kasanki(i);
        seq_value *x = seq_from_int(k);
        seq_value *r = seq_call(f, &x, 1);
        if (seq_to_int(r) != i + k) return "call";
        seq_release(f);
        seq_release(x);
        seq_release(r);
    }
    return NULL;
}

int main(void) {
    int64_t xs[] = {1, 2, 3, 4}, n = -1;
    printf("goukei %" PRId64 "\n", goukei(xs, 4));
    int64_t r = goukei(NULL, 0);
    printf("goukei() %" PRId64 " %s\n", r, ERR);
    double ds[] = {1.0, 2.0, 4.5};
    printf("heikin %g\n", heikin(ds, 3));
    int64_t *sq = nijou(xs, 4, &n);
    printf("nijou %" PRId64 " %" PRId64 " %" PRId64 " %" PRId64 " n=%" PRId64 "\n", sq[0], sq[1], sq[2], sq[3], n);
    seq_free(sq);
    sq = nijou(xs, 0, &n);
    printf("nijou() n=%" PRId64 " %s\n", n, sq ? "nonnull" : "null");
    seq_free(sq);
    double *h = hanbun(ds, 3, NULL);
    printf("hanbun %g %g %g\n", h[0], h[1], h[2]);
    seq_free(h);
    uint8_t bs[] = {1, 0, 2};
    printf("nagasa %" PRId64 "\n", nagasa(bs, 3));
    uint8_t *b = baito("aé", &n);
    printf("baito n=%" PRId64 " %02x %02x %02x\n", n, b[0], b[1], b[2]);
    seq_free(b);
    printf("kaijou %" PRId64 "\n", kaijou(20));
    int64_t big[] = {1, INT64_C(1) << 62};
    r = goukei(big, 2);
    printf("big %" PRId64 " %s\n", r, ERR);
    sq = nijou(NULL, 3, &n);
    printf("null %s %s\n", sq ? "nonnull" : "null", ERR);
    r = goukei(xs, -1);
    printf("neg %" PRId64 " %s\n", r, ERR);
    const char *bad[] = {"a", NULL};
    char *t = tsunagu(bad, 2);
    printf("nullstr %s %s\n", t ? "nonnull" : "null", ERR);

    seq_value *p = ten(3, 4);
    const char *ty = seq_type(p);
    printf("type %s\n", ty);
    char *s = seq_show(p);
    printf("show %s\n", s);
    seq_free(s);
    seq_value *q = seq_field(p, "高さ");
    printf("field %s %s\n", q ? "nonnull" : "null", ERR);
    seq_value *items[3] = {seq_from_int(1), seq_from_string("あ"), p};
    seq_value *l = seq_list(items, 3);
    s = seq_show(l);
    printf("list %s len=%" PRId64 "\n", s, seq_len(l));
    seq_free(s);
    seq_value *e = seq_get(l, 1);
    s = seq_to_string(e);
    printf("get %s %s\n", s, seq_type(e));
    seq_free(s);
    r = seq_to_int(e);
    printf("to_int %" PRId64 " %s\n", r, ERR);
    seq_value *g = seq_get(l, 5);
    printf("get5 %s %s\n", g ? "nonnull" : "null", ERR);
    r = yoko(NULL);
    printf("yoko(NULL) %" PRId64 " %s\n", r, ERR);
    seq_value *d = seq_from_double(2.5), *tr = seq_from_bool(1);
    double dv = seq_to_double(d);
    int bv = seq_to_bool(tr);
    printf("double %g bool %d\n", dv, bv);
    seq_release(d);
    seq_release(tr);
    seq_release(e);
    seq_release(l);
    for (int i = 0; i < 3; i++) seq_release(items[i]);
    seq_release(NULL);

    pthread_t th[6];
    for (long i = 0; i < 6; i++) pthread_create(&th[i], NULL, work, (void *)i);
    for (int i = 0; i < 6; i++) {
        void *res;
        pthread_join(th[i], &res);
        if (res) printf("thread failed: %s\n", (char *)res);
    }
    printf("threads ok\n");
    return 0;
}
"""

SEQ_OUT = """goukei 10
goukei() 0 ok
heikin 2.5
nijou 1 4 9 16 n=4
nijou() n=0 nonnull
hanbun 0.5 1 2.25
nagasa 3
baito n=3 61 c3 a9
kaijou 2432902008176640000
big 0 52行目 3文字目: 「合計する」に渡したリストの 2 番目の数 4611686018427387904 が大きすぎます(数は ±4611686018427387903 までです)
null null 55行目 3文字目: 「二乗並びにする」に渡した番地が NULL です(長さは 3)
neg 0 52行目 3文字目: 「合計する」に渡した長さ -1 が負です
nullstr null 54行目 3文字目: 「横線結合する」に渡したリストの 2 番目の文字列が NULL です
type 点
show （横 は 3 で 縦 は 4 の 点）
field null 「（横 は 3 で 縦 は 4 の 点）」には「高さ」というフィールドがありません
list （1 と 「あ」 と （横 は 3 で 縦 は 4 の 点）） len=3
get あ 文字列
to_int 0 「手札」の値は整数でなければなりません(「あ」でした)
get5 null 手札のリストの 5 番目はありません(番号は 0 から 2 まで)
yoko(NULL) 0 手札が NULL です
double 2.5 bool 1
threads ok
"""


def run_seq_host(lib_dir: pathlib.Path, env: dict | None = None) -> str:
    (lib_dir / "host.c").write_text(SEQ_HOST, encoding="utf-8")
    cc = suru_compile.find_cc()
    subprocess.run([cc, "-Wall", "-Werror", "host.c", f"-I{lib_dir}", f"-L{lib_dir}", "-lseq", *rpath(lib_dir),
                    "-lpthread", "-o", "host" + EXE], cwd=lib_dir, check=True)
    r = subprocess.run([str(lib_dir / ("host" + EXE))], cwd=lib_dir, capture_output=True, text=True, timeout=300, env={**os.environ, **(env or {})})
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_リストと手札の型():
    ir = suru_compile.compile_source(SEQ_LIB, str(ROOT / "lib"), "seq.suru", True, lib=True)
    h = suru_compile.export_header(ir, "seq")
    for decl in ("double heikin(const double *a1, int64_t a1_len);",
                 "char *tsunagu(const char *const *a1, int64_t a1_len);",
                 "int64_t *nijou(const int64_t *a1, int64_t a1_len, int64_t *out_len);",
                 "char **gyaku(const char *const *a1, int64_t a1_len, int64_t *out_len);",
                 "double *hanbun(const double *a1, int64_t a1_len, int64_t *out_len);",
                 "int64_t nagasa(const uint8_t *a1, int64_t a1_len);",
                 "uint8_t *baito(const char *a1, int64_t *out_len);",
                 "seq_value *ten(int64_t a1, int64_t a2);", "int64_t yoko(seq_value *a1);", "seq_value *kasanki(int64_t a1);"):
        assert decl in h, decl
    # 整数 の リスト や 組 の リスト は手札で渡す
    src = ("点 とは 横 と 縦 の 組\n点 の リスト を 数え上げする は 点 の リスト を 返す\nxs を 数え上げする とは xs です\n"
           "以下は外部に出す関数です\n  数え上げする は 「f」\n以上です\n")
    h = suru_compile.export_header(suru_compile.compile_source(src, ".", "x.suru", True, lib=True), "x")
    assert "/* する: 数え上げする  (手札) → (手札)" in h and "x_value *f(x_value *a1);" in h


@needs_clang
def test_リストと手札をCから使う(tmp_path):
    (tmp_path / "seq.suru").write_text(SEQ_LIB, encoding="utf-8")
    r = build_py(tmp_path / "seq.suru", tmp_path / ("libseq" + SO))
    assert r.returncode == 0, r.stderr
    assert run_seq_host(tmp_path) == SEQ_OUT


@needs_clang
def test_リストと手札でGCを何度も動かす(tmp_path):
    (tmp_path / "seq.suru").write_text(SEQ_LIB, encoding="utf-8")
    assert build_py(tmp_path / "seq.suru", tmp_path / ("libseq" + SO)).returncode == 0
    assert run_seq_host(tmp_path, {"SURU_GC_MIN": "0"}) == SEQ_OUT


@needs_clang
def test_Go版でリストと手札(suruc, tmp_path):
    (tmp_path / "seq.suru").write_text(SEQ_LIB, encoding="utf-8")
    r = build_go(suruc, tmp_path / "seq.suru", tmp_path / ("libseq" + SO))
    assert r.returncode == 0, r.stderr
    assert run_seq_host(tmp_path) == SEQ_OUT
    py = tmp_path / "py"
    py.mkdir()
    assert build_py(tmp_path / "seq.suru", py / ("libseq" + SO)).returncode == 0
    assert (py / "seq.h").read_text(encoding="utf-8") == (tmp_path / "seq.h").read_text(encoding="utf-8")

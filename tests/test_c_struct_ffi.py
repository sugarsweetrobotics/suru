"""外部の関数で C構造体を値で渡す・返す(#241 段階2・3)。C のコンパイラが決める並びと呼び出しの決まりと同じになるか"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
from suru import SuruError  # noqa: E402
from test_ffi import compiled, interpreted  # noqa: E402

# 試験の中で作る C のライブラリ(Windows は DLL)
LIB = "libst.dll" if sys.platform == "win32" else "libst.so"
needs_cc = pytest.mark.skipif(shutil.which("cc") is None and shutil.which("clang") is None, reason="C コンパイラがありません")

# 大きさの違う構造体(1・2・4・8・12・16・24 バイト、単精度と小数だけのもの、入れ子)。どれも値で受け取って値で返す
C_SOURCE = r"""
#include <stdint.h>
typedef struct { uint8_t a; } S1;
typedef struct { int8_t a; uint8_t b; } S2;
typedef struct { int16_t a; uint16_t b; } S4;
typedef struct { int32_t a; float b; } S8;
typedef struct { int32_t a; int32_t b; int32_t c; } S12;
typedef struct { int64_t a; double b; } S16;
typedef struct { int64_t a; int64_t b; int64_t c; } S24;
typedef struct { float x; float y; } F2;
typedef struct { double x; double y; double z; double w; } D4;
typedef struct { int64_t sec; uint32_t nsec; } T;
typedef struct { uint64_t depth; T deadline; float rate; uint8_t flag; void *p; } Q;

S1 s1(S1 v) { v.a += 1; return v; }
S2 s2(S2 v) { v.a -= 1; v.b += 1; return v; }
S4 s4(S4 v) { v.a *= 2; v.b += 1; return v; }
S8 s8(S8 v) { v.a += 1; v.b *= 2; return v; }
S12 s12(S12 v) { S12 r = { v.c, v.b, v.a }; return r; }
S16 s16(S16 v) { v.a += 1; v.b /= 2; return v; }
S24 s24(S24 v) { S24 r = { v.a + v.b + v.c, v.a, v.b }; return r; }
F2 f2(F2 v) { F2 r = { v.y, v.x }; return r; }
D4 d4(D4 v) { D4 r = { v.w, v.z, v.y, v.x }; return r; }
T add_time(T a, T b) { T r = { a.sec + b.sec, a.nsec + b.nsec }; return r; }
int64_t total(int64_t k, T a, double m) { return k + (int64_t)((double)(a.sec * 1000000000 + a.nsec) * m); }
Q make_q(int64_t d) { Q q = { (uint64_t)d, { d, (uint32_t)(d * 2) }, 0.5f, 1, (void *)0x10 }; return q; }
double q_sum(Q q) { return (double)q.depth + q.deadline.sec + q.deadline.nsec + q.rate + q.flag + (double)(uintptr_t)q.p; }
void *pick_total(void) { return (void *)total; }
"""

PROGRAM = """「標準」 を 読み込んで 使う
外部の「./""" + LIB + """」 を 読み込む
甲1 とは a は 符号なし8 の C構造体
甲2 とは a は 符号付き8 で b は 符号なし8 の C構造体
甲4 とは a は 符号付き16 で b は 符号なし16 の C構造体
甲8 とは a は 符号付き32 で b は 単精度 の C構造体
甲12 とは a は 符号付き32 で b は 符号付き32 で c は 符号付き32 の C構造体
甲16 とは a は 符号付き64 で b は 小数 の C構造体
甲24 とは a は 符号付き64 で b は 符号付き64 で c は 符号付き64 の C構造体
浮2 とは x は 単精度 で y は 単精度 の C構造体
浮4 とは x は 小数 で y は 小数 で z は 小数 で w は 小数 の C構造体
時間 とは 秒 は 符号付き64 で ナノ秒 は 符号なし32 の C構造体
品質 とは 深さ は 符号なし64 で 期限 は 時間 で 率 は 単精度 で 印 は 真偽 で 先 は 番地 の C構造体
以下は外部の関数です
  甲1 を 一処理する は 「s1」 で 甲1 を 返します
  甲2 を 二処理する は 「s2」 で 甲2 を 返します
  甲4 を 四処理する は 「s4」 で 甲4 を 返します
  甲8 を 八処理する は 「s8」 で 甲8 を 返します
  甲12 を 十二処理する は 「s12」 で 甲12 を 返します
  甲16 を 十六処理する は 「s16」 で 甲16 を 返します
  甲24 を 二十四処理する は 「s24」 で 甲24 を 返します
  浮2 を 浮二処理する は 「f2」 で 浮2 を 返します
  浮4 を 浮四処理する は 「d4」 で 浮4 を 返します
  時間 を 時間 に 時間加算する は 「add_time」 で 時間 を 返します
  数 を 時間 に 小数 で 総ナノ秒にする は 「total」 で 数 を 返します
  数 を 品質作成する は 「make_q」 で 品質 を 返します
  品質 を 品質合計する は 「q_sum」 で 小数 を 返します
  総ナノ秒番地取得する は 「pick_total」 で 番地 を 返します
以上です
数 を 時間 に 小数 で 番地 から 番地経由総ナノ秒にする は 数
k を t に m で f から 番地経由総ナノ秒にする とは 外部の（f）
（254 の 甲1） を 一処理する
（-128 と 255 の 甲2） を 二処理する
（-300 と 65534 の 甲4） を 四処理する
（7 と 1.25 の 甲8） を 八処理する
（1 と 2 と 3 の 甲12） を 十二処理する
（4611686018427387902 と 3.0 の 甲16） を 十六処理する
（1 と 2 と 3 の 甲24） を 二十四処理する
（1.5 と 2.5 の 浮2） を 浮二処理する
（1.0 と 2.0 と 3.0 と 4.0 の 浮4） を 浮四処理する
（1 と 2 の 時間） を （3 と 4 の 時間） に 時間加算する
10 を （5 と 6 の 時間） に 2.0 で 総ナノ秒にする
q とは 7 を 品質作成する
q
q を 品質合計する
（（q の 期限） を （q の 期限） に 時間加算する） の ナノ秒
1 を （0 と 3 の 時間） に 1.0 で （総ナノ秒番地取得する） から 番地経由総ナノ秒にする
"""

EXPECTED = """（a は 255 の 甲1）
（a は 127 で b は 0 の 甲2）
（a は -600 で b は 65535 の 甲4）
（a は 8 で b は 2.5 の 甲8）
（a は 3 で b は 2 で c は 1 の 甲12）
（a は 4611686018427387903 で b は 1.5 の 甲16）
（a は 6 で b は 1 で c は 2 の 甲24）
（x は 2.5 で y は 1.5 の 浮2）
（x は 4 で y は 3 で z は 2 で w は 1 の 浮4）
（秒 は 4 で ナノ秒 は 6 の 時間）
10000000022
（深さ は 7 で 期限 は （秒 は 7 で ナノ秒 は 14 の 時間） で 率 は 0.5 で 印 は 真 で 先 は 番地(0x10) の 品質）
45.5
28
4
"""


@pytest.fixture(scope="module")
def libdir(tmp_path_factory):
    d = tmp_path_factory.mktemp("cstruct")
    cc = shutil.which("cc") or shutil.which("clang")
    (d / "st.c").write_text(C_SOURCE, encoding="utf-8")
    pic = [] if sys.platform == "win32" else ["-fPIC"]
    subprocess.run([cc, "-shared", *pic, "-o", str(d / LIB), str(d / "st.c")], check=True)
    return d


@needs_cc
def test_インタプリタで値で渡して値で返す(libdir):
    assert interpreted(PROGRAM, str(libdir)) == EXPECTED


def _err(source: str, base_dir: str) -> str:
    with pytest.raises(SuruError) as info:
        it = suru.Interpreter()
        it.ctx.base_dir = base_dir
        it.run(source)
    return info.value.message


BAD_CALLS = [
    ("（256 の 甲1） を 一処理する", "外部の関数「一処理する」の「を」の「a」: 「256」は"),
    ("（256 の 甲1） を 一処理する", "「256」は符号なし8に入りません(0 から 255 までの整数です)"),
    ("（-129 と 0 の 甲2） を 二処理する", "「-129」は符号付き8に入りません"),
    ("（1 と -1 の 時間） を （0 と 0 の 時間） に 時間加算する", "「-1」は符号なし32に入りません"),
    ("（1 と 2.5 と 3 の 甲12） を 十二処理する", "「2.5」は符号付き32に入りません"),
]


@needs_cc
@pytest.mark.parametrize("call, want", BAD_CALLS)
def test_入らない値はフィールドの名前を出してエラー(libdir, call, want):
    src = PROGRAM.split("（254 の 甲1）")[0] + call + "\n"
    assert want in _err(src, str(libdir))


def test_型の宣言に書けるのは_C構造体の型():
    src = "点 とは 横 は 数 の 組\n点 を 点処理する は 点\np を 点処理する とは 外部の「f」\n"
    with pytest.raises(SuruError) as info:
        suru.Interpreter().run(src)
    assert "数・小数・整数・真偽・文字列・番地・バイト列・単精度 のどれかの型か、C構造体の型を書いてください" in info.value.message


@pytest.mark.skipif(shutil.which("go") is None, reason="go がありません")
def test_Go版の検査も_C構造体の引数を読む(libdir, tmp_path):
    suruc = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(suruc), "./cmd/suruc"], cwd=ROOT, check=True)
    prog = libdir / "例.suru"
    prog.write_text(PROGRAM, encoding="utf-8")
    r = subprocess.run([str(suruc), "--検査", str(prog)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


needs_clang = pytest.mark.skipif(shutil.which("clang") is None, reason="clang がありません")


@pytest.fixture(scope="module")
def suruc(tmp_path_factory):
    if shutil.which("go") is None:
        pytest.skip("go がありません")
    exe = tmp_path_factory.mktemp("suruc") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return exe


@needs_clang
def test_Python版のコンパイラでも同じ(libdir):
    r = compiled(PROGRAM, str(libdir))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED


@needs_clang
def test_Go版のコンパイラでも同じ(libdir, suruc):
    prog = libdir / "例.suru"
    prog.write_text(PROGRAM, encoding="utf-8")
    exe = libdir / ("例.exe" if sys.platform == "win32" else "例")
    b = subprocess.run([str(suruc), str(prog), "-o", str(exe)], capture_output=True, text=True)
    assert b.returncode == 0, b.stderr
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert r.stdout == EXPECTED, r.stderr
    # 中継の C のソースは Python 版と同じ
    import suru_compile

    py = suru_compile.cshim_source(suru_compile.compile_source(PROGRAM, str(libdir)))
    ll = subprocess.run([str(suruc), "--ll", str(prog), "-o", str(libdir / "例.ll")], capture_output=True, text=True)
    assert ll.returncode == 0, ll.stderr
    go = suru_compile.cshim_source((libdir / "例.ll").read_text(encoding="utf-8"))
    assert py and py == go


@needs_clang
@pytest.mark.parametrize("call, want", BAD_CALLS)
def test_コンパイルしたものも入らない値は同じエラー(libdir, suruc, call, want):
    src = PROGRAM.split("（254 の 甲1）")[0] + call + "\n"
    prog = libdir / "誤.suru"
    prog.write_text(src, encoding="utf-8")
    exe = libdir / ("誤.exe" if sys.platform == "win32" else "誤")
    b = subprocess.run([str(suruc), str(prog), "-o", str(exe)], capture_output=True, text=True)
    assert b.returncode == 0, b.stderr
    r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and want in r.stderr, r.stderr

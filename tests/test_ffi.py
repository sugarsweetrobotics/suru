"""外部の関数(FFI)のテスト: インタプリタ(ctypes)とコンパイルしたバイナリで、C の関数を同じように呼べるか"""

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

C_SOURCE = r"""
#include <stdint.h>
#include <string.h>
int64_t add3(int64_t a, int64_t b, int64_t c) { return a * 100 + b * 10 + c; }
int ilen(const char *s) { return (int)strlen(s); }
const char *greet(const char *s) { static char buf[256]; strcpy(buf, "こんにちは、"); strncat(buf, s, 200); return buf; }
static int64_t counter;
int64_t bump(int64_t n) { counter += n; return counter; }
int is_pos(double x) { return x > 0; }
double half(double x) { return x / 2; }
void *mk(int64_t n) { return (void *)(intptr_t)n; }
int64_t unmk(void *p) { return (int64_t)(intptr_t)p; }
int64_t huge(void) { return INT64_MAX; }
const char *nothing(void) { return 0; }
"""

DECLS = """外部の「./libtest.so」 を 読み込む
数 を 数 で 数 に 三和する は 数
a を b で c に 三和する とは 外部の「add3」
文字列 を 字数計測する は 整数
s を 字数計測する とは 外部の「ilen」
文字列 を 挨拶する は 文字列
s を 挨拶する とは 外部の「greet」
数 を 加算記録する は 数 の 動作
n を 加算記録する とは 外部の「bump」
小数 が 正である は 真偽
x が 正である とは 外部の「is_pos」
小数 を 半分にする は 小数
x を 半分にする とは 外部の「half」
数 を 番地にする は 番地
n を 番地にする とは 外部の「mk」
番地 を 番地解除する は 数
p を 番地解除する とは 外部の「unmk」
"""

PROGRAM = DECLS + """
1 を 2 で 3 に 三和する
「あいう」 を 字数計測する
「世界」 を 挨拶する
-1.5 が 正である
2 が 正である
7 を 半分にする
255 を 番地にする
（255 を 番地にする） を 番地解除する
（3 を 番地にする） = （3 を 番地にする）
未使用 とは 100 を 加算記録する
試す とは 手順
  a とは 5 を 加算記録した 結果
  b とは 10 を 加算記録した 結果
  a + b を 表示する
試す
3 を 加算記録してから 表示する
"""

EXPECTED = "123\n9\nこんにちは、世界\n偽\n真\n3.5\n番地(0xff)\n255\n真\n20\n18\n"

needs_cc = pytest.mark.skipif(shutil.which("cc") is None and shutil.which("clang") is None, reason="C コンパイラがありません")


@pytest.fixture
def libdir(tmp_path):
    cc = shutil.which("cc") or shutil.which("clang")
    (tmp_path / "a.c").write_text(C_SOURCE, encoding="utf-8")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(tmp_path / "libtest.so"), str(tmp_path / "a.c")], check=True)
    return tmp_path


def interpreted(source: str, base_dir: str) -> str:
    out: list[str] = []
    it = suru.Interpreter(out=lambda s: out.append(s + "\n"))
    it.ctx.base_dir = base_dir
    it.run(source, emit=lambda v: out.append(it.format(v) + "\n"))
    return "".join(out)


def compiled(source: str, base_dir: str, check: bool = True) -> subprocess.CompletedProcess:
    ir = suru_compile.compile_source(source, base_dir, check=check)
    ll = pathlib.Path(base_dir) / "prog.ll"
    ll.write_text(ir, encoding="utf-8")
    exe = pathlib.Path(base_dir) / "prog"
    suru_compile.build(str(ll), str(exe))
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)


def err(source: str, base_dir: str = ".") -> str:
    with pytest.raises(SuruError) as info:
        it = suru.Interpreter()
        it.ctx.base_dir = base_dir
        it.run(source)
    return info.value.message


@needs_cc
def test_インタプリタで呼ぶ(libdir):
    suru._FFI_LIBS.clear()
    assert interpreted(PROGRAM, str(libdir)) == EXPECTED


@needs_cc
@pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")
def test_バイナリでも同じ(libdir):
    r = compiled(PROGRAM, str(libdir))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED


def test_libmとlibc():
    src = (ROOT / "examples" / "ffi.suru").read_text(encoding="utf-8")
    assert interpreted(src, str(ROOT / "examples")) == "1\n1024\n5\n6\n"


@needs_cc
def test_実行時のまちがいはインタプリタとバイナリで同じ(libdir):
    cases = [
        DECLS + "1.5 を 2 で 3 に 三和する\n",
        DECLS + "「あ」 を 半分にする\n",
        "外部の「./libtest.so」 を 読み込む\n整数 を 番地にする は 番地\nn を 番地にする とは 外部の「mk」\n5000000000 を 番地にする\n",
        "外部の「./libtest.so」 を 読み込む\n最大値取得する は 数\n最大値取得する とは 外部の「huge」\n最大値取得する\n",
    ]
    for src in cases:
        suru._FFI_LIBS.clear()
        it = suru.Interpreter(out=lambda s: None)
        it.ctx.base_dir = str(libdir)
        with pytest.raises(SuruError) as info:
            it.run(src)
        want = info.value.message
        if suru_compile.find_cc() is not None:
            r = compiled(src, str(libdir), check=False)
            assert r.returncode == 1
            assert want in r.stderr, (want, r.stderr)


@needs_cc
def test_空の文字列が返る(libdir):
    src = "外部の「./libtest.so」 を 読み込む\n空取得する は 文字列\n空取得する とは 外部の「nothing」\n空取得して 文字列化する\n"
    src += "「[」 + （空取得する） + 「]」\n"
    assert interpreted(src, str(libdir)) == "\n[]\n"


def test_型の検査():
    from suru_check import check

    def err(source: str) -> str:
        with pytest.raises(SuruError) as info:
            check(source)
        return info.value.message

    src = "外部の「m」 を 読み込む\n小数 を 余弦にする は 小数\nx を 余弦にする とは 外部の「cos」\n「a」 を 余弦にする\n"
    assert "「余弦にする」の「を」には数が必要ですが、文字列が渡されています" in err(src)
    src = "番地 を 解除する は 数\np を 解除する とは 外部の「unmk」\n1 を 解除する\n"
    assert "「解除する」の「を」には番地が必要ですが、数が渡されています" in err(src)


def test_書き方のまちがい():
    assert "型の宣言が必要です" in err("x を 余弦にする とは 外部の「cos」\n")
    assert "型の宣言が必要です" in err("円周率 は 小数\n円周率 とは 外部の「pi」\n")
    assert "のどれかの型を書いてください" in err("数 の リスト を 合計する は 数\nx を 合計する とは 外部の「sum」\n")
    assert "のどれかの型を書いてください" in err("数 を 待機する は 数 の リスト\nx を 待機する とは 外部の「sum」\n")
    assert "C の関数の名前ではありません" in err("数 を 余弦にする は 数\nx を 余弦にする とは 外部の「余弦」\n")
    assert "実行時が使う名前" in err("数 を 余弦にする は 数\nx を 余弦にする とは 外部の「rt_alloc」\n")
    assert "2回定義されています" in err("数 を 甲関数にする は 数\nx を 甲関数にする とは 外部の「abs」\n"
                                    "数 を 乙関数にする は 数\nx を 乙関数にする とは 外部の「abs」\n")
    assert "のように書いて読み込みます" in err("外部の「m」 を 読み込んで 使う\n")
    assert "のように書いて読み込みます" in err("外部の 「m」\n")
    assert "名前だけで書いてください" in err("数 を 甲する は 数\n先頭 は x で 残り は 他 を 甲する とは 外部の「abs」\n")


def test_見つからない関数():
    src = "数 を 甲する は 数\nx を 甲する とは 外部の「suru_no_such_function_x」\n"
    assert "実行時が使う名前" in err(src)
    src = "外部の「m」 を 読み込む\n数 を 甲する は 数\nx を 甲する とは 外部の「no_such_function_x」\n1 を 甲する\n"
    assert "「no_such_function_x」が「m」に見つかりません" in err(src)


def test_作っただけの動作では呼ばない(libdir):
    if shutil.which("cc") is None and shutil.which("clang") is None:
        pytest.skip("C コンパイラがありません")
    suru._FFI_LIBS.clear()
    src = DECLS + "未実行 とは 7 を 加算記録する\n（未実行） と 1\n3 を 加算記録してから 表示する\n"
    assert interpreted(src, str(libdir)).endswith("3\n")


# --- バイト列・番地とのやりとり・失敗(段階2) ---

MEMORY = """外部の「c」 を 読み込む
「標準」 を 読み込んで 使う
数 を 確保する は 番地 の 動作
n を 確保する とは 外部の「malloc」
番地 を 解放する は 無 の 動作
p を 解放する とは 外部の「free」
バイト列 を 数 で 合計計算する は 数
b を n で 合計計算する とは 外部の「cs_sum」

b とは 「あい」 を バイト列にする
b
b を 数列にする
b を バイト長にする
b を 文字列にする
（65 と 66 と 0 と 255） を バイト列組立する
（「あい」 を バイト列にする） = b
（「」 を バイト列にする） を バイト長にする
16 を 番地にする
（16 を 番地にする） を 番地数値にする
-1 を 番地にする
（-1 を 番地にする） を 番地数値にする
試す とは 手順
  p とは 16 を 確保した 結果
  n とは b を p へ 書込した 結果
  c とは p から n を バイト列取得した 結果
  c を 文字列にして 表示する
  p を 解放した 結果 を 表示する
試す
"""

MEMORY_EXPECTED = ("バイト列（e3 81 82 e3 81 84）\n（227 と 129 と 130 と 227 と 129 と 132）\n6\nあい\n"
                   "バイト列（41 42 00 ff）\n真\n0\n番地(0x10)\n16\n番地(0xffffffffffffffff)\n-1\nあい\n0\n")

SUM_C = r"""
#include <stdint.h>
int64_t cs_sum(const uint8_t *b, int64_t n) { int64_t s = 0; for (int64_t i = 0; i < n; i++) s += b[i]; return s; }
"""

FAILS = [
    "「標準」 を 読み込んで 使う\n（1 と 256） を バイト列組立する\n",
    "「標準」 を 読み込んで 使う\n（「ff」 を バイト列にする） を 文字列にする\n（（255 と 254） を バイト列組立する） を 文字列にする\n",
    "「標準」 を 読み込んで 使う\n1.5 を 番地にする\n",
    "「標準」 を 読み込んで 使う\n（0 を 番地にする） から 4 を バイト列取得する\n",
    "「標準」 を 読み込んで 使う\n（「a」 を バイト列にする） を （0 を 番地にする） へ 書込する\n",
    "「標準」 を 読み込んで 使う\n「だめです」 を 失敗する\n",
    "外部の「c」 を 読み込む\n「標準」 を 読み込んで 使う\n文字列 を 整数 で 開封する は 整数 の 動作\n"
    "道 を 方法 で 開封する とは 外部の「open」\n（「/no/such/file」 を 0 で 開封する） を 「開くの」 で 失敗確認する\n",
]


def test_バイト列と番地():
    assert interpreted(MEMORY.replace("バイト列 を 数 で 合計計算する は 数\nb を n で 合計計算する とは 外部の「cs_sum」\n", ""),
                       str(ROOT)) == MEMORY_EXPECTED


@needs_cc
@pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")
def test_バイト列と番地をバイナリでも(tmp_path):
    src = MEMORY.replace("バイト列 を 数 で 合計計算する は 数\nb を n で 合計計算する とは 外部の「cs_sum」\n", "")
    r = compiled(src, str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout == MEMORY_EXPECTED


@needs_cc
def test_バイト列をCに渡す(tmp_path):
    cc = shutil.which("cc") or shutil.which("clang")
    (tmp_path / "s.c").write_text(SUM_C, encoding="utf-8")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(tmp_path / "libsum.so"), str(tmp_path / "s.c")], check=True)
    src = ("外部の「./libsum.so」 を 読み込む\n「標準」 を 読み込んで 使う\nバイト列 を 数 で 合計計算する は 数\n"
           "b を n で 合計計算する とは 外部の「cs_sum」\n（（1 と 2 と 250） を バイト列組立する） を 3 で 合計計算する\n")
    assert interpreted(src, str(tmp_path)) == "253\n"
    if suru_compile.find_cc() is not None:
        r = compiled(src, str(tmp_path))
        assert r.stdout == "253\n", r.stderr


def test_失敗の文はインタプリタとバイナリで同じ(tmp_path):
    for src in FAILS:
        it = suru.Interpreter(out=lambda s: None)
        it.ctx.base_dir = str(tmp_path)
        with pytest.raises(SuruError) as info:
            it.run(src)
        want = info.value.message
        if suru_compile.find_cc() is not None:
            r = compiled(src, str(tmp_path), check=False)
            assert r.returncode == 1
            assert want in r.stderr, (src, want, r.stderr)
    assert want == "開くのに失敗しました(No such file or directory)"


def test_値と引数に使えない型():
    assert "のどれかの型を書いてください" in err("バイト列 を 甲する は バイト列\nx を 甲する とは 外部の「abs」\n")
    assert "のどれかの型を書いてください" in err("無 を 甲する は 数\nx を 甲する とは 外部の「abs」\n")


@needs_cc
@pytest.mark.skipif(shutil.which("pkg-config") is None, reason="pkg-config がありません")
def test_短い名前はpkg_configのフォルダからも探す(tmp_path, monkeypatch):
    # 普通は探さないフォルダ(Homebrew の /opt/homebrew/lib のような)にあるライブラリ
    cc = shutil.which("cc") or shutil.which("clang")
    lib = tmp_path / "変な場所" / "lib"
    lib.mkdir(parents=True)
    (tmp_path / "s.c").write_text("long long surupc_triple(long long x) { return 3 * x; }\n", encoding="utf-8")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(lib / "libsurupc.so"), str(tmp_path / "s.c")], check=True)
    pc = tmp_path / "pc"
    pc.mkdir()
    (pc / "surupc.pc").write_text(f"libdir={lib}\n\nName: surupc\nDescription: t\nVersion: 1.0\nLibs: -L${{libdir}} -lsurupc\n", encoding="utf-8")
    monkeypatch.setenv("PKG_CONFIG_PATH", str(pc))
    suru._PKGCONFIG_CACHE.clear()
    suru._FFI_LIBS.clear()
    src = "外部の「surupc」 を 読み込む\n数 を 三倍する は 数\nx を 三倍する とは 外部の「surupc_triple」\n14 を 三倍して 表示する\n"
    assert interpreted(src, str(tmp_path)) == "42\n"
    assert suru_compile._pkgconfig_link_flags("surupc") == [f"-L{lib}", f"-Wl,-rpath,{lib}"]
    assert suru_compile._pkgconfig_link_flags("m") == []
    if suru_compile.find_cc() is not None:
        r = compiled(src, str(tmp_path))
        assert r.returncode == 0, r.stderr
        assert r.stdout == "42\n"


SEVEN_C = r"""
#include <stdint.h>
int64_t seven(int64_t a, const char *b, int64_t c, int64_t d, int e, void *f, void *g) {
  return a * 1000000 + (int64_t)b[0] * 1000 + c * 100 + d * 10 + e + (f ? 7000000000 : 0) + (g ? 90000000000 : 0);
}
int64_t sub3(int64_t a, int64_t b, int64_t c) { return a - b - c; }
"""

SEVEN = """外部の「./libseven.so」 を 読み込む
「標準」 を 読み込んで 使う
数 を 文字列 で 数 に 数 から 整数 へ 番地 より 七呼出する は 数
a を b で c に d から e へ f より 七呼出する とは 外部の「seven」（a と b と c と d と e と f と 0）
数 を 数 で 逆引算する は 数
a を b で 逆引算する とは 外部の「sub3」（b と a と -1）
1 を 「A」 で 2 に 3 から 4 へ （0 を 番地にする） より 七呼出する
1 を 「A」 で 2 に 3 から 4 へ （5 を 番地にする） より 七呼出する
10 を 3 で 逆引算する
"""


@pytest.fixture
def sevendir(tmp_path):
    cc = shutil.which("cc") or shutil.which("clang")
    (tmp_path / "s.c").write_text(SEVEN_C, encoding="utf-8")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(tmp_path / "libseven.so"), str(tmp_path / "s.c")], check=True)
    return tmp_path


@needs_cc
def test_C_に渡す引数を並べて書く(sevendir):
    # 助詞は6つなので、7つ以上の引数や定数の引数(NULL など)は「（a と 0 と b）」で並べる
    suru._FFI_LIBS.clear()
    want = "1065234\n7001065234\n-6\n"
    assert interpreted(SEVEN, str(sevendir)) == want
    if suru_compile.find_cc() is not None:
        r = compiled(SEVEN, str(sevendir))
        assert r.returncode == 0, r.stderr
        assert r.stdout == want


def test_C_に渡す引数の並びのまちがい():
    head = "数 を 数 で 引算する は 数\n"
    assert "「c」は「引算する」の引数ではありません" in err(head + "a を b で 引算する とは 外部の「sub3」（a と c）\n")
    assert "引数「b」を C に渡していません" in err(head + "a を b で 引算する とは 外部の「sub3」（a と 0）\n")
    assert "引数の名前か整数を「と」でつないで" in err(head + "a を b で 引算する とは 外部の「sub3」（a と 「x」 と b）\n")
    assert "引数の名前か整数を「と」でつないで" in err(head + "a を b で 引算する とは 外部の「sub3」（a と 1.5 と b）\n")
    assert "引数の名前か整数を「と」でつないで" in err(head + "a を b で 引算する とは 外部の「sub3」（a b）\n")

"""C から する の関数を呼び戻す(「呼び戻し番地作成する」)と、ほかのスレッドから通路に送る(「通路送り番地作成する」)"""

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
from test_c_memory import compiled, interpreted  # noqa: E402

C_SOURCE = r"""
#include <pthread.h>
#include <stdint.h>
typedef void (*ev_cb)(const void *user, int64_t n, double x, const char *s);
static ev_cb g_cb; static const void *g_user;
static void *run(void *arg) { for (int i = 1; i <= 3; i++) g_cb(g_user, i, i * 0.5, "やあ"); return 0; }
void start_events(ev_cb cb, const void *user) { g_cb = cb; g_user = user; pthread_t t; pthread_create(&t, 0, run, 0); pthread_join(t, 0); }
double apply_twice(double (*f)(double), double x) { return f(f(x)); }
float apply_f(float (*f)(float, int32_t), float x) { return f(x, 2); }
int64_t fold3(int64_t (*f)(int64_t, int64_t, int32_t)) { return f(f(1, 2, 0), 3, 1); }
static void *call7(void *f) { ((void (*)(int64_t))f)(7); return 0; }
void call_from_thread(void (*f)(int64_t)) { pthread_t t; pthread_create(&t, 0, call7, (void *)f); pthread_join(t, 0); }
"""

HEAD = """外部の「./libcbt.so」 を 読み込む
「標準」 を 読み込んで 使う
「スレッド」 を 読み込んで 使う
番地 を 数 で 数 に 番地 から 並べ替えする は 無 の 動作
p を n で k に f から 並べ替えする とは 外部の「qsort」（p と n と k と f）
数 を 確保する は 番地 の 動作
n を 確保する とは 外部の「calloc」（n と 1）
番地 を 番地 で 開始する は 無 の 動作
f を u で 開始する とは 外部の「start_events」（f と u）
番地 を 小数 で 二回適用する は 小数 の 動作
f を x で 二回適用する とは 外部の「apply_twice」（f と x）
番地 を 単精度 で 単精度適用する は 単精度 の 動作
f を x で 単精度適用する とは 外部の「apply_f」（f と x）
番地 を 三つ畳み込みする は 数 の 動作
f を 三つ畳み込みする とは 外部の「fold3」
番地 を 別スレッド呼出する は 無 の 動作
f を 別スレッド呼出する とは 外部の「call_from_thread」
番地 を 番地 で 比較する は 整数 の 動作
a を b で 比較する とは 手順
  x とは a から 0 で 符号付き64読取した 結果
  y とは b から 0 で 符号付き64読取した 結果
  （もし x < y ならば -1 そうでなければ もし x > y ならば 1 そうでなければ 0） を 結果にする
新着 とは 相手 と 数 と 値 と 文 の 組
"""

PROGRAM = HEAD + """試す とは 手順
  p とは 40 を 確保した 結果
  7 を p へ 0 で 符号付き64書込する
  3 を p へ 8 で 符号付き64書込する
  9 を p へ 16 で 符号付き64書込する
  1 を p へ 24 で 符号付き64書込する
  5 を p へ 32 で 符号付き64書込する
  f とは 比較すること を 「番地 と 番地」 で 「整数」 に 呼び戻し番地作成した 結果
  p を 5 で 8 に f から 並べ替えする
  f を 呼び戻し解放する
  （p から 0 で 符号付き64読取した 結果） を 表示する
  （p から 8 で 符号付き64読取した 結果） を 表示する
  （p から 32 で 符号付き64読取した 結果） を 表示する
  c とは プロセス間通路作成した 結果
  e とは （0 と 0 と 0.0 と 「」 の 新着） を c へ 「番地 と 数 と 小数 と 文字列」 で 通路送り番地作成した 結果
  e を （42 を 番地にする） で 開始する
  e を 呼び戻し解放する
  （c から 通路受信した 結果） を 表示する
  （c から 通路受信した 結果） を 表示する
  （c から 通路受信した 結果） を 表示する
  g とは （x を 受け取って x / 2 を 返すこと） を 「小数」 で 「小数」 に 呼び戻し番地作成した 結果
  （g を 10 で 二回適用した 結果） を 表示する
  h とは （x を n で 受け取って x * n を 返すこと） を 「単精度 と 整数」 で 「単精度」 に 呼び戻し番地作成した 結果
  （h を 1.25 で 単精度適用した 結果） を 表示する
  k とは （a を b で c に 受け取って （もし c = 1 ならば a * 10 + b そうでなければ a + b） を 返すこと） を 「数 と 数 と 整数」 で 「数」 に 呼び戻し番地作成した 結果
  （k を 三つ畳み込みした 結果） を 表示する
試す
"""

EXPECTED = """1
3
9
（相手 は 42 で 数 は 1 で 値 は 0.5 で 文 は 「やあ」 の 新着）
（相手 は 42 で 数 は 2 で 値 は 1 で 文 は 「やあ」 の 新着）
（相手 は 42 で 数 は 3 で 値 は 1.5 で 文 は 「やあ」 の 新着）
2.5
2.5
33
"""


@pytest.fixture
def libdir(tmp_path):
    cc = shutil.which("cc") or shutil.which("clang")
    if cc is None:
        pytest.skip("C コンパイラがありません")
    (tmp_path / "cb.c").write_text(C_SOURCE, encoding="utf-8")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(tmp_path / "libcbt.so"), str(tmp_path / "cb.c"), "-lpthread"], check=True)
    suru._FFI_LIBS.clear()
    return tmp_path


def test_インタプリタ(libdir):
    assert interpreted(PROGRAM, str(libdir)) == EXPECTED


@pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")
def test_バイナリでも同じ(libdir):
    r = compiled(PROGRAM, str(libdir))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED


ERRORS = [
    ("（x を 受け取って x を 返すこと） を 「番地 と 何か」 で 「数」 に 呼び戻し番地作成する",
     "「番地 と 何か」は「呼び戻し番地作成する」の引数の型の並びではありません"),
    ("（x を 受け取って x を 返すこと） を 「数」 で 「文字列」 に 呼び戻し番地作成する", "「文字列」は呼び戻しの値の型ではありません"),
    ("（x を 受け取って x を 返すこと） を 「数 と 数 と 数 と 数 と 数 と 数 と 数」 で 「数」 に 呼び戻し番地作成する",
     "引数の型が多すぎます"),
    ("（0 を 番地にする） を 呼び戻し解放する", "は呼び戻しの番地ではありません"),
    ("（0 と 0 と 0 と 「」 の 新着） を （プロセス間通路作成した 結果） へ 「番地 と 数」 で 通路送り番地作成する",
     "「通路送り番地作成する」の「を」は、フィールドが 2 個の組でなければなりません"),
    ("（0 と 0 と 0 と 0 の 新着） を （プロセス間通路作成した 結果） へ 「番地 と 数 と 小数 と 文字列」 で 通路送り番地作成する",
     "見本の4番目のフィールド「0」は文字列でなければなりません"),
    ("（0 と 0 と 0 と 「」 の 新着） を （0 で 通路作成した 結果） へ 「番地 と 数 と 小数 と 文字列」 で 通路送り番地作成する",
     "プロセス間通路作成する で作って"),
    # 呼び戻しの中のエラーは、外部の関数から戻ってからそのエラーになる
    ("（（x を 受け取って 「だめ」 を 失敗する を 返すこと） を 「小数」 で 「小数」 に 呼び戻し番地作成した 結果） を 1 で 二回適用する",
     "だめ"),
    ("（（x を 受け取って 「a」 を 返すこと） を 「小数」 で 「小数」 に 呼び戻し番地作成した 結果） を 1 で 二回適用する",
     "外部の関数「呼び戻し」の「を」には数が必要です(「a」が渡されました)"),
    # 同じスレッドで呼び戻す番地を、ほかのスレッドから呼ぶと止まる
    ("（（x を 受け取って x を 返すこと） を 「数」 で 「無」 に 呼び戻し番地作成した 結果） を 別スレッド呼出する",
     "呼び戻しの番地が、外部の関数を呼んでいる途中ではないところ(ほかのスレッドなど)から呼ばれました"),
]


@pytest.mark.parametrize("expr,want", ERRORS, ids=[str(i) for i in range(len(ERRORS))])
def test_まちがいはインタプリタとバイナリで同じ(libdir, expr, want):
    src = HEAD + "試す とは 手順\n  " + expr + "\n試す\n"
    if "別スレッド" in expr:  # プロセスごと止まるので、別のプロセスで動かす
        (libdir / "p.suru").write_text(src, encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(libdir / "p.suru")], capture_output=True, text=True, timeout=60)
        assert r.returncode == 1 and want in r.stderr, r.stderr
    else:
        with pytest.raises(SuruError) as info:
            interpreted(src, str(libdir))
        assert want in info.value.message
    if suru_compile.find_cc() is not None:
        r = compiled(src, str(libdir), check=False)
        assert r.returncode == 1
        assert want in r.stderr, r.stderr

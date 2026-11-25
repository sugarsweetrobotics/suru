"""C の構造体の形(「C形作成する」): インタプリタとコンパイルしたバイナリで同じか、C と同じ並びか"""

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

needs_clang = pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")

HEAD = """「標準」 を 読み込んで 使う
数 を 確保する は 番地 の 動作
n を 確保する とは 外部の「calloc」（n と 1）
時間 とは 秒 と ナノ秒 の 組
時間形 とは （0 と 0 の 時間） を （「符号付き32」 と 「符号なし32」） で C形作成する
品質 とは 履歴 と 深さ と 期限 と 寿命 と 回避 と 印 の 組
品質形 とは （0 と 0 と （0 と 0 の 時間） と 空 と 偽 と 空 の 品質） を （「符号付き32」 と 「符号なし64」 と 「構造体」 と 「構造体[2]」 と 「真偽」 と 「符号なし8[3]」） で C形作成して 3 で 時間形 に 入れ子設定して 4 で 時間形 に 入れ子設定する
x とは （1 と 2 と （3 と 4 の 時間） と （（5 と 6 の 時間） と （7 と 8 の 時間）） と 真 と （9 と 10 と 11） の 品質）
"""

PROGRAM = HEAD + """品質形 を C大きさにする
品質形 を C揃えにする
時間形 を C大きさにする
（1 と 2 と 3 と 4 と 5 と 6） を （k を 受け取って 品質形 を k で C位置にする を 返すこと） で 写像する
品質形
（x を 品質形 で C直列化する） を 数列にする
（（x を 品質形 で C直列化する） を 品質形 で C復元する） = x
試す とは 手順
  p とは 64 を 確保した 結果
  x を p へ 8 で 品質形 に 構造体書込してから 表示する
  （p から 8 で 品質形 を 構造体読取した 結果） を 表示する
  （p から 24 で 符号付き32読取した 結果） を 表示する
  （p から 49 で 真偽読取した 結果） を 表示する
試す
"""

EXPECTED = """48
8
8
（0 と 8 と 16 と 24 と 40 と 41）
<C形 品質>
（1 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 2 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 4 と 0 と 0 と 0 と 5 と 0 と 0 と 0 と 6 と 0 と 0 と 0 と 7 と 0 と 0 と 0 と 8 と 0 と 0 と 0 と 1 と 9 と 10 と 11 と 0 と 0 と 0 と 0）
真
48
（履歴 は 1 で 深さ は 2 で 期限 は （秒 は 3 で ナノ秒 は 4 の 時間） で 寿命 は （（秒 は 5 で ナノ秒 は 6 の 時間） と （秒 は 7 で ナノ秒 は 8 の 時間）） で 回避 は 真 で 印 は （9 と 10 と 11） の 品質）
3
真
"""


def test_インタプリタ(tmp_path):
    assert interpreted(PROGRAM, str(tmp_path)) == EXPECTED


@needs_clang
def test_バイナリでも同じ(tmp_path):
    r = compiled(PROGRAM, str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED


C_SOURCE = r"""
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
typedef struct { int32_t sec; uint32_t nsec; } T;
typedef struct { int32_t h; uint64_t d; T a; T b[2]; bool c; uint8_t m[3]; } Q;
typedef struct { uint8_t a; double b; uint16_t c; float d; void *e; int8_t f[5]; } R;
int64_t q_size(void) { return sizeof(Q); }
int64_t r_size(void) { return sizeof(R); }
int64_t r_off(int64_t k) {
    size_t o[] = {offsetof(R, a), offsetof(R, b), offsetof(R, c), offsetof(R, d), offsetof(R, e), offsetof(R, f)};
    return (int64_t)o[k - 1];
}
int64_t q_sum(Q *q) { return q->h + q->d + q->a.sec + q->a.nsec + q->b[1].nsec + q->c + q->m[2]; }
void q_fill(Q *q) { q->h = -7; q->d = 1000; q->a.sec = 1; q->a.nsec = 2; q->b[0].sec = 3; q->b[0].nsec = 4; q->b[1].sec = 5; q->b[1].nsec = 6; q->c = true; q->m[0] = 1; q->m[1] = 2; q->m[2] = 3; }
"""

C_PROGRAM = HEAD + """外部の「./libst.so」 を 読み込む
大きさ取得する は 数
大きさ取得する とは 外部の「q_size」
番地 を 合計する は 数 の 動作
p を 合計する とは 外部の「q_sum」
番地 を 埋めする は 無 の 動作
p を 埋めする とは 外部の「q_fill」
例組 とは 一番 と 二番 と 三番 と 四番 と 五番 と 六番 の 組
例形 とは （0 と 0 と 0 と 0 と （0 を 番地にする） と 空 の 例組） を （「符号なし8」 と 「小数」 と 「符号なし16」 と 「単精度」 と 「番地」 と 「符号付き8[5]」） で C形作成する
例大きさ取得する は 数
例大きさ取得する とは 外部の「r_size」
数 を 例位置にする は 数
k を 例位置にする とは 外部の「r_off」
（品質形 を C大きさにする） = （大きさ取得する）
（例形 を C大きさにする） = （例大きさ取得する）
（1 と 2 と 3 と 4 と 5 と 6） を （k を 受け取って （例形 を k で C位置にする） = （k を 例位置にする） を 返すこと） で 写像する
試す とは 手順
  p とは 64 を 確保した 結果
  x を p へ 0 で 品質形 に 構造体書込する
  p を 合計してから 表示する
  q とは 64 を 確保した 結果
  q を 埋めする
  （q から 0 で 品質形 を 構造体読取した 結果） を 表示する
試す
"""

C_EXPECTED = ("真\n真\n（真 と 真 と 真 と 真 と 真 と 真）\n" + str(1 + 2 + 3 + 4 + 8 + 1 + 11) + "\n"
              "（履歴 は -7 で 深さ は 1000 で 期限 は （秒 は 1 で ナノ秒 は 2 の 時間） で 寿命 は （（秒 は 3 で ナノ秒 は 4 の 時間） と "
              "（秒 は 5 で ナノ秒 は 6 の 時間）） で 回避 は 真 で 印 は （1 と 2 と 3） の 品質）\n")


@pytest.fixture
def libdir(tmp_path):
    cc = shutil.which("cc") or shutil.which("clang")
    if cc is None:
        pytest.skip("C コンパイラがありません")
    (tmp_path / "st.c").write_text(C_SOURCE, encoding="utf-8")
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(tmp_path / "libst.so"), str(tmp_path / "st.c")], check=True)
    return tmp_path


def test_Cの構造体と同じ並び_インタプリタ(libdir):
    suru._FFI_LIBS.clear()
    assert interpreted(C_PROGRAM, str(libdir)) == C_EXPECTED


@needs_clang
def test_Cの構造体と同じ並び_バイナリ(libdir):
    r = compiled(C_PROGRAM, str(libdir))
    assert r.returncode == 0, r.stderr
    assert r.stdout == C_EXPECTED


ERRORS = [
    ("（0 と 0 の 時間） を （「符号付き32」 と 「int」） で C形作成する", "「int」はC形の欄の型ではありません"),
    ("（0 と 0 の 時間） を （「符号付き32」 と 「小数」 と 「小数」） で C形作成する", "C形の欄の数(3)が、見本のフィールドの数(2)と違います"),
    ("（0 と 「a」 の 時間） を （「符号付き32」 と 「符号付き32」） で C形作成する",
     "C形の見本の2番目のフィールド「a」は数でなければなりません(欄は「符号付き32」)"),
    ("（0 と 0 の 時間） を （「符号付き32」 と 「符号なし8[0]」） で C形作成する", "配列の大きさは 1 から 1048576 までの整数で書きます"),
    ("（0 と 0 の 時間） を （「符号付き32」 と 「符号なし8[16]」） で C形作成する",
     "C形の見本の2番目のフィールド「0」はリストでなければなりません(欄は「符号なし8[16]」)"),
    ("（0 と （0 と 0 の 時間） の 時間） を （「符号付き32」 と 「構造体」） で C形作成して C大きさにする",
     "中の形が決まっていない「構造体」の欄があります"),
    ("時間形 を 1 で 時間形 に 入れ子設定する", "C形の1番目の欄は「符号付き32」なので、入れ子にできません"),
    ("品質形 を 7 で 時間形 に 入れ子設定する", "「入れ子設定する」の「で」は 1 から 6 までの欄の番号です(「7」が渡されました)"),
    ("（1 と 2 と （3 と 4 の 時間） と （（5 と 6 の 時間）） と 真 と （9 と 10 と 11） の 品質） を 品質形 で C直列化する",
     "は2個の要素のリストではありません(4番目のフィールド「寿命」)"),
    ("（1 と 2 と （3 と 4 の 時間） と （（5 と 6 の 時間） と （7 と 8 の 時間）） と 真 と （9 と 10 と 300） の 品質） を 品質形 で C直列化する",
     "「300」は符号なし8に入りません(0 から 255 までの整数です)"),
    ("（空 を バイト列組立する） を 品質形 で C復元する", "バイト列の長さがC形と違います(C形は 48 バイト、バイト列は 0 バイト)"),
    ("（0 を 番地にする） から 0 で 品質形 を 構造体読取する", "番地(0x0)からは読み取れません"),
]


@pytest.mark.parametrize("expr,want", ERRORS, ids=[str(i) for i in range(len(ERRORS))])
def test_まちがいはインタプリタとバイナリで同じ(tmp_path, expr, want):
    src = HEAD + expr + "\n"
    with pytest.raises(SuruError) as info:
        interpreted(src, str(tmp_path))
    assert want in info.value.message
    if suru_compile.find_cc() is not None:
        r = compiled(src, str(tmp_path), check=False)
        assert r.returncode == 1
        assert want in r.stderr, r.stderr


def test_型の検査():
    from suru_check import check

    def err(source: str) -> str:
        with pytest.raises(SuruError) as info:
            check(source)
        return info.value.message

    assert "時間" in err(HEAD + "（1 と 2 の 時間） を 品質形 で C直列化する\n")
    assert "数" in err(HEAD + "（品質形 を C直列化する） を 時間形 で C復元して 品質形 で C直列化する\n")
    # 型の宣言に C形 を書ける
    check(HEAD + "時間 の C形 を 大きさ取得する は 数\nf を 大きさ取得する とは f を C大きさにする\n時間形 を 大きさ取得する\n")
    assert "前には型を1つ書いてください" in err("C形 を 甲する は 数\nx を 甲する とは 1\n")

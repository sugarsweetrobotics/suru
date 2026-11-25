"""C のメモリを型を決めて読み書きする(「符号付き32読取する」など): インタプリタとコンパイルしたバイナリで同じか"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_compile  # noqa: E402
from suru import SuruError  # noqa: E402

needs_clang = pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")

HEAD = """「標準」 を 読み込んで 使う
数 を 確保する は 番地 の 動作
n を 確保する とは 外部の「calloc」（n と 1）
番地 を 解放する は 無 の 動作
p を 解放する とは 外部の「free」
"""

PROGRAM = HEAD + """試す とは 手順
  p とは 64 を 確保した 結果
  -5 を p へ 0 で 符号付き32書込する
  300 を p へ 4 で 符号なし16書込する
  -2 を p へ 6 で 符号付き8書込する
  1.5 を p へ 8 で 単精度書込する
  2.25 を p へ 16 で 小数書込する
  （p から 0 で 符号付き32読取した 結果） を 表示する
  （p から 0 で 符号なし32読取した 結果） を 表示する
  （p から 4 で 符号なし16読取した 結果） を 表示する
  （p から 4 で 符号なし8読取した 結果） を 表示する
  （p から 6 で 符号付き8読取した 結果） を 表示する
  （p から 6 で 符号なし8読取した 結果） を 表示する
  （p から 8 で 単精度読取した 結果） を 表示する
  （p から 16 で 小数読取した 結果） を 表示する
  4611686018427387903 を p へ 24 で 符号付き64書込する
  （p から 24 で 符号付き64読取した 結果） を 表示する
  -32768 を p へ 32 で 符号付き16書込する
  （p から 32 で 符号付き16読取した 結果） を 表示する
  4294967295 を p へ 32 で 符号なし32書込する
  （p から 32 で 符号なし32読取した 結果） を 表示する
  （p から 32 で 符号付き32読取した 結果） を 表示する
  p を p へ 40 で 番地書込する
  （（p から 40 で 番地読取した 結果） = p） を 表示する
  （（（p を 40 で 番地加算する） から -40 で 符号付き32読取した 結果）） を 表示する
  真 を p へ 48 で 真偽書込する
  （p から 48 で 真偽読取した 結果） を 表示する
  （p から 49 で 真偽読取した 結果） を 表示する
  n とは 「あいう」 を p へ 50 で C文字列書込した 結果
  n を 表示する
  （p から 50 で C文字列読取した 結果） を 表示する
  （（p を 53 で 番地加算する） から 0 で C文字列読取した 結果） を 表示する
  （p から 63 で C文字列読取した 結果） を 文字列化して 表示する
  （p を 0 で 番地加算する） = p を 表示する
  p を 解放する
試す
"""

EXPECTED = ("-5\n4294967291\n300\n44\n-2\n254\n1.5\n2.25\n4611686018427387903\n-32768\n4294967295\n-1\n"
            "真\n-5\n真\n偽\n10\nあいう\nいう\n\n真\n")


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


def test_インタプリタで読み書きする(tmp_path):
    assert interpreted(PROGRAM, str(tmp_path)) == EXPECTED


@needs_clang
def test_バイナリでも同じ(tmp_path):
    r = compiled(PROGRAM, str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED


ERRORS = [
    ("256 を p へ 0 で 符号なし8書込する", "「256」は符号なし8に入りません(0 から 255 までの整数です)"),
    ("-1 を p へ 0 で 符号なし32書込する", "「-1」は符号なし32に入りません(0 から 4294967295 までの整数です)"),
    ("128 を p へ 0 で 符号付き8書込する", "「128」は符号付き8に入りません(-128 から 127 までの整数です)"),
    ("1.5 を p へ 0 で 符号付き32書込する", "「1.5」は符号付き32に入りません"),
    ("1 を p へ 0.5 で 符号付き32書込する", "「符号付き32書込する」の「で」は位置(整数のバイト数)でなければなりません(「0.5」が渡されました)"),
    ("p から 0.5 で 小数読取する", "「小数読取する」の「で」は位置(整数のバイト数)でなければなりません"),
    ("（0 を 番地にする） から 0 で 符号付き32読取する", "番地(0x0)からは読み取れません"),
    ("1 を （0 を 番地にする） へ 0 で 符号付き32書込する", "番地(0x0)へは書き込めません"),
    ("-1 を p へ 0 で 符号付き64書込する\n  p から 0 で 符号なし64読取する", "符号なし64の値 18446744073709551615 が大きすぎます"),
    ("（「a」 + （0 を 文字にする）） を p へ 0 で C文字列書込する", "途中に文字コード 0 を含まない文字列でなければなりません"),
]


def _error_program(stmt: str) -> str:
    return HEAD + f"試す とは 手順\n  p とは 16 を 確保した 結果\n  {stmt}\n試す\n"


@pytest.mark.parametrize("stmt,want", ERRORS, ids=[str(i) for i in range(len(ERRORS))])
def test_まちがいはインタプリタとバイナリで同じ(tmp_path, stmt, want):
    src = _error_program(stmt)
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

    assert "「符号付き32書込する」の「を」には数が必要ですが、文字列が渡されています" in err(
        _error_program("「a」 を p へ 0 で 符号付き32書込する"))
    assert "「C文字列読取する」の「から」には番地が必要ですが、数が渡されています" in err(
        _error_program("1 から 0 で C文字列読取する"))
    assert "「番地加算する」の「で」には数が必要ですが、文字列が渡されています" in err(
        _error_program("p を 「a」 で 番地加算する"))

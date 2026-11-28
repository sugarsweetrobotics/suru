"""C構造体の宣言(#241 段階1): 「時間 とは 秒 は 符号付き64 で ナノ秒 は 符号付き64 の C構造体」"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import Interpreter, SuruError  # noqa: E402
from suru_check import check  # noqa: E402

DECL = (
    "時間 とは 秒 は 符号付き64 で ナノ秒 は 符号なし32 の C構造体\n"
    "品質 とは 深さ は 符号なし64 で 期限 は 時間 で 率 は 単精度 で 印 は 真偽 で 先 は 番地 の C構造体\n"
)
USE = DECL + (
    "「標準」 を 読み込んで 使う\n"
    "時間 を 秒取得する は 数\n"
    "t を 秒取得する とは t の 秒\n"
    "q とは （5 と （1 と 2 の 時間） と 0.5 と 真 と （0 を 番地にする） の 品質）\n"
    "（q の 期限） を 秒取得する\n"
    "q の 率 + 1\n"
    "（深さ は 7 で 期限 は （秒 は 3 で ナノ秒 は 4 の 時間） で 率 は 0.25 で 印 は 偽 で 先 は （0 を 番地にする） の 品質） の 深さ\n"
)


def _run(src: str) -> list[str]:
    check(src)
    return Interpreter().run_text(src)


def _err(src: str) -> str:
    with pytest.raises(SuruError) as info:
        check(src)
        Interpreter().run_text(src)
    return str(info.value)


def test_C構造体はふつうの組として使える():
    assert _run(USE) == ["1", "1.5", "7"]


def test_かっこでフィールドの型を書ける():
    """「秒 （符号付き64） と ナノ秒 （符号なし32） の C構造体」(#242 の書き方)"""
    src = "時間 とは 秒 （符号付き64） と ナノ秒 （符号なし32） の C構造体\n品質 とは 深さ （符号なし64） と 期限 （時間） の C構造体\n（5 と （3 と 4 の 時間） の 品質） の 期限 の ナノ秒\n"
    assert _run(src) == ["4"]
    assert "フィールド「秒」の型「数」は C の型ではありません" in _err("時間 とは 秒 （数） の C構造体\n")


def test_句読点の書き方でも書ける():
    assert _run("時間とは、秒は符号付き64でナノ秒は符号なし32のC構造体。\n（1と2の時間）の秒。\n") == ["1"]


def test_フィールドの値の型は検査する():
    assert "「時間」の「秒」は数ですが、文字列が渡されています" in _err(DECL + "（「a」 と 2 の 時間）\n")
    assert "「+」の両側の型が違います(数 と 文字列)" in _err(DECL + "（1 と 2 の 時間） の 秒 + 「a」\n")


@pytest.mark.parametrize("src, want", [
    ("時間 とは 秒 は 数 の C構造体\n", "C構造体「時間」のフィールド「秒」の型「数」は C の型ではありません"),
    ("時間 とは 秒 は 符号付き64 で 名 は 文字列 の C構造体\n", "フィールド「名」の型「文字列」は C の型ではありません"),
    ("時間 とは 秒 は 数 の リスト の C構造体\n", "フィールド「秒」の型は C の型ではありません"),
    ("時間 とは 秒 と 分 の C構造体\n", "C構造体のフィールドには C の型を書いてください"),
    ("時間 とは 秒 は 符号付き64 の 甲 か 分 は 符号付き64 の C構造体\n", "「C構造体」は形が1つのときだけ使えます"),
    ("時間 とは 秒 は 時間 の C構造体\n", "C構造体「時間」が自分自身をフィールドに持っています"),
    ("甲 とは 中 は 乙 の C構造体\n乙 とは 中 は 甲 の C構造体\n", "が自分自身をフィールドに持っています"),
    ("点 とは 横 は 数 の 組\n時間 とは 秒 は 点 の C構造体\n", "フィールド「秒」の型「点」は C の型ではありません"),
])
def test_書き方の誤り(src, want):
    assert want in _err(src)


def test_読み込んだファイルの_C構造体を入れ子にできる(tmp_path):
    (tmp_path / "部品.suru").write_text("時間 とは 秒 は 符号付き64 で ナノ秒 は 符号なし32 の C構造体\n", encoding="utf-8")
    main = tmp_path / "本体.suru"
    main.write_text("「部品」 を 読み込む\n期限 とは 間 は 部品内の時間 の C構造体\n"
                    "（（1 と 2 の 部品内の時間） の 期限） の 間 の 秒 を 表示する\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--インタプリタ", str(main)], capture_output=True, text=True)
    assert r.stdout == "1\n", r.stderr


@pytest.mark.skipif(shutil.which("go") is None, reason="go がありません")
def test_Go版も同じ(tmp_path):
    suruc = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(suruc), "./cmd/suruc"], cwd=ROOT, check=True)
    prog = tmp_path / "例.suru"
    prog.write_text(USE, encoding="utf-8")
    r = subprocess.run([str(suruc), "--検査", str(prog)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for src, want in [("時間 とは 秒 は 数 の C構造体\n", "C構造体「時間」のフィールド「秒」の型「数」は C の型ではありません"),
                      ("時間 とは 秒 と 分 の C構造体\n", "C構造体のフィールドには C の型を書いてください"),
                      ("時間 とは 秒 は 時間 の C構造体\n", "が自分自身をフィールドに持っています")]:
        prog.write_text(src, encoding="utf-8")
        r = subprocess.run([str(suruc), "--検査", str(prog)], capture_output=True, text=True)
        assert want in r.stderr

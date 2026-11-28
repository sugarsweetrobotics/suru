"""要素が1つのリスト「X だけ」(#250): 「X を 空 に 挿入する」の短い書き方"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import suru_compile  # noqa: E402
from suru import Interpreter, SuruError  # noqa: E402
from suru_check import check  # noqa: E402

DAKE = (
    "点 とは 番 は 数 で 誤群 は 数 の リスト の 組\n"
    "（404 だけ） を 表示する\n"
    "xs とは 3 だけ\n"
    "（xs + （4 だけ）） を 表示する\n"
    "（（「a」 だけ） の 長さ） を 表示する\n"
    "p とは 番 は 1 で 誤群 は 404 だけ の 点\n"
    "（p の 誤群） を 表示する\n"
    "（（「花」 だけ） = （「花」 を 空 に 挿入する）） を 表示する\n"
    "5 だけ を 表示する\n"
)
OUT = ["（404）", "（3 と 4）", "1", "（404）", "真", "（5）"]


def test_だけは要素が1つのリスト():
    check(DAKE)
    out: list[str] = []
    Interpreter(out=out.append).run_text(DAKE)
    assert out == OUT


@pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")
def test_だけはコンパイルしても同じ(tmp_path):
    from test_compile import same
    assert same(DAKE, tmp_path).splitlines() == OUT


def test_だけは値1つの後に書く():
    with pytest.raises(SuruError) as info:
        check("（1 と 2 だけ） を 表示する\n")
    assert "「だけ」は値1つの後に書きます" in str(info.value)

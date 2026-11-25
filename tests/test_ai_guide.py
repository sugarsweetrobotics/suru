"""docs/AIの手引き.md のコード例のテスト。```suru の例は型の検査が通り、```suru-誤り の例はエラーになるか"""

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
from suru_check import check  # noqa: E402

GUIDE = ROOT / "docs" / "AIの手引き.md"


def blocks(lang: str) -> list[str]:
    text = GUIDE.read_text(encoding="utf-8")
    return re.findall(rf"^```{re.escape(lang)}\n(.*?)^```$", text, re.M | re.S)


GOOD = blocks("suru")
BAD = blocks("suru-誤り")


def test_例がある():
    assert len(GOOD) >= 5 and len(BAD) >= 3


@pytest.mark.parametrize("source", GOOD, ids=[f"例{k + 1}" for k in range(len(GOOD))])
def test_例は型の検査が通る(source, tmp_path):
    check(source, str(tmp_path), str(tmp_path / "例.suru"))


@pytest.mark.parametrize("source", BAD, ids=[f"誤り{k + 1}" for k in range(len(BAD))])
def test_誤りの例はエラーになる(source, tmp_path):
    with pytest.raises(Exception) as e:
        check(source, str(tmp_path), str(tmp_path / "誤り.suru"))
    assert type(e.value).__name__ == "SuruError"
    assert isinstance(e.value, Exception) and suru  # suru を読み込んでおく(suru_check と同じモジュール)

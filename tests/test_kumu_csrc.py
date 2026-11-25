"""kumu の「Cソース」をインタプリタでも使う: プロジェクトと依存の C のソースを共有ライブラリにして、外部の関数を探す"""

import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
from suru import SuruError  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("clang") is None and shutil.which("cc") is None, reason="C コンパイラがありません")


def make_project(tmp_path: pathlib.Path) -> pathlib.Path:
    files = {
        "部品/組.suru": "名前 とは 「部品」\nCソース とは 「c/部品.c」\nC引数 とは 「-DSCALE=${SURU_TEST_SCALE}」\n",
        "部品/c/部品.c": '#include "部品.h"\nlong long buhin_scale(long long x) { return x * SCALE + OFFSET; }\n',
        "部品/c/部品.h": "#define OFFSET 1\n",
        "部品/部品.suru": "数 を 拡大する は 数\nx を 拡大する とは 外部の「buhin_scale」\n",
        "本/組.suru": "名前 とは 「本」\n依存 とは 「../部品」\nCソース とは 「包み.c」\n",
        "本/組.lock": "# kumu\n部品\t../部品\t-\t-\t-\n",
        "本/包み.c": "long long hon_twice(long long x) { return 2 * x; }\n",
    }
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path / "本"


PROGRAM = "「部品」 を 読み込む\n数 を 二倍する は 数\nx を 二倍する とは 外部の「hon_twice」\n（5 を 部品内の拡大する） を 二倍する\n"


def run(source: str, base_dir: pathlib.Path) -> list:
    suru._PROJECT_C.clear()
    it = suru.Interpreter(out=lambda s: None)
    it.ctx.base_dir = str(base_dir)
    return it.run(source)


def test_インタプリタでCソースの関数を呼ぶ(tmp_path, monkeypatch):
    monkeypatch.setenv("KUMU_HOME", str(tmp_path / "kumu"))
    monkeypatch.setenv("SURU_TEST_SCALE", "3")
    app = make_project(tmp_path)
    assert run(PROGRAM, app) == [32]
    # ヘッダーを変えると作り直す
    (tmp_path / "部品/c/部品.h").write_text("#define OFFSET 2\n", encoding="utf-8")
    assert run(PROGRAM, app) == [34]


def test_環境変数がない(tmp_path, monkeypatch):
    monkeypatch.setenv("KUMU_HOME", str(tmp_path / "kumu"))
    monkeypatch.delenv("SURU_TEST_SCALE", raising=False)
    app = make_project(tmp_path)
    with pytest.raises(SuruError) as info:
        run(PROGRAM, app)
    assert "「部品」のC引数「-DSCALE=${SURU_TEST_SCALE}」に使う環境変数「SURU_TEST_SCALE」がありません" in info.value.message


def test_コンパイルの失敗(tmp_path, monkeypatch):
    monkeypatch.setenv("KUMU_HOME", str(tmp_path / "kumu"))
    monkeypatch.setenv("SURU_TEST_SCALE", "3")
    app = make_project(tmp_path)
    (app / "包み.c").write_text("this is not C\n", encoding="utf-8")
    with pytest.raises(SuruError) as info:
        run(PROGRAM, app)
    assert "「本」のCソース「包み.c」のコンパイルに失敗しました" in info.value.message

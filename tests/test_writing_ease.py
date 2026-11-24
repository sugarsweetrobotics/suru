"""書きやすさの小さな直し(#119): 文字列の中の「」、試験/ の同じ名前のファイル、
型の宣言の「文字列 と JSON を」、「する」で終わらない関数名のエラー"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import Interpreter, SuruError, tokenize_line  # noqa: E402
from suru_check import check  # noqa: E402


def _run(src: str) -> list[str]:
    return Interpreter().run_text(src)


def _err(src: str) -> str:
    with pytest.raises(SuruError) as info:
        check(src)
    return str(info.value)


# --- 文字列の中の「」 ---


def test_文字列の中の鉤括弧は入れ子として数える():
    assert _run("「失敗: 「abc」は数にできません」\n") == ["失敗: 「abc」は数にできません"]
    assert _run("「a「b「c」」d」 の 長さ\n") == ["8"]
    assert _run("「「です」は文の終わりに書きます」 + 「。」\n") == ["「です」は文の終わりに書きます。"]
    # 句読点の書き方でも同じ
    assert _run("xとは、「彼は「はい」と言った」。x。\n") == ["彼は「はい」と言った"]
    assert [t.value for t in tokenize_line("「a「b」c」 と 「d」", 1) if t.kind == "STR"] == ["a「b」c", "d"]


def test_閉じていない鉤括弧はエラー():
    with pytest.raises(SuruError, match="文字列の「に対応する」がありません"):
        _run("「a「b」 + 「c」\n")


def test_鉤括弧1つだけは文字の番号で作る():
    assert _run("「標準」 を 読み込んで 使う\n（12300 を 文字にする） + 「a」\n") == ["「a"]


# --- 型の宣言の「文字列 と 数 を」 ---

PAIR = """文字列 と 数 を 表示文にする は 文字列
名 と 値 を 表示文にする とは 名 + 「=」 + （値 を 文字列化する）
"""


def test_型の違う2つをとで受け取る():
    src = PAIR + "「a」 と 3 を 表示文にする\n（「b」 と 4 を 表示文にする） + 「!」\n「c」 と 5 を 表示文にして 表示する\n"
    check(src)
    assert _run(src) == ["a=3", "b=4!"]


def test_型の違う2つをとで受け取る_型変数():
    src = ("甲 と 乙 を 入替する は （乙 と 甲） の 対\na と b を 入替する とは b と a の 対\n対 とは 左 と 右 の 組\n"
           "（「x」 と 1 を 入替する） の 左\n")
    check(src)
    assert _run(src) == ["1"]


def test_型の違う2つをとで受け取る_間違い():
    assert "「と」でつないだ1番目の値は文字列のはずですが、数です" in _err(PAIR + "3 と 3 を 表示文にする\n")
    assert "「と」でつないだ2番目の値は数のはずですが、文字列です" in _err(PAIR + "「a」 と 「b」 を 表示文にする\n")
    assert "「表示文にする」の値は文字列と宣言されていますが、数になっています" in _err(
        "文字列 と 数 を 表示文にする は 文字列\n名 と 値 を 表示文にする とは 値\n")


def test_宣言がなければとはリスト():
    e = _err("名 と 値 を 表示文にする とは 名\n「a」 と 3 を 表示文にする\n")
    assert "リストの要素の型がそろっていません(文字列 と 数)" in e
    assert "型の宣言で「文字列 と 数 を …」" in e
    assert _run("a と b を 足算する とは a + b\n1 と 2 を 足算する\n") == ["3"]


# --- 「する」で終わらない関数名 ---


def test_するで終わらない関数名のエラー():
    assert "関数名は「する」で終わる必要があります(「流す」)" in _err("数 で 流す は 数 を 返す 入出力動作\n")
    assert "関数名は「する」で終わる必要があります(「流す」)" in _err("x で 流す とは x\n")
    assert "関数名は「する」で終わる必要があります(「倍にして」)" in _err("x を 倍にして とは x\n")
    # 「名前 は 値」の組はこれまでどおり
    assert "「名前 は 値」の後に「の 型名」が必要です" in _err("横 は 3 で 縦 は 4\n")


# --- 試験/ の同じ名前のファイル ---


def _project(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "おはなし"
    (root / "試験").mkdir(parents=True)
    (root / "組.suru").write_text("名前 とは 「お話」\n", encoding="utf-8")
    (root / "会話帳.suru").write_text("x を 倍にする とは x * 2\n", encoding="utf-8")
    (root / "試験" / "会話帳.suru").write_text("「会話帳」 を 読み込む\n3 を 会話帳内の倍にして 表示する\n", encoding="utf-8")
    return root


def _suru(path: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), str(path)], capture_output=True, text=True,
                          env=os.environ.copy())


def test_試験の同じ名前のファイルはプロジェクトのほうを読む(tmp_path):
    root = _project(tmp_path)
    r = _suru(root / "試験" / "会話帳.suru")
    assert (r.returncode, r.stdout) == (0, "6\n"), r.stderr


def test_自分自身しかなければエラー(tmp_path):
    (tmp_path / "自分.suru").write_text("「自分」 を 読み込む\n", encoding="utf-8")
    r = _suru(tmp_path / "自分.suru")
    assert r.returncode == 1
    assert "「自分.suru」を読み込むと、自分自身を読み込むことになります" in r.stderr


def test_試験の同じ名前のファイル_Go版(tmp_path):
    if shutil.which("go") is None:
        pytest.skip("go がない")
    root = _project(tmp_path)
    exe = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    r = subprocess.run([str(exe), str(root / "試験" / "会話帳.suru"), "-o", str(tmp_path / "a")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert subprocess.run([str(tmp_path / "a")], capture_output=True, text=True).stdout == "6\n"
    (tmp_path / "自分.suru").write_text("「自分」 を 読み込む\n", encoding="utf-8")
    r = subprocess.run([str(exe), str(tmp_path / "自分.suru"), "-o", str(tmp_path / "b")], capture_output=True, text=True)
    assert "「自分.suru」を読み込むと、自分自身を読み込むことになります" in r.stderr

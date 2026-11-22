"""lib/点検.suru(する で書いた点検)と「suru --点検」のテスト。インタプリタとバイナリの両方で同じ結果か"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

BAD = """x を 三倍する とは x * 3\x20\x20
5 を 三倍して 表示します
6 を 三倍して 表示する
7 を 三倍して 表示する
『半径』 とは （1 ＋ 2)
y とは 『おやつ』
  a とは 1
\tb とは 2 # 点検しない: 字下げの混在
\tc とは 2
# 点検しない
1 を 表示する\x20
「閉じない
"""

BAD_OUT = """\
DIR/bad.suru:1:18: 行末の空白: 行の終わりに空白があります
DIR/bad.suru:2:10: 丁寧語の混在: 文の終わりが「する」の文が3つ、「します」の文が1つあります。「する」にそろえると読みやすくなります
DIR/bad.suru:5:1: 不要な二重かぎ: 『半径』はひらがなを含まないので、『』で囲まなくても書けます
DIR/bad.suru:5:9: 全角半角の混在: このファイルの括弧は半角が多いので、「（」も半角にそろえると読みやすくなります
DIR/bad.suru:5:12: 全角半角の混在: このファイルの記号は半角が多いので、「＋」も半角にそろえると読みやすくなります
DIR/bad.suru:9:1: 字下げの混在: このファイルの字下げは半角スペースですが、この行にはタブが使われています
DIR/bad.suru:12:1: 字句の誤り: 文字列の「に対応する」がありません
"""

POLITE = """5を三倍します。
6を三倍します。
7を三倍する。
"""

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def run_lint(kind: str, tmp_path: pathlib.Path, *paths: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, XDG_CACHE_HOME=str(tmp_path / "cache"))
    if kind == "interp":
        env["SURU_LINT_INTERP"] = "1"
    else:
        env.pop("SURU_LINT_INTERP", None)
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), "--点検", *paths],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)


@pytest.mark.parametrize("kind", KINDS)
def test_知らせと終了コード(kind, tmp_path):
    (tmp_path / "bad.suru").write_text(BAD, encoding="utf-8")
    (tmp_path / "polite.suru").write_text(POLITE, encoding="utf-8")
    (tmp_path / "good.suru").write_text("x とは 1\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "bad.suru", "good.suru", "polite.suru")
    assert r.returncode == 1, r.stderr
    assert r.stdout == BAD_OUT.replace("DIR/", "") + (
        "polite.suru:3:3: 丁寧語の混在: 文の終わりが「する」の文が1つ、「します」の文が2つあります。「します」にそろえると読みやすくなります\n")
    r = run_lint(kind, tmp_path, "good.suru")
    assert (r.returncode, r.stdout) == (0, "")
    if kind == "binary":
        assert len(list((tmp_path / "cache" / "suru").glob("点検-*"))) == 1


def test_例とライブラリは知らせなし(tmp_path):
    files = sorted(str(p) for p in (ROOT / "examples").glob("*.suru")) + sorted(str(p) for p in (ROOT / "lib").glob("*.suru"))
    r = run_lint(KINDS[-1], tmp_path, *files)
    assert (r.returncode, r.stdout) == (0, ""), r.stdout + r.stderr


def test_ファイルがないと使い方(tmp_path):
    r = run_lint("interp", tmp_path)
    assert r.returncode == 2
    assert "使い方" in r.stderr

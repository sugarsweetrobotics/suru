"""エラーと点検の知らせを JSON で出す(--json)のテスト。Python 版と Go 版(suruc)で同じ JSON か"""

import json
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SURU = [sys.executable, str(ROOT / "suru.py")]

TYPE_ERR = "数 を 二乗する は 数\nx を 二乗する とは x * x\n「あ」 を 二乗して 表示する\n"
SYNTAX_ERR = "数 を 二乗する は 数\nx を 二乗する とは （x * x\n"
RUN_ERR = "数 を 半分にする は 数\nx を 半分にする とは x / 0\n4 を 半分にして 表示する\n"
USE_PART = "「部品」 を 読み込む\n3 を 部品内の二乗して 表示する\n"
PART_ERR = "数 を 二乗する は 数\nx を 二乗する とは x + 「a」\n"
GOOD = "数 を 二乗する は 数\nx を 二乗する とは x * x\n3 を 二乗して 表示する\n"


def run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def one(text: str) -> dict:
    lines = text.splitlines()
    assert len(lines) == 1, text
    return json.loads(lines[0])


@pytest.fixture
def files(tmp_path):
    for name, src in [("型.suru", TYPE_ERR), ("構文.suru", SYNTAX_ERR), ("実行.suru", RUN_ERR),
                      ("使う.suru", USE_PART), ("部品.suru", PART_ERR), ("良い.suru", GOOD)]:
        (tmp_path / name).write_text(src, encoding="utf-8")
    return tmp_path


def test_型のエラー(files):
    r = run(SURU + ["--検査", "--json", "型.suru"], files)
    assert r.returncode == 1 and r.stdout == ""
    assert one(r.stderr) == {"file": "型.suru", "line": 3, "column": 7, "kind": "型", "rule": None,
                             "message": "「二乗する」の「を」には数が必要ですが、文字列が渡されています"}


def test_構文のエラー(files):
    r = run(SURU + ["--検査", "--json", "構文.suru"], files)
    assert r.returncode == 1
    assert one(r.stderr) == {"file": "構文.suru", "line": 2, "column": 13, "kind": "構文", "rule": None,
                             "message": "「(」に対応する「)」がありません"}


def test_jsonはファイルの後ろでもよい(files):
    r = run(SURU + ["--検査", "構文.suru", "--json"], files)
    assert one(r.stderr)["kind"] == "構文"


def test_実行時のエラー(files):
    r = run(SURU + ["--json", "実行.suru"], files)
    assert r.returncode == 1
    assert one(r.stderr) == {"file": "実行.suru", "line": 2, "column": 16, "kind": "実行", "rule": None,
                             "message": "0 で割ることはできません"}


def test_読み込んだファイルの中のエラーはそのファイルの位置(files):
    r = run(SURU + ["--検査", "--json", "使う.suru"], files)
    e = one(r.stderr)
    assert (pathlib.Path(e["file"]).name, e["line"], e["column"], e["kind"]) == ("部品.suru", 2, 15, "型")
    assert e["message"].startswith("「+」の両側の型が違います")


def test_問題がなければ何も出さない(files):
    r = run(SURU + ["--検査", "--json", "良い.suru"], files)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    r = run(SURU + ["--json", "良い.suru"], files)
    assert (r.returncode, r.stdout) == (0, "9\n")


def test_プログラムの引数の後ろのjsonはプログラムに渡す(files):
    (files / "引数.suru").write_text("「環境」 を 読み込む\n環境内の引数取得してから 表示する\n", encoding="utf-8")
    r = run(SURU + ["引数.suru", "--json"], files)
    assert (r.returncode, r.stdout) == (0, "（「--json」）\n")


def test_点検の知らせ(files):
    (files / "点検.suru").write_text("x とは 1 \n", encoding="utf-8")
    r = run(SURU + ["--点検", "--json", "点検.suru"], files)
    assert r.returncode == 1
    rows = [json.loads(s) for s in r.stdout.splitlines()]
    assert {"file": "点検.suru", "line": 1, "column": 7, "kind": "点検", "rule": "行末の空白",
            "message": "行の終わりに空白があります"} in rows
    assert all(set(x) == {"file", "line", "column", "kind", "rule", "message"} for x in rows)


@pytest.mark.skipif(shutil.which("go") is None, reason="go がありません")
def test_Go版も同じJSON(files, tmp_path_factory):
    exe = tmp_path_factory.mktemp("go") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    for name in ["型.suru", "構文.suru", "使う.suru", "良い.suru"]:
        py = run(SURU + ["--検査", "--json", name], files)
        go = run([str(exe), "--検査", "--json", name], files)
        assert (go.returncode, go.stdout, go.stderr) == (py.returncode, py.stdout, py.stderr), name
    # コンパイルするときも同じ形
    py = run(SURU + ["--翻訳", "--ll", "--json", "構文.suru"], files)
    go = run([str(exe), "--ll", "--json", "構文.suru"], files)
    assert go.stderr == py.stderr and one(go.stderr)["kind"] == "構文"

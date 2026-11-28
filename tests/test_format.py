"""空白を整える suru --整える(lib/整形.suru、#250)"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

MESSY = (
    "\n"
    "数 を  二倍する は 数\n"
    "x を 二倍する とは   x * 2   \n"
    "\n\n\n\n"
    "以下は【例】です\n"
    "  a    b\n"
    "以上です\n"
    "f とは\n"
    "　もし 1 > 0 ならば 「a  b」 そうでなければ 「c」   # 注  \n"
    "\t# タブの字下げ\n"
    "（3  を 二倍する） を 表示する\n"
    "\n\n"
)
TIDY = (
    "数 を 二倍する は 数\n"
    "x を 二倍する とは x * 2\n"
    "\n\n"
    "以下は【例】です\n"
    "  a    b\n"
    "以上です\n"
    "f とは\n"
    "  もし 1 > 0 ならば 「a  b」 そうでなければ 「c」   # 注\n"
    "    # タブの字下げ\n"
    "（3 を 二倍する） を 表示する\n"
)


def run(kind: str, tmp_path: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if kind == "interp":
        env["SURU_LINT_INTERP"] = "1"
    else:
        env.pop("SURU_LINT_INTERP", None)
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), "--整える", *args],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)


@pytest.mark.parametrize("kind", KINDS)
def test_空白を整える(kind, tmp_path):
    f = tmp_path / "a.suru"
    f.write_text(MESSY, encoding="utf-8")
    r = run(kind, tmp_path, "--確認", "a.suru")
    assert (r.returncode, r.stdout) == (1, "a.suru: 整えていません\n"), r.stderr
    assert f.read_text(encoding="utf-8") == MESSY
    r = run(kind, tmp_path, "--出力", "a.suru")
    assert (r.returncode, r.stdout) == (0, TIDY), r.stderr
    r = run(kind, tmp_path, "a.suru")
    assert (r.returncode, r.stdout) == (0, "a.suru: 整えました\n"), r.stderr
    assert f.read_text(encoding="utf-8") == TIDY
    # 2回目は何もしない
    r = run(kind, tmp_path, "a.suru")
    assert (r.returncode, r.stdout) == (0, ""), r.stderr


def test_使い方(tmp_path):
    r = run("interp", tmp_path)
    assert r.returncode == 2 and "使い方: suru --整える" in r.stderr


def test_例とライブラリは整っている(tmp_path):
    files = sorted(str(p) for p in (ROOT / "lib").glob("*.suru"))
    r = run(KINDS[-1], tmp_path, "--確認", *files)
    assert (r.returncode, r.stdout) == (0, ""), r.stdout + r.stderr

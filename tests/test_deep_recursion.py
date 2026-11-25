"""インタプリタの深い再帰(#152)"""
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402

DEEP = ("数 を 非末尾和する は 数\n0 を 非末尾和する とは 0\n"
        "n を 非末尾和する とは n + （n - 1 を 非末尾和する）\n（100000 を 非末尾和する） を 表示する\n")
ENDLESS = "数 を 無限する は 数\nn を 無限する とは 1 + （n + 1 を 無限する）\n（1 を 無限する） を 表示する\n"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="Python 3.11 までは再帰の上限を小さくしている")
def test_10万段の再帰も動く(tmp_path):
    path = tmp_path / "深い.suru"
    path.write_text(DEEP, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(path)], capture_output=True, text=True)
    assert (r.returncode, r.stdout, r.stderr) == (0, "5000050000\n", "")


def _run_endless(tmp_path, monkeypatch, capsys, *flags):
    # 上限を小さくして、止まったときの知らせ方を確かめる
    path = tmp_path / "無限.suru"
    path.write_text(ENDLESS, encoding="utf-8")
    monkeypatch.setattr(suru, "RECURSION_LIMIT", 3000)
    saved = sys.getrecursionlimit()
    try:
        code = suru.main(["suru", *flags, str(path)])
    finally:
        sys.setrecursionlimit(saved)
    return code, capsys.readouterr()


def test_深すぎる再帰は_する_のエラーにする(tmp_path, monkeypatch, capsys):
    code, out = _run_endless(tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "Traceback" not in out.err
    assert out.err.startswith("エラー: 再帰が深すぎます(もっと深い再帰は、suruc か suru --翻訳 でコンパイルすると動きます)")


def test_深すぎる再帰のエラーも_JSON_で出す(tmp_path, monkeypatch, capsys):
    code, out = _run_endless(tmp_path, monkeypatch, capsys, "--json")
    assert code == 1
    e = json.loads(out.err.strip())
    assert (e["kind"], e["line"]) == ("実行", None)
    assert e["message"].startswith("再帰が深すぎます")

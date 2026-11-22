"""lib/シグナル.suru のテスト: インタプリタとコンパイルしたバイナリで同じに動くか"""

import os
import pathlib
import signal
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

SELF = """「シグナル」 を 読み込んで 使う
「プロセス」 を 読み込む
試す とは 手順
  「TERM」 を シグナル番号取得してから 表示する
  （「USR1」 と 「TERM」） を シグナル受付する
  シグナル確認してから 表示する
  「USR1」 を シグナル発生する
  pid とは プロセス内のプロセス番号取得した 結果
  「TERM」 を pid へ シグナル送信する
  シグナル確認してから 表示する
  シグナル確認してから 表示する
  「USR2」 を シグナル発生する
  「USR1」 を pid へ シグナル送信する
  シグナル待機してから 表示する
  「HUP」 を シグナル無視する
  「HUP」 を シグナル発生する
  「まだ動いている」 を 表示する
  「HUP」 を シグナル既定化する
  （「USR1」 と 「TERM」） を シグナル受付解除する
  「TERM」 を シグナル発生する
  「ここは出ない」 を 表示する
試す
"""

SELF_OUT = "15\n空\n（「TERM」 と 「USR1」）\n空\nUSR1\nまだ動いている\n"

WAIT = """「シグナル」 を 読み込んで 使う
試す とは 手順
  （「INT」 と 「TERM」） を シグナル受付する
  「待っています」 を 表示する
  シグナル待機してから 表示する
  シグナル待機してから 表示する
  「おわり」 を 表示する
試す
"""

BAD_NAME = "「シグナル」 を 読み込む\n「SIGTERM」 を シグナル内のシグナル発生する\n"

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


@pytest.mark.parametrize("kind", KINDS)
def test_自分に送って受け取る(tmp_path, kind):
    """受付した USR1・TERM は届いても終わらず、確認・待機で受け取れる。受付を解除した TERM で終わる"""
    r = subprocess.run(build(SELF.replace("  「USR2」 を シグナル発生する\n", ""), tmp_path, kind),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == -signal.SIGTERM, r.stderr
    assert r.stdout == SELF_OUT


@pytest.mark.parametrize("kind", KINDS)
def test_受付していないシグナルで終わる(tmp_path, kind):
    r = subprocess.run(build(SELF, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == -signal.SIGUSR2, r.stderr
    assert r.stdout == "15\n空\n（「TERM」 と 「USR1」）\n空\n"


@pytest.mark.parametrize("kind", KINDS)
def test_外から送られたシグナルを待つ(tmp_path, kind):
    p = subprocess.Popen(build(WAIT, tmp_path, kind), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline() == "待っています\n"  # 待つ前に表示を出しておくこと
        p.send_signal(signal.SIGTERM)
        assert p.stdout.readline() == "TERM\n"
        p.send_signal(signal.SIGINT)
        out, err = p.communicate(timeout=30)
    finally:
        p.kill()
    assert p.returncode == 0, err
    assert out == "INT\nおわり\n"


@pytest.mark.parametrize("kind", KINDS)
def test_ない名前(tmp_path, kind):
    r = subprocess.run(build(BAD_NAME, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "『SIGTERM』というシグナルはありません(TERM・INT のように SIG を除いた名前で書きます)" in r.stderr

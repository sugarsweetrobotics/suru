"""fork・exec(lib/プロセス.suru)とセマフォ(lib/セマフォ.suru)のテスト: インタプリタとバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

FORK = """「プロセス」 を 読み込んで 使う
試す とは 手順
  「まえ」 を 表示する
  pid とは 分岐した 結果
  もし pid = 0 ならば 子の仕事する そうでなければ pid を 親待機する
子の仕事する は 数 の 動作
子の仕事する とは 手順
  「子です」 を 表示する
  7 を 子終了する
数 を 親待機する は 数 の 動作
pid を 親待機する とは 手順
  c とは pid を 子終了待機した 結果
  （「子の終了コード」 + （c を 文字列化する）） を 表示する
  pid2 とは 分岐した 結果
  もし pid2 = 0 ならば （「sh」 と 「-c」 と 「echo 置換しました $0; exit 4」 と 「い ろ」） を 置換実行する そうでなければ pid2 を 子終了待機してから 表示する
  pid3 とは 分岐した 結果
  もし pid3 = 0 ならば （「suru-no-such-command」 を 1 で 複製する） を 置換実行する そうでなければ pid3 を 子終了待機してから 表示する
試す
"""

FORK_OUT = "まえ\n子です\n子の終了コード7\n置換しました い ろ\n4\n1\n"

# 2 つの子が、セマフォをロックにして共有メモリの数を 50 回ずつ 1 増やす
COUNTER = """「プロセス」 を 読み込んで 使う
「セマフォ」 を 読み込んで 使う
「共有メモリ」 を 読み込んで 使う
数 から 共有メモリ で セマフォ に 増加続けする は 数 の 動作
n から m で s に 増加続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ n から m で s に 増加本体する
数 から 共有メモリ で セマフォ に 増加本体する は 数 の 動作
n から m で s に 増加本体する とは 手順
  s を セマフォ待機する
  b とは m から 1 を 0 で 共有読込した 結果
  x とは （b を 数列にする） の 先頭
  （（x + 1） を 1 で 複製して バイト列組立する） を 0 で m へ 共有書込する
  s を セマフォ解放する
  n - 1 から m で s に 増加続けする
共有メモリ で セマフォ を 子作成する は 数 の 動作
m で s を 子作成する とは 手順
  pid とは 分岐した 結果
  もし pid = 0 ならば m で s を 子本体する そうでなければ pid を 結果にする
共有メモリ で セマフォ を 子本体する は 数 の 動作
m で s を 子本体する とは 手順
  50 から m で s に 増加続けする
  0 を 子終了する
試す とは 手順
  m とは 「SHM」 を 8 で 共有メモリ作成した 結果
  s とは 「SEM」 を 1 で セマフォ作成した 結果
  a とは m で s を 子作成した 結果
  b とは m で s を 子作成した 結果
  a を 子終了待機する
  b を 子終了待機する
  m から 1 を 0 で 共有読込してから 数列にして 表示する
  s を セマフォ試行してから 表示する
  s を セマフォ試行してから 表示する
  s を セマフォ削除する
  m を 共有メモリ解除する
  「SHM」 を 共有メモリ削除する
試す
"""

FAIL_SEM = "「セマフォ」 を 読み込む\n「SEM」 を セマフォ内のセマフォ接続する\n"

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
def test_分岐と置換実行(tmp_path, kind):
    r = subprocess.run(build(FORK, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == FORK_OUT
    assert "命令『suru-no-such-command』を実行するのに失敗しました(No such file or directory)" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_セマフォで順番に増やす(tmp_path, kind):
    tag = f"suru-test-{os.getpid()}-{kind}"
    src = COUNTER.replace("SHM", "/" + tag).replace("SEM", tag)
    r = subprocess.run(build(src, tmp_path, kind), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "（100）\n真\n偽\n"


@pytest.mark.parametrize("kind", KINDS)
def test_ないセマフォ(tmp_path, kind):
    tag = f"suru-test-{os.getpid()}-none-{kind}"
    r = subprocess.run(build(FAIL_SEM.replace("SEM", tag), tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert f"セマフォ『{tag}』に接続するのに失敗しました(No such file or directory)" in r.stderr

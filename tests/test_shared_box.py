"""共有箱(lib/共有箱.suru)のテスト: インタプリタとバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

BASIC = """「共有箱」 を 読み込んで 使う
点 とは 横 と 縦 の 組
文字列 を 点接続する は 点 の 共有箱 の 動作
名前 を 点接続する とは 名前 を 共有箱接続する
試す とは 手順
  b とは 「BOX」 を （1 と 2 の 点） で 256 に 共有箱作成した 結果
  b を 共有箱読取してから 表示する
  （3 と 4 の 点） を b へ 共有箱書込する
  b を （p を 受け取って （p の 横 + 10） と p の 縦 の 点 を 返すこと） で 共有箱更新してから 表示する
  c とは 「BOX」 を 点接続した 結果
  c を 共有箱読取してから 表示する
  （5 と 6 の 点） を c へ 共有箱書込する
  b を 共有箱読取してから 表示する
  c を 共有箱解除する
  b を 共有箱削除する
試す
"""

BASIC_OUT = """（横 は 1 で 縦 は 2 の 点）
（横 は 13 で 縦 は 4 の 点）
（横 は 13 で 縦 は 4 の 点）
（横 は 5 で 縦 は 6 の 点）
"""

# 2 つの子が、共有箱の数を 50 回ずつ 1 増やす。途中でエラーになった更新のあともロックは戻る
COUNTER = """「プロセス」 を 読み込んで 使う
「共有箱」 を 読み込んで 使う
数 の 共有箱 を 数 で 増加続けする は 数 の 動作
b を n で 増加続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ b を n で 一回増加する
数 の 共有箱 を 数 で 一回増加する は 数 の 動作
b を n で 一回増加する とは 手順
  b を （x を 受け取って x + 1 を 返すこと） で 共有箱更新する
  b を n - 1 で 増加続けする
数 の 共有箱 を 子作成する は 数 の 動作
b を 子作成する とは 手順
  pid とは 分岐した 結果
  もし pid = 0 ならば b を 子本体する そうでなければ pid を 結果にする
数 の 共有箱 を 子本体する は 数 の 動作
b を 子本体する とは 手順
  b を 50 で 増加続けする
  0 を 子終了する
数 の 共有箱 を 計数する は 数 の 動作
b を 計数する とは 手順
  p とは b を 子作成した 結果
  q とは b を 子作成した 結果
  p を 子終了待機する
  q を 子終了待機する
  b を 共有箱読取してから 表示する
  （b を （x を 受け取って x / 0 を 返すこと） で 共有箱更新する） を （0 を 結果にする） で 試行する
  b を （x を 受け取って x + 1 を 返すこと） で 共有箱更新してから 表示する
「BOX」 を 0 で （b を 受け取って b を 計数する を 返すこと） に 共有箱使用する
"""

TOO_BIG = """「共有箱」 を 読み込んで 使う
「標準」 を 読み込んで 使う
文字列 の 共有箱 を 長く書込する は 文字列 の 動作
b を 長く書込する とは （（「とても長い文字列をここに書きます。」 を 400 で 複製する） を 「」 で 結合する） を b へ 共有箱書込する
「BOX」 を 「あ」 で （b を 受け取って b を 長く書込する を 返すこと） に 共有箱使用する
"""

NOT_BOX = """「共有メモリ」 を 読み込んで 使う
「共有箱」 を 読み込んで 使う
数 の 共有箱 を 不使用にする は 数
b を 不使用にする とは 0
試す とは 手順
  m とは 「BOX」 を 256 で 共有メモリ作成した 結果
  b とは 「BOX」 を 共有箱接続した 結果
  b を 不使用にする
試す
"""


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


def run(source: str, d: pathlib.Path, kind: str, tag: str) -> subprocess.CompletedProcess:
    name = f"/suru-test-{os.getpid()}-{tag}-{kind}"
    try:
        return subprocess.run(build(source.replace("BOX", name), d, kind), capture_output=True, text=True, timeout=120)
    finally:
        try:
            os.unlink("/dev/shm" + name)
        except OSError:
            pass


@pytest.mark.parametrize("kind", KINDS)
def test_作って読み書きする(tmp_path, kind):
    r = run(BASIC, tmp_path, kind, "basic")
    assert r.returncode == 0, r.stderr
    assert r.stdout == BASIC_OUT


@pytest.mark.parametrize("kind", KINDS)
def test_子と数える(tmp_path, kind):
    r = run(COUNTER, tmp_path, kind, "count")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "100\n101\n"
    assert "』を書く途中でエラーになりました" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_大きすぎる値(tmp_path, kind):
    r = run(TOO_BIG, tmp_path, kind, "big")
    assert r.returncode == 1
    assert "に入れる値が大きすぎます(直列化して" in r.stderr
    assert "』を使う動作はエラーで終わりました" in r.stderr
    assert not os.path.exists(f"/dev/shm/suru-test-{os.getpid()}-big-{kind}")


@pytest.mark.parametrize("kind", KINDS)
def test_共有箱でない(tmp_path, kind):
    r = run(NOT_BOX, tmp_path, kind, "notbox")
    assert r.returncode == 1
    assert "』は共有箱ではありません" in r.stderr

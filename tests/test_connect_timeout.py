"""「通信」の 期限付き接続する・記述子取得する と、時間切れの文(「…で通信に失敗しました(時間切れ)」)を、インタプリタとコンパイルしたもので確かめる"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from test_udp import KINDS, run  # noqa: E402

# つながる相手には、ふつうにつながる。受け取りの時間切れも同じ文になる
CONNECT = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

始めする とは 以下の入出力手順です
  口 とは 0 を 「127.0.0.1」 に 通信内の待受開始した 結果
  ポート とは 口 を 通信内のポート取得した 結果
  c とは 「127.0.0.1」 に ポート で 2 を 通信内の期限付き接続した 結果
  c を 0.2 で 通信内の待機時間設定する
  （c から 通信内の行受信する） を 試行した 結果 を 表示する
  （「127.0.0.1」 に ポート で 0 を 通信内の期限付き接続する） を 試行した 結果 を 表示する
  （（c を 通信内の記述子取得した 結果） > 0） を 表示する
  c を 5 で 通信内の待機時間設定する
  以上です
始めする
"""


@pytest.mark.parametrize("kind", KINDS)
def test_connect_within(kind, tmp_path):
    r = run(CONNECT, kind, tmp_path)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "（理由 は 「「行受信する」で通信に失敗しました(時間切れ)」 の 失敗）"
    assert lines[1] == "（理由 は 「「0」は待つ秒数ではありません(0 より大きい数です)」 の 失敗）"
    assert lines[2] == "真"


# 受け付けない待受口の待ち行列をいっぱいにすると、次の接続は時間切れになる(Linux)
FILL = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

数 を 数 で 埋めする は 数 を 返す 入出力動作
ポート を n で 埋めする とは 以下の手順です
  r とは （「127.0.0.1」 に ポート で 0.3 を 通信内の期限付き接続する） を 試行した 結果
  もし （r を 有無にする） = 無 ならば r を 報告する そうでなければ もし n > 200 ならば 0 を 結果にする そうでなければ ポート を n + 1 で 埋めする
  以上です

（数 と 文字列） の 成否 を 報告する は 数 を 返す 入出力動作
r を 報告する とは 以下の手順です
  r を 表示する
  0 を 結果にする
  以上です

始めする とは 以下の入出力手順です
  口 とは 0 を 「127.0.0.1」 に 通信内の待受開始した 結果
  ポート とは 口 を 通信内のポート取得した 結果
  ポート を 0 で 埋めする
  以上です
始めする
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="待ち行列があふれたときの振る舞いは OS ごとに違う")
@pytest.mark.parametrize("kind", KINDS)
def test_connect_times_out(kind, tmp_path):
    r = run(FILL, kind, tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "（理由 は 「「期限付き接続する」で通信に失敗しました(時間切れ)」 の 失敗）"

"""「通信」のポート取得する・相手アドレス取得する・相手ポート取得する と、待ち受けるアドレスの指定(「に」)"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from test_udp import KINDS, run  # noqa: E402

PROGRAM = """「通信」 を 読み込んで 使う

始めする とは 入出力手順
  口 とは 0 を 「127.0.0.1」 に 待受開始した 結果
  ポート とは 口 を ポート取得した 結果
  （ポート > 0） を 表示する
  客 とは 「127.0.0.1」 に ポート で 接続した 結果
  受 とは 口 から 接続受付した 結果
  受 を 相手アドレス取得した 結果 を 表示する
  （（受 を 相手ポート取得した 結果） = （客 を ポート取得した 結果）） を 表示する
  （（客 を 相手ポート取得した 結果） = ポート） を 表示する
  u とは 0 を 「localhost」 に UDP開始した 結果
  （（u を ポート取得した 結果） > 0） を 表示する
  （u を 相手アドレス取得する） を 試行した 結果 を 表示する
  （0 を 「no-such-host.invalid」 に UDP開始する） を 試行した 結果 を 表示する
  v とは 0 を UDP開始した 結果
  （v を ポート取得した 結果） > 0 を 表示する
  口 を 切断する
  （口 を ポート取得する） を 試行した 結果 を 表示する
始めする
"""


@pytest.mark.parametrize("kind", KINDS)
def test_ポートとアドレス(kind, tmp_path):
    r = run(PROGRAM, kind, tmp_path)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[:5] == ["真", "127.0.0.1", "真", "真", "真"]
    assert lines[5] == "（理由 は 「「相手アドレス取得する」で通信に失敗しました(Transport endpoint is not connected)」 の 失敗）"
    assert lines[6].startswith("（理由 は 「「UDP開始する」で通信に失敗しました(")
    assert lines[7] == "真"
    assert "は開いている待受口か接続かUDPの口ではありません" in lines[8]


def test_アドレスは文字列(tmp_path):
    r = run("「通信」 を 読み込んで 使う\n0 を 1 に 待受開始する\n", "インタプリタ", tmp_path)
    assert r.returncode == 1
    assert "「待受開始する」の「に」には文字列が必要です" in r.stderr

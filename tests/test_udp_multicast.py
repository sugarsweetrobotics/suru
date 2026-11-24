"""「通信」の ブロードキャスト許可する・マルチキャスト参加する・マルチキャスト離脱する と IPv6 の口(#123 の段階3)"""

import pathlib
import socket
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from test_udp import KINDS, run  # noqa: E402


def _multicast_works() -> bool:
    """この機械で、自分に送ったマルチキャストとブロードキャストが届くか(ネットワークのない所では届かない)"""
    try:
        r = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        r.bind(("0.0.0.0", 0))
        r.settimeout(1)
        port = r.getsockname()[1]
        r.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton("239.1.2.3") + socket.inet_aton("0.0.0.0"))
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b"m", ("239.1.2.3", port))
        r.recvfrom(10)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(b"b", ("255.255.255.255", port))
        r.recvfrom(10)
        return True
    except OSError:
        return False


def _ipv6_works() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


MULTICAST = """「通信」 を 読み込んで 使う

始めする とは 入出力手順
  受 とは 0 を UDP開始した 結果
  受 を 5 で 待機時間設定する
  ポート とは 受 を ポート取得した 結果
  受 を 「239.1.2.3」 に マルチキャスト参加する
  送 とは 0 を UDP開始した 結果
  「みなさん」 を 送 から 「239.1.2.3」 に ポート で UDP送信する
  便 とは 受 から UDP受信した 結果
  便 の 中身 を 表示する
  （「x」 を 送 から 「255.255.255.255」 に ポート で UDP送信する） を 試行した 結果 を 表示する
  送 を ブロードキャスト許可する
  「全員」 を 送 から 「255.255.255.255」 に ポート で UDP送信する
  便2 とは 受 から UDP受信した 結果
  便2 の 中身 を 表示する
  受 を 「239.1.2.3」 から マルチキャスト離脱する
  （受 を 「10.0.0.1」 に マルチキャスト参加する） を 試行した 結果 を 表示する
始めする
"""


@pytest.mark.skipif(not _multicast_works(), reason="この機械では自分へのマルチキャストかブロードキャストが届きません")
@pytest.mark.parametrize("kind", KINDS)
def test_マルチキャストとブロードキャスト(kind, tmp_path):
    r = run(MULTICAST, kind, tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "みなさん",
        "（理由 は 「「UDPバイト列送信する」で通信に失敗しました(Permission denied)」 の 失敗）",
        "全員",
        "（理由 は 「「10.0.0.1」はマルチキャストのアドレスではありません(IPv4 は 224.0.0.0〜239.255.255.255、IPv6 は ff で始まる)」 の 失敗）",
    ]


def test_マルチキャストのアドレスは文字列(tmp_path):
    r = run("「通信」 を 読み込んで 使う\n1 を 2 に マルチキャスト参加する\n", "インタプリタ", tmp_path)
    assert r.returncode == 1
    assert "「マルチキャスト参加する」の「に」には文字列が必要です" in r.stderr


IPV6 = """「通信」 を 読み込んで 使う

始めする とは 入出力手順
  受 とは 0 を 「::1」 に UDP開始した 結果
  受 を 5 で 待機時間設定する
  送 とは 0 を 「::1」 に UDP開始した 結果
  「やあ」 を 送 から 「::1」 に （受 を ポート取得した 結果） で UDP送信する
  便 とは 受 から UDP受信した 結果
  便 の 中身 を 表示する
  便 の 送り主 を 表示する
  「おう」 を 受 から 便 へ UDP返信する
  返事 とは 送 から UDP受信した 結果
  返事 の 中身 を 表示する
  口 とは 0 を 「::1」 に 待受開始した 結果
  客 とは 「::1」 に （口 を ポート取得した 結果） で 接続した 結果
  相手 とは 口 から 接続受付した 結果
  相手 を 相手アドレス取得した 結果 を 表示する
始めする
"""


@pytest.mark.skipif(not _ipv6_works(), reason="この機械では IPv6 が使えません")
@pytest.mark.parametrize("kind", KINDS)
def test_IPv6の口(kind, tmp_path):
    r = run(IPV6, kind, tmp_path)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "やあ\n::1\nおう\n::1\n"

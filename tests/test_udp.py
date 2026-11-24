"""「通信」の UDP(UDP開始する・UDP送信する・UDP受信する・UDP返信する)を、インタプリタとコンパイルしたもので確かめる"""

import pathlib
import socket
import subprocess
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import suru_compile  # noqa: E402

KINDS = ["インタプリタ", "コンパイル"]
DIR = ROOT / "examples" / "通信"


def run(src: str, kind: str, tmp_path: pathlib.Path, stdin: str = "") -> subprocess.CompletedProcess:
    path = tmp_path / "prog.suru"
    path.write_text(src, encoding="utf-8")
    return subprocess.run(command(path, kind, tmp_path), input=stdin, capture_output=True, text=True, timeout=60)


def command(path: pathlib.Path, kind: str, tmp_path: pathlib.Path) -> list[str]:
    if kind == "インタプリタ":
        return [sys.executable, str(ROOT / "suru.py"), str(path)]
    if suru_compile.find_cc() is None:
        pytest.skip("clang がありません")
    ll = tmp_path / (path.stem + ".ll")
    ll.write_text(suru_compile.compile_source(path.read_text(encoding="utf-8"), str(path.parent)), encoding="utf-8")
    exe = tmp_path / path.stem
    suru_compile.build(str(ll), str(exe))
    return [str(exe)]


def peer() -> tuple[socket.socket, int]:
    """Python の UDP の相手(127.0.0.1 の空いているポート)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(10)
    return s, s.getsockname()[1]


# 相手に送って、返事を文字列とバイト列で受け取る
SEND_RECV = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

始めする とは 入出力手順
  口 とは 0 を 通信内のUDP開始した 結果
  口 を 10 で 通信内の待機時間設定する
  「こんにちは」 を 口 から 「localhost」 に PORT で 通信内のUDP送信した 結果 を 表示する
  （（0 から 255 を 範囲にする） を バイト列組立する） を 口 から 「127.0.0.1」 に PORT で 通信内のUDPバイト列送信した 結果 を 表示する
  便 とは 口 から 通信内のUDP受信した 結果
  便 の 中身 を 表示する
  便 の 送り主 を 表示する
  （便 の ポート） = PORT を 表示する
  便2 とは 口 から 通信内のUDPバイト列受信した 結果
  便2 の 中身 を バイト長にして 表示する
  口 を 通信内の切断する
始めする
"""


@pytest.mark.parametrize("kind", KINDS)
def test_送って受け取る(kind, tmp_path):
    s, port = peer()
    got = []

    def answer() -> None:
        with s:
            for _ in range(2):
                data, addr = s.recvfrom(65536)
                got.append(data)
                s.sendto("返事:".encode("utf-8") + data, addr)

    t = threading.Thread(target=answer, daemon=True)
    t.start()
    r = run(SEND_RECV.replace("PORT", str(port)), kind, tmp_path)
    t.join(10)
    assert r.returncode == 0, r.stderr
    assert got == ["こんにちは".encode("utf-8"), bytes(range(256))]
    assert r.stdout == "15\n256\n返事:こんにちは\n127.0.0.1\n真\n263\n"


# 受け取った便りに、返信する で答える(送り主のポートへ)
REPLY = """「通信」 を 読み込んで 使う

始めする とは 入出力手順
  口 とは PORT を UDP開始した 結果
  「待受中」 を 表示する
  便 とは 口 から UDP受信した 結果
  「受け取りました: 」 + （便 の 中身） を 表示する
  「やあ」 を 口 から 便 へ UDP返信する
  便2 とは 口 から UDPバイト列受信した 結果
  （便2 の 中身） を 口 から 便2 へ UDPバイト列返信する
  口 を 切断する
始めする
"""


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.parametrize("kind", KINDS)
def test_返信する(kind, tmp_path):
    port = free_udp_port()
    path = tmp_path / "prog.suru"
    path.write_text(REPLY.replace("PORT", str(port)), encoding="utf-8")
    p = subprocess.Popen(command(path, kind, tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline() == "待受中\n"
        s, _ = peer()
        with s:
            s.sendto("はじめまして".encode("utf-8"), ("127.0.0.1", port))
            assert s.recvfrom(65536)[0] == "やあ".encode("utf-8")
            s.sendto(b"\x00\xff\x80", ("127.0.0.1", port))
            assert s.recvfrom(65536)[0] == b"\x00\xff\x80"
        assert p.wait(10) == 0
        assert p.stdout.read() == "受け取りました: はじめまして\n"
    finally:
        p.kill()


# 時間切れと、引けないホストは実行時エラー(試行する で受け止める)
ERRORS = """「通信」 を 読み込んで 使う

始めする とは 入出力手順
  口 とは 0 を UDP開始した 結果
  口 を 0.2 で 待機時間設定する
  （口 から UDP受信する） を 試行した 結果 を 表示する
  （「a」 を 口 から 「no-such-host.invalid」 に 9 で UDP送信する） を 試行した 結果 を 表示する
  口 を 切断する
  （「a」 を 口 から 「localhost」 に 9 で UDP送信する） を 試行した 結果 を 表示する
  （70000 を UDP開始する） を 試行した 結果 を 表示する
始めする
"""


@pytest.mark.parametrize("kind", KINDS)
def test_失敗は実行時エラー(kind, tmp_path):
    r = run(ERRORS, kind, tmp_path)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0].startswith("（理由 は 「「UDPバイト列受信する」で通信に失敗しました(")
    assert lines[1].startswith("（理由 は 「「UDPバイト列送信する」で通信に失敗しました(")
    assert "は開いているUDPの口ではありません" in lines[2]
    assert "「70000」はポートの番号ではありません" in lines[3]


def test_受け取った中身の型(tmp_path):
    # UDP受信する の中身は文字列、UDPバイト列受信する の中身はバイト列
    src = "「通信」 を 読み込んで 使う\nf とは 手順\n  便 とは 1 から UDP受信した 結果\n  （便 の 中身） + 1 を 結果にする\n"
    r = run(src, "インタプリタ", tmp_path)
    assert r.returncode == 1
    assert "文字列" in r.stderr


def with_port(path: pathlib.Path, port: int, tmp_path: pathlib.Path) -> pathlib.Path:
    src = path.read_text(encoding="utf-8")
    assert "ポート とは 9001\n" in src
    out = tmp_path / path.name
    out.write_text(src.replace("ポート とは 9001\n", f"ポート とは {port}\n"), encoding="utf-8")
    return out


@pytest.mark.parametrize("kind", KINDS)
def test_UDPのエコーサーバーとクライアント(kind, tmp_path):
    port = free_udp_port()
    server = subprocess.Popen(command(with_port(DIR / "UDPエコーサーバー.suru", port, tmp_path), kind, tmp_path),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert server.stdout.readline() == f"UDP の ポート {port} で待っています\n"
        r = subprocess.run(command(with_port(DIR / "UDPエコークライアント.suru", port, tmp_path), kind, tmp_path),
                           input="こんにちは\nする です\n", capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert r.stdout == f"localhost:{port} へ送ります\n> < こんにちは\n> < する です\n> \n"
        line = server.stdout.readline()
        assert line.startswith("127.0.0.1:") and line.endswith(" から こんにちは\n")
    finally:
        server.kill()
        server.wait()


def test_UDPのクライアントは返事がなければそう表示する(tmp_path):
    port = free_udp_port()  # だれも待っていない
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(with_port(DIR / "UDPエコークライアント.suru", port, tmp_path))],
                       input="もしもし\n", capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"localhost:{port} へ送ります\n> (返事がありません)\n> \n"

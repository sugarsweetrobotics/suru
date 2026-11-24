"""examples/通信/ のエコーサーバーとエコークライアントを、本当につないで確かめる(インタプリタとコンパイルしたもの)"""

import pathlib
import socket
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import suru_compile  # noqa: E402
from net_helper import free_port  # noqa: E402

DIR = ROOT / "examples" / "通信"
SERVER = DIR / "エコーサーバー.suru"
CLIENT = DIR / "エコークライアント.suru"


def with_port(path: pathlib.Path, port: int, tmp_path: pathlib.Path) -> pathlib.Path:
    """例のポート 9000 を空いているポートに変えた写しを作る"""
    src = path.read_text(encoding="utf-8")
    assert "ポート とは 9000\n" in src
    out = tmp_path / path.name
    out.write_text(src.replace("ポート とは 9000\n", f"ポート とは {port}\n"), encoding="utf-8")
    return out


def command(path: pathlib.Path, compiled: bool, tmp_path: pathlib.Path) -> list[str]:
    if not compiled:
        return [sys.executable, str(ROOT / "suru.py"), str(path)]
    ll = tmp_path / (path.stem + ".ll")
    ll.write_text(suru_compile.compile_source(path.read_text(encoding="utf-8"), str(path.parent)), encoding="utf-8")
    exe = tmp_path / path.stem
    suru_compile.build(str(ll), str(exe))
    return [str(exe)]


def connect(port: int) -> socket.socket:
    for _ in range(100):
        try:
            return socket.create_connection(("127.0.0.1", port), timeout=10)
        except ConnectionRefusedError:
            time.sleep(0.1)
    raise AssertionError("サーバーが待ち受けません")


@pytest.mark.parametrize("compiled", [False, True], ids=["インタプリタ", "コンパイル"])
def test_エコーサーバーとクライアント(compiled, tmp_path):
    if compiled and suru_compile.find_cc() is None:
        pytest.skip("clang がありません")
    port = free_port()
    server = subprocess.Popen(command(with_port(SERVER, port, tmp_path), compiled, tmp_path),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert server.stdout.readline() == f"ポート {port} で待っています\n"
        # 1人目がつないだままでも、2人目と話せる(接続ごとにスレッド)
        with connect(port) as first, first.makefile("rb") as f1:
            r = subprocess.run(command(with_port(CLIENT, port, tmp_path), compiled, tmp_path),
                               input="こんにちは\nする で 話す\n", capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, r.stderr
            assert r.stdout == (f"localhost:{port} につなぎました\n"
                                "> < こんにちは\n> < する で 話す\n> \n")
            first.sendall("1人目\n".encode("utf-8"))
            assert f1.readline().decode("utf-8") == "1人目\n"
    finally:
        server.kill()
        server.wait()


def test_サーバーがいないとエラー(tmp_path):
    port = free_port()
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(with_port(CLIENT, port, tmp_path))],
                       input="", capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "Connection refused" in r.stderr

"""Windows(MinGW-w64)向けの実行時ライブラリ。

clang で x86_64-w64-mingw32 向けに作れるか(MinGW-w64 のヘッダーとライブラリが要る)を確かめ、
wine があれば、作った .exe を動かして Linux・macOS と同じ表示になるかも確かめる。
どちらもなければ飛ばす(Ubuntu では apt install mingw-w64 wine)。
"""
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TARGET = "x86_64-w64-mingw32"


def _can_cross():
    if not shutil.which("clang"):
        return False
    r = subprocess.run(["clang", f"--target={TARGET}", "-x", "c", "-c", "-", "-o", os.devnull],
                       input="#include <winsock2.h>\n#include <pthread.h>\nint x;\n", capture_output=True, text=True)
    return r.returncode == 0


CROSS = _can_cross()
WINE = shutil.which("wine")
pytestmark = pytest.mark.skipif(not CROSS, reason="clang で MinGW-w64 向けに作れない(apt install mingw-w64)")


@pytest.fixture(scope="module")
def rt_obj(tmp_path_factory):
    out = tmp_path_factory.mktemp("rt") / "suru_rt.o"
    r = subprocess.run(["clang", f"--target={TARGET}", "-O1", "-w", "-c", str(ROOT / "runtime" / "suru_rt.c"), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _exe(tmp_path, rt_obj, src, name="prog"):
    prog = tmp_path / f"{name}.suru"
    prog.write_text(src, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), "--ll", str(prog)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    exe = tmp_path / f"{name}.exe"
    r = subprocess.run(["clang", f"--target={TARGET}", "-O1", "-w", str(tmp_path / f"{name}.ll"), str(rt_obj),
                        "-static", "-lpthread", "-lws2_32", "-o", str(exe)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


@pytest.fixture(scope="module")
def wine_env(tmp_path_factory):
    # 手元の環境の変数で wine が止まることがあるので、最小の変数で動かす。設定(~/.wine)は初めに1回だけ作る
    home = tmp_path_factory.mktemp("wine-home")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "WINEDEBUG": "-all", "LANG": "C.UTF-8"}
    subprocess.run(["wineboot", "-i"], env=env, capture_output=True, timeout=300)
    subprocess.run(["wineserver", "-w"], env=env, capture_output=True, timeout=300)
    return env


def _wine(env, exe, timeout=180):
    r = subprocess.run(["wine", str(exe)], capture_output=True, env=env, timeout=timeout)
    return r.returncode, r.stdout.decode("utf-8").replace("\r\n", "\n")


def test_実行時ライブラリを_Windows_向けに作れる(rt_obj):
    assert rt_obj.stat().st_size > 0


BASIC = """「標準」 を 読み込んで 使う
数 を 階乗する は 数 を 返す
0 を 階乗する とは 1 です
n を 階乗する とは n * （n - 1 を 階乗する） です
20 を 階乗して 表示します
「こんにちは、世界」 を 表示します
（（1 から 100000 を 範囲にする） を 加算する） を 表示します
"""

THREADS = """「スレッド」 を 読み込んで 使う
「標準」 を 読み込んで 使う
数 を 重く計算する は 数 を 返す
n を 重く計算する とは （（1 から n を 範囲にする） の それぞれ を 文字列化する） の 長さ です
始める とは 以下の手順です
  a とは （100000 を 重く計算して 結果にする） を 並行開始した 結果 です
  b とは （100000 を 重く計算して 結果にする） を 並行開始した 結果 です
  a を 合流してから 表示します
  b を 合流してから 表示します
  以上です
始める
"""

DEEP = """数 を 深く数えする は 数 を 返す
0 を 深く数えする とは 0 です
n を 深く数えする とは 1 + （n - 1 を 深く数えする） です
1000000 を 深く数えして 表示します
"""


@pytest.mark.skipif(not WINE, reason="wine がない")
@pytest.mark.parametrize("src,want", [
    (BASIC, "2432902008176640000\nこんにちは、世界\n5000050000\n"),
    (THREADS, "100000\n100000\n"),
    (DEEP, "1000000\n"),
], ids=["基本", "スレッド", "深い再帰"])
def test_Windows_の_exe_が_Linux_と同じに動く(tmp_path, rt_obj, wine_env, src, want):
    exe = _exe(tmp_path, rt_obj, src)
    assert _wine(wine_env, exe) == (0, want)


@pytest.mark.skipif(not WINE, reason="wine がない")
def test_Windows_の_exe_で_TCP_のエコーサーバーが動く(tmp_path, rt_obj, wine_env):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    src = (ROOT / "examples" / "通信" / "エコーサーバー.suru").read_text(encoding="utf-8")
    src = src.replace("ポート とは 9000", f"ポート とは {port}")
    exe = _exe(tmp_path, rt_obj, src, "サーバー")
    proc = subprocess.Popen(["wine", str(exe)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=wine_env)
    try:
        deadline = time.time() + 120
        while True:
            try:
                c = socket.create_connection(("127.0.0.1", port), timeout=5)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.5)
        with c:
            c.sendall("こんにちは\n2行目\n".encode())
            got = b""
            while got.count(b"\n") < 2:
                k = c.recv(1000)
                if not k:
                    break
                got += k
        assert got.decode() == "こんにちは\n2行目\n"
    finally:
        proc.kill()
        proc.wait()


# --- 段階2: suruc・kumu・suru --翻訳 が SURU_TARGET で Windows の .exe を作る ---

HELLO = "「こんにちは、窓」 を 表示します\n"


@pytest.fixture(scope="module")
def go_tools(tmp_path_factory):
    if not shutil.which("go"):
        pytest.skip("go がない")
    d = tmp_path_factory.mktemp("go")
    for name in ("suruc", "kumu"):
        subprocess.run(["go", "build", "-o", str(d / name), f"./cmd/{name}"], cwd=ROOT, check=True)
    return d


def _cross_env(tmp_path):
    env = dict(os.environ, SURU_TARGET=TARGET, XDG_CACHE_HOME=str(tmp_path / "cache"))
    env.pop("SURU_LINT_INTERP", None)
    return env


def _has_manifest(exe):
    # UTF-8 のマニフェストは windres があるときだけ埋め込む
    objdump = shutil.which(f"{TARGET}-objdump")
    if not objdump or not shutil.which(f"{TARGET}-windres"):
        return True
    r = subprocess.run([objdump, "-h", str(exe)], capture_output=True, text=True)
    return ".rsrc" in r.stdout


def test_suruc_で_exe_を作る(tmp_path, go_tools, wine_env):
    src = tmp_path / "窓.suru"
    src.write_text(HELLO, encoding="utf-8")
    r = subprocess.run([str(go_tools / "suruc"), str(src), "-o", str(tmp_path / "窓")],
                       capture_output=True, text=True, env=_cross_env(tmp_path))
    assert r.returncode == 0, r.stderr
    exe = tmp_path / "窓.exe"
    assert exe.exists() and not (tmp_path / "窓").exists()
    assert _has_manifest(exe)
    if WINE:
        assert _wine(wine_env, exe) == (0, "こんにちは、窓\n")


def test_suru_の翻訳で_exe_を作る(tmp_path, wine_env):
    src = tmp_path / "窓.suru"
    src.write_text(HELLO, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--翻訳", str(src)],
                       capture_output=True, text=True, env=_cross_env(tmp_path))
    assert r.returncode == 0, r.stderr
    exe = tmp_path / "窓.exe"
    assert exe.exists()
    assert _has_manifest(exe)
    if WINE:
        assert _wine(wine_env, exe) == (0, "こんにちは、窓\n")


def test_kumu_で_exe_を作る(tmp_path, go_tools, wine_env):
    env = _cross_env(tmp_path)
    r = subprocess.run([str(go_tools / "kumu"), "新規", "窓あけ"], cwd=tmp_path, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    proj = tmp_path / "窓あけ"
    (proj / "本体.suru").write_text(HELLO, encoding="utf-8")
    r = subprocess.run([str(go_tools / "kumu"), "作る"], cwd=proj, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    exe = proj / "出力" / "窓あけ.exe"
    assert exe.exists()
    if WINE:
        assert _wine(wine_env, exe) == (0, "こんにちは、窓\n")


def test_点検は_SURU_TARGET_があっても手元向けに作る(tmp_path, go_tools):
    src = tmp_path / "窓.suru"
    src.write_text(HELLO, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--点検", str(src)],
                       capture_output=True, text=True, env=_cross_env(tmp_path))
    assert r.returncode == 0, r.stderr
    built = list((tmp_path / "cache" / "suru").glob("点検-*"))
    assert built and not any(p.suffix == ".exe" for p in built)

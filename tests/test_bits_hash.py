"""ビット演算・バイト列排他和(標準)、Base64(標準)、SHA-1(lib/ハッシュ.suru)、通信内の待機時間設定する のテスト。
インタプリタとコンパイルしたバイナリで同じ結果になるかを確かめます。"""

import base64
import hashlib
import hmac
import pathlib
import socket
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

BITS = ('「標準」 を 読み込んで 使う\n'
        '12 を 10 で ビット積にする\n12 を 10 で ビット和にする\n12 を 10 で 排他的論理和にする\n'
        '-1 を 255 で ビット積にする\n-8 を 3 で 排他的論理和にする\n'
        '1 を 40 で 左シフトする\n3 を 0 で 左シフトする\n1024 を 3 で 右シフトする\n-8 を 1 で 右シフトする\n'
        '4294967295 を 4294967295 で 排他的論理和にする\n'
        '（「abcd」 を バイト列にする） を （「  」 を バイト列にする） で バイト列排他和にして 文字列にする\n'
        '（（（1 と 2 と 3 と 250 と 255） を バイト列組立する） を （（7 と 1） を バイト列組立する） で バイト列排他和にする） を 数列にする\n'
        '（（空 を バイト列組立する） を （「k」 を バイト列にする） で バイト列排他和にする） を バイト長にする\n')

BITS_OUT = '8\n14\n6\n255\n-5\n1099511627776\n3\n128\n-4\n0\nABCD\n（6 と 3 と 4 と 251 と 248）\n0\n'

BASE64 = ('「標準」 を 読み込んで 使う\n'
          '（バイト列 と 文字列） の 成否 を 見るする は 文字列\n'
          '（b の 成功） を 見るする とは 「成功: 」 + （b を 文字列にする）\n'
          '（e の 失敗） を 見るする とは 「失敗: 」 + e\n'
          '「」 を バイト列にして Base64符号化する\n「f」 を バイト列にして Base64符号化する\n'
          '「fo」 を バイト列にして Base64符号化する\n「foo」 を バイト列にして Base64符号化する\n'
          '「foobar」 を バイト列にして Base64符号化する\n「あいう」 を バイト列にして Base64符号化する\n'
          '（（251 と 255 と 191） を バイト列組立する） を Base64符号化する\n'
          '「Zm9vYmFy」 を Base64復号して 見るする\n「Zm9vYg==」 を Base64復号して 見るする\n'
          '「 Zm9vYg 」 を Base64復号して 見るする\n「44GC44GE44GG」 を Base64復号して 見るする\n'
          '「」 を Base64復号して 見るする\n'
          '（「-_-_」 を Base64復号して 取出して 数列にする） = （「+/+/」 を Base64復号して 取出して 数列にする）\n'
          '「Zm9v!」 を Base64復号して 見るする\n「Zm9vY」 を Base64復号して 見るする\n')

BASE64_OUT = ('\nZg==\nZm8=\nZm9v\nZm9vYmFy\n44GC44GE44GG\n+/+/\n'
              '成功: foobar\n成功: foob\n成功: foob\n成功: あいう\n成功: \n真\n'
              '失敗: Base64 で使えない文字があります\n失敗: Base64 の長さが合いません\n')

LONG = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
SAMPLES = ["", "abc", LONG, "a" * 55, "a" * 56, "a" * 64, "あいうえお" * 30]
SHA1 = ('「標準」 を 読み込んで 使う\n「ハッシュ」 を 読み込む\n'
        + "".join(f'「{s}」 を バイト列にして ハッシュ内のSHA1にして ハッシュ内の十六進表記にする\n' for s in SAMPLES)
        + '「dGhlIHNhbXBsZSBub25jZQ==258EAFA5-E914-47DA-95CA-C5AB0DC85B11」 を バイト列にして ハッシュ内のSHA1にして Base64符号化する\n'
        + '（（0 と 15 と 16 と 255） を バイト列組立する） を ハッシュ内の十六進表記にする\n')
SHA1_OUT = ("".join(hashlib.sha1(s.encode()).hexdigest() + "\n" for s in SAMPLES)
            + "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\n000f10ff\n")

SHA256 = ('「標準」 を 読み込んで 使う\n「ハッシュ」 を 読み込む\n'
          + "".join(f'「{s}」 を バイト列にして ハッシュ内のSHA256にして ハッシュ内の十六進表記にする\n' for s in SAMPLES))
SHA256_OUT = "".join(hashlib.sha256(s.encode()).hexdigest() + "\n" for s in SAMPLES)

HMAC_CASES = [("Jefe", "what do ya want for nothing?"), ("", ""), ("鍵" * 30, "長い鍵(64 バイトより長い)"), ("k" * 64, LONG)]
HMAC = ('「標準」 を 読み込んで 使う\n「ハッシュ」 を 読み込む\n'
        + "".join(f'（「{m}」 を バイト列にする） を （「{k}」 を バイト列にする） で ハッシュ内のHMACSHA256にして ハッシュ内の十六進表記にする\n'
                  for k, m in HMAC_CASES))
HMAC_OUT = "".join(hmac.new(k.encode(), m.encode(), hashlib.sha256).hexdigest() + "\n" for k, m in HMAC_CASES)


def run_both(source: str, tmp_path: pathlib.Path) -> list[str]:
    """インタプリタとバイナリの出力"""
    src = tmp_path / "prog.suru"
    src.write_text(source, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    outs = [r.stdout]
    if suru_compile.find_cc() is not None:
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "prog")], check=True)
        r = subprocess.run([str(tmp_path / "prog")], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        outs.append(r.stdout)
    return outs


@pytest.mark.parametrize("source, want", [(BITS, BITS_OUT), (BASE64, BASE64_OUT), (SHA1, SHA1_OUT),
                                            (SHA256, SHA256_OUT), (HMAC, HMAC_OUT)],
                         ids=["ビット演算", "Base64", "SHA-1", "SHA-256", "HMAC-SHA256"])
def test_インタプリタとバイナリで同じ(source, want, tmp_path):
    for out in run_both(source, tmp_path):
        assert out == want


def test_Base64はPythonと同じ(tmp_path):
    data = bytes(range(256)) + bytes(range(255, -1, -3))
    nums = " と ".join(str(b) for b in data)
    source = (f'「標準」 を 読み込んで 使う\nb とは （{nums}） を バイト列組立する\n'
              'b を Base64符号化する\n（b を Base64符号化して Base64復号して 取出して 数列にする） = （b を 数列にする）\n')
    want = base64.b64encode(data).decode() + "\n真\n"
    for out in run_both(source, tmp_path):
        assert out == want


@pytest.mark.parametrize("prog, err", [
    ("1 を 64 で 左シフトする", "「左シフトする」の「で」は 0 から 63 までです"),
    ("1 を -1 で 右シフトする", "「右シフトする」の「で」は 0 から 63 までです"),
    ("1.5 を 1 で ビット積にする", "「ビット積にする」の「を」は整数でなければなりません"),
    ("（「a」 を バイト列にする） を （空 を バイト列組立する） で バイト列排他和にする", "鍵)が空のバイト列です"),
])
def test_使い方の誤り(prog, err, tmp_path):
    src = tmp_path / "prog.suru"
    src.write_text("「標準」 を 読み込んで 使う\n" + prog + "\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and err in r.stderr
    if suru_compile.find_cc() is None:
        return
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "prog")], check=True)
    r = subprocess.run([str(tmp_path / "prog")], capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and err in r.stderr


# 受け付けた接続は5秒で見切るが、待機時間設定する で変えられる
TIMEOUT_SERVER = '''「標準」 を 読み込んで 使う
「通信」 を 読み込む
数 を 一行表示する は 無 の 動作
c を 一行表示する とは 手順
  行 とは c から 通信内の行受信した 結果
  行 を 表示する
始めする とは 手順
  口 とは {port} を 通信内の待受開始した 結果
  「待受」 を 表示する
  c とは 口 から 通信内の接続受付した 結果
  c を 0.3 で 通信内の待機時間設定する
  （c を 一行表示する） を （「時間切れ」 を 表示する） で 試行する
  c を 0 で 通信内の待機時間設定する
  c から 通信内の行受信した 結果 を 空白除去して 表示する
  c を 通信内の切断する
始めする
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_listen(proc: subprocess.Popen) -> None:
    assert proc.stdout.readline().strip() == "待受"


@pytest.mark.parametrize("compiled", [False, True], ids=["インタプリタ", "バイナリ"])
def test_待機時間設定する(compiled, tmp_path):
    port = free_port()
    src = tmp_path / "srv.suru"
    src.write_text(TIMEOUT_SERVER.format(port=port), encoding="utf-8")
    if compiled:
        if suru_compile.find_cc() is None:
            pytest.skip("clang がありません")
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "srv")], check=True)
        cmd = [str(tmp_path / "srv")]
    else:
        cmd = [sys.executable, str(ROOT / "suru.py"), str(src)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        wait_listen(proc)
        with socket.create_connection(("127.0.0.1", port)) as s:
            start = time.monotonic()
            assert proc.stdout.readline().strip() == "時間切れ"
            assert time.monotonic() - start < 3
            time.sleep(6)  # 0 にしたので、5秒を過ぎても待つ
            s.sendall("届いた\n".encode())
            out, err = proc.communicate(timeout=30)
        assert out == "届いた\n", err
    finally:
        proc.kill()

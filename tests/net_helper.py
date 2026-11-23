"""通信のテストで使う、する のサーバーとお客さん(テストではない)"""

import pathlib
import shutil
import socket

# HTTP のテストで使うサーバーのライブラリ。suru-lang/http の HTTP.suru の写しです(本体の標準ライブラリではありません)。
# 通信・スレッド・GC・試行する を、本物の使い方で確かめるために置いています。
HTTP_DIR = pathlib.Path(__file__).resolve().parent / "http"


def put_http(d: pathlib.Path) -> None:
    """フォルダ d に HTTP.suru を置く(d のプログラムが「HTTP」を読み込めるように)"""
    shutil.copy(HTTP_DIR / "HTTP.suru", d / "HTTP.suru")

# 3回答えて待受口を閉じるサーバー。1行目と、2行目のバイト数だけの本文を受け取り、まとめて返す
SERVER = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

口 と n を 答え続けする とは 手順
  接続 とは 口 から 通信内の接続受付した 結果
  行 とは 接続 から 通信内の行受信した 結果
  長さ とは 接続 から 通信内の行受信した 結果 を 数値にする
  本文 とは 接続 から 長さ を 通信内の受信した 結果
  返事 とは （行 を 空白除去する） + 「:」 + 本文 + 「:」 + （本文 を バイト数にして 文字列化する） + 改行
  返事 を 接続 へ 通信内の送信する
  接続 を 通信内の切断する
  もし n が 1 ならば 口 を 通信内の切断する そうでなければ 口 と （n - 1） を 答え続けする

始めする とは 手順
  口 とは PORT を 通信内の待受開始した 結果
  「待受中」 を 表示する
  口 と 3 を 答え続けする
始めする
"""

# 1件だけ受け付けて、0〜255 のバイト列と「あ」を送って閉じるサーバー
BYTES_SERVER = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

始めする とは 手順
  口 とは PORT を 通信内の待受開始した 結果
  「待受中」 を 表示する
  接続 とは 口 から 通信内の接続受付した 結果
  n とは （（0 から 255 を 範囲にする） を バイト列組立する） を 接続 へ 通信内のバイト列送信した 結果
  「あ」 を 接続 へ 通信内の送信する
  接続 を 通信内の切断する
  口 を 通信内の切断する
  n を 表示する
始めする
"""

BYTES_EXPECTED = bytes(range(256)) + "あ".encode("utf-8")


def read_all(port: int) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        out = b""
        while chunk := s.recv(65536):
            out += chunk
    return out


REQUESTS = [("こんにちは", "日本"), ("2番目", ""), ("three", "abc" * 1000)]


# こちらからつなぐお客さん。1行送り、相手が閉じるまでの行を表示する
CLIENT = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

接続 を 全部表示する とは 手順
  行 とは 接続 から 通信内の行受信した 結果
  もし 行 が 「」 ならば 接続 を 通信内の切断する そうでなければ 行 を 接続 で 表示続けする

行 を 接続 で 表示続けする とは 手順
  行 を 空白除去して 表示する
  接続 を 全部表示する

始めする とは 手順
  接続 とは 「localhost」 に PORT で 通信内の接続した 結果
  「こんにちは」 + 改行 を 接続 へ 通信内の送信する
  接続 を 全部表示する
始めする
"""


def answer_once(port: int) -> "threading.Thread":
    """1回だけ答えるサーバーを別スレッドで始める(受け取った行を返し、2行目を足して閉じる)"""
    import threading

    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen()

    def serve() -> None:
        with s:
            c, _ = s.accept()
            with c, c.makefile("rb") as f:
                line = f.readline()
                c.sendall(b"got:" + line + "二行目\n".encode("utf-8"))

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return t


CLIENT_OUT = ["got:こんにちは", "二行目"]

# 5 バイトずつバイト列で受け取ってからつなぐ(文字の途中で切れても壊れない)
CLIENT_BYTES = """「標準」 を 読み込んで 使う
「通信」 を 読み込む

接続 を 累 に 全部読込する とは 手順
  片 とは 接続 から 5 を 通信内のバイト列受信した 結果
  もし （片 を バイト長にする） が 0 ならば 累 を バイト列組立して 結果にする
  そうでなければ 接続 を 累 + （片 を 数列にする） に 全部読込する

始めする とは 手順
  接続 とは 「localhost」 に PORT で 通信内の接続した 結果
  「こんにちは」 + 改行 を 接続 へ 通信内の送信する
  全体 とは 接続 を 空 に 全部読込した 結果
  全体 を 文字列にして 表示する
  接続 を 通信内の切断する
始めする
"""
CLIENT_BYTES_OUT = ["got:こんにちは\n二行目\n"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ask(port: int, head: str, body: str) -> str:
    data = body.encode("utf-8")
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(f"{head}\r\n{len(data)}\r\n".encode("utf-8") + data)
        out = b""
        while chunk := s.recv(65536):
            out += chunk
    return out.decode("utf-8")


def expected(head: str, body: str) -> str:
    return f"{head}:{body}:{len(body.encode('utf-8'))}\n"


# HTTP のサーバー(純粋な関数で答える / 動作で答える)
HTTP_SERVER = """「HTTP」 を 読み込む

要求 を 案内する とは
  もし 要求 の 道 が
    「/」 ならば 「こんにちは」 を HTTP内の本文応答する
    「/break」 ならば 空 の 先頭 を HTTP内の本文応答する
    そうでなければ 404 で 「見つかりません: 」 + 要求 の 道 を HTTP内の状態応答する

PORT を 案内すること で HTTP内の待受する
"""

HTTP_ACTION_SERVER = """「HTTP」 を 読み込む

要求 を 記録する とは 手順
  要求 の 方法 + 「 」 + 要求 の 道 を 表示する
  （要求 の 本文 + 「/」 + （要求 から 「X-Name」 を HTTP内の見出し値にする）） を HTTP内の本文応答して 結果にする

PORT を 記録すること で HTTP内の動作待受する
"""


# フォルダを配るサーバー(Go 版と Python 版で同じ IR になるかを見る)
HTTP_STATIC_SERVER = """「HTTP」 を 読み込む
「標準」 を 読み込んで 使う

要求 を 案内する とは
  もし 要求 の 道 が 「/api/」 で 先頭一致である ならば （「api」 を HTTP内の本文応答して 結果にする）
  そうでなければ 「/static」 から 「public」 を 要求 で HTTP内の前置付配信する

PORT を 案内すること で HTTP内の動作待受する
"""


def http(port: int, path: str = "/", body: str | None = None, headers: dict | None = None) -> tuple:
    """(状態, 見出しの辞書, 本文) を返す"""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else body.encode("utf-8"),
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8")


def wait_http(port: int, timeout: float = 10) -> None:
    """サーバーが答えるまで「/」を聞き直す(つないで何も送らずに切ると、まだ止まるサーバーがあるため)"""
    import time

    end = time.time() + timeout
    while True:
        try:
            http(port)
            return
        except OSError:
            if time.time() > end:
                raise
            time.sleep(0.05)


def abuse(port: int) -> None:
    """サーバーを困らせる: 関数のエラー、何も送らずに切る、途中で切る、すぐ RST、壊れた要求"""
    assert http(port, "/break")[::2] == (500, "Internal Server Error")
    socket.create_connection(("127.0.0.1", port)).close()
    with socket.create_connection(("127.0.0.1", port)) as s:
        s.sendall(b"GET / HTTP/1.1\r\nContent-Length: 100\r\n\r\nab")
    s = socket.create_connection(("127.0.0.1", port))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
    s.sendall(b"GET / HTTP/1.1\r\n\r\n")
    s.close()
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(b"\xff\xfe garbage\r\nContent-Length: abc\r\n\r\n")
        assert s.recv(100).startswith(b"HTTP/1.1 500 ")

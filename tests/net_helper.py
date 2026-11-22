"""通信のテストで使う、する のサーバーとお客さん(テストではない)"""

import socket

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

REQUESTS = [("こんにちは", "日本"), ("2番目", ""), ("three", "abc" * 1000)]


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

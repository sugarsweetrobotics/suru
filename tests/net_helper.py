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

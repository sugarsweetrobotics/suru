"""コンパイラ(suru_compile.py)のテスト: コンパイルしたバイナリの出力がインタプリタと同じになるか"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_compile  # noqa: E402

pytestmark = pytest.mark.skipif(suru_compile.find_cc() is None, reason="clang がありません")

INPUT = "3\n4\n5\n"


def compiled(source: str, tmp_path: pathlib.Path, base_dir: str = ".", stdin: str = INPUT) -> subprocess.CompletedProcess:
    ir = suru_compile.compile_source(source, base_dir)
    ll = tmp_path / "prog.ll"
    ll.write_text(ir, encoding="utf-8")
    exe = tmp_path / "prog"
    suru_compile.build(str(ll), str(exe))
    return subprocess.run([str(exe)], input=stdin, capture_output=True, text=True, timeout=60)


def interpreted(source: str, base_dir: str = ".", stdin: str = INPUT) -> str:
    lines = iter(stdin.splitlines())
    out: list[str] = []

    def read(prompt: str) -> str:
        out.append(prompt)
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    it = suru.Interpreter(out=lambda s: out.append(s + "\n"), read=read)
    it.ctx.base_dir = base_dir
    it.run(source, emit=lambda v: out.append(it.format(v) + "\n"))
    return "".join(out)


def same(source: str, tmp_path: pathlib.Path, base_dir: str = ".") -> str:
    r = compiled(source, tmp_path, base_dir)
    assert r.returncode == 0, r.stderr
    assert r.stdout == interpreted(source, base_dir)
    return r.stdout


EXAMPLES = sorted(p for p in (ROOT / "examples").glob("*.suru") if p.stem not in ("数学", "http"))  # http は待ち続ける


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_例のプログラムがインタプリタと同じ結果(path, tmp_path):
    same(path.read_text(encoding="utf-8"), tmp_path, str(path.parent))


PROGRAMS = {
    "部分適用と関数の値": """
a を b で 割る数にする とは a / b
f とは 10 を 割る数にすること
f を 2 に 適用する
（1 と 2 と 4） の それぞれ に （8 を 割る数にすること） を 適用する
（1 と 2 と 3） を 0 から 加算すること で 畳み込みする
""",
    "数の表示": """
10 / 4
1 / 3
2 ^ 0.5
2 ^ -1
7 % -3
-7 % 3
5.5 % 2
0.1 + 0.2
1e-7 * 1
「答えは」 + （3 を 文字列化する）
""",
    "組の更新と比較": """
点 とは 横 と 縦 の 組
p とは 3 と 4 の 点
横 は 10 の p
p が （3 と 4 の 点）
p が （縦 は 4 で 横 は 3 の 点）
（1 と 2 と 3） が （1 と 2 と 3）
""",
    "局所定義の相互再帰": """
n を 判定する とは
  x を 偶数判定する とは もし x == 0 ならば 真 そうでなければ x - 1 を 奇数判定する
  x を 奇数判定する とは もし x == 0 ならば 偽 そうでなければ x - 1 を 偶数判定する
  n を 偶数判定する
10 を 判定する
7 を 判定する
""",
    "性質と既定の実装": """
比較可能 という 性質 とは
  a と b を 比較する
  a と b を 大きい方にする とは
    もし （a と b を 比較する） > 0 ならば a そうでなければ b
点 とは 横 と 縦 の 組
点 は 比較可能
  a と b を 比較する とは a の 横 - b の 横
（1 と 2 の 点） と （3 と 0 の 点） を 大きい方にする
箱 とは 幅 と 奥 の 組
箱 は 表示可能
  b を 文字列化する とは （b の 幅 を 文字列化する） + 「×」 + （b の 奥 を 文字列化する）
（2 と 3 の 箱） と （4 と 5 の 箱）
""",
    "自分で作った連鎖可能": """
多分 とは 値 の 存在 か 欠如
多分 は 連鎖可能
  m を f で 連鎖する とは
    もし m が
      x の 存在 ならば f を x に 適用する
      欠如 ならば 欠如
  x を 結果にする とは x の 存在
x を 半分にする とは もし x % 2 == 0 ならば x / 2 の 存在 そうでなければ 欠如
8 の 存在 を 半分にすること で 連鎖して 半分にすること で 連鎖する
6 の 存在 を 半分にすること で 連鎖して 半分にすること で 連鎖する
手順（a とは 20 の 存在 を 半分にすること で 連鎖した 結果。a + 1 を 結果にする）。
""",
    "動作とリストの連鎖": """
（1と2と3）を（nを受け取って（nとn*10）を返すこと）で連鎖する。
nを三倍するとは、n*3。
（1と2）の結果を三倍する。
「a」を表示する。それから、「b」を表示する。
（「x」 と 「y」） の それぞれ を 表示して 実行する
""",
}

DEEP = """
n を 計数する とは もし n == 0 ならば 0 そうでなければ 1 + （n - 1 を 計数する）
100000 を 計数する
"""


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_いろいろなプログラム(name, tmp_path):
    same(PROGRAMS[name], tmp_path)


def test_深い再帰も動く(tmp_path):
    # インタプリタでは再帰が深すぎて止まる深さ
    assert compiled(DEEP, tmp_path).stdout == "100000\n"


def test_手順の最後で自分を呼ぶ繰り返し(tmp_path):
    src = "n を 数え上げする とは 手順\n  n を 表示する\n  もし n < 30000 ならば n + 1 を 数え上げする そうでなければ 「終わり」 を 表示する\n1 を 数え上げする\n"
    out = same(src, tmp_path)
    assert out.endswith("30000\n終わり\n")


def test_実行時のエラーはインタプリタと同じ文(tmp_path):
    src = "x とは 1 と 2\nx の 先頭\n空 の 先頭\n"
    r = compiled(src, tmp_path)
    assert r.returncode == 1
    assert r.stdout == "1\n"
    with pytest.raises(suru.SuruError) as e:
        suru.run(src)
    assert r.stderr.strip() == suru.format_error(e.value, src)


def test_整数が大きすぎるとエラー(tmp_path):
    r = compiled("2 ^ 70\n", tmp_path)
    assert r.returncode == 1
    assert "整数が大きすぎます" in r.stderr


def test_型の間違いはコンパイルしない(tmp_path):
    with pytest.raises(suru.SuruError):
        suru_compile.compile_source("1 + 「a」 を 加算する\n「a」 - 1\n")


def test_コマンドで実行ファイルができる(tmp_path):
    src = tmp_path / "やあ.suru"
    src.write_text("「やあ」 を 表示する\n", encoding="utf-8")
    exe = tmp_path / "やあ"
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--翻訳", str(src), "-o", str(exe)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert subprocess.run([str(exe)], capture_output=True, text=True).stdout == "やあ\n"
    assert not (tmp_path / "やあ.ll").exists()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang がありません")
def test_LLVM_IRだけを出す(tmp_path):
    src = tmp_path / "p.suru"
    src.write_text("1 + 2\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), "--ll", str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "define void @suru_main()" in (tmp_path / "p.ll").read_text(encoding="utf-8")


def test_バイト数と文字はインタプリタと同じ(tmp_path):
    src = "「標準」 を 読み込んで 使う\n「aあ」 を バイト数にする\n12354 を 文字にする\n「あ」 を 文字コードにする\n改行 の 長さ\n復帰改行 を バイト数にする\n"
    assert same(src, tmp_path) == "4\nあ\n12354\n1\n2\n"


def test_開いていない接続のエラーはインタプリタと同じ文(tmp_path):
    r = compiled("「通信」 を 読み込む\n5 を 通信内の切断する\n", tmp_path)
    assert r.returncode == 1 and "「5」は開いている待受口か接続ではありません" in r.stderr


def test_通信のサーバーをコンパイルして答えてもらう(tmp_path):
    from net_helper import REQUESTS, SERVER, ask, expected, free_port

    port = free_port()
    ir = suru_compile.compile_source(SERVER.replace("PORT", str(port)), ".")
    (tmp_path / "srv.ll").write_text(ir, encoding="utf-8")
    suru_compile.build(str(tmp_path / "srv.ll"), str(tmp_path / "srv"))
    p = subprocess.Popen([str(tmp_path / "srv")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline() == "待受中\n"  # 接続を待つ前に表示が出る
        for head, body in REQUESTS:
            assert ask(port, head, body) == expected(head, body)
        assert p.wait(10) == 0
    finally:
        p.kill()


@pytest.mark.parametrize("which", ["HTTP_SERVER", "HTTP_ACTION_SERVER"])
def test_HTTPのサーバーをコンパイルして答えてもらう(which, tmp_path):
    import net_helper as N

    port = N.free_port()
    ir = suru_compile.compile_source(getattr(N, which).replace("PORT", str(port)), ".")
    (tmp_path / "srv.ll").write_text(ir, encoding="utf-8")
    suru_compile.build(str(tmp_path / "srv.ll"), str(tmp_path / "srv"))
    p = subprocess.Popen([str(tmp_path / "srv")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        N.wait_http(port)
        if which == "HTTP_SERVER":
            assert N.http(port)[::2] == (200, "こんにちは")
            assert N.http(port, "/zz")[::2] == (404, "見つかりません: /zz")
        else:
            assert N.http(port, "/post", "本文です", {"X-Name": "taro"})[::2] == (200, "本文です/taro")
            for _ in range(100):  # 何件でも続けて答える
                assert N.http(port, "/", "x")[0] == 200
            assert p.poll() is None
    finally:
        p.kill()
    if which == "HTTP_ACTION_SERVER":
        assert "POST /post\n" in p.communicate()[0]


def test_試行するはインタプリタと同じ(tmp_path):
    src = "「標準」 を 読み込んで 使う\n" \
        "x を 壊すする とは 手順\n  「前」 を 表示する\n  空 の 先頭 を 表示する\n" \
        "（1 を 壊すする） を （「代わり」 を 表示する） で 試行してから 表示する\n" \
        "（1 を 壊すする） を （「pure」 を 結果にする） で 試行してから 表示する\n"
    assert same(src, tmp_path) == "前\n代わり\n代わり\n前\npure\n"
    assert compiled(src, tmp_path).stderr.count("空のリストに「先頭」はありません") == 2


def test_HTTPのサーバーは失敗しても何も送らない相手がいても止まらない(tmp_path):
    import socket
    import time

    import net_helper as N

    port = N.free_port()
    ir = suru_compile.compile_source(N.HTTP_SERVER.replace("PORT", str(port)), ".")
    (tmp_path / "srv.ll").write_text(ir, encoding="utf-8")
    suru_compile.build(str(tmp_path / "srv.ll"), str(tmp_path / "srv"))
    p = subprocess.Popen([str(tmp_path / "srv")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        N.wait_http(port)
        N.abuse(port)
        idle = socket.create_connection(("127.0.0.1", port))  # つないだまま何も送らない
        t = time.time()
        assert N.http(port)[::2] == (200, "こんにちは")  # 5秒で見切って次に答える
        assert 4 < time.time() - t < 15
        idle.close()
        assert p.poll() is None
    finally:
        p.kill()
    assert "通信に失敗しました" in p.communicate()[1]


def test_HTTPのサーバーは1万件続けて答える(tmp_path):
    import http.client

    import net_helper as N

    port = N.free_port()
    ir = suru_compile.compile_source(N.HTTP_SERVER.replace("PORT", str(port)), ".")
    (tmp_path / "srv.ll").write_text(ir, encoding="utf-8")
    suru_compile.build(str(tmp_path / "srv.ll"), str(tmp_path / "srv"))
    p = subprocess.Popen([str(tmp_path / "srv")], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        N.wait_http(port)
        for _ in range(10000):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/")
            r = c.getresponse()
            assert (r.status, r.read()) == (200, "こんにちは".encode("utf-8"))
            c.close()
        assert p.poll() is None
    finally:
        p.kill()

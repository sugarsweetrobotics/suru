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

    it = suru.Interpreter(out=lambda s: out.append(s + "\n"), read=read, write=out.append)
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
a を b で 割った数にする とは a / b
f とは 10 を 割った数にすること
f を 2 に 適用する
（1 と 2 と 4） の それぞれ に （8 を 割った数にすること） を 適用する
（1 と 2 と 3） を 0 から 加算すること で 畳み込みする
""",
    "改行なしの表示": """
「あなた> 」 を 続表示する
（1 と 2） を 続表示する
「」 を 表示する
「a」を続表示する。それから、「b」を表示する。
""",
    "受け取った関数を名前で呼ぶ": """
文字列 の リスト を 甲 から （甲 を 文字列 で 受け取って 甲 を 返すこと） で 順畳込する は 甲
行 を 初め から 処理 で 順畳込する とは
  もし 行 が 空 ならば 初め
  そうでなければ （行 の 残り） を （初め を 行 の 先頭 で 処理する） から 処理 で 順畳込する
数 を 文字列 で 足込する とは 数 + （文字列 を 数値にする）
（「1」 と 「2」 と 「3」） を 0 から 足込すること で 順畳込する
（「a」 と 「b」） を 「」 から （s を t で 受け取って s + t + 「!」 を 返すこと） で 順畳込する
処理 を 局所呼出する とは
  x を 処理する とは x + 100
  1 を 処理する
（x を 受け取って x * 2 を 返すこと） を 局所呼出する
表示 を 引数優先する とは 5 を 表示する
（x を 受け取って x * 3 を 返すこと） を 引数優先する
""",
    "局所の定義に入れた関数を名前で呼ぶ": """
箱 とは 関 の 組
x を b で 使用する とは
  加え とは b の 関
  x を 0 で 加えする
b とは 関 は （a を i で 受け取って a + i を 返すこと） の 箱
（5 を b で 使用する） を 表示する
""",
    "整列する": """
「標準」 を 読み込んで 使う
（（3 と 1.5 と 2 と 1） を 整列する） を 表示する
（（「b」 と 「a」 と 「あ」 と 「B」） を 整列する） を 表示する
（（「bb」 と 「a」 と 「ccc」 と 「d」） を （s を 受け取って s の 長さ を 返すこと） で 基準整列する） を 表示する
（（1 と 2 と 3） を （x を 受け取って 0 - x を 返すこと） で 基準整列する） を 表示する
xs とは （1 から 3000 を 範囲にする） を 逆順にする
（（xs を 整列する） の 先頭） を 表示する
（（xs を （x を 受け取って 「k」 + （x を 文字列化する） を 返すこと） で 基準整列する） の 先頭） を 表示する
（空 を 整列する） を 表示する
""",
    "後始末実行する": """
「標準」 を 読み込んで 使う
片付ける とは 「片付けた」 を 表示する
成功例 とは （「本体」 を 表示する） を 片付ける で 後始末実行する
失敗例 とは 手順
  「途中」 を 表示する
  「x」 を 数値にして 表示する
始めする とは 手順
  r とは 成功例 を 試行した 結果
  r を 表示する
  s とは （失敗例 を 片付ける で 後始末実行する） を 試行した 結果
  s を 表示する
始めする
""",
    "入力確認する": """
文字列 の 有無 を 応答する は 文字列 の 動作
（s の 有） を 応答する とは 手順
  「> 」 + s を 表示する
  「? 」 を 入力確認してから 応答する
無 を 応答する とは 「おしまい」 を 表示する
「? 」 を 入力確認してから 応答する
""",
    "もしの枝のした結果": """
n を 質問する とは 手順
  答 とは もし n > 1 ならば 「大? 」 を 入力した 結果 そうでなければ 「小」
  追加 とは もし n > 5 ならば 「x」 そうでなければ もし n > 1 ならば 「中? 」 を 入力した 結果 そうでなければ 「-」
  答 + 追加 を 表示する
方法 を 処理する とは 手順
  本文 とは もし 方法 が 「HEAD」 ならば 「」 そうでなければ 「本文? 」 を 入力した 結果
  本文 の 長さ を 結果にする
1 を 質問する
3 を 質問する
「HEAD」 を 処理してから 表示する
「GET」 を 処理してから 表示する
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
    # Python 3.11 までのインタプリタでは再帰が深すぎて止まる深さ
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


def test_バイト列を送るのはインタプリタと同じ(tmp_path):
    from net_helper import BYTES_EXPECTED, BYTES_SERVER, free_port, read_all

    port = free_port()
    ir = suru_compile.compile_source(BYTES_SERVER.replace("PORT", str(port)), ".")
    (tmp_path / "srv.ll").write_text(ir, encoding="utf-8")
    suru_compile.build(str(tmp_path / "srv.ll"), str(tmp_path / "srv"))
    p = subprocess.Popen([str(tmp_path / "srv")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline() == "待受中\n"
        assert read_all(port) == BYTES_EXPECTED
        assert p.wait(10) == 0
        assert p.stdout.read() == "256\n"
    finally:
        p.kill()


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


def test_通信でこちらからつなぐのをコンパイルする(tmp_path):
    from net_helper import CLIENT, CLIENT_OUT, answer_once, free_port

    port = free_port()
    t = answer_once(port)
    r = compiled(CLIENT.replace("PORT", str(port)), tmp_path)
    t.join(10)
    assert r.returncode == 0 and r.stdout.splitlines() == CLIENT_OUT
    bad = compiled(f"「通信」 を 読み込む\n「127.0.0.1」 に {free_port()} で 通信内の接続する\n", tmp_path)
    assert bad.returncode == 1 and "「接続する」で通信に失敗しました" in bad.stderr


def test_バイト列受信するをコンパイルする(tmp_path):
    from net_helper import CLIENT_BYTES, CLIENT_BYTES_OUT, answer_once, free_port

    port = free_port()
    t = answer_once(port)
    r = compiled(CLIENT_BYTES.replace("PORT", str(port)), tmp_path)
    t.join(10)
    assert r.returncode == 0 and r.stdout == "".join(s + "\n" for s in CLIENT_BYTES_OUT)


@pytest.mark.parametrize("which", ["HTTP_SERVER", "HTTP_ACTION_SERVER"])
def test_HTTPのサーバーをコンパイルして答えてもらう(which, tmp_path):
    import net_helper as N

    port = N.free_port()
    ir = suru_compile.compile_source(getattr(N, which).replace("PORT", str(port)), str(N.HTTP_DIR))
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
    ir = suru_compile.compile_source(N.HTTP_SERVER.replace("PORT", str(port)), str(N.HTTP_DIR))
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
    ir = suru_compile.compile_source(N.HTTP_SERVER.replace("PORT", str(port)), str(N.HTTP_DIR))
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


# --- GC(runtime/suru_rt.c の「メモリ」の節) ---

def gc_run(source: str, tmp_path: pathlib.Path, env: dict, base_dir: str = ".") -> subprocess.CompletedProcess:
    import os

    compiled(source, tmp_path, base_dir)  # tmp_path/prog を作る
    return subprocess.run([str(tmp_path / "prog")], input=INPUT, capture_output=True, text=True, timeout=120,
                          env={**os.environ, **env})


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_確保のたびにGCしても結果が同じ(path, tmp_path):
    source = path.read_text(encoding="utf-8")
    r = gc_run(source, tmp_path, {"SURU_GC_MIN": "0"}, str(path.parent))
    assert r.returncode == 0, r.stderr
    assert r.stdout == interpreted(source, str(path.parent))


@pytest.mark.parametrize("name", list(PROGRAMS) + ["深い再帰"])
def test_確保のたびにGCしても結果が同じ_いろいろ(name, tmp_path):
    source = DEEP if name == "深い再帰" else PROGRAMS[name]
    r = gc_run(source, tmp_path, {"SURU_GC_MIN": "1"})  # 1KB ごと(深い再帰で毎回スタック全体を調べると遅いので)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ("100000\n" if name == "深い再帰" else interpreted(source))


GARBAGE = """
n を 数列にする とは もし n == 0 ならば 空 そうでなければ 0 を （n - 1 を 数列にする） に 追加する
xs を 合計する とは もし xs が 空 ならば 0 そうでなければ xs の 残り を 合計して xs の 先頭 を 加算する
s を 文字列反復する とは もし s の 長さ > 200 ならば s の 長さ そうでなければ s + 「あ」 を 文字列反復する
k を 反復する とは もし k == 0 ならば 0 そうでなければ （200 を 数列にして 合計する） + （「」 を 文字列反復する） + （k - 1 を 反復する）
3000 を 反復する
"""


def test_使い終わったメモリはGCで回収される(tmp_path):
    import os

    compiled(GARBAGE, tmp_path)
    p = subprocess.Popen([str(tmp_path / "prog")], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         env={**os.environ, "SURU_GC_LOG": "1"})
    out, err = p.communicate(timeout=120)
    assert p.returncode == 0, err
    assert out == "603000\n"
    logs = [line for line in err.splitlines() if line.startswith("GC ")]
    # GC がなければ 1GB 以上使うプログラム。何度も GC が動き、領域(1つ 256KB)は増え続けない
    assert len(logs) > 10
    regions = [int(line.split("領域 ")[1].split("、")[0]) for line in logs]
    assert max(regions) < 100


def test_文字列の大小はインタプリタと同じ(tmp_path):
    src = ("「a」 < 「b」\n「いぬ」 >= 「ねこ」\n「ab」 < 「abc」\n「abc」 <= 「abc」\n「Z」 > 「a」\n「」 < 「a」\n"
           "a と b を 小さい方にする とは もし a < b ならば a そうでなければ b\n「z」 と 「y」 を 小さい方にする\n")
    assert same(src, tmp_path) == "真\n偽\n真\n真\n偽\n真\ny\n"


TABLE = """「表」 を 読み込む
「標準」 を 読み込んで 使う
t とは 空表 を 「b」 から 2 へ 表内の登録して 「a」 から 1 へ 表内の登録して 「c」 から 3 へ 表内の登録して 「a」 から 10 へ 表内の登録する
t から 「a」 を 0 で 表内の既定取得する
t から 「z」 を 0 で 表内の既定取得する
t が 「c」 を 表内の鍵含有である
t が 「d」 を 表内の鍵含有である
t を 表内の鍵一覧にする
t を 表内の値一覧にする
t を 表内の件数にする
u に i を 足込する とは u を （i * 7 % 1000） から i へ 表内の登録する
大 とは （1 から 1000 を 範囲にする） を 空表 から 足込すること で 畳み込みする
大 を 表内の件数にする
大 から 7 を 0 で 表内の既定取得する
もし 大 が 鍵 は k で 値 は v で 左 は l で 右 は r で 段数 は h の 表節 ならば h <= 11 そうでなければ 偽
（（3 と 「x」 の 対） と （1 と 「y」 の 対） と （3 と 「z」 の 対）） を 表内の対表化して 表内の値一覧にする
"""


def test_表はインタプリタと同じ(tmp_path):
    assert same(TABLE, tmp_path) == "10\n0\n真\n偽\n（「a」 と 「b」 と 「c」）\n（10 と 2 と 3）\n3\n1000\n1\n真\n（「y」 と 「z」）\n"


def test_読み込んだファイルの中の実行時エラーはファイルの名前を付ける(tmp_path):
    from test_suru import PARTS, PARTS_ERR, PARTS_MAIN

    (tmp_path / "部品.suru").write_text(PARTS, encoding="utf-8")
    r = compiled(PARTS_MAIN, tmp_path, str(tmp_path))
    assert r.returncode == 1 and r.stderr == PARTS_ERR + "\n"


def test_型の名前はファイルごとに分かれる(tmp_path):
    from test_suru import TYPE_A, TYPE_B

    (tmp_path / "甲.suru").write_text(TYPE_A, encoding="utf-8")
    (tmp_path / "乙.suru").write_text(TYPE_B, encoding="utf-8")
    out = same("「甲」 を 読み込む\n「乙」 を 読み込む\n1 を 甲内の甲作成する\n（2 を 乙内の乙作成する） を 乙内の乙番号取得する\n"
               "（5 の 乙内の応答）\n乙内の空応答 を 乙内の乙番号取得する\n（（3 と 「x」 の 甲内の応答） を 甲内の甲状態取得する）\n",
               tmp_path, str(tmp_path))
    assert out == "甲の応答 1\n2\n（番号 は 5 の 応答）\n0\n3\n"


# 読み込んだファイルの中の実行時エラーは、本体の呼んだ場所で出す(#154)
LIB_ERRORS = {
    "直接呼ぶ": ("「標準」 を 読み込んで 使う\n「a」 を 表示する\n（空 を 最大値にする） を 表示する\n",
                 "エラー: 3行目 6文字目: 空のリストの最大値はありません(「標準.suru」の"),
    "関数の値で呼ぶ": ("「標準」 を 読み込んで 使う\nxs とは （1 と 2） と 空\n（xs を 最小値にすること で 写像する） を 表示する\n",
                     "エラー: 3行目 18文字目: 空のリストの最小値はありません(「標準.suru」の"),
    "作った動作": ("「標準」 を 読み込んで 使う\n「ファイル」 を 読み込んで 使う\n始めする とは 以下の手順です\n"
                   "  「始め」 を 表示する\n  s とは 「無い.csv」 を 読込した 結果\n  s を 表示する\n  以上\n始めする\n",
                   "エラー: 5行目 19文字目: ファイル『無い.csv』を開くのに失敗しました(No such file or directory)(「標準.suru」の"),
    "自分の関数の中から呼ぶ": ("「標準」 を 読み込んで 使う\nxs を 調べする とは xs を 最大値にする\n（（1 と 2） を 調べする） を 表示する\n"
                             "（空 を 調べする） を 表示する\n",
                             "エラー: 2行目 19文字目: 空のリストの最大値はありません(「標準.suru」の"),
}


@pytest.mark.parametrize("name", list(LIB_ERRORS))
def test_読み込んだファイルの中のエラーは呼んだ場所で出す(name, tmp_path):
    src, head = LIB_ERRORS[name]
    r = compiled(src, tmp_path)
    assert r.returncode == 1
    assert r.stderr.startswith(head), r.stderr
    with pytest.raises(suru.SuruError) as e:
        suru.run(src)
    assert r.stderr.strip() == suru.format_error(e.value, src)


def test_読み込んだファイルの中のエラーを試行で受け止めたあとも呼んだ場所で出す(tmp_path):
    src = ("「標準」 を 読み込んで 使う\n「ファイル」 を 読み込む\n始めする とは 以下の手順です\n"
           "  r とは （「無い.txt」 を ファイル内の読込する） を 試行した 結果\n  r を 表示する\n"
           "  （空 を 最大値にする） を 表示する\n  以上\n始めする\n")
    r = compiled(src, tmp_path)
    assert r.returncode == 1
    assert r.stderr.startswith("エラー: 6行目 8文字目: 空のリストの最大値はありません(「標準.suru」の"), r.stderr
    with pytest.raises(suru.SuruError) as e:
        suru.run(src)
    assert r.stderr.strip() == suru.format_error(e.value, src)


def test_自分の読み込んだファイルからライブラリを呼んだ場所で出す(tmp_path):
    # ライブラリ(同梱の lib/ と依存)でない、自分のファイルの中の呼び出しは、そのファイルの位置で出す
    (tmp_path / "部品.suru").write_text("「標準」 を 読み込んで 使う\nxs を 調べする とは xs を 最大値にする\n", encoding="utf-8")
    src = "「部品」 を 読み込む\n（空 を 部品内の調べする） を 表示する\n"
    r = compiled(src, tmp_path, str(tmp_path))
    assert r.returncode == 1
    assert r.stderr.startswith("エラー: 「部品.suru」の2行目 19文字目: 空のリストの最大値はありません(「標準.suru」の"), r.stderr
    with pytest.raises(suru.SuruError) as e:
        it = suru.Interpreter()
        it.ctx.base_dir = str(tmp_path)
        it.run(src)
    assert r.stderr.strip() == suru.format_error(e.value, src)

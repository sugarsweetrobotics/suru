"""スレッド(lib/スレッド.suru)のテスト: インタプリタとバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

BASIC = """「スレッド」 を 読み込んで 使う
数 を フィボナッチにする は 数
n を フィボナッチにする とは もし n < 2 ならば n そうでなければ （n - 1 を フィボナッチにする） + （n - 2 を フィボナッチにする）
試す とは 手順
  t とは （20 を フィボナッチにして 結果にする） を 並行開始した 結果
  t を 合流してから 表示する
  （（1 を 結果にする） と （2 を 結果にする） と （3 を 結果にする）） を 並行実行してから 表示する
  （1 と 2 と 3 と 4 と 5 と 6 と 7 と 8 と 9 と 10 と 11 と 12） を フィボナッチにすること で 並列写像して 表示する
  空 を フィボナッチにすること で 並列写像して 表示する
  n とは コア数取得した 結果
  n > 0 を 表示する
試す
"""

BASIC_OUT = "6765\n（1 と 2 と 3）\n（1 と 1 と 2 と 3 と 5 と 8 と 13 と 21 と 34 と 55 と 89 と 144）\n空\n真\n"

# 待つ間(外部の関数)はほかのスレッドが動く: 0.6 秒ずつ待つ 2 つのスレッドが、合わせて 1.2 秒よりずっと早く終わる
WAIT = """「スレッド」 を 読み込んで 使う
「時間」 を 読み込んで 使う
文字列 を 遅延返却する は 文字列 の 動作
s を 遅延返却する とは 手順
  0.6 を 待機する
  s を 結果にする
試す とは 手順
  a とは （「一」 を 遅延返却する） を 並行開始した 結果
  b とは （「二」 を 遅延返却する） を 並行開始した 結果
  「先」 を 表示する
  a を 合流してから 表示する
  b を 合流してから 表示する
試す
"""

# スレッドの中のエラーはそのスレッドだけを終え、合流すると「エラーで終わりました」になる
ERROR = """「スレッド」 を 読み込んで 使う
「標準」 を 読み込んで 使う
文字列 を 数値動作にする は 数 の 動作
s を 数値動作にする とは 手順
  n とは コア数取得した 結果
  s を 数値にして 結果にする
文字列 を 数値化する は 数
s を 数値化する とは s を 数値にする
試す とは 手順
  t とは （「零」 を 数値動作にする） を 並行開始した 結果
  （t を 合流する） を （-1 を 結果にする） で 試行してから 表示する
  （（「1」 と 「零」 と 「2」） を 数値化すること で 並列写像する） の 長さ を 表示する
試す
"""

# たくさん確保しながら、いくつものスレッドが同時に動く(バイナリでは GC が何度も走る)
MANY = """「スレッド」 を 読み込んで 使う
数 を 積算する は 数
n を 積算する とは もし n = 0 ならば 0 そうでなければ （（n と n と n） を 加算する） + （n - 1 を 積算する）
数 を 仕事する は 数 の 動作
k を 仕事する とは （k を 百倍積算する） を 結果にする
数 を 百倍積算する は 数
k を 百倍積算する とは k * 100 を 積算する
試す とは 手順
  （（1 と 2 と 3 と 4 と 5 と 6 と 7 と 8） の それぞれ を 仕事する） を 並行実行してから 表示する
  （1 と 2 と 3 と 4 と 5 と 6 と 7 と 8） を 百倍積算すること で 並列写像して 表示する
試す
"""


CHANNEL = """「スレッド」 を 読み込んで 使う
「標準」 を 読み込んで 使う
数 の 通路 へ 数 を 生産する は 数 の 通路 の 動作
c へ n を 生産する とは もし n = 0 ならば c を 通路閉鎖する そうでなければ c へ n を 一つ生産する
数 の 通路 へ 数 を 一つ生産する は 数 の 通路 の 動作
c へ n を 一つ生産する とは 手順
  n を c へ 通路送信する
  c へ n - 1 を 生産する
数 を 二倍表示する は 数 の 動作
x を 二倍表示する とは x * 2 を 表示する
試す とは 手順
  c とは 0 で 通路作成した 結果
  p とは （c へ 5 を 生産する） を 並行開始した 結果
  k とは c を 二倍表示すること で 通路処理した 結果
  （「件数」 + （k を 文字列化する）） を 表示する
  d とは 2 で 通路作成した 結果
  10 を d へ 通路送信する
  20 を d へ 通路送信する
  d を 通路閉鎖する
  d から 通路受信してから 表示する
  d から 通路受信してから 表示する
  （d から 通路受信する） を （-1 を 結果にする） で 試行してから 表示する
  （30 を d へ 通路送信する） を （-2 を 結果にする） で 試行してから 表示する
  e とは 1 で 通路作成した 結果
  e から 通路受信する
試す
"""

CHANNEL_OUT = "10\n8\n6\n4\n2\n件数5\n10\n20\n-1\n-2\n"

# 2 つのスレッドがお互いを待つ: 合流しているスレッドの相手が、だれも送らない通路を待つ
STUCK = """「スレッド」 を 読み込んで 使う
試す とは 手順
  c とは 0 で 通路作成した 結果
  t とは （c から 通路受信する） を 並行開始した 結果
  t を 合流する
試す
"""


# 箱を 3 つのスレッドで 100 回ずつ増やす、ロックの中で読んで待って書く、エラーでもロックを手放す、枠は同時に 2 つまで
LOCKS = """「スレッド」 を 読み込んで 使う
「標準」 を 読み込んで 使う
「時間」 を 読み込んで 使う
数 を 加一する は 数
x を 加一する とは x + 1
数 を 減一する は 数
x を 減一する とは x - 1
数 を 数 で 最大化する は 数
x を c で 最大化する とは もし x < c ならば c そうでなければ x
数 の 箱 を 数 で 箱増加続けする は 数 の 動作
b を n で 箱増加続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ b を n で 箱増加一回する
数 の 箱 を 数 で 箱増加一回する は 数 の 動作
b を n で 箱増加一回する とは 手順
  b を 加一すること で 箱更新する
  b を n - 1 で 箱増加続けする
数 の 箱 を 遅延加算する は 数 の 動作
b を 遅延加算する とは 手順
  x とは b を 箱読取した 結果
  0.01 を 待機する
  x + 1 を b へ 箱書込する
ロック で 数 の 箱 を 遅延増加する は 数 の 動作
l で b を 遅延増加する とは l で （b を 遅延加算する） を 排他実行する
数 の 箱 で 数 の 箱 を 計数本体する は 数 の 動作
今 で 最大 を 計数本体する とは 手順
  c とは 今 を 加一すること で 箱更新した 結果
  最大 を （c で 最大化すること） で 箱更新する
  0.05 を 待機する
  今 を 減一すること で 箱更新する
枠 で 数 の 箱 に 数 の 箱 を 枠内計数する は 数 の 動作
w で 今 に 最大 を 枠内計数する とは w で （今 で 最大 を 計数本体する） を 枠内実行する
主 とは 手順
  b とは 0 で 箱作成した 結果
  （（b を 100 で 箱増加続けする） と （b を 100 で 箱増加続けする） と （b を 100 で 箱増加続けする）） を 並行実行する
  b を 箱読取してから 表示する
  l とは ロック作成した 結果
  b2 とは 0 で 箱作成した 結果
  （（l で b2 を 遅延増加する） と （l で b2 を 遅延増加する） と （l で b2 を 遅延増加する） と （l で b2 を 遅延増加する）） を 並行実行する
  b2 を 箱読取してから 表示する
  （l で （「わざと」 を 失敗する） を 排他実行する） を （0 を 結果にする） で 試行する
  l で （「もう一度持てた」 を 表示する） を 排他実行する
  l で （l で （「重ねて持てた」 を 表示する） を 排他実行する） を 排他実行する
  w とは 2 で 枠作成した 結果
  今 とは 0 で 箱作成した 結果
  最大 とは 0 で 箱作成した 結果
  （（w で 今 に 最大 を 枠内計数する） と （w で 今 に 最大 を 枠内計数する） と （w で 今 に 最大 を 枠内計数する） と （w で 今 に 最大 を 枠内計数する）） を 並行実行する
  最大 を 箱読取してから 表示する
主
"""


# 接続ごとにスレッドで答える HTTP サーバー。/slow は 1 秒待ってから答える
HTTP_PARALLEL = """「HTTP」 を 読み込む
「時間」 を 読み込む

要求 を 案内する とは 手順
  もし 要求 の 道 が 「/slow」 ならば 1 を 時間内の待機する そうでなければ 0 を 結果にする
  （「道は」 + 要求 の 道） を HTTP内の本文応答して 結果にする

PORT を 案内すること で HTTP内の動作並行待受する
"""

# 本当の並列: 4つのスレッドが同じ箱を更新し、通路で作ったばかりのリストを渡し、その間に確保しない計算も動く
RACE = """「スレッド」 を 読み込んで 使う
「標準」 を 読み込んで 使う
数 を 加一する は 数
x を 加一する とは x + 1
数 を フィボナッチにする は 数
n を フィボナッチにする とは もし n < 2 ならば n そうでなければ （n - 1 を フィボナッチにする） + （n - 2 を フィボナッチにする）
数 を 文字列作成する は 文字列 の リスト
n を 文字列作成する とは （1 から n を 範囲にする） の それぞれ を 文字列化する
数 の 箱 を 数 で 箱増加続けする は 数 の 動作
b を n で 箱増加続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ b を n で 箱増加一回する
数 の 箱 を 数 で 箱増加一回する は 数 の 動作
b を n で 箱増加一回する とは 手順
  b を 加一すること で 箱更新する
  （20 を 文字列作成する） の 長さ を 結果にする
  b を n - 1 で 箱増加続けする
文字列 の リスト の 通路 へ 数 を 生産する は 文字列 の リスト の 通路 の 動作
c へ n を 生産する とは もし n = 0 ならば c を 通路閉鎖する そうでなければ c へ n を 一つ生産する
文字列 の リスト の 通路 へ 数 を 一つ生産する は 文字列 の リスト の 通路 の 動作
c へ n を 一つ生産する とは 手順
  （30 を 文字列作成する） を c へ 通路送信する
  c へ n - 1 を 生産する
文字列 の リスト を 確認する は 数 の 動作
xs を 確認する とは もし （xs を 「,」 で 結合する） の 長さ が 80 ならば 0 を 結果にする そうでなければ 「壊れた」 を 失敗する
主 とは 手順
  b とは 0 で 箱作成した 結果
  f とは （22 を フィボナッチにして 結果にする） を 並行開始した 結果
  （（b を N で 箱増加続けする） と （b を N で 箱増加続けする） と （b を N で 箱増加続けする） と （b を N で 箱増加続けする）） を 並行実行する
  b を 箱読取してから 表示する
  c とは 4 で 通路作成した 結果
  p とは （c へ N を 生産する） を 並行開始した 結果
  c を 確認すること で 通路処理してから 表示する
  f を 合流してから 表示する
主
"""

# 並列写像が本当に並列に計算する(確保しない計算)
SPEED = """「スレッド」 を 読み込んで 使う
数 を フィボナッチにする は 数
n を フィボナッチにする とは もし n < 2 ならば n そうでなければ （n - 1 を フィボナッチにする） + （n - 2 を フィボナッチにする）
（32 と 32 と 32 と 32） を フィボナッチにすること で MAPして 表示する
"""

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if "「HTTP」" in source:
        sys.path.insert(0, str(ROOT / "tests"))
        from net_helper import put_http
        put_http(d)
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


@pytest.mark.parametrize("kind", KINDS)
def test_並行開始と合流(tmp_path, kind):
    r = subprocess.run(build(BASIC, tmp_path, kind), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout == BASIC_OUT


@pytest.mark.parametrize("kind", KINDS)
def test_待つ間はほかのスレッドが動く(tmp_path, kind):
    cmd = build(WAIT, tmp_path, kind)
    start = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    took = time.monotonic() - start
    assert r.returncode == 0, r.stderr
    assert r.stdout == "先\n一\n二\n"
    assert took < 1.1 + (0.5 if kind == "interp" else 0), took


@pytest.mark.parametrize("kind", KINDS)
def test_スレッドの中のエラー(tmp_path, kind):
    r = subprocess.run(build(ERROR, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stderr
    assert r.stdout == "-1\n"
    lines = r.stderr.splitlines()
    assert lines[0] == "エラー: 6行目 7文字目: 「零」は数値にできません"
    assert lines[1] == "エラー: 10行目 26文字目: 並行開始した動作はエラーで終わりました"
    # 並列写像の中のエラーは、順に計算したときと同じエラー(1回だけ書く)
    assert r.stderr.count("「零」は数値にできません") == 2


@pytest.mark.parametrize("kind", KINDS)
def test_たくさんのスレッドで確保する(tmp_path, kind):
    env = dict(os.environ, SURU_GC_MIN="64")
    r = subprocess.run(build(MANY, tmp_path, kind), capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    want = [3 * (k * 100) * (k * 100 + 1) // 2 for k in range(1, 9)]
    lst = "（" + " と ".join(map(str, want)) + "）\n"
    assert r.stdout == lst + lst


@pytest.mark.parametrize("kind", KINDS)
def test_通路(tmp_path, kind):
    r = subprocess.run(build(CHANNEL, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert r.stdout == CHANNEL_OUT
    lines = r.stderr.splitlines()
    assert lines[0] == "エラー: 22行目 9文字目: 通路は閉じていて、もう値がありません"
    assert lines[1] == "エラー: 23行目 13文字目: 閉じた通路には送れません"
    assert lines[2] == "エラー: 25行目 8文字目: すべてのスレッドが待っていて、先に進めません(通路や合流の待ち)"


@pytest.mark.parametrize("kind", KINDS)
def test_お互いに待つと止まらずにエラー(tmp_path, kind):
    r = subprocess.run(build(STUCK, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "先に進めません" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_ロックと枠と箱(tmp_path, kind):
    r = subprocess.run(build(LOCKS, tmp_path, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "300\n4\nもう一度持てた\n重ねて持てた\n2\n"
    assert r.stderr == "エラー: 39行目 17文字目: わざと\n"


@pytest.mark.parametrize("kind", KINDS)
def test_HTTPは接続ごとに並行に答える(tmp_path, kind):
    import socket
    import threading

    sys.path.insert(0, str(ROOT / "tests"))
    import net_helper as N

    port = N.free_port()
    p = subprocess.Popen(build(HTTP_PARALLEL.replace("PORT", str(port)), tmp_path, kind),
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        N.wait_http(port)
        idle = socket.create_connection(("127.0.0.1", port))  # つないだまま何も送らない相手がいても
        slow: dict = {}
        th = threading.Thread(target=lambda: slow.update(r=N.http(port, "/slow")))
        th.start()
        time.sleep(0.2)
        t = time.monotonic()
        assert N.http(port, "/fast")[::2] == (200, "道は/fast")  # 遅い要求や待っている相手を待たない
        assert time.monotonic() - t < 0.5
        th.join()
        assert slow["r"][::2] == (200, "道は/slow")
        for i in range(200 if kind == "interp" else 2000):
            assert N.http(port, f"/{i}")[::2] == (200, f"道は/{i}")
        idle.close()
        assert p.poll() is None
    finally:
        p.kill()


@pytest.mark.parametrize("kind", KINDS)
def test_同時に動くスレッドとGC(tmp_path, kind):
    n = 300 if kind == "interp" else 3000
    env = dict(os.environ, SURU_GC_MIN="0")
    r = subprocess.run(build(RACE.replace("N", str(n)), tmp_path, kind), capture_output=True, text=True, timeout=300, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout == f"{4 * n}\n{n}\n17711\n"


@pytest.mark.skipif("binary" not in KINDS or (os.cpu_count() or 1) < 2, reason="clang と2つ以上のコアが必要")
def test_並列写像は速くなる(tmp_path):
    def best(src: str, d: pathlib.Path) -> float:
        cmd = build(src, d, "binary")
        times = []
        for _ in range(3):
            t = time.monotonic()
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            times.append(time.monotonic() - t)
            assert r.stdout == "（2178309 と 2178309 と 2178309 と 2178309）\n", r.stderr
        return min(times)

    seq = best(SPEED.replace("を フィボナッチにすること で MAPして", "の それぞれ を フィボナッチにして"), tmp_path / "seq")
    par = best(SPEED.replace("MAPして", "並列写像して"), tmp_path / "par")
    assert par < seq * 0.75, (seq, par)


def test_葉の関数には安全点を置かない():
    src = """x を 加一する とは x + 1
n を 数え下げする とは もし n = 0 ならば 0 そうでなければ （n - 1 を 数え下げする） + 1
3 を 加一して 表示する
3 を 数え下げして 表示する
"""
    ll = suru_compile.compile_source(src, str(ROOT))
    funcs = {}
    for part in ll.split("\ndefine ")[1:]:
        funcs[part.split("(")[0]] = "@rt_safepoint()" in part
    # 加一する(葉)には置かず、数え下げする(自分を呼ぶ)と一番外には置く
    direct = [v for k, v in funcs.items() if k.startswith("internal i64 @f.")]
    assert sorted(direct) == [False, True]
    assert funcs["internal i64 @suru_init"]

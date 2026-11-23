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

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
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

"""lib/プロセス.suru と lib/共有メモリ.suru のテスト: インタプリタとコンパイルしたバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

PROCESS = """「プロセス」 を 読み込んで 使う
試す とは 手順
  「まえ」 を 表示する
  「echo こんにちは; exit 3」 を 命令実行してから 表示する
  （「printf」 と 「%s|%s\\n」 と 「a b」 と 「it's」） を 実行してから 表示する
  r とは 「echo abc; echo def」 を 命令出力取得した 結果
  r の 出力 を 表示する
  r の 終了コード を 表示する
  （「sh」 と 「-c」 と 「echo $0; exit 5」 と 「い ろ」） を 出力取得してから 表示する
  「kill -9 $$」 を 命令実行してから 表示する
  「c」 + 改行 + 「a」 + 改行 + 「b」 + 改行 を 「sort」 で 命令変換してから 表示する
  h とは 「printf 'x\\n\\ny'」 を 「r」 で 命令開始した 結果
  h から 行読込してから 表示する
  h から 行読込してから 表示する
  h から 行読込してから 表示する
  h から 行読込してから 表示する
  h を 命令終了待機してから 表示する
  w とは 「cat; exit 2」 を 書込命令開始した 結果
  「書いた」 + 改行 を w へ 命令書込する
  w を 命令終了待機してから 表示する
  ps とは パイプ作成した 結果
  （「パイプ」 を バイト列にする） を （ps から 2 を 番目取得する） へ 口書込する
  （ps から 1 を 番目取得する） から 100 を 口読込してから 文字列にして 表示する
  （ps から 2 を 番目取得する） を 口閉鎖する
  （ps から 1 を 番目取得する） から 100 を 口読込してから 表示する
  pid とは プロセス番号取得した 結果
  （pid > 0） を 表示する
  「あと」 を 表示する
試す
「a'b」 を 引用する
"""

PROCESS_OUT = """まえ
こんにちは
3
a b|it's
0
abc
def

0
（出力 は 「い ろ
」 で 終了コード は 5 の 実行結果）
137
（出力 は 「a
b
c
」 で 終了コード は 0 の 実行結果）
x



y

0
書いた
2
パイプ
バイト列（）
真
あと
'a'\\''b'
"""

SHM_WRITE = """「共有メモリ」 を 読み込んで 使う
試す とは 手順
  m とは 「NAME」 を 64 で 共有メモリ作成した 結果
  m の 大きさ を 表示する
  （「こんにちは」 を バイト列にする） を 4 で m へ 共有書込してから 表示する
  m から 4 を 0 で 共有読込してから 表示する
  m を 共有メモリ解除する
試す
"""

SHM_READ = """「共有メモリ」 を 読み込んで 使う
試す とは 手順
  m とは 「NAME」 を 64 で 共有メモリ接続した 結果
  m から 15 を 4 で 共有読込してから 文字列にして 表示する
  m を 共有メモリ解除する
  「NAME」 を 共有メモリ削除する
試す
"""

FAIL_RANGE = ("「共有メモリ」 を 読み込む\n試す とは 手順\n  m とは 「NAME」 を 8 で 共有メモリ内の共有メモリ作成した 結果\n"
              "  「NAME」 を 共有メモリ内の共有メモリ削除する\n  m から 9 を 0 で 共有メモリ内の共有読込する\n試す\n")
FAIL_CONNECT = "「共有メモリ」 を 読み込む\n「NAME」 を 8 で 共有メモリ内の共有メモリ接続する\n"


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    """インタプリタなら実行の命令、binary ならコンパイルしてバイナリの命令"""
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


@pytest.mark.parametrize("kind", KINDS)
def test_プロセスとパイプ(tmp_path, kind):
    r = subprocess.run(build(PROCESS, tmp_path / kind, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == PROCESS_OUT


@pytest.mark.parametrize("writer, reader", [(a, b) for a in KINDS for b in KINDS])
def test_共有メモリを別のプロセスで読む(tmp_path, writer, reader):
    name = f"/suru-test-{os.getpid()}-{writer}-{reader}"
    w = subprocess.run(build(SHM_WRITE.replace("NAME", name), tmp_path / "w", writer), capture_output=True, text=True, timeout=60)
    assert w.returncode == 0, w.stderr
    assert w.stdout == "64\n15\nバイト列（00 00 00 00）\n"
    r = subprocess.run(build(SHM_READ.replace("NAME", name), tmp_path / "r", reader), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "こんにちは\n"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("source, message", [
    (FAIL_RANGE, "共有メモリ『NAME』の範囲の外です(大きさは8バイト)"),
    (FAIL_CONNECT, "共有メモリ『NAME』を開くのに失敗しました(No such file or directory)"),
], ids=["範囲", "接続"])
def test_共有メモリの失敗(tmp_path, kind, source, message):
    name = f"/suru-test-{os.getpid()}-fail-{kind}"
    r = subprocess.run(build(source.replace("NAME", name), tmp_path / kind, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert message.replace("NAME", name) in r.stderr

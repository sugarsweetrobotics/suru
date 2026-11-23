"""読み書きロック(lib/読み書きロック.suru)のテスト: インタプリタとバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

PROG = """「プロセス」 を 読み込んで 使う
「セマフォ」 を 読み込んで 使う
「共有メモリ」 を 読み込んで 使う
「読書ロック」 を 読み込んで 使う
「標準」 を 読み込んで 使う
共有メモリ を 数読込する は 数 の 動作
m を 数読込する とは m から 14 を 0 で 共有読込してから 復元する
数 を 共有メモリ へ 数書込する は 数 の 動作
x を m へ 数書込する とは （x を 直列化する） を 0 で m へ 共有書込する
共有メモリ を 増加本体する は 数 の 動作
m を 増加本体する とは 手順
  x とは m を 数読込した 結果
  x + 1 を m へ 数書込する
読書ロック で 共有メモリ に 数 から 増加続けする は 数 の 動作
l で m に n から 増加続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ l で m に n から 一回増加する
読書ロック で 共有メモリ に 数 から 一回増加する は 数 の 動作
l で m に n から 一回増加する とは 手順
  l で （m を 増加本体する） を 書込実行する
  l で m に n - 1 から 増加続けする
読書ロック で 共有メモリ を 書く子作成する は 数 の 動作
l で m を 書く子作成する とは 手順
  pid とは 分岐した 結果
  もし pid = 0 ならば l で m を 書く子本体する そうでなければ pid を 結果にする
読書ロック で 共有メモリ を 書く子本体する は 数 の 動作
l で m を 書く子本体する とは 手順
  l で m に 50 から 増加続けする
  0 を 子終了する
# 子は読む人のまま、親の合図を待つ。親も読む人になって合図を出せれば、読む人は同時に入れている
セマフォ を セマフォ で 合図待ちする は 数 の 動作
a を b で 合図待ちする とは 手順
  a を セマフォ解放する
  b を セマフォ待機する
読書ロック で セマフォ に セマフォ を 読む子作成する は 数 の 動作
l で a に b を 読む子作成する とは 手順
  pid とは 分岐した 結果
  もし pid = 0 ならば l で a に b を 読む子本体する そうでなければ pid を 結果にする
読書ロック で セマフォ に セマフォ を 読む子本体する は 数 の 動作
l で a に b を 読む子本体する とは 手順
  l で （a を b で 合図待ちする） を 読取実行する
  0 を 子終了する
わざと失敗する は 数 の 動作
わざと失敗する とは 「わざと」 を 失敗する
試す とは 手順
  l とは 「LOCK」 を 読書ロック作成した 結果
  m とは 「SHM」 を 64 で 共有メモリ作成した 結果
  0 を m へ 数書込する
  p とは l で m を 書く子作成した 結果
  q とは l で m を 書く子作成した 結果
  p を 子終了待機する
  q を 子終了待機する
  l で （m を 数読込する） を 読取実行してから 表示する
  a とは 「SEMA」 を 0 で セマフォ作成した 結果
  b とは 「SEMB」 を 0 で セマフォ作成した 結果
  r とは l で a に b を 読む子作成した 結果
  a を セマフォ待機する
  l で （b を セマフォ解放する） を 読取実行する
  r を 子終了待機してから 表示する
  （l で （わざと失敗する） を 書込実行する） を （0 を 結果にする） で 試行する
  l2 とは 「LOCK」 を 読書ロック接続した 結果
  l2 で （m を 増加本体する） を 書込実行する
  l2 で （m を 数読込する） を 読取実行してから 表示する
  l2 を 読書ロック解除する
  a を セマフォ削除する
  b を セマフォ削除する
  m を 共有メモリ解除する
  「SHM」 を 共有メモリ削除する
  l を 読書ロック削除する
試す
"""


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


@pytest.mark.parametrize("kind", KINDS)
def test_読み書きロック(tmp_path, kind):
    tag = f"suru-test-{os.getpid()}-rw-{kind}"
    src = (PROG.replace("LOCK", "/" + tag + "-lock").replace("SHM", "/" + tag + "-shm")
           .replace("SEMA", tag + "-a").replace("SEMB", tag + "-b"))
    r = subprocess.run(build(src, tmp_path, kind), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    # 書く人はひとりずつ(100) / 読む人は同時に入れる(子は 0 で終わる) / エラーのあともロックは戻る(101)
    assert r.stdout == "100\n0\n101\n"
    assert f"読み書きロック『/{tag}-lock』で書く途中でエラーになりました" in r.stderr


NOT_LOCK = """「共有メモリ」 を 読み込んで 使う
「読書ロック」 を 読み込んで 使う
試す とは 手順
  m とは 「SHM」 を 64 で 共有メモリ作成した 結果
  「SHM」 を 読書ロック接続する
試す
"""


@pytest.mark.parametrize("kind", KINDS)
def test_読み書きロックでない(tmp_path, kind):
    name = f"/suru-test-{os.getpid()}-notrw-{kind}"
    try:
        r = subprocess.run(build(NOT_LOCK.replace("SHM", name), tmp_path, kind), capture_output=True, text=True, timeout=60)
    finally:
        try:
            os.unlink("/dev/shm" + name)
        except OSError:
            pass
    assert r.returncode == 1
    assert f"共有メモリ『{name}』は読み書きロックではありません" in r.stderr

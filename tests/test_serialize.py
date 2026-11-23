"""直列化(標準内の直列化する・復元する)と、セマフォ内実行する(lib/セマフォ.suru)のテスト:
インタプリタとバイナリで同じに動き、同じバイト列になるか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

ROUND = """「標準」 を 読み込んで 使う
点 とは 横 と 縦 の 組
色 とは 赤 か 青
人 とは 名前 と 年 と 好み の 組
（（1 と 2 の 点） と （3 と 4.5 の 点）） を 直列化して 数列にして 表示する
ps は 点 の リスト
ps とは （（1 と 2 の 点） と （3 と -4.5 の 点）） を 直列化して 復元する
ps を 表示する
（（「あいう」 を 直列化して 復元する） + 「え」） を 表示する
c は 色
c とは 青 を 直列化して 復元する
c を 表示する
（（真 と 偽） を 直列化して 復元する） を 表示する
e は 数 の リスト
e とは 空 を 直列化して 復元する
e を 表示する
p は 人
p とは （「花子」 と 30 と （赤 と 青） の 人） を 直列化して 復元する
p を 表示する
（（「ab」 を バイト列にする） を 直列化して 復元する） を 表示する
（（-123456789 を 直列化して 復元する） * 2） を 表示する
"""

ROUND_OUT = """（83 と 85 と 82 と 85 と 1 と 108 と 2 と 0 と 0 と 0 と 114 と 3 と 0 と 0 と 0 と 231 と 130 と 185 と 2 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 230 と 168 と 170 と 105 と 1 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 231 と 184 と 166 と 105 と 2 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 114 と 3 と 0 と 0 と 0 と 231 と 130 と 185 と 2 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 230 と 168 と 170 と 105 と 3 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 231 と 184 と 166 と 102 と 0 と 0 と 0 と 0 と 0 と 0 と 18 と 64）
（（横 は 1 で 縦 は 2 の 点） と （横 は 3 で 縦 は -4.5 の 点））
あいうえ
青
（真 と 偽）
空
（名前 は 「花子」 で 年 は 30 で 好み は （赤 と 青） の 人）
バイト列（61 62）
-246913578
"""


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


def run(source: str, d: pathlib.Path, kind: str) -> subprocess.CompletedProcess:
    return subprocess.run(build(source, d, kind), capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("kind", KINDS)
def test_直列化して戻す(tmp_path, kind):
    r = run(ROUND, tmp_path, kind)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ROUND_OUT


# 「点」を横と縦で直列化したもの(ROUND の1行目の先頭の組)
POINT = "（83 と 85 と 82 と 85 と 1 と 114 と 3 と 0 と 0 と 0 と 231 と 130 と 185 と 2 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 230 と 168 と 170 と 105 と 1 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 3 と 0 と 0 と 0 と 231 と 184 と 166 と 105 と 2 と 0 と 0 と 0 と 0 と 0 と 0 と 0）"

ERRORS = [
    ("「標準」 を 読み込んで 使う\n（（x を 受け取って x を 返すこと） を 直列化する） を 表示する\n",
     "は直列化できません(関数・動作・番地はほかのプロセスへ渡せません)"),
    ("「標準」 を 読み込んで 使う\nx は 数\nx とは （「abc」 を バイト列にして 復元する）\nx を 表示する\n",
     "バイト列が直列化した値ではありません"),
    ("「標準」 を 読み込んで 使う\n点 とは 横 と 高さ の 組\nx は 点\nx とは " + POINT + " を バイト列組立して 復元する\nx を 表示する\n",
     "形「点」のフィールドが違うので復元できません(2番目は、このプログラムでは「高さ」)"),
    ("「標準」 を 読み込んで 使う\n位置 とは 横 と 縦 の 組\nx は 位置\nx とは " + POINT + " を バイト列組立して 復元する\nx を 表示する\n",
     "形「点」はこのプログラムにないので復元できません"),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("i", range(len(ERRORS)))
def test_直列化のエラー(tmp_path, kind, i):
    source, message = ERRORS[i]
    r = run(source, tmp_path, kind)
    assert r.returncode == 1
    assert message in r.stderr


# 2 つの子が、セマフォ内実行する の中で、共有メモリに直列化した数を 50 回ずつ 1 増やす
COUNTER = """「プロセス」 を 読み込んで 使う
「セマフォ」 を 読み込んで 使う
「共有メモリ」 を 読み込んで 使う
「標準」 を 読み込んで 使う
共有メモリ を 数読込する は 数 の 動作
m を 数読込する とは m から 14 を 0 で 共有読込してから 復元する
数 を 共有メモリ へ 数書込する は 数 の 動作
x を m へ 数書込する とは （x を 直列化する） を 0 で m へ 共有書込する
共有メモリ を 増加本体する は 数 の 動作
m を 増加本体する とは 手順
  x とは m を 数読込した 結果
  x + 1 を m へ 数書込する
数 から 共有メモリ で セマフォ に 増加続けする は 数 の 動作
n から m で s に 増加続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ n から m で s に 一回増加する
数 から 共有メモリ で セマフォ に 一回増加する は 数 の 動作
n から m で s に 一回増加する とは 手順
  s で （m を 増加本体する） を セマフォ内実行する
  n - 1 から m で s に 増加続けする
共有メモリ で セマフォ を 子作成する は 数 の 動作
m で s を 子作成する とは 手順
  pid とは 分岐した 結果
  もし pid = 0 ならば m で s を 子本体する そうでなければ pid を 結果にする
共有メモリ で セマフォ を 子本体する は 数 の 動作
m で s を 子本体する とは 手順
  50 から m で s に 増加続けする
  0 を 子終了する
わざと失敗する は 数 の 動作
わざと失敗する とは 「わざと」 を 失敗する
セマフォ を 持ったまま終わる子作成する は 数 の 動作
s を 持ったまま終わる子作成する とは 手順
  pid とは 分岐した 結果
  もし pid = 0 ならば s で （3 を 子終了する） を セマフォ内実行する そうでなければ pid を 結果にする
試す とは 手順
  m とは 「SHM」 を 64 で 共有メモリ作成した 結果
  0 を m へ 数書込する
  s とは 「SEM」 を 1 で セマフォ作成した 結果
  a とは m で s を 子作成した 結果
  b とは m で s を 子作成した 結果
  a を 子終了待機する
  b を 子終了待機する
  m を 数読込してから 表示する
  （s で （わざと失敗する） を セマフォ内実行する） を （0 を 結果にする） で 試行する
  s を セマフォ試行してから 表示する
  s を セマフォ解放する
  c とは s を 持ったまま終わる子作成した 結果
  c を 子終了待機してから 表示する
  s を セマフォ試行してから 表示する
  s を セマフォ削除する
  m を 共有メモリ解除する
  「SHM」 を 共有メモリ削除する
試す
"""


@pytest.mark.parametrize("kind", KINDS)
def test_セマフォ内実行する(tmp_path, kind):
    tag = f"suru-test-{os.getpid()}-undo-{kind}"
    src = COUNTER.replace("SHM", "/" + tag).replace("SEM", tag)
    r = run(src, tmp_path, kind)
    assert r.returncode == 0, r.stderr
    # 100 回増えた / 失敗してもロックは戻った / ロックを持ったまま終わった子の分も OS が戻した
    assert r.stdout == "100\n真\n3\n真\n"
    assert "わざと" in r.stderr
    assert f"セマフォ『{tag}』の中の動作はエラーで終わりました" in r.stderr

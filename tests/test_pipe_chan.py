"""パイプの通路(スレッド内のプロセス間通路作成する)と 子実行する(lib/プロセス.suru)のテスト:
インタプリタとバイナリで同じに動くか"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

HEAD = """「プロセス」 を 読み込んで 使う
「スレッド」 を 読み込んで 使う
点 とは 横 と 縦 の 組
"""

# 親が送り、子が受け取る
TO_CHILD = HEAD + """点 の 通路 を 子仕事する は 数 の 動作
c を 子仕事する とは c を （p を 受け取って （p の 横 + p の 縦） を 表示する を 返すこと） で 通路処理してから 表示する
試す とは 手順
  c とは プロセス間通路作成した 結果
  pid とは （c を 子仕事する） を 子実行した 結果
  （1 と 2 の 点） を c へ 通路送信する
  （3 と 4 の 点） を c へ 通路送信する
  c を 通路閉鎖する
  pid を 子終了待機してから 表示する
試す
"""

# 2 つの子が送り、親が受け取る。子が終わると(書く口がみな閉じると)親は閉じたと分かる
FROM_CHILDREN = HEAD + """数 の 通路 を 数 で 送る子仕事する は 数 の 動作
c を n で 送る子仕事する とは 手順
  n * 10 を c へ 通路送信する
  n * 10 + 1 を c へ 通路送信する
  （（n と n） の 点） を 文字列化して 表示する
試す とは 手順
  c とは プロセス間通路作成した 結果
  a とは （c を 1 で 送る子仕事する） を 子実行した 結果
  a を 子終了待機する
  b とは （c を 2 で 送る子仕事する） を 子実行した 結果
  b を 子終了待機する
  合計 とは c を （x を 受け取って x を 表示する を 返すこと） で 通路処理した 結果
  合計 を 表示する
  （c から 通路受信する） を （-1 を 結果にする） で 試行してから 表示する
試す
"""

# 1つのプロセスで送ってから受け取るのはエラー
BOTH = HEAD + """数 の 通路 を 一つ受信する は 数 の 動作
c を 一つ受信する とは c から 通路受信してから 表示する
試す とは 手順
  c とは プロセス間通路作成した 結果
  pid とは （c を 一つ受信する） を 子実行した 結果
  1 を c へ 通路送信する
  pid を 子終了待機する
  c から 通路受信してから 表示する
試す
"""

# 受け取るプロセスがいなければ送れない
NOBODY = HEAD + """試す とは 手順
  c とは プロセス間通路作成した 結果
  1 を c へ 通路送信する
試す
"""

# 子の動作のエラーは終了コード 1
CHILD_FAIL = HEAD + """数 を わざと失敗する は 数 の 動作
x を わざと失敗する とは 「わざと」 を 失敗する
試す とは 手順
  pid とは （1 を わざと失敗する） を 子実行した 結果
  pid を 子終了待機してから 表示する
試す
"""

# 関数は送れない
SEND_FN = HEAD + """（数 を 受け取って 数 を 返すこと） の 通路 を 関数送信する は （数 を 受け取って 数 を 返すこと） の 動作
c を 関数送信する とは （x を 受け取って x を 返すこと） を c へ 通路送信する
試す とは 手順
  c とは プロセス間通路作成した 結果
  c を 関数送信する
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


def run(source: str, d: pathlib.Path, kind: str) -> subprocess.CompletedProcess:
    return subprocess.run(build(source, d, kind), capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("kind", KINDS)
def test_子へ送る(tmp_path, kind):
    r = run(TO_CHILD, tmp_path, kind)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "3\n7\n2\n0\n"


@pytest.mark.parametrize("kind", KINDS)
def test_子から受け取る(tmp_path, kind):
    r = run(FROM_CHILDREN, tmp_path, kind)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "（横 は 1 で 縦 は 1 の 点）\n（横 は 2 で 縦 は 2 の 点）\n10\n11\n20\n21\n4\n-1\n"
    assert "通路は閉じていて、もう値がありません" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_送ってから受け取る(tmp_path, kind):
    r = run(BOTH, tmp_path, kind)
    assert r.returncode == 1
    assert r.stdout == "1\n"
    assert "この通路から受け取れません(このプロセスはこの通路に送っています)" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_受け取る相手がいない(tmp_path, kind):
    r = run(NOBODY, tmp_path, kind)
    assert r.returncode == 1
    assert "受け取る相手がいないので、通路に送れません" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_子のエラー(tmp_path, kind):
    r = run(CHILD_FAIL, tmp_path, kind)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "1\n"
    assert "わざと" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_関数は送れない(tmp_path, kind):
    r = run(SEND_FN, tmp_path, kind)
    assert r.returncode == 1
    assert "は直列化できません(関数・動作・番地はほかのプロセスへ渡せません)" in r.stderr

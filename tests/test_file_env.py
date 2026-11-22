"""lib/ファイル.suru と lib/環境.suru のテスト: インタプリタとコンパイルしたバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

FILES = """「標準」 を 読み込んで 使う
「ファイル」 を 読み込む
試す とは 手順
  「あいう」 + 改行 を 「DIR/a.txt」 へ ファイル内の書出する
  「えお」 + 改行 を 「DIR/a.txt」 へ ファイル内の追記した 結果 を 表示する
  「DIR/a.txt」 を ファイル内の読込してから 表示する
  「DIR/a.txt」 を ファイル内の行分割読込してから 表示する
  「DIR/a.txt」 を ファイル内のバイト列読込してから 表示する
  （（0 と 255） を バイト列組立する） を 「DIR/b.bin」 へ ファイル内のバイト列書出する
  「DIR/b.bin」 を ファイル内のバイト列読込してから 表示する
  「」 を 「DIR/empty.txt」 へ ファイル内の書出する
  「DIR/empty.txt」 を ファイル内の行分割読込してから 表示する
  「DIR/a.txt」 を ファイル内の存在確認してから 表示する
  「DIR/a.txt」 を ファイル内の削除する
  「DIR/a.txt」 を ファイル内の存在確認してから 表示する
  「DIR/sub」 を ファイル内のフォルダ作成する
  「DIR/sub」 を ファイル内の存在確認してから 表示する
試す
"""

FILES_OUT = ("7\nあいう\nえお\n\n（「あいう」 と 「えお」）\nバイト列（e3 81 82 e3 81 84 e3 81 86 0a e3 81 88 e3 81 8a 0a）\n"
             "バイト列（00 ff）\n空\n真\n偽\n真\n")

ENV = """「環境」 を 読み込む
環境内の引数取得してから 表示する
「SURU_TEST_VAR」 を 環境内の環境変数取得してから 表示する
「SURU_NO_SUCH_VAR」 を 環境内の環境変数取得してから 表示する
「エラーです」 を 環境内のエラー出力する
環境内の今のフォルダ取得してから 表示する
3 を 環境内の終了する
「ここは出ない」 を 表示する
"""

FAIL_OPEN = "「ファイル」 を 読み込む\n「DIR/no/such.txt」 を ファイル内の読込する\n"
FAIL_DELETE = "「ファイル」 を 読み込む\n「DIR/no_such.txt」 を ファイル内の削除する\n"
FAIL_EXIT = "「環境」 を 読み込む\n300 を 環境内の終了する\n"


def run_both(source: str, tmp_path: pathlib.Path, args: list[str] = ()) -> list[tuple[pathlib.Path, subprocess.CompletedProcess]]:
    """インタプリタと(clang があれば)バイナリで、別々のフォルダで動かす。DIR と今のフォルダはそのフォルダ"""
    env = dict(os.environ, SURU_TEST_VAR="値です")
    out = []
    kinds = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])
    for kind in kinds:
        d = tmp_path / kind
        d.mkdir()
        src = d / "prog.suru"
        src.write_text(source.replace("DIR", str(d)), encoding="utf-8")
        if kind == "interp":
            cmd = [sys.executable, str(ROOT / "suru.py"), str(src), *args]
        else:
            subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
            cmd = [str(d / "prog"), *args]
        out.append((d, subprocess.run(cmd, cwd=d, env=env, capture_output=True, text=True, timeout=60)))
    return out


def test_ファイルの読み書き(tmp_path):
    for d, r in run_both(FILES, tmp_path):
        assert r.returncode == 0, r.stderr
        assert r.stdout == FILES_OUT


def test_環境(tmp_path):
    for d, r in run_both(ENV, tmp_path, ["a", "いろは"]):
        assert r.returncode == 3, r.stderr
        assert r.stdout == f"（「a」 と 「いろは」）\n値です\n\n{d.resolve()}\n"
        assert r.stderr == "エラーです\n"


@pytest.mark.parametrize("source, message", [
    (FAIL_OPEN, "ファイル『DIR/no/such.txt』を開くのに失敗しました(No such file or directory)"),
    (FAIL_DELETE, "ファイル『DIR/no_such.txt』を削除するのに失敗しました(No such file or directory)"),
    (FAIL_EXIT, "「300」は終了コードではありません(0 から 255 までの整数です)"),
])
def test_失敗の文(tmp_path, source, message):
    for d, r in run_both(source, tmp_path):
        assert r.returncode == 1
        assert message.replace("DIR", str(d)) in r.stderr

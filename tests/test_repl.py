"""対話モード(引数なしの suru、suru --対話 ファイル)のテスト"""

import os
import subprocess
import sys

import suru
from suru import Repl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def session(*entries: str, checking: bool = True) -> list[str]:
    out: list[str] = []
    r = Repl(checking, out=out.append)
    for e in entries:
        r.feed(e)
    return out


def test_value_and_type():
    assert session("1 と 2 を 加算する") == ["3 は 数"]
    assert session("「あ」 と 「い」") == ["（「あ」 と 「い」） は 文字列 の リスト"]


def test_definition_shows_signature_and_is_kept():
    assert session("X を 二乗する とは X * X", "3 を 二乗する") == ["数 を 二乗する は 数", "9 は 数"]


def test_redefinition_replaces():
    out = session("X を 二乗する とは X * X", "X を 二乗する とは X と X", "3 を 二乗する")
    assert out[-2:] == ["甲 を 二乗する は 甲 の リスト", "（3 と 3） は 数 の リスト"]


def test_type_error_does_not_run():
    out = session("1 + 「あ」 を 表示する")
    assert len(out) == 1  # 表示しない
    assert out[0].startswith("エラー: 1行目 3文字目: 「+」の両側の型が違います")
    assert out[0].endswith("\n  1 + 「あ」 を 表示する\n    ^")


def test_failed_entry_is_forgotten():
    # 型の間違いがあった入力の定義は残らない
    out = session("X を 壊する とは X + 1 + 「あ」\n1 を 壊する", "1 を 壊する")
    assert len(out) == 2
    assert "型が違います" in out[0]
    assert out[1].startswith("エラー: 1行目 5文字目: 「壊する」は定義されていません")


def test_no_check_mode():
    assert session("1 と 「あ」", checking=False) == ["（1 と 「あ」）"]


def test_types_and_modules_across_entries():
    out = session("図形 とは 半径 の 円 か 幅 と 高 の 長方形",
                  "形 を 面積にする とは\n  もし 形 が\n    半径 の 円 ならば 3 * 半径 ^ 2\n    幅 と 高 の 長方形 ならば 幅 * 高\n",
                  "5 の 円 を 面積にする",
                  "「標準」 を 読み込んで 使う",
                  "（3 と 1 と 2） を 整列する")
    assert out == ["図形 を 面積にする は 数", "75 は 数", "（1 と 2 と 3） は 数 の リスト"]


def test_complete():
    c = Repl.complete
    assert c(["1 と 2"])
    assert not c(["X を 二乗する とは"])
    assert not c(["X を 二乗する とは", "  X * X"])
    assert c(["X を 二乗する とは", "  X * X", ""])
    assert not c(["（1 と"])
    assert not c(["1 と"])  # 「と」で終われば次の行に続く
    assert c(["1 と", "2"])
    assert not c(["（1 と", " 2"])
    assert c(["（1 と", " 2）"])
    assert not c(["aとbを合計するとは、"])
    assert c(["aとbを合計するとは、", "a+b。"])
    assert c(["「（」 を 表示する"])  # 文字列の中の括弧は数えない
    # 「以下の手順です」は「以上」まで読む
    assert not c(["挨拶する とは 以下の手順です"])
    assert not c(["挨拶する とは 以下の手順です", "  「a」 を 表示する", ""])
    assert c(["挨拶する とは 以下の手順です", "  「a」 を 表示する", "  以上"])
    assert not c(["挨拶するとは、以下の手順です。「a」を表示する。"])
    assert c(["挨拶するとは、以下の手順です。「a」を表示する。", "以上。"])
    # 場合分けを閉じる「以上」(場合と同じ深い行)では、まだ手順は終わらない
    case = ["x を 見る とは 以下の手順です", "  もし x が", "    1 ならば 「a」 を 表示する",
            "    そうでなければ 「b」 を 表示する", "    以上"]
    assert not c(case)
    assert c(case + ["  「c」 を 表示する", "  以上です"])
    assert c(case[:-1] + ["  以上"])  # 場合より浅い「以上」は手順を閉じる


def test_commands():
    out: list[str] = []
    r = Repl(out=out.append)
    assert r.command("：型　3 を 加算すること")
    assert r.command(":type 1 と 2")
    assert r.command(":謎")
    assert not r.command(":終わる")
    assert out == ["（数 に 受け取って 数 を 返すこと）", "数 の リスト",
                   "エラー: 「:謎」というコマンドはありません(:助け で一覧を表示します)"]


def test_load_and_names():
    out: list[str] = []
    r = Repl(out=out.append)
    r.command(":読む " + os.path.join(ROOT, "examples", "数学"))
    assert out[-1].endswith("を読みました(:一覧 で定義した名前と型を表示します)")
    r.feed("2 を 円の面積にする")
    assert out[-1] == "12.56 は 数"
    out.clear()
    r.command(":一覧")
    assert out == ["円周率 は 数\n数 を 二乗する は 数\n数 を 円の面積にする は 数\n図形 を 面積にする は 数"]
    out.clear()
    r.command(":読む ない.suru")
    assert out == ["エラー: ファイル「ない.suru」が見つかりません"]


def test_interrupt():
    out: list[str] = []
    r = Repl(out=out.append)

    def stop(*a, **k):
        raise KeyboardInterrupt

    r.interp.run_program = stop
    assert not r.feed("1")
    assert out == ["中断しました"]


def test_cli_pipe():
    p = subprocess.run([sys.executable, os.path.join(ROOT, "suru.py")], capture_output=True, text=True,
                       input="X を 倍化する とは\n  X * 2\n\n4 を 倍化する\n:終わる\n1\n", encoding="utf-8")
    assert "数 を 倍化する は 数" in p.stdout
    assert "8 は 数" in p.stdout
    assert "1 は 数" not in p.stdout  # :終わる で終わる
    assert p.returncode == 0


def test_cli_load_file():
    p = subprocess.run([sys.executable, os.path.join(ROOT, "suru.py"), "--対話", os.path.join(ROOT, "examples", "数学.suru")],
                       capture_output=True, text=True, input="3 を 二乗する\n", encoding="utf-8")
    assert "9 は 数" in p.stdout


def test_history_path(monkeypatch):
    monkeypatch.setenv("SURU_HISTORY", "/tmp/x")
    assert suru.history_path() == "/tmp/x"
    monkeypatch.delenv("SURU_HISTORY")
    monkeypatch.setenv("XDG_STATE_HOME", "/s")
    assert suru.history_path() == os.path.join("/s", "suru", "history")

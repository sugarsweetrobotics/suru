"""lib/点検.suru(する で書いた点検)と「suru --点検」のテスト。インタプリタとバイナリの両方で同じ結果か"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

BAD = """x を 三倍する とは x * 3\x20\x20
5 を 三倍して 表示します
6 を 三倍して 表示する
7 を 三倍して 表示する
『半径』 とは （1 ＋ 2)
y とは 『おやつ』
  a とは 1
\tb とは 2 # 点検しない: 字下げの混在
\tc とは 2
# 点検しない
1 を 表示する\x20
「閉じない
"""

BAD_OUT = """\
DIR/bad.suru:1:18: 行末の空白: 行の終わりに空白があります
DIR/bad.suru:2:10: 丁寧語の混在: 文の終わりが「する」の文が3つ、「します」の文が1つあります。「する」にそろえると読みやすくなります
DIR/bad.suru:5:1: 不要な二重かぎ: 『半径』はひらがなを含まないので、『』で囲まなくても書けます
DIR/bad.suru:5:1: 未使用の定義: 「半径」は定義されていますが、使われていません
DIR/bad.suru:5:9: 全角半角の混在: このファイルの括弧は半角が多いので、「（」も半角にそろえると読みやすくなります
DIR/bad.suru:5:12: 全角半角の混在: このファイルの記号は半角が多いので、「＋」も半角にそろえると読みやすくなります
DIR/bad.suru:6:1: 未使用の定義: 「y」は定義されていますが、使われていません
DIR/bad.suru:7:3: 未使用の定義: 「a」は定義されていますが、使われていません
DIR/bad.suru:8:2: 未使用の定義: 「b」は定義されていますが、使われていません
DIR/bad.suru:9:1: 字下げの混在: このファイルの字下げは半角スペースですが、この行にはタブが使われています
DIR/bad.suru:9:2: 未使用の定義: 「c」は定義されていますが、使われていません
DIR/bad.suru:12:1: 字句の誤り: 文字列の「に対応する」がありません
"""

POLITE = """5を三倍します。
6を三倍します。
7を三倍する。
"""

# 段階2(定義と使用)。型.suru は同じフォルダに置く。「表」は SURU_LIB(lib/)から見つける
TYPES = """点 とは 横 と 縦 の 組
数 を 二倍する は 数
x を 二倍する とは x * 2
数 を 内側にする は 数
x を 内側にする とは x
内側にする は 非公開とする
"""

DEFS = """「型」 を 読み込んで 使う
「数学」 を 読み込む
「表」 を 読み込んで 使う
「標準」 を 読み込んで 使う
x と y を 足算する とは x + 1
n を 数え下げする とは もし n = 0 ならば 0 そうでなければ n - 1 を 数え下げする
k を 使う側にする とは
  a とは k * 2
  c とは 1
  a
空 を 長くする とは 0
先頭 は h で 残り は 他 を 長くする とは 1 + （他 を 長くする）
s を 外呼出する とは 外部の「puts」
xs を 加算する とは 0
xs を 件数にする とは 0
x を 内側にする とは x
（3 を 内側にする） を 表示する
（横 は 1 で 縦 は 2 の 点） を 表示する
（空表 を 「a」 から 1 へ 登録して 鍵一覧にする） を 表示する
3 を 使う側にして 表示する
（1 と 2 を 足算する） を 表示する
（1 と 2 を 長くする） を 表示する
# 点検しない
y を 黙るにする とは 1
"""

DEFS_OUT = """\
defs.suru:2:1: 未使用の読み込み: 「数学」を読み込んでいますが、中の名前を使っていません
defs.suru:4:1: 未使用の読み込み: 「標準」を読み込んでいますが、中の名前を使っていません
defs.suru:5:5: 未使用の引数: 引数「y」は「足算する」の中で使われていません
defs.suru:6:5: 未使用の定義: 「数え下げする」は定義されていますが、使われていません
defs.suru:9:3: 未使用の定義: 「c」は定義されていますが、使われていません
defs.suru:13:5: 未使用の定義: 「外呼出する」は定義されていますが、使われていません
defs.suru:14:1: 未使用の引数: 引数「xs」は「加算する」の中で使われていません
defs.suru:14:6: 未使用の定義: 「加算する」は定義されていますが、使われていません
defs.suru:14:6: 組み込みの上書き: 「加算する」は組み込みの関数と同じ名前です
defs.suru:15:1: 未使用の引数: 引数「xs」は「件数にする」の中で使われていません
defs.suru:15:6: 未使用の定義: 「件数にする」は定義されていますが、使われていません
defs.suru:15:6: 組み込みの上書き: 「件数にする」は「表」の関数と同じ名前です
"""

# ライブラリ(一番外に式の文がないファイル)では、一番外の定義が使われていなくても知らせない。
# 型の宣言のない関数はライブラリでだけ知らせる(宣言は後ろに書いてもよい)
LIBRARY = """x を 二倍する とは x * 2
n を 三倍する とは
  m とは n * 3
  m
数 を 二倍する は 数
"""

# 句読点の書き方と空白の書き方が混ざっていれば、少ないほうの最初の文で1回だけ知らせる
MIXED = """x とは 1
y とは 2
zとは、3。
wとは、4。
（x + y + z + w） を 表示する
"""

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def run_lint(kind: str, tmp_path: pathlib.Path, *paths: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, XDG_CACHE_HOME=str(tmp_path / "cache"))
    if kind == "interp":
        env["SURU_LINT_INTERP"] = "1"
    else:
        env.pop("SURU_LINT_INTERP", None)
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), "--点検", *paths],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=600)


@pytest.mark.parametrize("kind", KINDS)
def test_知らせと終了コード(kind, tmp_path):
    (tmp_path / "bad.suru").write_text(BAD, encoding="utf-8")
    (tmp_path / "polite.suru").write_text(POLITE, encoding="utf-8")
    (tmp_path / "good.suru").write_text("x とは 1\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "bad.suru", "good.suru", "polite.suru")
    assert r.returncode == 1, r.stderr
    assert r.stdout == BAD_OUT.replace("DIR/", "") + (
        "polite.suru:3:3: 丁寧語の混在: 文の終わりが「する」の文が1つ、「します」の文が2つあります。「します」にそろえると読みやすくなります\n")
    r = run_lint(kind, tmp_path, "good.suru")
    assert (r.returncode, r.stdout) == (0, "")
    if kind == "binary":
        assert len(list((tmp_path / "cache" / "suru").glob("点検-*"))) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_定義と使用(kind, tmp_path):
    (tmp_path / "型.suru").write_text(TYPES, encoding="utf-8")
    (tmp_path / "defs.suru").write_text(DEFS, encoding="utf-8")
    (tmp_path / "lib.suru").write_text(LIBRARY, encoding="utf-8")
    (tmp_path / "mixed.suru").write_text(MIXED, encoding="utf-8")
    r = run_lint(kind, tmp_path, "defs.suru", "lib.suru", "mixed.suru")
    assert r.returncode == 1, r.stderr
    assert r.stdout == DEFS_OUT + (
        "lib.suru:2:5: 型の宣言なし: 「三倍する」に型の宣言がありません(『数 を 三倍する は 数』のように書きます)\n"
        "mixed.suru:3:1: 書き方の混在: このファイルは空白の書き方が3文、句読点の書き方が2文あります。空白の書き方にそろえると読みやすくなります\n")


def test_例とライブラリは知らせなし(tmp_path):
    files = sorted(str(p) for p in (ROOT / "examples").glob("*.suru")) + sorted(str(p) for p in (ROOT / "lib").glob("*.suru"))
    files += sorted(str(p) for p in (ROOT / "tests").glob("*.suru"))
    r = run_lint(KINDS[-1], tmp_path, *files)
    assert (r.returncode, r.stdout) == (0, ""), r.stdout + r.stderr


def test_ファイルがないと使い方(tmp_path):
    r = run_lint("interp", tmp_path)
    assert r.returncode == 2
    assert "使い方" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_代わりのファイル(kind, tmp_path):
    # エディターが保存していない中身を別のファイルで渡すとき: 知らせは本当の道で出し、読み込みは本当の道のフォルダから探す
    (tmp_path / "本当").mkdir()
    (tmp_path / "本当" / "型.suru").write_text(TYPES, encoding="utf-8")
    (tmp_path / "中身.txt").write_text("「型」 を 読み込んで 使う\n「数学」 を 読み込む\n3 を 二倍する\n", encoding="utf-8")
    (tmp_path / "good.suru").write_text("x とは 1\nx を 表示する\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "--代わり", "中身.txt", "本当/a.suru", "good.suru")
    assert r.returncode == 1, r.stderr
    assert r.stdout == "本当/a.suru:2:1: 未使用の読み込み: 「数学」を読み込んでいますが、中の名前を使っていません\n"

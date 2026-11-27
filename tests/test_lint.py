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
x を 処理 で 二度呼する とは x を 処理して 処理する
（1 を （n を 受け取って n を 返すこと） で 二度呼する） を 表示する
# 点検しない
y を 黙るにする とは 1
"""

DEFS_OUT = """\
defs.suru:2:1: 未使用の読み込み: 「数学」を読み込んでいますが、中の名前を使っていません
defs.suru:4:1: 未使用の読み込み: 「標準」を読み込んでいますが、中の名前を使っていません
defs.suru:5:5: 未使用の引数: 引数「y」は「足算する」の中で使われていません
defs.suru:6:5: 未使用の定義: 「数え下げする」は定義されていますが、使われていません
defs.suru:7:1: 定義の間の空行: 「使う側にする」の定義は、前の「数え下げする」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
defs.suru:9:3: 未使用の定義: 「c」は定義されていますが、使われていません
defs.suru:11:1: 定義の間の空行: 「長くする」の定義は、前の「使う側にする」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
defs.suru:13:1: 定義の間の空行: 「外呼出する」の定義は、前の「長くする」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
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

# ライブラリでも、非公開の一番外の定義(公開とするの一覧にない定義)は使われていなければ知らせる
HIDDEN = """数 を 甲する は 数
x を 甲する とは x を 丙する
数 を 乙する は 数
x を 乙する とは x
数 を 丙する は 数
x を 丙する とは x
乙する と 丙する は 非公開とする
"""

LISTED = """数 を 甲する は 数
x を 甲する とは x
数 を 乙する は 数
x を 乙する とは x
甲する は 公開とする
"""

# 句読点の書き方と空白の書き方が混ざっていれば、少ないほうの最初の文で1回だけ知らせる
MIXED = """x とは 1
y とは 2
zとは、3。
wとは、4。
（x + y + z + w） を 表示する
"""

# 段階3(構文木を使う規則)。型.suru の形と型も使って読む。型の宣言があるライブラリなので、ほかの知らせは出ない
SYNTAX = """「型」 を 読み込んで 使う
数 を 判定する は 真偽
n を 判定する とは もし n > 1 ならば 真 そうでなければ 偽
数 を 逆判定する は 真偽
n を 逆判定する とは もし n > 1 ならば 偽 そうでなければ 真
真偽 を 確認する は 真偽
b を 確認する とは b = 真 かつ b != 偽 かつ b = 偽
真偽 を 場確認する は 数
b を 場確認する とは もし b が 真 ならば 1 そうでなければ 2
数 を 同枝する は 数
n を 同枝する とは もし n > 0 ならば n + 1 そうでなければ n + 1
数 を 場同枝する は 数
n を 場同枝する とは もし n が 3 ならば 1 そうでなければ 1
数 を 自比較する は 真偽
n を 自比較する とは n = n または （もし n が n ならば 真 そうでなければ n < n）
数 を 括弧する は 数
n を 括弧する とは （n） + （（n を 二倍する）） + （n + 1） * 2 + （横 は （n） で 縦 は 2 の 点） の 横
数 を 二若する は 真偽 の リスト
n を 二若する とは （もし n > 1 ならば 真 そうでなければ 偽） と （もし n > 2 ならば 真 そうでなければ 偽） と （n < n かつ n < n）
数 を 定数する は 数
n を 定数する とは もし 真 ならば n そうでなければ 0
数 を 場同枝二する は 数
n を 場同枝二する とは
  もし n が
    1 ならば 0
    2 ならば 0
    そうでなければ 0
形状 を 場別枝する は 数
形 を 場別枝する とは
  もし 形 が
    半径 の 円 ならば 0
    そうでなければ 0
数 を 左括弧する は 数
n を 左括弧する とは （n + 1） + 2 + （n * 2） + 1 - （（n - 1） - 2） * 3
形状 とは 半径 の 円 か 辺 の 正方形
"""

SYNTAX_OUT = """\
syntax.suru:3:13: 冗長な真偽: 真か偽を返すだけの『もし』は、条件をそのまま書けます
syntax.suru:4:1: 定義の間の空行: 「逆判定する」の定義は、前の「判定する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:5:14: 冗長な真偽: 偽か真を返すだけの『もし』は、条件を『= 偽』と比べる式にできます
syntax.suru:6:1: 定義の間の空行: 「確認する」の定義は、前の「逆判定する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:7:15: 冗長な真偽: 『= 真』や『!= 偽』は付けなくても同じです
syntax.suru:7:24: 冗長な真偽: 『= 真』や『!= 偽』は付けなくても同じです
syntax.suru:8:1: 定義の間の空行: 「場確認する」の定義は、前の「確認する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:9:14: 冗長な真偽: 『もし x が 真 ならば』は『もし x ならば』と同じです
syntax.suru:10:1: 定義の間の空行: 「同枝する」の定義は、前の「場確認する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:11:13: 同じ枝: 『もし』のどちらの枝も同じ式です
syntax.suru:12:1: 定義の間の空行: 「場同枝する」の定義は、前の「同枝する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:13:14: 同じ枝: 『もし』のどちらの枝も同じ式です
syntax.suru:14:1: 定義の間の空行: 「自比較する」の定義は、前の「場同枝する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:15:16: 自分との比較: 同じ式どうしを比べているので、結果はいつも同じです
syntax.suru:15:25: 自分との比較: 同じ式どうしを比べているので、結果はいつも同じです
syntax.suru:15:50: 自分との比較: 同じ式どうしを比べているので、結果はいつも同じです
syntax.suru:16:1: 定義の間の空行: 「括弧する」の定義は、前の「自比較する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:17:13: 不要な括弧: この括弧は外しても読み方が変わりません
syntax.suru:17:19: 不要な括弧: この括弧は外しても読み方が変わりません
syntax.suru:17:53: 不要な括弧: この括弧は外しても読み方が変わりません
syntax.suru:18:1: 定義の間の空行: 「二若する」の定義は、前の「括弧する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:19:14: 冗長な真偽: 真か偽を返すだけの『もし』は、条件をそのまま書けます
syntax.suru:19:43: 冗長な真偽: 真か偽を返すだけの『もし』は、条件をそのまま書けます
syntax.suru:19:74: 自分との比較: 同じ式どうしを比べているので、結果はいつも同じです
syntax.suru:19:83: 自分との比較: 同じ式どうしを比べているので、結果はいつも同じです
syntax.suru:20:1: 定義の間の空行: 「定数する」の定義は、前の「二若する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:21:13: 定数の条件: 条件がいつも真なので、『もし』を使わずに『ならば』の後ろの式だけを書けます
syntax.suru:22:1: 定義の間の空行: 「場同枝二する」の定義は、前の「定数する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:24:3: 同じ枝: 場合分けのどの場合も『そうでなければ』と同じ式です
syntax.suru:28:1: 定義の間の空行: 「場別枝する」の定義は、前の「場同枝二する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:33:1: 定義の間の空行: 「左括弧する」の定義は、前の「場別枝する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
syntax.suru:34:14: 不要な括弧: この括弧は外しても読み方が変わりません
syntax.suru:34:43: 不要な括弧: この括弧は外しても読み方が変わりません
"""

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def run_lint(kind: str, tmp_path: pathlib.Path, *paths: str, fresh_cache: bool = False) -> subprocess.CompletedProcess:
    # 点検のバイナリは作るのに十数秒かかるので、ふだんはいつものキャッシュ(~/.cache/suru)を共有する(#230)。
    # 名前に lib と実行時の中身のハッシュが入るので、古いものを使うことはない
    env = dict(os.environ)
    if fresh_cache:
        env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
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
    r = run_lint(kind, tmp_path, "bad.suru", "good.suru", "polite.suru", fresh_cache=True)
    assert r.returncode == 1, r.stderr
    assert r.stdout == BAD_OUT.replace("DIR/", "") + (
        "polite.suru:3:3: 丁寧語の混在: 文の終わりが「する」の文が1つ、「します」の文が2つあります。「します」にそろえると読みやすくなります\n")
    r = run_lint(kind, tmp_path, "good.suru", fresh_cache=True)
    assert (r.returncode, r.stdout) == (0, "")
    if kind == "binary":
        assert len(list((tmp_path / "cache" / "suru").glob("点検-*"))) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_定義と使用(kind, tmp_path):
    (tmp_path / "型.suru").write_text(TYPES, encoding="utf-8")
    (tmp_path / "defs.suru").write_text(DEFS, encoding="utf-8")
    (tmp_path / "lib.suru").write_text(LIBRARY, encoding="utf-8")
    (tmp_path / "mixed.suru").write_text(MIXED, encoding="utf-8")
    (tmp_path / "hidden.suru").write_text(HIDDEN, encoding="utf-8")
    (tmp_path / "listed.suru").write_text(LISTED, encoding="utf-8")
    r = run_lint(kind, tmp_path, "defs.suru", "hidden.suru", "lib.suru", "listed.suru", "mixed.suru")
    assert r.returncode == 1, r.stderr
    assert r.stdout == DEFS_OUT + (
        "hidden.suru:3:1: 定義の間の空行: 「乙する」の定義は、前の「甲する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります\n"
        "hidden.suru:4:5: 未使用の定義: 「乙する」は定義されていますが、使われていません\n"
        "hidden.suru:5:1: 定義の間の空行: 「丙する」の定義は、前の「乙する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります\n"
        "lib.suru:2:1: 定義の間の空行: 「三倍する」の定義は、前の「二倍する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります\n"
        "lib.suru:2:5: 型の宣言なし: 「三倍する」に型の宣言がありません(『数 を 三倍する は 数』のように書きます)\n"
        "lib.suru:5:1: 定義の間の空行: 「二倍する」の定義は、前の「三倍する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります\n"
        "listed.suru:3:1: 定義の間の空行: 「乙する」の定義は、前の「甲する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります\n"
        "listed.suru:4:5: 未使用の定義: 「乙する」は定義されていますが、使われていません\n"
        "mixed.suru:3:1: 書き方の混在: このファイルは空白の書き方が3文、句読点の書き方が2文あります。空白の書き方にそろえると読みやすくなります\n")



@pytest.mark.parametrize("kind", KINDS)
def test_局所の名前を名前するで呼ぶのは使用(kind, tmp_path):
    # #140: 局所の定義に入れた関数を「変換する」「変換した」で呼ぶなら、使ったと数える
    (tmp_path / "local.suru").write_text(
        "値 を 発行する とは 手順\n"
        "  変換 とは （a を 受け取って a * 2 を 返すこと）\n"
        "  加工 とは （a を 受け取って a + 1 を 返すこと）\n"
        "  他 とは （a を 受け取って a * 3 を 返すこと）\n"
        "  b とは 値 を 変換する\n"
        "  （b を 加工して） を 表示する\n"
        "3 を 発行する\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "local.suru")
    assert r.stdout == "local.suru:4:3: 未使用の定義: 「他」は定義されていますが、使われていません\n", r.stderr

@pytest.mark.parametrize("kind", KINDS)
def test_値の再定義(kind, tmp_path):
    # #155: 同じ名前の値を2回定義したら2回目を知らせる。場合ごとに定義する関数と、ただし の局所の定義は知らせない
    (tmp_path / "again.suru").write_text(
        "x とは 3\nx とは 4\nx を 表示する\n"
        "0 を 数える とは 0\nn を 数える とは n\n（1 を 数える） を 表示する\n"
        "a を 甲する とは y\nただし y とは a\nb を 乙する とは y\nただし y とは b\n"
        "（1 を 甲する） + （2 を 乙する） を 表示する\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "again.suru")
    assert r.stdout == ("again.suru:2:1: 値の再定義: 「x」は前にも定義しています(後の定義が使われます)\n"
                        "again.suru:9:1: 定義の間の空行: 「乙する」の定義は、前の「甲する」の定義とのあいだに空行を入れると、"
                        "どこからが新しい定義か読みやすくなります\n"), r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_構文木の規則(kind, tmp_path):
    (tmp_path / "型.suru").write_text(TYPES, encoding="utf-8")
    (tmp_path / "syntax.suru").write_text(SYNTAX, encoding="utf-8")
    r = run_lint(kind, tmp_path, "syntax.suru")
    assert r.returncode == 1, r.stderr
    assert r.stdout == SYNTAX_OUT
    # 読めないプログラムでは構文木の規則を調べない(エラーは実行したときに出る)
    (tmp_path / "broken.suru").write_text("x とは もし 1 = 1 ならば （2）\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "broken.suru")
    assert "不要な括弧" not in r.stdout and "自分との比較" not in r.stdout


def test_例とライブラリは知らせなし(tmp_path):
    files = sorted(str(p) for p in (ROOT / "examples").glob("*.suru")) + sorted(str(p) for p in (ROOT / "lib").glob("*.suru"))
    files += sorted(str(p) for p in (ROOT / "examples" / "通信").glob("*.suru"))
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


@pytest.mark.parametrize("kind", KINDS)
def test_フォルダの中のファイルの読み込みは最後の名前で使う(kind, tmp_path):
    (tmp_path / "庫").mkdir()
    (tmp_path / "庫" / "部品.suru").write_text("x を 二倍する とは x * 2\n", encoding="utf-8")
    (tmp_path / "本体.suru").write_text("「庫/部品」 を 読み込む\n3 を 部品内の二倍して 表示する\n", encoding="utf-8")
    r = run_lint(kind, tmp_path, "本体.suru")
    assert (r.returncode, r.stdout) == (0, ""), r.stdout + r.stderr


def test_点検が使うファイルだけでキャッシュの名前を決める():
    import suru

    files = suru.lint_lib_files()
    assert {"点検.suru", "字句.suru", "構文.suru", "表.suru", "基本.suru", "標準.suru"} <= set(files)
    assert "通信.suru" not in files and "スレッド.suru" not in files

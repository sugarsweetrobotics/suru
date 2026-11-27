"""外部の関数を1行で書く(#173)・外部の関数のまとまり「以下は外部の…」(#174、前の「以下の外部の…」も)・点検の「定義の間の空行」(#175)のテスト

ここに書いたプログラムは tests/test_go_compiler.py が Go 版でも同じ IR とエラーになるかを調べる。
"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_compile  # noqa: E402

ONE_LINE = """\
外部の「m」 を 読み込む
x を y で 累乗する とは 外部の「pow」 で 小数 を 小数 で 受け取って 小数 を 返します
s を 字数計測する とは 外部の「strlen」 で 文字列 を 受け取って 整数 を 返す 入出力動作です
（2 を 10 で 累乗する） を 表示する
「あいう」 を 字数計測してから 表示する
"""

BLOCK = """\
外部の「m」 を 読み込む

以下は外部の関数です
  小数 を 余弦にする は 「cos」 で 小数 を 返します
  # 引数を並べ替えるときは名前を付けた定義の形で書きます
  x を y で 逆累乗する とは 「pow」（y と x） で 小数 を 小数 で 受け取って 小数 を 返します

  小数 を 床にする は 「floor」 で 小数 を 返す
以上です

以下 の 外部 の 入出力動作
文字列 を 文字列 で 比較する は 「strcmp」 で 整数 を 返します
文字列 を 一行出力する は 「puts」 で 整数 を 返します
以上

0 を 余弦にして 表示する
（10 を 2 で 逆累乗する） を 表示する
2.5 を 床にして 表示する
「a」 を 「a」 で 比較してから 表示する
「まとまり」 を 一行出力する
"""

PUNCT = """\
以下は外部の入出力動作です。文字列を字数計測するは、「strlen」で整数を返します。以上です。
「abc」を字数計測してから、表示する。
"""

# (プログラム, エラーの文の一部)
ERRORS = [
    ("x を y で 累乗する とは 外部の「pow」 で 小数 で 小数 を 受け取って 小数 を 返します\n",
     "「累乗する」の型の引数は、定義と同じ助詞を同じ順に書き、最後に「受け取って」を書きます(定義の助詞: を・で)"),
    ("x を 床にする とは 外部の「floor」 で 小数 を 返します\n", "定義の助詞: を"),
    ("x を 床にする とは 外部の「floor」 で 小数 を 受け取って\n", "「受け取って」の後に値の型を書きます"),
    ("x とは 外部の「floor」 で 小数 を 返します\n", "型を後ろに書けるのは関数の定義だけです"),
    ("以下は外部の入出力動作です\n  小数 を 床にする は 「floor」 で 小数 を 返す 入出力動作\n以上です\n",
     "「以下は外部の入出力動作です」の中では、値の型に「入出力動作」を書きません"),
    ("以下は外部の関数です\n  小数 を 床にする は 「floor」（を と 0） で 小数 を 返します\n以上です\n",
     "C に渡す引数を並べて書くときは、名前を付けた定義の形で書きます"),
    ("以下は外部の関数です\n  小数 を 床にする は 「floor」 で 小数 を 返します\n1 を 表示する\n",
     "「以下は外部の関数です」を閉じる「以上」がありません"),
    ("以下は外部の関数です\n以上です\n", "「以下は外部の関数です」と「以上」の間に関数がありません"),
    ("以下は外部の関数です\n  小数 を 床にする は 「floor」 で 小数 を 返します\n"
     "  小数 を 床にする は 「floor」 で 小数 を 返します\n以上です\n", "「床にする」がまとまりの中で2回書かれています(2行目と3行目)"),
    ("以下は外部の関数です\n  1 を 表示する\n以上です\n", "「以下は外部の関数です」の中には、1行に1つ"),
    ("x とは 1\n  以下は外部の関数です\n", "「以下は外部の関数です」は一番外(字下げなし)に書きます"),
    ("以下の外部の関数です\n以上です\n", "「以下の外部の関数です」と「以上」の間に関数がありません"),
]


def run_interp(tmp_path: pathlib.Path, source: str, *args: str) -> subprocess.CompletedProcess:
    path = tmp_path / "prog.suru"
    path.write_text(source, encoding="utf-8")
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), *args, str(path)], capture_output=True, text=True,
                          timeout=300)


@pytest.mark.parametrize("source, out", [
    (ONE_LINE, "1024\n9\n"),
    (BLOCK, "1\n1024\n2\n0\nまとまり\n"),
    (PUNCT, "3\n"),
])
def test_インタプリタとコンパイルしたもので同じ(tmp_path, source, out):
    r = run_interp(tmp_path, source)
    assert (r.returncode, r.stdout) == (0, out), r.stderr
    assert run_interp(tmp_path, source, "--検査").returncode == 0
    if suru_compile.find_cc() is None:
        return
    exe = tmp_path / "prog"
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(tmp_path / "prog.suru"), "-o", str(exe)],
                   check=True)
    r = subprocess.run([suru_compile.exe_path(str(exe))], capture_output=True, text=True, timeout=60)
    assert (r.returncode, r.stdout) == (0, out)


def test_今までの2行の書き方と同じ構文木():
    """1行の書き方とまとまりは、型の宣言と定義の2行に直して読む"""
    two = suru.parse_program(
        "外部の「m」 を 読み込む\n小数 を 余弦にする は 小数\nx を 余弦にする とは 外部の「cos」\n"
        "文字列 を 字数計測する は 整数 を 返す 入出力動作\ns を 字数計測する とは 外部の「strlen」\n")
    one = suru.parse_program(
        "外部の「m」 を 読み込む\nx を 余弦にする とは 外部の「cos」 で 小数 を 受け取って 小数 を 返します\n"
        "以下は外部の入出力動作です\n  文字列 を 字数計測する は 「strlen」 で 整数 を 返します\n以上です\n")
    sigs = lambda ss: [(s.name, s.params, s.result) for s in ss if isinstance(s, suru.TypeSig)]  # noqa: E731
    assert sigs(one) == sigs(two)
    externs = lambda ss: [(s.name, s.body.symbol, s.body.params, s.body.result, s.body.action)  # noqa: E731
                          for s in ss if isinstance(s, suru.Define)]
    assert externs(one) == externs(two)


@pytest.mark.parametrize("source, message", ERRORS)
def test_書き方を案内するエラー(tmp_path, source, message):
    r = run_interp(tmp_path, source, "--検査")
    assert r.returncode == 1
    assert message in r.stderr


def test_対話モードは以上まで読む():
    lines = ["以下は外部の入出力動作です", "  文字列 を 字数計測する は 「strlen」 で 整数 を 返します"]
    assert not suru.Repl.complete(lines)
    assert suru.Repl.complete(lines + ["以上です"])


KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

BLANK = """\
外部の「m」 を 読み込む

数 を 確保する は 番地 を 返す 入出力動作
n を 確保する とは 外部の「SDL_malloc」
番地 を 解放する は 無 を 返す 入出力動作
p を 解放する とは 外部の「SDL_free」
x を y で 累乗する とは 外部の「pow」 で 小数 を 小数 で 受け取って 小数 を 返します
x を y で 累乗二する とは 外部の「powf」 で 小数 を 小数 で 受け取って 小数 を 返します
以下は外部の関数です
  小数 を 余弦にする は 「cos」 で 小数 を 返します
以上です
# 注釈は次の定義の一部です
数 を 三倍する は 数
x を 三倍する とは x * 3

# 注釈の上に空行があれば知らせません
数 を 四倍する は 数
x を 四倍する とは x * 4
数 を 五倍する は 数
0 を 五倍する とは 0
n を 五倍する とは n * 5
税率 とは 0.1
数 を 六倍する は 数
x を 六倍する とは x * 6
数 を 七倍する は 数 # 点検しない: 定義の間の空行
x を 七倍する とは x * 7
"""

BLANK_OUT = """\
blank.suru:5:1: 定義の間の空行: 「解放する」の定義は、前の「確保する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
blank.suru:7:1: 定義の間の空行: 「累乗する」の定義は、前の「解放する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
blank.suru:9:1: 定義の間の空行: 外部の関数のまとまりは、前の「累乗二する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
blank.suru:13:1: 定義の間の空行: 「三倍する」の定義は、前の外部の関数のまとまりとのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
blank.suru:19:1: 定義の間の空行: 「五倍する」の定義は、前の「四倍する」の定義とのあいだに空行を入れると、どこからが新しい定義か読みやすくなります
"""


@pytest.mark.parametrize("kind", KINDS)
def test_点検の定義の間の空行(kind, tmp_path):
    (tmp_path / "blank.suru").write_text(BLANK, encoding="utf-8")
    env = dict(os.environ)  # 点検のバイナリはいつものキャッシュを共有する(#230)
    if kind == "interp":
        env["SURU_LINT_INTERP"] = "1"
    else:
        env.pop("SURU_LINT_INTERP", None)
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--点検", "blank.suru"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 1, r.stderr
    assert r.stdout == BLANK_OUT

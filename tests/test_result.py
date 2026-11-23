"""成否・有無(lib/基本.suru)のテスト: インタプリタとコンパイルしたバイナリで同じ結果になるか"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_check  # noqa: E402
import suru_compile  # noqa: E402

DIV = """a と b を 安全除算する とは
  もし b が 0 ならば 「0 では割れません」 の 失敗
  そうでなければ （a / b） の 成功
x を 倍化する とは x * 2
"""

BASIC = DIV + """10 と 2 を 安全除算する
10 と 0 を 安全除算する
（10 と 2 を 安全除算する） を 取出する
（3 の 有） を 取出する
（3 の 有） を 「ない」 で 成否にする
無 を 「ない」 で 成否にする
（10 と 2 を 安全除算する） を 有無にする
（10 と 0 を 安全除算する） を 有無にする
（10 と 2 を 安全除算する） の 結果 を 倍化する
（10 と 0 を 安全除算する） の 結果 を 倍化する
（3 の 有） を 倍化すること で 写像する
手順（xとは、10と2を安全除算した結果。yとは、xと0を安全除算した結果。x+yを結果にする）。
手順（xとは、10と2を安全除算した結果。yとは、xと1を安全除算した結果。x+yを結果にする）。
"""

BASIC_OUT = """（値 は 5 の 成功）
（理由 は 「0 では割れません」 の 失敗）
5
3
（値 は 3 の 成功）
（理由 は 「ない」 の 失敗）
（値 は 5 の 有）
無
（値 は 10 の 成功）
（理由 は 「0 では割れません」 の 失敗）
（値 は 6 の 有）
（理由 は 「0 では割れません」 の 失敗）
（値 は 10 の 成功）
"""


def run_both(source: str, tmp_path: pathlib.Path):
    src = tmp_path / "prog.suru"
    src.write_text(source, encoding="utf-8")
    out = [subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=120)]
    if suru_compile.find_cc() is not None:
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "prog")], check=True)
        out.append(subprocess.run([str(tmp_path / "prog")], capture_output=True, text=True, timeout=60))
    return out


def test_成否と有無(tmp_path):
    for r in run_both(BASIC, tmp_path):
        assert (r.returncode, r.stdout, r.stderr) == (0, BASIC_OUT, "")


def test_失敗を取り出すと実行時エラー(tmp_path):
    for r in run_both(DIV + "（10 と 0 を 安全除算する） を 取出する\n", tmp_path):
        assert r.returncode == 1
        assert "失敗を取り出しました(0 では割れません)" in r.stderr
    for r in run_both("無 を 取出する\n", tmp_path):
        assert r.returncode == 1
        assert "無を取り出しました" in r.stderr


def test_中断するは実行時エラー(tmp_path):
    for r in run_both("x を 検査する とは もし x > 0 ならば x そうでなければ 「正ではありません」 を 中断する\n"
                      "3 を 検査する\n0 を 検査する\n", tmp_path):
        assert (r.returncode, r.stdout) == (1, "3\n")
        assert "正ではありません" in r.stderr


def test_型():
    suru_check.check(DIV + "r は （数 と 文字列） の 成否\nr とは 10 と 2 を 安全除算する\n"
                     "o は 数 の 有無\no とは r を 有無にする\n")
    with pytest.raises(suru.SuruError) as e:
        suru_check.check("（1 の 有） と （「a」 の 有）\n")
    assert "数 の 有無 と 文字列 の 有無" in str(e.value)
    with pytest.raises(suru.SuruError):
        suru_check.check("（1 の 成功） を 「a」 で 成否にする\n")


def test_使わなければ読み込まない():
    assert not any(isinstance(s, suru.Import) for s in suru.parse_program("1 を 表示する\n"))
    prog = suru.parse_program("x とは 3 の 有\n")
    assert isinstance(prog[0], suru.Import) and prog[0].module.name == "基本" and prog[0].open


def test_前置きを付けても使える(tmp_path):
    for r in run_both("（3 の 成功） を 基本内の有無にする\n", tmp_path):
        assert (r.returncode, r.stdout) == (0, "（値 は 3 の 有）\n")


def test_同じ名前の形はエラー():
    with pytest.raises(suru.SuruError) as e:
        suru.parse_program("答え とは 値 の 成功 か 駄目\n")
    assert "形「成功」は既に型「成否」で使われています" in str(e.value)


def test_自分で定義した関数が優先(tmp_path):
    for r in run_both("x を 有無にする とは x + 1\n（3 の 成功） を 基本内の有無にする\n1 を 有無にする\n", tmp_path):
        assert (r.returncode, r.stdout) == (0, "（値 は 3 の 有）\n2\n")


def test_取出するは定義し直せない(tmp_path):
    src = tmp_path / "prog.suru"
    src.write_text("y とは 3 の 有\nx を 取出する とは x + 1\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True)
    assert r.returncode == 1 and "「取出する」は形か性質の関数の名前なので、定義し直せません" in r.stderr

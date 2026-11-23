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


# --- 段階2: 「した 中身」 ----------------------------------------------------

UNWRAP = DIV + """x と y と z を 計算する とは （x と y を 安全除算した 中身） と z を 安全除算する
100 と 5 と 2 を 計算する
100 と 0 と 2 を 計算する
100 と 5 と 0 を 計算する
xとyとzを計算二するとは、（q+1）の成功。ただし、pとは、xとyを安全除算した中身。ただし、qとは、pとzを安全除算した中身。
100 と 5 と 2 を 計算二する
100 と 0 と 2 を 計算二する
f とは （x を 受け取って （（x と 0 を 安全除算した 中身） + 1） の 成功 を 返すこと）
f を 3 に 適用する
n を 一つ足する とは （（n を 正有化した 中身） + 1） の 有
n を 正有化する とは もし n > 0 ならば n の 有 そうでなければ 無
3 を 一つ足する
-3 を 一つ足する
"""

UNWRAP_OUT = """（値 は 10 の 成功）
（理由 は 「0 では割れません」 の 失敗）
（理由 は 「0 では割れません」 の 失敗）
（値 は 11 の 成功）
（理由 は 「0 では割れません」 の 失敗）
（理由 は 「0 では割れません」 の 失敗）
（値 は 4 の 有）
無
"""

IO_UNWRAP = DIV + """b を 読取する とは 手順
  「読みます」 を 表示する
  （10 と b を 安全除算する） を 結果にする
b を 処理する とは 手順
  x とは b を 読取した 中身
  y とは x と 2 を 安全除算した 中身
  （「答え 」 + （y を 文字列化する）） を 表示する
  （y の 成功） を 結果にする
2 を 処理してから 表示する
0 を 処理してから 表示する
手順（xとは、10と0を安全除算した中身。xを表示する）。
「ここには来ない」 を 表示する
"""

IO_UNWRAP_OUT = """読みます
答え 2.5
（値 は 2.5 の 成功）
読みます
（理由 は 「0 では割れません」 の 失敗）
"""


def test_した中身(tmp_path):
    for r in run_both(UNWRAP, tmp_path):
        assert (r.returncode, r.stdout, r.stderr) == (0, UNWRAP_OUT, "")


def test_手順の中のした中身(tmp_path):
    for r in run_both(IO_UNWRAP, tmp_path):
        assert (r.returncode, r.stdout, r.stderr) == (1, IO_UNWRAP_OUT, "エラー: 0 では割れません\n  経路:\n    15行目 一番外\n")


@pytest.mark.parametrize("src, msg", [
    ("x を 計算する とは （x と 2 を 安全除算した 中身） + 1",
     "「計算する」の値の型が合いません(（甲 と 文字列） の 成否 と 数)"),
    ("y とは 4 と 2 を 安全除算した 中身",
     "「した 中身」の失敗を返す先がありません(成否か有無を返す関数か手順の中で使ってください)"),
    ("x を 計算する とは （x を 倍化した 中身） の 成功", "「倍化した 中身」: 数は成否でも有無でもありません"),
    ("x を 計算する とは もし x > 0 ならば （x と 2 を 安全除算した 中身） の 有 そうでなければ 無",
     "「計算する」の値の型が合いません(（甲 と 文字列） の 成否 と 数 の 有無)"),
    ("計算する とは 手順\n  もし 1 > 0 ならば （1 と 0 を 安全除算した 中身） を 表示する そうでなければ 2 を 表示する",
     "「した 中身」は手順の文の中では条件分岐の枝の中に書けません(そこを「手順（…）」で囲みます)"),
    ("計算する とは 手順\n  x とは 1 と 0 を 安全除算した 中身\n  x + 1 を 結果にする",
     "「した 中身」を使う手順の値は（（甲 と 文字列） の 成否） の 動作になりますが、数 を 結果にしたものになっています"),
    ("計算する とは 3 を 表示してから 3 と 0 を 安全除算した 中身 を 表示する",
     "「した 中身」の失敗を返す先がありません(成否か有無を返す関数か手順の中で使ってください)"),
])
def test_した中身の型の間違い(src, msg):
    with pytest.raises(suru.SuruError) as e:
        suru_check.check(DIV + src + "\n")
    assert msg in str(e.value)


def test_した中身の後には結果か中身():
    with pytest.raises(suru.SuruError) as e:
        suru.parse_program("入力した 中\n")
    assert "「入力した」の後には「結果」か「中身」を書いてください" in str(e.value)


# --- 段階3: 「で」を省いた 試行する --------------------------------------------

TRY = """「標準」 を 読み込んで 使う
「ファイル」 を 読み込む
道 を 本文読取する とは 手順
  本文 とは （道 を ファイル内の読込する） を 試行した 中身
  （本文 の 長さ） の 成功 を 結果にする
「無い.txt」 を 本文読取してから 表示する
（「12」 を 数値にして 結果にする） を 試行してから 表示する
（「a」 を 失敗する） を 試行してから 表示する
（「a」 を 失敗する） を （「代わり」 を 表示する） で 試行する
手順（nとは、「無い.txt」を本文読取した中身。nを表示する）。
「ここには来ない」 を 表示する
"""

TRY_OUT = """（理由 は 「ファイル『無い.txt』を開くのに失敗しました(No such file or directory)」 の 失敗）
（値 は 12 の 成功）
（理由 は 「a」 の 失敗）
代わり
"""


def test_でを省いた試行するは成否を返す(tmp_path):
    for r in run_both(TRY, tmp_path):
        assert (r.returncode, r.stdout) == (1, TRY_OUT)
        assert r.stderr == ("エラー: 9行目 8文字目: a\nエラー: ファイル『無い.txt』を開くのに失敗しました(No such file or directory)\n"
                             "  経路:\n    4行目 本文読取する\n    10行目 一番外\n")


def test_でを省いた試行するの型():
    suru_check.check("「標準」 を 読み込んで 使う\nr は （数 と 文字列） の 成否 の 動作\nr とは （1 を 結果にする） を 試行する\n")
    with pytest.raises(suru.SuruError):
        suru_check.check("「標準」 を 読み込んで 使う\nr は 数 の 動作\nr とは （1 を 結果にする） を 試行する\n")


def test_でのある試行するは基本を読み込まない():
    prog = suru.parse_program("「標準」 を 読み込んで 使う\n（1 を 表示する） を （2 を 表示する） で 試行する\n")
    assert not any(isinstance(s, suru.Import) and s.auto for s in prog)


# --- 段階4: 失敗の連鎖の表示 ----------------------------------------------------

CHAIN = """n を 範囲確認する とは
  もし n < 1 または n > 65535 ならば 「番号は 1〜65535 です」 の 失敗
  そうでなければ n の 成功
s を 番号読取する とは （s を 数値にする） を 範囲確認する
s を 設定読込する とは （s を 番号読取した 中身） の 成功
s を 起動準備する とは （（s を 設定読込する） を 「設定を読む」 で 失敗説明した 中身） の 成功
（「70000」 を 起動準備する） を 失敗詳細にする
「70000」 を 起動準備する
（「70000」 を 起動準備する） が （「番号は 1〜65535 です」 の 失敗）
（「80」 を 起動準備する）
（（「80」 を 起動準備する） を 「使わない」 で 失敗説明する）
s を 手順読込する とは 手順
  「読みます」 を 表示する
  p とは s を 設定読込した 中身
  （p の 成功） を 結果にする
手順（rとは、「0」を手順読込した結果。（rを失敗詳細にする）を表示する）。
手順（xとは、「70000」を起動準備した中身。xを表示する）。
「ここには来ない」 を 表示する
"""

CHAIN_OUT = """設定を読むのに失敗しました
  原因: 番号は 1〜65535 です
  経路:
    5行目 設定読込する
    6行目 起動準備する
（理由 は 「番号は 1〜65535 です」 の 失敗）
真
（値 は 80 の 成功）
（値 は 80 の 成功）
読みます
番号は 1〜65535 です
  経路:
    5行目 設定読込する
    14行目 手順読込する
"""

CHAIN_ERR = """エラー: 設定を読むのに失敗しました
  原因: 番号は 1〜65535 です
  経路:
    5行目 設定読込する
    6行目 起動準備する
    17行目 一番外
"""


def test_失敗の連鎖(tmp_path):
    for r in run_both(CHAIN, tmp_path):
        assert (r.returncode, r.stdout, r.stderr) == (1, CHAIN_OUT, CHAIN_ERR)


def test_失敗詳細にするは失敗だけ(tmp_path):
    for r in run_both("（3 の 成功） を 失敗詳細にする\n", tmp_path):
        assert r.returncode == 1
        assert "「失敗詳細にする」の「を」は失敗の値でなければなりません" in r.stderr


def test_失敗説明するの型():
    suru_check.check("r は （数 と 文字列） の 成否\nr とは （1 の 成功） を 「読む」 で 失敗説明する\n"
                     "s は 文字列\ns とは r を 失敗詳細にする\n")
    with pytest.raises(suru.SuruError):
        suru_check.check("（1 の 成功） を 3 で 失敗説明する\n")
    with pytest.raises(suru.SuruError):
        suru_check.check("3 を 失敗詳細にする\n")


# --- 段階5: 数値確認する と JSON解析する --------------------------------------

NUMCHECK = """「12」 を 数値確認する
「１２.5」 を 数値確認する
「abc」 を 数値確認する
x と y を 文字加算する とは （（x を 数値確認した 中身） + （y を 数値確認した 中身）） の 成功
「3」 と 「4」 を 文字加算する
「3」 と 「x」 を 文字加算する
「JSON」 を 読み込んで 使う
v を 項目読取する とは （（v を JSON解析した 中身） から 「a」 を JSON取得する） の 成功
「{"a": 1}」 を 項目読取する
「{"a": 」 を 項目読取する
"""

NUMCHECK_OUT = """（値 は 12 の 成功）
（値 は 12.5 の 成功）
（理由 は 「「abc」は数値にできません」 の 失敗）
（値 は 7 の 成功）
（理由 は 「「x」は数値にできません」 の 失敗）
（値 は （数値 は 1 の JSON数） の 成功）
（理由 は 「JSON を読めません(閉じていない『[』か『{』があります)」 の 失敗）
"""


def test_数値確認するとJSON解析する(tmp_path):
    for r in run_both(NUMCHECK, tmp_path):
        assert (r.returncode, r.stdout, r.stderr) == (0, NUMCHECK_OUT, "")


def test_数値確認するの型():
    suru_check.check("r は （数 と 文字列） の 成否\nr とは 「1」 を 数値確認する\n")
    with pytest.raises(suru.SuruError):
        suru_check.check("3 を 数値確認する\n")
    suru_check.check("「JSON」 を 読み込んで 使う\nr は （JSON と 文字列） の 成否\nr とは 「1」 を JSON解析する\n")

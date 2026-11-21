"""静的な型検査(suru_check.py)のテスト"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import SuruError  # noqa: E402
from suru_check import check  # noqa: E402


def _err(src: str) -> SuruError:
    with pytest.raises(SuruError) as info:
        check(src)
    return info.value


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*.suru")), ids=lambda p: p.name)
def test_例はすべて検査を通る(path):
    check(path.read_text(encoding="utf-8"))


def test_引数の型の間違い():
    e = _err("x を 三倍する とは x * 3\n「あ」 を 三倍する")
    assert (e.line, e.col) == (2, 7)
    assert "「三倍する」の「を」には数が必要ですが、文字列が渡されています" in str(e)


def test_足りない引数と余分な引数():
    assert "「で」の引数が必要です" in str(_err("a を b で 割数する とは a / b\n1 を 割数する"))
    assert "「に」の引数を受け取りません" in str(_err("a を 三倍する とは a * 3\n1 を 2 に 三倍する"))


def test_型の混ざったリストはエラー():
    e = _err("1 と 「a」")
    assert e.line == 1 and "リストの要素の型がそろっていません(数 と 文字列)" in str(e)


def test_文字列と数は足せない():
    assert "文字列化する" in str(_err("「答えは」 + 3"))
    check("「答えは」 + （3 を 文字列化する）")


def test_条件分岐の型():
    assert "「ならば」と「そうでなければ」の値の型が違います" in str(_err("もし 真 ならば 1 そうでなければ 「a」"))
    assert "「もし」の条件には真偽が必要" in str(_err("もし 1 ならば 1 そうでなければ 2"))


def test_比較():
    assert "比べられません" in str(_err("1 が 「a」"))
    assert "「<」の右には数が必要" in str(_err("1 < 「a」"))


def test_多相な関数():
    check("x を 恒等にする とは x\n1 を 恒等にする\n「a」 を 恒等にする\n（1 を 恒等にする） + 1")


def test_相互再帰():
    check(
        "n が 偶である とは もし n が 0 ならば 真 そうでなければ n - 1 が 奇である\n"
        "n が 奇である とは もし n が 0 ならば 偽 そうでなければ n - 1 が 偶である\n10 が 偶である"
    )


def test_組のフィールド():
    assert "「+」の両側の型が違います" in str(_err("点 とは 横 と 縦 の 組\np とは 1 と 2 の 点\np の 横 + 「a」"))
    assert "「点」の「横」は数ですが、文字列が渡されています" in str(
        _err("点 とは 横 と 縦 の 組\n1 と 2 の 点\n「a」 と 「b」 の 点")
    )


def test_場合分けの値の型():
    src = (
        "図形 とは 半径 の 円 か 幅 と 高 の 長方形\n形 を 面積にする とは\n  もし 形 が\n"
        "    r の 円 ならば r * r\n    w と h の 長方形 ならば 「x」"
    )
    assert "場合ごとの値の型がそろっていません" in str(_err(src))


def test_場合ごとの定義():
    src = "0 を 階乗する とは 1\nn を 階乗する とは n * （n - 1 を 階乗する）\n"
    check(src + "5 を 階乗する")
    assert "「階乗する」の「を」には数が必要" in str(_err(src + "「a」 を 階乗する"))


def test_述語():
    check("x が 偶数である とは x % 2 が 0\n1 と 2 から 偶数であること で 選別する")
    assert "述語「変である」の値には真偽が必要" in str(_err("n が 変である とは n + 1"))


def test_高階関数():
    check("1 と 2 と 3 を 0 から 加算すること で 畳み込みする")
    assert "「選別する」の「で」の関数の値には真偽が必要" in str(
        _err("x を 三倍する とは x * 3\n1 と 2 から 三倍すること で 選別する")
    )
    assert "数を受け取りますが、文字列が渡されます" in str(_err("（1 を 加算すること） を 「a」 に 適用する"))
    assert "数を受け取りますが、文字列が渡されます" in str(
        _err("（x を 受け取って x * 2 を 返すこと） を 「a」 に 適用する")
    )


def test_それぞれ():
    src = "x を 三倍する とは x * 3\n"
    check(src + "（1 と 2） の それぞれ を 三倍する")
    assert "「三倍する」の「を」には数が必要" in str(_err(src + "（「a」 と 「b」） の それぞれ を 三倍する"))


def test_長さは文字列にもリストにも使える():
    check("「abc」 の 長さ\n（1 と 2） の 長さ")
    assert "「の 長さ」の前は文字列かリスト" in str(_err("5 の 長さ"))


def test_コマンドラインで検査する(tmp_path, capsys):
    import suru

    ok = tmp_path / "ok.suru"
    ok.write_text("1 + 2\n", encoding="utf-8")
    assert suru.main(["suru.py", "--検査", str(ok)]) == 0
    assert "問題は見つかりませんでした" in capsys.readouterr().out
    bad = tmp_path / "bad.suru"
    bad.write_text("1 + 「a」\n", encoding="utf-8")
    assert suru.main(["suru.py", "--検査", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "1行目" in err and "^" in err

"""lib/算術.suru と lib/乱数.suru のテスト: インタプリタとコンパイルしたバイナリで同じ結果になるか"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

MATH = '「算術」 を 読み込んで 使う\n算術内の円周率\n0 を 正弦にする\n円周率 / 2 を 正弦にする\n1 を 逆正接にする\n1 を -1 で 偏角にする\n1 を 指数関数にする\n100 を 常用対数にする\n8 を 2 で 対数にする\n2 を 0.5 で 累乗する\n27 を 立方根にする\n円周率 を 度にする\n180 を ラジアンにする\n12 を 18 で 最大公約数にする\n4 を 6 で 最小公倍数にする\n20 を 階乗する\n-3 を 符号にする\n-1 を 自然対数にする\n'

MATH_OUT = '3.141592653589793\n0\n1\n0.7853981633974483\n2.356194490192345\n2.718281828459045\n2\n3\n1.4142135623730951\n3.0000000000000004\n180\n3.141592653589793\n6\n12\n2432902008176640000\n-1\nnan\n'

RANDOM = '「乱数」 を 読み込んで 使う\n1 を 種更新する\n0 を 種にする\n42 を 一様にする\n1 から 6 を 12345 で 整数乱数にする\n5 を 1 で 乱数列作成する\n（1 と 2 と 3 と 4 と 5） を 7 で 混合する\n（「赤」 と 「青」 と 「緑」） から 99 で 選択する\n試す とは 手順\n  s とは OS乱数取得した 結果\n  （s > 0 かつ s < 2147483647） を 表示する\n試す\n'

RANDOM_OUT = '96542\n1\n1.9557774085139645e-08\n5\n（96542 と 365259859 と 617960190 と 1008522931 と 1103656729）\n（4 と 2 と 5 と 1 と 3）\n青\n真\n'


@pytest.mark.parametrize("source, want", [(MATH, MATH_OUT), (RANDOM, RANDOM_OUT)], ids=["算術", "乱数"])
def test_インタプリタとバイナリで同じ(source, want, tmp_path):
    src = tmp_path / "prog.suru"
    src.write_text(source, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == want
    if suru_compile.find_cc() is None:
        pytest.skip("clang がありません")
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "prog")], check=True)
    r = subprocess.run([str(tmp_path / "prog")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == want


def test_混合しても中身は同じ(tmp_path):
    src = tmp_path / "prog.suru"
    src.write_text("「乱数」 を 読み込んで 使う\n「標準」 を 読み込んで 使う\n"
                   "（（1 から 30 を 範囲にする） を 2024 で 混合して 整列する） = （1 から 30 を 範囲にする）\n"
                   "（1 から 200 を 範囲にする） を （n を 受け取って （1 から 6 を n で 整数乱数にする） を 返すこと） で 写像して 一意にして 整列する\n",
                   encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60)
    assert r.stdout == "真\n（1 と 2 と 3 と 4 と 5 と 6）\n", r.stderr

"""lib/JSON.suru と 標準 の数の書式のテスト: インタプリタとコンパイルしたバイナリで同じ結果になるか"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

JSON_PROGRAM = '「JSON」 を 読み込んで 使う\n「標準」 を 読み込んで 使う\n文字列 を 往復する は 文字列\ns を 往復する とは\n  もし （s を JSON解析する） が\n    v の 成功 ならば v を JSON文字列にする\n    m の 失敗 ならば m\n「 [ 1.5e3 , -0 , 0.25, 1E-2 ] 」 を 往復する\n「"tab\\there\\u0001\\/"」 を 往復する\n「"\\ud83d"」 を 往復する\n「"\\u12"」 を 往復する\n「"\\u12G4"」 を 往復する\n「{"a":{"b":{"c":[[],[{}]]}}}」 を 往復する\n「{"k": 1, "k": 2}」 を 往復する\n「truex」 を 往復する\n「[1,]」 を 往復する\n「{,}」 を 往復する\n「{"a":}」 を 往復する\n「{"a"}」 を 往復する\n「]」 を 往復する\n「"a\\\\"」 を 往復する\n「"a\\\\\\"b"」 を 往復する\n「"a\\」 を 往復する\nv とは （（「名前」 と （「花子」 の JSON文字列） の JSON項目） と （「点」 と （（（90 の JSON数） と （85.5 の JSON数）） の JSON配列） の JSON項目）） の JSON物\nv を JSON整形する\n（v から 「名前」 を JSON取得する）\n（v から 「無い」 を JSON取得する）\n（（v から 「点」 を JSON取得する） から 2 を JSON番目取得する）\n（（v から 「点」 を JSON取得する） から 3 を JSON番目取得する）\n（JSON無 から 1 を JSON番目取得する）\n（（「改行」 + 改行 + 「と」 + （9 を 文字にする）） の JSON文字列） を JSON文字列にする\n試す とは 手順\n  x とは 「[1, 2」 を JSON読取した 結果\n  x を JSON文字列にして 表示する\n（試す） を （「読めませんでした」 を 表示する） で 試行する\n'

JSON_OUT = '[1500,0,0.25,0.01]\n"tab\\there\\u0001/"\n"�"\nJSON を読めません(文字列の終わりで『\\』が途中です)\nJSON を読めません(『\\u』の後に十六進の数字でない『G』があります)\n{"a":{"b":{"c":[[],[{}]]}}}\n{"k":1,"k":2}\nJSON を読めません(『truex』は JSON の値ではありません)\nJSON を読めません(『]』をここには書けません)\nJSON を読めません(『,』をここには書けません)\nJSON を読めません(『}』をここには書けません)\nJSON を読めません(『}』をここには書けません)\nJSON を読めません(『]』をここには書けません)\n"a\\\\"\n"a\\\\\\"b"\nJSON を読めません(文字列が閉じていません)\n{\n  "名前": "花子",\n  "点": [\n    90,\n    85.5\n  ]\n}\n（文字値 は 「花子」 の JSON文字列）\nJSON無\n（数値 は 85.5 の JSON数）\nJSON無\nJSON無\n"改行\\nと\\t"\n読めませんでした\n'

FORMAT_PROGRAM = '「標準」 を 読み込んで 使う\n（「ab」 を 3 で 反復する） を 表示する\n（「[」 + （「ab」 を 5 で 右詰する） + 「]」） を 表示する\n（「[」 + （「ab」 を 5 で 左詰する） + 「]」） を 表示する\n（「[」 + （「abcdef」 を 3 で 右詰する） + 「]」） を 表示する\n（42 を 5 で 零詰する） を 表示する\n（-42 を 5 で 零詰する） を 表示する\n（3.14159 を 2 で 小数書式にする） を 表示する\n（2 を 3 で 小数書式にする） を 表示する\n（-0.004 を 2 で 小数書式にする） を 表示する\n（-1.005 を 1 で 小数書式にする） を 表示する\n（2.5 を 0 で 小数書式にする） を 表示する\n（0.05 を 1 で 小数書式にする） を 表示する\n（1234567 を 桁区切りする） を 表示する\n（-1234.5 を 桁区切りする） を 表示する\n（999 を 桁区切りする） を 表示する\n（「{}さん、{}歳です。{}」 を （「花子」 と 「12」） で 差込する） を 表示する\n（「{}」 を （「a」 と 「b」） で 差込する） を 表示する\n（「なし」 を 空 で 差込する） を 表示する\n'

FORMAT_OUT = 'ababab\n[   ab]\n[ab   ]\n[abcdef]\n00042\n-0042\n3.14\n2.000\n0.00\n-1.0\n3\n0.1\n1,234,567\n-1,234.5\n999\n花子さん、12歳です。{}\na\nなし\n'

# 長い配列と長い文字列でも再帰が深くならない(畳み込みで読む)
LONG = """「JSON」 を 読み込んで 使う
本文 とは 「[」 + （（1 から 3000 を 範囲にする） を （i を 受け取って 「{"id": 」 + （i を 文字列化する） + 「}」 を 返すこと） で 写像して 「,」 で 結合する） + 「]」
長文 とは 「"」 + （（「あ」 を 20000 で 複製する） を 「」 で 結合する） + 「"」
試す とは 手順
  v とは 本文 を JSON読取した 結果
  （v から 3000 を JSON番目取得して JSON文字列にする） を 表示する
  w とは 長文 を JSON読取した 結果
  （w を JSON文字列にする） の 長さ を 表示する
試す
"""


def run_both(source: str, tmp_path: pathlib.Path):
    src = tmp_path / "prog.suru"
    src.write_text(source, encoding="utf-8")
    out = [subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=120)]
    if suru_compile.find_cc() is not None:
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "prog")], check=True)
        out.append(subprocess.run([str(tmp_path / "prog")], capture_output=True, text=True, timeout=60))
    return out


def test_JSON(tmp_path):
    for r in run_both(JSON_PROGRAM, tmp_path):
        assert r.returncode == 0, r.stderr
        assert r.stdout == JSON_OUT
        assert "JSON を読めません(閉じていない『[』か『{』があります)" in r.stderr


def test_長いJSON(tmp_path):
    for r in run_both(LONG, tmp_path):
        assert r.returncode == 0, r.stderr
        assert r.stdout == '{"id":3000}\n20002\n'


def test_数の書式(tmp_path):
    for r in run_both(FORMAT_PROGRAM, tmp_path):
        assert r.returncode == 0, r.stderr
        assert r.stdout == FORMAT_OUT

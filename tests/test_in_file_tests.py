"""同じファイルの試験と例(#193): 「以下は「二倍」の試験です … 以上です」と「例えば … は … です」、suru --試験"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from suru import Interpreter, SuruError  # noqa: E402
from suru_check import check  # noqa: E402

CALC = """\
# x の2倍を返します。
数 を 二倍する は 数
x を 二倍する とは x * 2
例えば （2 を 二倍する） は 4 です
例えば （-3 を 二倍する） は -6

数 を 加一する は 数
x を 加一する とは x + 1

以下は「二倍」の試験です
  （2 を 二倍する） を 4 に 一致確認する
  （0 を 加一する） を 1 に 一致確認する
  以上です

加一する は 非公開とする。
"""


def _err(src: str) -> str:
    with pytest.raises(SuruError) as info:
        check(src)
    return str(info.value)


def _suru(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), *args], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8")


@pytest.fixture(scope="module")
def suruc(tmp_path_factory):
    import suru_compile

    if shutil.which("go") is None or suru_compile.find_cc() is None:
        pytest.skip("go か clang がありません")
    exe = tmp_path_factory.mktemp("go") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return exe


@pytest.fixture(params=["suru", "suruc"])
def runner(request):
    """試験を動かす道具: suru --試験(インタプリタ)と suruc --試験(ファイルごとにバイナリ)"""
    if request.param == "suru":
        return lambda *args, cwd: _suru("--試験", *args, cwd=cwd)
    exe = request.getfixturevalue("suruc")
    return lambda *args, cwd: subprocess.run([str(exe), "--試験", *args], cwd=cwd, capture_output=True,
                                             text=True, encoding="utf-8")


def test_通常の実行では試験と例を行わない():
    src = CALC + "（5 を 二倍する） を 表示する\n"
    check(src)
    assert Interpreter().run_text(src) == []
    # 試験のまとまりの中の文は行わない(表示しない)
    out = Interpreter().run_text("以下は「a」の試験です\n  「中」 を 表示する\n  以上です\n「外」\n")
    assert out == ["外"]


def test_空白で区切った頭も読む():
    check("以下 は 「a」 の 試験 です\n  1 < 2 を 確認する\n  以上です\n")


def test_試験と例の型を検査する():
    assert "比べられません" in _err("数 を 二倍する は 数\nx を 二倍する とは x * 2\n例えば （2 を 二倍する） は 「4」 です\n")
    assert "数が必要" in _err("以下は「a」の試験です\n  （1 + 1） を 「2」 に 一致確認する\n  以上です\n")


def test_書き方の間違い():
    assert "以上" in _err("以下は「a」の試験です\n  1 < 2 を 確認する\n")
    assert "一番外" in _err("外側する とは 以下の手順です\n  以下は「a」の試験です\n    1 < 2 を 確認する\n    以上です\n  以上です\n")
    assert "例えば 式 は 期待する値" in _err("例えば 3\n")
    assert "一番外" in _err("外側する とは 以下の手順です\n  例えば 1 は 1\n  以上です\n")
    assert "1行目にも" in _err("以下は「a」の試験です\n  1 < 2 を 確認する\n  以上です\n"
                              "以下は「a」の試験です\n  1 < 2 を 確認する\n  以上です\n")
    assert "名前" in _err("以下は「」の試験です\n  1 < 2 を 確認する\n  以上です\n")


def test_試験で合格と不合格を知らせる(tmp_path, runner):
    (tmp_path / "計算.suru").write_text(CALC, encoding="utf-8")
    (tmp_path / "失敗.suru").write_text(
        "数 を 三倍する は 数\nx を 三倍する とは x * 2\n例えば （2 を 三倍する） は 6 です\n\n"
        "以下は「三倍」の試験です\n  「途中」 を 表示する\n  （2 を 三倍する） を 6 に 一致確認する\n  以上です\n",
        encoding="utf-8")
    r = runner(".", cwd=tmp_path)
    assert r.returncode == 1, r.stderr
    lines = r.stdout.splitlines()
    assert "✓ ./計算.suru 二倍するの例(4行)" in lines
    assert "✓ ./計算.suru 二倍するの例(5行)" in lines
    assert "✓ ./計算.suru 二倍" in lines
    assert "✗ ./失敗.suru 三倍するの例(3行)" in lines
    assert "    ./失敗.suru:3: 等しくありません: 期待は 6 / 実際は 4" in lines
    # 不合格の試験が書いたもの(表示する・一致確認する のエラー)は、その下に字下げして見せる
    # (バイナリでは、標準エラーのほうが先に出ることがある)
    k = lines.index("✗ ./失敗.suru 三倍")
    assert "    途中" in lines[k + 1:k + 3]
    assert any("等しくありません: 期待は 6 / 実際は 4" in x for x in lines[k + 1:k + 3])
    assert lines[-1] == "合格 3・不合格 2"


def test_名前で選ぶ(tmp_path, runner):
    (tmp_path / "計算.suru").write_text(CALC, encoding="utf-8")
    r = runner("計算.suru", "の例", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == "合格 2・不合格 0"
    r = runner("計算.suru", "見つからない名前", cwd=tmp_path)
    assert r.returncode == 0 and "試験が見つかりません" in r.stderr


def test_試験フォルダの試験するも動かす(tmp_path, runner):
    (tmp_path / "計算.suru").write_text(CALC, encoding="utf-8")
    (tmp_path / "試験").mkdir()
    (tmp_path / "試験" / "計算試験.suru").write_text(
        "「試験」 を 読み込んで 使う\n\n数 を 二倍する は 数\nx を 二倍する とは x * 2\n\n"
        "二倍試験する とは 以下の手順です\n  （3 を 二倍する） を 6 に 一致確認する\n  以上です\n",
        encoding="utf-8")
    r = runner("試験", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "✓ 試験/計算試験.suru 二倍試験する" in r.stdout.splitlines()


def test_読み込んだファイルの試験と例は使わない(tmp_path):
    (tmp_path / "計算.suru").write_text(CALC, encoding="utf-8")
    (tmp_path / "主.suru").write_text("「計算」 を 読み込む\n（5 を 計算内の二倍する） を 表示する\n", encoding="utf-8")
    r = _suru("主.suru", cwd=tmp_path)
    assert r.returncode == 0 and r.stdout == "10\n", r.stderr
    # 非公開の名前は外から見えない(試験のまとまりの中では使えた)
    (tmp_path / "主.suru").write_text("「計算」 を 読み込む\n（5 を 計算内の加一する） を 表示する\n", encoding="utf-8")
    assert _suru("主.suru", cwd=tmp_path).returncode == 1


def test_点検は試験と例を文と見なさない(tmp_path):
    # ライブラリ(文のないファイル)のままなので、公開の関数を「未使用の定義」と知らせない
    lib = tmp_path / "部品.suru"
    lib.write_text("数 を 二倍する は 数\nx を 二倍する とは x * 2\n例えば （2 を 二倍する） は 4 です\n\n"
                   "以下は「二倍」の試験です\n  （1 を 二倍する） を 2 に 一致確認する\n  以上です\n", encoding="utf-8")
    r = _suru("--点検", "部品.suru", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_lib_の試験(runner):
    # lib/ の試験のまとまりと例(算術・乱数 など)を、インタプリタと Go 版のバイナリの両方で動かす(#193 段階5)。
    # suruc は同梱の lib/ を使うので、リポジトリの lib/ のファイルの組み込みも使えるか(「標準内の引数取得する」)も確かめる
    r = runner("lib/", cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    last = r.stdout.splitlines()[-1]
    assert last.endswith("・不合格 0") and not last.startswith("合格 0・"), r.stdout


def test_suruc_の試験は一番外の行うことをしない(tmp_path, suruc):
    # 一番外の表示は行わず、型の間違いは「読めません」と知らせる
    (tmp_path / "主.suru").write_text(CALC + "「外」 を 表示する\n", encoding="utf-8")
    (tmp_path / "誤.suru").write_text("例えば 1 は 「1」\n", encoding="utf-8")
    r = subprocess.run([str(suruc), "--試験", "主.suru", "誤.suru"], cwd=tmp_path, capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 1
    assert "外" not in r.stdout.replace("✗ 誤", "")
    assert "✗ 誤.suru(読めません)" in r.stdout
    assert r.stdout.splitlines()[-1] == "合格 3・不合格 1"

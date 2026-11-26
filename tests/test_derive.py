"""導出(#192 段階4): 「会員 は 【記述】 を 導出する」を、読み込んだファイルの「記述導出する」が返した定義にする

導出の関数は型の記述(lib/導出.suru の 型記述)を受け取る。Python 版と Go 版(suruc)が同じ展開・同じ IR・同じエラーになるかも調べる。
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 導出の関数を定義したファイル(「写」 を 読み込む で使う)。【記述】は型の記述を文字列にした値「X記述」を作る
DERIVERS = """「標準」 を 読み込んで 使う
「導出」 を 読み込んで 使う

型記述 を 記述導出する は 文字列 の 成否
d を 記述導出する とは
  左 とは 12300 を 文字にする
  右 とは 12301 を 文字にする
  形文群 とは （d の 形群 の それぞれ を 形文にする） を 「; 」 で 結合する
  （d の 型名 + 「記述 とは 」 + 左 + d の 型名 + 「(」 + （d の 型引数 を 「,」 で 結合する） + 「) 」 + 形文群 + 右） の 成功

形記述 を 形文にする は 文字列
c を 形文にする とは c の 形名 + 「: 」 + （（c の 欄群 を 欄文にすること で 写像する） を 「, 」 で 結合する）

欄記述 を 欄文にする は 文字列
f を 欄文にする とは f の 欄名 + 「=」 + （f の 欄型 を 型式文にする）

# 【数え】は「X形数 とは 形の数」を作る
型記述 を 数え導出する は 文字列 の 成否
d を 数え導出する とは （d の 型名 + 「形数 とは 」 + （d の 形群 の 長さ を 文字列化する）） の 成功

型記述 を 誤導出する は 文字列 の 成否
d を 誤導出する とは （d の 型名 + 「は無理です」） の 失敗

型記述 を 読込導出する は 文字列 の 成否
d を 読込導出する とは 「「数学」 を 読み込む」 の 成功
"""

MAIN = """「写」 を 読み込む

会員 とは 番号 は 数 で 名前 は 文字列 で 好物 は 文字列 の リスト の 組
木 とは 値 は 甲 で 左 は 木 で 右 は 木 の 節 か 葉
会員 は 【記述】 を 導出する
木 は 【記述】 と 【数え】 を 導出します。

会員記述 を 表示する
木記述 を 表示する
木形数 を 表示する
"""

MAIN_OUT = ["会員() 会員: 番号=数, 名前=文字列, 好物=文字列 の リスト", "木(甲) 節: 値=甲, 左=木, 右=木; 葉: ", "2"]


def _write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    (tmp_path / "写.suru").write_text(DERIVERS, encoding="utf-8")
    path = tmp_path / "本体.suru"
    path.write_text(source, encoding="utf-8")
    return path


def _suru(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), *args], capture_output=True, text=True)


def _err(tmp_path: pathlib.Path, source: str) -> str:
    r = _suru(str(_write(tmp_path, source)))
    assert r.returncode != 0
    return r.stderr


def test_導出した定義を使う(tmp_path):
    r = _suru(str(_write(tmp_path, MAIN)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == MAIN_OUT


def test_導出したソースを出す(tmp_path):
    r = _suru("--展開", str(_write(tmp_path, MAIN)))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[4] == "会員記述 とは 「会員() 会員: 番号=数, 名前=文字列, 好物=文字列 の リスト」"
    assert lines[5:7] == ["木記述 とは 「木(甲) 節: 値=甲, 左=木, 右=木; 葉: 」", "木形数 とは 2"]


def test_型の検査も通る(tmp_path):
    r = _suru("--検査", str(_write(tmp_path, MAIN)))
    assert r.returncode == 0, r.stderr


def test_型式文にする():
    import suru

    src = ("「導出」 を 読み込んで 使う\n"
           "（（「リスト」 と （（「数」 と 空 の 名型） を 空 に 挿入する） の 名型） を 型式文にする）\n"
           "（（「対」 と （（「数」 と 空 の 名型） と （「甲」 と 空 の 名型）） の 名型） を 型式文にする）\n")
    assert suru.Interpreter().run_text(src) == ["数 の リスト", "（数 と 甲） の 対"]


def test_関数の型や入れ子の型の記述(tmp_path):
    src = ("「写」 を 読み込む\n"
           "関 とは f は （数 を 受け取って 数 を 返すこと） で g は （数 の リスト） の リスト で h は 甲 の 組\n"
           "関 は 【記述】 を 導出する\n関記述 を 表示する\n")
    r = _suru(str(_write(tmp_path, src)))
    assert r.stdout == "関(甲) 関: f=（数 を 受け取って 数 を 返すこと）, g=（数 の リスト） の リスト, h=甲\n", r.stderr


def test_型の記述をソースにして戻すと同じ値():
    import suru

    src = "記述 とは 番号 は 数 で 名前 は 文字列 で 子 は 記述 の リスト で 関 は （甲 を 受け取って 乙 を 返すこと） の 組\n"
    nodes = suru.build_layout(suru.split_lines(src))
    desc = suru.type_description("記述", [nodes], 1, suru.ParseContext())
    it = suru.Interpreter()
    out = it.run_text("「導出」 を 読み込んで 使う\n" + "x とは " + suru.description_source(desc) + "\n" + "x\n")
    assert out == [suru.format_value(desc)]
    assert desc.values[1] == ("甲", "乙")


@pytest.mark.parametrize("source, message", [
    ("「写」 を 読み込む\n無 は 【記述】 を 導出する\n", "2行目: 「無」の型の定義がこのファイルにありません"),
    ("「写」 を 読み込む\n点 とは 横 と 縦 の 組\n点 は 【記述】 を 導出する\n", "「点」のフィールドに型が書かれていないので導出できません"),
    ("「写」 を 読み込む\n色 とは 赤 か 青\n色 は 【記述】 と 【誤】 を 導出する\n", "3行目: 【誤】で「色」を導出できません: 色は無理です"),
    ("「写」 を 読み込む\n色 とは 赤 か 青\n色 は 【無】 を 導出する\n",
     "【無】の導出の関数「無導出する」が、読み込んだファイルにありません(「型記述 を 無導出する は 文字列 の 成否」"),
    ("色 とは 赤 か 青\nf とは 1\n  色 は 【記述】 を 導出する\n", "「色 は 【記述】 を 導出する」は一番外(字下げなし)にだけ書けます"),
    ("「写」 を 読み込む\n色 とは 赤 か 青\n色 は 【読込】 を 導出する\n", "【読込】の導出したコードには、読み込みの文を書けません"),
])
def test_導出のエラー(tmp_path, source, message):
    assert message in _err(tmp_path, source)


def test_点検は導出の関数を使った読み込みを使ったとみなす(tmp_path):
    source = "「写」 を 読み込む\n\n色 とは 赤 か 青\n\n色 は 【数え】 を 導出する\n\n色形数 を 表示する\n"
    r = _suru("--点検", str(_write(tmp_path, source)))
    assert r.stdout == "", r.stdout


# --- Go 版(suruc) ---

needs_go = pytest.mark.skipif(shutil.which("go") is None or shutil.which("clang") is None, reason="go か clang がありません")


@pytest.fixture(scope="module")
def suruc(tmp_path_factory):
    exe = tmp_path_factory.mktemp("go") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return exe


GO_PROGRAMS = [
    MAIN,
    "「写」 を 読み込む\n関 とは f は （数 を 受け取って 数 を 返すこと） で g は （数 の リスト） の リスト で h は 甲 の 組\n"
    "関 は 【記述】 を 導出する\n関記述 を 表示する\n",
    "「写」 を 読み込む\n無 は 【記述】 を 導出する\n",
    "「写」 を 読み込む\n点 とは 横 と 縦 の 組\n点 は 【記述】 を 導出する\n",
    "「写」 を 読み込む\n色 とは 赤 か 青\n色 は 【記述】 と 【誤】 を 導出する\n",
    "「写」 を 読み込む\n色 とは 赤 か 青\n色 は 【無】 を 導出する\n",
]


@needs_go
@pytest.mark.parametrize("k", range(len(GO_PROGRAMS)))
def test_Go版も同じIRとエラー(k, suruc, tmp_path):
    from test_go_compiler import compare

    compare(_write(tmp_path, GO_PROGRAMS[k]), suruc, tmp_path)


@needs_go
def test_Go版で導出したソースとバイナリ(suruc, tmp_path):
    path = _write(tmp_path, MAIN)
    go = subprocess.run([str(suruc), "--展開", str(path)], capture_output=True, text=True)
    assert go.returncode == 0, go.stderr
    assert go.stdout == _suru("--展開", str(path)).stdout
    subprocess.run([str(suruc), str(path), "-o", str(tmp_path / "本体")], check=True)
    out = subprocess.run([str(tmp_path / "本体")], capture_output=True, text=True)
    assert out.stdout.splitlines() == MAIN_OUT

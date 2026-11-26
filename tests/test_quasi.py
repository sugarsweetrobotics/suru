"""準クォート(#192 段階2・3): 「以下は【道】です … 以上です」を、読み込んだファイルの「道展開する」で する のコードにする

Python 版(suru.py・suru_compile.py)と Go 版(suruc)が同じ展開・同じ IR・同じエラーになるかも調べる。
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 展開の関数を定義したファイル(「道」 を 読み込む で使う)
EXPANDERS = """「標準」 を 読み込んで 使う

# 1行に「名前 値」を書くと「名前 とは 値」にする
文字列 を 定展開する は 文字列 の 成否
本文 を 定展開する とは
  行群 とは 本文 を 改行 で 分割する
  （（行群 の それぞれ を 一行変換する） を 改行 で 結合する） の 成功

文字列 を 一行変換する は 文字列
行 を 一行変換する とは
  語群 とは 行 を 「 」 で 分割する
  （語群 の 先頭） + 「 とは 」 + （語群 の 残り を 「 」 で 結合する）

文字列 を 式展開する は 文字列 の 成否
本文 を 式展開する とは （本文 + 「 + 1」） の 成功

文字列 を 誤展開する は 文字列 の 成否
本文 を 誤展開する とは もし 本文 = 「」 ならば 「空です」 の 失敗 そうでなければ 「2行目: 分かりません」 の 失敗

文字列 を 再展開する は 文字列 の 成否
本文 を 再展開する とは （「以下は【再】です」 + 改行 + 「  」 + 本文 + 改行 + 「以上です」） の 成功

文字列 を 読込展開する は 文字列 の 成否
本文 を 読込展開する とは 「「数学」 を 読み込む」 の 成功
"""

MAIN = """「道」 を 読み込む

以下は【定】です
  x 10
  y x * 2
以上です

z とは 以下の【式】です
  y + 3
以上です

x を 表示する
y を 表示する
z を 表示する
"""


def _write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    (tmp_path / "道.suru").write_text(EXPANDERS, encoding="utf-8")
    path = tmp_path / "本体.suru"
    path.write_text(source, encoding="utf-8")
    return path


def _suru(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), *args], capture_output=True, text=True)


def _err(tmp_path: pathlib.Path, source: str) -> str:
    r = _suru(str(_write(tmp_path, source)))
    assert r.returncode != 0
    return r.stderr


def test_一番外の形と式の形を展開して動かす(tmp_path):
    r = _suru(str(_write(tmp_path, MAIN)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["10", "20", "24"]


def test_展開したソースを出す(tmp_path):
    r = _suru("--展開", str(_write(tmp_path, MAIN)))
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "「道」 を 読み込む\n\nx とは 10\ny とは x * 2\n\nz とは\n  y + 3 + 1\n\n"
        "x を 表示する\ny を 表示する\nz を 表示する\n"
    )


def test_展開の関数の失敗は中身の行を指す(tmp_path):
    err = _err(tmp_path, MAIN + "以下は【誤】です\n  a\n  b\n以上です\n")
    assert "17行目: 【誤】の2行目: 分かりません" in err


def test_展開の関数がなければエラー(tmp_path):
    err = _err(tmp_path, MAIN + "w とは 以下の【無】です\n  1\n以上です\n")
    assert "【無】の展開の関数「無展開する」が、読み込んだファイルにありません" in err


def test_閉じていなければエラー(tmp_path):
    err = _err(tmp_path, "「道」 を 読み込む\n以下は【定】です\n  x 1\n")
    assert "2行目: 「以下は【定】です」を閉じる「以上です」がありません" in err


def test_中身がなければエラー(tmp_path):
    err = _err(tmp_path, "「道」 を 読み込む\n以下は【定】です\n\n以上です\n")
    assert "「以下は【定】です」と「以上です」の間に中身がありません" in err


def test_中身の字下げが浅ければエラー(tmp_path):
    err = _err(tmp_path, "「道」 を 読み込む\n以下は【定】です\n  x 1\ny 2\n以上です\n")
    assert "4行目: 「以下は【定】です」の中身は頭より深く字下げして" in err


def test_墨付き括弧は頭のほかでは使えない(tmp_path):
    err = _err(tmp_path, "a とは 【b】\n")
    assert "「【】」は「以下は【道】です」のような準クォートの頭にだけ書けます" in err
    r = _suru(str(_write(tmp_path, "「【b】」 を 表示する\n")))
    assert r.stdout == "【b】\n"


def test_一番外の形は字下げできない(tmp_path):
    err = _err(tmp_path, "「道」 を 読み込む\nf とは 以下の手順です\n  以下は【定】です\n    x 1\n  以上です\n以上です\n")
    assert "「以下は【定】です」は一番外(字下げなし)にだけ書けます" in err


def test_展開が深すぎればエラー(tmp_path):
    err = _err(tmp_path, "「道」 を 読み込む\n以下は【再】です\n  x\n以上です\n")
    assert "【再】の展開が深すぎます" in err


def test_展開したコードでは読み込めない(tmp_path):
    err = _err(tmp_path, "「道」 を 読み込む\n以下は【読込】です\n  x\n以上です\n")
    assert "【読込】の展開したコードには、読み込みの文を書けません" in err


def test_点検は展開の関数を使った読み込みと中身の名前を使ったとみなす(tmp_path):
    source = (
        "「道」 を 読み込む\n\n"
        "倍 とは 2\n\n"
        "以下は【定】です\n  x 倍\n以上です\n\n"
        "x を 表示する\n"
    )
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
    MAIN + "以下は【誤】です\n  a\n  b\n以上です\n",
    MAIN + "w とは 以下の【無】です\n  1\n以上です\n",
    "「道」 を 読み込む\n以下は【定】です\n  x 1\n",
    "「道」 を 読み込む\n以下は【定】です\n  x 1\ny 2\n以上です\n",
    "a とは 【b】\n",
    "「道」 を 読み込む\n以下は【再】です\n  x\n以上です\n",
    "「道」 を 読み込む\n以下は【読込】です\n  x\n以上です\n",
]


@needs_go
@pytest.mark.parametrize("k", range(len(GO_PROGRAMS)))
def test_Go版も同じIRとエラー(k, suruc, tmp_path):
    from test_go_compiler import compare

    compare(_write(tmp_path, GO_PROGRAMS[k]), suruc, tmp_path)


@needs_go
def test_Go版で展開したソースとバイナリ(suruc, tmp_path):
    path = _write(tmp_path, MAIN)
    go = subprocess.run([str(suruc), "--展開", str(path)], capture_output=True, text=True)
    assert go.returncode == 0, go.stderr
    assert go.stdout == _suru("--展開", str(path)).stdout
    subprocess.run([str(suruc), str(path), "-o", str(tmp_path / "本体")], check=True)
    out = subprocess.run([str(tmp_path / "本体")], capture_output=True, text=True)
    assert out.stdout.split() == ["10", "20", "24"]

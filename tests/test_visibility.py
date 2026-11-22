"""「… は 非公開とする」「… は 公開とする」のテスト(インタプリタ・型の検査・Python 版と Go 版のコンパイラ)"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

PART = """数 を 二倍する は 数
x を 二倍する とは x を 補助する
数 を 補助する は 数
x を 補助する とは x * 2
円周率 とは 3

補助する は 非公開とする
"""

PART2 = """数 を 補助する は 数
x を 補助する とは x + 100
数 を 百足する は 数
x を 百足する とは x を 補助する
数 を 千足する は 数
x を 千足する とは x + 1000

百足する と 千足する は 公開とする。
"""

MAIN = """「部品」 を 読み込んで 使う
「部品二」 を 読み込んで 使う
3 を 二倍する
3 を 百足する
3 を 千足する
部品内の円周率
数 を 補助する は 数
x を 補助する とは x - 1
3 を 補助する
"""


def suruc() -> str | None:
    go = shutil.which("go")
    if go is None:
        return None
    out = pathlib.Path(__file__).parent / ".." / "build"
    exe = (out / "suruc_test").resolve()
    subprocess.run([go, "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return str(exe)


def write(d: pathlib.Path, files: dict) -> pathlib.Path:
    for name, src in files.items():
        (d / name).write_text(src, encoding="utf-8")
    return d / "main.suru"


def runs(d: pathlib.Path, main: pathlib.Path) -> list:
    out = [subprocess.run([sys.executable, str(ROOT / "suru.py"), str(main)], capture_output=True, text=True, timeout=60)]
    if suru_compile.find_cc() is not None:
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(main), "-o", str(d / "p")], check=True)
        out.append(subprocess.run([str(d / "p")], capture_output=True, text=True, timeout=60))
        exe = suruc()
        if exe:
            subprocess.run([exe, str(main), "-o", str(d / "g")], check=True)
            out.append(subprocess.run([str(d / "g")], capture_output=True, text=True, timeout=60))
    return out


def test_非公開の名前はぶつからない(tmp_path):
    main = write(tmp_path, {"部品.suru": PART, "部品二.suru": PART2, "main.suru": MAIN})
    for r in runs(tmp_path, main):
        assert r.returncode == 0, r.stderr
        assert r.stdout == "6\n103\n1003\n3\n2\n"
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--検査", str(main)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("use", ["部品内の補助する", "部品二内の補助する"])
def test_非公開の名前は前置きでも使えない(tmp_path, use):
    main = write(tmp_path, {"部品.suru": PART, "部品二.suru": PART2,
                            "main.suru": f"「部品」 を 読み込む\n「部品二」 を 読み込む\n3 を {use}\n"})
    for r in runs(tmp_path, main):
        assert r.returncode == 1
        assert f"「{use}」は定義されていません" in r.stderr


@pytest.mark.parametrize("part, message", [
    ("x とは 1\n無い名前 は 非公開とする\n", "「無い名前」はこのファイルで定義していないので、非公開とするにできません"),
    ("x とは 1\nx は 非公開とする\nx は 公開とする\n", "「x」が「公開とする」と「非公開とする」の両方に書かれています"),
    ("x とは 1\nx 1 は 非公開とする\n", "名前を「と」で並べてください"),
], ids=["ない名前", "両方", "並べ方"])
def test_書き方の間違い(tmp_path, part, message):
    main = write(tmp_path, {"部品.suru": part, "main.suru": "「部品」 を 読み込む\n1\n"})
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(main)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert message in r.stderr
    exe = suruc() if suru_compile.find_cc() is not None else None
    if exe:
        r = subprocess.run([exe, str(main), "-o", str(tmp_path / "g")], capture_output=True, text=True, timeout=60)
        assert r.returncode != 0
        assert message in r.stderr


def test_字下げの中には書けない(tmp_path):
    main = write(tmp_path, {"main.suru": "f とは 手順\n  x は 非公開とする\n  1 を 表示する\n"})
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(main)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "一番外側" in r.stderr


def test_ライブラリの補助の関数は見えない(tmp_path):
    main = write(tmp_path, {"main.suru": "「時間」 を 読み込む\n10 を 時間内の時刻冪乗する\n"})
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(main)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "「時間内の時刻冪乗する」は定義されていません" in r.stderr

"""lib/ のライブラリを全部「読み込んで 使う」にしても名前がぶつからないか"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 字句・点検は linter のためのもので、ほかのライブラリと「部分」などの名前が同じ。
# 環境 の 引数取得する・終了する は 標準 の組み込みと同じ名前(環境内の… で使う)なので、標準 とは一緒に開かない
SKIP = {"字句", "点検", "環境"}


def test_全部読み込んで使う(tmp_path):
    names = sorted(p.stem for p in (ROOT / "lib").glob("*.suru") if p.stem not in SKIP)
    src = tmp_path / "prog.suru"
    src.write_text("".join(f"「{n}」 を 読み込んで 使う\n" for n in names) + "1 + 1\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "2\n"


def test_全部読み込んでコンパイルできる(tmp_path):
    # 同じ C の関数を、別のファイルが違う型で宣言していると組めない(#120: プロセス と ファイル の fread)
    names = sorted(p.stem for p in (ROOT / "lib").glob("*.suru"))
    src = tmp_path / "prog.suru"
    src.write_text("".join(f"「{n}」 を 読み込む\n" for n in names) + "1 + 1 を 表示する\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), "--ll", str(src), "-o", str(tmp_path / "a.ll")],
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr


def test_違う型の外部の関数はもう1つの場所を出す(tmp_path):
    (tmp_path / "甲.suru").write_text("文字列 を 長甲計測する は 数\ns を 長甲計測する とは 外部の「strlen」\n", encoding="utf-8")
    (tmp_path / "乙.suru").write_text("文字列 を 長乙計測する は 整数\ns を 長乙計測する とは 外部の「strlen」\n", encoding="utf-8")
    src = tmp_path / "prog.suru"
    src.write_text("「甲」 を 読み込んで 使う\n「乙」 を 読み込んで 使う\n"
                   "（「ab」 を 長甲計測する） を 表示する\n（「ab」 を 長乙計測する） を 表示する\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), "--ll", str(src), "-o", str(tmp_path / "a.ll")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0
    assert "外部の関数「strlen」が違う型で2回宣言されています(もう1つは「甲.suru」の2行目" in r.stderr

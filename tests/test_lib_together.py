"""lib/ のライブラリを全部「読み込んで 使う」にしても名前がぶつからないか"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# 字句・点検は linter のためのもので、HTTP とは「部分」などの名前が同じ。
# 環境 の 引数取得する・終了する は 標準 の組み込みと同じ名前(環境内の… で使う)なので、標準 とは一緒に開かない
SKIP = {"字句", "点検", "環境"}


def test_全部読み込んで使う(tmp_path):
    names = sorted(p.stem for p in (ROOT / "lib").glob("*.suru") if p.stem not in SKIP)
    src = tmp_path / "prog.suru"
    src.write_text("".join(f"「{n}」 を 読み込んで 使う\n" for n in names) + "1 + 1\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "2\n"

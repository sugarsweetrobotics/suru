"""Go 版コンパイラ(cmd/suruc)のテスト: Python 版(suru_compile.py)と同じ LLVM IR とエラーを出すか

go がなければ飛ばす。例のプログラムと、ほかのテストに書いたプログラム(エラーになるものも)を全部調べる。
"""

import ast
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytestmark = pytest.mark.skipif(shutil.which("go") is None, reason="go がありません")


@pytest.fixture(scope="module")
def suruc(tmp_path_factory):
    exe = tmp_path_factory.mktemp("go") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return exe


def programs() -> list[str]:
    """tests/*.py に書いた、する のプログラム(日本語を含む文字列)"""
    seen: dict[str, None] = {}
    for f in sorted((ROOT / "tests").glob("test_*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value
                if len(s) >= 3 and re.search(r"[぀-ヿ一-鿿]", s):
                    seen.setdefault(s if s.endswith("\n") else s + "\n")
    return list(seen)


def compare(path: pathlib.Path, suruc: pathlib.Path, out: pathlib.Path) -> None:
    py = subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), "--ll", str(path), "-o", str(out / "py.ll")],
                        capture_output=True, text=True)
    go = subprocess.run([str(suruc), "--ll", str(path), "-o", str(out / "go.ll")], capture_output=True, text=True)
    assert (go.returncode, go.stderr) == (py.returncode, py.stderr)
    if py.returncode == 0:
        assert (out / "go.ll").read_bytes() == (out / "py.ll").read_bytes()


EXAMPLES = sorted((ROOT / "examples").glob("*.suru"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_例のプログラムで同じIR(path, suruc, tmp_path):
    compare(path, suruc, tmp_path)


def test_テストのプログラムで同じIRとエラー(suruc, tmp_path):
    shutil.copy(ROOT / "examples" / "数学.suru", tmp_path / "数学.suru")
    failed = []
    for k, source in enumerate(programs()):
        path = tmp_path / f"p{k}.suru"
        path.write_text(source, encoding="utf-8")
        try:
            compare(path, suruc, tmp_path)
        except AssertionError:
            failed.append(source)
    assert not failed, f"{len(failed)} 個のプログラムで違います。最初のもの:\n{failed[0]}"


def test_バイナリを作って動かす(suruc, tmp_path):
    if shutil.which("clang") is None:
        pytest.skip("clang がありません")
    src = tmp_path / "fib.suru"
    src.write_text("n を数列する とは\n  もし n < 2 ならば n\n  そうでなければ （n - 1 を数列する） + （n - 2 を数列する）\n20 を数列する\n",
                   encoding="utf-8")
    subprocess.run([str(suruc), str(src), "-o", str(tmp_path / "fib")], check=True)
    r = subprocess.run([str(tmp_path / "fib")], capture_output=True, text=True, check=True)
    assert r.stdout == "6765\n"


def test_通信のサーバーで同じIR(suruc, tmp_path):
    from net_helper import SERVER

    path = tmp_path / "srv.suru"
    path.write_text(SERVER.replace("PORT", "8080"), encoding="utf-8")
    compare(path, suruc, tmp_path)


def test_HTTPのサーバーで同じIR(suruc, tmp_path):
    from net_helper import HTTP_ACTION_SERVER, HTTP_SERVER

    for k, src in enumerate((HTTP_SERVER, HTTP_ACTION_SERVER)):
        path = tmp_path / f"http{k}.suru"
        path.write_text(src.replace("PORT", "8080"), encoding="utf-8")
        compare(path, suruc, tmp_path)

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


EXAMPLES = sorted((ROOT / "examples").glob("*.suru")) + sorted((ROOT / "examples" / "通信").glob("*.suru"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_例のプログラムで同じIR(path, suruc, tmp_path):
    compare(path, suruc, tmp_path)


def _compile_py(path: str, ll: str) -> tuple[int, str]:
    """Python 版で --ll を作る(suru_compile.py --ll と同じ)。プログラムごとに新しい子で動かすので、状態は次のプログラムに残らない"""
    import contextlib
    import io

    import suru_compile

    sys.setrecursionlimit(10000)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        try:
            code = suru_compile.main(["suru_compile.py", "--ll", path, "-o", ll])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return code, err.getvalue()


def _compare_one(job: tuple[str, str, str]) -> str | None:
    """1つのプログラムを Python 版と Go 版でコンパイルして比べる。違えば そのソース"""
    path, suruc, out = job
    py_ll, go_ll = out + ".py.ll", out + ".go.ll"
    for ll in (py_ll, go_ll):
        pathlib.Path(ll).unlink(missing_ok=True)
    py = _compile_py(path, py_ll)
    go = subprocess.run([suruc, "--ll", path, "-o", go_ll], capture_output=True, text=True)
    same = (go.returncode, go.stderr) == py
    if same and py[0] == 0:
        same = pathlib.Path(go_ll).exists() and pathlib.Path(go_ll).read_bytes() == pathlib.Path(py_ll).read_bytes()
    return None if same else pathlib.Path(path).read_text(encoding="utf-8")


def test_テストのプログラムで同じIRとエラー(suruc, tmp_path):
    # 2000 個ほどあるので、Python を毎回起動しない。suru_compile を読み込んだ forkserver から
    # プログラムごとに子を fork して、並べて動かす(#230)
    import multiprocessing

    shutil.copy(ROOT / "examples" / "数学.suru", tmp_path / "数学.suru")
    jobs = []
    for k, source in enumerate(programs()):
        path = tmp_path / f"p{k}.suru"
        path.write_text(source, encoding="utf-8")
        jobs.append((str(path), str(suruc), str(tmp_path / f"p{k}")))
    if "forkserver" in multiprocessing.get_all_start_methods():
        ctx = multiprocessing.get_context("forkserver")
        ctx.set_forkserver_preload(["suru_compile", "test_go_compiler"])
    else:  # Windows
        ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(maxtasksperchild=1) as pool:
        failed = [src for src in pool.map(_compare_one, jobs, chunksize=1) if src is not None]
    assert not failed, f"{len(failed)} 個のプログラムで違います。最初のもの:\n{failed[0]}"


def test_2つのファイルにある型と同じ名前の変数で同じIR(suruc, tmp_path):
    from test_suru import TYPE_A, TYPE_B, TYPE_VARS

    (tmp_path / "甲.suru").write_text(TYPE_A, encoding="utf-8")
    (tmp_path / "乙.suru").write_text(TYPE_B, encoding="utf-8")
    path = tmp_path / "main.suru"
    path.write_text(TYPE_VARS, encoding="utf-8")
    compare(path, suruc, tmp_path)
    path.write_text(TYPE_VARS + "（5 の 応答）\n", encoding="utf-8")
    compare(path, suruc, tmp_path)


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


def test_通信のお客さんで同じIR(suruc, tmp_path):
    from net_helper import CLIENT

    path = tmp_path / "cli.suru"
    path.write_text(CLIENT.replace("PORT", "8080"), encoding="utf-8")
    compare(path, suruc, tmp_path)


def test_HTTPのサーバーで同じIR(suruc, tmp_path):
    from net_helper import HTTP_ACTION_SERVER, HTTP_SERVER, HTTP_STATIC_SERVER, put_http

    put_http(tmp_path)
    for k, src in enumerate((HTTP_SERVER, HTTP_ACTION_SERVER, HTTP_STATIC_SERVER)):
        path = tmp_path / f"http{k}.suru"
        path.write_text(src.replace("PORT", "8080"), encoding="utf-8")
        compare(path, suruc, tmp_path)

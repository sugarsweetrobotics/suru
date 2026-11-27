"""pip の OS ごとの wheel で suru と一緒に入る suruc を使う(#229)"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402

GOOD = "1 と 2 を 加算して 表示する\n"
BAD = "「標準」 を 読み込んで 使う\n（1 を 文字列にする） を 表示する\n"


def _run(args, env_extra=None, **kw):
    env = {k: v for k, v in os.environ.items() if k not in ("SURU_SURUC", "SURU_INTERPRETER")}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(ROOT / "suru.py")] + args, capture_output=True, text=True, env=env, **kw)


def test_lookup(tmp_path, monkeypatch):
    monkeypatch.delenv("SURU_SURUC", raising=False)
    monkeypatch.delenv("SURU_INTERPRETER", raising=False)
    exe = tmp_path / ("suruc.exe" if os.name == "nt" else "suruc")
    exe.write_text("")
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "suru")])
    assert suru.bundled_suruc() == str(exe)
    # リポジトリのまま python3 suru.py で動かしたときは使わない
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "suru.py")])
    assert suru.bundled_suruc() is None
    # suru の隣になければ使わない
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "other" / "suru")])
    assert suru.bundled_suruc() is None
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "suru")])
    monkeypatch.setenv("SURU_INTERPRETER", "1")
    assert suru.bundled_suruc() is None
    monkeypatch.delenv("SURU_INTERPRETER")
    monkeypatch.setenv("SURU_SURUC", "")
    assert suru.bundled_suruc() is None
    monkeypatch.setenv("SURU_SURUC", "/x/suruc")
    assert suru.bundled_suruc() == "/x/suruc"


@pytest.mark.skipif(os.name == "nt", reason="sh の偽の suruc を使う")
def test_delegates_to_suruc(tmp_path):
    log = tmp_path / "log"
    fake = tmp_path / "suruc"
    # --実行準備 には「インタプリタで動かして」(3)と答える
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n[ "$1" = --実行準備 ] && exit 3\nexit 0\n')
    fake.chmod(0o755)
    prog = tmp_path / "a.suru"
    prog.write_text(GOOD, encoding="utf-8")
    env = {"SURU_SURUC": str(fake)}
    assert _run(["--検査", "--json", str(prog)], env).returncode == 0
    r = _run([str(prog)], env)
    assert r.stdout == "3\n"  # 調べるのは suruc、動かすのはインタプリタ
    assert _run(["--翻訳", "-O0", str(prog), "-o", "x"], env).returncode == 0
    assert _run(["--検査なし", str(prog)], env).stdout == "3\n"
    assert log.read_text().splitlines() == [
        f"--検査 --json {prog}",
        f"--実行準備 {prog}",
        f"--検査 {prog}",
        f"-O0 {prog} -o x",
        f"--実行準備 --検査なし {prog}",
    ]
    # SURU_INTERPRETER=1 なら使わない
    log.unlink()
    assert _run([str(prog)], {**env, "SURU_INTERPRETER": "1"}).stdout == "3\n"
    assert not log.exists()


@pytest.mark.skipif(shutil.which("go") is None, reason="go がありません")
def test_same_errors_with_real_suruc(tmp_path):
    exe = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    bad = tmp_path / "bad.suru"
    bad.write_text(BAD, encoding="utf-8")
    good = tmp_path / "good.suru"
    good.write_text(GOOD, encoding="utf-8")
    for args in (["--検査", str(bad)], ["--検査", "--json", str(bad)], [str(bad)], ["--json", str(bad)]):
        py = _run(args)
        go = _run(args, {"SURU_SURUC": str(exe)})
        assert (go.returncode, go.stdout, go.stderr) == (py.returncode, py.stdout, py.stderr)
        assert go.returncode == 1 and "バイト列が必要" in go.stderr
    for args in (["--検査", str(good)], [str(good)]):
        py = _run(args)
        go = _run(args, {"SURU_SURUC": str(exe)})
        assert (go.returncode, go.stdout, go.stderr) == (py.returncode, py.stdout, py.stderr)


# ---- その場でコンパイルして動かす(suruc --実行・suru の既定) ----

needs_go_cc = pytest.mark.skipif(shutil.which("go") is None or shutil.which("clang") is None,
                                 reason="go か clang がありません")
ARGS = "「標準」 を 読み込んで 使う\n以下の手順です\n  a とは 引数取得した 結果\n  a を 表示する\n以上です\n"
INPUT = "以下の手順です\n  s とは 入力した 結果\n  s を 表示する\n以上です\n"
FAIL = "（1 / 0） を 表示する\n"


@pytest.fixture(scope="module")
def real_suruc(tmp_path_factory):
    exe = tmp_path_factory.mktemp("go") / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    return exe


def _runs(cache: pathlib.Path) -> list[str]:
    d = cache / "suru" / "run"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


@needs_go_cc
def test_runs_compiled_and_caches(tmp_path, real_suruc):
    cache = tmp_path / "cache"
    env = {"SURU_SURUC": str(real_suruc), "XDG_CACHE_HOME": str(cache)}
    files = {}
    for name, src in (("good", GOOD), ("args", ARGS), ("input", INPUT), ("fail", FAIL), ("bad", BAD)):
        files[name] = tmp_path / f"{name}.suru"
        files[name].write_text(src, encoding="utf-8")
    cases = [
        ([str(files["good"])], None),
        ([str(files["args"]), "x", "y z"], None),
        ([str(files["input"])], "こんにちは\n"),
        ([str(files["fail"])], None),
        (["--json", str(files["fail"])], None),
        ([str(files["bad"])], None),
        (["--json", str(files["bad"])], None),
        (["--検査なし", str(files["good"])], None),
    ]
    for args, stdin in cases:
        py = _run(args, input=stdin)
        native = _run(args, env, input=stdin)
        assert (native.returncode, native.stdout, native.stderr) == (py.returncode, py.stdout, py.stderr), args
    # 読み込んだファイルの中と、ライブラリの中の実行時エラー(--json でも同じ)
    (tmp_path / "除算.suru").write_text("数 を 半端にする は 数 を 返す\nx を 半端にする とは x / 0 です\n", encoding="utf-8")
    inner = tmp_path / "inner.suru"
    inner.write_text("「除算」 を 読み込む\n（3 を 除算内の半端にする） を 表示する\n", encoding="utf-8")
    lib = tmp_path / "lib.suru"
    lib.write_text("「標準」 を 読み込んで 使う\n（「あ」 を 数値にする） を 表示する\n", encoding="utf-8")
    for args in ([str(inner)], ["--json", str(inner)], [str(lib)], ["--json", str(lib)]):
        py = _run(args)
        native = _run(args, env)
        assert (native.returncode, native.stdout, native.stderr) == (py.returncode, py.stdout, py.stderr), args
    for p in (cache / "suru" / "run").iterdir():
        p.unlink()
    for args, stdin in cases[:4]:
        _run(args, env, input=stdin)
    built = _runs(cache)
    assert len(built) == 4  # good・args・input・fail(検査なしの good は同じ IR なので同じもの、bad は作らない)
    # 2回目はキャッシュのバイナリを動かす(作り直さない)
    assert _run([str(files["good"])], env).stdout == "3\n"
    assert _runs(cache) == built
    # 読み込んだファイルが変われば作り直す
    (tmp_path / "数.suru").write_text("x とは 1 です\n", encoding="utf-8")
    use = tmp_path / "use.suru"
    use.write_text("「数」 を 読み込む\n数内のx を 表示する\n", encoding="utf-8")
    assert _run([str(use)], env).stdout == "1\n"
    (tmp_path / "数.suru").write_text("x とは 2 です\n", encoding="utf-8")
    assert _run([str(use)], env).stdout == "2\n"
    assert len(_runs(cache)) == 6


@needs_go_cc
def test_interpreter_flag_and_fallbacks(tmp_path, real_suruc):
    cache = tmp_path / "cache"
    env = {"SURU_SURUC": str(real_suruc), "XDG_CACHE_HOME": str(cache)}
    prog = tmp_path / "a.suru"
    prog.write_text(GOOD, encoding="utf-8")
    for flags in (["--インタプリタ"], ["--interpreter", "--検査なし"], ["--検査なし", "--インタプリタ"]):
        assert _run(flags + [str(prog)], env).stdout == "3\n"
    assert _run([str(prog)], {**env, "SURU_INTERPRETER": "1"}).stdout == "3\n"
    assert _runs(cache) == []
    # C コンパイラがなければインタプリタで動かし、お知らせは1回だけ
    no_cc = {**env, "CC": "", "PATH": str(tmp_path / "nothing")}
    first = _run([str(prog)], no_cc)
    assert first.stdout == "3\n" and "clang を入れると" in first.stderr
    second = _run([str(prog)], no_cc)
    assert second.stdout == "3\n" and second.stderr == ""
    assert _runs(cache) == []
    # kumu の Cソース を使うプロジェクトもインタプリタで(suruc はつながない)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "組.suru").write_text("名前 とは 「試し」\nCソース とは 「c/a.c」\n", encoding="utf-8")
    (proj / "main.suru").write_text(GOOD, encoding="utf-8")
    assert _run([str(proj / "main.suru")], env).stdout == "3\n"
    assert _runs(cache) == []
    r = subprocess.run([str(real_suruc), "--実行準備", str(proj / "main.suru")], capture_output=True, text=True,
                       env={**os.environ, "XDG_CACHE_HOME": str(cache)})
    assert r.returncode == suru.EXIT_NEED_INTERPRETER and r.stdout == ""


@needs_go_cc
def test_suruc_run_directly(tmp_path, real_suruc):
    prog = tmp_path / "a.suru"
    prog.write_text(ARGS, encoding="utf-8")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    r = subprocess.run([str(real_suruc), "--実行", "-O1", str(prog), "1", "--json"], capture_output=True, text=True, env=env)
    assert (r.returncode, r.stdout) == (0, "（「1」 と 「--json」）\n")
    fail = tmp_path / "f.suru"
    fail.write_text(FAIL, encoding="utf-8")
    r = subprocess.run([str(real_suruc), "--実行", str(fail)], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "0 で割ることはできません" in r.stderr
    r = subprocess.run([str(real_suruc), "--実行"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "使い方" in r.stderr

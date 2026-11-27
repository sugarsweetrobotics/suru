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
    fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n')
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
        f"--検査 {prog}",
        f"-O0 {prog} -o x",
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

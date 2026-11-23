"""プロジェクトの依存(kumu の 組.lock)を、インタプリタと型の検査と Go 版のコンパイラが同じ決まりで探すか"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402


def make_project(tmp: pathlib.Path, home: pathlib.Path) -> pathlib.Path:
    """依存2つ(Git から取ったものと手元のフォルダ)を持つプロジェクトを作る"""
    app = tmp / "アプリ"
    (app / "部品").mkdir(parents=True)
    (app / "組.suru").write_text("名前 とは 「アプリ」\n依存 とは 「example.com/x/計算@1.2.0」 と 「../手元」\n", encoding="utf-8")
    (app / "組.lock").write_text(
        "# kumu が書いたファイルです\n"
        "計算\texample.com/x/計算\t1.2.0\tabc\tsha256-x\n"
        "手元\t../手元\t-\t-\t-\n", encoding="utf-8")
    calc = home / "依存" / "example.com" / "x" / "計算@1.2.0"
    (calc / "中").mkdir(parents=True)
    (calc / "計算.suru").write_text("「中/補助」 を 読み込む\nx を 二倍する とは x を 補助内の倍にする\n", encoding="utf-8")
    (calc / "中" / "補助.suru").write_text("x を 倍にする とは x * 2\n", encoding="utf-8")
    (calc / "道具.suru").write_text("x を 三倍する とは x * 3\n", encoding="utf-8")
    local = tmp / "手元"
    local.mkdir()
    (local / "手元.suru").write_text("挨拶文 とは 「やあ」\n", encoding="utf-8")
    # 部品/ の中のファイルからも、プロジェクトの依存を読み込める
    (app / "部品" / "表示部品.suru").write_text("「手元」 を 読み込む\n文 とは 手元内の挨拶文\n", encoding="utf-8")
    (app / "本体.suru").write_text(
        "「計算」 を 読み込む\n「計算/道具」 を 読み込む\n「部品/表示部品」 を 読み込む\n"
        "4 を 計算内の二倍して 表示する\n4 を 道具内の三倍して 表示する\n表示部品内の文 を 表示する\n", encoding="utf-8")
    return app


WANT = "8\n12\nやあ\n"


@pytest.fixture
def project(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("KUMU_HOME", str(home))
    return make_project(tmp_path, home), home


def run_suru(path: pathlib.Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), *flags, str(path)], capture_output=True, text=True,
                          env=os.environ.copy())


def test_インタプリタが依存を読み込む(project):
    app, _ = project
    r = run_suru(app / "本体.suru")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == WANT


def test_型の検査も依存を読む(project):
    app, _ = project
    r = run_suru(app / "本体.suru", "--検査")
    assert r.returncode == 0, r.stdout + r.stderr


def test_まだ取ってきていない依存(project):
    app, home = project
    shutil.rmtree(home / "依存")
    r = run_suru(app / "本体.suru")
    assert r.returncode == 1
    assert "依存の「計算」がまだ取ってきてありません" in r.stdout + r.stderr


def test_自分のフォルダのファイルが先(project):
    app, _ = project
    (app / "計算.suru").write_text("x を 二倍する とは x * 100\n", encoding="utf-8")
    r = run_suru(app / "本体.suru")
    assert r.stdout.startswith("400\n"), r.stdout + r.stderr


def test_組lockがなければ依存はない(project):
    app, _ = project
    (app / "組.lock").unlink()
    r = run_suru(app / "本体.suru")
    assert r.returncode == 1
    assert "ファイル「計算.suru」が見つかりません" in r.stdout + r.stderr


def test_Go版のコンパイラも同じに探す(project, tmp_path):
    if shutil.which("go") is None:
        pytest.skip("go がない")
    app, _ = project
    exe = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    r = subprocess.run([str(exe), "--ll", str(app / "本体.suru"), "-o", str(tmp_path / "a.ll")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    import suru_compile
    src = (app / "本体.suru").read_text(encoding="utf-8")
    ir = suru_compile.compile_source(src, str(app), str(app / "本体.suru"), True)
    assert ir == (tmp_path / "a.ll").read_text(encoding="utf-8")

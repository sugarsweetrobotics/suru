"""導出【JSON】(#192 段階5): 「会員 は 【JSON】 を 導出する」で 会員JSON化する と 会員JSON復元する を作る

インタプリタとコンパイルしたバイナリ(Python 版と Go 版)で同じ結果になるかも調べる。
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROGRAM = """「JSON」 を 読み込んで 使う

会員 とは 番号 は 数 で 名前 は 文字列 で 好物 は 文字列 の リスト で 会費済 は 真偽 の 組
図形 とは 半径 は 数 の 円 か 幅 は 数 で 高 は 数 の 長方形 か 点
名簿 とは 題 は 文字列 で 人 は 会員 の リスト で 形 は 図形 で 余り は JSON の 組

会員 は 【JSON】 を 導出する
図形 は 【JSON】 を 導出する
名簿 は 【JSON】 を 導出する

m とは （番号 は 1 で 名前 は 「花子」 で 好物 は （「茶」 と 「餅」） で 会費済 は 真 の 会員）
帳 とは （題 は 「会」 で 人 は （m を 空 に 挿入する） で 形 は （2 と 3 の 長方形） で 余り は JSON無 の 名簿）
帳 を 名簿JSON化して JSON文字列にして 表示する
（（帳 を 名簿JSON化する） を 名簿JSON復元する） = （帳 の 成功） を 表示する
（「{"番号": "x"}」 を JSON解析して 取出する） を 会員JSON復元して 表示する
（「{"形": "三角"}」 を JSON解析して 取出する） を 図形JSON復元して 表示する
（「{"形": "円", "半径": 4}」 を JSON解析して 取出する） を 図形JSON復元して 表示する
点 を 図形JSON化して JSON文字列にして 表示する
"""

OUT = [
    '{"題":"会","人":[{"番号":1,"名前":"花子","好物":["茶","餅"],"会費済":true}],"形":{"形":"長方形","幅":2,"高":3},"余り":null}',
    "真",
    "（理由 は 「番号が数ではありません」 の 失敗）",
    "（理由 は 「「形」が三角の形はありません」 の 失敗）",
    "（値 は （半径 は 4 の 円） の 成功）",
    '{"形":"点"}',
]


def _write(tmp_path: pathlib.Path, source: str) -> pathlib.Path:
    path = tmp_path / "本体.suru"
    path.write_text(source, encoding="utf-8")
    return path


def _suru(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "suru.py"), *args], capture_output=True, text=True)


def test_JSONにして戻す(tmp_path):
    r = _suru(str(_write(tmp_path, PROGRAM)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == OUT


def test_型の検査が通る(tmp_path):
    r = _suru("--検査", str(_write(tmp_path, PROGRAM)))
    assert r.returncode == 0, r.stderr


def test_点検で知らせがない(tmp_path):
    r = _suru("--点検", str(_write(tmp_path, PROGRAM)))
    assert r.stdout == "", r.stdout


@pytest.mark.parametrize("source, message", [
    ("「JSON」 を 読み込んで 使う\n箱 とは 中 は 甲 の 組\n箱 は 【JSON】 を 導出する\n", "型の引数(甲・乙 …)のある型は、まだ【JSON】で導出できません"),
    ("「JSON」 を 読み込んで 使う\n点 とは 横 は 小数 の 組\n点 は 【JSON】 を 導出する\n", "「横」の型「小数」は【JSON】で導出できません"),
    ("「JSON」 を 読み込んで 使う\n点 とは 横 は （数 を 受け取って 数 を 返すこと） の 組\n点 は 【JSON】 を 導出する\n",
     "「横」の型「（数 を 受け取って 数 を 返すこと）」は【JSON】で導出できません"),
])
def test_導出できない型(tmp_path, source, message):
    r = _suru(str(_write(tmp_path, source)))
    assert r.returncode != 0 and message in r.stderr, r.stderr


def test_コンパイルしても同じ(tmp_path):
    path = _write(tmp_path, PROGRAM)
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(path), "-o", str(tmp_path / "py")], check=True)
    out = subprocess.run([str(tmp_path / "py")], capture_output=True, text=True)
    assert out.stdout.splitlines() == OUT


@pytest.mark.skipif(shutil.which("go") is None or shutil.which("clang") is None, reason="go か clang がありません")
def test_Go版も同じIR(tmp_path):
    from test_go_compiler import compare

    exe = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    compare(_write(tmp_path, PROGRAM), exe, tmp_path)


# かっこで型を後ろに書いた組からも同じものを導出する(#242)
PAREN_PROGRAM = PROGRAM.replace(
    "会員 とは 番号 は 数 で 名前 は 文字列 で 好物 は 文字列 の リスト で 会費済 は 真偽 の 組",
    "会員 とは 番号 （数） と 名前 （文字列） と 好物 （文字列 の リスト） と 会費済 （真偽） の 組",
).replace(
    "図形 とは 半径 は 数 の 円 か 幅 は 数 で 高 は 数 の 長方形 か 点",
    "図形 とは 半径 （数） の 円 か 幅 （数） と 高 （数） の 長方形 か 点",
).replace(
    "名簿 とは 題 は 文字列 で 人 は 会員 の リスト で 形 は 図形 で 余り は JSON の 組",
    "名簿 とは 題 (文字列) と 人 (会員 の リスト) と 形 (図形) と 余り (JSON) の組",
)


def test_かっこで型を書いた組からも導出する(tmp_path):
    assert PAREN_PROGRAM.count("（数）") == 4
    r = _suru(str(_write(tmp_path, PAREN_PROGRAM)))
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == OUT
    path = _write(tmp_path, PAREN_PROGRAM)
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(path), "-o", str(tmp_path / "py")], check=True)
    out = subprocess.run([str(tmp_path / "py")], capture_output=True, text=True)
    assert out.stdout.splitlines() == OUT


@pytest.mark.skipif(shutil.which("go") is None or shutil.which("clang") is None, reason="go か clang がありません")
def test_かっこで型を書いた組もGo版で同じIR(tmp_path):
    from test_go_compiler import compare

    exe = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    compare(_write(tmp_path, PAREN_PROGRAM), exe, tmp_path)

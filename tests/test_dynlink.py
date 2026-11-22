"""lib/動的リンク.suru と「外部の（f）」のテスト: インタプリタとコンパイルしたバイナリで同じに動くか"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

PROG = """「動的リンク」 を 読み込んで 使う
「環境」 を 読み込む
小数 を 番地 で 番地余弦にする は 小数
x を f で 番地余弦にする とは 外部の（f）
文字列 を 番地 で 番地長さ計測する は 数
s を f で 番地長さ計測する とは 外部の（f）
番地 で 数 を 整数 に 番地加算する は 数
f で a を b に 番地加算する とは 外部の（f）
番地 を 番地呼出する は 整数 の 動作
f を 番地呼出する とは 外部の（f）
試す とは 手順
  m とは 「LIBM」 を ライブラリ開封した 結果
  cos とは m から 「cos」 を 記号取得した 結果
  （0 を cos で 番地余弦にする） を 表示する
  me とは 自分取得した 結果
  strlen とは me から 「strlen」 を 記号取得した 結果
  （「あいう」 を strlen で 番地長さ計測する） を 表示する
  引数 とは 環境内の引数取得した 結果
  道 とは 引数 の 先頭
  自作 とは 道 を ライブラリ開封した 結果
  add とは 自作 から 「add」 を 記号取得した 結果
  （add で 40 を 2 に 番地加算する） を 表示する
  数える とは 自作 から 「count」 を 記号取得した 結果
  数える を 番地呼出する
  数える を 番地呼出してから 表示する
  自作 から 「nothing」 を 記号取得する
試す
"""

LIB_C = """
#include <stdint.h>
int64_t add(int64_t a, int b) { return a + b; }
static int n;
int count(void) { return ++n; }
"""

BAD_NULL = "「標準」 を 読み込んで 使う\n文字列 を 番地 で 番地長さ計測する は 数\ns を f で 番地長さ計測する とは 外部の（f）\n「a」 を （0 を 番地にする） で 番地長さ計測する\n"
BAD_TYPE = "文字列 を 数 で 番地長さ計測する は 数\ns を f で 番地長さ計測する とは 外部の（f）\n"
BAD_NAME = "文字列 を 番地 で 番地長さ計測する は 数\ns を f で 番地長さ計測する とは 外部の（g）\n"

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])


def libm() -> str:
    return "libm.dylib" if sys.platform == "darwin" else "libm.so.6"


def build(source: str, d: pathlib.Path, kind: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
    return [str(d / "prog")]


@pytest.mark.parametrize("kind", KINDS)
def test_開いて取り出して呼ぶ(tmp_path, kind):
    cc = suru_compile.find_cc() or shutil.which("cc")
    if cc is None:
        pytest.skip("C コンパイラがありません")
    (tmp_path / "lib.c").write_text(LIB_C)
    so = tmp_path / "libjisaku.so"
    subprocess.run([cc, "-shared", "-fPIC", "-o", str(so), str(tmp_path / "lib.c")], check=True)
    r = subprocess.run(build(PROG.replace("LIBM", libm()), tmp_path / kind, kind) + [str(so)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stderr
    assert r.stdout == "1\n9\n42\n2\n"
    assert "『nothing』を取り出すのに失敗しました(" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_開けないライブラリ(tmp_path, kind):
    src = "「動的リンク」 を 読み込む\n「libない.so」 を 動的リンク内のライブラリ開封する\n"
    r = subprocess.run(build(src, tmp_path / kind, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "ライブラリ『libない.so』を開くのに失敗しました(" in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_NULL_の番地は呼ばない(tmp_path, kind):
    r = subprocess.run(build(BAD_NULL, tmp_path / kind, kind), capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "外部の関数「番地長さ計測する」の「で」には関数の番地が必要です" in r.stderr


@pytest.mark.parametrize("source, message", [
    (BAD_TYPE, "「外部の（f）」の「f」は型の宣言で 番地 にしてください"),
    (BAD_NAME, "「外部の（g）」の「g」は「番地長さ計測する」の引数ではありません"),
], ids=["型", "名前"])
def test_外部の番地の間違い(tmp_path, source, message):
    src = tmp_path / "prog.suru"
    src.write_text(source, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert message in r.stderr
    if suru_compile.find_cc() is not None:
        for cmd in ([sys.executable, str(ROOT / "suru_compile.py")], ):
            r = subprocess.run(cmd + [str(src), "-o", str(tmp_path / "prog")], capture_output=True, text=True, timeout=60)
            assert r.returncode != 0
            assert message in r.stderr

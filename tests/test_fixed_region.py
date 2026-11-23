"""固定の形(標準内の固定直列化する・固定復元する)と固定領域(lib/固定領域.suru)のテスト:
インタプリタとバイナリで同じに動き、C の構造体と同じ並びになるか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

CC = suru_compile.find_cc()
KINDS = ["interp"] + (["binary"] if CC is not None else [])

ROUND = """「標準」 を 読み込んで 使う
点 とは 横 と 縦 の 組
線 とは 始め と 終わり と 見える の 組
見本 とは （（0 と 0.0 の 点） と （0 と 0.0 の 点） と 真 の 線）
b とは （（1 と 2 の 点） と （-3 と 4.5 の 点） と 偽 の 線） を 見本 で 固定直列化する
b を 数列にして 表示する
（b を 見本 で 固定復元する） を 表示する
（b を 見本 で 固定復元する） の 終わり の 縦 * 2 を 表示する
"""

ROUND_OUT = """（1 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 64 と 253 と 255 と 255 と 255 と 255 と 255 と 255 と 255 と 0 と 0 と 0 と 0 と 0 と 0 と 18 と 64 と 0 と 0 と 0 と 0 と 0 と 0 と 0 と 0）
（始め は （横 は 1 で 縦 は 2 の 点） で 終わり は （横 は -3 で 縦 は 4.5 の 点） で 見える は 偽 の 線）
9
"""

ERRORS = [
    ("人 とは 名前 と 年 の 組\nx とは （「花子」 と 3 の 人） を （「」 と 0 の 人） で 固定直列化する\nx を 表示する\n",
     "は固定の形にできません(できるのは、数と真偽だけでできた組です)"),
    ("点 とは 横 と 縦 の 組\nx とは （1 と 2.5 の 点） を （0 と 0 の 点） で 固定直列化する\nx を 表示する\n",
     "「2.5」は見本と違って整数ではありません"),
    ("図 とは 半径 の 円 か 横 の 四角\nx とは （1 の 円） を （1 の 四角） で 固定直列化する\nx を 表示する\n",
     "は見本と形が違います(見本は「四角」)"),
    ("点 とは 横 と 縦 の 組\nx は 点\nx とは （「ab」 を バイト列にする） を （0 と 0 の 点） で 固定復元する\nx を 表示する\n",
     "バイト列の長さが見本の形と違います(形は 16 バイト、バイト列は 2 バイト)"),
    ("x とは 3 を 3 で 固定直列化する\nx を 表示する\n",
     "固定の形の見本は組でなければなりません(「3」が渡されました)"),
]

# 作って書き、もう1つの接続から読む
REGION = """「固定領域」 を 読み込んで 使う
点 とは 横 と 縦 と 見える の 組
試す とは 手順
  r とは 「SHM」 を （0 と 0.0 と 偽 の 点） で 固定領域作成した 結果
  r を 固定領域読取してから 表示する
  （7 と 2.5 と 真 の 点） を r へ 固定領域書込する
  s とは 「SHM」 を （0 と 0.0 と 偽 の 点） で 固定領域接続した 結果
  s を 固定領域読取してから 表示する
  s を 固定領域解除する
  r を 固定領域解除する
試す
"""

READ_BACK = """「固定領域」 を 読み込んで 使う
点 とは 横 と 縦 と 見える の 組
試す とは 手順
  r とは 「SHM」 を （0 と 0.0 と 偽 の 点） で 固定領域接続した 結果
  r を 固定領域読取してから 表示する
  r を 固定領域解除する
  「SHM」 を 固定領域削除する
試す
"""

# 同じ並びの C の構造体で読み、書きかえる
C_SIDE = r"""#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>
struct 点 { int64_t 横; double 縦; int64_t 見える; };
int main(int argc, char **argv) {
    int fd = shm_open(argv[1], O_RDWR, 0);
    if (fd < 0) { perror("shm_open"); return 1; }
    struct 点 *p = mmap(NULL, sizeof *p, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (p == MAP_FAILED) { perror("mmap"); return 1; }
    printf("%lld %g %lld\n", (long long)p->横, p->縦, (long long)p->見える);
    p->横 = 8;
    p->縦 = -1.25;
    p->見える = 0;
    return 0;
}
"""


def build(source: str, d: pathlib.Path, kind: str, name: str = "prog") -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / f"{name}.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / name)], check=True)
    return [str(d / name)]


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("kind", KINDS)
def test_固定の形にして戻す(tmp_path, kind):
    r = run(build(ROUND, tmp_path, kind))
    assert r.returncode == 0, r.stderr
    assert r.stdout == ROUND_OUT


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("i", range(len(ERRORS)))
def test_固定の形のエラー(tmp_path, kind, i):
    source, message = ERRORS[i]
    r = run(build("「標準」 を 読み込んで 使う\n" + source, tmp_path, kind))
    assert r.returncode == 1
    assert message in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_固定領域(tmp_path, kind):
    name = f"/suru-test-{os.getpid()}-fixed-{kind}"
    try:
        r = run(build(REGION.replace("SHM", name), tmp_path, kind, "region"))
        assert r.returncode == 0, r.stderr
        assert r.stdout == "（横 は 0 で 縦 は 0 で 見える は 偽 の 点）\n（横 は 7 で 縦 は 2.5 で 見える は 真 の 点）\n"
        if CC is not None:
            c = tmp_path / "c_side.c"
            c.write_text(C_SIDE, encoding="utf-8")
            libs = ["-lrt"] if sys.platform.startswith("linux") else []
            subprocess.run([CC, str(c), "-o", str(tmp_path / "c_side")] + libs, check=True)
            r = run([str(tmp_path / "c_side"), name])
            assert r.returncode == 0, r.stderr
            assert r.stdout == "7 2.5 1\n"
            want = "（横 は 8 で 縦 は -1.25 で 見える は 偽 の 点）\n"
        else:
            want = "（横 は 7 で 縦 は 2.5 で 見える は 真 の 点）\n"
        r = run(build(READ_BACK.replace("SHM", name), tmp_path, kind, "back"))
        assert r.returncode == 0, r.stderr
        assert r.stdout == want
        assert not os.path.exists("/dev/shm" + name) or sys.platform != "linux"
    finally:
        try:
            os.unlink("/dev/shm" + name)
        except OSError:
            pass

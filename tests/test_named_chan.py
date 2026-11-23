"""名前つきの通路(スレッド内の名前つき通路作成する・接続する・削除する)のテスト:
別々に起動したプログラムどうしで値を渡せるか。インタプリタとバイナリで同じに動くか"""

import os
import pathlib
import subprocess
import sys
import time

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

HEAD = """「スレッド」 を 読み込んで 使う
点 とは 横 と 縦 の 組
"""

# 受け取る側: 通路を作り(もうあればそれを使い)、閉じるまで受け取って 横 を表示する。最後に数と、消した結果
READER = HEAD + """点 の 通路 を 受信続けする は 数 の 動作
c を 受信続けする とは c を （p を 受け取って p の 横 を 表示する を 返すこと） で 通路処理する
試す とは 手順
  c とは 「FIFO」 を 名前つき通路作成した 結果
  n とは c を 受信続けした 結果
  n を 表示する
  「FIFO」 を 名前つき通路削除してから 表示する
試す
"""

# 送る側: 大きな値(パイプに一度に入らない大きさ)を 20 回送る。横 は 送る人の番号 * 100 + 回
WRITER = HEAD + """「標準」 を 読み込んで 使う
長い とは （「あいうえおかきくけこ」 を 5000 で 複製する） を 「」 で 結合する
点 の 通路 を 数 で 送信続けする は 数 の 動作
c を n で 送信続けする とは もし n = 0 ならば 0 を 結果にする そうでなければ c を n で 一回送信する
点 の 通路 を 数 で 一回送信する は 数 の 動作
c を n で 一回送信する とは 手順
  （（ID * 100 + n） と 長い の 点） を c へ 通路送信する
  c を n - 1 で 送信続けする
試す とは 手順
  c とは 「FIFO」 を 名前つき通路接続した 結果
  c を 20 で 送信続けする
試す
"""

ERRORS = [
    ("「FILE」 を 名前つき通路作成する\n", "』はすでにあり、名前つきの通路ではありません"),
    ("「FILE」 を 名前つき通路接続する\n", "』は名前つきの通路ではありません"),
    ("「NONE」 を 名前つき通路接続する\n", "』に接続できませんでした("),
    ("「NONE」 を 名前つき通路削除する\n", "』を消せませんでした("),
]


def build(source: str, d: pathlib.Path, kind: str, name: str) -> list[str]:
    d.mkdir(exist_ok=True)
    src = d / f"{name}.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        return [sys.executable, str(ROOT / "suru.py"), str(src)]
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / name)], check=True)
    return [str(d / name)]


def run_two_writers(tmp_path: pathlib.Path, reader_kind: str, writer_kinds: tuple) -> None:
    fifo = str(tmp_path / "chan")
    os.mkfifo(fifo, 0o600)
    reader = build(READER.replace("FIFO", fifo), tmp_path, reader_kind, "reader")
    writers = [build(WRITER.replace("FIFO", fifo).replace("ID", str(i + 1)), tmp_path, k, f"writer{i}")
               for i, k in enumerate(writer_kinds)]
    # 送る側を先に起動する(受け取る側が開くまで待つ)。2人とも開いてから受け取る側が開けば、
    # 2人とも送り終えるまで受け取る側は閉じたと思わない
    ws = [subprocess.Popen(w, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for w in writers]
    time.sleep(1.5)
    r = subprocess.run(reader, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        for w in ws:
            w.kill()
    assert r.returncode == 0, r.stderr
    for w in ws:
        _, err = w.communicate(timeout=60)
        assert w.returncode == 0, err
    lines = r.stdout.splitlines()
    assert lines[-2:] == ["40", "0"]
    want = sorted(str(i * 100 + n) for i in (1, 2) for n in range(1, 21))
    assert sorted(lines[:-2]) == want
    # 1人の送ったものは送った順に届く
    for i in (1, 2):
        mine = [int(x) for x in lines[:-2] if int(x) // 100 == i]
        assert mine == sorted(mine, reverse=True)
    assert not os.path.exists(fifo)


@pytest.mark.parametrize("kind", KINDS)
def test_送る人が2人(tmp_path, kind):
    run_two_writers(tmp_path, kind, (kind, kind))


@pytest.mark.skipif(len(KINDS) < 2, reason="C コンパイラがない")
def test_インタプリタとバイナリの間(tmp_path):
    run_two_writers(tmp_path, "binary", ("interp", "binary"))


@pytest.mark.parametrize("kind", KINDS)
def test_受け取る側が作る(tmp_path, kind):
    fifo = str(tmp_path / "chan")
    reader = build(READER.replace("FIFO", fifo), tmp_path, kind, "reader")
    writer = build(WRITER.replace("FIFO", fifo).replace("ID", "3"), tmp_path, kind, "writer")
    rp = subprocess.Popen(reader, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for _ in range(600):
        if os.path.exists(fifo):
            break
        time.sleep(0.05)
    w = subprocess.run(writer, capture_output=True, text=True, timeout=120)
    if w.returncode != 0:
        rp.kill()
    out, err = rp.communicate(timeout=60)
    assert w.returncode == 0, w.stderr
    assert rp.returncode == 0, err
    assert out.splitlines() == [str(300 + n) for n in range(20, 0, -1)] + ["20", "0"]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("i", range(len(ERRORS)))
def test_名前つき通路のエラー(tmp_path, kind, i):
    source, message = ERRORS[i]
    f = tmp_path / "file"
    f.write_text("x")
    src = "「スレッド」 を 読み込んで 使う\n" + source.replace("FILE", str(f)).replace("NONE", str(tmp_path / "none"))
    r = subprocess.run(build(src, tmp_path, kind, "prog"), capture_output=True, text=True, timeout=120)
    assert r.returncode == 1
    assert message in r.stderr

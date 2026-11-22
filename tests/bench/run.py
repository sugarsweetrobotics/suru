"""バイナリの速さとメモリを測る(テストではない。機械によって揺れるので記録用)

    python3 tests/bench/run.py          # tests/bench/*.suru をバイナリにして、3回ずつ動かす

最短の時間、最大のメモリ(RSS)、GC の回数を表示する。
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for src in sorted(pathlib.Path(__file__).parent.glob("*.suru")):
            ll = pathlib.Path(tmp) / "prog.ll"
            ll.write_text(suru_compile.compile_source(src.read_text(encoding="utf-8"), str(src.parent)), encoding="utf-8")
            exe = pathlib.Path(tmp) / src.stem
            suru_compile.build(str(ll), str(exe))
            times, rss, gcs = [], 0, 0
            for _ in range(3):
                t = time.perf_counter()
                p = subprocess.Popen([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                     env={**os.environ, "SURU_GC_LOG": "1"})
                err = p.stderr.read()
                _, _, usage = os.wait4(p.pid, 0)
                times.append(time.perf_counter() - t)
                rss = max(rss, usage.ru_maxrss)
                gcs = err.count("\nGC ") + err.startswith("GC ")
            print(f"{src.stem}: {min(times):.3f}秒、最大 {rss // 1024}MB、GC {gcs}回")


if __name__ == "__main__":
    main()

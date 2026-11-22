"""lib/時間.suru のテスト: インタプリタとコンパイルしたバイナリで同じ結果になるか"""

import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

CALENDAR = """「時間」 を 読み込んで 使う
d とは 1763807472 を 32400 で 日時にする
d
d を 時刻にする
d を 国際書式にする
d を 曜日にする
d を 和暦にする
d を 「%Y年%m月%d日（%a） %H時%M分%S秒 %z」 で 書式にする
d を -3600 で 秒数加算して 国際書式にする
d を 40 で 日数加算して 日付文字列にする
（2024 と 1 と 31） を 日付作成して 1 で 月数加算する
（2024 と 2 と 29） を 日付作成して 1 で 年数加算して 日付文字列にする
（2024 と 11 と 30） を 日付作成して -11 で 月数加算して 日付文字列にする
（2019 と 5 と 1） を 日付作成して 和暦にする
（2019 と 4 と 30） を 日付作成して 和暦にする
（1868 と 10 と 23） を 日付作成して 和暦にする
（1970 と 1 と 1） を 日付作成して 時刻にする
（2000 と 3 と 1） を 日付作成して 曜日にする
（1969 と 12 と 31） を 日付作成して 曜日番号にする
-1 を 世界日時にする
1.75 を 世界日時にして 時刻文字列にする
（（2024 と 1 と 1） を 日付作成する） から （（2025 と 1 と 1） を 日付作成する） を 日数差にする
（1 を 世界日時にする） から （d） を 秒数差にする
2000 が 閏年である
1900 が 閏年である
2024 が 閏年である
（2023 と 2 と 1） を 日付作成して 月日数にする
（2024 と 2 と 1） を 日付作成して 月日数にする
（2024 と 4 と 1） を 日付作成して 月日数にする
-12600 を 0 で 日時にして 時差文字列にする
0 を -12600 で 日時にして 国際書式にする
"""

CALENDAR_OUT = """（年 は 2025 で 月 は 11 で 日 は 22 で 時 は 19 で 分 は 31 で 秒 は 12 で 時差 は 32400 の 日時）
1763807472
2025-11-22T19:31:12+09:00
土
令和7年11月22日
2025年11月22日（土） 19時31分12秒 +09:00
2025-11-22T18:31:12+09:00
2026-01-01
（年 は 2024 で 月 は 2 で 日 は 29 で 時 は 0 で 分 は 0 で 秒 は 0 で 時差 は 0 の 日時）
2025-02-28
2023-12-30
令和元年5月1日
平成31年4月30日
1868年10月23日
0
水
3
（年 は 1969 で 月 は 12 で 日 は 31 で 時 は 23 で 分 は 59 で 秒 は 59 で 時差 は 0 の 日時）
00:00:01
366
1763807471
真
偽
真
28
29
30
Z
1969-12-31T20:30:00-03:30
"""

CLOCK = """「時間」 を 読み込んで 使う
試す とは 手順
  t とは 現在時刻取得した 結果
  （t > 1700000000） を 表示する
  0.05 を 待機する
  e とは t を 経過秒取得した 結果
  （e >= 0.05 かつ e < 5） を 表示する
  1763807472 を 時差取得してから 表示する
  1751328000 を 時差取得してから 表示する
  1763807472 を 現地日時取得してから 国際書式にして 表示する
  d とは 現在日時取得した 結果
  （d の 年 >= 2025） を 表示する
試す
"""

FAIL_SLEEP = "「時間」 を 読み込む\n-1 を 時間内の待機する\n"


def run_both(source: str, tmp_path: pathlib.Path, env=None):
    src = tmp_path / "prog.suru"
    src.write_text(source, encoding="utf-8")
    env = dict(os.environ, **(env or {}))
    out = [subprocess.run([sys.executable, str(ROOT / "suru.py"), str(src)], capture_output=True, text=True, timeout=60, env=env)]
    if suru_compile.find_cc() is not None:
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(tmp_path / "prog")], check=True)
        out.append(subprocess.run([str(tmp_path / "prog")], capture_output=True, text=True, timeout=60, env=env))
    return out


def test_暦(tmp_path):
    for r in run_both(CALENDAR, tmp_path):
        assert r.returncode == 0, r.stderr
        assert r.stdout == CALENDAR_OUT


@pytest.mark.parametrize("tz, want", [
    ("UTC", "0\n0\n2025-11-22T10:31:12Z\n"),
    ("Asia/Tokyo", "32400\n32400\n2025-11-22T19:31:12+09:00\n"),
    ("America/New_York", "-18000\n-14400\n2025-11-22T05:31:12-05:00\n"),
])
def test_時計と時差(tmp_path, tz, want):
    if not pathlib.Path("/usr/share/zoneinfo", tz).exists() and tz != "UTC":
        pytest.skip("時間帯のデータがありません")
    for r in run_both(CLOCK, tmp_path, {"TZ": tz}):
        assert r.returncode == 0, r.stderr
        assert r.stdout == "真\n真\n" + want + "真\n"


def test_待てない時間(tmp_path):
    for r in run_both(FAIL_SLEEP, tmp_path):
        assert r.returncode == 1
        assert "待つのに失敗しました(Invalid argument)" in r.stderr

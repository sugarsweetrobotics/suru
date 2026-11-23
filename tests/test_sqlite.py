"""lib/SQLite.suru のテスト: インタプリタとコンパイルしたバイナリで同じに動くか

libsqlite3 がなければ飛ばす。Go 版コンパイラとの比べ合わせは test_go_compiler.py が、ここに書いたプログラムで行う。
"""

import ctypes.util
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru_compile  # noqa: E402

pytestmark = pytest.mark.skipif(ctypes.util.find_library("sqlite3") is None, reason="libsqlite3 がありません")

KINDS = ["interp"] + (["binary"] if suru_compile.find_cc() is not None else [])

PROG = """「SQLite」 を 読み込んで 使う
「標準」 を 読み込んで 使う
SQL値 の リスト を 行文字列にする は 文字列
行 を 行文字列にする とは 行 の それぞれ を SQL値文字列にして 「 | 」 で 結合する
試す とは 手順
  db とは 「:memory:」 を SQLite開封した 結果
  （db に 「CREATE TABLE 人 (id INTEGER PRIMARY KEY, 名前 TEXT, 点 REAL, 写真 BLOB); INSERT INTO 人 (名前, 点) VALUES ('花子', 90.5)」 を SQLite実行した 結果） を 表示する
  （db に 「INSERT INTO 人 (名前, 点, 写真) VALUES (?, ?, ?)」 を （（「太郎」 の SQL文字列） と （72 の SQL数） と （（（1 と 2 と 255） を バイト列組立する） の SQLバイト列）） で SQLite差込実行した 結果） を 表示する
  （db に 「INSERT INTO 人 (名前, 点, 写真) VALUES (?, ?, ?)」 を （（（「改行」 + 改行 + 「と'引用'」） の SQL文字列） と SQL無 と （（空 を バイト列組立する） の SQLバイト列）） で SQLite差込実行した 結果） を 表示する
  db を SQLite最終行番号取得してから 表示する
  行群 とは db に 「SELECT * FROM 人 ORDER BY id」 を SQLite問合した 結果
  行群 の それぞれ を 行文字列にして 改行 で 結合して 表示する
  （db に 「SELECT 名前, 点 * 2, typeof(点) FROM 人 WHERE 点 > ?」 を （（80 の SQL数） を 空 に 挿入する） で SQLite差込問合した 結果） を 表示する
  （db に 「SELECT id AS 番号, 名前 FROM 人」 を SQLite列名取得した 結果） を 表示する
  （db に 「UPDATE 人 SET 点 = 点 + 1」 を SQLite実行した 結果） を 表示する
  （db に 「SELECT count(*), sum(点), NULL, x'', 1.5, -3 FROM 人」 を SQLite問合した 結果） を 表示する
  （db に 「SELECT * FROM 人 WHERE id > 100」 を SQLite問合した 結果） を 表示する
  （db に 「SELECT 1」 を （（1 の SQL数） を 空 に 挿入する） で SQLite差込問合する） を （「多すぎる値」 を 表示する） で 試行する
  （db に 「SELEC 1」 を SQLite問合する） を （「読めない文」 を 表示する） で 試行する
  （db に 「INSERT INTO 無い表 VALUES (1)」 を SQLite実行する） を （「無い表」 を 表示する） で 試行する
  （db に 「」 を SQLite問合する） を （「空の文」 を 表示する） で 試行する
  数群 とは db に 「WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 5000) SELECT x FROM c」 を SQLite問合した 結果
  数群 の 長さ を 表示する
  （数群 の 最後 の 先頭 を SQL値文字列にする） を 表示する
  db を SQLite閉鎖してから 表示する
試す
（「/存在しない/フォルダ/a.db」 を SQLite開封する） を （「開けない」 を 表示する） で 試行する
"""

OUT = """1
1
1
3
1 | 花子 | 90.5 | NULL
2 | 太郎 | 72 | バイト列(3バイト)
3 | 改行
と'引用' | NULL | バイト列(0バイト)
（（（SQL文字値 は 「花子」 の SQL文字列） と （SQL数値 は 181 の SQL数） と （SQL文字値 は 「real」 の SQL文字列）））
（「番号」 と 「名前」）
3
（（（SQL数値 は 3 の SQL数） と （SQL数値 は 164.5 の SQL数） と SQL無 と （SQLバイト値 は バイト列（） の SQLバイト列） と （SQL数値 は 1.5 の SQL数） と （SQL数値 は -3 の SQL数）））
空
多すぎる値
読めない文
無い表
空の文
5000
5000
0
開けない
"""

ERRORS = [
    "SQLite で『SELECT 1』を実行するとき、1番目の値を入れるのに失敗しました(column index out of range)",
    "SQLite で『SELEC 1』を実行するのに失敗しました(near \"SELEC\": syntax error)",
    "SQLite で『INSERT INTO 無い表 VALUES (1)』を実行するのに失敗しました(no such table: 無い表)",
    "SQLite で『』を実行するのに失敗しました(文がありません)",
    "SQLite で『/存在しない/フォルダ/a.db』を開くのに失敗しました(unable to open database file)",
]

# ファイルのデータベースに書いて、別の実行で読む
WRITE = """「SQLite」 を 読み込んで 使う
試す とは 手順
  db とは 「DB」 を SQLite開封した 結果
  db に 「CREATE TABLE 記録 (文 TEXT)」 を SQLite実行する
  db に 「INSERT INTO 記録 VALUES (?)」 を （（「残る」 の SQL文字列） を 空 に 挿入する） で SQLite差込実行する
  db を SQLite閉鎖する
試す
"""

READ = """「SQLite」 を 読み込む
試す とは 手順
  db とは 「DB」 を SQLite内のSQLite開封した 結果
  行群 とは db に 「SELECT 文 FROM 記録」 を SQLite内のSQLite問合した 結果
  （行群 の 先頭 の 先頭 を SQLite内のSQL値文字列にする） を 表示する
  db を SQLite内のSQLite閉鎖する
試す
"""


def run(source: str, d: pathlib.Path, kind: str) -> subprocess.CompletedProcess:
    d.mkdir(exist_ok=True)
    src = d / "prog.suru"
    src.write_text(source, encoding="utf-8")
    if kind == "interp":
        cmd = [sys.executable, str(ROOT / "suru.py"), str(src)]
    else:
        subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(src), "-o", str(d / "prog")], check=True)
        cmd = [str(d / "prog")]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("kind", KINDS)
def test_SQLite(tmp_path, kind):
    r = run(PROG, tmp_path / kind, kind)
    assert r.returncode == 0, r.stderr
    assert r.stdout == OUT
    for e in ERRORS:
        assert e in r.stderr


@pytest.mark.parametrize("kind", KINDS)
def test_ファイルに残る(tmp_path, kind):
    db = tmp_path / f"{kind}.db"
    w = run(WRITE.replace("DB", str(db)), tmp_path / f"{kind}-w", kind)
    assert w.returncode == 0, w.stderr
    r = run(READ.replace("DB", str(db)), tmp_path / f"{kind}-r", kind)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "残る\n"

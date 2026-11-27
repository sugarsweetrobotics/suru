"""定義の説明(定義のすぐ上の注釈)とファイルの説明を読む(#209)。compiler/doc_test.go と同じ例"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from suru import ParseContext, doc_comments, parse_program  # noqa: E402

LIB = pathlib.Path(__file__).resolve().parent.parent / "lib"

SRC = """# SPDX-License-Identifier: MIT
# Copyright (c) 2026 だれか
# 計算のライブラリ
#
#   n を 二倍する … 2倍

# 数を2倍します。
#
# 負の数もそのまま2倍します。
数 を 二倍する は 数 を 返す
n を 二倍する とは n * 2 です

例えば 3 を 二倍する は 6 です

# これは説明ではない(空行がある)

n を 三倍する とは n * 3 です

# 円周率の近い値
# 点検しない: 未使用の定義
円周率 とは 3.14 です

# 図形の形
図形 とは 半径 の 円 か 幅 と 高 の 長方形 です
"""


def test_doc_comments():
    module, names = doc_comments(SRC, parse_program(SRC, ParseContext()))
    assert module == "計算のライブラリ\n\n  n を 二倍する … 2倍"
    assert names == {
        "二倍する": "数を2倍します。\n\n負の数もそのまま2倍します。",
        "円周率": "円周率の近い値",
        "図形": "図形の形",
    }


def test_head_comment_is_not_a_description():
    src = "# ファイルの説明\nn を 二倍する とは n * 2\n"
    assert doc_comments(src, parse_program(src)) == ("ファイルの説明", {})


def test_library_files():
    """標準ライブラリのファイルが全部読める(説明の付いた定義があるものを1つ確かめる)"""
    for path in sorted(LIB.glob("*.suru")):
        src = path.read_text(encoding="utf-8")
        module, names = doc_comments(src, parse_program(src))
        if path.name == "通信.suru":
            assert module.startswith("「する」の通信ライブラリ(TCP)")
            assert names["UDP便"].startswith("受け取った便り。")


# --- suru --文書(段階2) ---

import json  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import pytest  # noqa: E402

from suru import doc_markdown, document, private_names  # noqa: E402

ROOT = LIB.parent

API_SRC = """# 計算のライブラリです。

# 数を2倍した値です。
数 を 二倍する は 数 を 返す
x を 二倍する とは x * 2 です
例えば （3 を 二倍する） は 6 です
例えば （0 を 二倍する） は 0 です

# 円周率の近い値です。
円周率 とは 3.14 です

# 図形です。
図形 とは
  半径 の 円
    か 幅 と 高 の 長方形

a と b を 足す計算する とは a + b です

n を 内緒する とは n です

内緒する は 非公開とする
"""

API_MD = """# 「計算」

計算のライブラリです。

## 二倍する

```suru
数 を 二倍する は 数 を 返す
```

使い方: `x を 二倍する`

数を2倍した値です。

例:

```suru
例えば （3 を 二倍する） は 6 です
例えば （0 を 二倍する） は 0 です
```

## 円周率

円周率の近い値です。

## 図形

```suru
図形 とは
  半径 の 円
    か 幅 と 高 の 長方形
```

図形です。

## 足す計算する

使い方: `a と b を 足す計算する`
"""


def test_document_markdown():
    program = parse_program(API_SRC)
    d = document(API_SRC, program, private_names(program))
    d["module"] = "計算"
    assert doc_markdown(d) == API_MD
    kinds = {it["name"]: it["kind"] for it in d["items"]}
    assert kinds == {"二倍する": "関数", "円周率": "値", "図形": "型", "足す計算する": "関数"}


def test_doc_command(tmp_path):
    (tmp_path / "計算.suru").write_text(API_SRC, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--文書", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == API_MD
    out = tmp_path / "出力"
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--文書", "--json", "--出力", str(out), str(tmp_path / "計算.suru")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    d = json.loads((out / "計算.json").read_text(encoding="utf-8"))
    assert d["module"] == "計算" and d["items"][0]["examples"][1] == "例えば （0 を 二倍する） は 0 です"


def test_doc_command_syntax_error(tmp_path):
    (tmp_path / "壊れ.suru").write_text("x を 二倍する とは （x\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--文書", "--json", str(tmp_path / "壊れ.suru")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and json.loads(r.stderr.splitlines()[0])["kind"] == "構文"


@pytest.mark.skipif(shutil.which("go") is None, reason="go がありません")
def test_go_version_gives_the_same_documents(tmp_path):
    """Go 版(suruc --文書)と Python 版が、lib/ の全部のファイルで同じ JSON と Markdown を出す"""
    exe = tmp_path / "suruc"
    subprocess.run(["go", "build", "-o", str(exe), "./cmd/suruc"], cwd=ROOT, check=True)
    for args in (["--json"], []):
        py = subprocess.run([sys.executable, str(ROOT / "suru.py"), "--文書", *args, "lib"], cwd=ROOT, capture_output=True, text=True)
        go = subprocess.run([str(exe), "--文書", *args, "lib"], cwd=ROOT, capture_output=True, text=True)
        assert py.returncode == 0 and go.returncode == 0, py.stderr + go.stderr
        assert py.stdout == go.stdout

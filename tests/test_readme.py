"""README.md(英語、正)と README_jp.md(日本語、副)の形がそろっているかを確かめる。

節(## と ###)の数と深さ、節ごとの番号の項目の数、表の行の数、コードの例が同じでなければならない。
片方だけを直したときに気づけるようにするためのもの(CLAUDE.md の「README は英語が正、日本語が副」)。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAIRS = [
    (ROOT / "README.md", ROOT / "README_jp.md"),
    (ROOT / "editors" / "vscode" / "README.md", ROOT / "editors" / "vscode" / "README_jp.md"),
]


def shape(path):
    """節ごとに (見出しの深さ, 番号の項目の数, 表の行の数, コードの例) を並べる。"""
    sections = []
    level, items, rows, code = 0, 0, 0, []
    in_code = False
    block = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            if in_code:
                code.append("\n".join(block))
                block = []
            in_code = not in_code
            continue
        if in_code:
            # コードの中の注釈(# の後ろ)は訳してよいので比べない
            block.append(re.sub(r"\s+#.*$", "", line).rstrip())
            continue
        m = re.match(r"^(#{1,6}) ", line)
        if m:
            sections.append((level, items, rows, code))
            level, items, rows, code = len(m.group(1)), 0, 0, []
        elif re.match(r"^ *\d+\. ", line):
            items += 1
        elif line.startswith("|"):
            rows += 1
    sections.append((level, items, rows, code))
    return sections


@pytest.mark.parametrize("en,ja", PAIRS, ids=lambda p: str(p.relative_to(ROOT)))
def test_readme_shapes_match(en, ja):
    a, b = shape(en), shape(ja)
    assert len(a) == len(b), f"{en.name} と {ja.name} の節の数が違います"
    for i, (x, y) in enumerate(zip(a, b)):
        assert x[:3] == y[:3], f"{i} 番目の節の形(深さ・項目・表の行)が違います: {x[:3]} と {y[:3]}"
        assert x[3] == y[3], f"{i} 番目の節のコードの例が違います"


@pytest.mark.parametrize("en,ja", PAIRS, ids=lambda p: str(p.relative_to(ROOT)))
def test_readme_links_each_other(en, ja):
    assert "(README_jp.md)" in en.read_text(encoding="utf-8").splitlines()[0]
    assert "(README.md)" in ja.read_text(encoding="utf-8").splitlines()[0]

# 「する」本体のドキュメント(Sphinx + MyST、Read the Docs で公開、#209)
# 標準ライブラリの API のページ(api/)は、ビルドの前に
#   python suru.py --文書 --出力 docs/api lib
# が作ります(.readthedocs.yaml)。する のコードの色付けは kumu 文書 --雛形 と同じ lexer を使います。
import os
import re
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.join(_here, "..")
sys.path.insert(0, os.path.join(_root, "cmd", "kumu", "docs_template"))

_m = re.search(r'__version__ = "([^"]+)"', open(os.path.join(_root, "suru.py"), encoding="utf-8").read())

project = "する"
copyright = "2026 sugarsweetrobotics"
release = _m.group(1) if _m else ""
version = release
language = "ja"

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
myst_heading_anchors = 3
# 今後の候補とリリースの手順は、使う人向けのページではないので入れない
exclude_patterns = ["_build", "今後", "リリース.md", "conf.py"]
html_theme = "furo"
html_title = f"「する」 {release}"
highlight_language = "suru"
suppress_warnings = ["myst.header", "myst.xref_missing"]


def setup(app):
    from suru_lexer import SuruLexer

    app.add_lexer("suru", SuruLexer)
    app.add_lexer("suru-誤り", SuruLexer)  # AI の手引きの、検査でエラーになる例

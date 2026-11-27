# Documentation of Suru itself (Sphinx + MyST, published on Read the Docs, #209).
# The API pages of the standard library (api/) are made before the build by
#   python suru.py --文書 --出力 docs/api lib
# (.readthedocs.yaml). Suru code is highlighted by the same lexer as kumu 文書 --雛形.
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
language = "en"

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
myst_heading_anchors = 3
# Future candidates and the release steps are not pages for users
exclude_patterns = ["_build", "今後", "リリース.md", "ライブラリを公開する.md", "公式ライブラリ.md", "conf.py"]
html_theme = "furo"
html_title = f"「する」 {release}"
highlight_language = "suru"
suppress_warnings = ["myst.header", "myst.xref_missing"]


def setup(app):
    from suru_lexer import SuruLexer

    app.add_lexer("suru", SuruLexer)
    app.add_lexer("suru-誤り", SuruLexer)  # examples in the AI guide that fail the check

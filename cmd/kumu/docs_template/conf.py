# Sphinx の設定(kumu 文書 --雛形 が書いたもの。自由に直してかまいません)
# API のページ(api/)は、ビルドの前に kumu 文書 --出力 docs/api が作ります。
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_ext"))

_here = os.path.dirname(os.path.abspath(__file__))
_config = os.path.join(_here, "..", "組.suru")
_text = open(_config, encoding="utf-8").read() if os.path.exists(_config) else ""
_m = re.search(r"^版\s*とは\s*「([^」]*)」", _text, re.M)

project = "{{名前}}"
release = _m.group(1) if _m else ""
version = release
language = "ja"

extensions = ["myst_parser"]
source_suffix = {".md": "markdown"}
myst_heading_anchors = 3
exclude_patterns = ["_build"]
html_theme = "furo"
html_title = f"「{project}」 {release}"
html_show_copyright = False  # 持ち主を書くなら copyright = "…" にして、この行を消します
highlight_language = "suru"


def setup(app):
    from suru_lexer import SuruLexer

    app.add_lexer("suru", SuruLexer)

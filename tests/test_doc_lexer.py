"""kumu 文書 --雛形 が書く Pygments の lexer(cmd/kumu/docs_template/suru_lexer.py、#209)"""

import importlib.util
import pathlib

import pytest

pytest.importorskip("pygments")

from pygments.token import Comment, Keyword, Name, Number, String  # noqa: E402

PATH = pathlib.Path(__file__).resolve().parent.parent / "cmd" / "kumu" / "docs_template" / "suru_lexer.py"


def lexer():
    spec = importlib.util.spec_from_file_location("suru_lexer", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.SuruLexer()


def test_tokens():
    src = "# 説明\n数 を 二倍する は 数 を 返す\nx を 二倍する とは x * 2 です\n「「a」b」 を 表示する\n例えば （3 を 算術内の二倍する） は 6 です\n"
    toks = [(t, v) for t, v in lexer().get_tokens(src) if v.strip()]
    assert (Comment.Single, "# 説明") in toks
    assert (Name.Function, "二倍する") in toks
    assert (Keyword, "とは") in toks and (Keyword, "です") in toks and (Keyword, "返す") in toks
    assert (Number, "2") in toks
    assert "".join(v for t, v in toks if t in String) == "「「a」b」"
    assert (Name.Namespace, "算術内の") in toks
    assert (Keyword, "例えば") in toks

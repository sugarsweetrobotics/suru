# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""VS Code 拡張の色分けの文法(syntaxes/suru.tmLanguage.json)を作る。

キーワード・助詞・組み込み関数の一覧は suru.py と suru_check.py から取るので、
言語に言葉を足したら、リポジトリの一番上で

    python3 editors/vscode/make_grammar.py

を実行して作り直します(tests/test_vscode_grammar.py が古いままだと失敗します)。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "syntaxes", "suru.tmLanguage.json")
# 文字列。中の「」は入れ子として数える(Oniguruma の \g<名前> で再帰する)
STRING = "(?<str>「(?:[^「」]|\\g<str>)*」)"


def alt(words):
    """長いものから順に並べた選択(同じ文字で始まる短い語に先に当たらないように)"""
    return "(?:" + "|".join(sorted(set(words), key=lambda w: (-len(w), w))) + ")"


def build() -> dict:
    sys.path.insert(0, ROOT)
    import suru
    import suru_check

    # 名前に使える文字: ひらがな以外の文字と「_」(字句解析の charClass の NAME と同じ)。数字は2文字目から
    name_start = r"[\p{L}_&&[^ぁ-ゟ]]"
    name_char = r"[\p{L}\p{Nd}_&&[^ぁ-ゟ]]"
    not_before = f"(?<!{name_char})"
    not_after = f"(?!{name_char})"
    # 関数名の語幹: 名前の文字の並び(「畳み込み」のようにひらがなを含む決まった名前も)。
    # 語幹の後ろにひらがなが続いてから「する」などで終わるもの(「数値にする」)も1つの名前
    # 空白の書き方の単語に入る文字(空白・括弧・文字列・演算子以外)
    word_char = "[^\\s　（）()「」『』。、#＃※+\\-*/%^<>=!−×÷＋－＊／％＾＝≠≦≧≤≥＜＞・]"
    stem = f"(?:{alt(suru.MIXED_NAMES)}|{name_char})+"
    forms = alt(suru.CALL_FORMS)
    call = f"{stem}\\p{{Hiragana}}*?{forms}"

    def stem_of(name):
        for form in ("である", "する"):
            if name.endswith(form):
                return name[: -len(form)]
        return name

    builtins = sorted({stem_of(n) for n in suru_check.BUILTIN_CALLS} | {stem_of(b.name) for b in suru.BUILTINS})

    control = [suru.KW_IF, suru.KW_THEN, suru.KW_ELSE, suru.KW_PROVISO, suru.KW_SOREKARA, suru.KW_KATSU, suru.KW_MATAHA]
    declare = [suru.KW_TOWA, suru.KW_TOIU, suru.KW_KA, suru.KW_WA, suru.DESU]
    particles = list(suru.PARTICLES) + [suru.KW_TO, suru.KW_NO, suru.KW_GA]
    hira_props = [p for p in suru.PROPERTIES if all("ぁ" <= c <= "ゟ" for c in p)]
    kanji_props = [p for p in suru.PROPERTIES if p not in hira_props]
    imports = [suru.KW_IMPORT, suru.KW_IMPORT_POLITE, suru.KW_IMPORT_TE, suru.KW_USE, suru.KW_USE_POLITE, suru.KW_EXTERN, suru.KW_MAIN_THREAD]

    def word(words):
        return f"{not_before}{alt(words)}{not_after}"

    patterns = {
        "comment": {
            "name": "comment.line.suru",
            "match": "(?<![^\\s　、。（）()」])[#＃※].*$",
        },
        # 試験のまとまりの頭「以下は「二倍」の試験です」と、例の「例えば」(#193)
        "test": {
            "patterns": [
                {
                    "match": f"{not_before}(以下[ 　]*は[ 　]*)(「[^「」]*」)([ 　]*の[ 　]*試験)",
                    "captures": {
                        "1": {"name": "keyword.control.suru"},
                        "2": {"name": "string.quoted.other.suru"},
                        "3": {"name": "keyword.control.suru"},
                    },
                },
                {"name": "keyword.control.suru", "match": f"^[ 　]*{suru.KW_EXAMPLE}{not_after}"},
            ]
        },
        "string": {
            "patterns": [
                # 文字列の中の「」は入れ子として数える(「失敗: 「abc」は数にできません」)
                {"name": "string.quoted.other.suru", "match": STRING},
                {"name": "invalid.illegal.unclosed-string.suru", "match": "「.*$"},
            ]
        },
        "quoted-name": {
            "patterns": [
                {
                    "match": f"(『)([^』]*)(』)(\\p{{Hiragana}}*?{forms})",
                    "captures": {
                        "1": {"name": "punctuation.definition.name.begin.suru"},
                        "2": {"name": "entity.name.function.suru"},
                        "3": {"name": "punctuation.definition.name.end.suru"},
                        "4": {"name": "entity.name.function.suru"},
                    },
                },
                {
                    "match": "(『)([^』]*)(』)",
                    "captures": {
                        "1": {"name": "punctuation.definition.name.begin.suru"},
                        "2": {"name": "variable.other.suru"},
                        "3": {"name": "punctuation.definition.name.end.suru"},
                    },
                },
            ]
        },
        "import": {
            "name": "keyword.control.import.suru",
            "match": alt(imports),
        },
        "module": {
            # 数学内の二乗する の「数学内の」
            "match": f"{not_before}({name_char}+?)({suru.MODULE_MARK})({suru.KW_NO})",
            "captures": {
                "1": {"name": "entity.name.namespace.suru"},
                "2": {"name": "keyword.operator.module.suru"},
                "3": {"name": "keyword.operator.module.suru"},
            },
        },
        "lambda": {
            "name": "keyword.other.lambda.suru",
            "match": alt([suru.KW_LAMBDA, suru.KW_RETURN]),
        },
        # 関数の型の宣言の終わりの飾り「数 を 返す」「数 を 返します」(「返すこと」は lambda)
        "returns": {
            "name": "keyword.other.declaration.suru",
            "match": f"{not_before}{alt([suru.KW_HENSU, suru.KW_HENSU_POLITE])}(?!こと){not_after}",
        },
        "builtin": {
            "name": "support.function.builtin.suru",
            "match": f"{not_before}{alt(builtins)}{forms}",
        },
        # 句読点の書き方の行: 文字種の境目で単語が切れるので、語幹は名前の文字だけ
        "call": {
            "name": "entity.name.function.suru",
            "match": f"{not_before}{call}",
        },
        # 空白の書き方の行: 空白から空白までが1つの単語なので、語幹にひらがなが混ざってもよい(「大きい方にする」)
        "spaced-call": {
            "name": "entity.name.function.suru",
            "match": f"(?<=^|[\\s　（）()]|{suru.MODULE_SEP}){word_char}+?{forms}(?=$|[\\s　（）()])",
        },
        # 導出「会員 は 【JSON】 と 【表】 を 導出する」の【JSON】と「導出する」(#192)
        "quasi-name": {
            "match": "(【)([^【】 　]+)(】)",
            "captures": {
                "1": {"name": "punctuation.definition.tag.suru"},
                "2": {"name": "entity.name.tag.suru"},
                "3": {"name": "punctuation.definition.tag.suru"},
            },
        },
        "derive": {
            "name": "keyword.other.declaration.suru",
            "match": f"{not_before}導出(?:する|します)(?=[ 　]*。?[ 　]*(?:[#＃].*)?$)",
        },
        "kanji-keyword": {
            "patterns": [
                # 「以下の手順です」「以下 の 入出力手順」と、閉じる「以上」
                {"name": "keyword.control.suru", "match": f"{not_before}以下[ 　]*[のは][ 　]*外部[ 　]*の[ 　]*(?:入出力動作|関数)"},
                {"name": "keyword.control.suru", "match": f"{not_before}以下[ 　]*の[ 　]*(?:入出力)?手順"},
                {"name": "keyword.control.suru", "match": word([suru.TEJUN, suru.TEJUN_IO, suru.KW_IJOU])},
                {"name": "storage.type.suru", "match": word(sorted(suru.KANJI_KEYWORDS - {suru.KW_IJOU}))},
                {"name": "constant.language.suru", "match": word(["真", "偽", suru.KW_EMPTY])},
                {"name": "variable.language.suru", "match": word(kanji_props + [suru.RESULT])},
            ]
        },
        "number": {
            "name": "constant.numeric.suru",
            "match": f"{not_before}[0-9０-９]+(?:[.．][0-9０-９]+)?",
        },
        "operator": {
            "name": "keyword.operator.arithmetic.suru",
            "match": "\\*\\*|[<>=!]=|[+\\-*/%^<>=]|[−×÷＋－＊／％＾＝≠≦≧≤≥＜＞]",
        },
        "punctuation": {
            "patterns": [
                {"name": "punctuation.terminator.statement.suru", "match": "。"},
                {"name": "punctuation.separator.suru", "match": "、"},
                {"name": "punctuation.section.parens.suru", "match": "[()（）]"},
                {"name": "invalid.illegal.reserved.suru", "match": "・"},
            ]
        },
    }
    # 長い語を先に当てるため、ひらがなの各グループは「全部をまとめた選択」の中で順位を決める
    hira_all = control + hira_props + declare + particles
    order = sorted(set(hira_all), key=lambda w: (-len(w), w))
    group = {}
    for w in control:
        group[w] = "keyword.control.suru"
    for w in hira_props:
        group[w] = "variable.language.suru"
    for w in declare:
        group[w] = "keyword.other.declaration.suru"
    for w in particles:
        group[w] = "keyword.other.particle.suru"
    # 関数名に含まれないひらがなは、キーワードか助詞
    patterns["hiragana"] = {
        "match": "(" + ")|(".join(order) + ")",
        "captures": {str(i + 1): {"name": group[w]} for i, w in enumerate(order)},
    }
    patterns["name"] = {"name": "variable.other.suru", "match": f"{name_start}{name_char}*"}

    def rules(call_rule):
        return [{"include": f"#{k}"} for k in
                ["comment", "test", "string", "quoted-name", "quasi-name", "import", "module", "lambda", "returns", "builtin",
                 "derive", call_rule,
                 "kanji-keyword", "number", "operator", "punctuation", "hiragana", "name"]]

    # 準クォート「以下は【道】です … 以上です」「x とは 以下の【SQL】です … 以上です」(#192)。
    # 中身はほかの言語なので色を付けず、頭と同じ字下げの「以上です」で閉じる
    patterns["quasi"] = {
        "begin": "^([ 　]*)(.*?)(以下[ 　]*[のは][ 　]*)(?=【[^【】 　]+】[ 　]*(?:です)?[ 　]*。?[ 　]*(?:[#＃].*)?$)",
        "beginCaptures": {
            "2": {"patterns": [{"include": "#spaced-call"}, {"include": "#hiragana"}, {"include": "#name"}]},
            "3": {"name": "keyword.control.suru"},
        },
        "end": "^\\1(以上)(?:[ 　]*です)?",
        "endCaptures": {"1": {"name": "keyword.control.suru"}},
        "patterns": [
            {"begin": "\\G", "end": "$", "patterns": [{"include": "#quasi-name"}, {"include": "#kanji-keyword"},
                                                       {"include": "#comment"}]},
            {"name": "meta.embedded.block.suru", "match": ".+"},
        ],
    }
    # 「。」か「、」を含む行(文字列・『』・コメントの中は数えない)は句読点の書き方、それ以外は空白の書き方
    patterns["punct-line"] = {
        "begin": "^(?=(?:" + STRING + "|『[^』]*』|[^「『#＃※。、])*[。、])",
        "end": "$",
        "patterns": rules("call"),
    }
    return {
        "$schema": "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json",
        "name": "する",
        "scopeName": "source.suru",
        "comment": "editors/vscode/make_grammar.py が作るファイルです。直接編集しないでください",
        "fileTypes": ["suru"],
        "patterns": [{"include": "#quasi"}, {"include": "#punct-line"}] + rules("spaced-call"),
        "repository": patterns,
    }


def render() -> str:
    return json.dumps(build(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(render())
    print(f"作りました: {os.path.relpath(OUT, ROOT)}")

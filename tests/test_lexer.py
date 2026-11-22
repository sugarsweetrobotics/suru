"""lib/字句.suru(する で書いた字句解析)が suru.py の字句解析(split_lines)と同じ結果になるか"""

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_compile  # noqa: E402

DUMP = ROOT / "tests" / "字句出力.suru"
FILES = sorted((ROOT / "examples").glob("*.suru")) + sorted((ROOT / "lib").glob("*.suru"))

KINDS = {"NUM": "数", "STR": "文字列", "OP": "演算子", "LP": "開き", "RP": "閉じ", "WORD": "名前", "KW": "予約語",
         "PART": "助詞", "CALL": "呼出", "PERIOD": "句点", "SEP": "区切り"}

# 両方の書き方の、字句解析で間違えやすいところ(構文としては正しくなくてよい)
TRICKY = """\
x を 『割る数に』する とは 「a b」 + １２ # コメント
a と b を加算する とは a + b です
n が 偶数でない を返すこと -5 1.5 .5 1e3 真 空 = ＝＝ ** 三倍します 加算しまして 表示しましてから
リスト から （x を 受け取って x > 0 を 返すこと） で 選別する
aとbを加算するとは、a+b。引数を三倍するとは、引数と引数を加算して、引数を加算する。
xs を 0 から 加算すること で 畳み込みする。xs を畳み込みする。x1+y2×3÷4≦5≠6
p とは 3 と 4 の 点 です。もしn>0ならば「正」です、そうでなければ「負」です。
『おやつの数』とは、3。『おやつの数』を三倍する。『割る数に』する。
長文とは、1と2と
    3と4。  # 改行をまたぐ
挿入式 とは 手順（
  「a」を表示する。
  「b」を表示します。）
「数学」を読み込んで使う。「数学」 を 読み込む
もし 形 が、半径 の 円 ならば 1、そうでなければ 2。
　全角の字下げ とは 1
\t\tタブ とは 2
n が 偶数である とは n ％ 2 が 0。偶数であること。３が偶数でない。
受け取って返すこと長さ残り使う それぞれ。
"""

ERRORS = [
    "「閉じない",
    "x とは 1・2",
    "『閉じない とは 1",
    "『』 とは 1",
    "へんかんする とは 1",
    "1 です を 表示する",
    "5を、へんかんする。",
    "x とは、1",
    "あいうえを 表示する。",
]


def py_value(t: suru.Token) -> str:
    v = t.value
    if t.kind == "NUM":
        if v is True:
            return "真"
        if v is False:
            return "偽"
        if v == ():
            return "空"
    if t.kind == "LP":
        return "("
    if t.kind == "RP":
        return ")"
    return str(v)


def py_dump(source: str) -> list[str]:
    out = []
    for line in suru.split_lines(source):
        toks = " ".join(
            f"{KINDS[t.kind]}:{py_value(t)}/{t.form}@{int(t.line)}:{t.line.col}"
            + ("q" if t.quoted else "") + ("n" if t.negated else "")
            for t in line.tokens
        )
        out.append(f"L{int(line.number)} {line.indent}{'.' if line.closed else ''}: {toks}")
    return out


def normalize_numbers(text: str) -> str:
    """する の字句は数を書いたままの文字列で持つので、Python の値と同じ書き方にそろえる"""
    def num(m: re.Match) -> str:
        t = m.group(1)
        if t in ("真", "偽", "空"):
            return f"数:{t}/"
        try:
            return f"数:{int(t)}/"
        except ValueError:
            return f"数:{float(t)}/"
    return re.sub(r"数:([^/]+)/", num, text)


@pytest.fixture(scope="module")
def dumper(tmp_path_factory):
    """字句出力.suru を動かすコマンド。clang があればバイナリにして速く動かす"""
    if suru_compile.find_cc() is None:
        return [sys.executable, str(ROOT / "suru.py"), str(DUMP)]
    exe = tmp_path_factory.mktemp("lexer") / "dump"
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(DUMP), "-o", str(exe)], check=True)
    return [str(exe)]


def su_dump(dumper, path: pathlib.Path) -> list[str]:
    r = subprocess.run([*dumper, str(path)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    return normalize_numbers(r.stdout).splitlines()


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_例とライブラリの字句が同じ(dumper, path):
    assert su_dump(dumper, path) == py_dump(path.read_text(encoding="utf-8"))


def test_間違えやすい書き方の字句が同じ(dumper, tmp_path):
    path = tmp_path / "tricky.suru"
    path.write_text(TRICKY, encoding="utf-8")
    assert su_dump(dumper, path) == py_dump(TRICKY)


@pytest.mark.parametrize("source", ERRORS)
def test_エラーになる行は誤りの字句になる(dumper, tmp_path, source):
    with pytest.raises(suru.SuruError):
        suru.split_lines(source)
    path = tmp_path / "error.suru"
    path.write_text(source + "\n", encoding="utf-8")
    assert any("誤り:" in line for line in su_dump(dumper, path))

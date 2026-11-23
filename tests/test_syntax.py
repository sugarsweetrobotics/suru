"""lib/構文.suru(する で書いた構文解析)が suru.py の構文解析(ExprParser)と同じ構文木を作るか"""

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import suru  # noqa: E402
import suru_compile  # noqa: E402

DUMP = ROOT / "tests" / "構文出力.suru"

# 形の名前とフィールド
CTORS = {"点": ("点", ["横", "縦"]), "円": ("図形", ["半径"]), "長方形": ("図形", ["幅", "高"]),
         "赤": ("色", []), "青": ("色", [])}
TYPES = {"点": ["点"], "図形": ["円", "長方形"], "色": ["赤", "青"]}

# 1行に1つの式(構文として正しいもの)
EXPRS = """\
1 + 2 * 3 - 4 / 5 % 6
2 ^ 3 ^ 2
-x + -3
（1 + 2） * 3
x == 1
x != y + 1
a < b
a <= b かつ b >= c または d > e
x が 空
x を 三倍する
x を 三倍して 1 に 加算する
x を 三倍して 1 に 加算して 表示する
a を b で 除算する
xs から 0 より 1 へ 2 に 3 で 何かする
答えする
n が 偶数である
n が 偶数でない
n が 偶数である かつ n が 正である
n が 偶数である または n が 正である かつ m が 負である
x が 1 かつ y が 2
1 と 2 と 3
1 と 2 と 3 を 加算する
xs の 先頭
xs の 残り の 先頭
xs の 長さ + 1
xs の 最後
xs の それぞれ を 三倍する
p の 横
p の 横 の 縦
三倍すること
1 を 加算すること
偶数であること
xs を 三倍すること で 写像する
xs から 偶数であること で 選別する
xs を 0 から 加算すること で 畳み込みする
xs が 偶数であること で 全部真である
x を 受け取って x * 2 を 返すこと
a を b で 受け取って a + b を 返すこと
a と b を 受け取って a + b を 返すこと
xs を （x を 受け取って x * 2 を 返すこと） で 写像する
もし x > 0 ならば 1 そうでなければ 2
もし x > 0 ならば 1 そうでなければ もし x < 0 ならば -1 そうでなければ 0
もし n が 偶数である ならば 「偶数」 そうでなければ 「奇数」
3 と 4 の 点
（1 と 2 の 点） と （3 と 4 の 点）
5 の 円
赤
横 は 3 で 縦 は 4 の 点
横 は 10 の p
横 は 10 で 縦 は 20 の p
横 は p の 縦 の q
横 は 1 の （3 と 4 の 点）
もし 形 が 半径 の 円 ならば 半径 そうでなければ 0
もし 形 が 半径 の 円 ならば 1、幅 と 高 の 長方形 ならば 2。
もし 形 が 半径 の 円 かつ 半径 > 10 ならば 1、そうでなければ 2。
もし c が 赤 ならば 1、青 ならば 2。
もし xs が 空 ならば 0、先頭 は x で 残り は 他 ならば x。
もし n が 0 ならば 「零」、1 ならば 「一」、そうでなければ 「多」。
もし n が -1 ならば 1 そうでなければ 2
もし s が 「a」 ならば 1 そうでなければ 2
もし p が 横 は a の 点 ならば a そうでなければ 0
もし a と b が 0 と y ならば y そうでなければ 0
もし 3 と 4 の 点 が x と y の 点 ならば x そうでなければ 0
もし p が （x と y の 点） ならば x そうでなければ 0
（3 と 4） の 点 が p
入力した 結果 を 表示する
入力してから 表示する
入力してから 数値にして 表示する
「やあ」 を 表示してから 入力してから 表示する
x を 加算して 1 を 減算する
xs を 1 と 2 で 何かする
「a b」 + 「c」
真 かつ 偽
空
1.5 + .5
『おやつ』 + 1
x を 『割る数に』する
n が 偶数でない かつ n > 0
xs の それぞれ が 偶数である
（xs の それぞれ） と ys を 加算する
""".splitlines()

# 句読点の書き方の式
PUNCT = """\
1と2と3を加算する。
xを三倍して、1に加算する。
もしx>0ならば1、そうでなければ2。
もしnが偶数であるならば「偶数」、そうでなければ「奇数」。
もし形が、半径の円ならば半径、幅と高の長方形ならば幅。
xsを、（xを受け取ってx*2を返すこと）で写像する。
横は3で縦は4の点。
""".splitlines()

# 読めない式
BAD = """\
1 +
x を
x を 三倍して
（1 + 2
1 + 2）
x を 受け取って x
もし x ならば 1
もし x ならば 1 そうでなければ
入力した 表示する
x を y を 加算する
1 2
xs の 3
横 は 3 で 縦 は 4
3 と 4 の 点 と 5
ならば
""".splitlines()

# 読めることだけ確かめる(中は 未解析式)
UNPARSED = ["（合計とは、a+b。合計/2）。", "手順（「a」を表示する。「b」を表示する。）。"]


def num(v) -> str:
    if v is True:
        return "真"
    if v is False:
        return "偽"
    if v == ():
        return "空"
    return str(v)


def pat_name(p) -> str:
    return f"束:{p}" if isinstance(p, str) else "並[" + " ".join(f"束:{x}" for x in p) + "]"


def dump(n) -> str:
    S = suru
    at = lambda: f"@{int(n.line)}"  # noqa: E731
    lst = lambda xs: "[" + " ".join(dump(x) for x in xs) + "]"  # noqa: E731
    fields = lambda fs: "".join(f" {k}={dump(v)}" for k, v in fs)  # noqa: E731
    if n is None:
        return "-"
    if isinstance(n, S.Num):
        return f"数:{num(n.value)}{at()}"
    if isinstance(n, S.Str):
        return f'文:"{n.value}"{at()}'
    if isinstance(n, S.Var):
        return f"穴{at()}" if n.name == S.HOLE else f"名:{n.name}{at()}"
    if isinstance(n, S.ListLit):
        return "列" + lst(n.items)
    if isinstance(n, S.Prop):
        return f"性({dump(n.target)} {n.name}){at()}"
    if isinstance(n, S.Each):
        return f"各({dump(n.target)}){at()}"
    if isinstance(n, S.BinOp):
        return f"演({n.op} {dump(n.left)} {dump(n.right)}){at()}"
    if isinstance(n, S.Neg):
        return f"負({dump(n.operand)})"
    if isinstance(n, S.Not):
        return f"否({dump(n.operand)}){at()}"
    if isinstance(n, S.Call):
        return f"呼({n.name}{fields(sorted(n.args.items()))}){at()}"
    if isinstance(n, S.Ref):
        return f"参({n.name}{fields(sorted(n.args.items()))}){at()}"
    if isinstance(n, S.Lambda):
        return "関(" + "".join(f" {p}={pat_name(x)}" for p, x in n.params) + f" ; {dump(n.body)}){at()}"
    if isinstance(n, S.If):
        return f"若({dump(n.cond)} {dump(n.then)} {dump(n.other)})"
    if isinstance(n, S.Chain):
        return f"連({dump(n.call)} {dump(n.cont)}){at()}"
    if isinstance(n, S.Run):
        return f"行({dump(n.call)}){at()}"
    if isinstance(n, S.Construct):
        return f"作({n.ctor} {lst(n.items)}){at()}"
    if isinstance(n, S.NamedConstruct):
        return f"名作({n.ctor}{fields(n.fields)}){at()}"
    if isinstance(n, S.Update):
        return f"更({dump(n.target)}{fields(n.fields)}){at()}"
    if isinstance(n, S.Field):
        return f"欄({dump(n.target)} {n.name}){at()}"
    if isinstance(n, S.Match):
        cases = "".join(f" {{{dump(p)} ? {dump(g)} => {dump(b)}}}" for p, g, b in n.cases)
        return f"場({dump(n.subject)}{cases} 他={dump(n.default)}){at()}"
    if isinstance(n, S.PBind):
        return f"束:{n.name}"
    if isinstance(n, S.PSeq):
        return "並" + lst(n.items)
    if isinstance(n, S.PValue):
        return f"値({dump(n.expr)})"
    if isinstance(n, S.PCtor):
        return f"型({n.ctor} {lst(n.items)}){at()}"
    if isinstance(n, S.PNamed):
        return f"名型({n.ctor or '-'}{fields(n.fields)}){at()}"
    if isinstance(n, (S.Block, S.Do)):
        return "未解析"  # 括弧の中の文の並び(lib/構文.suru はまだ読まない)
    raise AssertionError(f"表示できない構文木: {n!r}")


def body(tokens: list) -> list:
    """括弧の外の最初の「とは」より後ろ(定義の本体)。なければ全部"""
    depth = 0
    for i, t in enumerate(tokens):
        if t.kind == "LP":
            depth += 1
        elif t.kind == "RP":
            depth -= 1
        elif depth == 0 and t.kind == "KW" and t.value == suru.KW_TOWA:
            return tokens[i + 1:]
    return tokens


def py_dump(source: str, ctx: "suru.ParseContext | None" = None) -> list[str]:
    out = []
    saved = suru._CTX
    suru._CTX = ctx or suru.ParseContext(ctors=CTORS, types=TYPES)
    try:
        for line in suru.split_lines(source):
            try:
                text = dump(suru.ExprParser(body(line.tokens)).parse_all())
            except suru.SuruError:
                text = "誤り"
            out.append(f"L{int(line.number)}: {text}")
    finally:
        suru._CTX = saved
    return out


def normalize(text: str) -> str:
    """する の構文木は数を書いたままの文字列で持つので、Python の値と同じ書き方にそろえる。誤りの説明は比べない"""
    def number(m: re.Match) -> str:
        t = m.group(1)
        if t in ("真", "偽", "空"):
            return f"数:{t}@"
        try:
            return f"数:{int(t)}@"
        except ValueError:
            return f"数:{float(t)}@"
    text = re.sub(r"数:([-+0-9.eE]+|真|偽|空)@", number, text)
    text = re.sub(r"未解析@\d+", "未解析", text)
    return re.sub(r"(?m)^(L\d+: )誤り: .*$", r"\1誤り", text)


@pytest.fixture(scope="module")
def dumper(tmp_path_factory):
    """構文出力.suru を動かすコマンド。clang があればバイナリにして速く動かす"""
    if suru_compile.find_cc() is None:
        return [sys.executable, str(ROOT / "suru.py"), str(DUMP)]
    exe = tmp_path_factory.mktemp("syntax") / "dump"
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(DUMP), "-o", str(exe)], check=True)
    return [str(exe)]


def su_dump(dumper, path: pathlib.Path, ctors: dict = CTORS) -> list[str]:
    args = [f"{c}={len(fs)}" for c, (_, fs) in ctors.items()]
    r = subprocess.run([*dumper, str(path), *args], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    return normalize(r.stdout).splitlines()


def check_same(dumper, tmp_path, lines: list[str]) -> list[str]:
    source = "\n".join(lines) + "\n"
    path = tmp_path / "exprs.suru"
    path.write_text(source, encoding="utf-8")
    py = py_dump(source)
    assert su_dump(dumper, path) == py
    return py


def test_式の構文木が同じ(dumper, tmp_path):
    py = check_same(dumper, tmp_path, EXPRS)
    assert len(py) == len(EXPRS)
    assert [x for x in py if x.endswith("誤り")] == []


def test_句読点の書き方の構文木が同じ(dumper, tmp_path):
    py = check_same(dumper, tmp_path, PUNCT)
    assert [x for x in py if x.endswith("誤り")] == []


def test_読めない式はどちらも誤りになる(dumper, tmp_path):
    py = check_same(dumper, tmp_path, BAD)
    assert all(x.endswith("誤り") for x in py), py


def test_文の並びは未解析式になる(dumper, tmp_path):
    path = tmp_path / "blocks.suru"
    path.write_text("\n".join(UNPARSED) + "\n", encoding="utf-8")
    assert su_dump(dumper, path) == ["L1: 未解析", "L2: 未解析"]


FILES = sorted((ROOT / "examples").glob("*.suru")) + sorted((ROOT / "lib").glob("*.suru"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_例とライブラリの行の構文木が同じ(dumper, path):
    """どの論理行も、定義の本体(なければ行の全体)を式として読む。文の書き方の行は両方とも誤りになる"""
    source = path.read_text(encoding="utf-8")
    ctx = suru.ParseContext(base_dir=str(path.parent))
    suru.parse_program(source, ctx)
    ctx = suru.ParseContext(ctors=ctx.ctors, types=ctx.types)
    assert su_dump(dumper, path, ctx.ctors) == py_dump(source, ctx)

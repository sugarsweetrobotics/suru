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
横 は 3 だけ で 縦 は 4 の 点
404 だけ
（3 だけ） + （4 と 5）
x だけ を 表示する
横 は 10 の p
横 は 10 で 縦 は 20 の p
横 は p の 縦 の q
横 は 1 の （3 と 4 の 点）
もし 形 が 半径 の 円 ならば 半径 そうでなければ 0
もし 形 が 半径 という 円 ならば 半径 そうでなければ 0
もし 形 が 横 は a という 点 ならば a そうでなければ 0
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
（a と b を 安全除算した 中身） + 1
（x と b を 安全除算した 中身） と c を 安全除算する
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
x を 『割った数に』する
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
1 と 2 だけ
1 +
x を
x を 三倍して
（1 + 2
1 + 2）
x を 受け取って x
もし x ならば 1
もし x ならば 1 そうでなければ
入力した 表示する
入力した 中
x を y を 加算する
1 2
xs の 3
横 は 3 で 縦 は 4
3 と 4 の 点 と 5
ならば
""".splitlines()

# 括弧の中の文の並び
BLOCKS = ["（合計とは、a+b。合計/2）。", "手順（「a」を表示する。「b」を表示する。）。", "（x とは、1。ただし、y とは、2。x+y）。"]


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
        return f"{'身' if n.unwrap else '行'}({dump(n.call)}){at()}"
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
    if isinstance(n, S.Define):
        params = "".join(f" {p}={param(x)}" for p, x in n.params)
        return f"定({n.name} {'関' if n.is_function else '値'}{params} ; {dump(n.body)}){at()}"
    if isinstance(n, S.Block):
        return "塊" + lst(n.statements)
    if isinstance(n, S.Do):
        return ("順続" if n.sequel else "順") + lst(n.statements) + at()
    if isinstance(n, S.TypeDef):
        def ctor(c: str, fs: list) -> str:
            if n.field_types is None or not fs:
                return f" {c}[{' '.join(fs)}]"
            return f" {c}[" + " ".join(f"{f}:{'・'.join(t.value for t in n.field_types[f])}" for f in fs) + "]"
        return f"型定({n.name}" + "".join(ctor(c, fs) for c, fs in n.ctors) + f"){at()}"
    if isinstance(n, S.TypeSig):
        params = "" if n.params is None else "".join(f" {p}={dump(t)}" for p, t in n.params)
        return f"宣({n.name} {'値' if n.params is None else '関'}{params} -> {dump(n.result)}){at()}"
    if isinstance(n, S.TypeName):
        return f"型:{n.name}" + (lst(n.args) if n.args else "")
    if isinstance(n, S.TypeFun):
        return "関型[" + "".join(f" {p}={dump(t)}" for p, t in n.params) + f" -> {dump(n.result)}]"
    if isinstance(n, S.TypeVarName):
        return f"変:{n.name}"
    if isinstance(n, S.TraitDecl):
        sigs = "[" + " ".join(f"頭({name}" + "".join(f" {p}={param(x)}" for p, x in ps) + ")" for name, ps in n.sigs) + "]"
        return f"性質({n.name} {sigs} {lst(n.defaults)}){at()}"
    if isinstance(n, S.TraitImpl):
        return f"実装({n.type_name} {n.trait} {lst(n.defs)}){at()}"
    if isinstance(n, S.Import):
        return f"読込({n.module.name} {'開' if n.open else '閉'}){at()}"
    if isinstance(n, S.ExternLib):
        return f"外庫({n.name}){at()}"
    if isinstance(n, S.Extern):
        return f"外({n.symbol} {n.pointer}){at()}"
    if isinstance(n, S.Export):
        return f"出({n.name} {n.symbol}){at()}"
    if isinstance(n, S.Visibility):
        return f"公開({'公' if n.public else '非'} [{' '.join(n.names)}]){at()}"
    raise AssertionError(f"表示できない構文木: {n!r}")


def param(x) -> str:
    """定義の引数: 名前(「a」)・名前の並び(「a と b」)・パターン"""
    if isinstance(x, (str, list)):
        return pat_name(x)
    return dump(x)


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
    text = re.sub(r"(?m)^(L\d+: )誤り: .*$", r"\1誤り", text)
    return re.sub(r"(?m)^誤り: .*$", "誤り", text)


@pytest.fixture(scope="module")
def dumper(tmp_path_factory):
    """構文出力.suru を動かすコマンド。clang があればバイナリにして速く動かす"""
    if suru_compile.find_cc() is None:
        return [sys.executable, str(ROOT / "suru.py"), str(DUMP)]
    exe = tmp_path_factory.mktemp("syntax") / "dump"
    subprocess.run([sys.executable, str(ROOT / "suru_compile.py"), str(DUMP), "-o", str(exe)], check=True)
    return [str(exe)]


def su_dump(dumper, path: pathlib.Path, ctors: dict = CTORS, types: dict = TYPES, program: bool = False) -> list[str]:
    # lib/構文.suru は型の名前をファイルごとに分けない(前置きなしの名前で比べる)
    args = ([f"{suru.short_type_name(c)}={len(fs)}" for c, (_, fs) in ctors.items()]
            + [f"型:{suru.short_type_name(t)}" for t in types])
    args += ["--文"] if program else []
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


def test_括弧の中の文の並びの構文木が同じ(dumper, tmp_path):
    py = check_same(dumper, tmp_path, BLOCKS)
    assert [x for x in py if x.endswith("誤り")] == []


FILES = sorted((ROOT / "examples").glob("*.suru")) + sorted((ROOT / "lib").glob("*.suru"))


def py_program(source: str, base_dir: str) -> tuple[list[str], "suru.ParseContext"]:
    ctx = suru.ParseContext(base_dir=base_dir)
    try:
        # 自動で読み込む基本は 構文.suru では扱わない(書いた文だけを比べる)
        out = [dump(s) for s in suru.parse_program(source, ctx) if not (isinstance(s, suru.Import) and s.auto)]
    except suru.SuruError:
        out = ["誤り"]
    return shorten(out, ctx), ctx


def shorten(lines: list[str], ctx: "suru.ParseContext") -> list[str]:
    """読み込んだファイルの型と形の本当の名前(「数学内の長方形」)を、前置きなしの名前にする(lib/構文.suru と比べるため)"""
    names = sorted((n for n in list(ctx.ctors) + list(ctx.types) if suru.MODULE_SEP in n), key=len, reverse=True)
    out = []
    for line in lines:
        for n in names:
            line = re.sub(rf"(?<![^\s(\[:]){re.escape(n)}(?=[\s)\]@]|$)", suru.short_type_name(n), line)
        out.append(line)
    return out


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_例とライブラリのプログラムの構文木が同じ(dumper, path):
    """ファイル全体を suru.py の parse_program と同じ一番外の文のリストにする"""
    source = path.read_text(encoding="utf-8")
    py, ctx = py_program(source, str(path.parent))
    assert py != ["誤り"]
    assert su_dump(dumper, path, ctx.ctors, ctx.types, program=True) == py


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_例とライブラリの行の構文木が同じ(dumper, path):
    """どの論理行も、定義の本体(なければ行の全体)を式として読む。文の書き方の行は両方とも誤りになる"""
    source = path.read_text(encoding="utf-8")
    ctx = suru.ParseContext(base_dir=str(path.parent))
    suru.parse_program(source, ctx)
    sh = suru.short_type_name
    # 1行ずつ読むときは型の名前をファイルごとに分けないので、前置きなしの名前で比べる
    ctx = suru.ParseContext(ctors={sh(c): (sh(t), fs) for c, (t, fs) in ctx.ctors.items()},
                            types={sh(t): [sh(c) for c in cs] for t, cs in ctx.types.items()})
    assert su_dump(dumper, path, ctx.ctors, ctx.types) == py_dump(source, ctx)


# 手で書いたプログラム(文の書き方の組み合わせ)
PROGRAMS = [
    # 他の言語に出す関数のまとまり(#208)
    "数 を 二倍する は 数\nx を 二倍する とは x * 2\n以下 は 外部 に 出す 関数 です\n  二倍する は 「nibai」\n以上\n",
    "数を二倍するは、数を返す。\nxを二倍するとは、x*2です。\n以下は外部に出す関数です。\n二倍するは、「nibai」。\n以上です。\n",
    """\
会員 とは 番号 は 数 で 名前 は 文字列 で 年齢 は 数 の 組
図形 とは 半径 は 数 の 円 か 幅 は 数 で 高 は 数 の 長方形 か 点図形
木 とは 値 は 甲 で 左 は 木 で 右 は 木 の 節 か 葉
箱 とは 中身 は 甲 の リスト で 名札 は 文字列 の 組
線 とは 始め は 位置 で 終わり は 位置 の 組
位置 とは 横 は 数 で 縦 は 数 の 組
（1 と 「花子」 と 20 の 会員） の 名前 を 表示する
""",
    # C構造体(#241)
    "時間 とは 秒 は 符号付き64 で ナノ秒 は 符号なし32 の C構造体\n品質 とは 期限 は 時間 で 率 は 単精度 の C構造体\n（1 と 2 の 時間） の 秒\n",
    "時間とは、秒は符号付き64でナノ秒は符号なし32のC構造体。\n（1と2の時間）の秒。\n",
    "時間 とは 秒 （符号付き64） と ナノ秒 （符号なし32） の C構造体\n品質 とは 期限 （時間） と 率 （単精度） の C構造体\n（1 と 2 の 時間） の 秒\n",
    # フィールドの型の「数 を 返す 動作」(#206)
    "型札 とは 名 は 文字列 で 書込 は （数 を 受け取って 数 を 返す 入出力動作 を 返すこと） で 読込 は 数 を 返す 動作 の 組\n",
    "型札 とは 名 （文字列） と 読込 （数 を 返す 動作） の 組\n",
    # かっこで型を後ろに書く(#242)
    """\
品 とは 番号 （数） と 名前 （文字列） と 値段 （数） の 組
図形 とは 半径 （数） の 円 か 幅 （数） と 高 （数） の 長方形 か 点図形
鎖 とは 値 （甲） と 次 （甲 の 鎖） の 節 か 末
道 とは 名前 （文字列） と 処理 （数 を 受け取って 数 を 返すこと） の 組
対 とは 左 (数) と 右 (数 の リスト) の組
線 とは 始め （位置） と 終わり （位置 の リスト） の 組
位置 とは 横 と 縦 の組
（1 と 「茶」 と 120 の 品） の 名前 を 表示する
""",
    "品とは、番号（数）と名前（文字列）の組。\n（1 と 「茶」 の 品） の 名前 を 表示する\n",
    """\
図形 とは 半径 の 円 か 幅 と 高 の 長方形
信号 とは 赤 か 黄 か 青
（半径 の 円） を 面積にする とは 半径 * 半径 * 3
（幅 と 高 の 長方形） を 面積にする とは 幅 * 高
（半径 という 円） を 外周にする とは 半径 * 6
（幅 と 高 という 長方形） を 外周にする とは （幅 + 高） * 2
赤 を 次にする とは 青
c を 次にする とは 赤
0 を x で 何かする とは x
n を x で 何かする とは n + x
先頭 は x で 残り は 他 を 足する とは x + （他 を 足する）
空 を 足する とは 0
""",
    """\
比較可能 という 性質 とは
  a と b を 比較する
  a と b を 大きい方にする とは
    もし （a と b を 比較する） > 0 ならば a そうでなければ b
ただし x を 小さい方にする とは x
点 とは 横 と 縦 の 組
点 は 比較可能
  a と b を 比較する とは a の 横 - b の 横
ただし a と b を 差にする とは a の 横 - b の 縦
""",
    """\
数 を 数 で 加算する は 数
数 を 数 と 数 と 数 で 三回転和にする は 数
文字列 と 数 を 組表示する は 文字列
（文字列 と 数 を 受け取って 数 を 返すこと） を 適用二する は 数
（数 を 受け取って 数 を 返すこと） を 数 の リスト で 写像化する は 数 の リスト
甲 の リスト を （甲 を 数 で 受け取って 真偽 を 返すこと） で 選ぶする は 甲 の リスト
税率 は 数
表 は 数 の リスト の リスト
税率 とは 0.1
数 を 三倍する は 数 を 返す
数 の リスト を 合計する は 数 を 返します
数を四倍するは、数を返す。
挨拶する は 数 を 返す 動作
（数 を 返す 動作） を 二回する は 文字列 を 返す 動作 を 返す
数を数値表示するは、数を返す動作。
挨拶二する とは 入出力手順
  「a」 を 表示する
  「b」 を 表示する
挨拶三する とは 入出力手順（「a」を表示する。「b」を表示する。）。
数 を 表示数する は 数 を 返す 入出力動作
数 を 表示二する は 数 の 入出力動作 の リスト
a と b を 内側にする とは a
a と b を 外側にする とは b
内側にする は 非公開とする
""",
    """\
aとbを平均するとは、合計/2。ただし、合計とは、a+b。
「やあ」を表示する。それから、「またね」を表示する。それから、「おわり」を表示する。
挨拶するとは、手順（「a」を表示する。xとは、入力した結果。xを表示する。）。
""",
    """\
挨拶する とは 手順
  名前 とは 入力した 結果
  名前 を 表示する
  それから 「おわり」 を 表示する
n を 判定する とは
  もし n > 0
    ならば 「正」
    そうでなければ 「負」
x を 二倍する とは
  y とは x + x
  y
番地 を 長さ計測する は 数
s を 長さ計測する とは 外部の（s）
""",
    """\
「数学」 を 読み込む
数学内の二乗する
数学内の 円周率
""",
    """\
外部の「m」 を 主スレッドで 読み込む
小数 を 余弦にする は 小数
x を 余弦にする とは 外部の「cos」
単精度 を 半分にする は 単精度
x を 半分にする とは 外部の「halff」
""",
    """\
名前 を 挨拶する とは 以下の手順です
  「こんにちは、」 + 名前 + 「さん」 を 表示する
  以上
二回挨拶する とは 以下の入出力手順です
  「太郎」 を 挨拶する
  「花子」 を 挨拶する
以上
同じ字下げする とは 以下 の 手順
「a」 を 表示する
以上です
x と y を 分類する とは
  もし x が
    1 ならば もし y が
      1 ならば 「a」
      2 ならば 「b」
    2 ならば 「c」
    そうでなければ 「d」
x を 選ぶする とは
  もし x が
    1 ならば 以下の手順です
      「一」 を 表示する
      x を 結果にする
      以上
    そうでなければ 以下の手順です
      「他」 を 表示する
      以上
""",
    """\
名前を挨拶するとは、以下の手順です。
  「こんにちは、」+名前+「さん」を表示する。
  以上。
二回挨拶するとは、以下の手順です。「太郎」を挨拶する。「花子」を挨拶する。以上です。
xとyを分類するとは、もしxが1ならば、もしyが1ならば「a」、2ならば「b」以上、2ならば「c」、そうでなければ「d」。
内外するとは、以下の手順です。内とは、以下の手順です。「a」を表示する。以上。内を実行する。以上。
""",    """\
外部の「m」 を 読み込む
x を y で 累乗する とは 外部の「pow」 で 小数 を 小数 で 受け取って 小数 を 返します
p を 字数計測する とは 外部の「strlen」 で 文字列 を 受け取って 整数 を 返す 入出力動作です
r を 読取する とは 外部の「SDL_RenderReadPixels」（r と 0） で 番地 を 受け取って 番地 を 返す 入出力動作です
以下は外部の関数です
  小数 を 余弦にする は 「cos」 で 小数 を 返します

  小数 を 小数 で 正接2にする は 「atan2」 で 小数 を 返す
  x を 床にする とは 「floor」（x） で 小数 を 受け取って 小数 を 返します
以上です
以下 は 外部 の 入出力動作
低終了する は 「SDL_Quit」 で 無 を 返します
文字列 を 番地 で 何か書込する は 「something」 で 番地 を 返します
f を 呼出する とは 外部の「g」（f と 0） で 番地 を 受け取って 数 を 返します
以上
以下は外部の入出力動作です。文字列を一行出力するは、「puts」で整数を返します。以上です。
以下の外部の関数です
  小数 を 正弦にする は 「sin」 で 小数 を 返します
以上です
""",
    """\
q を g で 一行呼出する とは 外部の（g） で 番地 を 番地 で 受け取って 無 を 返す 入出力動作です
s を f で 長さ計測する とは 外部の（f） で 文字列 を 番地 で 受け取って 数 を 返します
以下は外部の入出力動作です
  p を f で 呼出する とは （f） で 番地 を 番地 で 受け取って 無 を 返します
  低終了する は 「SDL_Quit」 で 無 を 返します
  f を x で 呼戻する とは 外部の（f） で 番地 を 数 で 受け取って 番地 を 返します
以上です
""",
    """\
x を 分けるする とは 以下の手順です
  もし x > 10 ならば 以下の手順です
    「大」 を 表示する
    以上です
  そうでなければ もし x > 5 ならば 以下の入出力手順です
    「中」 を 表示する
    以上です
  そうでなければ 以下の手順です
    「小」 を 表示する
    以上です
  「終わり」 を 表示する
  以上です
x を 見せるする とは
  もし x > 0 ならば 以下の手順です
    x を 表示する
    以上
  そうでなければ 「負」 を 表示する
""",    """\
# 試験のまとまりと例(#193)
数 を 二倍する は 数
x を 二倍する とは x * 2
例えば （2 を 二倍する） は 4 です
例えば （-3 を 二倍する） は -6
例えば 3 と 4 の 点 は （3 と 4 の 点）
例えば （1 と 2） の 長さ は （もし 真 ならば 2 そうでなければ 3）

以下は「二倍」の試験です
  （2 を 二倍する） を 4 に 一致確認する
  x とは 1
  （x を 二倍する） を 2 に 一致確認する
  以上です

以下 は 「空白で 区切る」 の 試験 です
  1 < 2 を 確認する
  以上です
以下は「「入れ子」の名前」の試験です
  もし 1 > 0 ならば 以下の手順です
    1 < 2 を 確認する
    以上
  そうでなければ 「負」 を 表示する
  以上です
""",
    """\
「試験」 を 読み込んで 使う
以下は「開いて読み込んだ」の試験です
  1 < 2 を 確認する
  以上です
""",
    """\
「試験」 を 読み込む
以下は「閉じて読み込んだ」の試験です
  1 < 2 を 試験内の確認する
  以上です
""",
]

BAD_PROGRAMS = [
    "数 を 二倍する は 数\nx を 二倍する とは x * 2\n以下は外部に出す関数です\n  二倍する は 「nibai」\n",
    "以下は外部に出す関数です\n以上です\n",
    "数 を 二倍する は 数\nx を 二倍する とは x * 2\n以下は外部に出す関数です\n  二倍する 「nibai」\n以上です\n",
    "x とは 1\n以下は外部に出す関数です\n  x は 「a」\n以上です\n",
    "f とは 以下の手順です\n  以下は外部に出す関数です\n    二倍する は 「a」\n  以上です\n  以上です\n",
    "  x とは 1\n",
    "x とは\n",
    "とは 1\n",
    "ただし x とは 1\n",
    "それから x\n",
    "x とは 1\n    y\n  z\n",
    "点 とは 横 と と 縦 の 組\n",
    "数 を 何かする は\n",
    "x を 三倍しない とは x\n",
    "点 とは 横 は 数 で 縦 の 組\n",
    "点 とは 横 は 数 の 円 か 幅 と 高 の 長方形\n",
    "点 とは 横 は 数 の 甲点 か 横 は 文字列 の 乙点\n",
    "点 とは 横 は 数 で 横 は 数 の 組\n",
    "時間 とは 秒 と 分 の C構造体\n",
    "時間 とは 秒 （符号付き64） の 甲 か 分 （符号付き64） の C構造体\n",
    "時間 とは 秒 は 符号付き64 の 甲 か 分 は 符号付き64 の C構造体\n",
    "点 とは 横 は 数 で の 組\n",
    "品 とは 番号 （数） と 名前 は 文字列 の 組\n",
    "品 とは 番号 は 数 で 名前 （文字列） の 組\n",
    "品 とは 番号 （数） で 名前 （文字列） の 組\n",
    "品 とは 番号 （数） の 甲品 か 名前 は 文字列 の 乙品\n",
    "品 とは 番号 （数） と 名前 の 組\n",
    "品 とは 番号 と 名前 （数） の 組\n",
    "品 とは 番号 （数） の 甲品 か 名前 の 乙品\n",
    "品 とは 番号 （数） 名前 （数） の 組\n",
    "品 とは 番号 （） の 組\n",
    "品 とは （数） の 組\n",
    "品 とは 番号 （数） と 番号 （数） の 組\n",
    "品 とは 番号 （数） の 甲品 か 番号 （文字列） の 乙品\n",
    "品 とは 番号 （数） と の 組\n",
    "a b を 何かする とは a\n",
    "f とは 「a」 を 読み込む\n",
    "x とは 1 +\n",
    "（1 と 2\n",
    "税率 は 数 を 返す\n",
    "外部の「m」 を 主スレッドに 読み込む\n",
    "外部の「m」 を 主スレッドで 使う 読み込む\n",
    "f とは 以下の手順です\n  1 を 表示する\n",
    "f とは 以下の手順です\n以上\n",
    "以上\n",
    "fとは、以下の手順です。「a」を表示する。\n",
    "f とは 以下の手順です\n  1 を 表示する\n  以上\n  2 を 表示する\n",    "以下の外部の入出力動作です\n  数 を 確保する は 「f」 で 番地 を 返します\n",
    "以下の外部の入出力動作です\n以上です\n",
    "以下は外部の入出力動作です\n以上です\n",
    "以下は外部の入出力動作です\n  数 を 確保する は 「f」 で 番地 を 返す 入出力動作\n以上です\n",
    "  以下の外部の関数です\n",
    "以下の外部の関数です\n  1 を 表示する\n以上\n",
    "以下の外部の関数です\n  数 を 確保する は 「f」（を と 0） で 番地 を 返します\n以上\n",
    "以下の外部の関数です\n  数 を 確保する は 「f」 で 番地 を 返します\n1 を 表示する\n以上\n",
    "x とは 外部の「f」 で 数 を 返します\n",
    "n を 確保する とは 外部の「f」 で\n",
    "以下は外部の関数です\n  文字列 を 番地 で 計測する は （f） で 数 を 返します\n以上です\n",
    "s を f で 計測する とは 外部の（f）（s） で 文字列 を 番地 で 受け取って 数 を 返します\n",
    "f とは\n  もし 1 > 0 ならば 以下の手順です\n    以上\n  そうでなければ 2\n",
    "f とは\n  もし 1 > 0 ならば 以下の手順です\n    1 を 表示する\n    以上\n  2 を 表示する\n",
    # 試験のまとまりと例(#193)
    "以下は「a」の試験です\n  1 < 2 を 確認する\n",
    "以下は「a」の試験です 1\n  1 < 2 を 確認する\n  以上です\n",
    "f とは 以下の手順です\n  以下は「a」の試験です\n    1 < 2 を 確認する\n    以上です\n  以上です\n",
    "以下は「」の試験です\n  1 < 2 を 確認する\n  以上です\n",
    "以下は「 」の試験です\n  1 < 2 を 確認する\n  以上です\n",
    "以下は「a」の試験です\n  以上です\n",
    "以下は「a」の試験です\n  1 < 2 を 確認する\n  以上です\n以下は「a」の試験です\n  2 < 3 を 確認する\n  以上です\n",
    "例えば 3\n",
    "例えば は 3\n",
    "例えば 3 は\n",
    "f とは 以下の手順です\n  例えば 1 は 1\n  以上です\n",
    "例えば 1 + は 1\n",
]


@pytest.mark.parametrize("source", PROGRAMS, ids=range(len(PROGRAMS)))
def test_手で書いたプログラムの構文木が同じ(dumper, tmp_path, source):
    path = tmp_path / "prog.suru"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "数学.suru").write_text((ROOT / "examples" / "数学.suru").read_text(encoding="utf-8"), encoding="utf-8")
    py, ctx = py_program(source, str(tmp_path))
    assert py != ["誤り"]
    assert su_dump(dumper, path, ctx.ctors, ctx.types, program=True) == py


@pytest.mark.parametrize("source", BAD_PROGRAMS)
def test_読めないプログラムはどちらも誤りになる(dumper, tmp_path, source):
    path = tmp_path / "bad.suru"
    path.write_text(source, encoding="utf-8")
    py, _ = py_program(source, str(tmp_path))
    assert py == ["誤り"]
    assert su_dump(dumper, path, {}, {}, program=True) == ["誤り"]


def test_読み込みの後でも自分の型と形を使える(dumper, tmp_path):
    """このファイルの型と形は lib/構文.suru が自分で集める(読み込みの文の後の文でも見える)"""
    source = ("「数学」 を 読み込む\n点 とは 横 と 縦 の 組\n点 を 横取得する は 数\n"
              "p を 横取得する とは p の 横\n（3 と 4 の 点） を 横取得して 表示する\n")
    path = tmp_path / "prog.suru"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "数学.suru").write_text((ROOT / "examples" / "数学.suru").read_text(encoding="utf-8"), encoding="utf-8")
    py, _ = py_program(source, str(tmp_path))
    assert py != ["誤り"]
    assert su_dump(dumper, path, {}, {}, program=True) == py

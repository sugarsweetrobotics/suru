"""VS Code 拡張の kumu の部分(editors/vscode/kumu.js)のテスト。node がなければ飛ばす"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
KUMU_JS = ROOT / "editors" / "vscode" / "kumu.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node がない")


def node(expr: str):
    code = f"const k = require({json.dumps(str(KUMU_JS))}); process.stdout.write(JSON.stringify({expr}));"
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_試験の定義を見つける():
    text = "「試験」 を 読み込んで 使う\n二倍試験する とは 手順\n  x\n三倍試験するとは、手順（\n補助 とは 1\n# 四倍試験する とは\n二倍試験する とは 1\n  五倍試験する とは 1\n"
    assert node(f"k.testDefinitions({json.dumps(text)})") == [
        {"name": "二倍試験する", "line": 1},
        {"name": "三倍試験する", "line": 3},
    ]


def test_プロジェクトのフォルダと試験のファイル(tmp_path):
    (tmp_path / "試験" / "下").mkdir(parents=True)
    (tmp_path / "組.suru").write_text("名前 とは 「a」\n", encoding="utf-8")
    t = tmp_path / "試験" / "下" / "b.suru"
    main = tmp_path / "本体.suru"
    assert node(f"k.findProjectRoot({json.dumps(str(t))})") == str(tmp_path)
    assert node(f"k.isTestFile({json.dumps(str(tmp_path))}, {json.dumps(str(t))})") is True
    assert node(f"k.isTestFile({json.dumps(str(tmp_path))}, {json.dumps(str(main))})") is False
    outside = tmp_path.parent / "外.suru"
    assert node(f"k.findProjectRoot({json.dumps(str(outside))}) === undefined") is True


def test_設定したkumuを使う():
    assert node('k.findKumu("/opt/kumu")') == "/opt/kumu"

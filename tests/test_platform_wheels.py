"""packaging/platform_wheels.py: 純 Python の wheel から OS ごとの wheel を作る"""

import base64
import hashlib
import io
import os
import pathlib
import sys
import tarfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import platform_wheels  # noqa: E402


def _pure_wheel(path: pathlib.Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("suru.py", "__version__ = '9.9.9'\n")
        z.writestr("suru_lang-9.9.9.dist-info/METADATA", "Metadata-Version: 2.4\nName: suru-lang\nVersion: 9.9.9\n")
        z.writestr("suru_lang-9.9.9.dist-info/WHEEL",
                   "Wheel-Version: 1.0\nGenerator: hatchling\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr("suru_lang-9.9.9.dist-info/RECORD", "suru.py,,\n")


def _tar(path: pathlib.Path, names: list[str]) -> None:
    with tarfile.open(path, "w:gz") as t:
        for n in names:
            data = f"binary {n}".encode()
            info = tarfile.TarInfo(f"suru-9.9.9-linux-amd64/{n}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def _zip(path: pathlib.Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for n in names:
            z.writestr(f"suru-9.9.9-windows-amd64/{n}", f"binary {n}")


def test_linux_and_windows_wheels(tmp_path):
    pure = tmp_path / "suru_lang-9.9.9-py3-none-any.whl"
    _pure_wheel(pure)
    bins = tmp_path / "bin"
    bins.mkdir()
    _tar(bins / "suru-9.9.9-linux-amd64.tar.gz", ["suruc", "kumu", "suru-ls", "README.md"])
    _zip(bins / "suru-9.9.9-windows-amd64.zip", ["suruc.exe", "kumu.exe", "suru-ls.exe", "LICENSE"])
    out = tmp_path / "out"
    assert platform_wheels.main(["x", str(pure), str(bins), str(out)]) == 0
    made = sorted(os.listdir(out))
    assert made == [
        "suru_lang-9.9.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.musllinux_1_1_x86_64.whl",
        "suru_lang-9.9.9-py3-none-win_amd64.whl",
    ]

    with zipfile.ZipFile(out / made[0]) as z:
        wheel = z.read("suru_lang-9.9.9.dist-info/WHEEL").decode()
        assert "Tag: py3-none-any" not in wheel
        assert "Tag: py3-none-manylinux_2_17_x86_64" in wheel
        assert "Tag: py3-none-musllinux_1_1_x86_64" in wheel
        assert "Root-Is-Purelib: false" in wheel
        info = z.getinfo("suru_lang-9.9.9.data/scripts/suruc")
        assert (info.external_attr >> 16) & 0o111  # 実行できる
        assert z.read("suru_lang-9.9.9.data/scripts/kumu") == b"binary kumu"
        assert "suru_lang-9.9.9.data/scripts/README.md" not in z.namelist()
        # RECORD の sha256 と大きさが中身と合う
        rows = z.read("suru_lang-9.9.9.dist-info/RECORD").decode().splitlines()
        assert len(rows) == len(z.namelist())
        for row in rows:
            name, digest, size = row.rsplit(",", 2)
            if name.endswith("/RECORD"):
                assert digest == "" and size == ""
                continue
            data = z.read(name)
            want = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
            assert digest == f"sha256={want}" and int(size) == len(data)

    with zipfile.ZipFile(out / made[1]) as z:
        names = z.namelist()
        assert "suru_lang-9.9.9.data/scripts/suruc.exe" in names
        assert "suru_lang-9.9.9.data/scripts/suru-ls.exe" in names
        assert "Tag: py3-none-win_amd64" in z.read("suru_lang-9.9.9.dist-info/WHEEL").decode()


def test_missing_binary_is_an_error(tmp_path):
    pure = tmp_path / "suru_lang-9.9.9-py3-none-any.whl"
    _pure_wheel(pure)
    bins = tmp_path / "bin"
    bins.mkdir()
    _tar(bins / "suru-9.9.9-linux-amd64.tar.gz", ["suruc", "kumu"])
    try:
        platform_wheels.main(["x", str(pure), str(bins), str(tmp_path / "out")])
    except SystemExit as e:
        assert "suru-ls" in str(e)
    else:
        raise AssertionError("suru-ls がないのにエラーになりません")

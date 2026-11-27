# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 sugarsweetrobotics
"""純 Python の wheel から、OS ごとの wheel を作る(suruc・kumu・suru-ls を入れる)。

    python3 packaging/platform_wheels.py dist/suru_lang-0.12.0-py3-none-any.whl bin/ dist/

bin/ には packaging/build_binaries.sh が作った suru-版-OS-CPU.tar.gz(Windows は .zip)を置いておきます。
3つのバイナリは wheel の `suru_lang-版.data/scripts/` に入れるので、pip で入れると
`suru` と同じ場所(venv の bin/ など)に suruc・kumu・suru-ls も入ります(ruff や uv と同じ形)。
Go のバイナリは静的(CGO_ENABLED=0)なので、Linux は glibc(manylinux)でも musl(musllinux)でも動きます。
純 Python の wheel(py3-none-any)はそのまま残し、ほかの機械や Pyodide(Web の playground)はそれを使います。
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tarfile
import zipfile

# Go の対象 → wheel の platform タグ(Go 1.23 から macOS は 11 以上)
PLATFORMS = {
    "linux-amd64": "manylinux_2_17_x86_64.manylinux2014_x86_64.musllinux_1_1_x86_64",
    "linux-arm64": "manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64",
    "darwin-amd64": "macosx_11_0_x86_64",
    "darwin-arm64": "macosx_11_0_arm64",
    "windows-amd64": "win_amd64",
    "windows-arm64": "win_arm64",
}
COMMANDS = ("suruc", "kumu", "suru-ls")


def _record_hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


def read_binaries(archive: str) -> dict[str, bytes]:
    """固めたものから3つのバイナリを取り出す(名前 → 中身。Windows は .exe 付きの名前)"""
    out: dict[str, bytes] = {}
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                base = name.rsplit("/", 1)[-1]
                if base.removesuffix(".exe") in COMMANDS:
                    out[base] = z.read(name)
    else:
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                base = m.name.rsplit("/", 1)[-1]
                if m.isfile() and base in COMMANDS:
                    f = t.extractfile(m)
                    assert f is not None
                    out[base] = f.read()
    missing = [c for c in COMMANDS if c not in out and c + ".exe" not in out]
    if missing:
        raise SystemExit(f"{archive} に {', '.join(missing)} がありません")
    return out


def make_wheel(pure: str, binaries: dict[str, bytes], plat: str, out_dir: str) -> str:
    """pure(py3-none-any の wheel)に binaries を足して、タグを plat にした wheel を out_dir に書く"""
    base = os.path.basename(pure)
    if not base.endswith("-py3-none-any.whl"):
        raise SystemExit(f"{base} は純 Python の wheel(…-py3-none-any.whl)ではありません")
    stem = base.removesuffix("-py3-none-any.whl")  # suru_lang-0.12.0
    dist_info = stem + ".dist-info"
    data_scripts = stem + ".data/scripts"
    target = os.path.join(out_dir, f"{stem}-py3-none-{plat}.whl")
    records: list[str] = []
    with zipfile.ZipFile(pure) as src, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:

        def put(info: zipfile.ZipInfo, data: bytes) -> None:
            dst.writestr(info, data)
            records.append(f"{info.filename},{_record_hash(data)},{len(data)}")

        for info in src.infolist():
            if info.filename == f"{dist_info}/RECORD":
                continue
            data = src.read(info)
            if info.filename == f"{dist_info}/WHEEL":
                lines = [ln for ln in data.decode().splitlines() if not ln.startswith("Tag:")]
                lines += [f"Tag: py3-none-{p}" for p in plat.split(".")]
                # バイナリが入るので「純 Python」ではない(platlib に入れる)
                lines = [("Root-Is-Purelib: false" if ln.startswith("Root-Is-Purelib:") else ln) for ln in lines]
                data = ("\n".join(lines) + "\n").encode()
            put(info, data)
        for name in sorted(binaries):
            info = zipfile.ZipInfo(f"{data_scripts}/{name}", date_time=(2020, 2, 2, 0, 0, 0))
            info.external_attr = (0o100755 << 16)  # 実行できる普通のファイル
            info.compress_type = zipfile.ZIP_DEFLATED
            put(info, binaries[name])
        records.append(f"{dist_info}/RECORD,,")
        rec = zipfile.ZipInfo(f"{dist_info}/RECORD", date_time=(2020, 2, 2, 0, 0, 0))
        rec.compress_type = zipfile.ZIP_DEFLATED
        dst.writestr(rec, "\n".join(records) + "\n")
    return target


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    pure, bin_dir, out_dir = argv[1:]
    os.makedirs(out_dir, exist_ok=True)
    made = 0
    for key, plat in PLATFORMS.items():
        found = [f for f in os.listdir(bin_dir)
                 if f.endswith((f"-{key}.tar.gz", f"-{key}.zip")) and f.startswith("suru-")]
        if not found:
            print(f"{key} のバイナリがないので飛ばします", file=sys.stderr)
            continue
        print(make_wheel(pure, read_binaries(os.path.join(bin_dir, found[0])), plat, out_dir))
        made += 1
    if made == 0:
        print(f"{bin_dir} に suru-版-OS-CPU.tar.gz / .zip がありません", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

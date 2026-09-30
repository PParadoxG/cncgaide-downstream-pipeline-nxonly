"""Download and unpack Apache Jena Fuseki under install/fuseki/.

    python install/fuseki_install.py [--version 6.2.0]

The archive is fetched from the Apache download mirror, its SHA-512 is checked
against the published checksum, and it is unpacked to
``install/fuseki/apache-jena-fuseki-<version>/``.  Java 21 or later is
required to run it; this script only installs the files.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "fuseki"
DEFAULT_VERSION = "6.2.0"
MIRROR = "https://dlcdn.apache.org/jena/binaries/"
ARCHIVE = "https://archive.apache.org/dist/jena/binaries/"


def fetch(url: str, dest: Path) -> None:
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / total:6.1%}", end="", flush=True)
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=DEFAULT_VERSION)
    args = ap.parse_args()
    name = f"apache-jena-fuseki-{args.version}"
    TARGET.mkdir(parents=True, exist_ok=True)
    if (TARGET / name / "fuseki-server.jar").is_file():
        print(f"already installed: {TARGET / name}")
        return 0
    archive = TARGET / f"{name}.zip"
    for base in (MIRROR, ARCHIVE):
        try:
            fetch(f"{base}{name}.zip", archive)
            checksum = urllib.request.urlopen(f"{base}{name}.zip.sha512", timeout=60).read().decode().split()[0]
            break
        except Exception as error:  # noqa: BLE001
            print(f"  {base}: {error}")
            checksum = None
    if checksum is None:
        print("download failed")
        return 1
    actual = hashlib.sha512(archive.read_bytes()).hexdigest()
    if actual != checksum.lower():
        print(f"checksum mismatch: expected {checksum}, got {actual}")
        archive.unlink()
        return 1
    print("checksum ok; unpacking")
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(TARGET)
    archive.unlink()
    print(f"installed: {TARGET / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

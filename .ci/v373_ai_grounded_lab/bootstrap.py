from __future__ import annotations

from pathlib import Path
import argparse, base64, hashlib, io, shutil, zipfile

HERE = Path(__file__).resolve().parent
FIXTURE_PARTS = tuple(sorted(HERE.glob("fixture.part*.b64")))
EXPECTED_FIXTURE_TEXT_SHA256 = "bec085c0ba2336329e7a11d5e983f47e49ac153f4ce07432dfd53cf9a30f7649"
EXPECTED_ARCHIVE_SHA256 = "d85a8ad614a1eec89d3d99ed71e5c7731a5e8efb66c5a02f999760062911c572"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(HERE / "runtime"))
    args = p.parse_args()
    out = Path(args.out).resolve()

    if len(FIXTURE_PARTS) != 5:
        raise SystemExit(f"W12.2 fixture part count mismatch: {len(FIXTURE_PARTS)} != 5")

    packed_text = "".join(part.read_text(encoding="ascii") for part in FIXTURE_PARTS)
    text_sha = sha256(packed_text.encode("ascii"))
    if text_sha != EXPECTED_FIXTURE_TEXT_SHA256:
        raise SystemExit(f"W12.2 packed fixture text SHA mismatch: {text_sha}")

    raw = base64.b64decode(packed_text, validate=True)
    actual = sha256(raw)
    if actual != EXPECTED_ARCHIVE_SHA256:
        raise SystemExit(f"W12.2 packed fixture SHA mismatch: {actual}")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for info in z.infolist():
            target = (out / info.filename).resolve()
            if out not in target.parents and target != out:
                raise SystemExit(f"unsafe fixture path: {info.filename}")
        z.extractall(out)

    sums = {}
    for line in (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        expected, name = line.split(None, 1)
        sums[name.strip()] = expected
    for name, expected in sums.items():
        actual_file = sha256((out / name).read_bytes())
        if actual_file != expected:
            raise SystemExit(f"W12.2 file SHA mismatch {name}: {actual_file}")
        print(f"HASH PASS {name} {actual_file}")

    print(f"W12.2 fixture PASS text_sha256={text_sha} archive_sha256={actual} parts={len(FIXTURE_PARTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

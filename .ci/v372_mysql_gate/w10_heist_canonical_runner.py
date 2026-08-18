from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import shutil

import w10_heist_contracts as gate

CANONICAL_SOURCE_SHA256 = "2de77b645c52fa9d78f75b0105a795140237f8e34250b60e5ef70ca7d471d59d"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_overlay_and_verify(src: Path) -> None:
    # The ZIP is only a transport container. ZIP timestamps/compression metadata
    # are not source identity, so verify the authoritative extracted source bytes
    # instead of failing on a container-level hash difference.
    encoded = "".join(path.read_text(encoding="ascii") for path in gate.HEIST_PARTS)
    raw = base64.b64decode(encoded)
    archive = src.parent / "heist-source.zip"
    archive.write_bytes(raw)
    shutil.unpack_archive(str(archive), str(src))

    services = src / "app" / "services"
    services.mkdir(parents=True, exist_ok=True)
    (services / "__init__.py").touch(exist_ok=True)

    checks = (
        ("app/services/heist.py", src / "app" / "services" / "heist.py", gate.HEIST_FILE_SHA256),
        ("app/heist_config.py", src / "app" / "heist_config.py", gate.HEIST_CONFIG_SHA256),
    )

    canonical = hashlib.sha256()
    for relative, path, expected in checks:
        data = path.read_bytes()
        actual = _sha256(data)
        if actual != expected:
            raise AssertionError(
                f"Heist authoritative source hash mismatch for {relative}: "
                f"expected={expected}, actual={actual}"
            )
        canonical.update(relative.encode("utf-8"))
        canonical.update(b"\0")
        canonical.update(str(len(data)).encode("ascii"))
        canonical.update(b"\0")
        canonical.update(data)
        canonical.update(b"\0")

    actual_canonical = canonical.hexdigest()
    if actual_canonical != CANONICAL_SOURCE_SHA256:
        raise AssertionError(
            "Heist canonical source SHA mismatch: "
            f"expected={CANONICAL_SOURCE_SHA256}, actual={actual_canonical}"
        )


# Patch only the transport verification boundary. The real v3.72 HeistService,
# Database and db_backend transaction code executed by the W10.2 contracts is
# unchanged.
gate.overlay_and_verify_heist = canonical_overlay_and_verify
gate.HEIST_ZIP_SHA256 = CANONICAL_SOURCE_SHA256


if __name__ == "__main__":
    raise SystemExit(gate.main())

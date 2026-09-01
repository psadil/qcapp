"""The wire format for one unit's images: a tar of ``d<display>[s<slice>].avif``.

Deliberately Django-free: this is the module that decides whether bytes
arriving from outside are allowed to become files, and it is easier to trust —
and to test, with no database — when it depends on nothing. The push client
(``push.py``) uses the same functions to build what the server takes apart.

The guarantee it provides is that **a name chosen by the sender never reaches
a storage path**. Every member is matched against the unit's declared manifest
by the ``(display, slice)`` its own name parses to, its bytes are sniffed for
AVIF magic and re-digested, and the digest must equal the manifest's — so the
storage name (which embeds the digest) is rebuilt server-side from verified
parts. A member whose name does not parse is refused rather than sanitised.
"""

from __future__ import annotations

import hashlib
import io
import re
import tarfile
from collections.abc import Iterable, Iterator, Mapping
from typing import IO

#: Hex characters kept of a sha256 — plenty against accidental collision,
#: short enough to read in a URL.
DIGEST_LENGTH = 16

#: One member per rendered view: its display axis and optional slice index.
_MEMBER_RE = re.compile(r"^d(\d)(?:s(-?\d{1,5}))?\.avif$")

#: Sniffed rather than trusted: the stored extension is fixed (AVIF), so a
#: blob cannot pick its own Content-Type by picking its own file name.
_AVIF_BRANDS = frozenset({b"avif", b"avis"})


class RejectedImage(Exception):
    """A tar member is not an acceptable image. Carries the reason."""


def content_digest(data: bytes) -> str:
    """The 16-hex content fingerprint that names (and versions) an image."""
    return hashlib.sha256(data).hexdigest()[:DIGEST_LENGTH]


def is_avif(data: bytes) -> bool:
    """ISO-BMFF ``ftyp`` box whose major or compatible brand is AVIF."""
    if len(data) < 12 or data[4:8] != b"ftyp":
        return False
    if data[8:12] in _AVIF_BRANDS:
        return True
    # compatible brands fill the rest of the ftyp box, four bytes each
    box_size = min(int.from_bytes(data[0:4], "big"), len(data))
    brands = (data[at : at + 4] for at in range(16, box_size - 3, 4))
    return any(brand in _AVIF_BRANDS for brand in brands)


def member_name(display: int, slice: int | None) -> str:
    """The tar member name for one view of the unit."""
    cut = "" if slice is None else f"s{slice}"
    return f"d{display}{cut}.avif"


def read_unit_tar(
    fileobj: IO[bytes],
    *,
    expected: Mapping[tuple[int, int | None], str],
    max_member_bytes: int,
) -> Iterator[tuple[tuple[int, int | None], bytes]]:
    """Yield ``((display, slice), bytes)`` for each image in an uploaded tar.

    ``expected`` is the unit's declared manifest: ``(display, slice)`` to
    content digest. Streamed (``mode="r|"``), so peak memory is one member
    rather than the whole archive. Refuses, in this order and before trusting
    any payload: anything that is not a regular file (which is what excludes
    symlinks, hard links and device nodes), an oversized member, more members
    than the manifest declares, a name that does not parse, a view the
    manifest does not declare, a repeated view, bytes that are not AVIF, and
    bytes whose digest disagrees with the manifest.
    """
    seen: set[tuple[int, int | None]] = set()
    with tarfile.open(fileobj=fileobj, mode="r|") as tar:
        for member in tar:
            if not member.isfile():
                raise RejectedImage(f"{member.name!r} is not a regular file")
            if member.size > max_member_bytes:
                raise RejectedImage(
                    f"{member.name!r} is {member.size} bytes, over the "
                    f"{max_member_bytes}-byte limit"
                )
            if len(seen) >= len(expected):
                raise RejectedImage(f"more than the {len(expected)} declared image(s)")
            parsed = _MEMBER_RE.match(member.name)
            if parsed is None:
                raise RejectedImage(f"{member.name!r} is not an image member name")
            view = (int(parsed.group(1)), _maybe_int(parsed.group(2)))
            if view not in expected:
                raise RejectedImage(f"{member.name!r} is not a declared view")
            if view in seen:
                raise RejectedImage(f"{member.name!r} appears twice")
            handle = tar.extractfile(member)
            if handle is None:  # unreachable for isfile(), but typed Optional
                raise RejectedImage(f"{member.name!r} could not be read")
            data = handle.read()
            if not is_avif(data):
                raise RejectedImage(f"{member.name!r} is not an AVIF image")
            if content_digest(data) != expected[view]:
                raise RejectedImage(
                    f"{member.name!r} does not match its declared digest"
                )
            seen.add(view)
            yield view, data


def write_unit_tar(
    members: Iterable[tuple[int, int | None, bytes]], fileobj: IO[bytes]
) -> int:
    """Pack ``(display, slice, bytes)`` triples into ``fileobj``; return the count.

    View-derived names only: the unit's identity travels in the JSON payload,
    not the archive, so the receiver decides where the files land.
    """
    count = 0
    with tarfile.open(fileobj=fileobj, mode="w") as tar:
        for display, cut, data in members:
            info = tarfile.TarInfo(member_name(display, cut))
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            count += 1
    return count


def _maybe_int(text: str | None) -> int | None:
    return None if text is None else int(text)

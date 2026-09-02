"""Where rendered QC images live under ``MEDIA_ROOT``.

Images are ordinary Django media: written through ``default_storage`` and
served by the login-required media view out of ``settings.MEDIA_ROOT``. This
module owns nothing but their *layout*, so the naming rule lives in one place
instead of being spelled out at every call site.

The layout is content-addressed::

    images/<step cli_name>/<unit_key(file1)>/<digest>-d<display>[s<slice>].avif

``unit_key`` because ``file1`` is a bare basename for most steps but a full
catalog-relative path for surface localization: the readable half is the
sanitized basename, and the hash suffix keeps two distinct ``file1`` strings
from ever sharing a directory. ``digest`` — a fingerprint of the image bytes —
because it makes a re-render additive: new bytes get a new name, and the old
file is dropped only after the row points at the new one. Nothing is ever
overwritten in place, so an image URL never changes what it means and can be
served ``immutable``.

The ``Image`` row stores the resulting name in its ``FileField`` (assigned
directly, never through ``Storage.save``'s collision-renaming ``save()`` on the
field) and the digest in its own column, which is what makes "already
uploaded and unchanged" an exact comparison for the push client.
"""

from __future__ import annotations

import hashlib
import typing
from collections.abc import Iterable, Iterator
from contextlib import suppress
from pathlib import Path

import orjson
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename

from django_dirt_ratings import models, transfer

#: Rendered images all live under this storage prefix.
IMAGES_PREFIX = "images/"

#: The digest length is owned by the (Django-free) wire-format module, so the
#: push client and the server agree on it by construction.
DIGEST_LENGTH = transfer.DIGEST_LENGTH

#: The 16-hex content fingerprint that names (and versions) an image.
image_digest = transfer.content_digest


def unit_key(file1: str) -> str:
    """Directory-safe key for one ``file1`` — readable, and collision-proof.

    The basename is sanitized and truncated for the human half; the 8-hex hash
    of the *full* string keeps identities distinct when the basename alone is
    not (surface localization's ``file1`` is a catalog-relative path whose
    basename, ``ribbon.mgz``, repeats for every subject).
    """
    readable = get_valid_filename(Path(file1).name)[:80] or "file"
    return f"{readable}-{hashlib.sha256(file1.encode()).hexdigest()[:8]}"


def image_basename(*, display: int, slice: int | None, digest: str, ext: str) -> str:
    """One image's file name within its unit directory."""
    cut = "" if slice is None else f"s{slice}"
    return f"{digest}-d{display}{cut}.{ext}"


def image_name(
    *, step: int, file1: str, display: int, slice: int | None, digest: str
) -> str:
    """The storage-relative name for one rendered view of one file."""
    step_enum = models.Step(step)
    basename = image_basename(
        display=int(display), slice=slice, digest=digest, ext=step_enum.image_type
    )
    return f"{IMAGES_PREFIX}{step_enum.cli_name}/{unit_key(file1)}/{basename}"


def save(name: str, data: bytes) -> None:
    """Write ``data`` at ``name``, replacing anything already there.

    ``Storage.save`` on its own would *rename* around a collision
    (``…-d0_a8Fk2p.avif``), which would leave a re-pushed image serving its old
    bytes forever.
    """
    if default_storage.exists(name):
        default_storage.delete(name)
    default_storage.save(name, ContentFile(data))


def exists(name: str) -> bool:
    return default_storage.exists(name)


def delete(name: str) -> None:
    """Remove one stored image and any directories it leaves empty."""
    default_storage.delete(name)
    prefix = name.rsplit("/", 1)[0] + "/"
    _remove_empty_directory(prefix)


def modified_time(name: str):
    """When the stored file last changed (timezone-aware under USE_TZ)."""
    return default_storage.get_modified_time(name)


def unit_digest(images: Iterable[tuple[int, int | None, str]]) -> str:
    """Order-independent fingerprint of one unit's ``(display, slice, digest)`` set.

    Computable from ``Image`` rows alone — no file reads — so the push client
    and the server can agree on "present and unchanged" over the wire. A None
    slice keeps its own spelling (never an integer's), so a sliceless view can
    never alias a sliced one.
    """
    canonical = sorted(
        f"{display},{'' if slice is None else slice},{digest}"
        for display, slice, digest in images
    )
    return hashlib.sha256(";".join(canonical).encode()).hexdigest()[:DIGEST_LENGTH]


def unit_meta_digest(
    *,
    file2: str | None,
    entities: dict | None,
    values: typing.Mapping[str, float | None] | None,
    plan_hash: str | None,
) -> str:
    """Fingerprint of everything a unit carries *besides* its image bytes.

    The push skip-set compares this alongside :func:`unit_digest`, so a
    re-measure (new metrics, changed entities, a new plan) still reaches the
    server even when every rendered byte is identical. Canonical via orjson
    with sorted keys — both ends run the same serializer over the same float
    values, so equality is exact, not approximate.
    """
    payload = orjson.dumps(
        {
            "file2": file2,
            "entities": entities,
            "metrics": dict(values or {}),
            "plan_hash": plan_hash,
        },
        option=orjson.OPT_SORT_KEYS,
    )
    return hashlib.sha256(payload).hexdigest()[:DIGEST_LENGTH]


def stored_names() -> Iterator[str]:
    """Every stored image name under the images prefix (for pruning)."""
    pending = [IMAGES_PREFIX]
    while pending:
        prefix = pending.pop()
        directories, files = _listdir(prefix)
        pending.extend(f"{prefix}{directory}/" for directory in directories)
        for file_name in files:
            yield f"{prefix}{file_name}"


def _remove_empty_directory(prefix: str) -> None:
    """Drop the directory the deleted file was in, on a filesystem backend.

    ``Storage`` has no notion of one, because an object store has no
    directories — so this is best-effort and does nothing at all elsewhere.
    """
    try:
        path = Path(default_storage.path(prefix))
    except NotImplementedError:
        return
    with suppress(OSError):
        path.rmdir()


def _listdir(prefix: str) -> tuple[list[str], list[str]]:
    try:
        return default_storage.listdir(prefix)
    except (FileNotFoundError, NotADirectoryError):
        return [], []

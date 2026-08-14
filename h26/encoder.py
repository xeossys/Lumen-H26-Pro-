"""Top-level H26 encoder pipeline.

``compile(project)`` turns a :class:`~h26.project.Project` into a
valid binary H26 watchface (``.bin``).

The pipeline is layered so each stage is independently testable:

    1. Encode every :class:`ImageAsset` into a compressed
       graphical block (LZ4pal32 / BGR565 / ...).
    2. Build the preview block (JPG by default).
    3. Build the 0x40-byte header.
    4. Concatenate: header + preview + graphical blocks + UI table.
    5. Build the UI table (sequential UIItems, layout first).

Stage functions live in this module; the image encoding helpers
are in :mod:`h26.image_codec`.
"""

from __future__ import annotations

from h26.project import (
    Project,
)


class EncoderError(RuntimeError):
    """Raised when a project cannot be compiled."""


def compile(project: Project) -> bytes:  # noqa: A001 - shadows builtin intentionally
    """Compile a :class:`Project` into raw H26 ``.bin`` bytes.

    Raises:
        EncoderError: if the project references an unsupported
            UIItem type, a missing image, or otherwise cannot be
            turned into a valid binary.
    """
    raise EncoderError(
        "h26.encoder is not implemented yet (pipeline stage 1-5 pending implementation)"
    )

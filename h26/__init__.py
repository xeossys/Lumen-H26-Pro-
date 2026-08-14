"""H26 watchface encoder package.

Exposes the public API:
    - ``compile(project) -> bytes``            -- full pipeline
    - :class:`h26.project.*`                   -- data model / JSON

This package is deliberately importable headless (no PyQt6 at
import time). PyQt6 is only needed when actually *loading* a PNG
or rendering a preview; see :mod:`h26.image_codec`.
"""

from h26.encoder import compile  # noqa: F401
from h26.project import (
    AnimationItem,  # noqa: F401
    FrameItem,  # noqa: F401
    HandItem,  # noqa: F401
    ImageAsset,  # noqa: F401
    Layout,  # noqa: F401
    Project,  # noqa: F401
    ProjectSchemaError,  # noqa: F401
)

__all__ = [
    "compile",
    "Project",
    "Layout",
    "ImageAsset",
    "FrameItem",
    "HandItem",
    "AnimationItem",
    "ProjectSchemaError",
]

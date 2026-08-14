"""H26 watchface encoder package.

Exposes the public API:
    - ``compile(project) -> bytes``            -- full pipeline
    - :class:`h26.project.*`                   -- data model / JSON
    - Byte readers and LZ4 decoder from :mod:`h26.utils`
    - Block scanning and image decoding from :mod:`h26.decoder`

This package is deliberately importable headless (no PyQt6 at
import time). PyQt6 is only needed when actually *loading* a PNG
or rendering a preview; see :mod:`h26.image_codec`.
"""

from h26.decoder import (  # noqa: F401
    TAG_BGR565,
    TAG_BGR565A,
    TAG_GIF,
    TAG_JPG,
    TAG_LZ4PAL32,
    TAG_UNK_34,
    BlockInfo,
    UIItemInfo,
    decode_bgr565a_to_rgba,
    decode_block_to_rgba,
    decode_lz4pal32_to_rgba,
    extract_jpg_bytes,
    scan_blocks,
)
from h26.encoder import compile  # noqa: F401
from h26.image_codec import (
    ImageCodecError,  # noqa: F401
    build_jpg_preview_block,  # noqa: F401
    build_lz4pal32_block,  # noqa: F401
)
from h26.project import (
    AnimationItem,  # noqa: F401
    FrameItem,  # noqa: F401
    HandItem,  # noqa: F401
    ImageAsset,  # noqa: F401
    Layout,  # noqa: F401
    Project,  # noqa: F401
    ProjectSchemaError,  # noqa: F401
)
from h26.utils import (  # noqa: F401
    MAGIC,
    TAG_NAMES,
    decompress_lz4_vb,
    vb_get_3b_be,
    vb_get_4b_be,
    vb_get_4b_le,
    vb_get_4b_signed_be,
    vb_get_4b_signed_le,
)

__all__ = [
    "compile",
    "build_lz4pal32_block",
    "build_jpg_preview_block",
    "ImageCodecError",
    "Project",
    "Layout",
    "ImageAsset",
    "FrameItem",
    "HandItem",
    "AnimationItem",
    "ProjectSchemaError",
    # From h26.decoder
    "BlockInfo",
    "TAG_BGR565",
    "TAG_BGR565A",
    "TAG_GIF",
    "TAG_JPG",
    "TAG_LZ4PAL32",
    "TAG_UNK_34",
    "UIItemInfo",
    "scan_blocks",
    "decode_lz4pal32_to_rgba",
    "decode_bgr565a_to_rgba",
    "decode_block_to_rgba",
    "extract_jpg_bytes",
    # From h26.utils
    "MAGIC",
    "TAG_NAMES",
    "decompress_lz4_vb",
    "vb_get_3b_be",
    "vb_get_4b_be",
    "vb_get_4b_le",
    "vb_get_4b_signed_be",
    "vb_get_4b_signed_le",
]

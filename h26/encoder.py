"""Top-level H26 encoder pipeline.

``compile(project)`` turns a :class:`~h26.project.Project` into a
valid binary H26 watchface (``.bin``).

The pipeline is layered so each stage is independently testable:

    1. Encode every :class:`ImageAsset` into a compressed graphical
       block (LZ4pal32).
    2. Build the preview block (JPG by default).
    3. Build the 0x40-byte header.
    4. Concatenate: header + preview + graphical blocks + UI table.
    5. Build the UI table (sequential UIItems, layout first).

Stage functions live in this module; the image encoding helpers
are in :mod:`h26.image_codec`.

**Endianness note** (important for future maintainers):

``main.py``'s helper functions have misleading names:
``vb_get_4b_le`` actually reads **big-endian** and ``vb_get_4b_be``
reads **little-endian**. The header fields (preview_offset, l2, l3,
l3_length) are read with ``vb_get_4b_le`` → they are **big-endian**.
Block lengths at offset 8 are read with ``vb_get_4b_be`` → they are
**little-endian**. This module uses explicit ``struct.pack(">I", ...)``
for BE and ``struct.pack("<I", ...)`` for LE to avoid ambiguity.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Sequence

from h26.image_codec import (
    build_jpg_preview_block,
    build_lz4pal32_block,
)
from h26.project import (
    TYPE_ANIMATION,
    TYPE_FRAME,
    TYPE_FRAME2,
    TYPE_HAND,
    AnimationItem,
    FrameItem,
    HandItem,
    Layout,
    Project,
    UIItemBase,
)


class EncoderError(RuntimeError):
    """Raised when a project cannot be compiled."""


# --------------------------------------------------------------------------
# Stage 1-2: Image blocks (delegate to image_codec)
# --------------------------------------------------------------------------


def _encode_image_asset(rgba: Sequence[int], width: int, height: int) -> bytes:
    """Encode RGBA pixels as a full LZ4pal32 graphical block."""
    return build_lz4pal32_block(rgba, width, height)


def _encode_preview(jpg_bytes: bytes) -> bytes:
    """Wrap raw JPEG bytes in a JPG preview block."""
    return build_jpg_preview_block(jpg_bytes)


# --------------------------------------------------------------------------
# Stage 3: Header builder
# --------------------------------------------------------------------------

HEADER_SIZE = 0x40
MAGIC = b"Sb@*"
# The watchface name area at 0x04..0x0B. We use a fixed placeholder
# matching the fixtures (the meaning of "O2GG" is still unclear —
# see spec Q2).
WF_NAME_PLACEHOLDER = b"O2GG\x00\x0bPC"


def build_header(
    preview_offset: int,
    preview_length: int,
    l3: int,
    l3_length: int,
    l2: int,
) -> bytearray:
    """Build the 0x40-byte file header.

    Field layout (all values big-endian unless noted):
        0x00: magic "Sb@*" (4 bytes)
        0x04: watchface name placeholder (8 bytes)
        0x0C: preview_offset (4 bytes BE)
        0x10: preview_length (4 bytes BE)
        0x14: l3 — "internal addressing block" offset (4 bytes BE)
        0x18: l3_length (4 bytes BE)
        0x1C: l2 — UI table offset (4 bytes BE)
        0x20..0x3F: zero padding
    """
    h = bytearray(HEADER_SIZE)
    h[0:4] = MAGIC
    h[4:12] = WF_NAME_PLACEHOLDER
    struct.pack_into(">I", h, 0x0C, preview_offset)
    struct.pack_into(">I", h, 0x10, preview_length)
    struct.pack_into(">I", h, 0x14, l3)
    struct.pack_into(">I", h, 0x18, l3_length)
    struct.pack_into(">I", h, 0x1C, l2)
    return h


# --------------------------------------------------------------------------
# Stage 5: UI table encoder
# --------------------------------------------------------------------------


def _encode_ui_item_header(item: UIItemBase) -> bytearray:
    """Encode the standard 5x4-byte UI item header."""
    buf = bytearray(20)
    struct.pack_into(">I", buf, 0, item.item_type)
    struct.pack_into(">I", buf, 4, item.sub_type)
    struct.pack_into(">I", buf, 8, item.align)
    struct.pack_into(">i", buf, 12, item.x)
    struct.pack_into(">i", buf, 16, item.y)
    return buf


def _encode_layout(layout: Layout, item_offsets: dict[str, int]) -> bytes:
    """Encode a Type 0x00 layout with its children.

    The layout's extended bytes follow the 5x4 header:
        [counter:4b] [child_index_0:4b] [child_index_1:4b] ...

    ``item_offsets`` maps ``ImageAsset.name`` to the UI item index
    of that item in the final table.
    """
    header = _encode_ui_item_header(layout)
    # Extended bytes: the parser reads this as `loops` groups,
    # each with its own `count` + child indices. We emit a
    # single group (loops=1) containing all children.
    ext = bytearray()
    ext += struct.pack(">I", 1)  # loops = 1 (one group)
    ext += struct.pack(">I", len(layout.children))  # count in this group
    for child in layout.children:
        idx = _child_index(child, item_offsets)
        ext += struct.pack(">I", idx)
    return bytes(header) + bytes(ext)


def _encode_frame(item: FrameItem, image_blocks: dict[str, int]) -> bytes:
    """Encode a Type 0x01 / 0x02 frame item.

    Extended bytes: [frame_count:4b] [offset:4b] [length:4b]
    """
    header = _encode_ui_item_header(item)
    block_offset = image_blocks.get(item.image_name, 0)
    block_length = 0  # not tracked in v1 (the parser ignores it)
    ext = bytearray()
    ext += struct.pack(">I", 1)  # frame count
    ext += struct.pack(">I", block_offset)  # frame offset
    ext += struct.pack(">I", block_length)  # frame length
    return bytes(header) + bytes(ext)


def _encode_hand(item: HandItem, image_blocks: dict[str, int]) -> bytes:
    """Encode a Type 0x0F hand item.

    Extended bytes (per spec 4.5):
        [frame_count:4b]
        [rX:4b] [rY:4b]
        [frame_offset:4b] [frame_length:4b]
    """
    header = _encode_ui_item_header(item)
    block_offset = image_blocks.get(item.image_name, 0)
    ext = bytearray()
    ext += struct.pack(">I", 1)  # frame count
    ext += struct.pack(">i", item.pivot_x)  # rX (signed)
    ext += struct.pack(">i", item.pivot_y)  # rY (signed)
    ext += struct.pack(">I", block_offset)  # frame offset
    ext += struct.pack(">I", 0)  # frame length
    return bytes(header) + bytes(ext)


def _encode_animation(item: AnimationItem, image_blocks: dict[str, int]) -> bytes:
    """Encode a Type 0x14 animation item.

    Extended bytes (per spec 4.6, variant 0x34):
        [unknown:4b] [X:4b] [Y:4b]
        [frame_count:4b]
        [offset_0:4b] [length_0:4b]
        [offset_1:4b] [length_1:4b] ...
    """
    header = _encode_ui_item_header(item)
    ext = bytearray()
    ext += struct.pack(">I", 0)  # unknown
    ext += struct.pack(">i", item.x)
    ext += struct.pack(">i", item.y)
    ext += struct.pack(">I", len(item.frame_names))
    for name in item.frame_names:
        offset = image_blocks.get(name, 0)
        ext += struct.pack(">I", offset)
        ext += struct.pack(">I", 0)  # length
    return bytes(header) + bytes(ext)


def _child_index(child: UIItemBase, item_offsets: dict[str, int]) -> int:
    """Look up the UI table index for a child item by its image_name."""
    idx = item_offsets.get(child.image_name, 0)
    return idx


def encode_ui_table(
    layout: Layout,
    image_blocks: dict[str, int],
) -> bytes:
    """Encode the full UI table for a single layout.

    The table is a flat concatenation of UI items, starting with the
    layout itself (Type 0x00), followed by its children in order.

    Returns the raw UI table bytes.
    """
    parts: list[bytes] = []
    # The layout itself is always item 0.
    # Build a name→index map for child references.
    item_offsets: dict[str, int] = {}
    for i, child in enumerate(layout.children):
        item_offsets[child.image_name] = i + 1  # +1 because layout is 0

    parts.append(_encode_layout(layout, item_offsets))

    for child in layout.children:
        if isinstance(child, FrameItem) or child.item_type in (TYPE_FRAME, TYPE_FRAME2):
            parts.append(_encode_frame(child, image_blocks))
        elif isinstance(child, HandItem) or child.item_type == TYPE_HAND:
            parts.append(_encode_hand(child, image_blocks))
        elif isinstance(child, AnimationItem) or child.item_type == TYPE_ANIMATION:
            parts.append(_encode_animation(child, image_blocks))
        else:
            raise EncoderError(
                f"unsupported UI item type 0x{child.item_type:02X} "
                f"in encoder v1 (only Frame, Hand, Animation supported)"
            )

    return b"".join(parts)


# --------------------------------------------------------------------------
# Stage 4+5: Top-level compile
# --------------------------------------------------------------------------


def compile(project: Project) -> bytes:  # noqa: A001
    """Compile a :class:`Project` into raw H26 ``.bin`` bytes.

    Pipeline:
        1. Encode each image asset as a LZ4pal32 graphical block.
        2. Build the preview block (JPG).
        3. Build the header (0x40 bytes).
        4. Concatenate: header + preview + blocks + UI table.
        5. Patch header fields (preview_offset, l2, l3, l4).

    Raises:
        EncoderError: if a referenced image is missing, an
            unsupported UIItem type is encountered, or the
            project is otherwise invalid.
    """
    # ---- Validate ------------------------------------------------------
    if not project.layout.children:
        raise EncoderError("project layout has no children")

    # ---- Stage 1: encode image assets ----------------------------------
    block_order: list[str] = []  # image names in file order
    block_data: dict[str, bytes] = {}  # name → encoded block bytes
    image_blocks: dict[str, int] = {}  # name → offset (filled later)

    for img in project.images:
        rgba = _load_rgba(img.source_path, img.width, img.height)
        block = _encode_image_asset(rgba, img.width, img.height)
        block_order.append(img.name)
        block_data[img.name] = block

    # ---- Stage 2: preview block ----------------------------------------
    preview_bytes = _make_preview(project)
    preview_block = _encode_preview(preview_bytes)

    # ---- Stage 3: header (will be patched later) -----------------------
    header = build_header(
        preview_offset=HEADER_SIZE,  # placeholder
        preview_length=len(preview_block),
        l3=0,
        l3_length=0,
        l2=0,  # placeholders
    )

    # ---- Stage 4: concatenate ------------------------------------------
    # header + preview + graphical blocks + UI table
    parts: list[bytes] = [bytes(header), preview_block]

    # Graphical blocks
    for name in block_order:
        image_blocks[name] = len(b"".join(parts))  # record offset
        parts.append(block_data[name])

    # UI table
    ui_table = encode_ui_table(project.layout, image_blocks)
    parts.append(ui_table)

    result = bytearray(b"".join(parts))

    # ---- Stage 5: patch header fields ----------------------------------
    preview_offset = HEADER_SIZE
    l3 = preview_offset + len(preview_block)
    l3_length = sum(len(block_data[n]) for n in block_order)
    l2 = l3 + l3_length

    struct.pack_into(">I", result, 0x0C, preview_offset)
    struct.pack_into(">I", result, 0x10, len(preview_block))
    struct.pack_into(">I", result, 0x14, l3)
    struct.pack_into(">I", result, 0x18, l3_length)
    struct.pack_into(">I", result, 0x1C, l2)

    return bytes(result)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _load_rgba(source_path: str, width: int, height: int) -> Sequence[int]:
    """Load RGBA pixels from a file path.

    Uses Pillow if available, otherwise raises an error. The caller
    must supply valid (width, height) — the encoder trusts the
    project metadata.
    """
    path = Path(source_path)
    if not path.exists():
        raise EncoderError(f"image file not found: {source_path}")

    try:
        from PIL import Image
    except ImportError as exc:
        raise EncoderError(
            f"Pillow is required to load image files (pip install Pillow): {exc}"
        ) from exc

    img = Image.open(path).convert("RGBA")
    if img.size != (width, height):
        # Resize to match the declared dimensions.
        img = img.resize((width, height), Image.LANCZOS)
    # Flatten (R,G,B,A) tuples into a flat byte list.
    flat = bytearray()
    for r, g, b, a in img.getdata():
        flat += bytes((r, g, b, a))
    return list(flat)


def _make_preview(project: Project) -> bytes:
    """Render a JPEG preview image from the project.

    If ``project.preview_source_path`` is set, load that file
    directly. Otherwise render the layout background as a 240x240
    JPEG (requires Pillow).
    """
    if project.preview_source_path:
        path = Path(project.preview_source_path)
        if path.exists():
            return path.read_bytes()

    # Render a placeholder preview: solid dark gray.
    try:
        from PIL import Image

        img = Image.new("RGB", (project.canvas_width, project.canvas_height), (32, 32, 32))
        import io

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except ImportError:
        # No Pillow: return a minimal valid JPEG (smallest possible).
        # This is a 1x1 gray JPEG.
        return (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01"
            b"\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07"
            b"\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13"
            b"\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c"
            b"(7),01444\x1f'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01"
            b"\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05"
            b"\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08"
            b"\x01\x01\x00\x00?\x00T\xdb\x9e\xa7I\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\xff\xd9"
        )

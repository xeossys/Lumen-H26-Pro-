"""Shared H26 binary decoder logic.

This module contains the core decoding algorithms shared between
the GUI (main.py) and the CLI (h26/cli.py):

- Block scanning and type detection
- Image decoding (LZ4pal32, BGR565A → raw RGBA bytes)
- UI table parsing

The output is always raw RGBA bytes or structured dicts.
GUI-specific rendering (QImage) and CLI-specific output (PNG)
are handled by the respective callers.
"""

from __future__ import annotations

from typing import Any

from h26.utils import (
    decompress_lz4_vb,
    vb_get_3b_be,
    vb_get_4b_be,
    vb_get_4b_le,
    vb_get_4b_signed_be,
)

# Block type tags (from the H26 spec, section 3)
TAG_LZ4PAL32 = (0x4B, 0x01)
TAG_BGR565A = (0x48, 0x01)
TAG_BGR565 = (0x49, 0x01)
TAG_JPG = (0x09, 0x00)
TAG_GIF = (0x03, 0x00)
TAG_UNK_34 = (0x34, 0x01)  # Unknown block type found in some watchfaces

TAG_NAMES = {
    TAG_LZ4PAL32: "LZ4pal32",
    TAG_BGR565A: "BGR565A",
    TAG_BGR565: "BGR565",
    TAG_JPG: "JPG",
    TAG_GIF: "GIF",
    TAG_UNK_34: "UNK_34",
}


# ---------------------------------------------------------------------------
# Block info
# ---------------------------------------------------------------------------


class BlockInfo:
    """Information about a graphical block in an H26 file."""

    __slots__ = ("offset", "tag", "type_name", "size", "width", "height", "raw")

    def __init__(
        self,
        offset: int = 0,
        *,
        tag: tuple[int, int] = (0, 0),
        type_name: str = "unknown",
        size: int = 0,
        width: int = 0,
        height: int = 0,
        raw: bytes = b"",
    ):
        self.offset = offset
        self.tag = tag
        self.type_name = type_name
        self.size = size
        self.width = width
        self.height = height
        self.raw = raw

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "tag": self.tag,
            "type": self.type_name,
            "size": self.size,
            "width": self.width,
            "height": self.height,
        }


# ---------------------------------------------------------------------------
# UI item info
# ---------------------------------------------------------------------------


class UIItemInfo:
    """Information about a UI item in the UI table."""

    __slots__ = (
        "index",
        "type",
        "sub_type",
        "x",
        "y",
        "header_offset",
        "extended_length",
        "frame_indices",
        "pivot",
        "data_values",
        "system_screens",
    )

    def __init__(self, index: int = 0):
        self.index = index
        self.type = 0
        self.sub_type = 0
        self.x = 0
        self.y = 0
        self.header_offset = 0
        self.extended_length = 0
        self.frame_indices: list[int] = []
        self.pivot: list[int] = []
        self.data_values: list[int] = []
        self.system_screens: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        result = {
            "index": self.index,
            "type": f"0x{self.type:02X}",
            "sub_type": f"0x{self.sub_type:02X}",
            "x": self.x,
            "y": self.y,
            "header_offset": self.header_offset,
            "extended_length": self.extended_length,
        }
        if self.frame_indices:
            result["frame_indices"] = self.frame_indices
        if self.pivot:
            result["pivot"] = self.pivot
        if self.system_screens:
            result["system_screens"] = self.system_screens
        return result


# ---------------------------------------------------------------------------
# Image decoding (LZ4pal32, BGR565A → RGBA)
# ---------------------------------------------------------------------------


def decode_lz4pal32_to_rgba(block: bytes) -> tuple[bytes, int, int] | None:
    """Decode an LZ4pal32 block to raw RGBA bytes.

    Returns (rgba_bytes, width, height) or None if invalid.
    """
    if len(block) < 0x11:
        return None

    b1, b2 = block[0], block[1]
    if b1 != 0x4B or b2 != 0x01:
        return None

    size_val = vb_get_3b_be(block, 5)
    w = size_val >> 12
    h = size_val & 0xFFF

    if w <= 0 or h <= 0 or w > 1000 or h > 1000:
        return None

    payload = block[0x10:]
    unpacked = decompress_lz4_vb(payload)

    if len(unpacked) <= 0x400:
        return None

    # Read palette (256 entries × 4 bytes BGRA)
    palette = []
    for i in range(0, 0x400, 4):
        b_val = unpacked[i]
        g_val = unpacked[i + 1]
        r_val = unpacked[i + 2]
        a_val = unpacked[i + 3]
        palette.append((r_val, g_val, b_val, a_val))

    # Decode pixels
    rgba = bytearray(w * h * 4)
    idx = 0x400
    for y_pos in range(h):
        for x_pos in range(w):
            if idx < len(unpacked) and unpacked[idx] < len(palette):
                r, g, b, a = palette[unpacked[idx]]
                offset = (y_pos * w + x_pos) * 4
                rgba[offset] = r
                rgba[offset + 1] = g
                rgba[offset + 2] = b
                rgba[offset + 3] = a
            idx += 1

    return bytes(rgba), w, h


def decode_bgr565a_to_rgba(block: bytes) -> tuple[bytes, int, int] | None:
    """Decode a BGR565A block to raw RGBA bytes.

    Returns (rgba_bytes, width, height) or None if invalid.
    """
    if len(block) < 0x11:
        return None

    b1, b2 = block[0], block[1]
    if b1 != 0x48 or b2 != 0x01:
        return None

    size_val = vb_get_3b_be(block, 5)
    w = size_val >> 12
    h = size_val & 0xFFF

    if w <= 0 or h <= 0 or w > 1000 or h > 1000:
        return None

    payload = block[0x10:]
    unpacked = decompress_lz4_vb(payload)

    rgba = bytearray(w * h * 4)
    idx = 0
    for y_pos in range(h):
        for x_pos in range(w):
            if idx + 2 < len(unpacked):
                c565 = (unpacked[idx + 1] << 8) | unpacked[idx]
                alpha = unpacked[idx + 2]
                r = ((c565 & 0xF800) >> 11) * 255 // 31
                g = ((c565 & 0x07E0) >> 5) * 255 // 63
                b = (c565 & 0x001F) * 255 // 31
                offset = (y_pos * w + x_pos) * 4
                rgba[offset] = r
                rgba[offset + 1] = g
                rgba[offset + 2] = b
                rgba[offset + 3] = alpha
                idx += 3

    return bytes(rgba), w, h


def extract_jpg_bytes(block: bytes) -> bytes | None:
    """Extract raw JPG bytes from a JPG block.

    Returns the JPG byte data or None if invalid.
    """
    if len(block) < 0x11:
        return None

    b1, b2 = block[0], block[1]
    if b1 != 0x09 or b2 != 0x00:
        return None

    data_len = vb_get_3b_be(block, 2)
    return block[0x10 : 0x10 + data_len]


def decode_block_to_rgba(block: bytes) -> tuple[bytes, int, int] | None:
    """Decode any supported image block to raw RGBA bytes.

    Returns (rgba_bytes, width, height) or None if unsupported/invalid.
    """
    b1, b2 = block[0], block[1]
    tag = (b1, b2)

    if tag == TAG_LZ4PAL32:
        return decode_lz4pal32_to_rgba(block)
    elif tag == TAG_BGR565A:
        return decode_bgr565a_to_rgba(block)
    else:
        return None


# ---------------------------------------------------------------------------
# Block scanning
# ---------------------------------------------------------------------------


def scan_blocks(b: bytes) -> dict[str, Any]:
    """Scan a binary H26 file and return structural info.

    Returns dict with keys:
    - preview_offset, l3, l3_len, l2: header fields
    - blocks: list of BlockInfo objects
    - ui_items: list of UIItemInfo objects
    """
    preview_offset = vb_get_4b_le(b, 0x0C)
    l3 = vb_get_4b_le(b, 0x14)
    l3_len = vb_get_4b_le(b, 0x18)
    l2 = vb_get_4b_le(b, 0x1C)

    # Scan graphical blocks
    pos = preview_offset
    tpos = min(len(b) - 1, l2)
    blocks: list[BlockInfo] = []

    while pos < tpos:
        if pos + 1 >= len(b):
            break
        b1, b2 = b[pos], b[pos + 1]
        tag = (b1, b2)
        tag_name = TAG_NAMES.get(tag, "unknown")

        if tag in (TAG_LZ4PAL32, TAG_BGR565A, TAG_BGR565):
            data_len = vb_get_4b_be(b, pos + 8)
            l1 = data_len + 0x10
        elif tag in (TAG_JPG, TAG_GIF):
            data_len = vb_get_3b_be(b, pos + 2)
            l1 = data_len + 0x10
        elif tag == TAG_UNK_34:
            # Unknown block type with different header size
            data_len = vb_get_3b_be(b, pos + 2)
            l1 = data_len + 0x08
        else:
            guess = vb_get_3b_be(b, pos + 2) + 0x10
            l1 = guess if 0x10 < guess < len(b) - pos else max((len(b) - pos), 1)
        size_val = vb_get_3b_be(b, pos + 5) if pos + 5 < len(b) else 0
        w = (size_val >> 12) & 0xFFF
        h = size_val & 0xFFF

        block_info = BlockInfo(
            offset=pos,
            tag=tag,
            type_name=tag_name,
            size=l1,
            width=w,
            height=h,
            raw=b[pos : pos + l1],
        )
        blocks.append(block_info)

        pos += l1

    # Parse UI table
    ui_items = _parse_ui_table(b, l2)

    return {
        "preview_offset": preview_offset,
        "l3": l3,
        "l3_len": l3_len,
        "l2": l2,
        "blocks": blocks,
        "ui_items": ui_items,
    }


# ---------------------------------------------------------------------------
# UI table parsing
# ---------------------------------------------------------------------------


def _parse_ui_table(b: bytes, l2: int) -> list[UIItemInfo]:
    """Parse the UI table starting at offset l2.

    Returns a list of UIItemInfo objects.
    """
    if l2 >= len(b) - 1:
        return []

    ui_raw = b[l2:]
    pos = 0
    tpos = len(ui_raw)
    items: list[UIItemInfo] = []
    idx = 0

    while pos + 20 <= tpos:
        item_start = pos
        item = UIItemInfo(idx)
        item.header_offset = l2 + pos

        # Read header: type, sub_type, align (unsigned) + x, y (signed)
        item.type = vb_get_4b_le(ui_raw, pos)
        item.sub_type = vb_get_4b_le(ui_raw, pos + 4)
        _align = vb_get_4b_le(ui_raw, pos + 8)
        item.x = vb_get_4b_signed_be(ui_raw, pos + 12)
        item.y = vb_get_4b_signed_be(ui_raw, pos + 16)
        pos += 20

        # Calculate extended bytes length based on type
        ext_len = _calc_extended_length(ui_raw, pos, tpos - pos, item.type, item.sub_type)
        item.extended_length = ext_len

        # Parse extended data for specific types
        _parse_extended_data(ui_raw, item_start + 20, ext_len, item)

        pos += ext_len
        items.append(item)
        idx += 1

    return items


def _calc_extended_length(ui_raw: bytes, pos: int, remaining: int, t_type: int, t_sub: int) -> int:
    """Calculate the extended bytes length for a UI item."""

    if t_type == 0x00:  # Layout
        if t_sub in (0x8C, 0x8D):
            loops = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
            return 4 + 4 + loops * 4
        elif t_sub == 0x34:
            loops = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
            return 8 + loops * 8
        elif t_sub in (0x0B, 0, 0x11, 0x17, 0x32, 0x28):
            loops = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
            return 4 + loops * 8
        else:
            return remaining

    elif t_type in (0x01, 0x02, 3, 5, 6, 0x18, 0x56):  # Frame types
        count = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
        return 4 + count * 8

    elif t_type == 0x0F:  # Hand
        count = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
        return 4 + count * 16

    elif t_type == 0x14:  # Animation
        if t_sub in (0x34, 0x3B):
            count = vb_get_4b_le(ui_raw, pos + 4) if pos + 4 < len(ui_raw) else 0
            return 8 + count * 8
        elif t_sub == 0x70:
            count = vb_get_4b_le(ui_raw, pos + 8) if pos + 8 < len(ui_raw) else 0
            return 12 + count * 8
        else:
            count = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
            return 4 + count * 8

    elif t_type == 0x37:  # Button
        return 12

    elif t_type == 0x47:  # Angle font
        count = vb_get_4b_le(ui_raw, pos) if pos < len(ui_raw) else 0
        return 4 + count * 16

    else:
        return remaining


def _parse_extended_data(ui_raw: bytes, ext_start: int, ext_len: int, item: UIItemInfo) -> None:
    """Parse extended data for specific UI item types."""

    if item.type in (0x01, 0x02):  # Frame
        if ext_len >= 4:
            img_off = vb_get_4b_le(ui_raw, ext_start)
            item.frame_indices.append(img_off)

    elif item.type == 0x0F:  # Hand
        count = ext_len // 16 if ext_len >= 4 else 0
        pos = ext_start + 4  # Skip count field
        for _ in range(count):
            if pos + 12 <= len(ui_raw):
                px = vb_get_4b_le(ui_raw, pos)
                py = vb_get_4b_le(ui_raw, pos + 4)
                img_off = vb_get_4b_le(ui_raw, pos + 8)
                item.data_values.extend([px, py])
                item.frame_indices.append(img_off)
                pos += 16

    elif item.type == 0x14:  # Animation
        if item.sub_type in (0x34, 0x3B):
            count = vb_get_4b_le(ui_raw, ext_start + 4) if ext_len >= 8 else 0
            pos = ext_start + 8
            for _ in range(count):
                if pos + 8 <= len(ui_raw):
                    img_off = vb_get_4b_le(ui_raw, pos)
                    item.frame_indices.append(img_off)
                    pos += 8

    elif item.type == 0x37:  # Button
        if ext_len >= 12:
            count = vb_get_4b_le(ui_raw, ext_start)
            item.data_values.append(count)
            for i in range(min(count, 3)):
                val = vb_get_4b_le(ui_raw, ext_start + 4 + i * 4)
                if val >= 0:
                    item.data_values.append(val)

    elif item.type == 0x47:  # Angle font
        if ext_len >= 4:
            count = vb_get_4b_le(ui_raw, ext_start)
            item.data_values.append(count)
            pos = ext_start + 4
            for _ in range(count):
                if pos + 16 <= len(ui_raw):
                    dx = vb_get_4b_signed_be(ui_raw, pos + 4)
                    dy = vb_get_4b_signed_be(ui_raw, pos + 8)
                    img_off = vb_get_4b_le(ui_raw, pos + 12)
                    item.data_values.extend([dx, dy])
                    item.frame_indices.append(img_off)
                    pos += 16

    elif item.type == 0x5B and ext_len >= 16:  # Solid color rectangle
        item.data_values = [
            vb_get_4b_le(ui_raw, ext_start),
            vb_get_4b_le(ui_raw, ext_start + 4),
            vb_get_4b_le(ui_raw, ext_start + 8),
            vb_get_4b_le(ui_raw, ext_start + 12),
            vb_get_4b_le(ui_raw, ext_start + 16) if ext_len >= 20 else 0,
        ]

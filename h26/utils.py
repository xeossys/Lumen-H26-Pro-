"""Shared low-level utilities for the H26 encoder/decoder.

Byte readers and LZ4 decompression used by both the CLI
and the GUI (main.py).

**Endianness warning** (from main.py):

``vb_get_4b_le`` is actually **big-endian** and ``vb_get_4b_be`` is
actually **little-endian**. The names are backwards — this matches
main.py's original naming and must be preserved for compatibility.
"""

from __future__ import annotations

import struct

# ---------------------------------------------------------------------------
# Byte readers
# ---------------------------------------------------------------------------


def vb_get_4b_be(b: bytes, pos: int) -> int:
    """Read 4 bytes as little-endian unsigned.

    NOTE: Despite the name (which matches main.py), this reads
    **little-endian**. The name is backwards for historical reasons.
    """
    if pos < 0 or pos + 3 >= len(b):
        return -1
    return b[pos] + (b[pos + 1] << 8) + (b[pos + 2] << 16) + (b[pos + 3] << 24)


def vb_get_4b_le(b: bytes, pos: int) -> int:
    """Read 4 bytes as big-endian unsigned.

    NOTE: Despite the name (which matches main.py), this reads
    **big-endian**. The name is backwards for historical reasons.
    """
    if pos < 0 or pos + 3 >= len(b):
        return -1
    return (b[pos] << 24) + (b[pos + 1] << 16) + (b[pos + 2] << 8) + b[pos + 3]


def vb_get_4b_signed_be(b: bytes, pos: int) -> int:
    """Read 4 bytes as a SIGNED big-endian 32-bit integer.

    NOTE: this function was previously misnamed ``vb_get_4b_signed_le``
    but was always reading big-endian (``>i``). Per the H26 spec, all
    integer values in the UI Table are signed big-endian, so the
    behaviour was correct — only the name was wrong.
    """
    if pos < 0 or pos + 3 >= len(b):
        return -1
    return struct.unpack(">i", b[pos : pos + 4])[0]


# Backwards-compat alias: keep the old name so older call sites still work.
vb_get_4b_signed_le = vb_get_4b_signed_be


def vb_get_3b_be(b: bytes, pos: int) -> int:
    """Read 3 bytes as little-endian unsigned.

    NOTE: Despite the name (which matches main.py), this reads
    **little-endian**. The name is backwards for historical reasons.
    """
    if pos < 0 or pos + 2 >= len(b):
        return -1
    return b[pos] + (b[pos + 1] << 8) + (b[pos + 2] << 16)


# ---------------------------------------------------------------------------
# LZ4 decompression
# ---------------------------------------------------------------------------


def decompress_lz4_vb(b: bytes) -> bytes:
    """Decompress an LZ4 VB stream (H26 proprietary variant).

    This is the same algorithm used in main.py's parser.
    """
    db = bytearray()
    pos = 0
    tpos = len(b) - 1
    try:
        while pos < tpos:
            bt = b[pos]
            cl = bt >> 4
            cm = (bt & 0x0F) + 4
            pos += 1
            if cl == 0x0F:
                while True:
                    bt = b[pos]
                    cl += bt
                    pos += 1
                    if bt != 0xFF:
                        break
            db.extend(b[pos : pos + cl])
            pos += cl
            if pos >= tpos:
                break
            opos = b[pos] + (b[pos + 1] << 8)
            pos += 2
            if cm == 0x13:
                while True:
                    bt = b[pos]
                    cm += bt
                    pos += 1
                    if bt != 0xFF:
                        break
            dpos = len(db)
            dopos = dpos - opos
            if cm > opos:
                pattern = db[dopos:dpos]
                if not pattern:
                    break
                while len(pattern) < cm:
                    pattern.extend(pattern)
                db.extend(pattern[:cm])
            else:
                db.extend(db[dopos : dopos + cm])
    except (IndexError, ValueError, struct.error):
        pass
    return bytes(db)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAGIC = b"Sb@*"

TAG_NAMES = {
    (0x4B, 0x01): "LZ4pal32",
    (0x48, 0x01): "BGR565A",
    (0x49, 0x01): "BGR565",
    (0x09, 0x00): "JPG",
    (0x03, 0x00): "GIF",
}

import contextlib
import logging
import os
import struct
import sys
from typing import List, Optional

from PyQt6.QtCore import QRect, Qt, QTime, QTimer
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# 1. CORE UTILITIES & DECOMPRESSOR
# ==============================================================================


def vb_get_4b_be(b: bytes, pos: int) -> int:
    if pos < 0 or pos + 3 >= len(b):
        return -1
    return b[pos] + (b[pos + 1] << 8) + (b[pos + 2] << 16) + (b[pos + 3] << 24)


def vb_get_4b_le(b: bytes, pos: int) -> int:
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
    if pos < 0 or pos + 2 >= len(b):
        return -1
    return b[pos] + (b[pos + 1] << 8) + (b[pos + 2] << 16)


def decompress_lz4_vb(b: bytes) -> bytes:
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
    # Malformed input is expected for proprietary H26 streams; we
    # silently truncate to whatever was decoded so far rather than
    # crashing the analyzer. Logging at DEBUG keeps it inspectable
    # without spamming the user's stderr.
    except (IndexError, ValueError, struct.error) as exc:
        logging.debug("LZ4 decode truncated at pos=%d: %s", pos, exc)
    return bytes(db)


def generate_hex_dump(data: bytes, limit: int = 8192) -> str:
    """Generates a professional hex dump string from raw bytes (limited to prevent UI freezing)"""
    if not data:
        return "No binary data available."
    dump = []
    size = min(len(data), limit)
    for i in range(0, size, 16):
        chunk = data[i : i + 16]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
        dump.append(f"{i:08X}  {hex_str:<47}  |{ascii_str}|")

    if len(data) > limit:
        dump.append(f"\n... (Dump truncated for performance. Total size: {len(data)} bytes) ...")
    return "\n".join(dump)


# ==============================================================================
# 2. WATCHFACE STRUCTURE & DECODER ENGINE
# ==============================================================================


class BlockType:
    Unknown = -1
    Header = 1
    LZ4pal32 = 2
    LZ4raw565 = 3
    LZ4raw565a = 4
    JPG = 5
    GIF = 6
    Unk = 7
    UITable = 8


class BlockInfo:
    def __init__(self):
        self.b_type = BlockType.Unknown
        self.base_offset = 0
        self.internal_offset = -1
        self.raw = b""
        self.raw_unpacked = b""
        self.qimage: Optional[QImage] = None


class UIItem:
    def __init__(self, index: int):
        self.index = index
        self.header_raw = b""
        self.header_values: List[int] = []
        self.item_type = 0
        self.x = 0
        self.y = 0
        self.data_values: List[int] = []
        self.frame_indices: List[int] = []
        self.pointer_offsets: List[int] = []
        self.system_screens: List[str] = []  # populated for Type 37
        self.tag: tuple = ()  # populated for unknown block tags


class H26WatchfaceAnalyzer:
    def __init__(self):
        self.file_path = ""
        self.raw_bytes = b""
        self.blocks: List[BlockInfo] = []
        self.unknown_blocks: List[BlockInfo] = []  # blocks with tags not yet mapped
        self.ui_items: List[UIItem] = []
        self.l3 = 0
        self.l4 = 0
        self.wf_name = ""
        self.preview_offset = 0
        self.wf_name_offset = 0

    def _read_wf_name(self, b: bytes) -> str:
        """Decode the watchface name string living at offset 0x17.

        Per the H26 spec the wf name is a NUL-terminated ASCII string
        stored in the trailing block. We read it defensively: bounded by
        the next structural offset (the graphical-block area starts at
        ``self.preview_offset``) so we never cross into image data.
        """
        start = self.wf_name_offset
        if start < 0 or start >= len(b):
            return ""
        end = self.preview_offset if self.preview_offset > start else len(b)
        raw = b[start:end]
        nul = raw.find(b"\x00")
        if nul >= 0:
            raw = raw[:nul]
        with contextlib.suppress(UnicodeDecodeError):
            return raw.decode("utf-8", errors="strict")
        return raw.decode("utf-8", errors="replace")

    def load_file(self, file_path: str) -> bool:
        self.file_path = file_path
        with open(file_path, "rb") as f:
            self.raw_bytes = f.read()

        b = self.raw_bytes
        if len(b) < 20:
            return False

        # Magic Header Check
        # Per the H26 spec, a valid H26 watchface always begins with the
        # 4-byte signature 0x53 0x62 0x40 0x2A (ASCII: "Sb@*").
        if not (b[0] == 0x53 and b[1] == 0x62 and b[2] == 0x40 and b[3] == 0x2A):
            return False

        self.blocks.clear()
        self.ui_items.clear()

        l2 = vb_get_4b_le(b, 0x1C)
        self.l3 = vb_get_4b_le(b, 0x14)
        self.l4 = self.l3 + vb_get_4b_le(b, 0x18)

        # Per the H26 spec, the main header carries:
        #   0x00..0x03  magic "Sb@*"  (0x53 0x62 0x40 0x2A)
        #   0x0C..0x0F  preview-block offset
        #   0x14..0x17  "block with internal addressing" offset (l3)
        #   0x18..0x1B  "block with internal addressing" length
        #   0x1C..0x1F  UI Table offset                  (l2)
        # The watchface name is a string living in the trailing block
        # at offset 0x17 (terminated by a NUL or by EOF).
        self.preview_offset = vb_get_4b_le(b, 0x0C)
        self.wf_name_offset = 0x17
        self.wf_name = self._read_wf_name(b)

        tpos = min(len(b) - 1, l2)
        pos = vb_get_4b_le(b, 0x0C)

        header_block = BlockInfo()
        header_block.base_offset = 0
        header_block.raw = b[:pos]
        header_block.b_type = BlockType.Header
        self.blocks.append(header_block)

        while pos < tpos:
            if pos + 1 >= len(b):
                break
            b1, b2 = b[pos], b[pos + 1]

            bi = BlockInfo()
            bi.base_offset = pos
            bi.internal_offset = (pos - self.l3) if (self.l3 <= pos <= self.l4) else -1

            l1 = 0
            if b1 == 0x4B and b2 == 0x01:
                bi.b_type = BlockType.LZ4pal32
                l1 = vb_get_4b_be(b, pos + 8) + 0x10
            elif b1 == 0x48 and b2 == 0x01:
                bi.b_type = BlockType.LZ4raw565a
                l1 = vb_get_4b_be(b, pos + 8) + 0x10
            elif b1 == 0x49 and b2 == 0x01:
                bi.b_type = BlockType.LZ4raw565
                l1 = vb_get_4b_be(b, pos + 8) + 0x10
            elif b1 == 0x09 and b2 == 0x00:
                bi.b_type = BlockType.JPG
                l1 = vb_get_3b_be(b, pos + 2) + 0x10
            elif b1 == 0x34 and b2 == 0x01:
                bi.b_type = BlockType.Unk
                l1 = vb_get_3b_be(b, pos + 2) + 0x08
            elif b1 == 0x03 and b2 == 0x00:
                bi.b_type = BlockType.GIF
                l1 = vb_get_3b_be(b, pos + 2) + 0x10
            else:
                # Unknown block tag — record it instead of silently
                # dropping it. Researchers need to see these to crack
                # new block types.
                bi.b_type = BlockType.Unk
                bi.tag = (b1, b2)
                # Be conservative: stop the scan if we hit too much
                # unknown data, otherwise we'd loop forever on garbage.
                if pos + 2 >= len(b):
                    break
                guess = vb_get_3b_be(b, pos + 2) + 0x10
                l1 = guess if 0x10 < guess < len(b) - pos else 1
                if pos + l1 > len(b):
                    break
                bi.raw = b[pos : pos + l1]
                self.unknown_blocks.append(bi)
                pos += l1
                continue

            if pos + l1 > len(b):
                break

            bi.raw = b[pos : pos + l1]
            bi.qimage = self._convert_block_to_image(bi.raw)

            if (
                bi.b_type in [BlockType.LZ4pal32, BlockType.LZ4raw565a, BlockType.LZ4raw565]
                and len(bi.raw) > 16
            ):
                bi.raw_unpacked = decompress_lz4_vb(bi.raw[0x10:])

            self.blocks.append(bi)
            pos += l1

        if l2 < len(b) - 1:
            ui_table_raw = b[l2:]
            bi_ui = BlockInfo()
            bi_ui.base_offset = l2
            bi_ui.raw = ui_table_raw
            bi_ui.b_type = BlockType.UITable
            self.blocks.append(bi_ui)
            self._parse_ui_table_fixed(ui_table_raw)

        return True

    def get_image_by_offset(self, target_offset: int) -> Optional[QImage]:
        for block in self.blocks:
            if block.base_offset == target_offset:
                return block.qimage
        return None

    def _convert_block_to_image(self, b: bytes) -> Optional[QImage]:
        if len(b) < 0x11:
            return None
        b1, b2 = b[0], b[1]
        size_val = vb_get_3b_be(b, 5)
        w = size_val >> 12
        h = size_val & 0xFFF

        if w <= 0 or h <= 0 or w > 1000 or h > 1000:
            return None
        payload = b[0x10:]

        def qRgb(r, g, b_col, a=255):
            return QColor(r, g, b_col, a).rgba()

        if b1 == 0x4B and b2 == 0x01:
            unpacked = decompress_lz4_vb(payload)
            if len(unpacked) <= 0x400:
                return None
            colors = [
                qRgb(unpacked[i + 2], unpacked[i + 1], unpacked[i], unpacked[i + 3])
                for i in range(0, 0x400, 4)
            ]
            img = QImage(w, h, QImage.Format.Format_ARGB32)
            idx = 0x400
            for y in range(h):
                for x in range(w):
                    if idx < len(unpacked) and unpacked[idx] < len(colors):
                        img.setPixel(x, y, colors[unpacked[idx]])
                    idx += 1
            return img

        elif b1 == 0x48 and b2 == 0x01:
            unpacked = decompress_lz4_vb(payload)
            img = QImage(w, h, QImage.Format.Format_ARGB32)
            idx = 0
            for y in range(h):
                for x in range(w):
                    if idx + 2 < len(unpacked):
                        c565 = (unpacked[idx + 1] << 8) | unpacked[idx]
                        alpha = unpacked[idx + 2]
                        r = ((c565 & 0xF800) >> 11) * 255 // 31
                        g = ((c565 & 0x07E0) >> 5) * 255 // 63
                        b_col = (c565 & 0x001F) * 255 // 31
                        img.setPixel(x, y, qRgb(r, g, b_col, alpha))
                        idx += 3
            return img

        elif b1 == 0x49 and b2 == 0x01:
            unpacked = decompress_lz4_vb(payload)
            img = QImage(w, h, QImage.Format.Format_RGB32)
            idx = 0
            for y in range(h):
                for x in range(w):
                    if idx + 1 < len(unpacked):
                        c565 = (unpacked[idx + 1] << 8) | unpacked[idx]
                        r = ((c565 & 0xF800) >> 11) * 255 // 31
                        g = ((c565 & 0x07E0) >> 5) * 255 // 63
                        b_col = (c565 & 0x001F) * 255 // 31
                        img.setPixel(x, y, qRgb(r, g, b_col, 255))
                        idx += 2
            return img

        elif b1 == 0x09 and b2 == 0x00:
            img = QImage()
            img.loadFromData(payload)
            return img
        return None

    def _parse_ui_table_fixed(self, b: bytes):
        pos = 0
        tpos = len(b)
        ui_index = 0

        while pos < tpos:
            if pos + 20 > tpos:
                break

            uii = UIItem(ui_index)
            uii.header_raw = b[pos : pos + 20]
            uii.header_values = [
                vb_get_4b_le(b, pos),
                vb_get_4b_le(b, pos + 4),
                vb_get_4b_le(b, pos + 8),
                vb_get_4b_signed_le(b, pos + 12),
                vb_get_4b_signed_le(b, pos + 16),
            ]

            t_type = uii.header_values[0]
            uii.item_type = t_type
            uii.x = uii.header_values[3]
            uii.y = uii.header_values[4]

            l1 = 20
            try:
                if t_type == 0:
                    l2 = uii.header_values[1]
                    if l2 in [0x8C, 0x8D]:
                        pos2 = pos + 20
                        loops = vb_get_4b_le(b, pos2)
                        pos2 += 4
                        for _ in range(loops):
                            l3 = vb_get_4b_le(b, pos2)
                            pos2 += 4 + (l3 * 4)
                        l1 = pos2 - pos
                    elif l2 == 0x34:
                        pos2 = pos + 20
                        loops = vb_get_4b_le(b, pos2)
                        pos2 += 8 + (loops * 8)
                        l1 = pos2 - pos
                    elif l2 in [0x0B, 0, 0x11, 0x17, 0x32, 0x28]:
                        pos2 = pos + 20
                        loops = vb_get_4b_le(b, pos2)
                        pos2 += 4 + (loops * 8)
                        l1 = pos2 - pos
                    else:
                        l1 = tpos - pos

                elif t_type in [1, 2, 3, 5, 6, 0x18, 0x56]:
                    count = vb_get_4b_le(b, pos + 20)
                    l1 = 24 + (count * 8)
                    pos2 = pos + 24
                    for _ in range(count):
                        img_offset = vb_get_4b_le(b, pos2)
                        uii.frame_indices.append(img_offset)
                        uii.pointer_offsets.append(pos2)
                        pos2 += 8

                elif t_type == 0x0F:
                    count = vb_get_4b_le(b, pos + 20)
                    l1 = 24 + (count * 16)
                    pos2 = pos + 24
                    for _ in range(count):
                        pivot_x = vb_get_4b_le(b, pos2)
                        pivot_y = vb_get_4b_le(b, pos2 + 4)
                        img_offset = vb_get_4b_le(b, pos2 + 8)
                        uii.data_values.extend([pivot_x, pivot_y])
                        uii.frame_indices.append(img_offset)
                        uii.pointer_offsets.append(pos2 + 8)
                        pos2 += 16

                elif t_type == 0x14:
                    h1 = uii.header_values[1]
                    if h1 in [0x34, 0x3B]:
                        # Standard animation: header (3*4=12) + 4b X + 4b Y
                        # + 4b counter + records*8  →  28 + n*8
                        count = vb_get_4b_le(b, pos + 24)
                        l1 = 28 + (count * 8)
                        pos2 = pos + 28
                    elif h1 == 0x70:
                        # Extended animation: adds 2 unknown 4-byte words
                        # before X/Y → counter is at pos+28 instead of
                        # pos+24. Each frame record is still 8 bytes
                        # (offset + length) per the H26 spec.
                        count = vb_get_4b_le(b, pos + 28)
                        l1 = 32 + (count * 8)
                        pos2 = pos + 32
                    else:
                        # Fallback / unknown animation variant
                        count = vb_get_4b_le(b, pos + 20)
                        l1 = 24 + (count * 8)
                        pos2 = pos + 24

                    for _ in range(count):
                        img_offset = vb_get_4b_le(b, pos2)
                        uii.frame_indices.append(img_offset)
                        uii.pointer_offsets.append(pos2)
                        pos2 += 8

                elif t_type == 0x37:
                    # Per the H26 spec, Type 37 ("button" / system-screen
                    # reference) has extended bytes:
                    #   4b  unknown            (always 3 in observed samples)
                    #   4b  Width
                    #   4b  Height
                    #   30b NUL-terminated strings identifying which
                    #        system screens this button can jump to
                    #        (WeatherScreen, CompassScreen,
                    #         StepDetailScreen, HRScreen, ...).
                    # The original parser only consumed l1 = 0x3E; we
                    # now actually extract the fields.
                    pos2 = pos + 20
                    if pos2 + 12 > tpos:
                        raise ValueError("Type 37 too short")
                    uii.data_values.extend(
                        [
                            vb_get_4b_le(b, pos2),  # unknown (always 3)
                            vb_get_4b_signed_be(b, pos2 + 4),  # width
                            vb_get_4b_signed_be(b, pos2 + 8),  # height
                        ]
                    )
                    # The 30-byte string tail may contain one or more
                    # NUL-terminated tokens. Split on NULs, drop empties.
                    str_tail = b[pos2 + 12 : pos2 + 12 + 30]
                    for tok in str_tail.split(b"\x00"):
                        if tok:
                            with contextlib.suppress(UnicodeDecodeError):
                                uii.system_screens.append(tok.decode("utf-8", errors="strict"))
                                continue
                            uii.system_screens.append(tok.decode("utf-8", errors="replace"))
                    l1 = 0x3E

                elif t_type in [0x47, 0x48, 0x4B, 0x4C]:
                    # Per the H26 spec, "angled font" types (47/48/4B/4C)
                    # carry a position-shift vector (dX, dY) applied to
                    # each successive character — this is NOT a frame
                    # rotation. The header counter equals
                    #     frame_count + 2
                    # (the extra 2 slots are dX and dY).
                    counter = vb_get_4b_le(b, pos + 20)
                    count = counter - 2
                    count = max(count, 0)
                    if pos + 32 > tpos:
                        raise ValueError("Angled font header too short")
                    # dX, dY are the first two values in the extended area
                    uii.data_values.extend(
                        [
                            vb_get_4b_signed_be(b, pos + 24),  # dX
                            vb_get_4b_signed_be(b, pos + 28),  # dY
                        ]
                    )
                    l1 = 32 + (count * 8)
                    pos2 = pos + 32
                    for _ in range(count):
                        img_offset = vb_get_4b_le(b, pos2)
                        uii.frame_indices.append(img_offset)
                        uii.pointer_offsets.append(pos2)
                        pos2 += 8

                elif t_type == 0x5B:
                    # Per the H26 spec, Type 5B is a "solid rectangle"
                    # with extended bytes:
                    #   4b Counter (typically the number of color bytes
                    #              that follow, observed = 3)
                    #   4b Width
                    #   4b Height
                    #   3b Color (B, G, R)  -- alpha not used
                    if pos + 32 > tpos:
                        raise ValueError("Type 5B too short")
                    counter = vb_get_4b_le(b, pos + 20)
                    width = vb_get_4b_signed_be(b, pos + 24)
                    height = vb_get_4b_signed_be(b, pos + 28)
                    color_tail = b[pos + 32 : pos + 32 + max(0, counter)]
                    # The spec states 3 bytes B/G/R. Defensively pad if
                    # the counter is unusual.
                    bgr = (
                        color_tail[0] if len(color_tail) > 0 else 0,
                        color_tail[1] if len(color_tail) > 1 else 0,
                        color_tail[2] if len(color_tail) > 2 else 0,
                    )
                    uii.data_values.extend([counter, width, height, *bgr])
                    l1 = 32 + max(0, counter)
                else:
                    l1 = tpos - pos
            except (ValueError, IndexError, struct.error) as exc:
                # Defensive fallback: if a UIItem branch hit a malformed
                # sub-record we don't trust, advance to EOF for this item
                # so the parser keeps going instead of infinite-looping.
                logging.debug("UI item parse at pos=%d: %s", pos, exc)
                l1 = tpos - pos

            if l1 <= 0:
                l1 = 20

            pos += l1
            self.ui_items.append(uii)
            ui_index += 1


# ==============================================================================
# 3. GUI CANVAS WIDGETS
# ==============================================================================


class WatchfaceCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.background_image: Optional[QImage] = None
        self.highlight_rect: Optional[QRect] = None

    def set_preview(self, img: Optional[QImage], rect: Optional[QRect] = None):
        self.background_image = img
        self.highlight_rect = rect
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1E1E1E"))

        if self.background_image:
            x = (self.width() - self.background_image.width()) // 2
            y = (self.height() - self.background_image.height()) // 2
            painter.drawImage(x, y, self.background_image)

            if self.highlight_rect:
                pen = QPen(QColor("#0E639C"), 2, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawRect(
                    x + self.highlight_rect.x(),
                    y + self.highlight_rect.y(),
                    self.highlight_rect.width(),
                    self.highlight_rect.height(),
                )
        else:
            painter.setPen(QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Preview Loaded")


class LiveEmulatorCanvas(QWidget):
    def __init__(self, analyzer: H26WatchfaceAnalyzer):
        super().__init__()
        self.analyzer = analyzer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor("#141414"))

        if not self.analyzer.ui_items:
            painter.setPen(QColor("#666666"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Load Watchface to Emulate")
            return

        main_screen_items = []
        for uii in self.analyzer.ui_items:
            if uii.item_type == 0x00 and len(main_screen_items) > 0:
                break
            main_screen_items.append(uii)

        bg_w, bg_h = 400, 400
        for uii in main_screen_items:
            if uii.item_type == 0x14 and uii.frame_indices:
                img = self.analyzer.get_image_by_offset(uii.frame_indices[0])
                if img:
                    bg_w, bg_h = img.width(), img.height()
                    break

        canvas_x = (self.width() - bg_w) // 2
        canvas_y = (self.height() - bg_h) // 2

        for uii in main_screen_items:
            if uii.item_type == 0x14 and uii.frame_indices:
                bg_img = self.analyzer.get_image_by_offset(uii.frame_indices[0])
                if bg_img:
                    painter.drawImage(canvas_x + uii.x, canvas_y + uii.y, bg_img)

        for uii in main_screen_items:
            if uii.item_type not in [0x00, 0x14, 0x0F] and uii.frame_indices:
                static_img = self.analyzer.get_image_by_offset(uii.frame_indices[0])
                if static_img:
                    align = uii.header_values[2] if len(uii.header_values) > 2 else 0
                    dx, dy = canvas_x + uii.x, canvas_y + uii.y
                    if align == 1:
                        dx -= static_img.width() // 2
                        dy -= static_img.height() // 2
                    elif align == 2:
                        dx -= static_img.width()
                    painter.drawImage(dx, dy, static_img)

        current_time = QTime.currentTime()
        h, m, s, ms = (
            current_time.hour() % 12,
            current_time.minute(),
            current_time.second(),
            current_time.msec(),
        )

        for uii in main_screen_items:
            if uii.item_type == 0x0F and uii.frame_indices:
                hand_type = uii.header_values[1]
                if hand_type == 11:
                    angle = (h + m / 60.0) * 30.0
                elif hand_type == 12:
                    angle = (m + s / 60.0) * 6.0
                elif hand_type == 13:
                    angle = (s + ms / 1000.0) * 6.0
                else:
                    angle = 0.0

                img_offset = uii.frame_indices[0]
                hand_img = self.analyzer.get_image_by_offset(img_offset)
                if not hand_img:
                    continue

                pivot_x, pivot_y = uii.data_values[0], uii.data_values[1]
                abs_cx = canvas_x + uii.x + pivot_x
                abs_cy = canvas_y + uii.y + pivot_y

                painter.save()
                painter.translate(abs_cx, abs_cy)
                painter.rotate(angle)
                painter.drawImage(-pivot_x, -pivot_y, hand_img)
                painter.restore()


# ==============================================================================
# 4. PYQT6 WORKBENCH GUI (OpenLumen H26pro+)
# ==============================================================================


class OpenLumenH26ProPlus(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenLumen H26pro+ (Data Analysis & Extraction Only)")
        self.resize(1300, 800)
        self.analyzer = H26WatchfaceAnalyzer()
        self.apply_professional_theme()
        self._init_ui()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 1. Header Toolbar Area
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        self.btn_open = QPushButton("Open File")
        self.btn_open.setToolTip("Select any file to analyze structure")
        self.btn_open.clicked.connect(self._open_file)
        self.btn_open.setMinimumWidth(120)

        self.btn_extract = QPushButton("Extract Resources")
        self.btn_extract.setToolTip("Extract all valid visual assets and tables")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self._extract_images)
        self.btn_extract.setMinimumWidth(130)

        header_layout.addWidget(self.btn_open)
        header_layout.addWidget(self.btn_extract)
        header_layout.addStretch()
        main_layout.addLayout(header_layout)

        # 2. Main Workspace (Splitter)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # Panel 1: Memory Blocks
        self.tree_blocks = QTreeWidget()
        self.tree_blocks.setHeaderLabels(["Offset", "Type", "Size", "Diagnostic Info"])
        self.tree_blocks.setColumnWidth(0, 110)
        self.tree_blocks.setColumnWidth(1, 140)
        self.tree_blocks.itemSelectionChanged.connect(self._on_block_selected)

        blocks_container = self.create_panel("MEMORY BLOCKS", self.tree_blocks)
        splitter.addWidget(blocks_container)

        # Panel 2: Inspector Tabs (Specs, UI Table, Raw Dump)
        self.tabs_inspector = QTabWidget()

        # Sub-tab: Specs & Logs
        widget_specs = QWidget()
        layout_specs = QVBoxLayout(widget_specs)
        layout_specs.setContentsMargins(5, 5, 5, 5)
        self.lbl_specs = QLabel("Select an element from Memory Blocks to view structure details.")
        self.lbl_specs.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_specs.setStyleSheet("color: #CCCCCC; padding: 10px;")
        self.lbl_specs.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout_specs.addWidget(self.lbl_specs)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(150)
        layout_specs.addWidget(self.create_panel("ACTIVITY LOG", self.txt_log))

        # Sub-tab: UI Table Map
        self.table_ui = QTableWidget()
        self.table_ui.setColumnCount(6)
        self.table_ui.setHorizontalHeaderLabels(
            ["Idx", "Hex", "Element Category", "X", "Y", "Memory Values"]
        )
        self.table_ui.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_ui.itemSelectionChanged.connect(self._on_ui_item_selected)

        # Sub-tab: Hex Dump Viewer
        self.txt_hex_dump = QTextEdit()
        self.txt_hex_dump.setReadOnly(True)
        font = QFont("Consolas", 10)
        self.txt_hex_dump.setFont(font)
        self.txt_hex_dump.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)

        self.tabs_inspector.addTab(widget_specs, "Block Properties")
        self.tabs_inspector.addTab(self.table_ui, "UI Table Decoder")
        self.tabs_inspector.addTab(self.txt_hex_dump, "Hex Dump (Raw Bytes)")

        inspector_container = self.create_panel("DATA INSPECTOR", self.tabs_inspector)
        splitter.addWidget(inspector_container)

        # Panel 3: Visuals
        self.tabs_preview = QTabWidget()
        self.canvas_static = WatchfaceCanvas()
        self.canvas_live = LiveEmulatorCanvas(self.analyzer)

        self.tabs_preview.addTab(self.canvas_static, "Asset View & Highlight")
        self.tabs_preview.addTab(self.canvas_live, "Watch Emulator")

        preview_container = self.create_panel("VISUAL CANVAS", self.tabs_preview)
        splitter.addWidget(preview_container)

        # Layout Sizing
        splitter.setSizes([350, 500, 430])
        main_layout.addWidget(splitter, 1)

        # 3. Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Open a file to begin OpenLumen analysis.")

    def create_panel(self, title_text, content_widget):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl_title = QLabel(title_text)
        lbl_title.setStyleSheet(
            "font-weight: 600; font-size: 10px; color: #9E9E9E; letter-spacing: 1px; padding-left: 2px;"
        )

        layout.addWidget(lbl_title)
        layout.addWidget(content_widget)
        return container

    def _open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open File for Analysis", "", "All Files (*)"
        )
        if not file_path:
            return

        self.status_bar.showMessage(f"Analyzing {os.path.basename(file_path)}...")

        if self.analyzer.load_file(file_path):
            self.status_bar.showMessage(f"Successfully loaded: {os.path.basename(file_path)}")
            self.btn_extract.setEnabled(True)
            self._populate_block_tree()
            self._populate_ui_table()
            self._log_info(
                f"✅ Successfully decoded file headers and located {len(self.analyzer.blocks)} memory blocks."
            )

            bg_img = next((b.qimage for b in self.analyzer.blocks if b.qimage), None)
            self.canvas_static.set_preview(bg_img)
            self.canvas_live.timer.start(16)
        else:
            self.status_bar.showMessage("Error: File signature does not match expected H26 format.")
            self._log_info(
                "❌ Failed magic header check. This file does not appear to be a valid H26 watchface binary."
            )

    def _extract_images(self):
        if not self.analyzer.blocks:
            return
        export_dir = QFileDialog.getExistingDirectory(self, "Select Folder to Extract Assets")
        if not export_dir:
            return

        img_count = 0
        for i, bi in enumerate(self.analyzer.blocks):
            if bi.qimage:
                file_name = os.path.join(
                    export_dir, f"asset_{i:04d}_offset_{bi.base_offset:08X}.png"
                )
                bi.qimage.save(file_name, "PNG")
                img_count += 1
            elif bi.b_type == BlockType.UITable:
                bin_path = os.path.join(export_dir, f"ui_table_offset_{bi.base_offset:08X}.bin")
                with open(bin_path, "wb") as f:
                    f.write(bi.raw)

                txt_path = os.path.join(export_dir, "ui_layout_map.txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(f"--- OPENLUMEN UI TABLE MAP (Offset: 0x{bi.base_offset:08X}) ---\n")
                    for uii in self.analyzer.ui_items:
                        f.write(
                            f"Idx {uii.index:03d} | Type: 0x{uii.item_type:02X} | X: {uii.x:<4} Y: {uii.y:<4}\n"
                        )
                        f.write(
                            f"     Pivots/Params: {uii.data_values} | Image Pointers: {[hex(idx) for idx in uii.frame_indices]}\n"
                        )
                        f.write("-" * 50 + "\n")

        self._log_info(
            f"📥 Export Complete: Saved {img_count} visual assets and UI Table to {export_dir}"
        )
        self.status_bar.showMessage(f"Extraction successful: {img_count} items exported.")

    def _populate_block_tree(self):
        self.tree_blocks.clear()
        type_names = {
            BlockType.Header: "BIN HEADER",
            BlockType.LZ4pal32: "LZ4 Palette (8-bit)",
            BlockType.LZ4raw565a: "LZ4 RGB565+Alpha",
            BlockType.LZ4raw565: "LZ4 RGB565 (Opaque)",
            BlockType.JPG: "JPEG Image Asset",
            BlockType.GIF: "GIF Animation Asset",
            BlockType.UITable: "UI Element Map",
            BlockType.Unk: "Unknown Data Block",
        }
        for bi in self.analyzer.blocks:
            offset_str = f"0x{bi.base_offset:08X}"
            info_str = (
                f"{bi.qimage.width()}x{bi.qimage.height()} px"
                if bi.qimage
                else f"Size: {len(bi.raw_unpacked)} B"
                if bi.raw_unpacked
                else ""
            )
            item = QTreeWidgetItem(
                [offset_str, type_names.get(bi.b_type, "Unmapped"), f"{len(bi.raw)} B", info_str]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, bi)
            self.tree_blocks.addTopLevelItem(item)

    def _populate_ui_table(self):
        self.table_ui.setRowCount(0)

        def get_element_name(item_type: int):
            if item_type == 0x00:
                return "⚙️ Root Master Layout"
            if item_type == 0x14:
                return "🖼️ Background/Layer"
            if item_type == 0x0F:
                return "⏱️ Analog Rotational Hand"
            if item_type in [1, 2, 3, 5, 6, 0x18, 0x56]:
                return "🔢 Digital String / Value"
            if item_type in [0x47, 0x48, 0x4B, 0x4C]:
                return "🔠 Secondary Font Map"
            if item_type == 0x37:
                return "👆 Touch Region Shortcut"
            if item_type == 0x5B:
                return "🛠️ System Config Marker"
            return "❓ Unknown Subsystem"

        for uii in self.analyzer.ui_items:
            row = self.table_ui.rowCount()
            self.table_ui.insertRow(row)

            idx_item = QTableWidgetItem(str(uii.index))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_ui.setItem(row, 0, idx_item)

            type_item = QTableWidgetItem(f"0x{uii.item_type:02X}")
            type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_ui.setItem(row, 1, type_item)

            self.table_ui.setItem(row, 2, QTableWidgetItem(get_element_name(uii.item_type)))
            self.table_ui.setItem(row, 3, QTableWidgetItem(str(uii.x)))
            self.table_ui.setItem(row, 4, QTableWidgetItem(str(uii.y)))

            pivots = str(uii.data_values) if uii.data_values else ""
            frames = str([f"0x{f:08X}" for f in uii.frame_indices]) if uii.frame_indices else ""
            self.table_ui.setItem(row, 5, QTableWidgetItem(f"{pivots} {frames}"))

    def _on_block_selected(self):
        selected = self.tree_blocks.selectedItems()
        if not selected:
            return
        bi: BlockInfo = selected[0].data(0, Qt.ItemDataRole.UserRole)

        # 1. Canvas View
        if bi.qimage:
            self.canvas_static.set_preview(bi.qimage)
        else:
            self.canvas_static.set_preview(None)

        # 2. Block Properties Panel
        type_names = {
            BlockType.Header: "Root Binary Header",
            BlockType.LZ4pal32: "LZ4 Indexed Palette (256 Colors)",
            BlockType.LZ4raw565a: "LZ4 RGB565 + Alpha Channel",
            BlockType.LZ4raw565: "LZ4 RGB565",
            BlockType.JPG: "Standard JPEG Graphic",
            BlockType.GIF: "Standard GIF Graphic",
            BlockType.UITable: "Layout/UI Object Table",
            BlockType.Unk: "Unidentified Structure",
        }

        t_name = type_names.get(bi.b_type, "Unknown Type")
        dims = (
            f"{bi.qimage.width()} x {bi.qimage.height()} px" if bi.qimage else "Not a visual asset"
        )
        raw_size = len(bi.raw)

        specs_html = f"""
        <table width='100%' style='line-height: 1.8; color: #CCCCCC;'>
            <tr><td width='160'><b>Global Offset:</b></td><td style='color:#FFFFFF;'>0x{bi.base_offset:08X}</td></tr>
            <tr><td><b>Data Format:</b></td><td style='color: #0E639C;'>{t_name}</td></tr>
            <tr><td><b>Pixel Dimensions:</b></td><td style='color:#FFFFFF;'>{dims}</td></tr>
            <tr><td><b>Binary Footprint:</b></td><td style='color:#FFFFFF;'>{raw_size} bytes</td></tr>
        </table>
        """
        self.lbl_specs.setText(specs_html)

        # 3. Hex Dump Panel
        self.txt_hex_dump.setPlainText(generate_hex_dump(bi.raw))

        self._log_info(f"Focused Block at Offset: 0x{bi.base_offset:08X} | Type: {t_name}")

    def _on_ui_item_selected(self):
        selected = self.table_ui.selectionModel().selectedRows()
        if not selected:
            return
        uii = self.analyzer.ui_items[selected[0].row()]
        self._log_info(
            f"Targeting UI Element #{uii.index} | Component Type: 0x{uii.item_type:02X} @ Pos: ({uii.x}, {uii.y})"
        )

        bg = self.canvas_static.background_image
        if uii.item_type == 0x14 and uii.frame_indices:
            bg = self.analyzer.get_image_by_offset(uii.frame_indices[0])
            self.canvas_static.set_preview(bg, QRect(uii.x, uii.y, 40, 40))
        else:
            self.canvas_static.set_preview(bg, QRect(uii.x, uii.y, 40, 40))

    def _log_info(self, text: str):
        self.txt_log.append(text)
        scrollbar = self.txt_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def apply_professional_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { 
                background-color: #1E1E1E; 
                color: #CCCCCC; 
                font-family: 'Segoe UI', 'San Francisco', sans-serif; 
                font-size: 12px;
            }
            
            QPushButton { 
                background-color: #333333; 
                border: 1px solid #444444; 
                border-radius: 4px; 
                padding: 6px 12px; 
            }
            QPushButton:hover { background-color: #404040; border-color: #555555; }
            QPushButton:pressed { background-color: #2D2D2D; }
            QPushButton:disabled { background-color: #252525; color: #555555; border: 1px solid #333333; }
            
            QTreeWidget, QTextEdit, QTableWidget { 
                background-color: #252526; 
                border: 1px solid #333333; 
                border-radius: 4px; 
                outline: 0; 
            }
            
            QTreeWidget::item:hover { background-color: #2A2D2E; }
            QTreeWidget::item:selected { background-color: #04395E; color: #FFFFFF; }
            
            QTableWidget::item:hover { background-color: #2A2D2E; }
            QTableWidget::item:selected { background-color: #04395E; color: #FFFFFF; }
            
            QTabWidget::pane { border: 1px solid #333333; border-radius: 4px; top: -1px; }
            QTabBar::tab { 
                background: #1E1E1E; 
                color: #969696; 
                padding: 6px 16px; 
                border: 1px solid transparent; 
                border-bottom: 1px solid #333333; 
                margin-right: 2px;
            }
            QTabBar::tab:selected { 
                background: #252526; 
                color: #FFFFFF; 
                border: 1px solid #333333;
                border-bottom: 1px solid #252526;
                border-top: 2px solid #0E639C;
            }
            QTabBar::tab:hover:!selected { color: #CCCCCC; }
            
            QHeaderView::section { 
                background-color: #252526; 
                color: #CCCCCC; 
                padding: 4px; 
                border: none; 
                border-bottom: 1px solid #333333; 
                border-right: 1px solid #333333; 
            }
            
            QSplitter::handle { background-color: #333333; margin: 2px; }
            
            QStatusBar { 
                background: #007ACC; 
                color: #FFFFFF; 
                padding-left: 8px; 
            }
        """)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = OpenLumenH26ProPlus()
    window.show()
    sys.exit(app.exec())

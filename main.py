import contextlib
import os
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

from h26.decoder import (
    TAG_BGR565,
    TAG_BGR565A,
    TAG_GIF,
    TAG_JPG,
    TAG_LZ4PAL32,
    decode_block_to_rgba,
    scan_blocks,
)
from h26.utils import (
    decompress_lz4_vb,  # noqa: F401 — used by tests
    generate_hex_dump,
    vb_get_3b_be,  # noqa: F401 — used by tests
    vb_get_4b_signed_be,  # noqa: F401 — backward compat alias
    vb_get_4b_signed_le,  # noqa: F401 — backward compat alias
)

# ==============================================================================
# 1. CORE UTILITIES & DECOMPRESSOR
# ==============================================================================
# Byte readers and LZ4 decompression are now imported from h26.utils
# See h26/utils.py for the implementations


# generate_hex_dump is now imported from h26.utils

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
        if not (b[0] == 0x53 and b[1] == 0x62 and b[2] == 0x40 and b[3] == 0x2A):
            return False

        self.blocks.clear()
        self.ui_items.clear()

        # Use shared decoder to scan blocks and parse UI table
        result = scan_blocks(b)
        self.l2 = result["l2"]
        self.l3 = result["l3"]
        self.l4 = result["l3"] + result["l3_len"]
        self.preview_offset = result["preview_offset"]
        self.wf_name_offset = 0x17
        self.wf_name = self._read_wf_name(b)

        # Header block (raw bytes before first graphical block)
        pos = self.preview_offset
        header_block = BlockInfo()
        header_block.base_offset = 0
        header_block.raw = b[:pos]
        header_block.b_type = BlockType.Header
        self.blocks.append(header_block)

        # Convert decoder BlockInfo → GUI BlockInfo
        for dec_block in result["blocks"]:
            bi = BlockInfo()
            bi.base_offset = dec_block.offset
            bi.raw = dec_block.raw
            # Map tag to BlockType
            tag = dec_block.tag
            if tag == TAG_LZ4PAL32:
                bi.b_type = BlockType.LZ4pal32
            elif tag == TAG_BGR565A:
                bi.b_type = BlockType.LZ4raw565a
            elif tag == TAG_BGR565:
                bi.b_type = BlockType.LZ4raw565
            elif tag == TAG_JPG:
                bi.b_type = BlockType.JPG
            elif tag == TAG_GIF:
                bi.b_type = BlockType.GIF
            else:
                bi.b_type = BlockType.Unknown
                self.unknown_blocks.append(bi)
                continue
            # Convert to QImage
            bi.qimage = self._convert_block_to_image(bi.raw)
            self.blocks.append(bi)

        # UI Table block
        ui_table_raw = b[self.l2 :]
        bi_ui = BlockInfo()
        bi_ui.base_offset = self.l2
        bi_ui.raw = ui_table_raw
        bi_ui.b_type = BlockType.UITable
        self.blocks.append(bi_ui)

        # Convert decoder UIItemInfo → GUI UIItem
        for dec_item in result["ui_items"]:
            uii = UIItem(dec_item.index)
            uii.item_type = dec_item.type
            uii.x = dec_item.x
            uii.y = dec_item.y
            uii.header_raw = b[
                self.l2 + dec_item.header_offset : self.l2 + dec_item.header_offset + 20
            ]
            uii.header_values = [
                dec_item.type,
                dec_item.sub_type,
                0,  # align (not stored in decoder)
                dec_item.x,
                dec_item.y,
            ]
            uii.data_values = list(dec_item.data_values)
            uii.frame_indices = list(dec_item.frame_indices)
            uii.system_screens = list(dec_item.system_screens)
            self.ui_items.append(uii)

        return True

    def get_image_by_offset(self, target_offset: int) -> Optional[QImage]:
        for block in self.blocks:
            if block.base_offset == target_offset:
                return block.qimage
        return None

    def serialize(self) -> bytes:
        """Re-emit the parsed .bin file as bytes.

        Concatenates the raw bytes of every block (in original order:
        header, graphical blocks, UI table) and any unknown blocks that
        were captured during the scan. This is a **byte-perfect
        round-trip** for files whose structure the parser fully
        understands; for files with unknown blocks the bytes are
        preserved too, so the output is always structurally equivalent
        to the input even if the parser didn't decode every field.

        Use this to:
        * regression-test the parser (parse → serialize → compare)
        * build the foundation for a future compiler/repacker
        """
        parts: list[bytes] = []
        # The first block is always the header (BlockType.Header),
        # followed by graphical blocks in the order the scan found
        # them, with the UI table at the end.
        for block in self.blocks:
            parts.append(block.raw)
        # Unknown blocks were captured separately during the scan
        # because their tag didn't match any known block type. We
        # append them after the main blocks to preserve them in the
        # serialized output even though their position may not be
        # exact (the round-trip is structural, not positional).
        for block in self.unknown_blocks:
            parts.append(block.raw)
        return b"".join(parts)

    def _convert_block_to_image(self, b: bytes) -> Optional[QImage]:
        """Convert a graphical block to QImage using shared decoder."""
        result = decode_block_to_rgba(b)
        if result is None:
            # Try JPG fallback (not handled by decode_block_to_rgba)
            if len(b) >= 0x11 and b[0] == 0x09 and b[1] == 0x00:
                payload = b[0x10:]
                img = QImage()
                img.loadFromData(payload)
                return img
            return None
        rgba_bytes, w, h = result
        img = QImage(rgba_bytes, w, h, QImage.Format.Format_ARGB32)
        # QImage does not take ownership of the buffer, so keep a reference
        img._rgba_data = rgba_bytes  # prevent GC
        return img

    # _parse_ui_table_fixed removed — now using scan_blocks() + _parse_ui_table() from h26.decoder


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

        self.btn_export = QPushButton("Export Project")
        self.btn_export.setToolTip("Export watchface as folder with images + project.json")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export_project)
        self.btn_export.setMinimumWidth(130)

        self.btn_replace = QPushButton("Replace Image")
        self.btn_replace.setToolTip("Replace selected block image with a new file")
        self.btn_replace.setEnabled(False)
        self.btn_replace.clicked.connect(self._replace_image)
        self.btn_replace.setMinimumWidth(130)

        header_layout.addWidget(self.btn_open)
        header_layout.addWidget(self.btn_extract)
        header_layout.addWidget(self.btn_export)
        header_layout.addWidget(self.btn_replace)
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
            self.btn_export.setEnabled(True)
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

    def _export_project(self):
        """Export watchface as folder with images + project.json."""
        if not self.analyzer.blocks:
            return

        export_dir = QFileDialog.getExistingDirectory(self, "Select Folder to Export Project")
        if not export_dir:
            return

        # Use h26.decoder to scan the binary
        from h26.decoder import scan_blocks

        b = self.analyzer.raw_bytes
        scan = scan_blocks(b)

        # Build block offset → index map
        block_offset_map = {}
        for i, blk in enumerate(scan["blocks"]):
            block_offset_map[blk.offset] = i

        # Export images
        images_dir = os.path.join(export_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        img_count = 0
        for i, bi in enumerate(self.analyzer.blocks):
            if bi.qimage:
                fname = f"block_{i:03d}.png"
                bi.qimage.save(os.path.join(images_dir, fname), "PNG")
                img_count += 1

        # Build UI items with image references
        ui_items_export = []
        for item in scan["ui_items"]:
            export_item = {
                "type": f"0x{item.type:02X}",
                "sub_type": f"0x{item.sub_type:02X}",
                "x": item.x,
                "y": item.y,
            }

            if item.frame_indices:
                export_item["images"] = []
                for frame_off in item.frame_indices:
                    if frame_off in block_offset_map:
                        blk_idx = block_offset_map[frame_off]
                        export_item["images"].append(f"block_{blk_idx:03d}.png")

            if item.pivot:
                export_item["pivot"] = item.pivot

            ui_items_export.append(export_item)

        # Build project structure
        import json

        project = {
            "name": os.path.splitext(os.path.basename(self.analyzer.file_path))[0],
            "source_file": os.path.basename(self.analyzer.file_path),
            "canvas_width": 480,
            "canvas_height": 480,
            "blocks": [blk.to_dict() for blk in scan["blocks"]],
            "ui_table": ui_items_export,
        }

        # Write project.json
        project_path = os.path.join(export_dir, "project.json")
        with open(project_path, "w", encoding="utf-8") as f:
            json.dump(project, f, indent=2, ensure_ascii=False)

        self._log_info(
            f"📥 Project Export Complete: {img_count} images + project.json to {export_dir}"
        )
        self.status_bar.showMessage(f"Project exported: {export_dir}")

    def _replace_image(self):
        """Replace the selected block's image with a new file."""
        selected = self.tree_blocks.selectedItems()
        if not selected:
            return

        bi: BlockInfo = selected[0].data(0, Qt.ItemDataRole.UserRole)
        if not bi.qimage:
            return

        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Replacement Image",
            "",
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)",
        )
        if not file_path:
            return

        # Load new image
        new_img = QImage(file_path)
        if new_img.isNull():
            self._log_info(f"❌ Failed to load image: {file_path}")
            return

        # Convert to ARGB32 if needed
        if new_img.format() != QImage.Format.Format_ARGB32:
            new_img = new_img.convertToFormat(QImage.Format.Format_ARGB32)

        # Update the block
        old_w, old_h = bi.qimage.width(), bi.qimage.height()
        new_w, new_h = new_img.width(), new_img.height()

        # Resize if dimensions don't match
        if old_w != new_w or old_h != new_h:
            self._log_info(f"⚠️ Resizing image from {new_w}x{new_h} to {old_w}x{old_h}")
            new_img = new_img.scaled(
                old_w,
                old_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        bi.qimage = new_img

        # Re-encode to LZ4pal32 format
        from h26.image_codec import build_lz4pal32_block

        # Convert QImage to RGBA bytes
        ptr = new_img.bits()
        ptr.setsize(new_img.sizeInBytes())
        rgba_bytes = bytes(ptr)

        # Build new block data
        new_raw = build_lz4pal32_block(rgba_bytes, new_img.width(), new_img.height())
        bi.raw = new_raw

        # Update the view
        self.canvas_static.set_preview(bi.qimage)
        self._populate_block_tree()

        self._log_info(
            f"✅ Replaced block at 0x{bi.base_offset:08X} with image from {os.path.basename(file_path)}"
        )
        self.status_bar.showMessage(f"Image replaced at block 0x{bi.base_offset:08X}")

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

        # Enable replace button only for image blocks
        self.btn_replace.setEnabled(bi.qimage is not None)

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

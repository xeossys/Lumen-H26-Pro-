# ⌚ OpenLumen H26pro+ 
> **An Open-Source Reverse-Engineering & Modding Studio for H26 Smartwatches.**

![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)
![PyQt6](https://img.shields.io/badge/PyQt-6-green.svg)
![Contributions](https://img.shields.io/badge/contributions-welcome-orange.svg)
![License](https://img.shields.io/badge/license-MIT-purple.svg)

**OpenLumen H26pro+** is a pure-Python reverse-engineering and modding suite built for smartwatch UI developers. By translating proprietary H26 binary structures into editable data, OpenLumen bridges the gap between raw hexadecimal code and visual design.

Currently, OpenLumen functions as a highly advanced **Decompiler, Analyzer, and Emulator**. You can unpack `.bin` files, extract raw assets, decode UI layouts, and emulate analog clock behaviors. 

⚠️ **Help Wanted:** We are currently building the **Compiler & Repacker** phase of this project and are actively looking for Python developers and reverse-engineers to help us crack the LZ4 encoding injection! (See the [Help Wanted / Roadmap](#-help-wanted--roadmap-the-compiler) section below).

---

## 🙏 Credits & Acknowledgments

**Full Credit:**  
This Python version was ported and is fully based on the watchface analyzer and all binary data provided by **[@vx_vxsw](https://t.me/vx_vxsw)** on Telegram. All credit for the original reverse-engineering research, structural analysis, and data mapping goes entirely to him!

---

## ✨ Current Features (v1.0)

* **Full Decompilation & Extraction:** Automatically unpacks `.bin` files, maps memory offsets and UI tables, and extracts all valid image layers (PNG, JPG, GIF) to your local drive.
* **Zero-Dependency LZ4 Decoder:** Features built-in, pure-Python LZ4 decompression. No C-compilers, build tools, or external binary dependencies required.
* **Live Watchface Emulator:** A real-time rendering canvas that recreates the watchface interface, complete with active, system-clock-driven analog hand rotations. *(Note: Digital font emulation is WIP).*
* **UI Table Decoder:** Translates raw hex into a readable map showing Master Layouts, Analog Hands, Font Maps, Touch Regions, and their absolute (X, Y) screen coordinates.
* **Hex Dump Diagnostics:** Safely view raw byte data block-by-block without freezing the UI.
* **XEOS Studio Pro UI:** A sleek, dark-mode workspace built with PyQt6 featuring responsive splitters, property inspectors, and realtime diagnostic logging.

---

## 🛑 HELP WANTED / ROADMAP (The Compiler)

While the decompiler works flawlessly, **the Repacker/Compiler is not yet built.** 

We are calling all Python developers, hardware hackers, and LZ4 compression experts to help us build the encoder. To achieve a 100% safe modding pipeline, we need to implement a **"Safe Slot" Injection Algorithm**.

**What needs to be built:**
1. **LZ4 RGB565 / Palette32 Encoder:** A pure-Python encoder that can take a custom `.png`, convert it to the watch's specific 16-bit RGB565 or 8-bit palette format, and compress it using standard LZ4 block compression.
2. **Memory Alignment Logic:** If a newly compressed image is smaller than the original, we need a script to pad the remaining space with `0x00` (Null bytes) to preserve the exact global memory offsets for the rest of the `.bin` file.
3. **Safety Locks:** Logic to block injections if the new asset's binary size exceeds the original memory slot (to prevent soft-bricking).

If you want to contribute, please fork the repository, open a Pull Request, or start a discussion in the Issues tab!

---

## 📐 System Architecture & Parsing Pipeline

```text
  +-----------------------+
  |  Raw H26 .bin File    |
  +-----------+-----------+
              |
              v
  +-----------------------+   Check Magic Header (0x53 0x62 0x40 0x2A)
  |  Magic Header Check   |--> Read UI Table Pointer (L2 at 0x1C)
  +-----------+-----------+    Read Memory Boundaries (L3, L4)
              |
              v
  +-----------------------+   Iterate Memory Chunks from Offset 0x0C
  | Memory Block Scanner  |--> Read Block Headers (2-byte Magic Tags)
  +-----------+-----------+    Decompress LZ4 Payload (Pure Python)
              |
              v
  +-----------------------+   Parse UI Structs at L2 Offset
  |   UI Table Decoder    |--> Extract (X, Y) Coordinates & Element Types
  +-----------+-----------+    Harvest Image Offset Pointers
💾 Supported Memory BlocksCompression / BlockID HeaderDescriptionLZ4 Palette320x4B018-bit Indexed Palette (256 Colors)LZ4 RGB565 + A0x480116-bit RGB565 with Alpha ChannelLZ4 RGB5650x490116-bit RGB565 OpaqueJPEG Graphic0x0900Standard Compressed ImageGIF Graphic0x0300Standard Animated GraphicUI Table Map0x1CUI Layout & Pointers Structure📥 InstallationClone the Repository:Bashgit clone [https://github.com/xeossys/Lumen-H26-Pro-.git](https://github.com/xeossys/Lumen-H26-Pro-.git)
cd Lumen-H26-Pro-
Install Required GUI Library:Bashpip install PyQt6
Launch the Studio:Bashpython openlumen.py

📜 License & AttributionOriginal Research, Data & Watchface Analyzer: @vx_vxswPython Port & Code Implementation: OpenLumen Team (xeossys)License: MIT License

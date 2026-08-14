"""H26 encoder data model.

Defines the in-memory representation of a watchface *project*
(images + a layout tree of UI items) and its JSON serialization.

This is the user-facing abstraction: the GUI builds one of these
and the encoder -- ``h26.encoder.compile`` -- turns it into a
literal binary ``.bin`` file.

A project is deliberately high-level. It does **not** know about
byte offsets or compression; those are the encoder's job. The
decoder side (``main.py``) produces something close to this when it
parses a file, but the two are intentionally decoupled: a project
is what you *author*, a parsed analyzer state is what you *inspect*.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# UIItem type tags (from the H26 spec, section 4)
TYPE_LAYOUT = 0x00
TYPE_FRAME = 0x01
TYPE_FRAME2 = 0x02
TYPE_HAND = 0x0F
TYPE_ANIMATION = 0x14
TYPE_ANGLE_FONT = 0x47
TYPE_BUTTON = 0x37
TYPE_BGR565A = 0x48

# Layout sub-types
SUB_LAYOUT_REGULAR = 0x8C
SUB_LAYOUT_AOD = 0x8D

# Hand sub-types
SUB_HAND_HOUR = 0x0B
SUB_HAND_MINUTE = 0x0C
SUB_HAND_SECOND = 0x0D


# --------------------------------------------------------------------------
# Schema helpers
# --------------------------------------------------------------------------

_REQUIRED = {
    "project": ("name", "canvas_width", "canvas_height", "images", "layout"),
    "image": ("name", "source_path"),
    "layout": ("item_type", "sub_type", "children"),
    "item": ("item_type", "sub_type", "x", "y", "image_name"),
}


class ProjectSchemaError(ValueError):
    """Raised when a project JSON document fails validation."""


def _require(obj: dict, fields: tuple[str, ...], where: str) -> None:
    missing = [f for f in fields if f not in obj]
    if missing:
        raise ProjectSchemaError(f"{where}: missing required field(s): {', '.join(missing)}")


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


@dataclass
class ImageAsset:
    """An image to be baked into the .bin file.

    ``offset_in_bin`` is filled in by the encoder once the block is
    laid out, so the UI table can reference it.
    """

    name: str
    source_path: str = ""
    width: int = 0
    height: int = 0
    offset_in_bin: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> ImageAsset | None:
        _require(d, _REQUIRED["image"], "image")
        asset = cls(
            name=d["name"],
            source_path=d["source_path"],
            width=int(d.get("width", 0)),
            height=int(d.get("height", 0)),
            offset_in_bin=int(d.get("offset_in_bin", 0)),
        )
        return asset


# --------------------------------------------------------------------------
# UI items
# --------------------------------------------------------------------------


@dataclass
class UIItemBase:
    """Shared fields for every UI item (the 5x4-byte header)."""

    item_type: int = TYPE_FRAME
    sub_type: int = 0
    x: int = 0
    y: int = 0
    align: int = 0
    image_name: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("item_type", None)  # item_type is the discriminator
        return d


@dataclass
class FrameItem(UIItemBase):
    """A static image placed at (x, y) -- Type 0x01 / 0x02."""

    item_type: int = TYPE_FRAME


@dataclass
class HandItem(UIItemBase):
    """A clock hand with a rotation pivot -- Type 0x0F."""

    item_type: int = TYPE_HAND
    pivot_x: int = 0
    pivot_y: int = 0


@dataclass
class AnimationItem(UIItemBase):
    """A frame sequence -- Type 0x14.

    Each entry in ``frame_names`` references an ``ImageAsset.name``
    representing one animation frame.
    """

    item_type: int = TYPE_ANIMATION
    frame_names: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["frame_names"] = list(self.frame_names)
        return d


@dataclass
class Layout(UIItemBase):
    """Top-level layout (Type 0x00) referencing the item tree.

    ``children`` are the UI items of this watchface. Together they
    form the single "regular" layout (``sub_type == 0x8C``).
    """

    item_type: int = TYPE_LAYOUT
    sub_type: int = SUB_LAYOUT_REGULAR
    children: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["children"] = [child_to_dict(c) for c in self.children]
        return d


# Item type -> deserialization factory
_ITEM_FACTORIES = {
    TYPE_FRAME: FrameItem,
    TYPE_FRAME2: FrameItem,
    TYPE_HAND: HandItem,
    TYPE_ANIMATION: AnimationItem,
}


def _item_from_dict(d: dict) -> UIItemBase:
    _require(d, ("item_type",), "item")
    item_type = int(d["item_type"])

    # The Layout type is handled specially: its children are nested
    # and it uses a different field set (no x/y/image_name required).
    if item_type == TYPE_LAYOUT:
        layout = Layout(
            sub_type=int(d.get("sub_type", SUB_LAYOUT_REGULAR)),
            x=int(d.get("x", 0)),
            y=int(d.get("y", 0)),
            align=int(d.get("align", 0)),
        )
        layout.children = [child_from_dict(c) for c in d.get("children", [])]
        return layout

    _require(d, _REQUIRED["item"], "item")
    factory = _ITEM_FACTORIES.get(item_type)
    if factory is None:
        raise ProjectSchemaError(
            f"item: unsupported item_type 0x{item_type:02X} in encoder v1 "
            f"(supported: {', '.join(hex(t) for t in sorted(_ITEM_FACTORIES))})"
        )
    kwargs = {
        "sub_type": int(d.get("sub_type", 0)),
        "x": int(d.get("x", 0)),
        "y": int(d.get("y", 0)),
        "align": int(d.get("align", 0)),
        "image_name": str(d.get("image_name", "")),
    }
    if item_type == TYPE_HAND:
        kwargs["pivot_x"] = int(d.get("pivot_x", 0))
        kwargs["pivot_y"] = int(d.get("pivot_y", 0))
    if item_type == TYPE_ANIMATION:
        kwargs["frame_names"] = list(d.get("frame_names", []))
    return factory(**kwargs)


def child_to_dict(item: UIItemBase) -> dict:
    if isinstance(item, Layout):
        d = item.to_dict()
        # to_dict() already includes children; ensure item_type present
        d["item_type"] = item.item_type
        return d
    d = item.to_dict()
    d["item_type"] = item.item_type
    return d


def child_from_dict(d: dict) -> UIItemBase:
    return _item_from_dict(d)


# --------------------------------------------------------------------------
# Project
# --------------------------------------------------------------------------


@dataclass
class Project:
    """A complete watchface description, ready to compile."""

    name: str = "untitled"
    canvas_width: int = 240
    canvas_height: int = 240
    images: list = field(default_factory=list)
    layout: Layout = field(default_factory=Layout)

    #: Optional: a rendered preview (as a PNG/JPG path or raw bytes).
    #: If empty, the encoder renders one from the layout.
    preview_source_path: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Project:
        _require(d, _REQUIRED["project"], "project")
        img_iter = (ImageAsset.from_dict(i) for i in d.get("images", []))
        images = [i for i in img_iter if i is not None]
        layout_obj = _item_from_dict(d["layout"])
        if not isinstance(layout_obj, Layout):
            raise ProjectSchemaError(
                f"project: top-level 'layout' must be item_type "
                f"0x{TYPE_LAYOUT:02X}, got 0x{layout_obj.item_type:02X}"
            )
        return cls(
            name=str(d["name"]),
            canvas_width=int(d.get("canvas_width", 240)),
            canvas_height=int(d.get("canvas_height", 240)),
            images=images,
            layout=layout_obj,
            preview_source_path=str(d.get("preview_source_path", "")),
        )

    @classmethod
    def from_json(cls, text: str) -> Project:
        try:
            d = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProjectSchemaError(f"project: invalid JSON: {exc}") from exc
        if not isinstance(d, dict):
            raise ProjectSchemaError(f"project: expected a JSON object, got {type(d).__name__}")
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "preview_source_path": self.preview_source_path,
            "images": [asdict(i) for i in self.images],
            "layout": child_to_dict(self.layout),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def find_image(self, name: str) -> ImageAsset | None:
        for img in self.images:
            if img.name == name:
                return img
        return None

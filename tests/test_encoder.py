"""
Encoder data-model tests (h26/project.py).

Covers the JSON round-trip and schema validation of the H26
project data model. Run with::

    python3 tests/test_encoder.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from h26.project import (  # noqa: E402
    AnimationItem,
    FrameItem,
    HandItem,
    ImageAsset,
    Layout,
    Project,
    ProjectSchemaError,
)


def _sample_project() -> Project:
    bg = ImageAsset(name="bg", source_path="/tmp/bg.png", width=240, height=240)
    hour = ImageAsset(name="hour_hand", source_path="/tmp/hour.png", width=40, height=120)
    layout = Layout(
        x=0,
        y=0,
        children=[
            FrameItem(x=0, y=0, image_name="bg"),
            HandItem(
                x=120,
                y=120,
                image_name="hour_hand",
                pivot_x=20,
                pivot_y=110,
            ),
        ],
    )
    return Project(name="test", images=[bg, hour], layout=layout)


def test_project_json_roundtrip():
    p = _sample_project()
    dumped = p.to_json()
    # Valid JSON
    json.loads(dumped)
    p2 = Project.from_json(dumped)
    assert p2.name == p.name
    assert p2.canvas_width == p.canvas_width
    assert p2.canvas_height == p.canvas_height
    assert len(p2.images) == len(p.images)
    assert p2.images[0].name == "bg"
    assert isinstance(p2.layout, Layout)
    assert isinstance(p2.layout.children[0], FrameItem)
    assert isinstance(p2.layout.children[1], HandItem)
    assert p2.layout.children[1].pivot_x == 20
    assert p2.layout.children[1].pivot_y == 110


def test_project_json_animation_roundtrip():
    p = Project(
        name="anim",
        images=[
            ImageAsset(name=f"f{i}", source_path=f"/tmp/f{i}.png", width=240, height=240)
            for i in range(3)
        ],
        layout=Layout(
            children=[
                AnimationItem(x=0, y=0, frame_names=["f0", "f1", "f2"]),
            ],
        ),
    )
    p2 = Project.from_json(p.to_json())
    anim = p2.layout.children[0]
    assert isinstance(anim, AnimationItem)
    assert anim.frame_names == ["f0", "f1", "f2"]


def test_project_schema_validation_missing_field():
    d = {
        "name": "x",
        "canvas_width": 240,
        "canvas_height": 240,
        "images": [],
        # 'layout' missing
    }
    try:
        Project.from_dict(d)
        assert False, "expected ProjectSchemaError"
    except ProjectSchemaError as e:
        assert "layout" in str(e)


def test_project_schema_validation_bad_image():
    d = {
        "name": "x",
        "canvas_width": 240,
        "canvas_height": 240,
        "images": [{"name": "nope"}],  # missing source_path
        "layout": {"item_type": 0x00, "sub_type": 0x8C, "children": []},
    }
    try:
        Project.from_dict(d)
        assert False, "expected ProjectSchemaError"
    except ProjectSchemaError as e:
        assert "source_path" in str(e)


def test_project_schema_validation_unsupported_item_type():
    d = {
        "name": "x",
        "canvas_width": 240,
        "canvas_height": 240,
        "images": [],
        "layout": {
            "item_type": 0x00,
            "sub_type": 0x8C,
            "children": [{"item_type": 0x37, "sub_type": 0, "x": 0, "y": 0, "image_name": ""}],
        },
    }
    try:
        Project.from_dict(d)
        assert False, "expected ProjectSchemaError"
    except ProjectSchemaError as e:
        assert "0x37" in str(e)


def test_project_schema_validation_bad_json():
    try:
        Project.from_json("{not valid json")
        assert False, "expected ProjectSchemaError"
    except ProjectSchemaError as e:
        assert "JSON" in str(e)


def test_project_find_image():
    p = _sample_project()
    assert p.find_image("bg") is not None
    assert p.find_image("missing") is None


def main_runner():
    tests = [
        test_project_json_roundtrip,
        test_project_json_animation_roundtrip,
        test_project_schema_validation_missing_field,
        test_project_schema_validation_bad_image,
        test_project_schema_validation_unsupported_item_type,
        test_project_schema_validation_bad_json,
        test_project_find_image,
    ]
    failures = []
    for fn in tests:
        try:
            fn()
            print(f"[ok] {fn.__name__}")
        except AssertionError as e:
            failures.append((fn.__name__, str(e)))
            print(f"[FAIL] {fn.__name__}: {e}")
        except Exception as e:
            failures.append((fn.__name__, repr(e)))
            print(f"[ERROR] {fn.__name__}: {e!r}")
    if failures:
        print(f"\n{len(failures)} test(s) failed")
        sys.exit(1)
    print("\nALL ENCODER PROJECT TESTS PASSED")


if __name__ == "__main__":
    main_runner()

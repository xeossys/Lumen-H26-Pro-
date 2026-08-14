"""
Encoder data-model tests (h26/project.py).

Covers the JSON round-trip and schema validation of the H26
project data model.
"""

from __future__ import annotations

import json

import pytest

from h26.project import (
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
    p = _sample_project()
    anim = AnimationItem(
        x=50,
        y=50,
        frame_names=["bg", "bg"],
    )
    p.layout.children.append(anim)
    dumped = p.to_json()
    p2 = Project.from_json(dumped)
    assert len(p2.layout.children) == 3
    assert isinstance(p2.layout.children[2], AnimationItem)
    assert p2.layout.children[2].frame_names == ["bg", "bg"]


def test_project_schema_validation_missing_field():
    p = _sample_project()
    dumped = p.to_json()
    data = json.loads(dumped)
    del data["name"]
    with pytest.raises(ProjectSchemaError):
        Project.from_json(json.dumps(data))


def test_project_schema_validation_missing_name():
    """Project with empty name still parses (name is cosmetic)."""
    p = _sample_project()
    dumped = p.to_json()
    data = json.loads(dumped)
    data["name"] = ""
    p2 = Project.from_json(json.dumps(data))
    assert p2.name == ""


def test_project_schema_validation_bad_json():
    with pytest.raises(ProjectSchemaError):
        Project.from_json("not json")


def test_project_find_image():
    p = _sample_project()
    assert p.find_image("bg") is not None
    assert p.find_image("bg").width == 240
    assert p.find_image("nonexistent") is None

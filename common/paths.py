"""Repository data locations and stable capture identities."""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SCENES = ROOT / "data" / "scenes"
RUNS = ROOT / "data" / "runs"


def safe_name(value):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip(".")
    if not name:
        raise ValueError("Empty scene/capture identifier")
    return name


def capture_identity(scene_dir):
    basic = Path(scene_dir).resolve()
    manifest = json.loads((basic / "views.json").read_text(encoding="utf-8-sig"))
    return dict(scene=safe_name(manifest.get("scene") or "unidentified_scene"),
                capture_id=basic.parent.name if basic.name == "basic" else basic.name,
                basic_dir=str(basic))


def default_gt_directory(scene_dir, gt_id, kind):
    basic = Path(scene_dir).resolve()
    if basic.name == "basic":
        capture = basic.parent
    else:
        identity = capture_identity(basic)
        capture = SCENES / identity["scene"] / safe_name(identity["capture_id"])
    return capture / "gt" / safe_name(gt_id) / kind

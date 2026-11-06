"""Shared capture IO, parent classification, and atomic GT output."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile


PARENT_RELATIONS = {
    "CounterTop": "on", "Floor": "on", "Cabinet": "inside",
    "Fridge": "inside", "Drawer": "inside", "Shelf": "inside",
}


class DataError(ValueError):
    """Capture data is inconsistent or incomplete."""


def require(condition, message):
    if not condition:
        raise DataError(message)


def indexed(records, label):
    require(isinstance(records, list), f"{label}: expected a list")
    result = {}
    for record in records:
        key = record.get("objectId")
        require(isinstance(key, str) and key, f"{label}: missing objectId")
        require(key not in result, f"{label}: duplicate objectId {key}")
        result[key] = record
    return result


class Capture:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.hashes = {}

    def path(self, name):
        require(isinstance(name, str), "File path must be a string")
        path = (self.root / name).resolve()
        require(path.is_relative_to(self.root), f"Path outside capture: {name}")
        require(path.is_file(), f"Missing input: {name}")
        self.hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def json(self, name):
        return json.loads(self.path(name).read_text(encoding="utf-8-sig"))


def write_artifacts(result, output_dir, *, graph_kind="visible", per_view=False, html=None):
    """Publish a new directory only after all artifacts have been serialized."""
    output = Path(output_dir).resolve()
    require(not output.exists(), f"Output already exists; choose a new directory: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".gt-", dir=output.parent))
    try:
        def save(name, value):
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                            encoding="utf-8")
        for name in ("definitions", "input_manifest", "review_tasks", "validation_report"):
            save(f"{name}.json", result[name])
        folder = "drafts" if result["review_tasks"] else graph_kind
        for vid, graph in result["graphs"].items():
            if per_view:
                folder = graph_kind if graph["status"] == "complete" else "drafts"
            save(f"{folder}/{vid}.json", graph)
            save(f"measurements/{vid}.json", result["measurements"][vid])
        if html is not None:
            (temporary / "inspect.html").write_text(html, encoding="utf-8")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)



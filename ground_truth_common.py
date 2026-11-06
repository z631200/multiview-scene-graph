"""Shared capture IO, parent classification, and atomic GT output."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile


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


def finalize_result(result, graph_kind):
    """Give both generators the same graph, review-task, and summary contract."""
    graph_type = graph_kind + "_ground_truth"
    result["definitions"] = dict(result["definitions"], graph_type=graph_type)
    counts = Counter()
    for task in result["review_tasks"]:
        vid = task["view_id"]
        counts[vid] += 1
        task.setdefault("id", f"{vid}_r{counts[vid]}")
        if "objects" not in task:
            task["objects"] = [task["objectId"]] if "objectId" in task else [task["source"], task["target"]]
        task.setdefault("relation", "closer_to_camera" if task["reason"] == "no_valid_depth" else "on_or_inside")
    for vid, graph in result["graphs"].items():
        graph.update(schema_version="ground-truth-v1", graph_type=graph_type, review_task_count=counts[vid])
        summary = result["validation_report"]["views"][vid]
        summary["review_task_count"] = counts[vid]
        summary.setdefault("excluded_parent_count", 0)
    return result


def write_artifacts(result, output_dir, *, include_html=True):
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
        for vid, graph in result["graphs"].items():
            save(f"graphs/{vid}.json", graph)
            save(f"measurements/{vid}.json", result["measurements"][vid])
        if include_html:
            from inspect_graph import render_html
            data = dict(run_dir=str(output), graphs=[dict(graph, measurements=result["measurements"][vid],
                review_tasks=[t for t in result["review_tasks"] if t["view_id"] == vid])
                for vid, graph in result["graphs"].items()])
            html = render_html(data)
            (temporary / "inspect.html").write_text(html, encoding="utf-8")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def run_generator_cli(graph_kind, builder, argv=None):
    """Identical flags, directory names, HTML generation, and exit codes for both GTs."""
    parser = argparse.ArgumentParser(description=f"Build {graph_kind} ground-truth graphs.")
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--view", nargs="+", help="Selected view IDs; default: all views")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-html", action="store_true", help="Skip standalone inspect.html")
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = args.output_dir or Path("outputs/ground_truth") / args.scene_dir.name / f"{graph_kind}-{stamp}"
    try:
        require(not output.exists(), f"Output already exists: {output}")
        result = builder(args.scene_dir, args.view)
        write_artifacts(result, output, include_html=not args.no_html)
    except (ValueError, OSError, KeyError, TypeError, IndexError, OverflowError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"{graph_kind.title()} GT failed: {exc}\n")
    print(json.dumps(result["validation_report"], ensure_ascii=False, indent=2))
    print(f"Output: {output.resolve()}")
    if not args.no_html:
        print(f"Inspector: {output.resolve() / 'inspect.html'}")
    return 2 if result["review_tasks"] else 0



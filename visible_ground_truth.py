"""Build per-view visible ground truth from capture-v2 exports (no model calls)."""

from __future__ import annotations

from collections import Counter
import itertools
import re
import struct

import numpy as np

from ground_truth_common import (
    Capture, DataError, PARENT_RELATIONS, finalize_result, indexed, require, run_generator_cli, write_artifacts,
)


VERSION = "visible-parent-mask-depth-v1"
DEFINITIONS = {
    "version": VERSION,
    "scope": "Both endpoints must have nonempty instance masks in the same view.",
    "parent_relations": PARENT_RELATIONS,
    "physical_candidates": "Only explicit parentReceptacles; provisional on then type override.",
    "image_left_of": "Strict comparison of visible-mask mean column index (pixels).",
    "closer_to_camera": "Strict comparison of median finite positive native depth (meters).",
    "depth_convention": "AI2-THOR native depth; no geometric conversion",
    "ties": "Exactly equal measurements produce neither directed edge; recorded separately.",
    "gap_threshold": None,
}


def build_visible_gt(scene_dir, selected_views=None):
    """Return artifacts in memory. Review cases produce drafts, never complete GT."""
    capture = Capture(scene_dir)
    manifest = capture.json("views.json")
    require(manifest.get("schema_version") == "capture-v2", "Expected capture-v2")
    require(manifest.get("capture_complete") is True, "Capture is not complete")
    require(manifest.get("depth_unit") == "meter", "Expected depth_unit=meter")
    require(manifest.get("depth_format") == "Meters", "Expected native Meters depth")
    views = manifest["views"]
    require(bool(views) and manifest["num_views"] == len(views), "Invalid view count")
    view_ids = [v["view_id"] for v in views]
    require(len(set(view_ids)) == len(view_ids), "Duplicate view IDs")
    require(all(re.fullmatch(r"view_[1-9][0-9]*", v) for v in view_ids), "Invalid view IDs")
    objects = indexed(capture.json("objects.json"), "objects.json")
    visible = indexed(capture.json("visible_objects.json"), "visible_objects.json")
    require(manifest["object_count"] == len(objects), "Object count mismatch")
    for oid, obj in objects.items():
        vv = obj["visible_views"]
        require(isinstance(vv, list) and len(vv) == len(set(vv)) and
                set(vv) <= set(view_ids), f"Invalid visible_views: {oid}")
        require(obj["visible"] is bool(vv), f"visible disagrees with visible_views: {oid}")
        parents = obj.get("parentReceptacles") or []
        require(isinstance(parents, list) and len(parents) == len(set(parents)),
                f"Invalid parentReceptacles: {oid}")
        require(all(p in objects and p != oid for p in parents), f"Invalid parent ID: {oid}")
    require(set(visible) == {i for i, o in objects.items() if o["visible"]},
            "visible_objects.json is not the visible union")
    for oid, obj in visible.items():
        require(set(obj["visible_views"]) == set(objects[oid]["visible_views"]),
                f"Visible union view mismatch: {oid}")
        require(obj["objectType"] == objects[oid]["objectType"], f"Type mismatch: {oid}")

    chosen = set(selected_views) if selected_views is not None else set(view_ids)
    require(bool(chosen) and chosen <= set(view_ids), "Unknown or empty view selection")
    graphs, measurements, summaries, review = {}, {}, {}, []
    for view in views:
        if view["view_id"] not in chosen:
            continue
        vid = view["view_id"]
        height, width = view["image_height"], view["image_width"]
        image_header = capture.path(view["image"]).read_bytes()[:24]
        require(len(image_header) == 24 and image_header[:8] == b"\x89PNG\r\n\x1a\n" and
                image_header[12:16] == b"IHDR",
                f"{vid}: invalid PNG header")
        require(struct.unpack(">II", image_header[16:24]) == (width, height),
                f"{vid}: image dimensions mismatch")
        metadata = indexed(capture.json(view["metadata"])["objects"], view["metadata"])
        require(set(metadata) == set(objects), f"{vid}: metadata object set mismatch")
        for oid, obj in objects.items():
            for key in ("objectType", "position", "rotation", "axisAlignedBoundingBox", "parentReceptacles"):
                require(metadata[oid].get(key) == obj.get(key),
                        f"{vid}: metadata differs from snapshot: {oid} / {key}")
        require(view["depth_info"]["unit"] == "meter", f"{vid}: invalid depth unit")
        depth = np.load(capture.path(view["depth"]), allow_pickle=False)
        require(depth.shape == (height, width) and depth.dtype.kind == "f",
                f"{vid}: depth shape or dtype mismatch")
        mapping = capture.json(view["segmentation_mapping"])
        require(mapping["view_id"] == vid, f"{vid}: segmentation view mismatch")
        mapped = indexed(mapping["masks"], view["segmentation_mapping"])
        ids = {i for i, o in visible.items() if vid in o["visible_views"]}
        require(set(mapped) == ids == set(view["visible_object_pixel_counts"]),
                f"{vid}: mask / visibility membership mismatch")
        keys = [m["key"] for m in mapped.values()]
        require(len(keys) == len(set(keys)), f"{vid}: duplicate mask keys")
        stats = {}
        with np.load(capture.path(view["instance_masks"]), allow_pickle=False) as masks:
            require(set(masks.files) == set(keys) | {"object_ids"}, f"{vid}: NPZ keys mismatch")
            archive_ids = masks["object_ids"]
            require(archive_ids.ndim == 1 and archive_ids.dtype.kind == "U" and
                    archive_ids.tolist() == list(mapped), f"{vid}: NPZ object_ids mismatch")
            for oid in sorted(ids):
                entry = mapped[oid]
                mask = masks[entry["key"]]
                require(mask.dtype == np.bool_ and mask.shape == depth.shape,
                        f"{vid}: invalid mask dtype/shape: {oid}")
                _, columns = np.nonzero(mask)
                count = int(columns.size)
                require(count > 0 and count == entry["pixel_count"] ==
                        view["visible_object_pixel_counts"][oid], f"{vid}: pixel count mismatch: {oid}")
                pixels = depth[mask]
                valid = pixels[np.isfinite(pixels) & (pixels > 0)].astype(np.float64)
                median = float(np.median(valid)) if valid.size else None
                stats[oid] = {
                    "mask_key": entry["key"], "visible_pixel_count": count,
                    "mask_center_x_px": float(columns.mean()),
                    "valid_depth_pixel_count": int(valid.size),
                    "invalid_depth_pixel_count": count - int(valid.size),
                    "median_native_depth_m": median,
                }
                if median is None:
                    review.append({"view_id": vid, "objectId": oid, "reason": "no_valid_depth"})

        edges, ties, excluded, physical_decisions = [], [], [], []

        def edge(source, relation, target, evidence):
            edges.append({
                "id": f"e{len(edges) + 1}", "source": source, "relation": relation,
                "target": target, "frame": "physical" if relation in ("on", "inside") else vid,
                "status": "accepted", "definition_version": VERSION, "evidence": evidence,
            })

        for oid in sorted(ids):
            for parent in sorted(objects[oid].get("parentReceptacles") or []):
                if parent not in ids:
                    excluded.append({"source": oid, "target": parent, "reason": "parent_not_visible"})
                    continue
                parent_type = objects[parent]["objectType"]
                relation = PARENT_RELATIONS.get(parent_type)
                decision = {"source": oid, "target": parent, "initial_relation": "on",
                            "parent_type": parent_type, "final_relation": relation}
                physical_decisions.append(decision)
                if relation is None:
                    review.append({"view_id": vid, **decision, "reason": "unknown_parent_type"})
                else:
                    edge(oid, relation, parent, {
                        "method": "parentReceptacles_type_lookup", "metadata": view["metadata"],
                        "parent_type": parent_type, "initial_relation": "on",
                    })
        for a, b in itertools.combinations(sorted(ids), 2):
            for relation, field in (("image_left_of", "mask_center_x_px"),
                                    ("closer_to_camera", "median_native_depth_m")):
                av, bv = stats[a][field], stats[b][field]
                if av is None or bv is None:
                    continue
                if av == bv:
                    ties.append({"objects": [a, b], "relation": relation, "value": av})
                    continue
                source, target = (a, b) if av < bv else (b, a)
                edge(source, relation, target, {
                    "method": field, "source_value": stats[source][field],
                    "target_value": stats[target][field],
                    "measurements": f"measurements/{vid}.json",
                })
        counts = {r: 0 for r in ("on", "inside", "image_left_of", "closer_to_camera")}
        counts.update(Counter(e["relation"] for e in edges))
        needs_review = any(r["view_id"] == vid for r in review)
        graph = {
            "schema_version": "visible-gt-v1", "definition_version": VERSION,
            "graph_type": "visible_ground_truth", "view_id": vid,
            "status": "needs_review" if needs_review else "complete",
            "nodes": [{"id": oid, "objectType": objects[oid]["objectType"],
                       "name": objects[oid].get("name", oid)} for oid in sorted(ids)],
            "edges": edges,
        }
        signatures = {(e["source"], e["relation"], e["target"], e["frame"]) for e in edges}
        require(len(signatures) == len(edges), f"{vid}: duplicate edges")
        require(all(e["source"] in ids and e["target"] in ids and e["source"] != e["target"]
                    for e in edges), f"{vid}: invalid edge endpoints")
        for source, relation, target, frame in signatures:
            if relation in ("image_left_of", "closer_to_camera"):
                require((target, relation, source, frame) not in signatures, f"{vid}: opposing edges")
        graphs[vid] = graph
        measurements[vid] = {
            "view_id": vid, "sources": {k: view[k] for k in
                ("image", "depth", "instance_masks", "segmentation_mapping", "metadata")},
            "objects": stats, "equal_pairs": ties, "excluded_parent_relations": excluded,
            "physical_classification": physical_decisions,
        }
        summaries[vid] = {"status": graph["status"], "node_count": len(ids),
                          "edge_count": len(edges), "relations": counts,
                          "equal_pair_count": len(ties), "excluded_parent_count": len(excluded)}
    return finalize_result({
        "definitions": DEFINITIONS, "graphs": graphs, "measurements": measurements,
        "review_tasks": review,
        "input_manifest": {"scene_dir": str(capture.root), "scene": manifest.get("scene"),
                           "ai2thor_version": manifest.get("ai2thor_version"),
                           "inputs_sha256": capture.hashes},
        "validation_report": {"status": "needs_review" if review else "complete", "views": summaries},
    }, "visible")


def main(argv=None):
    return run_generator_cli("visible", build_visible_gt, argv)


if __name__ == "__main__":
    raise SystemExit(main())

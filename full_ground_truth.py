"""Build full-object ground-truth graphs for selected capture-v2 camera views."""

from __future__ import annotations

from collections import Counter
import itertools
import math
import re

from ground_truth_common import Capture, PARENT_RELATIONS, finalize_result, indexed, require, run_generator_cli


VERSION = "full-parent-position-camera-v1"
DEFINITIONS = {
    "version": VERSION, "graph_type": "full_ground_truth",
    "scope": "All metadata objects, including invisible and out-of-frame objects.",
    "parent_relations": PARENT_RELATIONS,
    "physical_candidates": "Only parentReceptacles; initially inside if never visible, else on; type overrides.",
    "image_left_of": "Strict comparison of camera X/Z for object position with Z > 0; no clipping.",
    "closer_to_camera": "Euclidean object-position to camera-position distance; compare squared meters.",
    "camera_convention": "World Y up; yaw 0 faces +Z, yaw 90 faces +X; pitch positive downward; no roll.",
    "aabb": "Diagnostic camera-depth bounds only; never substitutes for object position.",
    "ties": "Exact equality creates no directional edge and is recorded separately.",
    "nonpositive_camera_z": "Keep nodes and calculable edges; queue image_left_of pairs for human review.",
    "gap_threshold": None,
}


def finite(value, label):
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
            f"Nonfinite or invalid number: {label}")
    return float(value)


def xyz(value, label):
    return tuple(finite(value[k], f"{label}.{k}") for k in ("x", "y", "z"))


def sincos(degrees):
    # Exact cardinal rotations avoid classifying a point on the camera plane as in front.
    cardinal = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0), 270: (-1.0, 0.0)}
    angle = degrees % 360
    return cardinal[angle] if angle in cardinal else (math.sin(math.radians(angle)), math.cos(math.radians(angle)))


def camera_coordinates(position, camera):
    dx, dy, dz = (a - b for a, b in zip(position, camera["position"]))
    sy, cy = sincos(camera["yaw"])
    sp, cp = sincos(camera["pitch"])
    horizontal = sy * dx + cy * dz
    return cy * dx - sy * dz, cp * dy + sp * horizontal, cp * horizontal - sp * dy


def read_camera(view, metadata):
    c = view["camera"]
    require(c["position_unit"] == "meter" and c["rotation_unit"] == "degree" and
            c["horizon_positive"] == "down", "Unsupported camera units/convention")
    rotation = xyz(c["agent_rotation"], "camera.agent_rotation")
    require(rotation[0] == rotation[2] == 0, "Nonzero agent pitch/roll is not supported")
    position = xyz(c["position"], "camera.position")
    pitch = finite(c["camera_horizon"], "camera_horizon")
    fov = finite(c["vertical_fov"], "vertical_fov")
    require(0 < fov < 180, "FOV must be between 0 and 180 degrees")
    width, height = view["image_width"], view["image_height"]
    require(all(type(n) is int and n > 0 for n in (width, height)), "Invalid image dimensions")
    for record in (view, metadata):
        require(xyz(record["cameraPosition"], "cameraPosition") == position and
                xyz(record["agent"]["rotation"], "agent.rotation") == rotation and
                finite(record["agent"]["cameraHorizon"], "cameraHorizon") == pitch and
                finite(record["fov"], "fov") == fov, "Camera metadata mismatch")
    return dict(position=position, yaw=rotation[1], pitch=pitch, vertical_fov=fov,
                image_width=width, image_height=height)


def measure_object(obj, camera, vid):
    position = xyz(obj["position"], obj["objectId"] + ".position")
    x, y, z = camera_coordinates(position, camera)
    distance_squared = sum((a - b) ** 2 for a, b in zip(position, camera["position"]))
    for value in (x, y, z, distance_squared):
        finite(value, "computed geometry")
    region = "front" if z > 0 else "behind" if z < 0 else "camera_plane"
    ratio, pixel, in_frame = None, None, False
    if z > 0:
        ratio = finite(x / z, "projected X/Z")
        vertical = finite(y / z, "projected Y/Z")
        half_y = math.tan(math.radians(camera["vertical_fov"]) / 2)
        half_x = half_y * camera["image_width"] / camera["image_height"]
        pixel = {"x": camera["image_width"] * (0.5 + ratio / (2 * half_x)),
                 "y": camera["image_height"] * (0.5 - vertical / (2 * half_y))}
        xyz({**pixel, "z": z}, "projected_pixel")
        in_frame = 0 <= pixel["x"] < camera["image_width"] and 0 <= pixel["y"] < camera["image_height"]
    bounds = None
    if obj.get("axisAlignedBoundingBox") is not None:
        corners = obj["axisAlignedBoundingBox"]["cornerPoints"]
        require(len(corners) == 8 and all(len(p) == 3 for p in corners), "AABB requires eight xyz corners")
        depths = [camera_coordinates(tuple(finite(v, "AABB corner") for v in p), camera)[2] for p in corners]
        for value in depths:
            finite(value, "AABB camera depth")
        bounds = {"min_camera_z": min(depths), "max_camera_z": max(depths),
                  "intersects_camera_plane": min(depths) <= 0 <= max(depths)}
    return {
        "world_position": obj["position"], "camera_position": dict(zip(("x", "y", "z"), (x, y, z))),
        "camera_region": region, "projected_x_over_z": ratio, "projected_pixel": pixel,
        "position_in_frame": in_frame, "distance_squared_m2": distance_squared,
        "distance_m": math.sqrt(distance_squared), "aabb_camera_depth": bounds,
        "visible_in_view": vid in obj["visible_views"], "ever_visible": bool(obj["visible_views"]),
    }


def build_full_gt(scene_dir, selected_views=None):
    capture = Capture(scene_dir)
    manifest = capture.json("views.json")
    require(manifest.get("schema_version") == "capture-v2" and manifest.get("capture_complete") is True,
            "Expected complete capture-v2 data")
    require(manifest["position_unit"] == "meter" and manifest["rotation_unit"] == "degree", "Invalid units")
    views = manifest["views"]
    all_view_ids = [v["view_id"] for v in views]
    require(len(views) == manifest["num_views"] > 0 and len(set(all_view_ids)) == len(views), "Invalid view count/IDs")
    require(all(re.fullmatch(r"view_[1-9][0-9]*", v) for v in all_view_ids), "Invalid view IDs")
    chosen = set(selected_views) if selected_views is not None else set(all_view_ids)
    require(bool(chosen) and chosen <= set(all_view_ids), "Unknown or empty view selection")
    objects = indexed(capture.json("objects.json"), "objects.json")
    visible = indexed(capture.json("visible_objects.json"), "visible_objects.json")
    require(len(objects) == manifest["object_count"], "Object count mismatch")
    for oid, obj in objects.items():
        vv = obj["visible_views"]
        require(isinstance(vv, list) and len(vv) == len(set(vv)) and set(vv) <= set(all_view_ids),
                f"Invalid visible_views: {oid}")
        require(obj["visible"] is bool(vv), f"Visibility mismatch: {oid}")
        parents = obj.get("parentReceptacles") or []
        require(isinstance(parents, list) and len(parents) == len(set(parents)) and
                all(p in objects and p != oid for p in parents), f"Invalid parentReceptacles: {oid}")
    require(set(visible) == {i for i, o in objects.items() if o["visible"]}, "Visible union mismatch")
    for oid, obj in visible.items():
        require(obj["objectType"] == objects[oid]["objectType"] and
                set(obj["visible_views"]) == set(objects[oid]["visible_views"]), f"Visible object mismatch: {oid}")

    graphs, measurements, summaries, review = {}, {}, {}, []
    for view in views:
        vid = view["view_id"]
        if vid not in chosen:
            continue
        raw_metadata = capture.json(view["metadata"])
        metadata = indexed(raw_metadata["objects"], view["metadata"])
        require(set(metadata) == set(objects), f"{vid}: metadata object set mismatch")
        for oid, obj in objects.items():
            for key in ("objectType", "position", "rotation", "axisAlignedBoundingBox", "parentReceptacles"):
                require(metadata[oid].get(key) == obj.get(key), f"{vid}: metadata mismatch: {oid}/{key}")
        camera = read_camera(view, raw_metadata)
        stats = {oid: measure_object(objects[oid], camera, vid) for oid in sorted(objects)}
        edges, ties, decisions, tasks = [], [], [], []

        def add_edge(source, relation, target, evidence):
            edges.append(dict(id=f"e{len(edges) + 1}", source=source, relation=relation, target=target,
                              frame="physical" if relation in ("on", "inside") else vid,
                              status="accepted", definition_version=VERSION, evidence=evidence))

        def task(pair, relation, reason, **extra):
            tasks.append(dict(id=f"{vid}_r{len(tasks) + 1}", view_id=vid, objects=list(pair),
                              relation=relation, reason=reason, **extra))

        for oid, obj in sorted(objects.items()):
            for parent in sorted(obj.get("parentReceptacles") or []):
                parent_type = objects[parent]["objectType"]
                initial = "on" if obj["visible_views"] else "inside"
                relation = PARENT_RELATIONS.get(parent_type)
                decisions.append(dict(source=oid, target=parent, initial_relation=initial,
                                      parent_type=parent_type, final_relation=relation))
                if relation is None:
                    task((oid, parent), "on_or_inside", "unknown_parent_type", parent_type=parent_type)
                else:
                    add_edge(oid, relation, parent, dict(method="parentReceptacles_type_lookup",
                             metadata=view["metadata"], parent_type=parent_type, initial_relation=initial))
        for a, b in itertools.combinations(sorted(objects), 2):
            for relation, field in (("image_left_of", "projected_x_over_z"),
                                    ("closer_to_camera", "distance_squared_m2")):
                av, bv = stats[a][field], stats[b][field]
                if av is None or bv is None:
                    task((a, b), relation, "nonpositive_camera_z",
                         camera_regions={i: stats[i]["camera_region"] for i in (a, b)})
                elif av == bv:
                    ties.append(dict(objects=[a, b], relation=relation, value=av, method=field))
                else:
                    source, target = (a, b) if av < bv else (b, a)
                    add_edge(source, relation, target, dict(method=field, source_value=stats[source][field],
                             target_value=stats[target][field], measurements=f"measurements/{vid}.json"))
        pair_count = len(objects) * (len(objects) - 1) // 2
        counts = {r: sum(e["relation"] == r for e in edges) for r in
                  ("on", "inside", "image_left_of", "closer_to_camera")}
        signatures = {(e["source"], e["relation"], e["target"]) for e in edges}
        require(len(signatures) == len(edges), "Duplicate edges")
        for relation in ("image_left_of", "closer_to_camera"):
            require(counts[relation] + sum(t["relation"] == relation for t in ties) +
                    sum(t["relation"] == relation for t in tasks) == pair_count,
                    f"{vid}: incomplete pair accounting")
            require(all((t, r, s) not in signatures for s, r, t in signatures if r == relation), "Opposing edges")
        status = "needs_review" if tasks else "complete"
        graphs[vid] = dict(schema_version="full-gt-v1", graph_type="full_ground_truth", definition_version=VERSION,
            view_id=vid, status=status, review_task_count=len(tasks), nodes=[dict(id=oid,
            objectType=objects[oid]["objectType"], name=objects[oid].get("name", oid),
            visible_in_view=s["visible_in_view"], ever_visible=s["ever_visible"],
            camera_region=s["camera_region"]) for oid, s in stats.items()], edges=edges)
        measurements[vid] = dict(view_id=vid, camera=camera,
            sources=dict(objects="objects.json", metadata=view["metadata"], cameras="views.json"),
            objects=stats, equal_pairs=ties, excluded_parent_relations=[], physical_classification=decisions)
        summaries[vid] = dict(status=status, node_count=len(objects), edge_count=len(edges), relations=counts,
            equal_pair_count=len(ties), review_task_count=len(tasks),
            camera_regions=dict(Counter(s["camera_region"] for s in stats.values())),
            visible_node_count=sum(s["visible_in_view"] for s in stats.values()))
        review.extend(tasks)
    return finalize_result(dict(definitions=DEFINITIONS, graphs=graphs, measurements=measurements, review_tasks=review,
                input_manifest=dict(scene_dir=str(capture.root), scene=manifest.get("scene"),
                    ai2thor_version=manifest.get("ai2thor_version"), inputs_sha256=capture.hashes),
                validation_report=dict(status="needs_review" if review else "complete", views=summaries)), "full")


def main(argv=None):
    return run_generator_cli("full", build_full_gt, argv)


if __name__ == "__main__":
    raise SystemExit(main())

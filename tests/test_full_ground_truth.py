"""Camera geometry, full-object coverage, review gating, and real-scene acceptance."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from full_ground_truth import build_full_gt, camera_coordinates, measure_object
from ground_truth_common import DataError, write_artifacts
from inspect_graph import load_run, render_html


def camera(yaw=0, pitch=0):
    return dict(position=(0, 0, 0), yaw=yaw, pitch=pitch, vertical_fov=90,
                image_width=200, image_height=100)


class GeometryTests(unittest.TestCase):
    def test_camera_rotation_translation_and_pitch(self):
        self.assertEqual(camera_coordinates((2, 0, 1), camera(90)), (-1, 0, 2))
        self.assertEqual(camera_coordinates((0, -2, 0), camera(pitch=90)), (0, 0, 2))
        self.assertEqual(camera_coordinates((0, 0, 2), camera(180)), (0, 0, -2))
        translated = dict(camera(), position=(10, 3, 20))
        self.assertEqual(camera_coordinates((11, 5, 24), translated), (1, 2, 4))

    def test_no_clipping_and_distance_includes_behind(self):
        obj = dict(objectId="A", position=dict(x=10, y=0, z=1), visible_views=[])
        stat = measure_object(obj, camera(), "view_1")
        self.assertGreater(stat["projected_pixel"]["x"], 200)
        self.assertFalse(stat["position_in_frame"])
        self.assertEqual(stat["projected_x_over_z"], 10)
        obj["position"] = dict(x=0, y=0, z=-3)
        stat = measure_object(obj, camera(), "view_1")
        self.assertIsNone(stat["projected_x_over_z"])
        self.assertEqual(stat["distance_m"], 3)
        self.assertEqual(stat["camera_region"], "behind")

    def test_plane_is_exact_under_cardinal_rotation(self):
        obj = dict(objectId="A", position=dict(x=0, y=0, z=2), visible_views=[])
        stat = measure_object(obj, camera(90), "view_1")
        self.assertEqual(stat["camera_region"], "camera_plane")
        self.assertIsNone(stat["projected_pixel"])

    def test_aabb_crossing_does_not_replace_position(self):
        obj = dict(objectId="A", position=dict(x=1, y=0, z=2), visible_views=[],
                   axisAlignedBoundingBox={"cornerPoints": [[x, y, z] for x in (-1, 1)
                                           for y in (-1, 1) for z in (-1, 3)]})
        stat = measure_object(obj, camera(), "view_1")
        self.assertTrue(stat["aabb_camera_depth"]["intersects_camera_plane"])
        self.assertEqual(stat["projected_x_over_z"], .5)
        self.assertEqual(stat["camera_region"], "front")


class FullGTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "scene"
        self.root.mkdir()
        self.objects = [dict(objectId=i, objectType=t, name=i,
                            position=dict(zip(("x", "y", "z"), p)), rotation=dict(x=0, y=0, z=0),
                            visible=i != "B", visible_views=["view_1"] if i != "B" else [],
                            parentReceptacles=["P"] if i in ("A", "B") else None)
                        for i, t, p in [("A", "Cup", (-1, 0, 2)), ("B", "Bowl", (1, 0, 2)),
                                        ("P", "CounterTop", (0, 0, 4))]]
        self.views = []
        for index, yaw in enumerate((0, 180), 1):
            position, rotation = dict(x=0, y=0, z=0), dict(x=0, y=yaw, z=0)
            self.views.append(dict(view_id=f"view_{index}", metadata=f"metadata_{index}.json",
                image_width=200, image_height=100, cameraPosition=position, fov=90,
                agent=dict(rotation=rotation, cameraHorizon=0),
                camera=dict(position=position, agent_rotation=rotation, camera_horizon=0,
                            vertical_fov=90, position_unit="meter", rotation_unit="degree", horizon_positive="down")))
        self.save()

    def write(self, path, value):
        (self.root / path).write_text(json.dumps(value), encoding="utf-8")

    def save(self):
        self.write("objects.json", self.objects)
        self.write("visible_objects.json", [o for o in self.objects if o["visible"]])
        self.write("views.json", dict(schema_version="capture-v2", capture_complete=True,
            num_views=2, object_count=len(self.objects), position_unit="meter", rotation_unit="degree", views=self.views))
        for v in self.views:
            self.write(v["metadata"], dict(objects=self.objects, cameraPosition=v["cameraPosition"],
                                          fov=v["fov"], agent=v["agent"]))

    def test_all_objects_and_invisible_parent_classification(self):
        result = build_full_gt(self.root)
        graph = result["graphs"]["view_1"]
        self.assertEqual({n["id"] for n in graph["nodes"]}, {"A", "B", "P"})
        self.assertFalse(next(n for n in graph["nodes"] if n["id"] == "B")["ever_visible"])
        physical = {(e["source"], e["relation"], e["target"]) for e in graph["edges"] if e["frame"] == "physical"}
        self.assertEqual(physical, {("A", "on", "P"), ("B", "on", "P")})
        decisions = result["measurements"]["view_1"]["physical_classification"]
        self.assertEqual(decisions[1]["initial_relation"], "inside")
        self.assertEqual(decisions[1]["final_relation"], "on")

    def test_ties_and_pair_accounting(self):
        result = build_full_gt(self.root)
        self.assertEqual(result["validation_report"]["views"]["view_1"]["relations"],
                         dict(on=2, inside=0, image_left_of=3, closer_to_camera=2))
        ties = result["measurements"]["view_1"]["equal_pairs"]
        self.assertEqual([(t["objects"], t["relation"]) for t in ties], [(["A", "B"], "closer_to_camera")])
        self.assertEqual(len(result["review_tasks"]), 3)
        self.assertTrue(all(t["relation"] == "image_left_of" and t["view_id"] == "view_2"
                            for t in result["review_tasks"]))
        self.assertEqual(result["validation_report"]["views"]["view_2"]["relations"]["closer_to_camera"], 2)

    def test_selected_view_can_complete_without_other_views(self):
        result = build_full_gt(self.root, ["view_1"])
        self.assertEqual(set(result["graphs"]), {"view_1"})
        self.assertEqual(result["validation_report"]["status"], "complete")
        self.assertEqual(result["review_tasks"], [])
        self.assertNotIn("metadata_2.json", result["input_manifest"]["inputs_sha256"])
        with self.assertRaises(DataError): build_full_gt(self.root, ["view_9"])

    def test_per_view_publication_and_inspector(self):
        result = build_full_gt(self.root)
        out = Path(self.temp.name) / "out"
        write_artifacts(result, out)
        self.assertTrue((out / "graphs/view_1.json").is_file())
        self.assertTrue((out / "graphs/view_2.json").is_file())
        self.assertFalse((out / "full/view_2.json").exists())
        self.assertEqual(len(load_run(out, complete_only=True)["graphs"]), 1)
        data = load_run(out)
        self.assertEqual(len(data["graphs"]), 2)
        self.assertEqual(len(data["graphs"][1]["review_tasks"]), 3)
        html = render_html(data)
        self.assertIn('source_graph_status', html)
        self.assertIn('review-title', html)
        self.assertNotIn('unresolved', (out / "graphs/view_2.json").read_text())

    def test_all_draft_run_is_loadable_explicitly(self):
        result = build_full_gt(self.root, ["view_2"])
        out = Path(self.temp.name) / "draft-run"
        write_artifacts(result, out)
        with self.assertRaises(ValueError): load_run(out, complete_only=True)
        self.assertEqual(load_run(out)["graphs"][0]["status"], "needs_review")

    def test_unknown_parent_is_reviewed(self):
        self.objects[2]["objectType"] = "UnknownContainer"
        self.save()
        result = build_full_gt(self.root, ["view_1"])
        self.assertEqual(len(result["review_tasks"]), 2)
        self.assertTrue(all(t["reason"] == "unknown_parent_type" for t in result["review_tasks"]))

    def test_horizontal_ties_and_small_gaps(self):
        self.objects[0]["position"] = dict(x=0, y=0, z=2)
        self.objects[1]["position"] = dict(x=0, y=1, z=2)
        self.save()
        result = build_full_gt(self.root, ["view_1"])
        self.assertEqual(result["validation_report"]["views"]["view_1"]["relations"]["image_left_of"], 0)
        self.objects[1]["position"]["x"] = 1e-16
        self.save()
        result = build_full_gt(self.root, ["view_1"])
        edges = result["graphs"]["view_1"]["edges"]
        self.assertTrue(any(e["source"] == "A" and e["target"] == "B" and e["relation"] == "image_left_of" for e in edges))

    def test_nonfinite_camera_and_inconsistent_snapshot_are_rejected(self):
        original_objects, original_views = copy.deepcopy(self.objects), copy.deepcopy(self.views)
        for mutation in ("nan", "roll", "pose", "parent", "fov", "metadata"):
            with self.subTest(mutation=mutation):
                self.objects, self.views = copy.deepcopy(original_objects), copy.deepcopy(original_views)
                if mutation == "nan": self.objects[0]["position"]["x"] = float("nan")
                if mutation == "roll": self.views[0]["camera"]["agent_rotation"]["z"] = 5
                if mutation == "pose": self.views[0]["camera"]["position"] = dict(x=2, y=0, z=0)
                if mutation == "parent": self.objects[0]["parentReceptacles"] = ["missing"]
                if mutation == "fov": self.views[0]["camera"]["vertical_fov"] = 180
                self.save()
                if mutation == "metadata":
                    m = json.loads((self.root / "metadata_1.json").read_text())
                    m["objects"][0]["position"]["x"] = 3
                    self.write("metadata_1.json", m)
                with self.assertRaises(DataError): build_full_gt(self.root)


class SceneAcceptanceTests(unittest.TestCase):
    def test_all_four_views(self):
        scene = Path(__file__).resolve().parents[1] / "colab/scene_output/20261105T120357_736949Z"
        if not scene.is_dir(): self.skipTest("Local captured scene is not installed")
        result = build_full_gt(scene)
        expected = [(1889, 1035, 4853), (2344, 580, 5308), (2924, 0, 5888), (2848, 76, 5812)]
        for index, (left, reviews, edges) in enumerate(expected, 1):
            vid = f"view_{index}"
            report = result["validation_report"]["views"][vid]
            self.assertEqual(report["node_count"], 77)
            self.assertEqual(report["relations"], dict(on=26, inside=12, image_left_of=left, closer_to_camera=2926))
            self.assertEqual(report["edge_count"], edges)
            self.assertEqual(report["review_task_count"], reviews)
            self.assertEqual(report["equal_pair_count"], 2)
            self.assertEqual(report["status"], "needs_review" if reviews else "complete")
        physical = [{(e["source"], e["relation"], e["target"]) for e in g["edges"] if e["frame"] == "physical"}
                    for g in result["graphs"].values()]
        self.assertTrue(all(p == physical[0] for p in physical))


if __name__ == "__main__":
    unittest.main()

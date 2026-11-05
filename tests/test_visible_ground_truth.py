"""Visible GT semantics, input isolation, review gating, and scene acceptance."""

import copy
import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np

from visible_ground_truth import DataError, build_visible_gt, main, write_artifacts


class VisibleGTTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "scene"
        self.root.mkdir()
        self.make_scene()

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def load(self, name):
        return json.loads((self.root / name).read_text())

    def make_scene(self, visible_ids=("A", "B", "P"), parent_type="Shelf"):
        objects = [dict(objectId=i, objectType=t, name=i, visible=i in visible_ids,
                        visible_views=["view_1"] if i in visible_ids else [],
                        position=dict(x=0, y=0, z=0), parentReceptacles=["P"] if i == "A" else None)
                   for i, t in (("A", "Cup"), ("B", "Bottle"), ("P", parent_type))]
        self.save("objects.json", objects)
        self.save("visible_objects.json", [o for o in objects if o["visible"]])
        self.save("metadata.json", {"objects": objects})
        masks = {i: np.zeros((2, 4), dtype=bool) for i in visible_ids}
        positions = {"A": [(0, 0), (0, 2)], "B": [(0, 3)], "P": [(1, 0), (1, 1)]}
        for i, mask in masks.items():
            for y, x in positions[i]:
                mask[y, x] = True
        entries = [dict(objectId=i, key=f"mask_{n:04d}", pixel_count=int(masks[i].sum()))
                   for n, i in enumerate(visible_ids)]
        np.savez_compressed(self.root / "masks.npz", object_ids=np.array(visible_ids, dtype="U1"),
                            **{e["key"]: masks[e["objectId"]] for e in entries})
        self.save("mapping.json", {"view_id": "view_1", "masks": entries})
        np.save(self.root / "depth.npy", np.array([[1, 10, 5, 2], [7, 9, 10, 10]], dtype=np.float32))
        # The generator verifies PNG dimensions; pixel decoding is not used by GT.
        (self.root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) +
                                              b"IHDR" + struct.pack(">II", 4, 2))
        self.save("views.json", dict(schema_version="capture-v2", capture_complete=True,
                  depth_unit="meter", depth_format="Meters", num_views=1, object_count=3,
                  views=[dict(view_id="view_1", image="image.png", image_width=4, image_height=2,
                              metadata="metadata.json", depth="depth.npy", depth_info={"unit": "meter"},
                              instance_masks="masks.npz", segmentation_mapping="mapping.json",
                              visible_object_pixel_counts={i: int(m.sum()) for i, m in masks.items()})]))

    def test_directions_and_parent_override(self):
        result = build_visible_gt(self.root)
        edges = {(e["source"], e["relation"], e["target"]) for e in result["graphs"]["view_1"]["edges"]}
        self.assertEqual(edges, {("A", "inside", "P"),
            ("P", "image_left_of", "A"), ("P", "image_left_of", "B"), ("A", "image_left_of", "B"),
            ("B", "closer_to_camera", "A"), ("B", "closer_to_camera", "P"), ("A", "closer_to_camera", "P")})
        self.assertEqual(result["measurements"]["view_1"]["objects"]["A"]["median_native_depth_m"], 3)
        self.assertEqual(result["validation_report"]["status"], "complete")

    def test_all_parent_types(self):
        for parent_type, relation in [("CounterTop", "on"), ("Floor", "on"),
                ("Cabinet", "inside"), ("Fridge", "inside"), ("Drawer", "inside"), ("Shelf", "inside")]:
            with self.subTest(parent_type=parent_type):
                self.make_scene(parent_type=parent_type)
                edges = build_visible_gt(self.root)["graphs"]["view_1"]["edges"]
                self.assertEqual([e["relation"] for e in edges if e["frame"] == "physical"], [relation])

    def test_hidden_parent_is_not_a_visible_node_or_edge(self):
        self.make_scene(visible_ids=("A", "B"))
        result = build_visible_gt(self.root)
        graph = result["graphs"]["view_1"]
        self.assertEqual({n["id"] for n in graph["nodes"]}, {"A", "B"})
        self.assertFalse(any(e["relation"] in ("on", "inside") for e in graph["edges"]))
        self.assertEqual(len(result["measurements"]["view_1"]["excluded_parent_relations"]), 1)

    def test_empty_view_is_valid(self):
        self.make_scene(visible_ids=())
        result = build_visible_gt(self.root)
        self.assertEqual(result["graphs"]["view_1"]["nodes"], [])
        self.assertEqual(result["graphs"]["view_1"]["edges"], [])
        self.assertEqual(result["review_tasks"], [])

    def test_ties_have_no_directed_edge(self):
        depth = np.load(self.root / "depth.npy")
        depth[0, 0] = depth[0, 2] = 2
        np.save(self.root / "depth.npy", depth)
        result = build_visible_gt(self.root)
        ties = result["measurements"]["view_1"]["equal_pairs"]
        self.assertEqual(ties, [{"objects": ["A", "B"], "relation": "closer_to_camera", "value": 2}])
        self.assertEqual(result["validation_report"]["views"]["view_1"]["relations"]["closer_to_camera"], 2)
        self.assertEqual(result["review_tasks"], [])

    def test_invalid_pixels_are_filtered(self):
        depth = np.load(self.root / "depth.npy")
        depth[0, 0] = np.nan
        np.save(self.root / "depth.npy", depth)
        result = build_visible_gt(self.root)
        stat = result["measurements"]["view_1"]["objects"]["A"]
        self.assertEqual(stat["median_native_depth_m"], 5)
        self.assertEqual(stat["invalid_depth_pixel_count"], 1)
        self.assertEqual(result["review_tasks"], [])

    def test_equal_mask_centers_have_no_left_edge(self):
        with np.load(self.root / "masks.npz") as archive:
            data = {key: archive[key] for key in archive.files}
        data["mask_0001"][:] = False
        data["mask_0001"][0, 1] = True
        np.savez_compressed(self.root / "masks.npz", **data)
        result = build_visible_gt(self.root)
        self.assertIn({"objects": ["A", "B"], "relation": "image_left_of", "value": 1},
                      result["measurements"]["view_1"]["equal_pairs"])
        self.assertEqual(result["validation_report"]["views"]["view_1"]["relations"]["image_left_of"], 2)

    def test_small_depth_difference_is_not_thresholded(self):
        depth = np.load(self.root / "depth.npy")
        depth[0, 0] = depth[0, 2] = 2
        depth[0, 3] = np.nextafter(np.float32(2), np.float32(3))
        np.save(self.root / "depth.npy", depth)
        graph = build_visible_gt(self.root)["graphs"]["view_1"]
        self.assertTrue(any(e["source"] == "A" and e["target"] == "B" and
                            e["relation"] == "closer_to_camera" for e in graph["edges"]))

    def test_cli_review_exit_code(self):
        self.make_scene(parent_type="Bowl")
        output = Path(self.temp.name) / "review"
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(["--scene-dir", str(self.root), "--output-dir", str(output)])
        self.assertEqual(code, 2)
        self.assertFalse((output / "visible").exists())
        self.assertTrue((output / "review_tasks.json").exists())

    def test_no_valid_depth_publishes_only_drafts(self):
        depth = np.load(self.root / "depth.npy")
        depth[0, 0], depth[0, 2] = np.inf, 0
        np.save(self.root / "depth.npy", depth)
        result = build_visible_gt(self.root)
        self.assertEqual(result["review_tasks"][0]["reason"], "no_valid_depth")
        output = Path(self.temp.name) / "output"
        write_artifacts(result, output)
        self.assertFalse((output / "visible").exists())
        self.assertTrue((output / "drafts/view_1.json").is_file())
        self.assertNotIn("unresolved", (output / "drafts/view_1.json").read_text())

    def test_unknown_parent_type_requires_review(self):
        self.make_scene(parent_type="Bowl")
        result = build_visible_gt(self.root)
        self.assertEqual(result["review_tasks"][0]["reason"], "unknown_parent_type")
        self.assertFalse(any(e["frame"] == "physical" for e in result["graphs"]["view_1"]["edges"]))

    def test_inconsistent_inputs_fail(self):
        for corruption in ("count", "union", "metadata", "duplicate", "path", "shape", "mask_dtype"):
            with self.subTest(corruption=corruption):
                self.make_scene()
                if corruption == "count":
                    data = self.load("mapping.json"); data["masks"][0]["pixel_count"] += 1
                    self.save("mapping.json", data)
                elif corruption == "union":
                    self.save("visible_objects.json", self.load("visible_objects.json")[:-1])
                elif corruption == "metadata":
                    data = self.load("metadata.json"); data["objects"][0]["position"]["x"] = 1
                    self.save("metadata.json", data)
                elif corruption == "duplicate":
                    data = self.load("objects.json"); data.append(copy.deepcopy(data[0])); self.save("objects.json", data)
                elif corruption == "path":
                    data = self.load("views.json"); data["views"][0]["depth"] = "../outside.npy"
                    self.save("views.json", data)
                elif corruption == "shape":
                    np.save(self.root / "depth.npy", np.ones((1, 1), dtype=np.float32))
                else:
                    with np.load(self.root / "masks.npz") as archive:
                        data = {key: archive[key] for key in archive.files}
                    data["mask_0000"] = data["mask_0000"].astype(np.uint8)
                    np.savez_compressed(self.root / "masks.npz", **data)
                with self.assertRaises(DataError):
                    build_visible_gt(self.root)

    def test_publication_and_overwrite_protection(self):
        result = build_visible_gt(self.root)
        output = Path(self.temp.name) / "output"
        write_artifacts(result, output)
        original = (output / "visible/view_1.json").read_bytes()
        with self.assertRaises(DataError):
            write_artifacts(result, output)
        self.assertEqual((output / "visible/view_1.json").read_bytes(), original)
        self.assertEqual(len(result["input_manifest"]["inputs_sha256"]), 8)


class CapturedSceneAcceptanceTests(unittest.TestCase):
    def test_20261105_scene(self):
        scene = Path(__file__).resolve().parents[1] / "colab/scene_output/20261105T120357_736949Z"
        if not scene.is_dir():
            self.skipTest("Local captured scene is not installed")
        result = build_visible_gt(scene)
        self.assertEqual(result["review_tasks"], [])
        expected = [(11, 8, 0, 55, 55), (23, 15, 0, 253, 253),
                    (56, 25, 4, 1540, 1530), (43, 16, 1, 903, 903)]
        for index, (nodes, on, inside, left, closer) in enumerate(expected, 1):
            report = result["validation_report"]["views"][f"view_{index}"]
            self.assertEqual(report["node_count"], nodes)
            self.assertEqual(report["relations"], dict(on=on, inside=inside,
                             image_left_of=left, closer_to_camera=closer))
            self.assertEqual(report["edge_count"], on + inside + left + closer)
        self.assertEqual(result["validation_report"]["views"]["view_3"]["equal_pair_count"], 10)
        self.assertEqual(result["validation_report"]["views"]["view_4"]["excluded_parent_count"], 1)


if __name__ == "__main__":
    unittest.main()

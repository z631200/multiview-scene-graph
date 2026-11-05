"""Exercise the notebook's actual capture cells without AI2-THOR or Colab."""

import ast
import copy
import csv
import json
import math
import pickle
import numpy as np
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch


NOTEBOOK = Path(__file__).resolve().parents[1] / "colab" / "AI2_THOR_Scene_Capture.ipynb"
CELLS = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def code_cell(prefix):
    return next(
        "".join(cell["source"]) for cell in CELLS
        if cell["cell_type"] == "code" and "".join(cell["source"]).startswith(prefix)
    )


def obj(object_id, visible=False, view=0):
    return dict(objectId=object_id, objectType="Cup", name=f"Cup_{object_id}",
                position=dict(x=view / 10, y=1.0, z=-1.25),
                rotation=dict(x=0.0, y=90.0, z=0.0), visible=visible,
                distance=view + 0.5, parentReceptacles=["CounterTop"])


def FakeMask(count):
    mask = np.zeros((4, 4), dtype=bool)
    mask.flat[:count] = True
    return mask


class FakeController:
    def __init__(self, initial_objects, captures):
        self.initial_objects = initial_objects
        self.captures = iter(captures)
        self.events = []
        self.last_position = None
        self.third_party_cameras = []
        self.server = SimpleNamespace(camera_near_plane=0.1, camera_far_plane=20.0)

    def step(self, action, **kwargs):
        pixel_counts = {}
        segmentation_enabled = True
        if action == "ResetObjectFilter":
            metadata = dict(lastActionSuccess=True, objects=self.initial_objects)
        elif action == "GetReachablePositions":
            metadata = dict(lastActionSuccess=True, actionReturn=[
                dict(x=x, y=0.9, z=z) for x, z in ((0, 0), (2, 0), (2, 2), (0, 2))
            ])
        elif action == "GetMapViewCameraProperties":
            metadata = dict(lastActionSuccess=True, actionReturn=dict(
                position=dict(x=1.0, y=2.8, z=1.0), rotation=dict(x=90, y=0, z=0),
                orthographic=True, orthographicSize=2.0))
            segmentation_enabled = False
        elif action in ("AddThirdPartyCamera", "UpdateThirdPartyCamera"):
            if action == "AddThirdPartyCamera":
                self.third_party_cameras.append(dict(thirdPartyCameraId=len(self.third_party_cameras)))
            else:
                assert kwargs["thirdPartyCameraId"] < len(self.third_party_cameras)
            # Deliberately omit object/mask data: reference capture must not need it.
            metadata = dict(lastActionSuccess=True, thirdPartyCameras=copy.deepcopy(self.third_party_cameras))
            segmentation_enabled = False
        else:
            assert action == "Teleport"
            capture = next(self.captures)
            pixel_counts = capture.get("pixel_counts", {})
            segmentation_enabled = capture.get("segmentation_enabled", True)
            position = self.last_position if capture.get("repeat") else kwargs["position"]
            metadata = dict(lastActionSuccess=capture.get("success", True),
                            errorMessage="fake teleport failure", objects=capture["objects"],
                            agent=dict(position=position, rotation=kwargs["rotation"], cameraHorizon=kwargs["horizon"]),
                            cameraPosition=position, fov=90)
            if metadata["lastActionSuccess"]:
                self.last_position = position
        event = SimpleNamespace(
            metadata=metadata, frame=np.zeros((4, 4, 3), dtype=np.uint8),
            depth_frame=np.arange(16, dtype=np.float32).reshape(4, 4) + len(self.events) + 1,
            object_id_to_color={key: (i + 1, 0, 0) for i, key in enumerate(pixel_counts)},
            third_party_camera_frames=[bytearray(b"fake overhead frame") for _ in self.third_party_cameras],
            instance_segmentation_frame=np.zeros((4, 4, 3), dtype=np.uint8) if segmentation_enabled else None,
            instance_masks={key: FakeMask(count) for key, count in pixel_counts.items()}
                           if segmentation_enabled else None,
        )
        self.events.append(event)
        self.last_event = event
        return event


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output_dir = Path(self.temp.name)
        self.initial_objects = [obj("first"), obj("later"), obj("initial_only", True), obj("never")]

    def context(self, captures, num_views=4):
        controller = FakeController(self.initial_objects, captures)
        context = dict(controller=controller, Path=Path, copy=copy, json=json, math=math,
                       csv=csv, np=np, IMAGE_SIZE=4, output_dir=self.output_dir, NUM_VIEWS=num_views,
                       SCENE="FloorPlan1", HORIZON=0, _overhead_camera_id=None,
                       ai2thor=SimpleNamespace(__version__="fake"),
                       show_objects_table=lambda objects: None, plot_frames=lambda event: None,
                       Image=SimpleNamespace(fromarray=lambda frame: SimpleNamespace(
                           save=lambda path: path.write_bytes(bytes(frame)))),
                       print=lambda *args: None)
        exec(code_cell("event = controller.step(action='ResetObjectFilter')"), context)
        return context

    def capture(self, context):
        exec(code_cell("# Invalidate a prior"), context)
        return json.loads((self.output_dir / "objects.json").read_text(encoding="utf-8"))

    def captures(self, num_views):
        # These objects are rendered in the image despite native visible=False.
        return [dict(objects=[obj("first", False, view),
                              obj("later", False, view),
                              obj("initial_only", False, view), obj("never", False, view)] +
                     ([obj("new", False, view)] if view >= 3 else []),
                     pixel_counts={1: {"first": 8}, 2: {"later": 1},
                                   3: {"first": 3, "new": 2}, 4: {"later": 4}}[view])
                for view in range(1, num_views + 1)]

    def test_union_and_simplified_export_for_three_and_four_views(self):
        for num_views in (3, 4):
            with self.subTest(num_views=num_views):
                context = self.context(self.captures(num_views), num_views)
                result = self.capture(context)
                by_id = {item["objectId"]: item for item in result}
                self.assertEqual({key for key, item in by_id.items() if item["visible"]},
                                 {"first", "later", "new"})
                self.assertEqual(set(by_id), {"first", "later", "initial_only", "never", "new"})
                expected_views = {"first": ["view_1", "view_3"],
                                  "later": ["view_2"] + (["view_4"] if num_views == 4 else []),
                                  "new": ["view_3"], "initial_only": [], "never": []}
                for object_id, item in by_id.items():
                    self.assertEqual(item, dict(obj(object_id, item["visible"], num_views),
                                                ai2thor_visible=False, visible_views=expected_views[object_id]))
                    self.assertEqual(item["visible"], bool(item["visible_views"]))
                visible = json.loads((self.output_dir / "visible_objects.json").read_text(encoding="utf-8"))
                self.assertEqual(visible, [
                    {key: item[key] for key in ("objectId", "objectType", "name", "position", "rotation", "visible_views")}
                    for item in result if item["visible"]
                ])
                with (self.output_dir / "objects.csv").open(encoding="utf-8-sig", newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual({row["objectId"] for row in rows}, set(by_id))
                self.assertTrue(all(float(row["position_x"]) == num_views / 10 for row in rows))
                manifest = json.loads((self.output_dir / "views.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest["num_views"], num_views)
                self.assertEqual(manifest["object_count"], len(result))
                self.assertEqual(manifest["visibility_source"], "instance_masks")
                self.assertEqual(manifest["min_visible_pixels"], 1)
                self.assertEqual([view["visible_object_pixel_counts"] for view in manifest["views"]],
                                 [capture["pixel_counts"] for capture in self.captures(num_views)])
                for index, view in enumerate(manifest["views"], 1):
                    self.assertEqual(view["view_id"], f"view_{index}")
                    self.assertTrue((self.output_dir / view["image"]).is_file())
                    self.assertEqual(
                        {item["objectId"] for item in result if view["view_id"] in item["visible_views"]},
                        set(view["visible_object_pixel_counts"]),
                    )
                # Aggregating visibility must not alter AI2-THOR's raw event metadata.
                last_objects = context["controller"].events[-1].metadata["objects"]
                self.assertFalse(next(item for item in last_objects if item["objectId"] == "first")["visible"])
                self.assertTrue(all("visible_views" not in item for item in last_objects))
                self.assertTrue(self.initial_objects[2]["visible"])

    def test_recapture_resets_visibility_and_can_export_empty_list(self):
        context = self.context(self.captures(4))
        first_result = self.capture(context)
        context["controller"].captures = iter([
            dict(objects=[obj(item["objectId"], False, view) for item in first_result])
            for view in range(1, 5)
        ])
        second_result = self.capture(context)
        self.assertTrue(all(item["visible"] is False for item in second_result))
        self.assertTrue(all(item["visible_views"] == [] for item in second_result))
        self.assertEqual(json.loads((self.output_dir / "visible_objects.json").read_text(encoding="utf-8")), [])

    def test_failed_and_duplicate_views_do_not_contribute_visibility(self):
        first, second, third = self.captures(3)
        context = self.context([
            dict(success=False, objects=[obj("failed_only", True)], pixel_counts={"failed_only": 8}), first,
            dict(repeat=True, objects=[obj("duplicate_only", True)], pixel_counts={"duplicate_only": 8}), second, third,
        ], num_views=3)
        result = self.capture(context)
        self.assertEqual({item["objectId"] for item in result},
                         {"first", "later", "initial_only", "never", "new"})
        self.assertEqual(next(item for item in result if item["objectId"] == "first")["visible_views"],
                         ["view_1", "view_3"])
        self.assertEqual(len(context["views"]), 3)

    def test_distant_and_one_pixel_objects_are_included_without_native_visibility(self):
        far = obj("far", False)
        far["distance"] = 5.0
        captures = [dict(objects=[far, obj("zero_pixels", True), obj("outside_frame", False)],
                         pixel_counts={"far": 1, "zero_pixels": 0, "unannotated_wall": 12})
                    for _ in range(3)]
        context = self.context(captures, num_views=3)
        result = self.capture(context)
        by_id = {item["objectId"]: item for item in result}
        self.assertEqual({key for key, item in by_id.items() if item["visible"]}, {"far"})
        self.assertFalse(by_id["far"]["ai2thor_visible"])
        self.assertEqual(by_id["far"]["visible_views"], ["view_1", "view_2", "view_3"])
        self.assertTrue(by_id["zero_pixels"]["ai2thor_visible"])
        self.assertEqual(by_id["zero_pixels"]["visible_views"], [])
        self.assertNotIn("unannotated_wall", by_id)
        self.assertEqual(context["views"][0]["visible_object_pixel_counts"], {"far": 1})

    def test_missing_segmentation_fails_instead_of_falling_back_to_native_flag(self):
        context = self.context([dict(objects=[obj("native_only", True)], segmentation_enabled=False)])
        with self.assertRaisesRegex(RuntimeError, "renderInstanceSegmentation=True"):
            self.capture(context)
        self.assertFalse((self.output_dir / "objects.json").exists())
        self.assertFalse((self.output_dir / "visible_objects.json").exists())
        self.assertEqual(context["views"], [])

    def test_workspace_creates_controller_with_matching_resolution_and_timeout(self):
        workspace = ast.parse(code_cell("SCENE = "))
        image_size = next(ast.literal_eval(node.value) for node in workspace.body
                          if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == "IMAGE_SIZE"
                                  for target in node.targets))
        self.assertEqual(image_size, 1600)
        creation = next(node for node in ast.walk(workspace)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "Controller")
        options = eval(compile(ast.Expression(creation), "workspace-controller", "eval"),
                       dict(Controller=lambda **kwargs: kwargs, SCENE="FloorPlan1", IMAGE_SIZE=image_size,
                            DepthFormat=SimpleNamespace(Meters="Meters"),
                            os=SimpleNamespace(environ={"DISPLAY": ":91"})))
        self.assertIs(options["renderInstanceSegmentation"], True)
        self.assertIs(options["renderDepthImage"], True)
        self.assertEqual(options["depth_format"], "Meters")
        self.assertEqual((options["width"], options["height"]), (1600, 1600))
        self.assertEqual(options["x_display"], ":91")
        self.assertEqual(options["server_timeout"], 300)

    def test_x11_probe_checks_height_width_glx_and_depth(self):
        startup = ast.parse(code_cell("import os\n"))
        probe = next(node for node in startup.body if isinstance(node, ast.FunctionDef)
                     and node.name == "x11_ready")
        screen = SimpleNamespace(width_in_pixels=1024, height_in_pixels=768, root_depth=24)
        display = SimpleNamespace(screen=lambda: screen, list_extensions=lambda: ["GLX"],
                                  sync=lambda: None, close=lambda: None)

        def run_probe(args, **kwargs):
            with patch.dict(sys.modules, {"Xlib": SimpleNamespace(),
                                          "Xlib.display": SimpleNamespace(Display=lambda: display)}), \
                 patch.object(sys, "argv", ["-c", *args[3:]]):
                try:
                    exec(args[2], {})
                except AssertionError as exc:
                    return SimpleNamespace(returncode=1, stderr=str(exc))
            return SimpleNamespace(returncode=0, stderr="")

        context = dict(os=SimpleNamespace(environ={}), sys=sys,
                       subprocess=SimpleNamespace(run=run_probe, TimeoutExpired=TimeoutError))
        exec(compile(ast.Module(body=[probe], type_ignores=[]), "x11-probe", "exec"), context)
        ready = context["x11_ready"]
        self.assertFalse(ready(":90", min_width=800, min_height=800)[0])
        self.assertTrue(ready(":90", min_width=600, min_height=600)[0])
        self.assertFalse(ready(":90")[0])
        screen.width_in_pixels = screen.height_in_pixels = 1920
        self.assertTrue(ready(":90")[0])
        screen.root_depth = 16
        self.assertFalse(ready(":90")[0])
        screen.root_depth = 24
        display.list_extensions = lambda: []
        self.assertFalse(ready(":90")[0])

    def test_workspace_checks_display_before_start_and_cleans_up_on_timeout(self):
        statements = []
        for node in ast.parse(code_cell("SCENE = ")).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "output_dir"
                                                    for t in node.targets):
                break
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                statements.append(node)
        workspace = compile(ast.Module(body=statements, type_ignores=[]), "workspace-start", "exec")
        stop_function = next(node for node in ast.parse(code_cell("ready, detail = x11_ready")).body
                             if isinstance(node, ast.FunctionDef) and node.name == "stop_controller")
        calls = []

        def factory(**kwargs):
            calls.append("create")
            raise TimeoutError("fake Initialize timeout")

        context = dict(controller=SimpleNamespace(stop=lambda: calls.append("stop")),
                       Controller=factory, DepthFormat=SimpleNamespace(Meters="Meters"), os=SimpleNamespace(environ={"DISPLAY": ":90"}),
                       x11_ready=lambda *args, **kwargs: (False, "1024x768 is too small"),
                       show_thor_logs=lambda: calls.append("logs"), print=lambda *args: None)
        exec(compile(ast.Module(body=[stop_function], type_ignores=[]), "stop-controller", "exec"), context)
        with self.assertRaisesRegex(RuntimeError, "Display cannot fit"):
            exec(workspace, context)
        self.assertEqual(calls, [])
        context["x11_ready"] = lambda *args, **kwargs: (True, "")
        with self.assertRaisesRegex(TimeoutError, "fake Initialize timeout"):
            exec(workspace, context)
        self.assertEqual(calls, ["stop", "create", "logs"])
        self.assertIsNone(context["controller"])

    def test_overhead_only_writes_reference_png_without_changing_capture_data(self):
        overhead_code = code_cell("def save_overhead_reference(")
        for num_views in (3, 4):
            with self.subTest(num_views=num_views):
                (self.output_dir / "view_00.png").unlink(missing_ok=True)
                context = self.context(self.captures(num_views), num_views)
                self.capture(context)
                before_files = {path.name: path.read_bytes() for path in self.output_dir.iterdir()}
                before_state = copy.deepcopy({key: context[key] for key in (
                    "objects", "objects_by_id", "views", "frames", "positions", "manifest")})
                normal_event = context["event"]
                context["visible_object_pixel_counts"] = lambda event: self.fail("Reference used for visibility")
                context["plot_frames"] = lambda event: self.fail("Reference passed to normal view display")
                controller = context["controller"]
                with patch.object(controller, "step", wraps=controller.step) as step:
                    exec(overhead_code, context)
                    exec(overhead_code, context)
                self.assertEqual([call.kwargs["action"] for call in step.call_args_list], [
                    "GetMapViewCameraProperties", "AddThirdPartyCamera",
                    "GetMapViewCameraProperties", "UpdateThirdPartyCamera",
                ])
                add_options = step.call_args_list[1].kwargs
                self.assertIs(add_options["orthographic"], True)
                self.assertEqual(add_options["rotation"], dict(x=90, y=0, z=0))
                self.assertEqual(add_options["position"]["y"], 2.8)
                self.assertIs(add_options["raise_for_failure"], True)
                self.assertEqual(len(controller.third_party_cameras), 1)
                self.assertEqual((self.output_dir / "view_00.png").read_bytes(), b"fake overhead frame")
                after_files = {path.name: path.read_bytes() for path in self.output_dir.iterdir()}
                self.assertEqual(after_files.pop("view_00.png"), b"fake overhead frame")
                self.assertEqual(after_files, before_files)
                self.assertEqual(pickle.dumps({key: context[key] for key in before_state}), pickle.dumps(before_state))
                self.assertIs(context["event"], normal_event)
                self.assertNotIn("camera_event", context)
                self.assertNotIn("map_event", context)
                self.assertNotIn("nearClippingPlane", controller.events[-2].metadata["actionReturn"])

    def test_overhead_failure_preserves_normal_exports(self):
        for failed_action in ("GetMapViewCameraProperties", "AddThirdPartyCamera"):
            with self.subTest(failed_action=failed_action):
                context = self.context(self.captures(4))
                self.capture(context)
                before_files = {path.name: path.read_bytes() for path in self.output_dir.iterdir()}
                controller = context["controller"]
                original_step = controller.step

                def step(action, **kwargs):
                    if action == failed_action:
                        raise RuntimeError("fake overhead failure")
                    return original_step(action, **kwargs)

                with patch.object(controller, "step", side_effect=step):
                    with self.assertRaisesRegex(RuntimeError, "fake overhead failure"):
                        exec(code_cell("def save_overhead_reference("), context)
                self.assertFalse((self.output_dir / "view_00.png").exists())
                self.assertEqual({path.name: path.read_bytes() for path in self.output_dir.iterdir()}, before_files)
                self.assertIsNone(context["_overhead_camera_id"])

    def test_download_requires_and_includes_overhead_reference(self):
        context = self.context(self.captures(4))
        self.capture(context)
        downloads = []
        colab = SimpleNamespace(files=SimpleNamespace(download=downloads.append))
        archive_path = self.output_dir.with_suffix(".zip")
        self.addCleanup(archive_path.unlink, missing_ok=True)
        with patch.dict(sys.modules, {"google": SimpleNamespace(), "google.colab": colab}):
            with self.assertRaisesRegex(RuntimeError, "view_00.png"):
                exec(code_cell("import zipfile\n"), context)
            self.assertEqual(downloads, [])
            exec(code_cell("def save_overhead_reference("), context)
            exec(code_cell("import zipfile\n"), context)
        self.assertEqual(downloads, [str(archive_path)])
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("view_00.png", archive.namelist())
            manifest = json.loads(archive.read("views.json"))
            self.assertEqual(manifest["num_views"], 4)
            self.assertEqual([view["image"] for view in manifest["views"]],
                             [f"view_{index:02d}.png" for index in range(1, 5)])
            self.assertNotIn("view_00", archive.read("visible_objects.json").decode("utf-8"))

    def test_saved_arrays_and_metadata_round_trip(self):
        context = self.context(self.captures(4))
        self.capture(context)
        captures = [e for e in context["controller"].events if "agent" in e.metadata]
        for view, event in zip(context["views"], captures):
            depth = np.load(self.output_dir / view["depth"], allow_pickle=False)
            np.testing.assert_array_equal(depth, event.depth_frame)
            self.assertEqual(depth.dtype, np.float32)
            raw = json.loads((self.output_dir / view["metadata"]).read_text(encoding="utf-8"))
            self.assertEqual(raw, event.metadata)
            self.assertTrue(all("visible_views" not in item for item in raw["objects"]))
            self.assertEqual(view["camera"]["camera_horizon"], event.metadata["agent"]["cameraHorizon"])
            self.assertEqual((view["image_width"], view["image_height"]), (4, 4))
            mapping = json.loads((self.output_dir / view["segmentation_mapping"]).read_text())
            with np.load(self.output_dir / view["instance_masks"], allow_pickle=False) as masks:
                self.assertEqual(masks["object_ids"].tolist(), list(view["visible_object_pixel_counts"]))
                for entry in mapping["masks"]:
                    np.testing.assert_array_equal(masks[entry["key"]], event.instance_masks[entry["objectId"]])
                    self.assertEqual(masks[entry["key"]].dtype, np.bool_)
                    self.assertEqual(int(masks[entry["key"]].sum()), entry["pixel_count"])

    def test_missing_depth_or_misaligned_arrays_rejected(self):
        context = self.context(self.captures(3), 3)
        self.capture(context)
        event = copy.deepcopy(context["event"])
        counts = context["visible_object_pixel_counts"](event)
        for value, pattern in ((None, "Depth unavailable"), (np.ones((2, 2)), "Depth shape")):
            event.depth_frame = value
            with self.assertRaisesRegex(RuntimeError, pattern):
                context["save_view_data"](event, self.output_dir, 9, counts)
            self.assertFalse((self.output_dir / "metadata_09.json").exists())
        event.depth_frame = np.ones((4, 4), dtype=np.float32)
        object_id = next(iter(counts))
        event.instance_masks[object_id] = np.ones((2, 2), dtype=bool)
        with self.assertRaisesRegex(RuntimeError, "Mask shape/count"):
            context["save_view_data"](event, self.output_dir, 9, counts)

    def test_invalid_depth_preserved_and_reported(self):
        context = self.context(self.captures(3), 3)
        self.capture(context)
        event = copy.deepcopy(context["event"])
        event.depth_frame.flat[:3] = [np.nan, np.inf, 0]
        info = context["save_view_data"](event, self.output_dir, 9,
                                         context["visible_object_pixel_counts"](event))
        self.assertEqual(info["depth_info"]["invalid_pixel_count"], 3)
        np.testing.assert_array_equal(np.load(self.output_dir / info["depth"]), event.depth_frame)

    def test_failed_recapture_invalidates_manifest(self):
        context = self.context(self.captures(3), 3)
        self.capture(context)
        context["controller"].captures = iter([dict(objects=[obj("bad")], segmentation_enabled=False)])
        with self.assertRaises(RuntimeError):
            self.capture(context)
        self.assertFalse((self.output_dir / "views.json").exists())
        colab = SimpleNamespace(files=SimpleNamespace(download=lambda path: self.fail("Downloaded failed capture")))
        with patch.dict(sys.modules, {"google": SimpleNamespace(), "google.colab": colab}):
            with self.assertRaisesRegex(RuntimeError, "Capture incomplete"):
                exec(code_cell("import zipfile\n"), context)

    def test_zip_excludes_old_views_and_requires_per_view_data(self):
        context = self.context(self.captures(4))
        self.capture(context)
        context["NUM_VIEWS"] = 3
        context["controller"].captures = iter(self.captures(3))
        self.capture(context)
        exec(code_cell("def save_overhead_reference("), context)
        (self.output_dir / "ground_truth_scene_graph.json").write_text("{}")
        archive_path = self.output_dir.with_suffix(".zip")
        self.addCleanup(archive_path.unlink, missing_ok=True)
        colab = SimpleNamespace(files=SimpleNamespace(download=lambda path: None))
        with patch.dict(sys.modules, {"google": SimpleNamespace(), "google.colab": colab}):
            exec(code_cell("import zipfile\n"), context)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertNotIn("view_04.png", archive.namelist())
                self.assertNotIn("depth_04.npy", archive.namelist())
                self.assertNotIn("ground_truth_scene_graph.json", archive.namelist())
                self.assertIn("depth_03.npy", archive.namelist())
                self.assertIn("instance_masks_03.npz", archive.namelist())
            (self.output_dir / "depth_02.npy").unlink()
            with self.assertRaisesRegex(RuntimeError, "depth_02.npy"):
                exec(code_cell("import zipfile\n"), context)

    def test_all_python_cells_compile(self):
        for index, cell in enumerate(CELLS):
            source = "".join(cell["source"])
            if cell["cell_type"] == "code" and not source.startswith("!"):
                compile(source, f"{NOTEBOOK.name}:cell_{index}", "exec")


if __name__ == "__main__":
    unittest.main()

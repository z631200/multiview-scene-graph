"""Exercise the notebook's actual capture cells without AI2-THOR or Colab."""

import ast
import copy
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
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


class FakeMask:
    def __init__(self, count):
        self.pixels = [True] * count + [False]

    def sum(self):
        return sum(self.pixels)


class FakeController:
    def __init__(self, initial_objects, captures):
        self.initial_objects = initial_objects
        self.captures = iter(captures)
        self.events = []
        self.last_position = None

    def step(self, action, **kwargs):
        pixel_counts = {}
        segmentation_enabled = True
        if action == "ResetObjectFilter":
            metadata = dict(lastActionSuccess=True, objects=self.initial_objects)
        elif action == "GetReachablePositions":
            metadata = dict(lastActionSuccess=True, actionReturn=[
                dict(x=x, y=0.9, z=z) for x, z in ((0, 0), (2, 0), (2, 2), (0, 2))
            ])
        else:
            assert action == "Teleport"
            capture = next(self.captures)
            pixel_counts = capture.get("pixel_counts", {})
            segmentation_enabled = capture.get("segmentation_enabled", True)
            position = self.last_position if capture.get("repeat") else kwargs["position"]
            metadata = dict(lastActionSuccess=capture.get("success", True),
                            errorMessage="fake teleport failure", objects=capture["objects"],
                            agent=dict(position=position, rotation=kwargs["rotation"]),
                            cameraPosition=position, fov=90)
            if metadata["lastActionSuccess"]:
                self.last_position = position
        event = SimpleNamespace(
            metadata=metadata, frame=bytearray(b"fake frame"),
            instance_segmentation_frame=bytearray(b"segmentation") if segmentation_enabled else None,
            instance_masks={key: FakeMask(count) for key, count in pixel_counts.items()}
                           if segmentation_enabled else None,
        )
        self.events.append(event)
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
                       csv=csv, output_dir=self.output_dir, NUM_VIEWS=num_views,
                       SCENE="FloorPlan1", HORIZON=0,
                       ai2thor=SimpleNamespace(__version__="fake"),
                       show_objects_table=lambda objects: None, plot_frames=lambda event: None,
                       Image=SimpleNamespace(fromarray=lambda frame: SimpleNamespace(
                           save=lambda path: path.write_bytes(bytes(frame)))),
                       print=lambda *args: None)
        exec(code_cell("event = controller.step(action='ResetObjectFilter')"), context)
        return context

    def capture(self, context):
        exec(code_cell("event = controller.step(action='GetReachablePositions')"), context)
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
                    {key: item[key] for key in ("name", "position", "rotation", "visible_views")}
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
        creation = next(node for node in ast.walk(workspace)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "Controller")
        options = eval(compile(ast.Expression(creation), "workspace-controller", "eval"),
                       dict(Controller=lambda **kwargs: kwargs, SCENE="FloorPlan1", IMAGE_SIZE=800,
                            os=SimpleNamespace(environ={"DISPLAY": ":91"})))
        self.assertIs(options["renderInstanceSegmentation"], True)
        self.assertEqual((options["width"], options["height"]), (800, 800))
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
                       Controller=factory, os=SimpleNamespace(environ={"DISPLAY": ":90"}),
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

    def test_all_python_cells_compile(self):
        for index, cell in enumerate(CELLS):
            source = "".join(cell["source"])
            if cell["cell_type"] == "code" and not source.startswith("!"):
                compile(source, f"{NOTEBOOK.name}:cell_{index}", "exec")


if __name__ == "__main__":
    unittest.main()

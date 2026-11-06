"""Regression tests using metadata and fake controllers, never Unity."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scene_capture.demo.benchmark_referee import Referee
from scene_capture.demo.demo_task import ACTION_PLAN, build_task
from scene_capture.demo.main import main, run_plan
from scene_capture.demo.robot_interface import RobotInterface
from scene_capture.demo.simulation_platform import SimulationPlatform
from scene_capture.demo.task_definition import TaskDefinition


class FakeController:
    def __init__(self, objects=None):
        self.calls = []
        self.last_event = SimpleNamespace(
            frame=None,
            metadata={"objects": objects or [], "lastActionSuccess": True, "errorMessage": ""},
        )

    def reset(self, **kwargs):
        self.reset_kwargs = kwargs

    def step(self, **kwargs):
        self.calls.append(kwargs)
        return self.last_event


class GoalTests(unittest.TestCase):
    def test_demo_goal(self):
        objects = [
            {"objectId": "CounterTop|1", "objectType": "CounterTop", "receptacle": True},
            {"objectId": "Bowl|1", "objectType": "Bowl", "receptacle": True,
             "parentReceptacles": ["CounterTop|1"]},
            {"objectId": "PotatoSliced|1", "objectType": "PotatoSliced",
             "parentReceptacles": ["Bowl|1"], "isCooked": True},
            {"objectId": "Drawer|1", "openable": True, "isOpen": False},
        ]
        task = build_task()
        referee = Referee()
        self.assertTrue(referee.check_success(task, {"objects": objects})["is_success"])
        objects[2]["isCooked"] = False
        self.assertFalse(referee.check_success(task, {"objects": objects})["is_success"])
        objects[2]["isCooked"] = True
        objects[3]["isOpen"] = True
        self.assertFalse(referee.check_success(task, {"objects": objects})["is_success"])

    def test_empty_goal_is_not_success(self):
        task = TaskDefinition("empty", "FloorPlan1", "")
        self.assertFalse(Referee().check_success(task, {"objects": []})["is_success"])

    def test_legacy_conditions_must_match_same_object(self):
        task = TaskDefinition("legacy", "FloorPlan1", "")
        task.add_goal("Potato", "isCooked", True)
        task.add_goal("Potato", "isSliced", True)
        objects = [
            {"objectType": "Potato", "isCooked": True, "isSliced": False},
            {"objectType": "Potato", "isCooked": False, "isSliced": True},
        ]
        self.assertFalse(Referee().check_success(task, {"objects": objects})["is_success"])
        objects[0]["isSliced"] = True
        self.assertTrue(Referee().check_success(task, {"objects": objects})["is_success"])

    def test_invalid_goal_does_not_replace_existing_goal(self):
        task = build_task()
        original = (task.goal_pddl, task.goal_ast)
        with self.assertRaises(ValueError):
            task.set_goal_pddl("(:goal")
        self.assertEqual(original, (task.goal_pddl, task.goal_ast))


class RobotTests(unittest.TestCase):
    def test_toggle_off_filters_non_toggleable_objects(self):
        controller = FakeController([
            {"objectId": "Microwave|bad", "objectType": "Microwave", "visible": True},
            {"objectId": "Microwave|good", "objectType": "Microwave", "visible": True,
             "toggleable": True},
        ])
        RobotInterface(controller).parse_and_execute("ToggleObjectOff", "microwave")
        self.assertEqual(controller.calls[0]["objectId"], "Microwave|good")

    def test_wait_does_not_repeat_previous_failure(self):
        controller = FakeController()
        controller.last_event.metadata["lastActionSuccess"] = False
        self.assertTrue(RobotInterface(controller).parse_and_execute("Wait", 0)["success"])
        self.assertEqual(controller.calls, [])

    def test_invalid_durations_and_angles(self):
        robot = RobotInterface(FakeController())
        for action, value in [("Wait", -1), ("Wait", float("inf")),
                              ("RotateLeft", float("inf")), ("LookUp", float("nan"))]:
            with self.subTest(action=action, value=value):
                self.assertFalse(robot.parse_and_execute(action, value)["success"])
        self.assertTrue(robot.parse_and_execute("RotateLeft", 0)["success"])

    def test_put_uses_pinned_api_without_retry(self):
        controller = FakeController()
        controller.last_event.metadata["lastActionSuccess"] = False
        result = RobotInterface(controller).parse_and_execute("PutObject", "Bowl|1")
        self.assertFalse(result["success"])
        self.assertEqual(controller.calls, [
            {"action": "PutObject", "objectId": "Bowl|1", "forceAction": False}
        ])

    def test_teleport_requires_coordinates(self):
        controller = FakeController()
        robot = RobotInterface(controller)
        self.assertFalse(robot.parse_and_execute("Teleport", "knife")["success"])
        position = {"x": 1, "y": 0.9, "z": 2}
        self.assertTrue(robot.parse_and_execute("Teleport", position)["success"])
        self.assertEqual(controller.calls, [{"action": "Teleport", "position": position}])


class PlatformTests(unittest.TestCase):
    def test_rendering_mode_selection(self):
        for headless in (False, True):
            with self.subTest(headless=headless):
                controller = Mock()
                constructor = Mock(return_value=controller)
                cloud_rendering = object()
                modules = {
                    "ai2thor": SimpleNamespace(),
                    "ai2thor.controller": SimpleNamespace(Controller=constructor),
                    "ai2thor.platform": SimpleNamespace(CloudRendering=cloud_rendering),
                }
                with patch.dict(sys.modules, modules):
                    with patch("scene_capture.demo.main.SimulationPlatform"), patch("scene_capture.demo.main.run_plan"):
                        main(["--headless"] if headless else [])
                expected = {"width": 600, "height": 600}
                if headless:
                    expected["platform"] = cloud_rendering
                constructor.assert_called_once_with(**expected)
                controller.stop.assert_called_once()

    def test_load_step_save_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            logfile = Path(directory) / "nested" / "trace.json"
            controller = FakeController()
            platform = SimulationPlatform(controller, log_path=str(logfile))
            with self.assertRaises(RuntimeError):
                platform.run_step("Wait", 0)
            platform.load_task(build_task())
            self.assertEqual(controller.reset_kwargs, {"scene": "FloorPlan1", "gridSize": 0.25})
            platform.run_step("Wait", 0)
            platform.finish()
            saved = json.loads(logfile.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["action"], "Wait")
            self.assertTrue(saved[0]["success"])
            platform.load_task(build_task())
            self.assertEqual(platform.step_count, 0)
            self.assertEqual(platform.logger.history, [])

    def test_exact_post_success_steps(self):
        for extra in (0, 3):
            with self.subTest(extra=extra):
                platform = SimpleNamespace(run_step=lambda *args: {
                    "feedback": "", "goal_details": {}, "task_done": True
                })
                with patch.object(platform, "run_step", wraps=platform.run_step) as step:
                    run_plan(platform, ACTION_PLAN, step_delay=0, post_success_steps=extra)
                    self.assertEqual(step.call_count, 1 + extra)

    def test_controller_stopped_even_when_save_fails(self):
        controller = Mock()
        fake_module = SimpleNamespace(Controller=lambda **kwargs: controller)
        with patch.dict(sys.modules, {"ai2thor": SimpleNamespace(), "ai2thor.controller": fake_module}):
            with patch("scene_capture.demo.main.SimulationPlatform") as platform_type:
                platform = platform_type.return_value
                platform.load_task.side_effect = RuntimeError("reset failed")
                platform.finish.side_effect = OSError("save failed")
                with self.assertRaises(OSError):
                    main(["--no-video"])
                platform.finish.assert_called_once()
                controller.stop.assert_called_once()

    def test_video_open_failure_releases_writer(self):
        writer = Mock()
        writer.isOpened.return_value = False
        cv2 = SimpleNamespace(
            VideoWriter=Mock(return_value=writer),
            VideoWriter_fourcc=Mock(return_value=0),
        )
        with tempfile.TemporaryDirectory() as directory:
            platform = SimulationPlatform(
                FakeController(), record_video=True,
                video_path=str(Path(directory) / "run.mp4"),
            )
            with patch.dict(sys.modules, {"cv2": cv2}):
                with self.assertRaises(RuntimeError):
                    platform._on_frame_captured(SimpleNamespace(shape=(600, 600, 3)))
            writer.release.assert_called_once()
            self.assertIsNone(platform._video_writer)

    def test_help_without_third_party_packages(self):
        result = subprocess.run(
            [sys.executable, "-S", "-m", "scene_capture.demo", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("--no-video", result.stdout)
        self.assertIn("--headless", result.stdout)


if __name__ == "__main__":
    unittest.main()

"""Configuration precedence, portable paths, tracked samples, and module entrypoints."""

import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common.config import parse_config_args, snapshot
from common.paths import ROOT, default_gt_directory


class ProjectLayoutTests(unittest.TestCase):
    def test_cli_overrides_yaml_and_types_are_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "config.yaml"
            config.write_text("seed: 7\nscene_dir: input/basic\nview: [view_1, view_3]\n")
            parser = argparse.ArgumentParser()
            parser.add_argument("--seed", type=int, default=42)
            parser.add_argument("--scene-dir", type=Path, required=True)
            parser.add_argument("--view", nargs="+")
            args = parse_config_args(parser, ["--config", str(config), "--seed", "9"])
            self.assertEqual(args.seed, 9)
            self.assertEqual(args.scene_dir, Path("input/basic"))
            self.assertEqual(args.view, ["view_1", "view_3"])

    def test_bad_yaml_unknown_keys_and_mutual_exclusion(self):
        for content in ("seed: true", "unknown: 1", "!!python/object/apply:os.system ['bad']",
                        "first: true\nsecond: true"):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp:
                config = Path(temp) / "config.yaml"
                config.write_text(content)
                parser = argparse.ArgumentParser()
                parser.add_argument("--seed", type=int)
                group = parser.add_mutually_exclusive_group()
                group.add_argument("--first", action="store_true")
                group.add_argument("--second", action="store_true")
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    parse_config_args(parser, ["--config", str(config)])

    def test_gt_path_pairs_both_kinds_under_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            basic = Path(temp) / "FloorPlan1/capture_001/basic"
            basic.mkdir(parents=True)
            self.assertEqual(default_gt_directory(basic, "gt_001", "visible"), basic.parent / "gt/gt_001/visible")
            self.assertEqual(default_gt_directory(basic, "gt_001", "full"), basic.parent / "gt/gt_001/full")

    def test_snapshots_are_portable_yaml(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.yaml"
            snapshot(path, dict(scene_dir=Path("data/scenes/test/basic"), seed=42))
            self.assertEqual(json.loads(path.read_text())["seed"], 42)

    def test_samples_are_unignored_and_generated_data_are_ignored(self):
        for name, ignored in [("data/scenes/sample/test.json", False), ("data/runs/sample/test.json", False),
                              ("data/scenes/FloorPlan1/test.json", True), ("data/runs/exp_001/test.json", True)]:
            result = subprocess.run(["git", "check-ignore", "--no-index", name], cwd=ROOT, capture_output=True)
            self.assertEqual(result.returncode, 0 if ignored else 1, name)

    def test_standard_library_entrypoints_work_without_site_packages(self):
        for module in ("scene_capture.local", "scene_capture.demo", "gt.full", "reasoning", "visualization"):
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, "-S", "-m", module, "--help"], cwd=ROOT,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

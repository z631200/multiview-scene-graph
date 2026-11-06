"""Local capture parity, downstream compatibility and resource cleanup without Unity."""

import contextlib
import copy
import csv
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

import numpy as np
from PIL import Image

import scene_capture.local.capture as local
from gt.full.generate import build_full_gt
from reasoning.pipeline import load_scene
from test_scene_capture import FakeController, code_cell, obj
from gt.visible.generate import build_visible_gt


class LocalController(FakeController):
    def __init__(self, objects, captures):
        super().__init__(objects, captures)
        self.stop = Mock()
        self.last_event = SimpleNamespace(
            metadata={'lastActionSuccess': True},
            instance_segmentation_frame=np.zeros((4, 4, 3), dtype=np.uint8),
            depth_frame=np.ones((4, 4), dtype=np.float32),
        )

    def step(self, action, **kwargs):
        event = super().step(action, **kwargs)
        event.third_party_camera_frames = [
            np.full((4, 4, 3), 42, dtype=np.uint8) for _ in self.third_party_cameras]
        return event


class LocalCaptureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / 'capture'
        self.objects = [obj('cup'), obj('counter'), obj('never', True)]
        for item in self.objects:
            item['parentReceptacles'] = None
        self.objects[0]['parentReceptacles'] = ['counter']
        self.objects[1]['objectType'] = 'CounterTop'

    def controller(self, num_views=4):
        counts = [{'cup': 1, 'counter': 8}, {'counter': 5}, {'cup': 2}, {}]
        return LocalController(self.objects, [
            dict(objects=copy.deepcopy(self.objects), pixel_counts=count)
            for count in counts[:num_views]])

    def capture(self, controller=None, num_views=4):
        controller = controller or self.controller(num_views)
        with contextlib.redirect_stdout(io.StringIO()):
            manifest = local.capture_scene(
                controller, self.output, image_size=4, num_views=num_views,
                ai2thor_version='fake')
        return manifest

    def test_local_exports_match_notebook_for_three_and_four_views(self):
        for num_views in (3, 4):
            with self.subTest(num_views=num_views):
                self.output = self.root / f'local-{num_views}'
                manifest = self.capture(num_views=num_views)
                notebook_dir = self.root / f'notebook-{num_views}'
                notebook_dir.mkdir()
                notebook = dict(
                    controller=self.controller(num_views), output_dir=notebook_dir,
                    Path=Path, copy=copy, csv=csv, json=json, math=math, np=np, Image=Image,
                    SCENE='FloorPlan1', NUM_VIEWS=num_views, IMAGE_SIZE=4, HORIZON=0,
                    ai2thor=SimpleNamespace(__version__='fake'), _overhead_camera_id=None,
                    show_objects_table=lambda *_: None, plot_frames=lambda *_: None,
                    print=lambda *_: None,
                )
                exec(code_cell("event = controller.step(action='ResetObjectFilter')"), notebook)
                exec(code_cell('# Invalidate a prior'), notebook)
                exec(code_cell('def save_overhead_reference('), notebook)
                self.assertEqual(manifest, notebook['manifest'])
                for path in notebook_dir.iterdir():
                    actual = self.output / path.name
                    if path.suffix == '.json':
                        self.assertEqual(json.loads(actual.read_text()), json.loads(path.read_text()))
                    elif path.suffix == '.npy':
                        np.testing.assert_array_equal(np.load(actual), np.load(path))
                    elif path.suffix == '.npz':
                        with np.load(actual, allow_pickle=False) as a, np.load(path, allow_pickle=False) as b:
                            self.assertEqual(a.files, b.files)
                            for key in a.files:
                                np.testing.assert_array_equal(a[key], b[key])
                    else:
                        self.assertEqual(actual.read_bytes(), path.read_bytes())

    def test_outputs_feed_existing_graph_and_both_gt_generators(self):
        manifest = self.capture()
        scene = load_scene(self.output)
        self.assertEqual(set(scene['images']), {'view_1', 'view_2', 'view_3', 'view_4'})
        visible = build_visible_gt(self.output)
        full = build_full_gt(self.output)
        self.assertEqual(set(visible['graphs']), set(full['graphs']))
        self.assertEqual(len(full['graphs']), 4)
        self.assertEqual(visible['graphs']['view_4']['nodes'], [])
        objects = json.loads((self.output / 'objects.json').read_text())
        cup = next(item for item in objects if item['objectId'] == 'cup')
        self.assertEqual(cup['visible_views'], ['view_1', 'view_3'])
        self.assertFalse(cup['ai2thor_visible'])
        self.assertEqual(manifest['num_views'], 4)
        self.assertFalse(manifest['reference_image_used_for_computation'])
        with Image.open(self.output / 'view_00.png') as reference:
            self.assertEqual(reference.size, (4, 4))
        with Image.open(self.output / 'viewpoints.png') as plot:
            self.assertGreater(plot.width, 100)

    def test_zip_whitelist_and_missing_data(self):
        self.capture()
        (self.output / 'old_scene_graph.json').write_text('{}')
        archive_path = local.archive_capture(self.output)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertEqual(len(archive.namelist()), 31)
            self.assertIn('view_00.png', archive.namelist())
            self.assertNotIn('old_scene_graph.json', archive.namelist())
        with self.assertRaises(FileExistsError):
            local.archive_capture(self.output)
        archive_path.unlink()
        (self.output / 'depth_02.npy').unlink()
        with self.assertRaisesRegex(RuntimeError, 'depth_02.npy'):
            local.archive_capture(self.output)
        self.assertFalse(archive_path.exists())

    def test_failed_capture_does_not_publish_manifest(self):
        for failure in ('segmentation', 'depth', 'overhead', 'plot'):
            with self.subTest(failure=failure):
                self.output = self.root / failure
                controller = self.controller()
                original_step = controller.step

                def step(action, **kwargs):
                    if failure == 'overhead' and action == 'GetMapViewCameraProperties':
                        raise RuntimeError('overhead failure')
                    event = original_step(action, **kwargs)
                    if action == 'Teleport' and failure == 'segmentation':
                        event.instance_segmentation_frame = None
                    if action == 'Teleport' and failure == 'depth':
                        event.depth_frame = None
                    return event

                with patch.object(controller, 'step', side_effect=step), \
                        patch.object(local, 'save_viewpoints',
                                     side_effect=RuntimeError('plot failure') if failure == 'plot'
                                     else local.save_viewpoints):
                    with self.assertRaises(RuntimeError):
                        self.capture(controller)
                self.assertFalse((self.output / 'views.json').exists())

    def test_run_uses_cloud_rendering_and_stops_on_success_or_failure(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                output = self.root / str(fail)
                controller = self.controller()
                factory = Mock(return_value=controller)
                cloud = object()
                modules = {
                    'ai2thor': SimpleNamespace(__version__='fake'),
                    'ai2thor.controller': SimpleNamespace(Controller=factory),
                    'ai2thor.server': SimpleNamespace(DepthFormat=SimpleNamespace(Meters='Meters')),
                    'ai2thor.platform': SimpleNamespace(CloudRendering=cloud),
                }
                args = local.build_parser().parse_args([
                    '--headless', '--output-dir', str(output), '--zip', '--horizon', '15'])
                original = local.save_overhead_reference
                with patch.dict(sys.modules, modules), patch.object(sys, 'platform', 'linux'), \
                        patch.dict(os.environ, {'DISPLAY': ':invalid'}), \
                        patch.object(local, 'save_overhead_reference',
                                     side_effect=RuntimeError('overhead failure') if fail else original), \
                        contextlib.redirect_stdout(io.StringIO()):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'overhead failure'):
                            local.run(args)
                        self.assertFalse((output / 'views.json').exists())
                        self.assertFalse(Path(str(output) + '.zip').exists())
                    else:
                        self.assertEqual(local.run(args), output)
                        self.assertTrue(Path(str(output) + '.zip').is_file())
                controller.stop.assert_called_once()
                options = factory.call_args.kwargs
                self.assertIs(options['platform'], cloud)
                self.assertNotIn('x_display', options)
                self.assertEqual(options['width'], 1600)
                self.assertEqual(options['height'], 1600)
                self.assertTrue(options['renderInstanceSegmentation'])
                self.assertTrue(options['renderDepthImage'])
                self.assertEqual(options['depth_format'], 'Meters')
                self.assertEqual(options['server_timeout'], 300)
                self.assertEqual(options['server_start_timeout'], 300)

    def test_existing_directory_is_preserved_and_cli_checks_values(self):
        self.output.mkdir()
        sentinel = self.output / 'views.json'
        sentinel.write_text('keep')
        args = local.build_parser().parse_args(['--output-dir', str(self.output)])
        with self.assertRaises(FileExistsError):
            local.run(args)
        self.assertEqual(sentinel.read_text(), 'keep')
        for args in (['--num-views', '2'], ['--image-size', '0'], ['--horizon', 'nan'],
                     ['--horizon', '61'], ['--timeout', '0'], ['--timeout', 'inf'],
                     ['--headless', '--display', ':1']):
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    local.build_parser().parse_args(args)

    def test_help_works_without_site_packages(self):
        result = subprocess.run([sys.executable, '-S', '-m', 'scene_capture.local', '--help'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--headless', result.stdout)


if __name__ == '__main__':
    unittest.main()

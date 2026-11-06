"""Capture local AI2-THOR scenes in the Colab notebook's capture-v2 format.

Importing this module or using --help does not load simulator dependencies.
The notebook stays standalone; its capture algorithm and export schema are
preserved here without Colab startup, notebook display helpers or downloads.
"""

from __future__ import annotations

import argparse
import copy
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import zipfile

from common.config import parse_config_args, snapshot
from common.paths import SCENES, safe_name


VIEW_FILE_KEYS = ("image", "depth", "instance_masks", "instance_segmentation",
                  "segmentation_mapping", "metadata")

def visible_object_pixel_counts(event):
    if event.instance_segmentation_frame is None or event.instance_masks is None:
        raise RuntimeError('Instance segmentation is unavailable; capture requires renderInstanceSegmentation=True.')
    counts = {}
    for obj in event.metadata['objects']:
        object_id = obj['objectId']
        mask = event.instance_masks.get(object_id)
        if mask is not None:
            count = int(mask.sum())
            if count > 0:
                counts[object_id] = count
    return counts

def export_visible_objects(scene_dir: Path) -> Path:
    objects = json.loads((scene_dir / 'objects.json').read_text(encoding='utf-8'))
    visible_objects = [
        {key: obj[key] for key in ('objectId', 'objectType', 'name', 'position', 'rotation', 'visible_views')}
        for obj in objects
        if obj.get('visible') is True
    ]
    output_path = scene_dir / 'visible_objects.json'
    output_path.write_text(
        json.dumps(visible_objects, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    return output_path

def save_view_data(controller, event, scene_dir, index, pixel_counts):
    import numpy as np
    from PIL import Image

    # All data must come from this exact successful capture event.
    rgb = np.asarray(event.frame)
    segmentation = np.asarray(event.instance_segmentation_frame)
    if rgb.ndim != 3 or rgb.shape[2] != 3 or segmentation.shape != rgb.shape:
        raise RuntimeError('RGB and instance segmentation must be aligned H x W x 3 arrays')
    height, width = rgb.shape[:2]
    if event.depth_frame is None:
        raise RuntimeError('Depth unavailable; capture requires renderDepthImage=True')
    depth = np.asarray(event.depth_frame, dtype=np.float32)
    if depth.shape != (height, width):
        raise RuntimeError('Depth shape does not match the captured RGB image')
    metadata = copy.deepcopy(event.metadata)
    agent = metadata['agent']
    camera_position = metadata.get('cameraPosition')
    fov = metadata.get('fov')
    if camera_position is None or fov is None or 'cameraHorizon' not in agent:
        raise RuntimeError('Missing cameraPosition, fov or cameraHorizon in capture metadata')
    masks = {}
    mask_index = []
    for object_id, count in pixel_counts.items():
        mask = np.asarray(event.instance_masks[object_id], dtype=bool)
        if mask.shape != (height, width) or int(mask.sum()) != count:
            raise RuntimeError(f'Mask shape/count mismatch: {object_id}')
        mask_key = f'mask_{len(mask_index):04d}'
        masks[mask_key] = mask
        mask_index.append(dict(objectId=object_id, key=mask_key, pixel_count=count))
    # Unicode strings and bool arrays can be loaded with allow_pickle=False.
    masks['object_ids'] = np.asarray(list(pixel_counts), dtype=np.str_)
    suffix = f'{index:02d}'
    paths = dict(image=f'view_{suffix}.png', depth=f'depth_{suffix}.npy',
                 instance_masks=f'instance_masks_{suffix}.npz',
                 instance_segmentation=f'instance_segmentation_v{suffix}.png',
                 segmentation_mapping=f'segmentation_mapping_{suffix}.json',
                 metadata=f'metadata_{suffix}.json')
    colors = {key: [int(value) for value in color]
              for key, color in event.object_id_to_color.items()}
    mapping = dict(view_id=f'view_{index}', masks=mask_index, object_id_to_color=colors,
                   mask_scope='metadata objects with at least one visible pixel',
                   array_order='row_y,column_x', pixel_origin='top_left')
    Image.fromarray(rgb).save(scene_dir / paths['image'])
    Image.fromarray(segmentation).save(scene_dir / paths['instance_segmentation'])
    np.save(scene_dir / paths['depth'], depth, allow_pickle=False)
    np.savez_compressed(scene_dir / paths['instance_masks'], **masks)
    for key, data in (('metadata', metadata), ('segmentation_mapping', mapping)):
        (scene_dir / paths[key]).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    valid = np.isfinite(depth) & (depth > 0)
    return dict(**paths, image_width=width, image_height=height,
                camera=dict(position=camera_position, agent_rotation=agent['rotation'],
                            camera_horizon=agent['cameraHorizon'], vertical_fov=fov,
                            horizon_positive='down', position_unit='meter', rotation_unit='degree'),
                depth_info=dict(unit='meter', dtype='float32', source='event.depth_frame',
                                convention='AI2-THOR native depth; no geometric conversion',
                                invalid_pixel_count=int((~valid).sum()),
                                invalid_values='preserved; finite positive pixels are usable',
                                near_plane=controller.server.camera_near_plane,
                                far_plane=controller.server.camera_far_plane))

def capture_views(controller, output_dir, *, scene, num_views, horizon, image_size, ai2thor_version):
    """Port of the notebook capture; the caller publishes views.json after all exports."""
    event = controller.step(action='ResetObjectFilter')
    if not event.metadata['lastActionSuccess']:
        raise RuntimeError(event.metadata['errorMessage'])
    objects = copy.deepcopy(event.metadata['objects'])
    event = controller.step(action='GetReachablePositions')
    if not event.metadata['lastActionSuccess']:
        raise RuntimeError(event.metadata['errorMessage'])
    positions = event.metadata['actionReturn']
    positions = list({tuple(p[a] for a in 'xyz'): p for p in positions}.values())
    if len(positions) < num_views:
        raise RuntimeError('Not enough views; complete capture or choose another scene.')

    xmin, xmax = min(p['x'] for p in positions), max(p['x'] for p in positions)
    zmin, zmax = min(p['z'] for p in positions), max(p['z'] for p in positions)
    center_x, center_z = (xmin + xmax) / 2, (zmin + zmax) / 2
    corners = [(xmin, zmin), (xmax, zmin), (xmax, zmax), (xmin, zmax)]
    used = set()
    views = []
    # Only saved camera views contribute to the visibility union.
    objects_by_id = {obj['objectId']: copy.deepcopy(obj) for obj in objects}
    for obj in objects_by_id.values():
        obj.setdefault('ai2thor_visible', obj['visible'])
        obj['visible'] = False
        obj['visible_views'] = []
    for index, (corner_x, corner_z) in enumerate(corners[:num_views], 1):
        candidates = sorted(positions, key=lambda p: (p['x'] - corner_x)**2 + (p['z'] - corner_z)**2)
        last_error = ''
        for position in candidates:
            key = tuple(round(position[a], 4) for a in 'xyz')
            if key in used:
                continue
            yaw = math.degrees(math.atan2(center_x - position['x'], center_z - position['z'])) % 360
            event = controller.step(action='Teleport', position=position,
                                    rotation=dict(x=0, y=yaw, z=0), horizon=horizon, standing=True)
            if not event.metadata['lastActionSuccess']:
                last_error = event.metadata['errorMessage']
                continue
            agent = copy.deepcopy(event.metadata['agent'])
            actual_key = tuple(round(agent['position'][a], 4) for a in 'xyz')
            if actual_key in used:
                continue
            pixel_counts = visible_object_pixel_counts(event)
            view_id = f'view_{index}'
            view_files = save_view_data(controller, event, output_dir, index, pixel_counts)
            used.add(actual_key)
            views.append(dict(view_id=view_id, **view_files, agent=agent,
                              cameraPosition=event.metadata.get('cameraPosition'),
                              fov=event.metadata.get('fov'),
                              visible_object_pixel_counts=pixel_counts))
            for obj in event.metadata['objects']:
                object_id = obj['objectId']
                visible_views = list(objects_by_id.get(object_id, {}).get('visible_views', []))
                if object_id in pixel_counts:
                    visible_views.append(view_id)
                objects_by_id[object_id] = copy.deepcopy(obj)
                objects_by_id[object_id]['ai2thor_visible'] = obj['visible']
                objects_by_id[object_id]['visible_views'] = visible_views
                objects_by_id[object_id]['visible'] = bool(visible_views)
            print(view_files['image'], 'position:', agent['position'], 'rotation:', agent['rotation'])
            print(f'Image-visible objects: {len(pixel_counts)}; native AI2-THOR visible: {sum(obj["visible"] for obj in event.metadata["objects"])}')
            break
        else:
            raise RuntimeError(f'Could not capture view {index}: {last_error}')

    objects = list(objects_by_id.values())
    (output_dir / 'objects.json').write_text(
        json.dumps(objects, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    export_visible_objects(output_dir)
    fields = ['objectId', 'objectType', 'name'] + [f'{field}_{axis}' for field in ('position', 'rotation') for axis in 'xyz']
    with (output_dir / 'objects.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for obj in objects:
            row = {key: obj.get(key) for key in ('objectId', 'objectType', 'name')}
            for field in ('position', 'rotation'):
                row.update({f'{field}_{axis}': obj[field][axis] for axis in 'xyz'})
            writer.writerow(row)
    print(f'Exported {len(objects)} objects, {sum(obj["visible"] for obj in objects)} visible across captured views.')

    manifest = dict(schema_version='capture-v2', capture_complete=True, scene=scene, num_views=len(views), ai2thor_version=ai2thor_version,
                    position_unit='meter', rotation_unit='degree',
                    depth_unit='meter', depth_format='Meters', render_depth_image=True,
                    image_size=image_size, reference_image='view_00.png',
                    reference_image_used_for_computation=False,
                    object_snapshot='latest captured view per object', object_count=len(objects),
                    object_visibility='at least one instance segmentation pixel in any captured view',
                    visibility_source='instance_masks', min_visible_pixels=1,
                    look_at_center_xz=dict(x=center_x, z=center_z), views=views)
    (output_dir / 'reachable_positions.json').write_text(json.dumps(positions, indent=2), encoding='utf-8')

    return manifest, positions


def save_overhead_reference(controller, output_dir, camera_id=None):
    from PIL import Image

    # Keep every overhead event/frame local; only view_00.png leaves this function.
    map_event = controller.step(action='GetMapViewCameraProperties', raise_for_failure=True)
    camera_properties = copy.deepcopy(map_event.metadata['actionReturn'])
    camera_properties['nearClippingPlane'] = 0.01
    if camera_id is None:
        camera_event = controller.step(action='AddThirdPartyCamera',
                                       **camera_properties, raise_for_failure=True)
        camera_id = camera_event.metadata['thirdPartyCameras'][-1]['thirdPartyCameraId']
    else:
        # Reuse the reference camera when rerunning this cell.
        camera_event = controller.step(action='UpdateThirdPartyCamera',
                                       thirdPartyCameraId=camera_id,
                                       **camera_properties, raise_for_failure=True)
    Image.fromarray(camera_event.third_party_camera_frames[camera_id]).save(output_dir / 'view_00.png')
    return camera_id

def save_viewpoints(output_dir, manifest, positions):
    # Agg writes the plot without a desktop or a notebook display backend.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    fig = Figure(figsize=(7, 7))
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    ax.scatter([p['x'] for p in positions], [p['z'] for p in positions], s=8, color='lightgray')
    center = manifest['look_at_center_xz']
    ax.scatter(center['x'], center['z'], marker='x', color='red')
    for index, view in enumerate(manifest['views'], 1):
        position = view['agent']['position']
        yaw = math.radians(view['agent']['rotation']['y'])
        ax.quiver(position['x'], position['z'], math.sin(yaw), math.cos(yaw),
                  angles='xy', scale_units='xy', scale=2)
        ax.annotate(str(index), (position['x'], position['z']))
    ax.set(xlabel='X (m)', ylabel='Z (m)', title=manifest['scene'])
    ax.set_aspect('equal')
    fig.savefig(output_dir / 'viewpoints.png', dpi=150, bbox_inches='tight')

def capture_scene(controller, output_dir, *, scene='FloorPlan1', num_views=4,
                  horizon=0, image_size=1600, ai2thor_version):
    """Use a fresh directory; failed captures never publish a completion manifest."""
    if num_views not in (3, 4):
        raise ValueError('num_views must be 3 or 4')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    print('Output directory:', output_dir)
    manifest, positions = capture_views(
        controller, output_dir, scene=scene, num_views=num_views,
        horizon=horizon, image_size=image_size, ai2thor_version=ai2thor_version,
    )
    save_overhead_reference(controller, output_dir)
    save_viewpoints(output_dir, manifest, positions)
    # Publish only when the normal views, reference image and plot all exist.
    (output_dir / 'views.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest

def archive_capture(output_dir):
    """Archive only the files named by this completed capture, as in Colab."""
    output_dir = Path(output_dir)
    manifest = json.loads((output_dir / 'views.json').read_text(encoding='utf-8'))
    views = manifest['views']
    if (manifest.get('capture_complete') is not True
            or len(views) != manifest['num_views'] or len(views) not in (3, 4)):
        raise RuntimeError('Capture incomplete; cannot create ZIP.')
    names = ['view_00.png', 'views.json', 'objects.json', 'visible_objects.json',
             'objects.csv', 'reachable_positions.json', 'viewpoints.png']
    for view in views:
        names.extend(view[key] for key in VIEW_FILE_KEYS)
    paths = []
    for name in dict.fromkeys(names):
        path = (output_dir / name).resolve()
        if not path.is_relative_to(output_dir.resolve()):
            raise RuntimeError(f'Capture file is outside output directory: {name}')
        if not path.is_file():
            raise RuntimeError(f'Capture incomplete; missing {name}')
        paths.append((path, name))
    # Append rather than replace a suffix: --output-dir may contain a dot.
    archive = output_dir.parent / (output_dir.name + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path, name in paths:
            bundle.write(path, arcname=name)
    return archive

def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return number

def camera_horizon(value):
    number = float(value)
    if not math.isfinite(number) or not -30 <= number <= 60:
        raise argparse.ArgumentTypeError('must be between -30 and 60 degrees')
    return number

def build_parser():
    parser = argparse.ArgumentParser(
        description='Capture local AI2-THOR views, masks, depth and metadata (capture-v2).')
    parser.add_argument('--scene', default='FloorPlan1')
    parser.add_argument('--num-views', type=int, choices=(3, 4), default=4)
    parser.add_argument('--image-size', type=int, choices=(400, 600, 800, 1600), default=1600)
    parser.add_argument('--horizon', type=camera_horizon, default=0,
                        help='Camera pitch in degrees; positive looks down (default: 0).')
    parser.add_argument('--output-dir', type=Path,
                        help='New basic directory; default: data/scenes/<scene>/<UTC>/basic.')
    display = parser.add_mutually_exclusive_group()
    display.add_argument('--headless', action='store_true',
                         help='Linux CloudRendering; requires a working Vulkan driver, no X11.')
    display.add_argument('--display', help='Linux X11 display; otherwise inherit DISPLAY.')
    parser.add_argument('--timeout', type=positive_float, default=300,
                        help='Unity startup and action timeout in seconds (default: 300).')
    parser.add_argument('--zip', action='store_true', dest='make_zip',
                        help='Also create <output-dir>.zip; the directory remains usable directly.')
    return parser

def run(args):
    # These checks precede imports/downloads and keep --help usable offline.
    if (args.headless or args.display is not None) and not sys.platform.startswith('linux'):
        raise ValueError('--headless and --display are Linux-only options')
    output_dir = args.output_dir
    if output_dir is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        output_dir = SCENES / safe_name(args.scene) / stamp / 'basic'
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        raise FileExistsError(f'Output directory already exists; choose a new path: {output_dir}')
    if args.make_zip and (output_dir.parent / (output_dir.name + '.zip')).exists():
        raise FileExistsError(f'ZIP already exists: {output_dir}.zip')
    if args.headless and args.display is not None:
        raise ValueError('--headless and --display cannot be combined')

    import ai2thor
    from ai2thor.controller import Controller
    from ai2thor.server import DepthFormat
    # Detect missing export dependencies before launching Unity.
    import numpy  # noqa: F401
    from PIL import Image  # noqa: F401
    from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: F401

    options = dict(scene=args.scene, width=args.image_size, height=args.image_size,
                   gridSize=0.25, snapToGrid=False, renderInstanceSegmentation=True,
                   renderDepthImage=True, depth_format=DepthFormat.Meters,
                   server_timeout=args.timeout, server_start_timeout=args.timeout)
    if args.headless:
        from ai2thor.platform import CloudRendering

        options['platform'] = CloudRendering
    elif sys.platform.startswith('linux'):
        display = args.display or os.environ.get('DISPLAY')
        if display:
            options['x_display'] = display

    controller = None
    try:
        print(f'Starting AI2-THOR {ai2thor.__version__}: {args.scene}, '
              f'{args.image_size}x{args.image_size}', flush=True)
        controller = Controller(**options)
        event = controller.last_event
        if not event.metadata['lastActionSuccess']:
            raise RuntimeError(event.metadata['errorMessage'])
        if event.instance_segmentation_frame is None or event.depth_frame is None:
            raise RuntimeError('Controller did not initialize instance segmentation and depth rendering')
        capture_scene(controller, output_dir, scene=args.scene, num_views=args.num_views,
                      horizon=args.horizon, image_size=args.image_size,
                      ai2thor_version=ai2thor.__version__)
        config_dir = output_dir.parent if output_dir.name == 'basic' else output_dir
        snapshot(config_dir / 'capture_config.yaml', dict(vars(args), output_dir=str(output_dir)))
        if args.make_zip:
            print('ZIP:', archive_capture(output_dir))
        print('Capture complete:', output_dir)
        return output_dir
    finally:
        if controller is not None:
            controller.stop()

def main(argv=None):
    args = parse_config_args(build_parser(), argv)
    try:
        run(args)
    except ImportError as exc:
        print(f'Missing capture dependency: {exc}\n'
              'Install: python -m pip install -r requirements-capture.txt', file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'Capture failed: {exc}', file=sys.stderr)
        print('For Linux display/driver errors see docs/local_capture.md. '
              'Unity logs: ~/.ai2thor/log/unity.log or '
              '~/.config/unity3d/Allen Institute for Artificial Intelligence/AI2-THOR/Player.log',
              file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""CLI entry point; importing this module never starts AI2-THOR."""

import argparse
import math
from pathlib import Path
import time

from datetime import datetime, timezone
from common.paths import RUNS

from scene_capture.demo.demo_task import ACTION_PLAN, build_task
from scene_capture.demo.simulation_platform import SimulationPlatform


def run_plan(platform, action_plan, step_delay=2.0, post_success_steps=3):
    """Allow exactly N further actions after first success."""
    remaining = None
    for action, target in action_plan:
        print(f"\n[Agent] {action} target={target}")
        obs = platform.run_step(action, target)
        print(f" > {obs['feedback']}")
        print(f" > {obs['goal_details']}")
        if remaining is not None:
            remaining -= 1
        elif obs["task_done"]:
            remaining = post_success_steps
        if remaining == 0:
            break
        time.sleep(step_delay)


def nonnegative_float(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite, nonnegative number")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the fixed FloorPlan1 cooking demo.")
    parser.add_argument("--output-dir", type=Path,
                        default=RUNS / ("demo_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")) / "FloorPlan1" / "demo")
    parser.add_argument("--no-video", action="store_true", help="Disable video and OpenCV.")
    parser.add_argument(
        "--headless", action="store_true",
        help="Use CloudRendering without X11 (Linux with Vulkan support required).",
    )
    parser.add_argument("--step-delay", type=nonnegative_float, default=2.0)
    args = parser.parse_args(argv)

    from ai2thor.controller import Controller

    controller_kwargs = {"width": 600, "height": 600}
    if args.headless:
        from ai2thor.platform import CloudRendering

        controller_kwargs["platform"] = CloudRendering
    controller = Controller(**controller_kwargs)
    platform = None
    try:
        platform = SimulationPlatform(
            controller,
            record_video=not args.no_video,
            video_path=str(args.output_dir / "run.mp4"),
            log_path=str(args.output_dir / "trace_log.json"),
            fps=8,
        )
        platform.load_task(build_task())
        run_plan(platform, ACTION_PLAN, step_delay=args.step_delay)
    finally:
        try:
            if platform is not None:
                platform.finish()
        finally:
            controller.stop()


if __name__ == "__main__":
    main()

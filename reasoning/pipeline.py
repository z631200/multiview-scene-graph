"""Build a text scene graph from four saved views, without importing AI2-THOR."""

import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys

from reasoning.ollama_client import OllamaClient, OllamaError
import reasoning.prompts as prompts
from reasoning.validation import (
    ValidationError, validate_observation, validate_correspondence, validate_graph,
    normalize_graph,
)

from common.paths import ROOT, RUNS, safe_name
from common.config import parse_config_args, read_config, snapshot
from reasoning.visible.observer import export_observation
from reasoning.full.methods.central_llm import export_views


def task_folder(key, category):
    return Path("visible" if key.startswith("view_") else "full/central_llm") / category


def update_experiment(directory, manifest):
    """Record real run status only; evaluation metrics are not implemented."""
    experiment = directory.parent
    path = experiment / "run_manifest.json"
    index = read_json(path) if path.exists() else dict(schema_version=1, scenes={})
    index["scenes"][directory.name] = dict(status=manifest["status"], capture_id=manifest.get("capture_id"),
        source_scene_dir=manifest["scene_dir"], manifest=f"{directory.name}/run_manifest.json")
    write_json(path, index)
    with (experiment / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene", "capture_id", "status"])
        writer.writeheader()
        writer.writerows(dict(scene=scene, capture_id=entry.get("capture_id"), status=entry["status"])
                         for scene, entry in sorted(index["scenes"].items()))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def load_scene(directory):
    """Explicit allowlist: never read objects.json/csv or directory-wide image globs."""
    directory = Path(directory).resolve()
    manifest_path = directory / "views.json"
    raw = manifest_path.read_bytes()
    data = json.loads(raw.decode("utf-8-sig"))
    views = data.get("views")
    if not isinstance(views, list) or len(views) != 4 or data.get("num_views") != 4:
        raise ValueError("This baseline requires exactly four views")
    if data.get("position_unit") != "meter" or data.get("rotation_unit") != "degree":
        raise ValueError("Expected position_unit=meter and rotation_unit=degree")
    expected = {f"view_{i:02d}.png" for i in range(1, 5)}
    names = [v.get("image") for v in views]
    if any(not isinstance(n, str) for n in names) or set(names) != expected:
        raise ValueError("views.json must reference view_01.png through view_04.png once each")
    images, cameras = {}, {}
    hashes = {"views.json": digest(raw)}
    for index, view in enumerate(sorted(views, key=lambda v: v["image"]), 1):
        name = view["image"]
        path = (directory / name).resolve()
        if path.parent != directory:
            raise ValueError("Images must remain inside the scene directory")
        image = path.read_bytes()
        if len(image) < 33 or image[:8] != b"\x89PNG\r\n\x1a\n" or image[12:16] != b"IHDR":
            raise ValueError(f"Invalid PNG header: {name}")
        width, height = struct.unpack(">II", image[16:24])
        if not width or not height:
            raise ValueError(f"Invalid PNG dimensions: {name}")
        camera = view.get("cameraPosition")
        if not isinstance(camera, dict):
            raise ValueError(f"{name}: cameraPosition is required (agent position is not a substitute)")
        position = {a: finite(camera[a], f"{name}.cameraPosition.{a}") for a in "xyz"}
        agent = view["agent"]
        yaw = finite(agent["rotation"]["y"], f"{name}.yaw")
        horizon = finite(agent["cameraHorizon"], f"{name}.cameraHorizon")
        fov = finite(view["fov"], f"{name}.fov")
        if not 0 < fov < 180:
            raise ValueError(f"{name}: FOV must lie between 0 and 180")
        key = f"view_{index}"
        images[key] = image
        hashes[name] = digest(image)
        cameras[key] = dict(cameraPosition=position, yaw=yaw, cameraHorizon=horizon, fov=fov)
    return dict(scene_id=safe_name(data.get("scene") or "scene"),
        capture_id=directory.parent.name if directory.name == "basic" else directory.name,
        images=images, hashes=hashes, cameras={
        "coordinate_system": "AI2-THOR world: X/Z horizontal, Y up; yaw 0 faces +Z, 90 faces +X. "
                             "Positive cameraHorizon looks down; negative looks up.",
        "position_unit": "meter", "rotation_unit": "degree", "views": cameras,
    })


@contextmanager
def run_lock(directory):
    path = directory / ".run.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise ValueError(f"Run is locked: {path}. Remove only after confirming no process is using it.") from exc
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        path.unlink()


def reusable_run(source, scene, config):
    """Read and revalidate model outputs under current code, preserving the source run."""
    source = source.resolve()
    manifest_path = source / "run_manifest.json"
    old = read_json(manifest_path)
    settings = lambda value: {k: v for k, v in value.items() if k != "source_hashes"}
    if old.get("input_hashes") != scene["hashes"] or settings(old.get("config", {})) != settings(config):
        raise ValueError("Fork requires the same inputs, model and generation settings as the source run")
    texts = {}
    for index in range(1, 5):
        key = f"view_{index}"
        entry = old.get("completed", {}).get(key)
        if not entry:
            continue
        relative = f"visible/observations/{key}.md"
        text = (source / relative).read_text(encoding="utf-8")
        if digest(text.encode("utf-8")) != entry["sha256"]:
            raise ValueError(f"Source artifact was modified: {source / relative}")
        validate_observation(text, index)
        texts[key] = (relative, text)
    correspondence = old.get("completed", {}).get("correspondence")
    if correspondence:
        text = (source / "full/central_llm/correspondence.md").read_text(encoding="utf-8")
        if digest(text.encode("utf-8")) != correspondence["sha256"]:
            raise ValueError("Source correspondence was modified")
        validate_correspondence(text, {key: value[1] for key, value in texts.items()})
        texts["correspondence"] = ("full/central_llm/correspondence.md", text)
    candidate = None
    if correspondence:
        for attempt in reversed(old.get("attempts", [])):
            if attempt["task"] != "scene_graph" or attempt["status"] not in ("invalid", "valid"):
                continue
            stem = f"scene_graph_{attempt['number']:02d}"
            response = read_json(source / task_folder("scene_graph", "responses") / f"{stem}.json")
            text = (source / task_folder("scene_graph", "responses") / f"{stem}.md").read_text(encoding="utf-8")
            if (response.get("done") is True and response.get("done_reason") != "length"
                    and (response.get("message") or {}).get("content") == text):
                candidate = dict(text=text, response=response, source_attempt=attempt["number"])
            break
    return dict(texts=texts, candidate=candidate, server=old.get("server"),
                origin=dict(directory=str(source), manifest_sha256=digest(manifest_path.read_bytes()),
                            source_hashes=old["config"].get("source_hashes", {})))


def run(args, client=None):
    scene = load_scene(args.scene_dir)
    options = dict(temperature=args.temperature, seed=args.seed,
                   num_ctx=args.num_ctx, num_predict=args.num_predict)
    config = dict(model=args.model, ollama_url=args.ollama_url.rstrip("/"),
                  thinking=args.thinking,
                  options=options, verification_budget=args.verification_budget,
                  source_hashes={name: digest((ROOT / name).read_bytes()) for name in
                                 ("reasoning/prompts.py", "reasoning/validation.py",
                                  "reasoning/pipeline.py", "reasoning/ollama_client.py",
                                  "reasoning/visible/observer.py", "reasoning/full/methods/central_llm.py",
                                  "common/config.py", "common/paths.py")})
    fork = reusable_run(args.fork_from, scene, config) if args.fork_from else None
    if args.resume:
        directory = args.resume.resolve()
        manifest = read_json(directory / "run_manifest.json")
        if manifest.get("config") != config or manifest.get("input_hashes") != scene["hashes"]:
            raise ValueError("Resume inputs, model, generation settings or code differ; start a new run")
        if manifest.get("status") == "dry-run":
            raise ValueError("Dry runs cannot be resumed; start a new run")
    else:
        if args.stage in ("2", "3") and not fork:
            raise ValueError("Stages 2 and 3 require --resume or --fork-from with validated earlier stages")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        experiment = args.output_dir.resolve() / safe_name(getattr(args, "experiment_id", None) or f"exp_{run_id}")
        directory = experiment / scene["scene_id"]
        settings = {k:v for k,v in vars(args).items() if k not in ("scene_dir", "resume", "fork_from", "config")}
        settings = json.loads(json.dumps(settings, default=str))
        if (experiment / "config.yaml").exists() and read_config(experiment / "config.yaml") != settings:
            raise ValueError("Experiment settings differ; select a new --experiment-id")
        directory.mkdir(parents=True, exist_ok=False)
        snapshot(experiment / "config.yaml", settings)
        snapshot(directory / "config.yaml", vars(args))
        manifest = dict(schema_version=1, created_at=timestamp(), status="created",
                        scene_dir=str(args.scene_dir.resolve()), input_hashes=scene["hashes"],
                        capture_id=scene["capture_id"], scene=scene["scene_id"],
                        config=config, completed={}, attempts=[])
    with run_lock(directory):
        if fork:
            manifest["forked_from"] = fork["origin"]
            if fork["server"]:
                manifest["server"] = fork["server"]
            for key, (relative, text) in fork["texts"].items():
                write_text(directory / relative, text)
                manifest["completed"][key] = dict(path=relative, sha256=digest(text.encode("utf-8")),
                                                   reused_from=fork["origin"]["directory"])
            if fork["candidate"]:
                candidate = fork["candidate"]
                relative = "full/central_llm/responses/scene_graph_imported.md"
                write_text(directory / relative, candidate["text"])
                write_json(directory / "full/central_llm/responses/scene_graph_imported.json", candidate["response"])
                manifest["recovery_candidate"] = dict(path=relative,
                    sha256=digest(candidate["text"].encode("utf-8")),
                    source_attempt=candidate["source_attempt"])
        return execute(args, client, directory, manifest, scene, config)


def execute(args, client, directory, manifest, scene, config):
    manifest_path = directory / "run_manifest.json"
    report_path = directory / "validation_report.json"
    report = read_json(report_path) if report_path.exists() else {
        "scope": "Text structure and provenance only; not a judgment of visual correctness.",
        "tasks": {},
    }

    def save():
        manifest["updated_at"] = timestamp()
        write_json(manifest_path, manifest)
        write_json(report_path, report)
        update_experiment(directory, manifest)

    save()
    print(f"Run directory: {directory}", flush=True)
    write_json(directory / "camera_metadata.json", scene["cameras"])
    try:
        if args.dry_run:
            for i in range(1, 5):
                write_text(directory / "visible/prompts" / f"view_{i}.txt",
                           prompts.COMMON + "\n\n" + prompts.observation_prompt(i))
            write_text(directory / "full/central_llm/prompts" / "correspondence.template.txt",
                       prompts.COMMON + "\n\n" + prompts.CORRESPONDENCE +
                       "\n" + prompts.FORMAT_BASE + prompts.CORRESPONDENCE_FORMAT)
            write_text(directory / "full/central_llm/prompts" / "scene_graph.template.txt",
                       prompts.COMMON + "\n\n" + prompts.GRAPH +
                       "\n" + prompts.RELATIONS + prompts.FORMAT_BASE + prompts.GRAPH_FORMAT)
            manifest["status"] = "dry-run"
            save()
            return directory

        client = client or OllamaClient(args.ollama_url, args.model, args.timeout,
                                       config["options"], args.thinking)
        server = client.preflight()
        old_server = manifest.get("server")
        if old_server and old_server.get("digest") != server.get("digest"):
            raise ValueError("Model digest changed; start a new run")
        manifest["server"] = server
        manifest["status"] = "running"
        manifest.pop("error", None)
        for attempt in manifest["attempts"]:
            if attempt["status"] == "running":
                attempt["status"] = "interrupted"
        save()

        def obtain(key, relative, prompt, validator, image=None, allow_generate=True, normalizer=None):
            path = directory / relative
            previous = manifest["completed"].get(key)
            if previous:
                text = path.read_text(encoding="utf-8")
                if digest(text.encode("utf-8")) != previous["sha256"]:
                    raise ValueError(f"Completed artifact was modified: {path}")
                parsed = validator(text)
                report["tasks"][key] = dict(valid=True, counts={k: len(v) for k, v in parsed.items()})
                save()
                print(f"[resume] {key}", flush=True)
                return text
            if not allow_generate:
                raise ValueError(f"Missing prerequisite {key}; resume with --stage all")
            repair = None
            invalid_signatures = set()

            def correction(text, errors):
                return (text, "Rewrite the complete answer in the requested text format. "
                        "Fix these validation errors using only the original evidence. "
                        "Do not invent supporting evidence merely to pass validation. "
                        "Omit a relation if its two distinct existing IDs cannot be established.\n"
                        + "\n".join(errors))

            def prepare(text, stem):
                if normalizer is None:
                    return text
                normalized, changes = normalizer(text)
                if changes:
                    write_json(directory / task_folder(key, "normalizations") / f"{stem}.json",
                               dict(raw_sha256=digest(text.encode("utf-8")),
                                    normalized_sha256=digest(normalized.encode("utf-8")), changes=changes))
                    write_text(directory / task_folder(key, "responses") / f"{stem}.normalized.md", normalized)
                return normalized

            imported = manifest.get("recovery_candidate") if key == "scene_graph" else None
            if imported:
                raw = (directory / imported["path"]).read_text(encoding="utf-8")
                if digest(raw.encode("utf-8")) != imported["sha256"]:
                    raise ValueError("Imported graph response was modified")
                candidate = raw
                try:
                    candidate = prepare(raw, "scene_graph_imported")
                    parsed = validator(candidate)
                except ValidationError as exc:
                    report["tasks"][key] = dict(valid=False, errors=exc.errors)
                    repair = correction(candidate, exc.errors)
                    invalid_signatures.add((candidate, tuple(exc.errors)))
                    save()
                else:
                    write_text(path, candidate)
                    manifest["completed"][key] = dict(path=relative, sha256=digest(candidate.encode("utf-8")),
                                                       recovered_from=imported["path"])
                    report["tasks"][key] = dict(valid=True, counts={k: len(v) for k, v in parsed.items()})
                    save()
                    print(f"[recovered] {key} without new inference", flush=True)
                    return candidate
            for attempt in range(args.format_retries + 1):
                number = 1 + sum(a["task"] == key for a in manifest["attempts"])
                stem = f"{key}_{number:02d}"
                prompt_text = prompts.COMMON + "\n\n" + prompt
                if repair:
                    prompt_text += "\n\nPREVIOUS RESPONSE:\n" + repair[0] + "\n\n" + repair[1]
                write_text(directory / task_folder(key, "prompts") / f"{stem}.txt", prompt_text)
                entry = dict(task=key, number=number, started_at=timestamp(), status="running",
                             prompt_sha256=digest(prompt_text.encode("utf-8")))
                manifest["attempts"].append(entry)
                save()
                print(f"[generate] {key}, attempt {number}", flush=True)
                try:
                    response = client.chat(prompts.COMMON, prompt, image=image, repair=repair)
                except Exception as exc:
                    entry.update(status="error", error=str(exc), finished_at=timestamp())
                    save()
                    raise
                write_json(directory / task_folder(key, "responses") / f"{stem}.json", response)
                entry.update(finished_at=timestamp(), usage={k: response.get(k) for k in (
                    "total_duration", "load_duration", "prompt_eval_count",
                    "prompt_eval_duration", "eval_count", "eval_duration")},
                    done_reason=response.get("done_reason"))
                message = response.get("message") or {}
                text = message.get("content", "")
                if not isinstance(text, str):
                    text = ""
                write_text(directory / task_folder(key, "responses") / f"{stem}.md", text)
                entry["raw_sha256"] = digest(text.encode("utf-8"))
                if response.get("done") is not True or response.get("done_reason") == "length" or not text.strip():
                    entry.update(status="incomplete")
                    report["tasks"][key] = dict(valid=False, errors=["Empty or incomplete model response"])
                    save()
                    raise ValueError(f"{key}: empty/truncated response; increase --num-predict or --num-ctx in a NEW run")
                try:
                    text = prepare(text, stem)
                    parsed = validator(text)
                except ValidationError as exc:
                    entry.update(status="invalid", errors=exc.errors)
                    report["tasks"][key] = dict(valid=False, errors=exc.errors)
                    signature = (text, tuple(exc.errors))
                    if signature in invalid_signatures:
                        entry["no_progress"] = True
                        report["tasks"][key]["errors"] += [
                            "Identical invalid response and errors repeated; stopped to avoid wasting calls."
                        ]
                        save()
                        raise ValidationError(report["tasks"][key]["errors"]) from exc
                    invalid_signatures.add(signature)
                    save()
                    if attempt == args.format_retries:
                        raise
                    repair = correction(text, exc.errors)
                    continue
                write_text(path, text)
                entry["status"] = "valid"
                manifest["completed"][key] = dict(path=relative, sha256=digest(text.encode("utf-8")))
                report["tasks"][key] = dict(valid=True, counts={k: len(v) for k, v in parsed.items()})
                save()
                return text
            raise AssertionError("Unreachable")

        observations = {}
        for i in range(1, 5):
            key = f"view_{i}"
            observations[key] = obtain(
                key, f"visible/observations/{key}.md", prompts.observation_prompt(i),
                lambda text, index=i: validate_observation(text, index),
                image=scene["images"][key], allow_generate=args.stage in ("all", "1"),
            )
            write_json(directory / "visible/graphs" / f"{key}.json", export_observation(observations[key], i))
        if args.stage == "1":
            manifest["status"] = "stage_1_complete"
        else:
            correspondence = obtain(
                "correspondence", "full/central_llm/correspondence.md",
                prompts.correspondence_prompt(scene["cameras"], observations),
                lambda text: validate_correspondence(text, observations),
                allow_generate=args.stage in ("all", "2"),
            )
            write_json(directory / "full/central_llm/correspondence.json",
                       validate_correspondence(correspondence, observations))
            if args.stage == "2":
                manifest["status"] = "stage_2_complete"
            else:
                graph_text = obtain("scene_graph", "full/central_llm/scene_graph.md",
                       prompts.graph_prompt(scene["cameras"], observations, correspondence,
                                            args.verification_budget),
                       lambda text: validate_graph(text, observations, correspondence,
                                                  args.verification_budget),
                       normalizer=lambda text: normalize_graph(text, observations, correspondence))
                views, _ = export_views(graph_text, observations, correspondence, args.verification_budget)
                for vid, graph in views.items():
                    write_json(directory / "full/central_llm/graphs" / f"{vid}.json", graph)
                manifest["status"] = "complete"
        save()
        print(f"Finished: {manifest['status']}", flush=True)
        return directory
    except BaseException as exc:
        manifest.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                        error=str(exc) or type(exc).__name__)
        save()
        raise


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return number


def nonnegative_float(value):
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be finite and nonnegative")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--scene-dir", type=Path, required=True)
    result.add_argument("--output-dir", type=Path, default=RUNS)
    result.add_argument("--experiment-id", help="Experiment folder name; default: exp_<UTC>")
    result.add_argument("--model", default="gemma4:e4b")
    result.add_argument("--ollama-url", default="http://localhost:11434")
    result.add_argument("--stage", choices=("all", "1", "2", "3"), default="all")
    prior = result.add_mutually_exclusive_group()
    prior.add_argument("--resume", type=Path, help="Existing run directory; validates inputs and completed artifacts")
    prior.add_argument("--fork-from", type=Path,
                       help="Create a new run using revalidated outputs from an older code version")
    result.add_argument("--dry-run", action="store_true", help="Save prompts and camera allowlist without contacting Ollama")
    result.add_argument("--timeout", type=positive_int, default=600, help="Seconds per HTTP request")
    result.add_argument("--num-ctx", type=positive_int, default=32768)
    result.add_argument("--num-predict", type=positive_int, default=8192)
    result.add_argument("--temperature", type=nonnegative_float, default=0.2)
    result.add_argument("--seed", type=int, default=42)
    result.add_argument("--thinking", choices=("auto", "on", "off"), default="auto",
                        help="auto enables reasoning only for the two central text tasks")
    result.add_argument("--format-retries", type=nonnegative_int, default=3)
    result.add_argument("--verification-budget", type=nonnegative_int, default=4,
                        help="Maximum proposed questions; no verification calls are executed")
    return result


def main(argv=None):
    arguments = parser()
    args = parse_config_args(arguments, argv)
    if args.dry_run and (args.resume or args.fork_from):
        arguments.error("--dry-run cannot be combined with --resume or --fork-from")
    if args.num_predict >= args.num_ctx:
        arguments.error("--num-predict must be smaller than --num-ctx")
    try:
        run(args)
    except KeyboardInterrupt:
        print("Interrupted; validated outputs can be resumed.", file=sys.stderr)
        return 130
    except (OllamaError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Offline regression tests. No Ollama installation or AI2-THOR needed."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from reasoning.ollama_client import OllamaClient, OllamaError
from reasoning.pipeline import load_scene, parser, run, run_lock
from reasoning.validation import (
    ValidationError, validate_observation, validate_correspondence, validate_graph,
    normalize_graph,
)


def observation(index):
    return f"""## Observation conditions
- view_{index}: clear.
## Objects
- v{index}_o1 | cup | white | center | none
- v{index}_o2 | table | brown | bottom | partial
## Relations
- v{index}_r1 | v{index}_o1 | v{index}_o2 | rests on | physical | clear | base touches tabletop
## Uncertainties
- None
"""


OBSERVATIONS = {f"view_{i}": observation(i) for i in range(1, 5)}
CUP_SOURCES = ", ".join(f"v{i}_o1" for i in range(1, 5))
TABLE_SOURCES = ", ".join(f"v{i}_o2" for i in range(1, 5))
CORRESPONDENCE = f"""## Global objects
- g1 | white cup | {CUP_SOURCES} | provisional | same shape and table context
- g2 | brown table | {TABLE_SOURCES} | provisional | same shape
## Mapping
""" + "\n".join(f"- v{i}_o{j} | g{j} | provisional" for i in range(1, 5) for j in (1, 2)) + """
## Ambiguities
- None
"""
GRAPH = f"""## Nodes
- g1 | white cup | {CUP_SOURCES} | provisional
- g2 | brown table | {TABLE_SOURCES} | provisional
## Edges
- e1 | (g1, on, g2) | physical | provisional | observed | v1_r1, v2_r1 | none | visible support
## Unresolved issues
- None
## Verification requests
- None
"""


class FakeClient:
    def __init__(self, replies=None):
        self.replies = list(replies if replies is not None else [*OBSERVATIONS.values(), CORRESPONDENCE, GRAPH])
        self.calls = []

    def preflight(self):
        return {"version": "fake", "digest": "fixed", "capabilities": ["vision"]}

    def chat(self, system, prompt, image=None, repair=None):
        self.calls.append(dict(system=system, prompt=prompt, image=image, repair=repair))
        answer = self.replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return dict(message={"content": answer}, done=True, done_reason="stop",
                    eval_count=10, prompt_eval_count=20)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = self.root / "scene"
        self.scene.mkdir()
        views = []
        for i in range(1, 5):
            name = f"view_{i:02d}.png"
            # Header-only fixture is sufficient for loader checks; never sent to a real model.
            (self.scene / name).write_bytes(
                b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" +
                struct.pack(">II", 800, 800) + bytes([i]) * 9)
            views.append(dict(image=name, cameraPosition=dict(x=i, y=1.6, z=i),
                              agent=dict(position=dict(x=i, y=0.9, z=i),
                                         rotation=dict(x=0, y=i * 45, z=0), cameraHorizon=0),
                              fov=90, secret="GROUND_TRUTH_LEAK"))
        self.data = dict(num_views=4, position_unit="meter", rotation_unit="degree",
                         views=views, object_count=77, secret="GROUND_TRUTH_LEAK")
        self.save_scene()
        (self.scene / "objects.json").write_text("GROUND_TRUTH_LEAK", encoding="utf-8")
        (self.scene / "objects.csv").write_text("GROUND_TRUTH_LEAK", encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch("builtins.print").start()

    def save_scene(self):
        (self.scene / "views.json").write_text(json.dumps(self.data), encoding="utf-8")

    def args(self, *extra):
        return parser().parse_args(["--scene-dir", str(self.scene),
                                    "--output-dir", str(self.root / "outputs"), *extra])


class ValidationTests(unittest.TestCase):
    def image_observations(self):
        return {key: text.replace("## Uncertainties",
            f"- v{i}_r2 | v{i}_o1 | left of | v{i}_o2 | image | clear | visible placement\n## Uncertainties")
            for i, (key, text) in enumerate(OBSERVATIONS.items(), 1)}

    def image_graph(self, frame="image_left_of", sources="v1_r2"):
        return GRAPH.replace("(g1, on, g2) | physical",
                             f"(g1, image_left_of, g2) | {frame}").replace("v1_r1, v2_r1", sources)

    def test_frame_alias_recovered_only_from_unique_matching_sources(self):
        observations = self.image_observations()
        raw = self.image_graph()
        with self.assertRaisesRegex(ValidationError, "NOT a relation name"):
            validate_graph(raw, observations, CORRESPONDENCE)
        normalized, changes = normalize_graph(raw, observations, CORRESPONDENCE)
        parsed = validate_graph(normalized, observations, CORRESPONDENCE)
        self.assertEqual(parsed["edges"]["e1"]["frame"], "view_1")
        self.assertEqual(changes[0]["before"], "image_left_of")
        self.assertEqual(changes[0]["after"], "view_1")

    def test_normalizer_does_not_guess_ambiguous_or_wrong_view(self):
        observations = self.image_observations()
        for raw in (self.image_graph(sources="v1_r2, v2_r2"),
                    self.image_graph(frame="view_2"),
                    self.image_graph().replace("(g1, image_left_of, g2)", "(g2, image_left_of, g1)"),
                    self.image_graph(sources="v1_r99")):
            with self.subTest(raw=raw):
                normalized, changes = normalize_graph(raw, observations, CORRESPONDENCE)
                self.assertEqual(normalized, raw)
                self.assertEqual(changes, [])
                with self.assertRaises(ValidationError):
                    validate_graph(normalized, observations, CORRESPONDENCE)

    def test_duplicate_edges_keep_sources_and_conservative_status(self):
        raw = GRAPH.replace("## Unresolved issues",
            "- e2 | (g1, on, g2) | physical | unresolved | observed | v3_r1 | none | uncertain contact\n## Unresolved issues")
        raw = raw.replace("## Unresolved issues\n- None", "## Unresolved issues\n- u1: Review e2.")
        normalized, changes = normalize_graph(raw, OBSERVATIONS, CORRESPONDENCE)
        edge = validate_graph(normalized, OBSERVATIONS, CORRESPONDENCE)["edges"]["e1"]
        self.assertEqual(edge["sources"], ["v1_r1", "v2_r1", "v3_r1"])
        self.assertEqual(edge["status"], "unresolved")
        self.assertIn("Review e1", normalized)
        self.assertEqual(changes[0]["retained"], "e1")

    def test_valid_chain(self):
        self.assertEqual(len(validate_observation(observation(1), 1)["objects"]), 2)
        self.assertEqual(len(validate_correspondence(CORRESPONDENCE, OBSERVATIONS)["mapping"]), 8)
        self.assertEqual(len(validate_graph(GRAPH, OBSERVATIONS, CORRESPONDENCE)["edges"]), 1)

    def test_invalid_observation_references_and_duplicates(self):
        for text in (observation(1).replace("v1_o2 | rests", "v1_o9 | rests"),
                     observation(1).replace("- v1_o2 | table", "- v1_o1 | table"),
                     observation(1).replace("v1_", "v2_")):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                validate_observation(text, 1)

    def test_mapping_cannot_drop_a_local_object(self):
        text = CORRESPONDENCE.replace("- v4_o2 | g2 | provisional\n", "")
        with self.assertRaises(ValidationError):
            validate_correspondence(text, OBSERVATIONS)

    def test_all_non_numeric_global_ids_are_reported(self):
        text = CORRESPONDENCE.replace("g1", "g1_cup").replace("g2", "g2_table")
        with self.assertRaises(ValidationError) as caught:
            validate_correspondence(text, OBSERVATIONS)
        self.assertIn("g1_cup", str(caught.exception))
        self.assertIn("g2_table", str(caught.exception))

    def test_both_local_relation_field_orders_are_unambiguous(self):
        original = observation(1)
        reordered = original.replace("v1_o1 | v1_o2 | rests on", "v1_o1 | rests on | v1_o2")
        self.assertEqual(validate_observation(original, 1), validate_observation(reordered, 1))

    def test_opposite_image_relations_require_conflicting_status(self):
        observations = dict(OBSERVATIONS)
        observations["view_1"] = observation(1).replace(
            "rests on | physical", "left of | image"
        ).replace("## Uncertainties",
                  "- v1_r2 | v1_o2 | v1_o1 | left of | image | clear | visible placement\n## Uncertainties")
        graph = GRAPH.replace("(g1, on, g2) | physical", "(g1, image_left_of, g2) | view_1")
        graph = graph.replace("v1_r1, v2_r1", "v1_r1").replace(
            "## Unresolved issues",
            "- e2 | (g2, image_left_of, g1) | view_1 | provisional | observed | v1_r2 | none | opposing claim\n## Unresolved issues")
        with self.assertRaisesRegex(ValidationError, "conflicting"):
            validate_graph(graph, observations, CORRESPONDENCE)
        graph = graph.replace("| provisional | observed", "| conflicting | observed")
        self.assertEqual(len(validate_graph(graph, observations, CORRESPONDENCE)["edges"]), 2)

    def test_unknown_mapping_and_empty_graph_are_valid(self):
        text = "## Global objects\n- None\n## Mapping\n"
        text += "\n".join(f"- v{i}_o{j} | unknown | unresolved" for i in range(1, 5) for j in (1, 2))
        text += "\n## Ambiguities\n- a1: Matching cannot be determined.\n"
        graph = "## Nodes\n- None\n## Edges\n- None\n## Unresolved issues\n- u1: Identity unknown.\n## Verification requests\n- None"
        self.assertFalse(validate_graph(graph, OBSERVATIONS, text)["nodes"])

    def test_same_view_objects_cannot_merge(self):
        text = f"## Global objects\n- g1 | thing | {CUP_SOURCES}, {TABLE_SOURCES} | provisional | similar\n## Mapping\n"
        text += "\n".join(f"- v{i}_o{j} | g1 | provisional" for i in range(1, 5) for j in (1, 2))
        text += "\n## Ambiguities\n- None"
        with self.assertRaisesRegex(ValidationError, "same view"):
            validate_correspondence(text, OBSERVATIONS)

    def test_graph_rejects_untraceable_edges(self):
        for text in (GRAPH.replace("(g1, on, g2)", "(g2, on, g1)"),
                     GRAPH.replace("v1_r1, v2_r1", "v1_r99"),
                     GRAPH.replace("| observed |", "| derived |"),
                     GRAPH.replace("| physical |", "| view_1 |"),
                     GRAPH.replace("(g1, on, g2)", "(g1, near, g2)")):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                validate_graph(text, OBSERVATIONS, CORRESPONDENCE)

    def test_tentative_evidence_cannot_be_promoted(self):
        observations = dict(OBSERVATIONS)
        observations["view_1"] = observation(1).replace("| clear |", "| tentative |")
        with self.assertRaisesRegex(ValidationError, "uncertain evidence"):
            validate_graph(GRAPH, observations, CORRESPONDENCE)
        self.assertTrue(validate_graph(GRAPH.replace("| provisional | observed", "| unresolved | observed"),
                                       observations, CORRESPONDENCE)["edges"])

    def test_verification_budget_and_view_restrictions(self):
        text = GRAPH.replace("## Verification requests\n- None",
                             "## Verification requests\n- q1 | view_1 | v1_o1 | Is the cup supported?")
        with self.assertRaisesRegex(ValidationError, "budget"):
            validate_graph(text, OBSERVATIONS, CORRESPONDENCE, budget=0)
        with self.assertRaises(ValidationError):
            validate_graph(text.replace("q1 | view_1 | v1_o1", "q1 | view_2 | v1_o1"),
                           OBSERVATIONS, CORRESPONDENCE)
        with self.assertRaisesRegex(ValidationError, "only sees"):
            validate_graph(text.replace("Is the cup supported?", "Is it the same cup as in View 2?"),
                           OBSERVATIONS, CORRESPONDENCE)


class PipelineTests(Fixture):
    def test_experiment_layout_json_exports_and_scene_index(self):
        out = run(self.args("--experiment-id", "exp_test"), FakeClient())
        self.assertEqual(out.parent.name, "exp_test")
        self.assertTrue((out.parent / "config.yaml").exists())
        self.assertTrue((out.parent / "summary.csv").exists())
        for index in range(1, 5):
            local = json.loads((out / f"visible/graphs/view_{index}.json").read_text())
            full = json.loads((out / f"full/central_llm/graphs/view_{index}.json").read_text())
            self.assertEqual(len(local["nodes"]), 2)
            self.assertEqual(len(full["edges"]), 1)
            self.assertTrue(all(e["frame"] in ("physical", f"view_{index}") for e in full["edges"]))
        self.data["scene"] = "FloorPlan2"
        (self.scene / "views.json").write_text(json.dumps(self.data))
        second = run(self.args("--experiment-id", "exp_test"), FakeClient())
        self.assertEqual(second.name, "FloorPlan2")
        manifest = json.loads((out.parent / "run_manifest.json").read_text())
        self.assertEqual(set(manifest["scenes"]), {"scene", "FloorPlan2"})
        self.assertEqual(len((out.parent / "summary.csv").read_text().splitlines()), 3)

    def test_frame_normalization_preserves_raw_response_and_audit(self):
        raw = GRAPH.replace("| physical |", "| on |")
        out = run(self.args(), FakeClient([*OBSERVATIONS.values(), CORRESPONDENCE, raw]))
        self.assertEqual((out / "full/central_llm/responses/scene_graph_01.md").read_text(), raw)
        self.assertEqual(validate_graph((out / "full/central_llm/scene_graph.md").read_text(), OBSERVATIONS, CORRESPONDENCE),
                         validate_graph(GRAPH, OBSERVATIONS, CORRESPONDENCE))
        audit = json.loads((out / "full/central_llm/normalizations/scene_graph_01.json").read_text())
        self.assertEqual(audit["changes"][0]["after"], "physical")

    def test_fork_recovers_failed_graph_without_new_inference_or_source_changes(self):
        source = run(self.args("--stage", "1"), FakeClient())
        run(self.args("--stage", "2", "--resume", str(source)), FakeClient([CORRESPONDENCE]))
        manifest_path = source / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["config"]["source_hashes"]["reasoning/pipeline.py"] = "previous-version"
        manifest["status"] = "failed"
        manifest["attempts"].append(dict(task="scene_graph", number=1, status="invalid"))
        raw = GRAPH.replace("| physical |", "| on |")
        response = dict(message={"content": raw}, done=True, done_reason="stop")
        (source / "full/central_llm/responses").mkdir(exist_ok=True)
        (source / "full/central_llm/responses/scene_graph_01.md").write_text(raw)
        (source / "full/central_llm/responses/scene_graph_01.json").write_text(json.dumps(response))
        manifest_path.write_text(json.dumps(manifest))
        before = manifest_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "code differ"):
            run(self.args("--resume", str(source)), FakeClient([]))
        client = FakeClient([])
        out = run(self.args("--fork-from", str(source), "--stage", "3"), client)
        self.assertNotEqual(out, source)
        self.assertEqual(client.calls, [])
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(validate_graph((out / "full/central_llm/scene_graph.md").read_text(), OBSERVATIONS, CORRESPONDENCE),
                         validate_graph(GRAPH, OBSERVATIONS, CORRESPONDENCE))
        new = json.loads((out / "run_manifest.json").read_text())
        self.assertEqual(new["status"], "complete")
        self.assertIn("forked_from", new)

    def test_fork_rejects_modified_artifacts_and_different_settings(self):
        source = run(self.args("--stage", "1"), FakeClient())
        run(self.args("--stage", "2", "--resume", str(source)), FakeClient([CORRESPONDENCE]))
        with self.assertRaisesRegex(ValueError, "same inputs"):
            run(self.args("--fork-from", str(source), "--seed", "99"), FakeClient([]))
        (source / "visible/observations/view_1.md").write_text("modified")
        with self.assertRaisesRegex(ValueError, "modified"):
            run(self.args("--fork-from", str(source)), FakeClient([]))

    def test_repeated_identical_invalid_response_stops_early(self):
        client = FakeClient(["bad", "bad"])
        with self.assertRaisesRegex(ValidationError, "Identical invalid"):
            run(self.args("--format-retries", "8"), client)
        self.assertEqual(len(client.calls), 2)

    def test_full_pipeline_and_no_truth_leak(self):
        client = FakeClient()
        original_read = Path.read_bytes

        def guarded(path):
            if path.name.startswith("objects."):
                self.fail("Ground truth must never be read")
            return original_read(path)

        with patch.object(Path, "read_bytes", guarded):
            out = run(self.args(), client)
        self.assertEqual(len(client.calls), 6)
        for index, call in enumerate(client.calls):
            self.assertNotIn("GROUND_TRUTH_LEAK", call["prompt"])
            self.assertNotIn("object_count", call["prompt"])
            if index < 4:
                self.assertIsInstance(call["image"], bytes)
                self.assertNotIn("cameraPosition", call["prompt"])
                for other in range(1, 5):
                    if other != index + 1:
                        self.assertNotIn(f"view_{other}", call["prompt"])
            else:
                self.assertIsNone(call["image"])
                self.assertIn("cameraPosition", call["prompt"])
        self.assertEqual((out / "full/central_llm/scene_graph.md").read_text(encoding="utf-8"), GRAPH)
        manifest = json.loads((out / "run_manifest.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        empty = FakeClient([])
        run(self.args("--resume", str(out)), empty)
        self.assertEqual(empty.calls, [])

    def test_failure_resumes_only_missing_steps(self):
        broken = FakeClient([observation(1), OllamaError("offline")])
        with self.assertRaises(OllamaError):
            run(self.args(), broken)
        out = next((self.root / "outputs").iterdir()) / "scene"
        client = FakeClient([observation(i) for i in range(2, 5)] + [CORRESPONDENCE, GRAPH])
        run(self.args("--resume", str(out)), client)
        self.assertEqual(len(client.calls), 5)
        manifest = json.loads((out / "run_manifest.json").read_text())
        self.assertEqual(manifest["attempts"][1]["status"], "error")

    def test_modified_artifact_or_input_blocks_resume(self):
        out = run(self.args("--stage", "1"), FakeClient())
        path = out / "visible/observations" / "view_1.md"
        path.write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "modified"):
            run(self.args("--resume", str(out)), FakeClient())
        (self.scene / "view_01.png").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            run(self.args("--resume", str(out)), FakeClient())

    def test_stage2_uses_existing_observations(self):
        out = run(self.args("--stage", "1"), FakeClient())
        client = FakeClient([CORRESPONDENCE])
        run(self.args("--stage", "2", "--resume", str(out)), client)
        self.assertEqual(len(client.calls), 1)
        self.assertFalse((out / "full/central_llm/scene_graph.md").exists())
        run(self.args("--stage", "3", "--resume", str(out)), FakeClient([GRAPH]))
        self.assertTrue((out / "full/central_llm/scene_graph.md").exists())

    def test_format_repair_is_bounded_and_preserves_raw_answer(self):
        client = FakeClient(["bad", observation(1), *list(OBSERVATIONS.values())[1:], CORRESPONDENCE, GRAPH])
        out = run(self.args(), client)
        self.assertIsNotNone(client.calls[1]["repair"])
        self.assertEqual((out / "visible/responses" / "view_1_01.md").read_text(), "bad")
        with self.assertRaises(ValidationError):
            run(self.args("--format-retries", "1"), FakeClient(["bad", "still bad"]))

    def test_truncated_response_is_not_accepted(self):
        client = FakeClient()
        with patch.object(client, "chat", return_value={
            "done": True, "done_reason": "length", "message": {"content": observation(1)}
        }), self.assertRaisesRegex(ValueError, "truncated"):
            run(self.args(), client)
        out = next((self.root / "outputs").iterdir()) / "scene"
        self.assertFalse((out / "visible/observations" / "view_1.md").exists())

    def test_dry_run_never_contacts_server(self):
        client = FakeClient()
        with patch.object(client, "preflight", side_effect=AssertionError("network")):
            out = run(self.args("--dry-run"), client)
        self.assertFalse(client.calls)
        self.assertEqual(len(list((out / "visible/prompts").iterdir())) + len(list((out / "full/central_llm/prompts").iterdir())), 6)
        self.assertFalse((out / "full/central_llm/scene_graph.md").exists())

    def test_camera_allowlist_and_path_validation(self):
        loaded = load_scene(self.scene)
        self.assertEqual(loaded["cameras"]["views"]["view_1"]["cameraPosition"]["y"], 1.6)
        self.assertNotIn("GROUND_TRUTH_LEAK", json.dumps(loaded["cameras"]))
        self.data["views"][0]["image"] = "../view_01.png"
        self.save_scene()
        with self.assertRaises(ValueError):
            load_scene(self.scene)

    def test_duplicate_views_or_nonfinite_pose_rejected(self):
        original_name = self.data["views"][0]["image"]
        self.data["views"][0]["image"] = "view_02.png"
        self.save_scene()
        with self.assertRaises(ValueError):
            load_scene(self.scene)
        self.data["views"][0]["image"] = original_name
        self.data["views"][0]["cameraPosition"]["y"] = float("nan")
        self.save_scene()
        with self.assertRaises(ValueError):
            load_scene(self.scene)

    def test_concurrent_writers_rejected(self):
        with run_lock(self.root):
            with self.assertRaisesRegex(ValueError, "locked"):
                with run_lock(self.root):
                    pass
        self.assertFalse((self.root / ".run.lock").exists())


class HTTPClientTests(unittest.TestCase):
    def test_http_payload_and_error_handling(self):
        captured = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                captured.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                if self.path == "/error":
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'{"error":"test failure"}')
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"message":{"content":"ok"},"done":true}')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            client = OllamaClient(f"http://127.0.0.1:{server.server_port}")
            client.thinking_supported = True
            self.assertTrue(client.chat("rules", "prompt", image=b"PNG")["done"])
            payload = captured[0]
            self.assertEqual(payload["messages"][1]["images"], ["UE5H"])
            self.assertFalse(payload["stream"])
            self.assertNotIn("format", payload)
            self.assertFalse(payload["think"])
            client.chat("rules", "central task")
            self.assertTrue(captured[1]["think"])
            self.assertNotIn("images", captured[1]["messages"][1])
            with self.assertRaisesRegex(OllamaError, "500"):
                client.request("/error", {})
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    unittest.main()

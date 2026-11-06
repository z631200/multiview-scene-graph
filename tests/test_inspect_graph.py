import json
from pathlib import Path
import tempfile
import unittest

from visualization.inspect_graph import load_run, render_html


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "visible").mkdir()
        self.graph = {"view_id": "view_1", "status": "complete", "nodes": [
            {"id": "cup", "objectType": "Cup", "name": "Cup"},
            {"id": "table", "objectType": "CounterTop", "name": "Table"}],
            "edges": [{"id": "e1", "source": "cup", "target": "table", "relation": "on"}]}
        self.save()

    def save(self):
        (self.root / "visible/view_1.json").write_text(json.dumps(self.graph))

    def test_measurements_are_optional(self):
        data = load_run(self.root)
        self.assertEqual(data["graphs"][0]["measurements"], {})
        (self.root / "measurements").mkdir()
        measurement = {"view_id": "view_1", "objects": {"cup": {"mask_center_x_px": 3}}}
        (self.root / "measurements/view_1.json").write_text(json.dumps(measurement))
        self.assertEqual(load_run(self.root)["graphs"][0]["measurements"], measurement)

    def test_initial_selection_and_no_external_dependencies(self):
        html = render_html(load_run(self.root), types=["cUP"], relations=["on"], scope="connected")
        payload = json.loads(html.split('<script type="application/json" id="data">')[1].split('</script>')[0])
        self.assertEqual(payload["initial"], {"view": "view_1", "types": ["Cup"],
                                             "relations": ["on"], "scope": "connected"})
        self.assertNotIn('<script src=', html)

    def test_input_cannot_close_embedded_script(self):
        self.graph["nodes"][0]["name"] = '</script><script>alert("bad")</script>'
        self.save()
        html = render_html(load_run(self.root))
        self.assertNotIn(self.graph["nodes"][0]["name"], html)
        self.assertIn('\\u003c/script>', html)

    def test_invalid_selection_rejected(self):
        data = load_run(self.root)
        for kwargs in ({"view": "view_9"}, {"types": ["Typo"]}, {"relations": ["above"]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                render_html(data, **kwargs)

    def test_dangling_edge_and_draft_rejected(self):
        for corruption in ("endpoint", "draft", "duplicate", "view"):
            with self.subTest(corruption=corruption):
                original = json.loads(json.dumps(self.graph))
                if corruption == "endpoint": self.graph["edges"][0]["target"] = "unknown"
                if corruption == "draft": self.graph["status"] = "needs_review"
                if corruption == "duplicate": self.graph["nodes"].append(self.graph["nodes"][0])
                if corruption == "view": self.graph["view_id"] = "view_2"
                self.save()
                with self.assertRaises(ValueError): load_run(self.root)
                self.graph = original

    def test_legacy_visible_draft_without_kind_in_definitions(self):
        (self.root / "visible").rename(self.root / "drafts")
        self.graph.update(status="needs_review", graph_type="visible_ground_truth")
        (self.root / "drafts/view_1.json").write_text(json.dumps(self.graph))
        (self.root / "definitions.json").write_text(json.dumps({"version": "legacy"}))
        with self.assertRaises(ValueError):
            load_run(self.root)
        self.assertEqual(load_run(self.root, include_drafts=True)["graphs"][0]["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()

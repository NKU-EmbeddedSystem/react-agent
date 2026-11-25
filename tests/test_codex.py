"""The Codex wrapper: the reading of a final message that is not one JSON object, and the switch that
takes the collaboration tools away."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.codex import _no_agents, final_object

REQUIRED = ["outcomes", "notes", "issues"]
ANSWER = {"outcomes": [{"yield_text": "56"}], "notes": "", "issues": []}


class FinalObject(unittest.TestCase):
    def test_prose_before_the_object(self):
        text = "The table reading is right; entry 3 matches the SI.\n" + json.dumps(ANSWER)
        self.assertEqual(final_object(text, REQUIRED), ANSWER)

    def test_the_object_repeated(self):
        text = json.dumps(ANSWER) + json.dumps(ANSWER)
        self.assertEqual(final_object(text, REQUIRED), ANSWER)

    def test_streamed_in_pieces_the_complete_one_last(self):
        pieces = [{"outcomes": [], "notes": ""}, {"issues": []}, {"outcomes": [], "notes": "", "issues": []}]
        text = "".join(json.dumps(p) for p in pieces) + json.dumps(ANSWER)
        self.assertEqual(final_object(text, REQUIRED), ANSWER)

    def test_two_complete_answers_the_later_wins(self):
        revised = {**ANSWER, "notes": "revised"}
        self.assertEqual(final_object(json.dumps(ANSWER) + json.dumps(revised), REQUIRED), revised)

    def test_nothing_complete_takes_the_largest(self):
        text = json.dumps({"notes": ""}) + " and " + json.dumps({"notes": "", "outcomes": [1, 2, 3]})
        self.assertEqual(final_object(text, REQUIRED), {"notes": "", "outcomes": [1, 2, 3]})

    def test_braces_in_prose_are_skipped(self):
        text = "Entry {3} uses the {standard} conditions. " + json.dumps(ANSWER)
        self.assertEqual(final_object(text, REQUIRED), ANSWER)

    def test_no_object(self):
        self.assertIsNone(final_object("no answer at all", REQUIRED))
        self.assertIsNone(final_object("", REQUIRED))


if __name__ == "__main__":
    unittest.main()


class NoAgents(unittest.TestCase):
    def args(self, home):
        _no_agents.cache_clear()
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            try:
                return _no_agents()
            finally:
                _no_agents.cache_clear()

    def test_catalog_without_multi_agent_version(self):
        with tempfile.TemporaryDirectory() as home:
            cache = {"fetched_at": "x", "models": [{"slug": "m1", "multi_agent_version": "v2", "context_window": 9},
                                                   {"slug": "m2"}]}
            (Path(home) / "models_cache.json").write_text(json.dumps(cache))
            args = self.args(home)
            self.assertEqual(args[:2], ["-c", "features.multi_agent=false"])
            self.assertEqual(args[2], "-c")
            path = Path(json.loads(args[3].split("=", 1)[1]))
            catalog = json.loads(path.read_text())
            self.assertEqual([m["multi_agent_version"] for m in catalog["models"]], [None, None])
            self.assertEqual(catalog["models"][0]["context_window"], 9)
            self.assertEqual(self.args(home), args)  # same cache, same file

    def test_no_cache_switches_the_feature_off_only(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertEqual(self.args(home), ["-c", "features.multi_agent=false"])

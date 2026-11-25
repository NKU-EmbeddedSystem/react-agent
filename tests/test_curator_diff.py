import unittest

from curator.diff import diff, render_path


def part(key, **kw):
    return {"key": key, "label": key, "amount": None, **kw}


class Diff(unittest.TestCase):
    def test_equal_is_empty(self):
        value = {"a": [1, {"key": "x", "v": [1, 2]}], "b": None}
        self.assertEqual(diff(value, {"b": None, "a": [1, {"v": [1, 2], "key": "x"}]}), [])
        self.assertEqual(diff([], []), [])

    def test_scalars_and_type_changes(self):
        self.assertEqual(diff(1, 2), [{"op": "change", "path": [], "old": 1, "new": 2}])
        # 1 and True are equal in Python but not the same value in a record.
        self.assertEqual(len(diff({"a": 1}, {"a": True})), 1)
        self.assertEqual(len(diff({"a": 0.0}, {"a": False})), 1)

    def test_numbers_by_value(self):
        # A browser sends 126.0 back as 126 (JSON.parse, JSON.stringify): no change.
        self.assertEqual(diff({"bbox": [323.9, 126.0, 532.8, 137.0]}, {"bbox": [323.9, 126, 532.8, 137]}), [])
        self.assertEqual(diff(-0.0, 0), [])
        self.assertEqual(diff({"a": 126.0}, {"a": 126.5}),
                         [{"op": "change", "path": ["a"], "old": 126.0, "new": 126.5}])
        self.assertEqual(len(diff(10 ** 30, 1e30)), 1)  # not the same number
        self.assertEqual(diff({"a": {"b": 1}}, {"a": [1]}),
                         [{"op": "change", "path": ["a"], "old": {"b": 1}, "new": [1]}])
        self.assertEqual(diff({"a": None}, {"a": "x"})[0]["op"], "change")

    def test_dict_keys_added_and_removed_in_sorted_order(self):
        ops = diff({"b": 1, "z": 2, "a": {"x": 1}}, {"c": 3, "a": {"x": 2}, "b": 1})
        self.assertEqual([(o["op"], o["path"]) for o in ops],
                         [("change", ["a", "x"]), ("add", ["c"]), ("remove", ["z"])])
        self.assertEqual((ops[1]["old"], ops[1]["new"]), (None, 3))
        self.assertEqual((ops[2]["old"], ops[2]["new"]), (2, None))

    def test_keyed_lists_match_by_key(self):
        old = [part("1a"), part("2a"), part("3a")]
        new = [part("1a", amount="0.2 mmol"), part("new"), part("2a"), part("3a")]
        ops = diff({"reactants": old}, {"reactants": new}, ("data",))
        # Inserting an item is one addition, not a change of every item after it.
        self.assertEqual([(o["op"], o["path"]) for o in ops], [
            ("change", ["data", "reactants", {"key": "1a"}, "amount"]),
            ("add", ["data", "reactants", {"key": "new"}])])
        self.assertEqual(ops[1]["new"], part("new"))
        ops = diff(old, [part("1a"), part("3a")])
        self.assertEqual(ops, [{"op": "remove", "path": [{"key": "2a"}], "old": part("2a"), "new": None}])

    def test_reorder(self):
        old = [part("a"), part("b"), part("c")]
        ops = diff(old, [part("c"), part("a", label="A"), part("b")])
        self.assertEqual(ops[0], {"op": "change", "path": [{"key": "a"}, "label"], "old": "a", "new": "A"})
        self.assertEqual(ops[1], {"op": "reorder", "path": [], "old": ["a", "b", "c"], "new": ["c", "a", "b"]})
        # Removing one item is not a reorder of the others.
        self.assertEqual([o["op"] for o in diff(old, [part("a"), part("c")])], ["remove"])

    def test_empty_side_of_a_keyed_list(self):
        self.assertEqual(diff([], [part("x")]), [{"op": "add", "path": [{"key": "x"}], "old": None, "new": part("x")}])

    def test_unkeyed_lists_by_index(self):
        self.assertEqual(diff(["a", "b"], ["a", "c", "d"]), [
            {"op": "change", "path": [1], "old": "b", "new": "c"},
            {"op": "add", "path": [2], "old": None, "new": "d"}])
        self.assertEqual(diff([1, 2, 3], [1]), [
            {"op": "remove", "path": [1], "old": 2, "new": None},
            {"op": "remove", "path": [2], "old": 3, "new": None}])
        # Duplicate keys: not addressable by key, compared by index.
        ops = diff([part("a"), part("a")], [part("a"), part("a", label="z")])
        self.assertEqual(ops[0]["path"], [1, "label"])
        # Items without a key (outcomes) are nested by index.
        ops = diff([{"yield": {"value": 1}}], [{"yield": {"value": 2}}])
        self.assertEqual(ops[0]["path"], [0, "yield", "value"])

    def test_deterministic(self):
        a = {"x": [part("1"), part("2")], "y": {"q": 1, "p": 2}}
        b = {"y": {"p": 3, "q": 4}, "x": [part("2"), part("1", label="one")]}
        self.assertEqual(diff(a, b), diff(dict(reversed(a.items())), b))


class RenderPath(unittest.TestCase):
    def test_render(self):
        self.assertEqual(render_path(["data", "steps", 0, "reactants", {"key": "1a"}, "amount"]),
                         "data.steps[0].reactants[1a].amount")
        self.assertEqual(render_path(["review_status"]), "review_status")
        self.assertEqual(render_path([0, "x"]), "[0].x")
        self.assertEqual(render_path([]), "")
        self.assertEqual(render_path(["steps", 1, "products", {"key": "3a′"}]), "steps[1].products[3a′]")


if __name__ == "__main__":
    unittest.main()

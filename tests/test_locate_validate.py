import copy
import json
import unittest

from pipeline.steps.s1_locate import SCHEMA_PATH, validate

SCHEMA = json.loads(SCHEMA_PATH.read_text())
MANIFESTS = {
    "main": {"page_count": 3, "pages": [{"size_pt": [600, 800]}] * 3},
    "si": {"page_count": 10, "pages": [{"size_pt": [612, 792]}] * 10},
}
CANDIDATES = [
    {"candidate_id": "main:p2:b3", "doc": "main", "page": 2, "bbox": [50, 60, 300, 80], "text": "Scheme 2. Scope"},
    {"candidate_id": "main:p3:b1", "doc": "main", "page": 3, "bbox": [50, 60, 300, 80], "text": "Table 1 summarises"},
]


def block(**kw):
    b = {"block_id": "A", "page": 2, "bbox": [50, 90, 300, 400], "title": None,
         "kind": "substrate_scope", "layout": "product_scope", "scheme_id": "main:scheme2-general",
         "general_reaction": "1 + 2 -> 3", "conditions_text": "Fe cat.",
         "n_entries_est": 20, "labels_seen": "3a-3t", "entries_first_page": None,
         "entries_last_page": None, "include": True, "notes": ""}
    b.update(kw)
    return b


def valid():
    return {
        "paper": {"reaction_class": "Fe-catalyzed coupling", "numbering_convention": "3xy", "notes": ""},
        "si_sections": [
            {"section_id": "si-sec:5", "title": "Typical procedure", "first_page": 4, "last_page": 4,
             "kind": "general_procedure", "notes": ""},
            {"section_id": "si-sec:9", "title": "Product data", "first_page": 5, "last_page": 9,
             "kind": "characterization", "notes": ""},
        ],
        "schemes": [{"scheme_id": "main:scheme2-general", "doc": "main", "page": 2,
                     "bbox": [50, 90, 300, 130], "description": "1 + 2 -> 3"}],
        "regions": [{
            "region_id": "main:scheme2", "doc": "main", "first_page": 2, "last_page": 2,
            "boxes": [{"page": 2, "bbox": [45, 55, 305, 410]}], "label": "Scheme 2",
            "caption": "Scheme 2. Scope", "kind": "substrate_scope", "include": True,
            "exclude_reason": None, "presentation": "vector_graphic", "footnotes": None,
            "blocks": [block()],
            "related": [{"target_id": "si-sec:5", "relation": "procedure_in"},
                        {"target_id": "si-sec:9", "relation": "characterization_in"}],
            "notes": "",
        }],
        "caption_check": [
            {"candidate_id": "main:p2:b3", "region_id": "main:scheme2", "reason": None},
            {"candidate_id": "main:p3:b1", "region_id": None, "reason": "in-text reference"},
        ],
    }


def check(data):
    return validate(data, MANIFESTS, CANDIDATES, SCHEMA)


class ValidateLocate(unittest.TestCase):
    def assertError(self, data, fragment):
        errors, _ = check(data)
        self.assertTrue(any(fragment in e for e in errors), f"no error containing {fragment!r}: {errors}")

    def test_valid_passes(self):
        errors, warnings = check(valid())
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_schema_bbox_length(self):
        d = valid()
        d["regions"][0]["boxes"][0]["bbox"] = [1, 2, 3]
        self.assertError(d, "schema at /regions/0/boxes/0/bbox")

    def test_bbox_outside_page(self):
        d = valid()
        d["regions"][0]["boxes"][0]["bbox"] = [45, 55, 700, 410]
        self.assertError(d, "exceeds page size")

    def test_inverted_bbox(self):
        d = valid()
        d["regions"][0]["blocks"][0]["bbox"] = [300, 90, 50, 400]
        self.assertError(d, "needs x0<x1")

    def test_page_out_of_range(self):
        d = valid()
        d["regions"][0]["last_page"] = 7
        self.assertError(d, "page 7 out of range")

    def test_block_outside_region(self):
        d = valid()
        d["regions"][0]["blocks"][0]["bbox"] = [50, 500, 300, 700]
        self.assertError(d, "is not inside the region box")

    def test_block_slightly_outside_is_tolerated(self):
        d = valid()
        d["regions"][0]["blocks"][0]["bbox"] = [40, 90, 310, 415]
        self.assertEqual(check(d)[0], [])

    def test_unknown_related_target(self):
        d = valid()
        d["regions"][0]["related"].append({"target_id": "si:table-s9", "relation": "subset_of"})
        self.assertError(d, "related target 'si:table-s9'")

    def test_missing_caption_candidate(self):
        d = valid()
        d["caption_check"].pop()
        self.assertError(d, "candidate main:p3:b1 is not accounted for")

    def test_caption_without_region_or_reason(self):
        d = valid()
        d["caption_check"][1]["reason"] = " "
        self.assertError(d, "give a region_id or a reason")

    def test_excluded_region_needs_reason(self):
        d = valid()
        d["regions"][0]["include"] = False
        self.assertError(d, "needs exclude_reason")

    def test_included_region_needs_included_block(self):
        d = valid()
        d["regions"][0]["blocks"][0]["include"] = False
        self.assertError(d, "at least one included block")

    def test_duplicate_ids(self):
        d = valid()
        d["regions"].append(copy.deepcopy(d["regions"][0]))
        self.assertError(d, "duplicate region_id")

    def test_entries_pages_pair(self):
        d = valid()
        d["regions"][0]["blocks"][0]["entries_first_page"] = 5
        self.assertError(d, "set both entries_first_page and entries_last_page")

    def test_scheme_references(self):
        d = valid()
        d["regions"][0]["blocks"][0]["scheme_id"] = "main:nope"
        self.assertError(d, "is not listed under schemes")
        d = valid()
        d["schemes"][0]["doc"] = "si"
        self.assertError(d, "a block follows a scheme of its own document")
        d = valid()
        d["schemes"][0]["bbox"] = [50, 90, 900, 130]
        self.assertError(d, "exceeds page size")
        d = valid()
        d["regions"][0]["blocks"][0]["scheme_id"] = None
        errors, warnings = check(d)
        self.assertEqual(errors, [])
        self.assertTrue(any("not referenced by any block" in w for w in warnings))

    def test_documents_out_of_scope(self):
        main_only = lambda d: validate(d, MANIFESTS, CANDIDATES, SCHEMA, ["main"])[0]
        d = valid()
        self.assertTrue(any("si_sections must be empty" in e for e in main_only(d)))
        d["si_sections"], d["regions"][0]["related"] = [], []
        self.assertEqual(main_only(d), [])
        d["regions"][0]["doc"] = "si"
        self.assertTrue(any("document 'si' is out of scope" in e for e in main_only(d)))

    def test_block_layout(self):
        d = valid()
        d["regions"][0]["blocks"][0]["layout"] = "condition_table"
        self.assertEqual(check(d)[0], [])
        d["regions"][0]["blocks"][0]["layout"] = "table"
        self.assertError(d, "schema at /regions/0/blocks/0/layout")
        del d["regions"][0]["blocks"][0]["layout"]
        self.assertError(d, "'layout' is a required property")

    def test_overlapping_sections_warn(self):
        d = valid()
        d["si_sections"][1]["first_page"] = 3
        errors, warnings = check(d)
        self.assertEqual(errors, [])
        self.assertTrue(any("overlap" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()

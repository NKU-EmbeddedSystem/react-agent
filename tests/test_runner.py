"""When the runner takes a step as up to date."""

import unittest

from pipeline.runner import has_failures


class HasFailures(unittest.TestCase):
    def test_failed_sessions_make_the_step_run_again(self):
        self.assertTrue(has_failures({"reactions_ok": 114, "reactions_failed": 2, "records": 114}))
        self.assertTrue(has_failures({"inventories_failed": 1}))

    def test_a_clean_or_filtered_run_is_up_to_date(self):
        self.assertFalse(has_failures({"reactions_ok": 87, "reactions_failed": 0, "records": 87}))
        self.assertFalse(has_failures({"reactions_ok": 3, "reactions_pending": 40}))
        self.assertFalse(has_failures(None))
        self.assertFalse(has_failures({"tokens": {"input_tokens": 5}}))

import json
import unittest
from pathlib import Path

import uidump_compactor as uc


SAMPLE = Path(__file__).with_name("sample_dump.xml").read_text(encoding="utf-8")


class UidumpCompactorTests(unittest.TestCase):
    def test_default_lines_fold_actionable_labels(self):
        options = uc.Options(attrs=list(uc.DEFAULT_PRESETS["llm"]["attrs"]))
        result = uc.compact_xml(SAMPLE, options)

        self.assertLess(result.out_bytes, result.raw_bytes)
        self.assertIn("LinearLayout|pkg=com.example|id=login_row", result.output)
        self.assertIn('t="Sign in | Use your account"', result.output)
        self.assertNotIn("ImageView", result.output)

    def test_default_lines_include_package(self):
        options = uc.Options(attrs=list(uc.DEFAULT_PRESETS["llm"]["attrs"]))
        result = uc.compact_xml(SAMPLE, options)

        self.assertIn("|pkg=com.example|", result.output)

    def test_disabled_flag_and_duplicate_desc_removed(self):
        options = uc.Options(attrs=list(uc.DEFAULT_PRESETS["llm"]["attrs"]))
        result = uc.compact_xml(SAMPLE, options)

        submit_line = next(line for line in result.output.splitlines() if "id=submit" in line)
        self.assertIn("f=CFD", submit_line)
        self.assertNotIn("d=Continue", submit_line)

    def test_attrs_filter_can_remove_coordinates(self):
        options = uc.Options(attrs=["text", "resource-id"], coords="center", prune="actionable")
        result = uc.compact_xml(SAMPLE, options)

        self.assertIn("id=email", result.output)
        self.assertNotIn("|p=", result.output)
        self.assertNotIn("|b=", result.output)

    def test_json_format_is_machine_readable(self):
        options = uc.Options(attrs=list(uc.DEFAULT_PRESETS["llm"]["attrs"]), output_format="json")
        result = uc.compact_xml(SAMPLE, options)
        payload = json.loads(result.output)

        self.assertEqual(payload["v"], uc.VERSION)
        self.assertGreaterEqual(len(payload["nodes"]), 3)
        self.assertEqual(payload["nodes"][0][2]["pkg"], "com.example")

    def test_diff_reports_added_and_removed(self):
        after = SAMPLE.replace("Continue", "Done")
        options = uc.Options(attrs=list(uc.DEFAULT_PRESETS["llm"]["attrs"]))
        output = uc.diff_xml(SAMPLE, after, options)

        self.assertIn("# diff added=1 removed=1", output)
        self.assertIn("t=Done", output)


if __name__ == "__main__":
    unittest.main()

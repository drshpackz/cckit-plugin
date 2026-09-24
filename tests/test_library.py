"""Конструктор ассистентов: каталог из манифестов, заказ деталей, скачивание из git."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("lib", os.path.join(HERE, "..", "bin", "cckit_library.py"))
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)


class TestLibrary(unittest.TestCase):
    def test_the_index_is_built_from_manifests_and_holds_parts_and_roles(self):
        with tempfile.TemporaryDirectory() as d:
            lib.index(d)
            data = json.load(open(os.path.join(d, "library.json"), encoding="utf-8"))
        kinds = {c["kind"] for c in data["components"]}
        self.assertTrue({"hook", "format", "practice", "setting", "skill"} <= kinds, kinds)
        self.assertEqual({r["id"] for r in data["roles"]}, set(os.listdir(os.path.join(HERE, "..", "assistants"))) & {r["id"] for r in data["roles"]})
        self.assertGreaterEqual(len(data["roles"]), 4)

    def test_a_roles_permissions_are_the_installers_not_a_retelling(self):
        for r in lib.roles():
            with self.subTest(r["id"]):
                self.assertFalse(set(r["tools_allowed"]) & set(r["tools_denied"]))
                self.assertEqual("Edit" in r["tools_allowed"], r["access"] == "write-scoped")
                self.assertIn("ReportFindings", r["tools_denied"])

    def test_an_order_merges_parts_into_one_card(self):
        o = lib.order(["reports-to-main", "keeps-learned", "splits-work"], {})
        self.assertEqual(o["card"]["hooks"], ["report-done", "lint-learned"])
        self.assertEqual(o["grants"], ["spawn"])
        self.assertTrue(o["role_text"])

    def test_a_part_that_needs_input_says_so(self):
        self.assertTrue(any("ledger" in e for e in lib.order(["reads-ledger"], {})["errors"]))
        self.assertFalse(lib.order(["reads-ledger"], {"ledger": "docs/STATE.md"})["errors"])

    def test_an_unwired_part_is_flagged_and_an_unknown_need_is_named(self):
        o = lib.order(["writes-findings", "teleports"], {})
        self.assertIn("formats", o["wired_later"])
        self.assertEqual(o["not_found"], ["teleports"])

    def test_fetch_brings_only_the_ordered_parts_at_the_pinned_version(self):
        with tempfile.TemporaryDirectory() as d:
            got = lib.fetch(["writes-findings"], d)
            self.assertIn("formats/seed-record/TEMPLATE.md", got)
            self.assertFalse(any(f.startswith("hooks/") for f in got))
            head = subprocess.run(["git", "-C", lib.ROOT, "show", "HEAD:formats/seed-record/TEMPLATE.md"], capture_output=True, check=True).stdout
            self.assertEqual(open(os.path.join(d, "formats/seed-record/TEMPLATE.md"), "rb").read(), head)

    def test_a_unit_is_a_base_role_plus_parts_and_fetches_everything_in_its_card(self):
        u = lib.assemble("design-scout", ["reports-to-main", "writes-findings", "long-tasks"], {})
        self.assertIn("name: design-scout", u["card_yaml"])
        self.assertIn("formats: [seed-record]", u["card_yaml"])
        self.assertIn("compact_at: 900000", u["card_yaml"])
        for hook in lib.parse(u["card_yaml"])["hooks"]:
            self.assertIn("hooks/assistant/" + hook, u["fetch"])

    def test_an_unknown_base_role_is_named_with_the_choices(self):
        self.assertIn("есть:", lib.assemble("nobody", [], {})["errors"][0])


if __name__ == "__main__":
    unittest.main()

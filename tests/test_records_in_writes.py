"""records: вне writes: — установка отказывает: записи, которые нельзя писать, бесполезны."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ck", os.path.join(HERE, "..", "bin", "cckit_assistant.py"))
ck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ck)


class TestRecordsLieInsideWrites(unittest.TestCase):
    def card(self, writes, records):
        return {"formats": ["seed-record"], "writes": writes, "records": records, "hooks": ["lint-records"]}

    def test_records_inside_writes_pass(self):
        self.assertEqual(ck.card_formats(self.card(["docs/vscode-internals/**"], ["docs/vscode-internals/dossiers/*.md"])), ["seed-record"])

    def test_records_outside_writes_stop_the_install_and_say_why(self):
        with self.assertRaises(SystemExit):
            ck.card_formats(self.card(["docs/vscode-internals/**"], ["docs/dossiers/*.md"]))

    def test_glob_root(self):
        self.assertEqual(ck._glob_root("docs/x/**/*.md"), "docs/x")
        self.assertEqual(ck._glob_root("**"), "")


if __name__ == "__main__":
    unittest.main()

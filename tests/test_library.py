"""Конструктор ассистентов: каталог из манифестов, заказ деталей, скачивание из git."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from unittest import mock

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
        comps = [dict(c, status="wired-later") if c["id"] == "seed-record" else c for c in lib.load()]
        o = lib.order(["writes-findings", "teleports"], {}, comps=comps)
        self.assertIn("formats", o["wired_later"])
        self.assertEqual(o["not_found"], ["teleports"])

    def test_every_input_becomes_a_card_line_not_only_the_ledger(self):
        o = lib.order(["writes-findings"], {"records": "docs/dossiers", "ledger": "docs/STATE.md"})
        self.assertEqual(o["card_lines"], ["records: docs/dossiers", "ledger: docs/STATE.md"])
        u = lib.assemble("design-scout", ["writes-findings"], {"records": "docs/dossiers"})
        self.assertIn("records: docs/dossiers", u["card_yaml"])

    def test_fetch_brings_only_the_ordered_parts_at_the_pinned_version(self):
        with tempfile.TemporaryDirectory() as d:
            got = lib.fetch(["writes-findings"], d)
            self.assertIn("formats/seed-record/TEMPLATE.md", got)
            self.assertFalse(any(f.startswith(("skills/", "practices/", "assistants/")) for f in got))
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


def _strip_commits(data):
    return {k: [{f: v for f, v in x.items() if f != "commit"} for x in xs] for k, xs in data.items()}


class TestVersionsAndApi(unittest.TestCase):
    """Версия — по содержимому, каталог свежий в том же коммите, скачивание сверяет хэш."""

    def test_a_version_is_the_hash_of_the_manifest_and_the_parts_files(self):
        c = next(c for c in lib.load() if c["id"] == "seed-record")
        self.assertIn("formats/seed-record/TEMPLATE.md", c["blobs"])
        pairs = [(p, lib._blob(p)) for p in set([c["manifest"]] + c["blobs"])]
        self.assertEqual(c["version"], lib.digest(pairs))
        self.assertNotEqual(lib.digest(pairs), lib.digest(pairs[1:] + [(pairs[0][0], pairs[0][1] + b"x")]))
        self.assertEqual(lib.digest([("a", b"1\r\n")]), lib.digest([("a", b"1\n")]))

    def test_the_published_catalog_is_fresh(self):
        # API = library.json в репозитории. Отстал от деталей — чужой fetch откажет по хэшу.
        with tempfile.TemporaryDirectory() as d:
            lib.index(d)
            for name, load in (("library.json", lambda fh: _strip_commits(json.load(fh))), ("LIBRARY.md", lambda fh: fh.read())):
                with self.subTest(name):
                    with open(os.path.join(d, name), encoding="utf-8") as a, open(os.path.join(lib.ROOT, name), encoding="utf-8") as b:
                        self.assertEqual(load(a), load(b), "каталог устарел: python3 bin/cckit_library.py index")

    def _remote(self, tamper=None):
        """Поддельный raw.githubusercontent: каталог из index, файлы с диска; tamper — подмена."""
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        lib.index(d)
        prefix = lib.RAW % ("o", "r", "main", "")
        seen = []

        def get(url):
            self.assertTrue(url.startswith(prefix), url)
            path = url[len(prefix):]
            seen.append(path)
            if path == "library.json":
                with open(os.path.join(d, "library.json"), "rb") as fh:
                    return fh.read()
            if tamper and path in tamper:
                return tamper[path]
            return lib._blob(path)
        return get, seen

    def test_fetch_from_gh_verifies_every_part_and_writes_what_matches(self):
        get, seen = self._remote()
        with tempfile.TemporaryDirectory() as to:
            got = lib.fetch_gh("gh:o/r@main", ["writes-findings"], to, get=get)
            self.assertIn("formats/seed-record/TEMPLATE.md", got)
            self.assertTrue(os.path.isfile(os.path.join(to, "formats", "seed-record", "TEMPLATE.md")))
        self.assertEqual(seen[0], "library.json")

    def test_fetch_from_gh_refuses_forged_content_and_writes_nothing(self):
        get, _ = self._remote(tamper={"formats/seed-record/TEMPLATE.md": b"# forged\n"})
        with tempfile.TemporaryDirectory() as to:
            with self.assertRaises(ValueError) as e:
                lib.fetch_gh("gh:o/r@main", ["writes-findings"], to, get=get)
            self.assertIn("seed-record", str(e.exception))
            self.assertEqual(os.listdir(to), [])

    def test_fetch_from_gh_refuses_a_path_outside_the_repo(self):
        with self.assertRaises(ValueError):
            lib._safe("../../.ssh/id_rsa")
        with self.assertRaises(ValueError):
            lib.fetch_gh("github.com/o/r", ["x"], "/nonexistent")


class TestBuild(unittest.TestCase):
    """Сборочный лист → роль-юнит в библиотеке пользователя → установка."""

    def setUp(self):
        self.lib_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.lib_dir, ignore_errors=True))
        patcher = mock.patch.dict(os.environ, {"CCKIT_LIBRARY": self.lib_dir})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.said = []

    def build(self, name="scout-unit", **kw):
        return lib.build("design-scout", ["reports-to-main", "long-tasks", "splits-work"], name, {"ledger": "docs/L.md"},
                         say=self.said.append, **kw)

    def test_build_writes_a_unit_role_into_the_users_library(self):
        self.assertEqual(self.build(), 0, self.said)
        unit = os.path.join(self.lib_dir, "scout-unit")
        card = lib.parse(open(os.path.join(unit, "card.yaml"), encoding="utf-8").read())
        self.assertEqual((card["name"], card["ledger"], card["compact_at"]), ("scout-unit", "docs/L.md", "900000"))
        body = open(os.path.join(unit, "ROLE.md"), encoding="utf-8").read()
        base = open(os.path.join(lib.ROOT, "assistants", "design-scout", "ROLE.md"), encoding="utf-8").read()
        self.assertTrue(body.startswith(base.rstrip("\n")))
        self.assertIn("# Детали юнита", body)
        self.assertIn("субагентам", body.split("# Детали юнита")[1])

    def test_build_does_not_overwrite_a_role_without_force(self):
        self.assertEqual(self.build(), 0)
        card = os.path.join(self.lib_dir, "scout-unit", "card.yaml")
        with open(card, "w", encoding="utf-8") as fh:
            fh.write("name: mine\n")
        self.assertEqual(self.build(), 1)
        self.assertEqual(open(card, encoding="utf-8").read(), "name: mine\n")
        self.assertEqual(self.build(force=True), 0)
        self.assertIn("name: scout-unit", open(card, encoding="utf-8").read())

    def test_build_refuses_a_bad_name_or_a_missing_input_and_writes_nothing(self):
        self.assertEqual(self.build(name="Bad Name"), 2)
        self.assertEqual(lib.build("design-scout", ["writes-findings"], "u1", {}, say=self.said.append), 1)
        self.assertEqual(os.listdir(self.lib_dir), [])

    def test_build_with_install_calls_the_installer_with_the_orders_grants(self):
        calls = []
        self.assertEqual(self.build(project="/p", run=lambda a: calls.append(a) or 0), 0)
        self.assertEqual(calls[0][2:], ["install", "scout-unit", "--project", "/p", "--grant", "spawn"])
        self.assertTrue(calls[0][1].endswith(os.path.join("bin", "cckit_assistant.py")))
        self.build(project="/p", force=True, i_mean_it=True, run=lambda a: calls.append(a) or 0)
        self.assertEqual(calls[1][-2:], ["--force", "--i-mean-it"])


if __name__ == "__main__":
    unittest.main()

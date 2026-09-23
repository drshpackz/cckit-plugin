# Ограда должна считаться из ЧУЖОГО проекта, а не из памяти о своём.
#
# Запреты были перечислены руками: src/, extensions/, build/ — папки VS Code.
# В репозитории на Django таких имён нет, а настоящие не названы нигде. И раз
# ассистенты бегут под bypassPermissions, путь, который не разрешён и не
# запрещён, проходит МОЛЧА: ограда стояла вокруг пустого места.
#
# Поэтому раскладки здесь синтетические и чужие: ни одного дерева этой машины.
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
import cckit_assistant as ck  # noqa: E402

VSCODE_NAMES = ("src", "extensions", "build")


class Layout(unittest.TestCase):
    def make(self, dirs=(), files=()):
        root = tempfile.mkdtemp(prefix="cckit-foreign-")
        self.addCleanup(shutil.rmtree, root, True)
        for d in dirs:
            os.makedirs(os.path.join(root, *d.split("/")), exist_ok=True)
        for f in files:
            p = os.path.join(root, *f.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        return root

    def denies(self, project, writes=()):
        s = ck.compile_settings(
            {"name": "t", "access": "write-scoped" if writes else "read-only",
             "writes": list(writes)}, project, "/home", "t")
        # только хвост правила, без Edit(// и без корня проекта
        out = []
        for rule in s["permissions"]["deny"]:
            if not rule.startswith("Edit("):
                continue
            arg = rule[len("Edit("):-1].lstrip("/")
            out.append(arg[len(project.lstrip("/")):].lstrip("/"))
        return out


class TestForeignLayouts(Layout):
    def test_a_django_project_gets_its_own_folders_denied(self):
        p = self.make(dirs=("app", "migrations", "static"),
                      files=("manage.py", "requirements.txt"))
        d = self.denies(p)
        for name in ("app/**", "migrations/**", "static/**",
                     "manage.py", "requirements.txt"):
            self.assertIn(name, d, "%s не запрещён — под bypass пройдёт молча" % name)

    def test_no_vscode_names_leak_into_a_project_that_has_none(self):
        p = self.make(dirs=("cmd", "internal", "pkg"), files=("go.mod",))
        d = self.denies(p)
        for name in VSCODE_NAMES:
            self.assertNotIn(name + "/**", d,
                             "в чужом проекте запрещена папка %s, которой там нет" % name)
        for name in ("cmd/**", "internal/**", "pkg/**", "go.mod"):
            self.assertIn(name, d)

    def test_a_granted_write_carves_out_only_its_own_path(self):
        p = self.make(dirs=("docs/api", "docs/old", "app"))
        d = self.denies(p, writes=["docs/api/**"])
        self.assertNotIn("docs/**", d, "запрет на docs целиком убил бы выданное")
        self.assertIn("docs/old/**", d, "сосед выданного не запрещён")
        self.assertIn("app/**", d)

    def test_universal_names_are_denied_even_when_absent_from_disk(self):
        # .env и .git встречаются почти везде, а промах стоит дорого.
        d = self.denies(self.make(dirs=("lib",)))
        for name in (".git/**", ".claude/**", ".env", "CLAUDE.md"):
            self.assertIn(name, d)

    def test_an_empty_project_still_denies_the_universal_names(self):
        d = self.denies(self.make())
        self.assertIn(".git/**", d)
        self.assertIn(".env", d)


if __name__ == "__main__":
    unittest.main()


class TestExtraReadOnlyTrees(Layout):
    """Предмет изучения бывает шире одного дерева.

    Ассистент, изучающий семью инструментов, должен читать несколько
    каталогов — и НЕ получать при этом права писать в них.
    """

    def settings_with_extra(self, project, extra):
        return ck.compile_settings(
            {"name": "t", "access": "read-only", "writes": []},
            project, "/home", "t", extra_read=extra)

    def test_each_extra_tree_is_readable(self):
        a, b = self.make(dirs=("x",)), self.make(dirs=("y",))
        allow = self.settings_with_extra(a, [b])["permissions"]["allow"]
        self.assertTrue(any(b.lstrip("/") in r and r.startswith("Read(")
                            for r in allow), allow)

    def test_an_extra_tree_grants_reading_and_not_writing(self):
        a, b = self.make(dirs=("x",)), self.make(dirs=("y",))
        s = self.settings_with_extra(a, [b])
        self.assertFalse(any(r.startswith("Edit(") and b.lstrip("/") in r
                             for r in s["permissions"]["allow"]),
                         "лишнее дерево стало доступно на запись")

    def test_an_extra_tree_is_denied_for_writing_outright(self):
        a, b = self.make(dirs=("x",)), self.make(dirs=("y",))
        s = self.settings_with_extra(a, [b])
        self.assertTrue(any(r.startswith("Edit(") and b.lstrip("/") in r
                            for r in s["permissions"]["deny"]),
                        "под bypass незапрещённая запись проходит молча")

    def test_no_extra_trees_changes_nothing(self):
        a = self.make(dirs=("x",))
        plain = ck.compile_settings({"name": "t", "access": "read-only",
                                     "writes": []}, a, "/home", "t")
        self.assertEqual(self.settings_with_extra(a, [])["permissions"],
                         plain["permissions"])

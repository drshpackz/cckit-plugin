"""Каждая дыра здесь была открыта в отгруженном коде и найдена руками.

Тесты пишутся против СВОЙСТВА ограды, а не против списка починенных
инструментов: перечень закрытых дыр порождает соседние. И против того места,
где ограда правда стоит, — `caps_to_disallowed` и `permissions`, — а не против
того, где её удобно было бы проверять.

Осторожно с подстрокой. `any("Edit" in d for d in deny)` — правда для
`Edit(//p/src/**)`, то есть для запрета ОДНОГО ПУТИ, а не инструмента. Такой
тест зелен при полностью открытом `Edit`. Здесь имена сравниваются точно.
"""

import itertools
import json
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402

PLUGIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def settings(granted=None, home="/h", project="/p", writes=()):
    card = {"name": "t", "access": "write-scoped" if writes else "read-only",
            "writes": list(writes)}
    return ck.compile_settings(card, project, home, "t", granted=granted)


def tools_of(groups):
    out = set()
    for g in groups:
        out |= set(ck.CAPS[g])
    return out


def denied_tools(granted):
    """Что правда снимается с ребёнка: список для --disallowedTools.

    Не `permissions.deny` — там живут правила путей, и инструментов, кроме
    `Bash`, там нет вовсе. Тест, который искал бы Monitor там, был бы зелёным
    ровно до первого запуска.
    """
    return set(ck.caps_to_disallowed(set(granted)))


def all_subsets(names):
    names = sorted(names)
    for r in range(len(names) + 1):
        for c in itertools.combinations(names, r):
            yield set(c)


class TestNoToolEscapesTheDenylist(unittest.TestCase):
    def test_every_tool_is_either_granted_or_denied_for_every_grant(self):
        # Свойство, а не заплатка: при ЛЮБОМ наборе выданных групп каждый
        # инструмент из CAPS либо принадлежит выданной группе, либо назван в
        # отказе. Середины, в которой однажды оказался Monitor, нет.
        everything = tools_of(ck.CAPS)
        for granted in all_subsets(ck.CAPS):
            off = denied_tools(granted)
            allowed = tools_of(granted)
            for tool in everything:
                self.assertTrue(tool in allowed or tool in off,
                                "%s не выдан и не запрещён при выданных %s"
                                % (tool, sorted(granted) or "—"))

    def test_the_denylist_is_exactly_the_ungranted_tools_plus_never(self):
        for granted in all_subsets(ck.CAPS):
            self.assertEqual(
                denied_tools(granted),
                tools_of(set(ck.CAPS) - set(granted)) | set(ck.NEVER),
                "при выданных %s отказ разошёлся с выдачей" % (sorted(granted),))

    def test_no_tool_belongs_to_two_capability_groups(self):
        # Инструмент в двух группах запрещается, пока не выданы ОБЕ: выдача
        # одной рапортует успех, которого нет. Обратная ошибка так же тиха.
        seen = {}
        for group, tools in ck.CAPS.items():
            for tool in tools:
                self.assertNotIn(tool, seen,
                                 "%s и в «%s», и в «%s»" % (tool, seen.get(tool), group))
                seen[tool] = group

    def test_never_and_caps_do_not_overlap(self):
        # Инструмент и в CAPS, и в NEVER нельзя выдать никогда — а команда
        # выдачи об этом промолчит.
        self.assertEqual(tools_of(ck.CAPS) & set(ck.NEVER), set())

    def test_monitor_is_a_shell_and_is_denied_without_the_shell_group(self):
        # Monitor берёт произвольную команду и исполняет её в той же оболочке,
        # что и Bash. Он не входил ни в одну группу, поэтому его никто не
        # снимал: ассистент без Bash исполнял команды через него.
        self.assertIn("Monitor", ck.CAPS["shell"])
        self.assertIn("Monitor", denied_tools(ck.BASE_CAPS))
        self.assertNotIn("Monitor", denied_tools(set(ck.BASE_CAPS) | {"shell"}))

    def test_never_tools_are_denied_even_when_everything_is_granted(self):
        off = denied_tools(set(ck.CAPS))
        for tool in ck.NEVER:
            self.assertIn(tool, off, tool)


class TestPathRules(unittest.TestCase):
    def test_no_bare_tool_name_in_allow(self):
        # Голый "Read" в allow даёт всю файловую систему — доказано чтением
        # /etc/hosts из ассистента, которому полагался один проект.
        with Sandbox() as sb:
            os.makedirs(os.path.join(sb.project, "docs"))
            rules = settings(granted=ck.BASE_CAPS, project=sb.project,
                             home=sb.home, writes=["docs/**"])["permissions"]["allow"]
        self.assertTrue(rules)
        for rule in rules:
            self.assertIn("(", rule, "правило «%s» без пути даёт всю файловую систему" % rule)

    def test_absolute_path_rules_use_the_doubled_slash_form(self):
        with Sandbox() as sb:
            os.makedirs(os.path.join(sb.project, "docs"))
            os.makedirs(os.path.join(sb.project, "src"))
            s = settings(granted=ck.BASE_CAPS, home=sb.home, project=sb.project,
                         writes=["docs/**"])
        checked = 0
        for rule in s["permissions"]["allow"] + s["permissions"]["deny"]:
            if "(" not in rule:
                continue
            arg = rule.split("(", 1)[1].rstrip(")")
            if not arg.startswith("/"):
                continue
            checked += 1
            self.assertTrue(arg.startswith("//"),
                            "%s: одинарный слэш не совпадает ни с чем — ограда мнимая" % rule)
        # Без этого тест был бы зелен на пустом списке правил.
        self.assertGreaterEqual(checked, 4)

    def test_a_declared_write_target_is_not_also_denied(self):
        # Разрешение и запрет на один путь — это запрет, и `--grant write`
        # молча не работает.
        #
        # Проект НАСТОЯЩИЙ, потому что запреты теперь считаются обходом дерева.
        # На выдуманном `/p` обход не находит ничего, запретов нет вовсе, и
        # «выданное не запрещено» оказывается правдой ни о чём.
        with Sandbox() as sb:
            os.makedirs(os.path.join(sb.project, "docs", "api"))
            os.makedirs(os.path.join(sb.project, "src"))
            s = settings(granted=set(ck.BASE_CAPS) | {"write"},
                         project=sb.project, home=sb.home, writes=["docs/api/**"])
            mine = ck.abs_rule("Edit", sb.project + "/docs/api/**")
            self.assertEqual(
                (mine in s["permissions"]["allow"],
                 mine in s["permissions"]["deny"],
                 # обход правда что-то запретил — иначе проверка выше пуста
                 ck.abs_rule("Edit", sb.project + "/src/**") in s["permissions"]["deny"]),
                (True, False, True))


class TestGrant(unittest.TestCase):
    def test_granting_shell_actually_removes_the_bash_denial(self):
        # `--grant shell` рапортовал успех, которого не доставлял: правила
        # запрещали Bash, сколько бы флагов ни стояло в запуске.
        s = settings(granted=set(ck.BASE_CAPS) | {"shell"})
        self.assertNotIn("Bash", s["permissions"]["deny"])

    def test_shell_not_granted_denies_bash_in_the_rules_too(self):
        self.assertIn("Bash", settings(granted=ck.BASE_CAPS)["permissions"]["deny"])

    def test_every_dangerous_group_exists_in_caps(self):
        for g in ck.DANGEROUS:
            self.assertIn(g, ck.CAPS, "опасная группа %s не описана в CAPS" % g)

    def test_mcp_is_a_switch_not_a_tool_list(self):
        # У «mcp» нет инструментов: она правит --strict-mcp-config. Если бы
        # она их получила, проверка «выдан или запрещён» молча ослабла бы.
        self.assertEqual(ck.CAPS["mcp"], [])


class TestTrust(unittest.TestCase):
    def test_trust_marks_both_the_home_and_the_project(self):
        # Недоверенный workspace молча обнуляет все allow: ограда собирается,
        # пишется на диск и не делает ничего.
        with Sandbox() as sb:
            ck.trust([sb.home, sb.project])
            cfg = ck.claude_json()
            self.assertTrue(os.path.exists(cfg), cfg)
            d = json.load(open(cfg, encoding="utf-8"))
            self.assertEqual(
                {p: v.get("hasTrustDialogAccepted") for p, v in d["projects"].items()},
                {sb.home: True, sb.project: True})

    def test_trust_keeps_what_was_already_in_the_config(self):
        # Файл общий с самим Claude Code. Затереть его — снять доверие со всех
        # проектов владельца разом, и узнать об этом только по отказам.
        with Sandbox() as sb:
            with open(ck.claude_json(), "w", encoding="utf-8") as fh:
                json.dump({"numStartups": 7,
                           "projects": {"/old": {"hasTrustDialogAccepted": True}}}, fh)
            ck.trust([sb.project])
            d = json.load(open(ck.claude_json(), encoding="utf-8"))
            self.assertEqual(d["numStartups"], 7)
            self.assertTrue(d["projects"]["/old"]["hasTrustDialogAccepted"])
            self.assertTrue(d["projects"][sb.project]["hasTrustDialogAccepted"])


class TestGrantReachesTheRulesOnDisk(unittest.TestCase):
    """Флаги запуска и правила прав — две записи об одном. Выдача, дошедшая
    только до первой, отчитывается словом «выдано» и ничего не меняет."""

    def _install(self, sb):
        lib = os.path.join(sb.home, ".cckit", "library")
        os.makedirs(lib)
        shutil.copytree(os.path.join(PLUGIN, "assistants", "design-scout"),
                        os.path.join(lib, "design-scout"))
        sb.set_reply("готово", transcript_prompt="неважно")
        ck.cmd_install(["design-scout", "--project", sb.project])
        home = ck.instance_home("design-scout", sb.project)
        return home, os.path.basename(home)

    @staticmethod
    def _deny(home):
        with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
            return json.load(fh)["permissions"]["deny"]

    @staticmethod
    def _disallowed(home):
        with open(os.path.join(home, "launch.json"), encoding="utf-8") as fh:
            return json.load(fh)["disallowed_tools"]

    def test_granting_shell_reaches_the_permission_rules_not_only_the_flags(self):
        with Sandbox() as sb:
            home, name = self._install(sb)
            self.assertIn("Bash", self._deny(home))
            ck.cmd_grant([name, "shell", "--i-mean-it"])
            self.assertEqual(
                ("Bash" in self._deny(home), "Bash" in self._disallowed(home)),
                (False, False))

    def test_revoking_shell_puts_the_denial_back_into_the_rules(self):
        # Отзыв проверяется ТОЛЬКО после того, как выдача правда сняла запрет.
        # Без этой середины тест зелен и на коде, который не трогает правила
        # вовсе: запрет там и не уходил.
        with Sandbox() as sb:
            home, name = self._install(sb)
            ck.cmd_grant([name, "shell", "--i-mean-it"])
            self.assertEqual(
                ("Bash" in self._deny(home), "Bash" in self._disallowed(home)),
                (False, False), "выдача не дошла до правил — отзыв нечему вернуть")
            ck.cmd_grant([name, "shell"], revoking=True)
            self.assertEqual(
                ("Bash" in self._deny(home), "Bash" in self._disallowed(home)),
                (True, True))

    def test_an_owner_rule_closes_the_capability_in_the_rules_too(self):
        # Владелец закрыл «shell» словами. Если запрет доходит только до
        # флагов, правила на диске продолжают его разрешать.
        with Sandbox() as sb:
            home, name = self._install(sb)
            ck.cmd_grant([name, "shell", "--i-mean-it"])
            self.assertEqual(
                ("Bash" in self._deny(home), "Bash" in self._disallowed(home)),
                (False, False), "выдача не дошла до правил — запрещать нечего")
            ck.cmd_owner_rule([name, "deny", "shell", "оболочки ему не надо"])
            self.assertEqual(
                ("Bash" in self._deny(home), "Bash" in self._disallowed(home)),
                (True, True))


if __name__ == "__main__":
    unittest.main()

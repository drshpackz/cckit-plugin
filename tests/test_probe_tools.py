"""Проба набора инструментов — на пути, которым ассистента запускают ЛЮДИ.

Дыра, ради которой она заведена (измерено 2026-09-24): из 21 запрета
design-hand в доме лежал один Bash, остальные ехали только флагом
--disallowedTools установщика. Вкладка этого флага не передаёт, и ассистент
вызвал запрещённые ему ListAgents и SendMessage. Проба, которая шла тем же
путём, что и установщик, эту дыру видеть не могла.

Поэтому здесь утверждается три вещи:
  * проба не передаёт ребёнку argv-ограду вовсе;
  * вердикт берётся из набора, который выдал харнесс, и из стенограммы — не из
    ответа модели;
  * дом, где запрещён один Bash, роняет пробу (а не только юнит-тест правил).
"""

import json
import os
import stat
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402

CARD = {"name": "t", "access": "write-scoped", "writes": ["docs/**"],
        "budget_usd": "0.40"}


def everything():
    out = list(ck.NEVER)
    for tools in ck.CAPS.values():
        out.extend(tools)
    return out


def use_harness(sb, **scenario):
    """Подменяет `claude` песочницы харнессом, который собирает набор сам."""
    sc = {"full": everything(), "deferred": ["WebFetch", "Monitor", "CronList",
                                              "SendMessage", "TodoWrite"]}
    sc.update(scenario)
    with open(os.path.join(sb.state, "harness.json"), "w", encoding="utf-8") as fh:
        json.dump(sc, fh)
    sh = os.path.join(sb.bin, "claude")
    with open(sh, "w", encoding="utf-8") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n'
                 % (sys.executable, os.path.join(HERE, "fake_harness.py")))
    os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR)
    with open(os.path.join(sb.bin, "claude.cmd"), "w", encoding="utf-8") as fh:
        fh.write('@echo off\r\n"%s" "%s" %%*\r\n'
                 % (sys.executable, os.path.join(HERE, "fake_harness.py")))


def build_home(sb, granted=ck.BASE_CAPS + ("write",)):
    home = os.path.join(sb.home, "inst")
    os.makedirs(os.path.join(home, ".claude"))
    os.makedirs(os.path.join(sb.project, "docs"), exist_ok=True)
    ck.apply_grants(home, "t", sb.project, CARD, set(granted), extra_read=[])
    return home, set(granted)


def only_bash_in_deny(home):
    """Дом таким, каким его писал установщик до починки: из запрещённых
    инструментов в правилах — один Bash, правила путей не тронуты."""
    p = os.path.join(home, ".claude", "settings.json")
    with open(p, encoding="utf-8") as fh:
        d = json.load(fh)
    d["permissions"]["deny"] = [r for r in d["permissions"]["deny"]
                                if "(" in r] + ["Bash"]
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(d, fh)


class TestProbeGoesThePeoplePath(unittest.TestCase):
    def test_a_home_that_holds_its_fence_in_files_passes(self):
        with Sandbox() as sb:
            use_harness(sb)
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual((state, len(sb.calls())), ("ок", 1), note)

    def test_the_probe_passes_no_argv_fence_to_the_child(self):
        # Иначе это проба argv, а не дома — ровно та, что пропустила дыру.
        with Sandbox() as sb:
            use_harness(sb)
            home, granted = build_home(sb)
            ck.probe_tools(home, sb.project, granted)
            argv = sb.calls()[0]["argv"]
            self.assertEqual(
                ("--disallowedTools" in argv, "--add-dir" in argv,
                 argv[argv.index("--setting-sources") + 1],
                 sb.calls()[0]["cwd"] == os.path.realpath(home)
                 or sb.calls()[0]["cwd"] == home),
                (False, False, "user,project,local", True), argv)

    def test_a_home_denying_only_bash_breaks_the_probe(self):
        # Главная мутация: правила, какими они были до починки. Флаг
        # --disallowedTools закрыл бы это на пути установщика — проба обязана
        # покраснеть, потому что идёт путём, где флага нет.
        with Sandbox() as sb:
            use_harness(sb)
            home, granted = build_home(sb)
            only_bash_in_deny(home)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual((state, "WebFetch" in note, "Monitor" in note),
                             ("ПРОБОЙ", True, True), note)

    def test_containment_stops_on_a_tool_breach_before_any_write_probe(self):
        with Sandbox() as sb:
            use_harness(sb)
            home, granted = build_home(sb)
            only_bash_in_deny(home)
            state, note = ck.probe_containment(home, sb.project, CARD, granted)
            self.assertEqual((state, len(sb.calls())), ("ПРОБОЙ", 1), note)

    def test_every_containment_run_goes_the_people_path(self):
        # Набор проходит, запись — нет (подделка файлов не пишет), значит
        # вызовов ровно два, и оба без argv-ограды.
        with Sandbox() as sb:
            use_harness(sb)
            home, granted = build_home(sb)
            state, _ = ck.probe_containment(home, sb.project, CARD, granted)
            argvs = [c["argv"] for c in sb.calls()]
            self.assertEqual(
                (state, len(argvs),
                 [("--disallowedTools" in a) or ("--add-dir" in a) for a in argvs]),
                ("не подтвердилась", 2, [False, False]))

    def test_a_granted_group_is_not_denied_and_not_asked_for(self):
        with Sandbox() as sb:
            use_harness(sb, calls=["ListAgents", "SendMessage"])
            home, granted = build_home(sb, ck.BASE_CAPS + ("write", "peers"))
            state, note = ck.probe_tools(home, sb.project, granted)
            prompt = sb.calls()[0]["argv"][sb.calls()[0]["argv"].index("-p") + 1]
            self.assertEqual((state, "ListAgents" in prompt), ("ок", False), note)


class TestTheVerdictIsNotVacuous(unittest.TestCase):
    """Проба, зелёная оттого, что нечего было смотреть, — главный враг."""

    def test_no_init_event_is_not_measured_not_ok(self):
        with Sandbox() as sb:
            use_harness(sb, no_init=True)
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual(state, "не измерено", note)

    def test_an_empty_tool_set_is_not_measured_not_ok(self):
        with Sandbox() as sb:
            use_harness(sb, full=[])
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual(state, "не измерено", note)

    def test_no_transcript_is_not_measured_not_ok(self):
        with Sandbox() as sb:
            use_harness(sb, no_transcript=True)
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual(state, "не измерено", note)


class TestTheTranscriptIsTheSecondWitness(unittest.TestCase):
    def test_a_forbidden_call_that_worked_is_a_breach_even_if_init_hid_it(self):
        with Sandbox() as sb:
            use_harness(sb, calls=["CronList"], late=["CronList"])
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual((state, "CronList" in note), ("ПРОБОЙ", True), note)

    def test_a_forbidden_call_the_harness_refused_is_not_a_breach(self):
        # Модель попробовала, харнесс отказал — это и есть ограда в работе.
        with Sandbox() as sb:
            use_harness(sb, calls=["CronList", "WebSearch"])
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual((state, "попыток вызова: 2" in note), ("ок", True), note)

    def test_a_forbidden_tool_announced_as_deferred_is_a_breach(self):
        # Отложенный = загружаемый через ToolSearch: не в init, но достижим.
        with Sandbox() as sb:
            use_harness(sb, deferred_raw=["Monitor"])
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual((state, "Monitor" in note), ("ПРОБОЙ", True), note)


class TestUnknownToolsAreHoles(unittest.TestCase):
    def test_a_tool_in_no_group_fails_the_probe(self):
        # «Инструмент, не попавший ни в одну группу CAPS, не запрещён ничем» —
        # теперь это видно живьём, а не только в правилах репозитория.
        with Sandbox() as sb:
            use_harness(sb, full=everything() + ["ShinyNewTool"])
            home, granted = build_home(sb)
            state, note = ck.probe_tools(home, sb.project, granted)
            self.assertEqual((state, "ShinyNewTool" in note),
                             ("ДЫРА В CAPS", True), note)

    def test_todowrite_found_live_belongs_to_a_group(self):
        groups = [g for g, tools in ck.CAPS.items() if "TodoWrite" in tools]
        self.assertEqual(groups, ["read"])


if __name__ == "__main__":
    unittest.main()

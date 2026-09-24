"""Ограда дома, которую не видела проба установщика: ось MCP, сам дом, шелл
только субагентам, и уборка дома.

Каждая часть — измеренная дыра (docs/findings/subagents.md):
  * вкладка идёт без --strict-mcp-config, и ассистенту с субагентами
    доставались коннекторы владельца — CCPort send_reply, Claude Docs delete;
  * `Edit(//дом/**)` в allow отдавал ассистенту его же settings.json, хуки,
    карточку и reports.jsonl — канал улик;
  * «не надо было блокировать субагентам вообще bash» — выдача, у которой
    шелл есть у субагентов и нет у ассистента;
  * убрать дом плагин не умел вовсе.
"""

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402
import cckit_core as core  # noqa: E402

PLUGIN = os.path.join(HERE, "..")
CARD = {"name": "t", "access": "write-scoped", "writes": ["docs/**"],
        "budget_usd": "0.40"}
CONNECTORS = {
    "claude.ai Claude Docs": {"status": "connected",
                              "tools": ["create", "delete", "read"]},
    "claude.ai CCPort v6": {"status": "pending",
                            "tools": ["send_reply", "read_file", "git_read"]},
}


def everything():
    out = list(ck.NEVER)
    for tools in ck.CAPS.values():
        out.extend(tools)
    return out


def use_harness(sb, **scenario):
    sc = {"full": everything(), "mcp": CONNECTORS, "search": True}
    sc.update(scenario)
    with open(os.path.join(sb.state, "home_harness.json"), "w", encoding="utf-8") as fh:
        json.dump(sc, fh)
    fake = os.path.join(HERE, "fake_home_harness.py")
    sh = os.path.join(sb.bin, "claude")
    with open(sh, "w", encoding="utf-8") as fh:
        fh.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, fake))
    os.chmod(sh, os.stat(sh).st_mode | stat.S_IXUSR)
    with open(os.path.join(sb.bin, "claude.cmd"), "w", encoding="utf-8") as fh:
        fh.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, fake))


def build_home(sb, granted):
    """Дом, как его собирает установщик: карточка, правила, хуки, рецепт."""
    home = os.path.join(sb.home, "inst")
    os.makedirs(os.path.join(home, ".claude", "agents"))
    os.makedirs(os.path.join(sb.project, "docs"), exist_ok=True)
    ck.write_card(home, "t", CARD, "тело роли")
    ck.apply_grants(home, "t", sb.project, CARD, set(granted), extra_read=[])
    return home


def settings_of(home):
    with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def rewrite_settings(home, fn):
    d = settings_of(home)
    fn(d)
    with open(os.path.join(home, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
        json.dump(d, fh)


def card_text(home):
    with open(os.path.join(home, ".claude", "agents", "t.md"), encoding="utf-8") as fh:
        return fh.read()


def rule_covers(rule, path):
    """Совпадает ли правило пути `Tool(//abs)` с файлом — как у харнесса для
    наших двух форм: точный путь и `<каталог>/**`."""
    if "(" not in rule:
        return False
    arg = rule.split("(", 1)[1][:-1]
    target = "//" + path.replace("\\", "/").lstrip("/")
    if arg.endswith("/**"):
        return target.startswith(arg[:-2])
    return target == arg


def call(argv):
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(out):
        try:
            rc = ck.main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 1
    return rc, out.getvalue()


# ── 1. Ось MCP ────────────────────────────────────────────────────────────

class TestMcpRuleLivesInTheHome(unittest.TestCase):
    def test_without_the_mcp_grant_the_home_denies_every_server(self):
        with Sandbox() as sb:
            home = build_home(sb, ck.BASE_CAPS)
            self.assertIn("mcp__*", settings_of(home)["permissions"]["deny"])

    def test_the_mcp_grant_takes_the_rule_away(self):
        # Иначе `--grant mcp` рапортует выдачу, которой правило не даст.
        with Sandbox() as sb:
            home = build_home(sb, set(ck.BASE_CAPS) | {"mcp"})
            self.assertNotIn("mcp__*", settings_of(home)["permissions"]["deny"])

    def test_no_server_name_is_written_by_hand(self):
        # Имена коннекторов приходят с аккаунта; вписанные руками, они
        # закрывают ровно эту машину и ровно сегодня.
        with Sandbox() as sb:
            home = build_home(sb, ck.BASE_CAPS)
            named = [r for r in settings_of(home)["permissions"]["deny"]
                     if r.startswith("mcp__") and r != "mcp__*"]
            self.assertEqual(named, [])


class TestProbeMcp(unittest.TestCase):
    def test_a_fenced_home_passes_and_names_the_live_server(self):
        with Sandbox() as sb:
            use_harness(sb)
            home = build_home(sb, ck.BASE_CAPS)
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual((state, "claude.ai Claude Docs" in note), ("ок", True), note)

    def test_the_probe_runs_without_strict_mcp_config(self):
        # С флагом харнесс не пустил бы ни одного сервера, и «инструментов
        # MCP нет» было бы правдой о флаге, а не о доме.
        with Sandbox() as sb:
            use_harness(sb)
            home = build_home(sb, ck.BASE_CAPS)
            ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            argv = sb.calls()[0]["argv"]
            self.assertEqual(("--strict-mcp-config" in argv,
                              argv[argv.index("--setting-sources") + 1]),
                             (False, "user,project,local"))

    def test_a_home_without_the_rule_is_a_breach(self):
        with Sandbox() as sb:
            use_harness(sb)
            home = build_home(sb, ck.BASE_CAPS)
            rewrite_settings(home, lambda d: d["permissions"]["deny"].remove("mcp__*"))
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual((state, "mcp__*" in note), ("ПРОБОЙ", True), note)

    def test_a_harness_that_ignores_the_rule_is_caught_by_what_search_found(self):
        # Правило на месте, а харнесс его не читает: init несёт инструменты
        # сервера на связи, поиск — ещё и сервера в pending.
        with Sandbox() as sb:
            use_harness(sb, ignore_mcp_deny=True)
            home = build_home(sb, ck.BASE_CAPS)
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual((state, "send_reply" in note or "(6)" in note),
                             ("ПРОБОЙ", True), note)

    def test_only_search_reveals_a_pending_server(self):
        # Сервер в pending: в init его инструментов нет НИКОГДА, правило или нет.
        # Поймать его может только второй свидетель — поиск.
        with Sandbox() as sb:
            use_harness(sb, ignore_mcp_deny=True,
                        mcp={"late": {"status": "pending", "tools": ["send_reply"]},
                             "early": {"status": "connected", "tools": []}})
            home = build_home(sb, ck.BASE_CAPS)
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual((state, "mcp__late__send_reply" in note), ("ПРОБОЙ", True), note)

    def test_no_server_on_line_is_not_measured_not_ok(self):
        with Sandbox() as sb:
            use_harness(sb, mcp={"slow": {"status": "pending", "tools": ["x"],
                                          "stuck": True}})
            home = build_home(sb, ck.BASE_CAPS)
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual(state, "не измерено", note)

    def test_a_server_that_came_on_line_during_the_session_counts(self):
        # Живой замер: ни один коннектор не был `connected` к init, CCPort
        # доподключился по ходу — стенограмма это пишет. Без этого свидетеля
        # исправный дом получал «не измерено».
        with Sandbox() as sb:
            use_harness(sb, mcp={"slow": {"status": "pending", "tools": ["send_reply"]}})
            home = build_home(sb, ck.BASE_CAPS)
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual((state, "slow" in note), ("ок", True), note)

    def test_no_servers_at_all_is_said_so(self):
        with Sandbox() as sb:
            use_harness(sb, mcp={})
            home = build_home(sb, ck.BASE_CAPS)
            state, note = ck.probe_mcp(home, sb.project, ck.BASE_CAPS)
            self.assertEqual(state, "нечего мерить", note)

    def test_the_containment_probe_includes_the_mcp_axis(self):
        # Проба ограды целиком: набор, запись, MCP, исполнение. Дом с оградой
        # проходит; тот же дом без `mcp__*` — ПРОБОЙ по оси MCP, хотя набор и
        # запись у него в порядке.
        with Sandbox() as sb:
            use_harness(sb, writes=True)
            home = build_home(sb, set(ck.BASE_CAPS) | {"write"})
            ok = ck.probe_containment(home, sb.project, CARD, set(ck.BASE_CAPS) | {"write"})
            rewrite_settings(home, lambda d: d["permissions"]["deny"].remove("mcp__*"))
            bad = ck.probe_containment(home, sb.project, CARD, set(ck.BASE_CAPS) | {"write"})
            self.assertEqual((ok[0], bad[0], "MCP" in bad[1]), ("ок", "ПРОБОЙ", True),
                             (ok, bad))

    def test_a_granted_mcp_is_not_probed(self):
        with Sandbox() as sb:
            use_harness(sb)
            home = build_home(sb, set(ck.BASE_CAPS) | {"mcp"})
            state, _ = ck.probe_mcp(home, sb.project, set(ck.BASE_CAPS) | {"mcp"})
            self.assertEqual((state, len(sb.calls())), ("выдано", 0))


# ── 2. Самоправка дома ─────────────────────────────────────────────────────

class TestTheHomeIsFencedFromItself(unittest.TestCase):
    def _full_home(self, sb):
        home = build_home(sb, set(ck.BASE_CAPS) | {"write"})
        for rel in ("reports.jsonl", "OWNER-RULES.json", "CLAUDE.md", "LEARNED.md",
                    "memory/MEMORY.md", ".claude/agent-memory/t/MEMORY.md",
                    "tools/helper.py"):
            p = os.path.join(home, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w").close()
        # Правила пересчитываются, как при `grant`: дом уже полон.
        ck.apply_grants(home, "t", sb.project, CARD, set(ck.BASE_CAPS) | {"write"},
                        extra_read=[])
        return home

    def test_every_file_in_the_home_is_either_the_assistants_or_denied(self):
        with Sandbox() as sb:
            home = self._full_home(sb)
            perms = settings_of(home)["permissions"]
            writable, open_, files = [], [], 0
            for root, _, names in os.walk(home):
                for n in names:
                    files += 1
                    p = os.path.join(root, n)
                    rel = os.path.relpath(p, home).replace(os.sep, "/")
                    denied = any(rule_covers(r, p) for r in perms["deny"])
                    allowed = any(rule_covers(r, p) for r in perms["allow"]
                                  if r.startswith("Edit("))
                    if allowed and not denied:
                        writable.append(rel)
                    elif not denied:
                        open_.append(rel)
            self.assertGreaterEqual(files, 10, "дом пуст — проверять нечего")
            self.assertEqual((sorted(writable), open_),
                             (sorted(["LEARNED.md", "memory/MEMORY.md",
                                      ".claude/agent-memory/t/MEMORY.md"]), []))

    def test_the_fence_files_are_denied_by_name(self):
        with Sandbox() as sb:
            home = self._full_home(sb)
            deny = settings_of(home)["permissions"]["deny"]
            must = [".claude/settings.json", ".claude/settings.local.json",
                    ".claude/hooks/x", ".claude/agents/t.md", "reports.jsonl",
                    "OWNER-RULES.json", "launch.json", ".mcp.json"]
            self.assertEqual([m for m in must
                              if not any(rule_covers(r, os.path.join(home, m)) for r in deny)],
                             [])

    def test_the_whole_home_is_no_longer_allowed(self):
        with Sandbox() as sb:
            home = build_home(sb, ck.BASE_CAPS)
            self.assertNotIn(ck.abs_rule("Edit", home + "/**"),
                             settings_of(home)["permissions"]["allow"])

    def test_files_that_do_not_exist_yet_are_denied_on_first_install(self):
        # При первой установке правила пишутся до settings.json и хуков.
        with Sandbox() as sb:
            home = os.path.join(sb.home, "fresh")
            os.makedirs(home)
            s = ck.compile_settings(CARD, sb.project, home, "t", ck.BASE_CAPS)
            for rel in (".claude/settings.json", ".claude/hooks/x", "reports.jsonl"):
                self.assertTrue(any(rule_covers(r, os.path.join(home, rel))
                                    for r in s["permissions"]["deny"]), rel)


# ── 3. Шелл только субагентам ─────────────────────────────────────────────

SUB = set(ck.BASE_CAPS) | {"write", "spawn", "shell-subagents"}


class TestShellForSubagentsOnly(unittest.TestCase):
    def test_the_layout_is_the_measured_one(self):
        # Шапка закрывает Bash основному потоку; в deny его нет (иначе он
        # закрыт и субагентам); в allow он есть (иначе в default — отказ).
        # Monitor остаётся запрещённым всем.
        with Sandbox() as sb:
            home = build_home(sb, SUB)
            p = settings_of(home)["permissions"]
            with open(os.path.join(home, "launch.json"), encoding="utf-8") as fh:
                flags = json.load(fh)["disallowed_tools"]
            self.assertEqual(("Bash" in p["deny"], "Bash" in p["allow"],
                              "Monitor" in p["deny"],
                              "disallowedTools: Bash" in card_text(home),
                              "Bash" in flags),
                             (False, True, True, True, False))

    def test_revoking_returns_the_card_to_its_bytes(self):
        with Sandbox() as sb:
            home = build_home(sb, set(ck.BASE_CAPS) | {"write", "spawn"})
            before = card_text(home)
            ck.apply_grants(home, "t", sb.project, CARD, SUB, extra_read=[])
            self.assertNotEqual(card_text(home), before, "выдача не дошла до шапки")
            ck.apply_grants(home, "t", sb.project, CARD,
                            set(ck.BASE_CAPS) | {"write", "spawn"}, extra_read=[])
            self.assertEqual(card_text(home), before)

    def test_full_shell_needs_no_card_line(self):
        with Sandbox() as sb:
            home = build_home(sb, SUB | {"shell"})
            self.assertNotIn("disallowedTools", card_text(home))

    def test_shell_for_subagents_is_dangerous_and_named(self):
        self.assertIn("shell-subagents", ck.DANGEROUS)
        text = ck.DANGER_EXPLAINED["shell-subagents"]
        self.assertTrue("ограду путей" in text and "Write|Edit" in text, text)

    def test_without_spawn_it_is_refused_at_install(self):
        with Sandbox() as sb:
            lib = os.path.join(sb.home, ".cckit", "library")
            os.makedirs(lib)
            shutil.copytree(os.path.join(PLUGIN, "assistants", "design-scout"),
                            os.path.join(lib, "design-scout"))
            rc, out = call(["install", "design-scout", "--project", sb.project,
                            "--grant", "shell-subagents", "--i-mean-it"])
            self.assertEqual((rc, "без «spawn»" in out), (2, True), out)


class TestProbeSubagentShell(unittest.TestCase):
    def test_the_granted_layout_passes(self):
        with Sandbox() as sb:
            use_harness(sb, spawn_bash=True, search=False)
            home = build_home(sb, SUB)
            state, note = ck.probe_subagent_shell(home, sb.project)
            self.assertEqual(state, "ок", note)
            self.assertEqual(os.listdir(os.path.join(home, "memory")), [],
                             "проба не убрала за собой")

    def test_a_card_without_the_line_gives_the_main_thread_a_shell(self):
        with Sandbox() as sb:
            use_harness(sb, spawn_bash=True, search=False)
            home = build_home(sb, SUB)
            p = os.path.join(home, ".claude", "agents", "t.md")
            with open(p, encoding="utf-8") as fh:
                t = fh.read()
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(t.replace("disallowedTools: Bash\n", ""))
            state, note = ck.probe_subagent_shell(home, sb.project)
            self.assertEqual(state, "ПРОБОЙ", note)

    def test_bash_denied_to_the_session_is_not_a_grant(self):
        # Раскладка до слова владельца: Bash в deny — у субагента его нет.
        with Sandbox() as sb:
            use_harness(sb, spawn_bash=True, search=False)
            home = build_home(sb, SUB)
            rewrite_settings(home, lambda d: d["permissions"]["deny"].append("Bash"))
            state, note = ck.probe_subagent_shell(home, sb.project)
            self.assertEqual(state, "не подтвердилась", note)

    def test_a_file_laid_without_bash_proves_nothing(self):
        # Субагент положил файл инструментом Write: файл есть, шелла у него
        # не было. Без стенограммы субагента это читалось бы как выдача.
        with Sandbox() as sb:
            use_harness(sb, spawn_bash=True, search=False, sub_uses_write=True)
            home = build_home(sb, SUB)
            state, note = ck.probe_subagent_shell(home, sb.project)
            self.assertEqual(state, "не измерено", note)

    def test_the_main_tool_probe_counts_bash_as_forbidden(self):
        # Проба набора смотрит на основной поток: Bash в его init — пробой.
        self.assertIn("Bash", set(ck.caps_to_disallowed(SUB)) | set(ck.main_thread_off(SUB)))
        self.assertNotIn("Bash", ck.caps_to_disallowed(SUB))


# ── 4. Уборка дома ─────────────────────────────────────────────────────────

def seed_and_install(sb):
    lib = os.path.join(sb.home, ".cckit", "library")
    os.makedirs(lib, exist_ok=True)
    shutil.copytree(os.path.join(PLUGIN, "assistants", "design-scout"),
                    os.path.join(lib, "design-scout"))
    sb.set_reply("готово", transcript_prompt="неважно")
    call(["install", "design-scout", "--project", sb.project])
    home = ck.instance_home("design-scout", sb.project)
    with open(os.path.join(home, "LEARNED.md"), "a", encoding="utf-8") as fh:
        fh.write("\nзаработанное\n")
    return home, os.path.basename(home)


def listing(root):
    out = {}
    for r, _, names in os.walk(root):
        for n in names:
            p = os.path.join(r, n)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


def register_session(sb, pid, cwd):
    d = core.sessions_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "%d.json" % pid), "w", encoding="utf-8") as fh:
        json.dump({"pid": pid, "cwd": cwd, "sessionId": "live-1", "status": "busy"}, fh)


class TestRetire(unittest.TestCase):
    def test_the_home_moves_to_the_attic_whole_and_is_never_deleted(self):
        with Sandbox() as sb:
            home, name = seed_and_install(sb)
            before = listing(home)
            rc, out = call(["retire", name])
            attic = os.path.join(ck.assistants_dir(), ".attic", name)
            stamps = os.listdir(attic) if os.path.isdir(attic) else []
            self.assertEqual((rc, os.path.exists(home), len(stamps)), (0, False, 1), out)
            self.assertEqual(listing(os.path.join(attic, stamps[0])), before)
            self.assertIn("вернуть: mv", out)

    def test_a_retired_home_is_no_longer_an_instance(self):
        with Sandbox() as sb:
            home, name = seed_and_install(sb)
            self.assertIsNotNone(ck.find_instance(name, required=False))
            call(["retire", name])
            self.assertEqual((ck.find_instance(name, required=False), ck.instances()),
                             (None, []))

    def test_a_home_with_a_live_session_is_left_alone(self):
        with Sandbox() as sb:
            home, name = seed_and_install(sb)
            register_session(sb, os.getpid(), home)
            rc, out = call(["retire", name])
            self.assertEqual((rc, os.path.isdir(home), "live-1" in out), (3, True, True), out)

    def test_i_mean_it_moves_a_home_with_a_live_session(self):
        with Sandbox() as sb:
            home, name = seed_and_install(sb)
            register_session(sb, os.getpid(), home)
            rc, out = call(["retire", name, "--i-mean-it"])
            self.assertEqual((rc, os.path.exists(home)), (0, False), out)

    @unittest.skipIf(os.name == "nt", "на windows сессия считается живой всегда")
    def test_a_dead_session_record_does_not_block(self):
        # Файл реестра переживает упавший процесс.
        with Sandbox() as sb:
            home, name = seed_and_install(sb)
            p = subprocess.Popen([sys.executable, "-c", "pass"])
            p.wait()
            register_session(sb, p.pid, home)
            rc, out = call(["retire", name])
            self.assertEqual((rc, os.path.exists(home)), (0, False), out)

    def test_a_session_elsewhere_does_not_block(self):
        with Sandbox() as sb:
            home, name = seed_and_install(sb)
            register_session(sb, os.getpid(), sb.project)
            rc, out = call(["retire", name])
            self.assertEqual((rc, os.path.exists(home)), (0, False), out)

    def test_an_unknown_instance_is_refused(self):
        with Sandbox() as sb:
            rc, out = call(["retire", "nobody@nothing"])
            self.assertEqual(rc, 1, out)

    def test_the_attic_itself_cannot_be_retired(self):
        with Sandbox() as sb:
            seed_and_install(sb)
            os.makedirs(os.path.join(ck.assistants_dir(), ".attic"), exist_ok=True)
            rc, out = call(["retire", ".attic"])
            self.assertEqual((rc, os.path.isdir(os.path.join(ck.assistants_dir(), ".attic"))),
                             (1, True), out)


# ── Помощники ядра ─────────────────────────────────────────────────────────

class TestCoreHelpers(unittest.TestCase):
    def test_people_argv_keeps_strict_mcp_unless_asked(self):
        self.assertEqual(("--strict-mcp-config" in core.people_argv("x", "1"),
                          "--strict-mcp-config" in core.people_argv("x", "1", strict_mcp=False)),
                         (True, False))

    def test_servers_come_from_init_and_names_from_search(self):
        ev = [{"type": "system", "subtype": "init", "tools": [],
               "mcp_servers": [{"name": "a", "status": "pending"}]},
              {"type": "user", "message": {"content": [{"type": "tool_result", "content": [
                  {"type": "tool_reference", "tool_name": "mcp__a__x"}]}]}}]
        self.assertEqual((core.mcp_servers(ev), core.found_tool_names(ev),
                          core.mcp_servers([])),
                         ([("a", "pending")], ["mcp__a__x"], None))


if __name__ == "__main__":
    unittest.main()

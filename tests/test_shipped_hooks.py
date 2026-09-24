"""Поставляемые роли включают свои хуки — и хуки доезжают до дома и срабатывают.

1.2 привезла механизм: три реализации, установщик, пробу. И ни одна
поставляемая карточка не объявляла `hooks:` — у чужого человека после
установки дом по-прежнему не действовал сам. Механизм без включения — ноль,
и ни один тест этого не замечал: все они собирали дом из карточки, сочинённой
прямо в тесте.

Здесь карточки берутся ТЕ, что едут в поставке (`assistants/*/card.yaml`), дом
собирается настоящим установщиком, а зарегистрированные команды исполняются
так, как их исполнит CLI: строкой из settings.json, через оболочку, с телом
события на входе. Спрашивается последствие, а не запись в yaml.

Тут же — два соседних стража той же болезни («не смог» неотличим от «нечего
сказать»): хук session-start и ворота синтаксиса хуков в dev.sh.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402
from test_probe_hooks import install_hook_aware_claude, scenario  # noqa: E402

PLUGIN = os.path.realpath(os.path.join(HERE, ".."))
ROLES = sorted(d for d in os.listdir(os.path.join(PLUGIN, "assistants"))
               if os.path.isfile(os.path.join(PLUGIN, "assistants", d, "card.yaml")))


def shipped_card(role):
    return ck.load_card(os.path.join(PLUGIN, "assistants", role, "card.yaml"))


def run_registered(home, event, payload):
    """Исполнить КАЖДУЮ команду, зарегистрированную под событием, как это
    делает CLI: строка из settings.json, оболочка, JSON на входе, cwd — дом."""
    with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
        hooks = json.load(fh).get("hooks") or {}
    out = []
    for group in hooks.get(event) or []:
        for h in group.get("hooks") or []:
            p = subprocess.run(h["command"], shell=True, cwd=home,
                               input=json.dumps(payload, ensure_ascii=False),
                               capture_output=True, text=True, timeout=60)
            out.append((p.returncode, p.stdout, p.stderr))
    return out


class TestShippedCardsSwitchHooksOn(unittest.TestCase):

    def test_the_catalogue_is_the_four_roles_this_file_reasons_about(self):
        # Пустой каталог обнулил бы все проверки ниже, и они остались бы
        # зелёными: перебор по нулю ролей не падает.
        self.assertEqual(ROLES, ["cckit-smith", "design-hand", "design-scout",
                                 "under-the-hood"])

    def test_each_role_declares_the_hooks_it_needs_and_no_more(self):
        # Решение по ролям, одним снимком. Почему так:
        #  * report-done и lint-learned — всем: каждый дом ведёт LEARNED.md
        #    (так велит его CLAUDE.md), и каждый доклад об окончании хода —
        #    одна строка на диске, ни одного токена;
        #  * read-ledger — только тем, у кого есть ведомость, которую бриф и
        #    так велит прочесть первой. Он везёт файл в контекст КАЖДОЙ
        #    сессии: без ведомости это шум, с чужой — деньги;
        #  * design-hand ведомости нет: он рисует дизайн, а STATE.md — про
        #    свежесть разведки по этому дизайну, не его забота.
        got = {r: (shipped_card(r).get("hooks"), shipped_card(r).get("ledger"))
               for r in ROLES}
        self.assertEqual(got, {
            "cckit-smith": (["report-done", "lint-learned", "read-ledger"],
                            ["LEARNED.md", "docs/findings/STATE.md"]),
            "design-hand": (["report-done", "lint-learned"], None),
            "design-scout": (["report-done", "lint-learned", "read-ledger"],
                             "docs/vscode-internals/STATE.md"),
            "under-the-hood": (["report-done", "lint-learned", "read-ledger"],
                               "docs/vscode-internals/STATE.md"),
        }, "поставляемые карточки не включают хуки так, как решено")

    def test_model_effort_and_budget_are_untouched(self):
        # Включение хуков не повод двигать деньги: снимок того, что было.
        got = {r: tuple(shipped_card(r).get(k) for k in ("model", "effort", "budget_usd"))
               for r in ROLES}
        self.assertEqual(got, {
            "cckit-smith": ("claude-fable-5-1[1m]", "xhigh", "3.00"),
            "design-hand": ("claude-opus-5[1m]", "xhigh", "4.00"),
            # 1.3, намеренно: окно 1M и порог сжатия 900k — старую руку тормозили
            # два автосжатия посреди задачи на окне 200k (LEARNED.md, поправка).
            "design-scout": ("claude-opus-5-5[1m]", "xhigh", "3.00"),
            "under-the-hood": ("claude-opus-5-5[1m]", "xhigh", "4.00"),
        })


class TestShippedHooksReachTheHomeAndFire(unittest.TestCase):
    """Карточка → установщик → дом → команда из settings.json → последствие."""

    def _home(self, sb, role):
        card = shipped_card(role)
        project = sb.project
        # Ведомости кладутся в проект с меткой, которую больше взять неоткуда:
        # если она всплыла в контексте, её привёз хук, прочитав файл.
        marks = {}
        ledgers = card.get("ledger") or []
        for rel in ([ledgers] if isinstance(ledgers, str) else ledgers):
            p = os.path.join(project, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            marks[rel] = "LEDGER-%s-%s" % (role, rel.replace("/", "_"))
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("# ведомость\n\n## раздел — АКТУАЛЕН\n%s\n" % marks[rel])
        home = os.path.join(sb.home, ".cckit", "assistants",
                            role + "@" + os.path.basename(project))
        os.makedirs(home, exist_ok=True)
        granted = set(ck.BASE_CAPS) | ({"write"} if card.get("writes") else set())
        ck.apply_grants(home, role, project, card, granted, extra_read=[])
        with open(os.path.join(home, "LEARNED.md"), "w", encoding="utf-8") as fh:
            fh.write("# Что я узнал\n")
        return home, card, project, marks

    def test_the_install_time_probe_passes_for_every_shipped_role(self):
        # Проба та же, что зовёт install; CLI поддельный, но хуки он ПРАВДА
        # исполняет — из settings.json, который написал установщик.
        got = {}
        for role in ROLES:
            with Sandbox() as sb:
                install_hook_aware_claude(sb)
                scenario(sb)
                home, card, project, _ = self._home(sb, role)
                state, note = ck.probe_hooks(home, project, card)
                got[role] = (state, len(sb.calls()), note if state != "ок" else "")
        self.assertEqual(got, {r: ("ок", 1, "") for r in ROLES})

    def test_each_declared_hook_fires_from_its_registration_with_its_effect(self):
        got = {}
        for role in ROLES:
            with Sandbox() as sb:
                home, card, project, marks = self._home(sb, role)
                effects = {}

                ss = run_registered(home, "SessionStart",
                                    {"hook_event_name": "SessionStart", "cwd": home})
                ctx = ""
                for rc, so, _ in ss:
                    if rc == 0 and so.strip():
                        ctx += (json.loads(so).get("hookSpecificOutput") or {}) \
                            .get("additionalContext") or ""
                # Каждая ведомость карточки — своими байтами в контексте.
                effects["ledger"] = sorted(rel for rel, m in marks.items() if m in ctx)

                reports = os.path.join(home, "reports.jsonl")
                run_registered(home, "Stop", {"hook_event_name": "Stop", "cwd": home,
                                              "session_id": "s-" + role})
                with open(reports, encoding="utf-8") if os.path.exists(reports) \
                        else open(os.devnull) as fh:
                    lines = [json.loads(x) for x in fh if x.strip()]
                effects["report"] = [(x["role"], x["session"]) for x in lines]

                learned = os.path.join(home, "LEARNED.md")
                with open(learned, "a", encoding="utf-8") as fh:
                    fh.write("\n## запись без статуса\n")
                post = run_registered(home, "PostToolUse", {
                    "hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": home,
                    "tool_input": {"file_path": learned}})
                effects["lint"] = [json.loads(so).get("decision")
                                   for rc, so, _ in post if so.strip()]
                got[role] = effects

        def expect(role, ledgers):
            return {"ledger": sorted(ledgers), "report": [(role, "s-" + role)],
                    "lint": ["block"]}
        self.assertEqual(got, {
            "cckit-smith": expect("cckit-smith", ["LEARNED.md", "docs/findings/STATE.md"]),
            "design-hand": expect("design-hand", []),
            "design-scout": expect("design-scout", ["docs/vscode-internals/STATE.md"]),
            "under-the-hood": expect("under-the-hood", ["docs/vscode-internals/STATE.md"]),
        })


def _run_session_start(skill_text):
    """session-start в раскладке плагина, где SKILL.md такой, как велено:
    None — файла нет вовсе."""
    root = tempfile.mkdtemp(prefix="cckit-ss-")
    try:
        os.makedirs(os.path.join(root, "hooks"))
        shutil.copy(os.path.join(PLUGIN, "hooks", "session-start"),
                    os.path.join(root, "hooks", "session-start"))
        if skill_text is not None:
            d = os.path.join(root, "skills", "using-assistants")
            os.makedirs(d)
            with open(os.path.join(d, "SKILL.md"), "w", encoding="utf-8") as fh:
                fh.write(skill_text)
        p = subprocess.run(["bash", os.path.join(root, "hooks", "session-start")],
                           capture_output=True, text=True, timeout=30)
        return p.returncode, json.loads(p.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)


class TestSessionStartTellsCouldNotFromNothingToSay(unittest.TestCase):

    def test_a_missing_skill_is_said_out_loud_and_nothing_is_delivered(self):
        rc, d = _run_session_start(None)
        self.assertEqual((rc, "additional_context" in d, "SKILL.md" in d.get("systemMessage", "")),
                         (0, False, True),
                         "пропавший SKILL.md снова выглядит успехом: %r" % d)

    def test_an_empty_skill_is_a_failure_too(self):
        rc, d = _run_session_start(" \n\n")
        self.assertEqual((rc, "additional_context" in d, "пуст" in d.get("systemMessage", "")),
                         (0, False, True),
                         "пустой SKILL.md доставлен как диспетчер: %r" % d)

    def test_a_present_skill_is_delivered_whole_and_quietly(self):
        rc, d = _run_session_start('name: x\n"кавычки"\tтаб\\обратная\n')
        self.assertEqual((rc, "systemMessage" in d, d.get("additional_context")),
                         (0, False, 'You have CCKit Assistants.\n\nname: x\n"кавычки"\tтаб\\обратная'))


def _gate(extra):
    """`dev.sh hooks` на копии плагина, куда подложены файлы `extra`."""
    root = tempfile.mkdtemp(prefix="cckit-gate-")
    try:
        shutil.copy(os.path.join(PLUGIN, "dev.sh"), os.path.join(root, "dev.sh"))
        shutil.copytree(os.path.join(PLUGIN, "hooks"), os.path.join(root, "hooks"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for rel, body in extra.items():
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write(body)
        p = subprocess.run(["bash", os.path.join(root, "dev.sh"), "hooks"],
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout + p.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


class TestHookGateFindsNewHooksByItself(unittest.TestCase):

    def test_every_shipped_hook_file_is_checked_and_passes(self):
        rc, out = _gate({})
        shipped = sorted(os.path.relpath(os.path.join(dp, f), PLUGIN)
                         for dp, _, fs in os.walk(os.path.join(PLUGIN, "hooks"))
                         if "__pycache__" not in dp for f in fs if not f.endswith(".pyc"))
        unnamed = [f for f in shipped if "ok   " + f not in out]
        self.assertEqual((rc, unnamed), (0, []), out)

    def test_a_new_hook_with_broken_syntax_turns_the_gate_red_without_a_list_edit(self):
        rc, out = _gate({"hooks/assistant/brand-new":
                         "#!/usr/bin/env bash\nif then\n  echo\n"})
        self.assertEqual((rc != 0, "БЕДА hooks/assistant/brand-new" in out), (True, True),
                         "сломанный новый хук прошёл ворота:\n" + out)

    def test_a_hook_in_a_language_the_gate_cannot_check_is_not_waved_through(self):
        rc, out = _gate({"hooks/assistant/new.rb": "puts 1\n"})
        self.assertEqual((rc != 0, "БЕДА hooks/assistant/new.rb" in out), (True, True),
                         "непроверяемый хук прошёл ворота молча:\n" + out)


if __name__ == "__main__":
    unittest.main()

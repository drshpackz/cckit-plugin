"""Проба хуков: краснеет ли она, когда хук не сработал.

Правило проекта: **хук, который не сработал, неотличим от отсутствующего.**
Значит проба обязана отвечать не «файл на месте» и не «запись в settings.json
есть», а «хук действительно сработал» — и обязана КРАСНЕТЬ во всех случаях,
когда это не так.

Дом здесь собирается НАСТОЯЩИМ установщиком (`apply_grants` → `install_hooks`),
и хуки в нём — те самые, что везёт плагин. Поломки вносятся поверх, по одной.

Поддельный `claude` здесь не такой, как в песочнице: тот хуков не выполняет
вовсе. Этот читает `<дом>/.claude/settings.json` и ПРАВДА запускает
зарегистрированные команды — то есть изображает не модель, а ту часть CLI,
которую проба и проверяет. Сценарий говорит, чем именно он ломается: не
выполняет хуки, не доставляет контекст, выдумывает нонс, не пишет ничего.

Расхождение с заданием (побеждает код): «PostToolUse блокирует — посмотри,
легла ли запись на диск» не годится. `lint-learned` зовут ПОСЛЕ применения
правки, отменить её он не может и не пытается: он возвращает
`{"decision": "block"}`. Запись ложится на диск ВСЕГДА, и проба, смотрящая
туда, объявляла бы провал при исправном хуке. Поэтому блокировка читается из
его собственного вывода, а пара записей (со статусом и без) отличает сторожа
от того, кто блокирует всё подряд.

Каждый тест утверждает число вызовов `claude`: проба, не запускавшая ничего,
зелёная по той же причине, по которой зелёным бывает пустой набор.
"""

import json
import os
import shutil
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402

ROLE = "hooked"
ALL_THREE = ("read-ledger", "report-done", "lint-learned")

# Реализации зовутся через полиглот run-hook.cmd, а тот запускает их BASH —
# питоновская заглушка здесь упала бы синтаксисом, и «сломан» получилось бы по
# не той причине, по какой его проверяют.
CRASHES = '''#!/usr/bin/env bash
cat >/dev/null
echo "ведомость не читается" >&2
exit 1
'''

DOES_NOTHING = '''#!/usr/bin/env bash
cat >/dev/null
exit 0
'''

LINT_NEVER_COMPLAINS = '''def lint(text):
    return []
'''

LINT_ALWAYS_COMPLAINS = '''def lint(text):
    return ["всё плохо"]
'''

# ── Поддельный CLI, который правда выполняет хуки ──────────────────────────
HOOK_AWARE_CLAUDE = r'''#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

state = os.environ["CCKIT_FAKE_STATE"]
argv = sys.argv[1:]
with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": argv, "cwd": os.getcwd()}, ensure_ascii=False) + "\n")

sc = {"run_hooks": True, "deliver_context": True,
      "writes": ["good", "bad"], "fake_nonce": None}
sp = os.path.join(state, "hooks_scenario.json")
if os.path.exists(sp):
    with open(sp, encoding="utf-8") as fh:
        sc.update(json.load(fh))

prompt = ""
for i, a in enumerate(argv):
    if a == "-p" and i + 1 < len(argv):
        prompt = argv[i + 1]

home = os.getcwd()
try:
    with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    hooks = cfg.get("hooks") or {}
except Exception:
    cfg, hooks = {}, {}
# Снимок того, что CLI ПРАВДА прочёл в момент прогона: после пробы
# settings.json возвращается на место, и подсмотреть команду уже негде.
with open(os.path.join(state, "seen_settings.json"), "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, ensure_ascii=False)


def fire(event, payload):
    out = []
    if not sc["run_hooks"]:
        return out
    for group in hooks.get(event) or []:
        for h in group.get("hooks") or []:
            p = subprocess.run(h.get("command", ""), shell=True, cwd=home,
                               input=json.dumps(payload, ensure_ascii=False),
                               capture_output=True, text=True)
            out.append((p.returncode, p.stdout))
    return out


context = ""
for rc, so in fire("SessionStart", {"hook_event_name": "SessionStart", "cwd": home}):
    if rc != 0:
        continue
    try:
        d = json.loads(so or "{}")
        context += (d.get("hookSpecificOutput") or {}).get("additionalContext") or ""
    except Exception:
        pass
if not sc["deliver_context"]:
    context = ""

# «Модель» берёт нонс ТОЛЬКО из доставленного контекста: взять его с диска
# неоткуда — проба нигде его не пишет.
m = re.search(r"CCKIT-HOOK-[0-9A-F]+", context)
said = sc["fake_nonce"] or (m.group(0) if m else "НЕТ")

mk = re.search(r"HOOKPROBE-[0-9A-Z]+", prompt)
if mk and "LEARNED.md" in prompt:
    learned = os.path.join(home, "LEARNED.md")
    for kind in sc["writes"]:
        if kind == "good":
            chunk = "\n## %s со статусом\n**Статус: наблюдение** (2026-09-24, проба).\n" % mk.group(0)
        else:
            chunk = "\n## %s без статуса\n" % mk.group(0)
        # Правка применяется ДО хука: PostToolUse зовут после инструмента.
        with open(learned, "a", encoding="utf-8") as fh:
            fh.write(chunk)
        fire("PostToolUse",
             {"hook_event_name": "PostToolUse", "tool_name": "Edit", "cwd": home,
              "tool_input": {"file_path": learned, "new_string": chunk}})

fire("Stop", {"hook_event_name": "Stop", "cwd": home, "session_id": "s1"})
sys.stdout.write(json.dumps({"result": said, "session_id": "s1",
                             "total_cost_usd": 0.0}, ensure_ascii=False))
'''


def _exec(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_hook_aware_claude(sb):
    """Подменяет поддельный `claude` песочницы на тот, что выполняет хуки.

    Пишется в `sb.bin` — то есть внутрь этой же песочницы; наружу ничего не
    выходит, а песочница снимает свой каталог с PATH на выходе.
    """
    _exec(os.path.join(sb.bin, "claude"), HOOK_AWARE_CLAUDE)


def scenario(sb, **kw):
    with open(os.path.join(sb.state, "hooks_scenario.json"), "w", encoding="utf-8") as fh:
        json.dump(kw, fh, ensure_ascii=False)


def make_home(sb, declared=ALL_THREE):
    """Дом настоящим установщиком: реализации из плагина, регистрация из
    `compile_hooks`. Подделывать тут нечего — проба смотрит на то же, что
    получит живой ассистент."""
    project = sb.project
    home = os.path.join(sb.home, ".cckit", "assistants",
                        ROLE + "@" + os.path.basename(project))
    os.makedirs(home, exist_ok=True)
    card = {"name": ROLE, "summary": "проба", "access": "read-only",
            "budget_usd": "0.10"}
    if declared:
        card["hooks"] = list(declared)
    ck.apply_grants(home, ROLE, project, card, set(ck.BASE_CAPS), extra_read=[])
    with open(os.path.join(home, "LEARNED.md"), "w", encoding="utf-8") as fh:
        fh.write("# Что я узнал\n")
    return home, card, project


def break_hook(home, name, body=CRASHES):
    _exec(os.path.join(ck.hooks_dir(home), name), body)


def swap_linter(home, body):
    with open(os.path.join(ck.hooks_dir(home), "cckit_learned.py"), "w",
              encoding="utf-8") as fh:
        fh.write(body)


def strip_registration(home):
    p = os.path.join(home, ".claude", "settings.json")
    with open(p, encoding="utf-8") as fh:
        s = json.load(fh)
    s.pop("hooks", None)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent="\t", ensure_ascii=False)


class TestProbeHooks(unittest.TestCase):

    def test_three_working_hooks_pass_on_one_run(self):
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("ок", 1), note)

    def test_a_registered_hook_that_crashes_is_not_counted_as_working(self):
        # То самое: дом с ЗАРЕГИСТРИРОВАННЫМ, но неработающим хуком. Слот
        # срабатывает, улика на диске появляется — и проба обязана краснеть.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)
            break_hook(home, "read-ledger")
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, "read-ledger: СЛОМАН" in note, len(sb.calls())),
                             ("СЛОМАН", True, 1), note)

    def test_a_cli_that_never_runs_the_registered_command_is_caught(self):
        # Регистрация — не срабатывание. Настройки безупречны, реализации на
        # месте, хуки не выполняются ни разу.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb, run_hooks=False)
            home, card, project = make_home(sb)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ СРАБОТАЛ", 1), note)

    def test_the_stock_fake_claude_which_knows_nothing_of_hooks_is_caught(self):
        # Без подмены CLI: штатный поддельный `claude` песочницы хуков не знает
        # вовсе. Это и есть «хук неотличим от отсутствующего», увиденное пробой.
        with Sandbox() as sb:
            sb.set_reply("готов")
            home, card, project = make_home(sb)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ СРАБОТАЛ", 1), note)

    def test_a_session_start_that_fires_but_delivers_no_context_is_caught(self):
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb, deliver_context=False)
            home, card, project = make_home(sb, ("read-ledger",))
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ ДОШЁЛ", 1), note)

    def test_an_invented_nonce_does_not_pass_for_a_delivered_one(self):
        # Показание подделывается, уникальная строка из источника — нет.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb, deliver_context=False, fake_nonce="CCKIT-HOOK-DEADBEEF0000")
            home, card, project = make_home(sb, ("read-ledger",))
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ ДОШЁЛ", 1), note)

    def test_a_stop_hook_that_writes_no_line_is_caught(self):
        # rc=0 ничего не доказывает: cckit_hook.py ловит свои исключения и
        # выходит нулём нарочно. Спрашивается последствие.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb, ("report-done",))
            break_hook(home, "report-done", DOES_NOTHING)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ ДОШЁЛ", 1), note)

    def test_a_linter_that_lets_the_statusless_entry_through_is_caught(self):
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb, ("lint-learned",))
            swap_linter(home, LINT_NEVER_COMPLAINS)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ РАЗЛИЧИЛ", 1), note)

    def test_a_linter_that_blocks_the_correct_entry_too_is_caught(self):
        # Ложный красный — не успех: первый же он учит владельца не смотреть.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb, ("lint-learned",))
            swap_linter(home, LINT_ALWAYS_COMPLAINS)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ РАЗЛИЧИЛ", 1), note)

    def test_a_model_that_wrote_nothing_is_not_read_as_blocked(self):
        # Ничего не тронуто — значит наблюдать блокировку не на чем. Без этого
        # проба зеленела бы от бездействия модели.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb, writes=[])
            home, card, project = make_home(sb, ("lint-learned",))
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ ДОКАЗАН", 1), note)

    def test_the_probe_does_not_launch_under_a_cap_that_kills_the_turn(self):
        """Потолок пробы закреплён числом, и это не придирка к константе.

        Измерено живым прогоном 2026-09-24: при `--max-budget-usd 0.10` ход
        обрывается, `result` приходит ПУСТЫМ при стоимости 0.13, и Stop-хук не
        успевает сработать. Проба прочла бы это как «контекст не дошёл» и «хук
        не сработал» — ложный красный на исправных хуках. Тот же прогон при
        0.40 завершился за 0.042 и вернул нонс. Кто соберётся снижать потолок,
        уронит этот тест и прочтёт, почему.
        """
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)
            ck.probe_hooks(home, project, card)
            argv = sb.calls()[0]["argv"]
            cap = float(argv[argv.index("--max-budget-usd") + 1])
            self.assertEqual((cap >= 0.30, len(sb.calls())), (True, 1), argv)

    def test_declared_but_never_registered_is_red_and_spends_nothing(self):
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)
            strip_registration(home)
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ ЗАРЕГИСТРИРОВАН", 0), note)

    def test_registered_without_an_implementation_is_red(self):
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)
            os.remove(os.path.join(ck.hooks_dir(home), "read-ledger"))
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("НЕ ЗАРЕГИСТРИРОВАН", 0), note)

    def test_the_evidence_lies_where_the_assistant_cannot_write_it(self):
        """Улика внутри дома — улика, которую ассистент может написать сам.

        Дом разрешён ему на запись целиком (`Edit(//дом/**)`), и это уже
        однажды дало ложный ПРОБОЙ: проба ограды просила создать файл там, где
        запись разрешена, и мерила сговорчивость модели вместо ограды.
        Поэтому обёртка и её показания живут вне дома И вне проекта.
        """
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)
            ck.probe_hooks(home, project, card)
            with open(os.path.join(sb.state, "seen_settings.json"), encoding="utf-8") as fh:
                seen = json.load(fh)
            cmds = [h.get("command", "")
                    for groups in (seen.get("hooks") or {}).values()
                    for g in groups for h in (g.get("hooks") or [])]
            inside = [c for c in cmds if home in c or project in c]
            self.assertEqual((len(cmds), inside, len(sb.calls())), (3, [], 1), cmds)

    def test_nothing_declared_is_not_a_pass(self):
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            home, card, project = make_home(sb, ())
            state, note = ck.probe_hooks(home, project, card)
            self.assertEqual((state, len(sb.calls())), ("не объявлены", 0), note)

    def test_the_probe_leaves_settings_learned_and_the_project_as_it_found_them(self):
        # Проба не имеет права менять то, что проверяет: обёрнутый settings.json
        # или дописанный LEARNED.md пережили бы её и достались ассистенту.
        with Sandbox() as sb:
            install_hook_aware_claude(sb)
            scenario(sb)
            home, card, project = make_home(sb)

            def snapshot(root):
                out = {}
                for d, _, files in os.walk(root):
                    for f in files:
                        p = os.path.join(d, f)
                        with open(p, "rb") as fh:
                            out[os.path.relpath(p, root)] = fh.read()
                return out

            settings = os.path.join(home, ".claude", "settings.json")
            learned = os.path.join(home, "LEARNED.md")
            before = (open(settings, "rb").read(), open(learned, "rb").read(),
                      snapshot(project))
            state, note = ck.probe_hooks(home, project, card)
            after = (open(settings, "rb").read(), open(learned, "rb").read(),
                     snapshot(project))
            # reports.jsonl — работа самого хука, а не след пробы, и его
            # отсутствие в сравнении намеренное.
            self.assertEqual((state, after == before), ("ок", True), note)


class TestInstallCountsTheHookProbe(unittest.TestCase):
    """Место вызова: объявленные хуки, которые не сработали, не имеют права
    оставить установку «проверенной»."""

    def _seed(self, sb, hooks="[read-ledger]"):
        lib = os.path.join(sb.home, ".cckit", "library", ROLE)
        os.makedirs(lib)
        with open(os.path.join(lib, "card.yaml"), "w", encoding="utf-8") as fh:
            fh.write("name: %s\nsummary: проба\naccess: read-only\n"
                     "budget_usd: 0.10\nhooks: %s\n" % (ROLE, hooks))
        with open(os.path.join(lib, "ROLE.md"), "w", encoding="utf-8") as fh:
            fh.write("Ты обслуживаешь {PROJECT}.")

    def test_install_does_not_report_verified_when_the_hook_never_fired(self):
        with Sandbox() as sb:
            self._seed(sb)
            sb.set_reply("готово", transcript_prompt="Ты обслуживаешь %s." % sb.project)
            rc = ck.cmd_install([ROLE, "--project", sb.project])
            home = ck.instance_home(ROLE, sb.project)
            with open(os.path.join(home, "instance.json"), encoding="utf-8") as fh:
                it = json.load(fh)
            self.assertEqual((rc, it["verified"]["hooks"]), (1, "НЕ СРАБОТАЛ"))

    def test_a_card_without_hooks_is_recorded_as_nothing_declared(self):
        # «не объявлены» — не провал: карточка ничего не обещала. Иначе проба
        # роняла бы каждую установку без хуков.
        with Sandbox() as sb:
            lib = os.path.join(sb.home, ".cckit", "library", ROLE)
            os.makedirs(lib)
            with open(os.path.join(lib, "card.yaml"), "w", encoding="utf-8") as fh:
                fh.write("name: %s\nsummary: проба\naccess: read-only\n" % ROLE)
            with open(os.path.join(lib, "ROLE.md"), "w", encoding="utf-8") as fh:
                fh.write("Ты обслуживаешь {PROJECT}.")
            sb.set_reply("готово", transcript_prompt="Ты обслуживаешь %s." % sb.project)
            ck.cmd_install([ROLE, "--project", sb.project])
            home = ck.instance_home(ROLE, sb.project)
            with open(os.path.join(home, "instance.json"), encoding="utf-8") as fh:
                it = json.load(fh)
            # Два вызова — это проба ограды (её вторая половина не зовётся:
            # поддельный `claude` не пишет, и первая не подтвердилась) и проба
            # мозга. Проба хуков не добавила НИ ОДНОГО: объявлено ничего.
            self.assertEqual((it["verified"]["hooks"], len(sb.calls())),
                             ("не объявлены", 2))


if __name__ == "__main__":
    unittest.main()

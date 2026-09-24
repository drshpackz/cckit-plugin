"""Хуки дома: объявление в карточке → файлы в доме → запись в правах → работа.

Проверяется именно та цепочка, а не её звенья по отдельности. Звенья по
отдельности зелены у любого хука, который не сработал: файл на месте, запись
на месте, событие не наступило — и снаружи это неотличимо от хука, которого
нет вовсе. Поэтому каждый хук здесь ЗАПУСКАЕТСЯ, и запускается не напрямую, а
ровно той командой, которую установщик записал в `settings.json`: опечатка в
команде, сломанная обёртка и неверное событие роняют тест, а не проходят мимо.

Симметрия обязательна и проведена нарочно. `lint-learned`, блокирующий всё
подряд, прошёл бы проверку «блокирует запись без статуса» — поэтому рядом
стоит проверка, что на чистом файле и на постороннем файле он МОЛЧИТ.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402

PLUGIN = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ROLE = "hooked"
BODY = "Ты ассистент {PROJECT}. Дом: {HOME}.\n"

# Запись без статуса — то самое, что линтер обязан ловить.
DIRTY = "# Что узнал\n\n## Находка без статуса\n\nПросто текст.\n"
CLEAN = "# Что узнал\n\n## Находка со статусом\n\n**Статус: наблюдение** (один случай).\n"


def seed_role(sb, card_lines):
    lib = os.path.join(sb.home, ".cckit", "library", ROLE)
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(lib, "card.yaml"), "w", encoding="utf-8") as fh:
        fh.write("name: %s\nsummary: роль для проверки хуков\naccess: read-only\n" % ROLE)
        fh.write("".join(l.rstrip("\n") + "\n" for l in card_lines))
    with open(os.path.join(lib, "ROLE.md"), "w", encoding="utf-8") as fh:
        fh.write(BODY)
    return lib


def install(sb, card_lines=(), project=None):
    project = project or sb.project
    sb.set_reply("готово", transcript_prompt=BODY.replace("{PROJECT}", project)
                 .replace("{HOME}", ck.instance_home(ROLE, project)).strip())
    seed_role(sb, card_lines)
    rc = ck.cmd_install([ROLE, "--project", project])
    return rc, ck.instance_home(ROLE, project)


def settings(home):
    with open(os.path.join(home, ".claude", "settings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def registered(home):
    """{событие: [(matcher, имя хука)]} — то, что правда лежит в правах."""
    out = {}
    for event, groups in (settings(home).get("hooks") or {}).items():
        for g in groups:
            for h in g["hooks"]:
                name = h["command"].rsplit(" ", 1)[-1]
                out.setdefault(event, []).append((g.get("matcher"), name))
    return out


def fire(home, event, name, payload):
    """Запустить хук ТОЙ САМОЙ командой, что записана в правах.

    Не `bash <путь>`: так проверялась бы реализация, а не установка. Ошибка в
    записанной команде — самая дешёвая из возможных и самая тихая.
    """
    cmd = None
    for g in (settings(home).get("hooks") or {}).get(event, []):
        for h in g["hooks"]:
            if h["command"].endswith(" " + name):
                cmd = h["command"]
    if cmd is None:
        raise AssertionError("в правах нет хука %s на событии %s" % (name, event))
    proc = subprocess.run(["bash", "-c", cmd], input=json.dumps(payload),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)
    return proc


def out_json(proc):
    txt = (proc.stdout or "").strip()
    return json.loads(txt) if txt else None


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestHookInstall(unittest.TestCase):
    def test_declaration_in_the_card_puts_the_implementations_into_the_home(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [report-done, lint-learned, read-ledger]"])
            d = os.path.join(home, ".claude", "hooks")
            names = sorted(os.listdir(d)) if os.path.isdir(d) else []
            executable = sorted(n for n in names
                                if os.access(os.path.join(d, n), os.X_OK))
            # Исполнимость — часть установки, а не мелочь: скопированный без
            # бита файл даёт «Permission denied» из недр CLI, а не отказ хука.
            # `config.json` — данные, и бит ему не полагается.
            self.assertEqual((names, executable), (
                ["cckit_hook.py", "cckit_learned.py", "config.json",
                 "lint-learned", "read-ledger", "report-done", "run-hook.cmd"],
                ["cckit_hook.py", "cckit_learned.py",
                 "lint-learned", "read-ledger", "report-done", "run-hook.cmd"]))

    def test_every_declared_hook_is_registered_on_its_own_event(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [report-done, lint-learned, read-ledger]"])
            commands = [h["command"]
                        for groups in settings(home)["hooks"].values()
                        for g in groups for h in g["hooks"]]
            missing = [c for c in commands
                       if not os.path.isfile(c.split('"')[1])]
            self.assertEqual((registered(home), missing), ({
                "Stop": [(None, "report-done")],
                "PostToolUse": [("Write|Edit", "lint-learned")],
                "SessionStart": [("startup|clear|compact", "read-ledger")],
            }, []))

    def test_the_linter_that_travels_into_the_home_is_the_shipped_one(self):
        # Копия, а не ссылка на каталог плагина: дом обязан пережить переезд и
        # удаление плагина. Цена копии — расхождение, и она проверяется здесь.
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [lint-learned]"])
            shipped = open(os.path.join(PLUGIN, "bin", "cckit_learned.py"),
                           encoding="utf-8").read()
            landed = open(os.path.join(home, ".claude", "hooks", "cckit_learned.py"),
                          encoding="utf-8").read()
            self.assertEqual((landed == shipped, ck.installed_hooks(home)),
                             (True, ["lint-learned"]))

    def test_a_home_whose_path_has_a_space_still_fires(self):
        # Команда хука — строка для оболочки. Незакавыченный путь с пробелом
        # распадается на два слова, и хук не находится — молча.
        with Sandbox() as sb:
            project = os.path.join(sb.root, "мой проект")
            os.makedirs(project)
            _, home = install(sb, ["hooks: [report-done]"], project=project)
            proc = fire(home, "Stop", "report-done", {"session_id": "s"})
            with open(os.path.join(home, "reports.jsonl"), encoding="utf-8") as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            self.assertEqual((" " in home, proc.returncode, len(lines),
                              lines[0]["project"]),
                             (True, 0, 1, project))

    def test_a_card_that_declares_nothing_gets_no_hooks_at_all(self):
        # `"hooks": {}` читалось бы как «настроено», а каталог с обёрткой — как
        # «стоит». Ни того, ни другого быть не должно.
        with Sandbox() as sb:
            _, home = install(sb, [])
            self.assertEqual(("hooks" in settings(home),
                              os.path.exists(os.path.join(home, ".claude", "hooks"))),
                             (False, False))

    def test_a_card_may_name_an_event_and_bring_its_own_script(self):
        # Второе пространство имён: карточка называет СОБЫТИЕ, скрипт кладёт
        # хозяин дома. Установщик такой файл не выдумывает — он его только
        # регистрирует, и за его отсутствие отвечает проба, а не пустышка,
        # которая выглядела бы рабочим хуком.
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [stop]"])
            d = os.path.join(home, ".claude", "hooks")
            cmd = settings(home)["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertEqual(
                (cmd, sorted(os.listdir(d)), ck.installed_hooks(home)),
                ('"%s"' % os.path.join(d, "stop"), ["config.json"], ["stop"]))

    def test_an_unknown_hook_name_stops_the_install_and_names_it(self):
        with Sandbox() as sb:
            seed_role(sb, ["hooks: [report-done, telepathy]"])
            sb.set_reply("готово")
            err = None
            try:
                ck.cmd_install([ROLE, "--project", sb.project])
            except SystemExit as e:
                err = e
            home = ck.instance_home(ROLE, sb.project)
            self.assertEqual(
                (err is not None, getattr(err, "code", None),
                 os.path.exists(os.path.join(home, ".claude", "hooks", "telepathy"))),
                (True, 2, False))

    def test_reset_puts_the_hooks_back(self):
        # Права пересобираются при reset; хук, который туда не попал, пропадает
        # молча — дом продолжает выглядеть живым и перестаёт действовать.
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [report-done]"])
            shutil.rmtree(os.path.join(home, ".claude", "hooks"))
            sb.set_reply("готово", transcript_prompt=BODY
                         .replace("{PROJECT}", sb.project).replace("{HOME}", home).strip())
            ck.cmd_reset([os.path.basename(home)])
            self.assertEqual(
                (os.path.isfile(os.path.join(home, ".claude", "hooks", "report-done")),
                 registered(home)),
                (True, {"Stop": [(None, "report-done")]}))

    def test_the_command_path_never_carries_a_backslash(self):
        # На windows os.path.join даёт обратные косые, а команду исполняет
        # оболочка, для которой обратная косая — экранирование: путь распался
        # бы молча. Проверяется КОМПИЛЯЦИЯ, а не диск: настоящий windows-путь
        # подставляется прямо.
        spec = ck.compile_hooks("C:\\Users\\x\\.cckit\\a", {"hooks": ["report-done"]})
        cmd = spec["Stop"][0]["hooks"][0]["command"]
        self.assertEqual((("\\" in cmd), cmd),
                         (False, '"C:/Users/x/.cckit/a/.claude/hooks/run-hook.cmd" report-done'))


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestReportDone(unittest.TestCase):
    def test_each_turn_leaves_exactly_one_parsable_line(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [report-done]"])
            fire(home, "Stop", "report-done",
                 {"session_id": "s-один", "cwd": sb.project, "total_cost_usd": 0.125})
            proc = fire(home, "Stop", "report-done", {"session_id": "s-два"})
            with open(os.path.join(home, "reports.jsonl"), encoding="utf-8") as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            self.assertEqual(
                (proc.returncode, len(lines),
                 [(l["event"], l["role"], l["project"], l["session"], l.get("cost_usd"))
                  for l in lines],
                 bool(lines[0]["at"])),
                (0, 2,
                 [("stop", ROLE, sb.project, "s-один", 0.125),
                  ("stop", ROLE, sb.project, "s-два", None)],
                 True))

    def test_a_broken_recipe_neither_kills_the_turn_nor_goes_quiet(self):
        # Сломанный хук не вправе мешать работать — и не вправе молчать: иначе
        # он ровно то, чем был `|| exit 0` в подоболочке.
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [report-done]"])
            d = os.path.join(home, ".claude", "hooks")
            with open(os.path.join(d, "config.json"), "w", encoding="utf-8") as fh:
                fh.write("{не json")
            os.chmod(os.path.join(d, "cckit_hook.py"), 0o644)
            # Дом остаётся вычислимым из места хука, поэтому журнал всё равно
            # пишется: это и есть «не мешать работать».
            proc = fire(home, "Stop", "report-done", {"session_id": "s"})
            with open(os.path.join(home, "reports.jsonl"), encoding="utf-8") as fh:
                lines = [json.loads(l) for l in fh if l.strip()]
            self.assertEqual((proc.returncode, len(lines), lines[0]["role"]),
                             (0, 1, None))


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestLintLearned(unittest.TestCase):
    def _fire_on(self, home, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return fire(home, "PostToolUse", "lint-learned",
                    {"tool_name": "Write", "tool_input": {"file_path": path}})

    def test_a_record_without_a_status_is_blocked_with_a_readable_reason(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [lint-learned]"])
            proc = self._fire_on(home, os.path.join(home, "LEARNED.md"), DIRTY)
            d = out_json(proc)
            self.assertEqual(
                (proc.returncode, d["decision"],
                 "Находка без статуса" in d["reason"],
                 "измерено" in d["reason"],
                 d["hookSpecificOutput"]["hookEventName"]),
                (0, "block", True, True, "PostToolUse"))

    def test_it_stays_out_of_the_way_of_clean_files_and_other_files(self):
        # Без этой половины «блокирует всё подряд» выглядит как успех.
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [lint-learned]"])
            clean = self._fire_on(home, os.path.join(home, "LEARNED.md"), CLEAN)
            other = self._fire_on(home, os.path.join(sb.project, "NOTES.md"), DIRTY)
            self.assertEqual(
                [(clean.returncode, clean.stdout.strip()),
                 (other.returncode, other.stdout.strip())],
                [(0, ""), (0, "")])

    def test_a_missing_linter_says_so_instead_of_letting_the_record_through(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [lint-learned]"])
            os.remove(os.path.join(home, ".claude", "hooks", "cckit_learned.py"))
            proc = self._fire_on(home, os.path.join(home, "LEARNED.md"), DIRTY)
            d = out_json(proc)
            self.assertEqual(
                (proc.returncode, "decision" in (d or {}),
                 "lint-learned" in (d or {}).get("systemMessage", "")),
                (0, False, True))


@unittest.skipIf(sys.platform == "win32", "полиглот на windows проверяется отдельно")
class TestReadLedger(unittest.TestCase):
    def _ledger(self, project, rel, text):
        p = os.path.join(project, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        return p

    def test_the_ledger_bytes_really_reach_the_context(self):
        # Тот самый случай: `exit 0` в подоболочке отдавал валидный JSON с
        # ПУСТЫМ content, и «хук отдал JSON» было зелено. Проверяются байты.
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [read-ledger]"])
            self._ledger(sb.project, "docs/vscode-internals/STATE.md",
                         "# Ведомость\n\nлевая-панель — АКТУАЛЕН на 6011ec4e\n")
            d = out_json(fire(home, "SessionStart", "read-ledger",
                              {"source": "startup", "cwd": sb.project}))
            ctx = d["hookSpecificOutput"]["additionalContext"]
            self.assertEqual(
                ("левая-панель — АКТУАЛЕН на 6011ec4e" in ctx,
                 d["additional_context"] == ctx,
                 d["hookSpecificOutput"]["hookEventName"]),
                (True, True, "SessionStart"))

    def test_the_card_can_name_its_own_ledger_and_silence_means_absence(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [read-ledger]", "ledger: docs/ВЕДОМОСТЬ.md"])
            nothing = fire(home, "SessionStart", "read-ledger", {"cwd": sb.project})
            # Файл по пути ПО УМОЛЧАНИЮ не должен помочь: карточка назвала свой.
            self._ledger(sb.project, "docs/vscode-internals/STATE.md", "не тот файл\n")
            still = fire(home, "SessionStart", "read-ledger", {"cwd": sb.project})
            self._ledger(sb.project, "docs/ВЕДОМОСТЬ.md", "метка-7781\n")
            found = out_json(fire(home, "SessionStart", "read-ledger", {"cwd": sb.project}))
            self.assertEqual(
                (nothing.stdout.strip(), still.stdout.strip(),
                 "метка-7781" in found["additional_context"],
                 "не тот файл" in found["additional_context"]),
                ("", "", True, False))

    def test_an_empty_ledger_is_named_out_loud_rather_than_delivered_blank(self):
        with Sandbox() as sb:
            _, home = install(sb, ["hooks: [read-ledger]"])
            self._ledger(sb.project, "docs/vscode-internals/STATE.md", "   \n")
            d = out_json(fire(home, "SessionStart", "read-ledger", {"cwd": sb.project}))
            self.assertEqual(
                ("additional_context" in d, "пуст" in d.get("systemMessage", "")),
                (False, True))


if __name__ == "__main__":
    unittest.main()

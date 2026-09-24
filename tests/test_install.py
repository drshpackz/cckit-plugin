"""Установка целиком, против поддельного `claude`, внутри песочницы.

Ни один тест здесь не имеет права коснуться `~/.cckit/assistants` — там живёт
рабочий ассистент владельца с накопленной памятью. Их защищает песочница: HOME
переставлен, а `_cckit_dir()` читает HOME на каждом вызове, так что и
библиотека ролей, и дома экземпляров оказываются внутри временного дерева.

Расхождения с планом (побеждает код):
  * `main()` читает `sys.argv` и аргументов не принимает — зовутся `cmd_*`;
  * `display_name` берёт запись экземпляра, а не путь к дому;
  * у `grant` нет `--project`: экземпляр называется `<роль>@<папка>`, а `shell`
    из DANGEROUS и требует `--i-mean-it`;
  * `grant` и `revoke` правят launch.json И правила прав — settings.json тут
    больше не постоянная величина, и сравнение байт в байт что-то значит.
"""

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
ROLE = "design-scout"


def seed_library(sb):
    """Роль кладётся В ПЕСОЧНИЦУ. `library_dir()` читает HOME на каждом вызове,
    а `CCKIT_LIBRARY` песочница сбрасывает, — иначе установщик пошёл бы за
    ролью в настоящий `~/.cckit/library`."""
    lib = os.path.join(sb.home, ".cckit", "library")
    os.makedirs(lib, exist_ok=True)
    shutil.copytree(os.path.join(PLUGIN, "assistants", ROLE), os.path.join(lib, ROLE))
    return lib


def install(sb, project, extra=()):
    body = open(os.path.join(PLUGIN, "assistants", ROLE, "ROLE.md"),
                encoding="utf-8").read()
    sb.set_reply("готово", transcript_prompt=body.replace("{PROJECT}", project))
    return ck.cmd_install([ROLE, "--project", project] + list(extra))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class TestInstall(unittest.TestCase):
    def test_install_builds_the_home_with_every_file_it_promises(self):
        with Sandbox() as sb:
            seed_library(sb)
            rc = install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            missing = [f for f in (".claude/settings.json",
                                   ".claude/agents/%s.md" % ROLE,
                                   "CLAUDE.md", "LEARNED.md", "launch.json",
                                   "instance.json", "memory")
                       if not os.path.exists(os.path.join(home, *f.split("/")))]
            # Поддельный `claude` ничего не пишет на диск, поэтому проба ограды
            # не может подтвердиться и установка честно возвращает 1. Код
            # возврата закреплён вместе со списком файлов: «дом собран» и
            # «дом проверен» — разные утверждения, и путать их нельзя.
            #
            # Вызовов: проба ограды останавливается на первой части (набор
            # инструментов: подделка не называет его, «не измерено»), одна
            # проба мозга и — если карточка объявляет хуки — одна проба хуков.
            # Число хуков — дело карточки, а не установщика, поэтому ожидание
            # выводится из неё, а не зашито.
            hooks = ck.load_card(os.path.join(PLUGIN, "assistants", ROLE,
                                              "card.yaml")).get("hooks")
            self.assertEqual((rc, missing, len(sb.calls())),
                             (1, [], 2 + (1 if hooks else 0)))

    def test_the_instance_record_says_the_probes_did_not_confirm(self):
        # Установка без живой модели не имеет права записать «проверен».
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            it = json.loads(read(os.path.join(home, "instance.json")))
            self.assertEqual(
                (it["role"], it["project"], it["home"],
                 it["verified"]["containment"] == "ок",
                 it["verified"]["prompt"] == "ок"),
                (ROLE, sb.project, home, False, False))

    def test_two_projects_with_the_same_basename_get_different_homes(self):
        # И `~/work/editor`, и `~/old/editor` ставились в `design-scout@editor`,
        # и второй наследовал память первого. Проверяется не `instance_home` на
        # сухую, а две НАСТОЯЩИЕ установки: различать дома должна установка.
        with Sandbox() as sb:
            seed_library(sb)
            a = os.path.join(sb.root, "work", "editor")
            b = os.path.join(sb.root, "old", "editor")
            os.makedirs(a)
            os.makedirs(b)
            install(sb, a)
            install(sb, b)
            ha = ck.instance_home(ROLE, a)
            hb = ck.instance_home(ROLE, b)
            self.assertNotEqual(ha, hb)
            self.assertEqual(
                [json.loads(read(os.path.join(h, "instance.json")))["project"]
                 for h in (ha, hb)],
                [a, b])

    def test_the_second_project_does_not_inherit_the_first_ones_memory(self):
        with Sandbox() as sb:
            seed_library(sb)
            a = os.path.join(sb.root, "work", "editor")
            b = os.path.join(sb.root, "old", "editor")
            os.makedirs(a)
            os.makedirs(b)
            install(sb, a)
            with open(os.path.join(ck.instance_home(ROLE, a), "LEARNED.md"),
                      "a", encoding="utf-8") as fh:
                fh.write("\n## Только у первого\n**Статус: наблюдение** (2026-09-24).\n")
            install(sb, b)
            self.assertNotIn("Только у первого",
                             read(os.path.join(ck.instance_home(ROLE, b), "LEARNED.md")))

    def test_display_name_comes_from_the_directory_not_the_card(self):
        # Два столкнувшихся экземпляра под одним именем — и `where` отвечал бы
        # про тот, что попался первым.
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            it = json.loads(read(os.path.join(home, "instance.json")))
            self.assertEqual(ck.display_name(it), os.path.basename(home))

    def test_force_does_not_destroy_the_learned_file(self):
        # Месяц накопленных заметок, потерянный переустановкой, — худший отказ
        # этого продукта. `--force` пересобирает производное и не трогает
        # заработанное.
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            learned = os.path.join(home, "LEARNED.md")
            with open(learned, "a", encoding="utf-8") as fh:
                fh.write("\n## Накопленное\n**Статус: измерено** (2026-09-24, 3 случая).\n")
            memo = os.path.join(home, "memory", "note.md")
            with open(memo, "w", encoding="utf-8") as fh:
                fh.write("тоже заработанное\n")
            self.assertEqual(install(sb, sb.project, ["--force"]), 1)
            self.assertEqual((read(learned).count("## Накопленное"),
                              os.path.exists(memo)), (1, True))

    def test_force_does_rebuild_what_is_derived(self):
        # Без этого предыдущий тест зелен и на `--force`, который не делает
        # вообще ничего.
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            card = os.path.join(home, ".claude", "agents", ROLE + ".md")
            with open(card, "w", encoding="utf-8") as fh:
                fh.write("испорчено\n")
            install(sb, sb.project, ["--force"])
            self.assertNotEqual(read(card), "испорчено\n")

    def test_a_second_install_without_force_refuses_instead_of_overwriting(self):
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            with self.assertRaises(SystemExit) as e:
                install(sb, sb.project)
            self.assertEqual(e.exception.code, 2)


class TestGrantRevoke(unittest.TestCase):
    def test_grant_then_revoke_returns_every_derived_file_to_its_original_bytes(self):
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            name = os.path.basename(home)
            derived = [os.path.join(home, ".claude", "settings.json"),
                       os.path.join(home, "launch.json")]
            before = [read(p) for p in derived]

            ck.cmd_grant([name, "shell", "--i-mean-it"])
            # Сначала — что выдача правда что-то изменила в КАЖДОМ файле.
            # Иначе «вернулось к исходному» верно и для кода, который не
            # писал никуда.
            self.assertEqual([read(p) != b for p, b in zip(derived, before)],
                             [True, True])

            ck.cmd_grant([name, "shell"], revoking=True)
            self.assertEqual([read(p) for p in derived], before)

    def test_revoke_also_drops_the_capability_from_the_instance_record(self):
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            home = ck.instance_home(ROLE, sb.project)
            name = os.path.basename(home)
            rec = os.path.join(home, "instance.json")
            ck.cmd_grant([name, "shell", "--i-mean-it"])
            granted_after_grant = json.loads(read(rec))["granted"]
            ck.cmd_grant([name, "shell"], revoking=True)
            self.assertEqual(("shell" in granted_after_grant,
                              "shell" in json.loads(read(rec))["granted"]),
                             (True, False))

    def test_granting_a_dangerous_capability_without_i_mean_it_is_refused(self):
        with Sandbox() as sb:
            seed_library(sb)
            install(sb, sb.project)
            name = os.path.basename(ck.instance_home(ROLE, sb.project))
            with self.assertRaises(SystemExit):
                ck.cmd_grant([name, "shell"])


class TestTheSandboxKeepsTheRealAssistantsOut(unittest.TestCase):
    def test_the_installer_roots_move_with_the_sandbox_home(self):
        # Тот самый отказ, ради которого корни установщика — функции: застывший
        # на импорте HOME заставлял их смотреть в настоящий ~/.cckit, поверх
        # живого ассистента.
        real = ck.assistants_dir()
        with Sandbox() as sb:
            self.assertTrue(ck.assistants_dir().startswith(sb.root + os.sep),
                            ck.assistants_dir())
            self.assertTrue(ck.library_dir().startswith(sb.root + os.sep))
            self.assertTrue(ck.claude_json().startswith(sb.root + os.sep))
        self.assertEqual(ck.assistants_dir(), real)


if __name__ == "__main__":
    unittest.main()

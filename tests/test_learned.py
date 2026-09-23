"""Линтер статусов в LEARNED.md.

Главная опасность здесь — чистота от пустоты: линтер, не разобравший ни одной
записи, возвращает ровно то же самое, что линтер на безупречном файле. Поэтому
всюду, где утверждается «чисто», рядом утверждается ЧИСЛО разобранных записей.

Живые файлы только читаются. Ни один тест в этом файле ничего не пишет за
пределами самого себя.
"""

import contextlib
import glob
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))

import cckit_assistant as ck  # noqa: E402
import cckit_learned as learned  # noqa: E402

PLUGIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

GOOD = """# Что я узнал

## Порядок чтения дизайна

**Статус: измерено** (2026-09-23, прогон smoke-1, 3 случая).

Читать артборд раньше specs.md экономит один проход.
"""

SHORT = """# Что я узнал

## Порядок чтения дизайна

**измерено** (2026-09-23, 3 случая).
"""

NO_STATUS = """# Что я узнал

## Порядок чтения дизайна

Читать артборд раньше specs.md экономит один проход.
"""

BAD_STATUS = """# Что я узнал

## Порядок чтения

**Статус: наверное** так быстрее.
"""

# Написание, которое живой ассистент владельца правда употребил, знак в знак.
# Линтер, отвергающий его, отвергает единственную честную запись на машине.
LIVE_BOLD = """# Что я узнал на этом проекте

## У этой сессии нет исполнения команд — только файловые инструменты

**Статус: наблюдение** (2026-09-23, проба `.cckit-exec-probe`).

Доступный набор: `Edit`, `Glob`, `Grep`, `Read`.
"""

LIVE_TICK = """# Что я узнал на этом проекте

## Исполнение из этой сессии закрыто

`наблюдение` — 2026-09-23, Opus 5 (claude-opus-5).

Инструментов исполнения нет.
"""


class TestLint(unittest.TestCase):
    def test_a_record_with_a_valid_status_passes(self):
        self.assertEqual((len(learned.records(GOOD)), learned.lint(GOOD)), (1, []))

    def test_the_short_form_without_the_word_status_passes(self):
        self.assertEqual((len(learned.records(SHORT)), learned.lint(SHORT)), (1, []))

    def test_both_live_spellings_pass(self):
        self.assertEqual(
            [(len(learned.records(t)), learned.lint(t)) for t in (LIVE_BOLD, LIVE_TICK)],
            [(1, []), (1, [])])

    def test_a_record_without_a_status_is_reported(self):
        msgs = learned.lint(NO_STATUS)
        self.assertEqual(len(msgs), 1)
        self.assertIn("Порядок чтения дизайна", msgs[0])

    def test_an_invented_status_is_reported_as_invented(self):
        msgs = learned.lint(BAD_STATUS)
        self.assertEqual(len(msgs), 1)
        self.assertIn("наверное", msgs[0])

    def test_every_status_is_accepted(self):
        self.assertEqual(
            [learned.lint("## З\n\n**Статус: %s** (2026-09-23).\n" % s)
             for s in learned.STATUSES],
            [[], [], [], []])

    def test_a_file_with_no_records_is_clean_and_says_so(self):
        text = "# Что я узнал\n\nПока пусто.\n"
        self.assertEqual((len(learned.records(text)), learned.lint(text)), (0, []))

    def test_a_subsection_is_not_a_record_of_its_own(self):
        # `### Подробности` внутри записи не обязан нести свой статус.
        text = GOOD + "\n### Подробности\n\nЕщё немного.\n"
        self.assertEqual((len(learned.records(text)), learned.lint(text)), (1, []))

    def test_a_status_word_quoted_in_prose_is_not_a_status(self):
        # Вводная часть шаблона перечисляет статусы в обратных кавычках прозой.
        # Если бы такое засчитывалось где угодно в строке, запись, которая
        # просто упоминает `гипотеза`, проходила бы без собственного статуса.
        text = ("## Запись\n\nЭто пока не `гипотеза` и даже не `измерено`, "
                "а просто заметка.\n")
        self.assertEqual(len(learned.lint(text)), 1)


class TestTheFilesThatMustStayClean(unittest.TestCase):
    def test_the_installer_template_is_clean_and_carries_a_worked_example(self):
        # Пустой шаблон ничему не учит о форме, которую требует; а вводная
        # часть, перечисляющая статусы прозой, записью не считается.
        self.assertEqual((len(learned.records(ck.LEARNED_MD)),
                          learned.lint(ck.LEARNED_MD)), (1, []))

    def test_the_plugins_own_learned_file_is_clean(self):
        # Требовать дисциплину и не вести её самому — не годится.
        with open(os.path.join(PLUGIN, "LEARNED.md"), encoding="utf-8") as fh:
            text = fh.read()
        # Число записей НЕ зашивается: оно растёт при каждой находке, и тест,
        # падающий от того, что мы что-то узнали, учит стирать записи.
        self.assertEqual(learned.lint(text), [])
        self.assertGreaterEqual(len(learned.records(text)), 9)

    def test_every_live_assistant_file_on_this_machine_is_clean(self):
        # ТОЛЬКО ЧТЕНИЕ. Файлы живого ассистента владельца — не полигон.
        paths = sorted(glob.glob(os.path.join(
            os.path.expanduser("~"), ".cckit", "assistants", "*", "LEARNED.md")))
        if not paths:
            self.skipTest("на этой машине установленных ассистентов нет")
        self.assertEqual(
            {p: learned.lint(open(p, encoding="utf-8").read()) for p in paths},
            {p: [] for p in paths})


class TestCmdLint(unittest.TestCase):
    def lint_file(self, text):
        """Отчёт линтера перехватывается: он адресован человеку у терминала,
        а не выводу набора, где он читается как падение."""
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "LEARNED.md")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
            with contextlib.redirect_stdout(io.StringIO()):
                return learned.cmd_lint(p)

    def test_exit_code_is_one_when_a_record_has_no_status(self):
        self.assertEqual(self.lint_file(NO_STATUS), 1)

    def test_exit_code_is_zero_on_a_clean_file(self):
        self.assertEqual(self.lint_file(GOOD), 0)

    def test_a_missing_path_is_an_error_not_a_clean_bill(self):
        self.assertEqual(learned.main(["/нет/такого/LEARNED.md"]), 2)

    def test_no_path_at_all_is_an_error(self):
        self.assertEqual(learned.main([]), 2)


if __name__ == "__main__":
    unittest.main()

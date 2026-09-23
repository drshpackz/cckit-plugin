# -*- coding: utf-8 -*-
"""Ограда на живых прогонах. Идёт всегда, денег не стоит.

Переменная, выставленная в CI однажды, оплачивается на каждом пуше. Поэтому
проверяется не обещание, а два факта: пробы выключены по умолчанию и workflow
эту переменную не ставит.
"""

import os
import re
import unittest

from . import LIVE

PLUGIN = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKFLOW = os.path.join(PLUGIN, ".github", "workflows", "test.yml")


class TestLiveGuard(unittest.TestCase):
    def test_live_is_off_unless_the_variable_says_otherwise(self):
        self.assertEqual(LIVE, os.environ.get("CCKIT_LIVE") == "1")

    def test_every_live_test_is_skipped_without_the_variable(self):
        # Иначе проба «живая» только по имени файла: достаточно забыть
        # декоратор в одном классе, и пуш начинает тратить деньги.
        from . import test_live_probe as probe
        classes = [v for v in vars(probe).values()
                   if isinstance(v, type) and issubclass(v, unittest.TestCase)]
        self.assertTrue(classes, "в tests/live нет ни одного класса проб")
        for cls in classes:
            self.assertEqual(getattr(cls, "__unittest_skip__", False), not LIVE,
                             "%s не закрыт @skipUnless(LIVE)" % cls.__name__)


class TestWorkflowDoesNotTurnLiveOn(unittest.TestCase):
    def test_the_workflow_exists(self):
        # Без этого тест ниже зеленеет оттого, что читать нечего.
        self.assertTrue(os.path.isfile(WORKFLOW), WORKFLOW)

    def test_the_workflow_never_assigns_the_live_variable(self):
        # Проверяется ПРИСВОЕНИЕ, а не упоминание: шаг, который убеждается, что
        # переменной нет, обязан называть её по имени — и «нет упоминаний»
        # запретило бы саму проверку.
        with open(WORKFLOW, encoding="utf-8") as fh:
            text = fh.read()
        readings = re.sub(r"\$\{[^}]*\}", "", text)       # ${CCKIT_LIVE:-} — чтение
        assignments = re.findall(r"CCKIT_LIVE\s*[:=]\s*\S+", readings)
        self.assertEqual(assignments, [], "workflow выставляет CCKIT_LIVE: %s" % assignments)

    def test_the_workflow_asserts_the_variable_is_unset(self):
        with open(WORKFLOW, encoding="utf-8") as fh:
            text = fh.read()
        self.assertRegex(text, r"test -z \"\$\{CCKIT_LIVE:-\}\"",
                         "в CI нет шага, проверяющего, что CCKIT_LIVE не выставлена")


if __name__ == "__main__":
    unittest.main()

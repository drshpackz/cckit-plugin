# -*- coding: utf-8 -*-
"""Три вопроса, на которые поддельный `claude` ответить не может.

Проба УТВЕРЖДАЕТ РЕЗУЛЬТАТ ФУНКЦИИ — `prompt_delivered` и `memory_delivered`
вернули True, — и никогда не сличает тексты промптов сама. Диагностика тоже
идёт только через `core.describe_mismatch`: длина, метка, точка расхождения.
Выковыривание доставленного промпта уже убивало здесь агентов; нам нужен
ответ «дошло или нет», а сам текст мы и так написали.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "bin"))

import cckit_bench as bench                                          # noqa: E402
import cckit_core as core                                            # noqa: E402

from . import LIVE, live_reason                                      # noqa: E402

BUDGET = "0.10"
TIMEOUT = 180

ROLE = ("Ты — проба переносимости CCKit. Отвечай одним словом.\n"
        "Метка роли: ПРОБА-РОЛИ-CCKIT-2026.\n")
MARK = "Выученная метка живой пробы CCKIT: пионер-ромашка-77."


def launch(box, prompt):
    argv = core.launch_argv(prompt, box, bench.disallowed_tools(), True, BUDGET,
                            extra=["--output-format", "json"])
    return core.run_claude(box, argv, timeout=TIMEOUT)


@unittest.skipUnless(LIVE, live_reason())
class TestRealCli(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.mkdtemp(prefix="cckit-live-")
        self.addCleanup(shutil.rmtree, self.box, True)

    def assertReallyRan(self, res, err):
        """Живая проба, ничего не запустившая, — самый дорогой вид зелёного.

        Поэтому утверждается не «исключения не было», а три следа настоящего
        вызова: id сессии, отсутствие ошибки в самом ответе и ненулевой счёт.
        Прогон, за который не списали ни цента, не состоялся.
        """
        self.assertIsNone(err)
        res = res or {}
        self.assertFalse(res.get("is_error"), res.get("result"))
        self.assertTrue(res.get("session_id"), "ответ без session_id: %r" % sorted(res))
        self.assertGreater(res.get("total_cost_usd") or 0, 0, "прогон ничего не стоил")

    def test_the_cli_answers_and_reports_a_session_id(self):
        res, err = launch(self.box, "Ответь одним словом: готово")
        self.assertReallyRan(res, err)

    def test_the_role_body_reaches_the_model(self):
        # То единственное, чего подделка подтвердить не может: что харнесс
        # правда отдаёт модели написанное нами тело роли.
        bench.write_variant_card(self.box, ROLE.strip())
        res, err = launch(self.box, "Ответь одним словом: готово")
        self.assertReallyRan(res, err)
        ok, note = bench.prompt_delivered(res["session_id"], ROLE.strip())
        self.assertTrue(ok, "роль не доехала: %s" % note)
        # И заодно: диагностика обязана описывать расхождение, а не цитировать.
        # Кусок тела роли в ноте означал бы, что промпт утёк в отчёт.
        self.assertNotIn(ROLE[:24], note)

    def test_the_learned_layer_reaches_the_model(self):
        # Выученный слой едет @-импортом, а не системным промптом: он ломается
        # отдельно и молча, и тогда стенд сравнивает две одинаковых руки.
        with open(os.path.join(self.box, "LEARNED.md"), "w", encoding="utf-8") as fh:
            fh.write(bench.LEARNED_MD.strip() + "\n\n" + MARK + "\n")
        with open(os.path.join(self.box, "CLAUDE.md"), "w", encoding="utf-8") as fh:
            fh.write("@LEARNED.md\n")
        needle = bench.memory_needle(bench.LEARNED_MD.strip() + "\n\n" + MARK + "\n")
        self.assertTrue(needle, "метка не выделилась из выученного слоя")

        res, err = launch(self.box, "Ответь одним словом: готово")
        self.assertReallyRan(res, err)
        ok, note = bench.memory_delivered(res["session_id"], needle)
        self.assertTrue(ok, "выученный слой не доехал: %s" % note)


if __name__ == "__main__":
    unittest.main()

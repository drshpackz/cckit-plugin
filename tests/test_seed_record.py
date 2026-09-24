"""Запись-зерно: линтер описывает формат, который держат живые досье."""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "formats", "seed-record", "lint.py")
spec = importlib.util.spec_from_file_location("seed_lint", PATH)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

GOOD = """---
topic: welcome-page
question: Что на странице Welcome и где каждая строка задана в коде
collected: 2026-09-24
commit: c3626e6f
confidence: high
source: отчёт субагента; каждая ссылка перепроверена чтением файла
---
# Welcome

## Вердикт

Порядок: шапка, Start и Recent, Walkthroughs, подвал.

## Файлы

## Открытые вопросы
"""


class TestSeedRecord(unittest.TestCase):
    def test_a_record_in_the_practised_shape_passes(self):
        self.assertEqual(seed.lint(GOOD), [])

    def test_the_components_own_readme_is_a_seed_record(self):
        with open(os.path.join(HERE, "..", "formats", "seed-record", "README.md"), encoding="utf-8") as fh:
            self.assertEqual(seed.lint(fh.read()), [])

    def test_each_break_is_named(self):
        cases = {
            "нет шапки": GOOD.split("---\n", 2)[2],
            "в шапке нет «source»": GOOD.replace("source: отчёт субагента; каждая ссылка перепроверена чтением файла\n", ""),
            "commit — не sha": GOOD.replace("commit: c3626e6f", "commit: вчера"),
            "confidence — не high/medium/low": GOOD.replace("confidence: high", "confidence: уверен"),
            "первый раздел — не «Вердикт»": GOOD.replace("## Вердикт", "## Контекст"),
            "нет раздела «Открытые вопросы»": GOOD.replace("## Открытые вопросы\n", ""),
        }
        for want, text in cases.items():
            with self.subTest(want):
                self.assertTrue(any(want in m for m in seed.lint(text)), seed.lint(text))


if __name__ == "__main__":
    unittest.main()

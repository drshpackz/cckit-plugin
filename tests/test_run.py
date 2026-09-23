# «Поручить» — то, чего у плагина не было вовсе. Поставить, осмотреть, выдать
# права и снести можно было; дать работу — нечем. Человек, поставивший плагин с
# GitHub, получал ассистента, которого не может запустить.
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bin"))
from harness import Sandbox  # noqa: E402
import cckit_assistant as ck  # noqa: E402


class TestRun(unittest.TestCase):
    def home_with_recipe(self, sb, name="role@proj", budget="0.25"):
        home = os.path.join(sb.home, ".cckit", "assistants", name)
        os.makedirs(home)
        with open(os.path.join(home, "launch.json"), "w", encoding="utf-8") as fh:
            json.dump({"role": "role", "project": sb.project, "home": home,
                       "granted": ["read", "skills"], "budget_usd": budget}, fh)
        with open(os.path.join(home, "instance.json"), "w", encoding="utf-8") as fh:
            json.dump({"role": "role", "project": sb.project, "home": home,
                       "uuid": "u1", "verified": True}, fh)
        return home

    def run_cmd(self, argv):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            rc = ck.main(["run"] + argv)
        return rc, out.getvalue()

    def test_an_unknown_instance_is_an_error_not_a_silent_nothing(self):
        with Sandbox():
            rc, out = self.run_cmd(["нет-такого", "задание"])
            self.assertNotEqual(rc, 0)
            self.assertIn("нет-такого", out)

    def test_a_task_runs_from_the_instance_home(self):
        with Sandbox() as sb:
            home = self.home_with_recipe(sb)
            sb.set_reply("готово")
            rc, out = self.run_cmd(["role@proj", "посчитай"])
            self.assertEqual(rc, 0, out)
            calls = sb.calls()
            self.assertEqual(len(calls), 1, "ребёнок не запускался — тест пуст")
            self.assertEqual(os.path.realpath(calls[0]["cwd"]), os.path.realpath(home))
            self.assertIn("готово", out)

    def test_the_budget_from_the_recipe_reaches_the_child(self):
        with Sandbox() as sb:
            self.home_with_recipe(sb, budget="0.07")
            sb.set_reply("ok")
            self.run_cmd(["role@proj", "задание"])
            argv = sb.calls()[0]["argv"]
            self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.07")

    def test_the_task_itself_is_what_the_child_is_asked(self):
        with Sandbox() as sb:
            self.home_with_recipe(sb)
            sb.set_reply("ok")
            self.run_cmd(["role@proj", "найди позицию полосы значков"])
            self.assertIn("найди позицию полосы значков", sb.calls()[0]["argv"])

    def test_an_explicit_budget_wins_over_the_recipe(self):
        # Флаг, который молча проигрывает рецепту, — враньё в справке.
        # Замерено: --budget 2.50 при рецепте 3.00 дал прогон на $2.96.
        with Sandbox() as sb:
            self.home_with_recipe(sb, budget="3.00")
            sb.set_reply("ok")
            self.run_cmd(["role@proj", "задание", "--budget", "0.30"])
            argv = sb.calls()[0]["argv"]
            self.assertEqual(argv[argv.index("--max-budget-usd") + 1], "0.30")

    def test_raising_the_ceiling_above_the_recipe_is_said_out_loud(self):
        with Sandbox() as sb:
            self.home_with_recipe(sb, budget="0.50")
            sb.set_reply("ok")
            _, out = self.run_cmd(["role@proj", "задание", "--budget", "9.00"])
            self.assertIn("0.50", out, "потолок рецепта поднят молча")

    def test_a_home_without_a_recipe_says_so(self):
        with Sandbox() as sb:
            home = os.path.join(sb.home, ".cckit", "assistants", "role@proj")
            os.makedirs(home)
            with open(os.path.join(home, "instance.json"), "w", encoding="utf-8") as fh:
                json.dump({"role": "role", "home": home, "uuid": "u"}, fh)
            rc, out = self.run_cmd(["role@proj", "задание"])
            self.assertNotEqual(rc, 0)
            self.assertIn("рецепт", out.lower())


if __name__ == "__main__":
    unittest.main()

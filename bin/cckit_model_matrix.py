#!/usr/bin/env python3
"""Пробы ограды и промпта на каждой модели по очереди.

Юнит-тесты от модели не зависят — там поддельный `claude`. Зависит всё живое:
доходит ли тело роли как `systemPrompt[0]`, принимается ли идентификатор,
держится ли ограда. Это гонялось на двух моделях из соображения «должно быть
одинаково» — то есть не гонялось.

Стоит денег: два прогона на модель. Запускается руками.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.join(HERE, "cckit_assistant.py")
MODELS = ["claude-opus-5", "claude-opus-5-5", "claude-sonnet-5",
          "claude-fable-5-1", "claude-haiku-4-5-20251001"]


def probe(model, role_src, workdir):
    """Поставить одноразовый экземпляр на этой модели и посмотреть на пробы."""
    lib = os.path.join(workdir, "lib", "probe-role")
    os.makedirs(lib, exist_ok=True)
    with open(os.path.join(role_src, "card.yaml"), encoding="utf-8") as fh:
        card = fh.read()
    card = card.replace("name: cckit-smith", "name: probe-role")
    for line in card.splitlines():
        if line.startswith("model:"):
            card = card.replace(line, "model: " + model)
    with open(os.path.join(lib, "card.yaml"), "w", encoding="utf-8") as fh:
        fh.write(card)
    shutil.copyfile(os.path.join(role_src, "ROLE.md"),
                    os.path.join(lib, "ROLE.md"))

    project = os.path.join(workdir, "proj")
    os.makedirs(os.path.join(project, "docs", "findings"), exist_ok=True)
    env = dict(os.environ, CCKIT_LIBRARY=os.path.join(workdir, "lib"))
    p = subprocess.run([sys.executable, INSTALLER, "install", "probe-role",
                        "--project", project, "--force"],
                       env=env, capture_output=True, text=True, timeout=600)
    out = p.stdout + p.stderr
    return {
        "model": model,
        "ограда": "ок" if "ок — запись и исполнение" in out else "НЕТ",
        "промпт": "ок" if "ок — частей" in out else "НЕТ",
        "код": p.returncode,
        "нота": next((l.strip() for l in out.splitlines()
                      if "НЕ ДОСТАВЛЕН" in l or "не подтвердилась" in l), ""),
    }


def main():
    role_src = os.path.join(os.path.dirname(HERE), "assistants", "cckit-smith")
    models = sys.argv[1:] or MODELS
    rows = []
    for m in models:
        work = tempfile.mkdtemp(prefix="cckit-modelmatrix-")
        try:
            r = probe(m, role_src, work)
        except Exception as e:                  # noqa: BLE001 — отказ это данные
            r = {"model": m, "ограда": "?", "промпт": "?", "код": -1, "нота": str(e)[:80]}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        rows.append(r)
        print("  %-28s ограда:%-4s промпт:%-4s %s"
              % (r["model"], r["ограда"], r["промпт"], r["нота"][:60]))
    bad = [r for r in rows if r["ограда"] != "ок" or r["промпт"] != "ок"]
    print("\n%d из %d моделей прошли обе пробы" % (len(rows) - len(bad), len(rows)))
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

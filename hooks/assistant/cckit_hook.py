#!/usr/bin/env python3
"""Три хука дома ассистента. Один файл на три имени: решают они разное, а
падать обязаны одинаково.

Хук — единственное, чем дом действует САМ, в моменты своей жизни, а не когда
его спросили. Отсюда два запрета сразу, и они тянут в разные стороны:

  * **упасть громко нельзя.** Сломанный хук не должен мешать ассистенту
    работать, поэтому наружу всегда уходит код 0, что бы здесь ни случилось;
  * **промолчать тоже нельзя.** В `hooks/session-start` стояло
    `content=$(cat … || exit 0)`: `exit 0` выходил из ПОДОБОЛОЧКИ, а не из
    скрипта, оставлял пустую строку и рапортовал успехом. Хук, которому не
    удалось, был неотличим от хука, которому нечего сказать.

Поэтому здесь ровно одно различие, и оно проведено руками: «нечего сказать» —
молчание, «не смог» — всегда `systemMessage` с причиной. Ни один `except` не
уходит в пустоту.

Разбор JSON оставлен питону нарочно. Те же несколько строк на bash — это и
есть `|| exit 0` в подоболочке: место, где неудача выглядит успехом.
"""

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# Ведомость по умолчанию. Карточка может назвать свою (`ledger:`); эта —
# та, ради которой хук и заводился.
DEFAULT_LEDGERS = ("docs/vscode-internals/STATE.md",)

# Ведомость едет в контекст сессии целиком, и потолок тут не украшение:
# у ассистента она съедает окно, которое он не выбирал.
LEDGER_LIMIT = 60000


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(obj):
    """Пусто — значит молчание. Молчание здесь всегда намеренное."""
    if not obj:
        return
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _fail(name, why):
    """Не смог. Это НЕ молчание и НЕ отказ: ход продолжается, владелец видит."""
    _emit({"systemMessage": "хук %s: %s" % (name, why)})


def _config():
    """Рецепт рядом с хуком. Его пишет установщик; правка исчезнет при reset."""
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _home():
    """Дом: из рецепта, а если рецепта нет — из своего места на диске.

    Хук лежит в `<дом>/.claude/hooks/`, и это знание дороже рецепта: дом,
    потерявший config.json, всё ещё получает свой журнал, а не чужой."""
    cfg_home = _config().get("home")
    if isinstance(cfg_home, str) and cfg_home:
        return cfg_home
    return os.path.dirname(os.path.dirname(HERE))


def _payload():
    """Тело события со стандартного входа.

    `isatty` — не украшение: без входа `read()` заблокировался бы навсегда, и
    хук, который ничего не делает, выглядел бы как хук, который висит."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except Exception:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _as_list(v, default):
    if isinstance(v, str) and v.strip():
        return [v.strip()]
    if isinstance(v, (list, tuple)):
        return [x for x in v if isinstance(x, str) and x.strip()]
    return list(default)


# ── Stop ──────────────────────────────────────────────────────────────────

def report_done(cfg, payload):
    """Ход кончился — строка в журнал. Сегодня владелец узнаёт об этом,
    читая журналы глазами; узнавать он должен, не читая."""
    path = os.path.join(_home(), "reports.jsonl")
    line = {"at": _now(), "event": "stop",
            "role": cfg.get("role"), "project": cfg.get("project"),
            "session": payload.get("session_id"),
            "cwd": payload.get("cwd"),
            "transcript": payload.get("transcript_path")}
    # «Сколько стоило, ЕСЛИ ИЗВЕСТНО»: харнесс кладёт цену в тело события не
    # всегда. Отсутствие ключа честнее нуля — ноль читается как «бесплатно».
    for k in ("total_cost_usd", "cost_usd"):
        v = payload.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            line["cost_usd"] = round(float(v), 4)
            break
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError as e:
        _fail("report-done", "не записать %s: %s" % (path, e))


# ── PostToolUse (Write|Edit) ──────────────────────────────────────────────

def _edited_paths(payload):
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return []
    out = []
    for k in ("file_path", "filePath", "path", "notebook_path"):
        v = ti.get(k)
        if isinstance(v, str) and v and v not in out:
            out.append(v)
    return out


def lint_learned(cfg, payload):
    """Тронут LEARNED.md — прогнать линтер. Сегодня его зовут руками, и
    запись без статуса доживает до коммита, где через месяц читается как
    измеренный факт."""
    targets = [p for p in _edited_paths(payload)
               if os.path.basename(p) == "LEARNED.md"]
    if not targets:
        return                      # не наш файл: молчание, а не отказ
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import cckit_learned
    except Exception as e:
        # Молчать тут нельзя вдвойне: снаружи «линтер не нашёлся» и «линтер
        # промолчал» — одно и то же, и второе означает, что запись прошла.
        _fail("lint-learned",
              "линтер рядом с хуком не читается (%s) — запись без статуса "
              "прошла бы непроверенной" % e)
        return
    problems = []
    for p in targets:
        try:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            _fail("lint-learned", "не прочитать %s: %s" % (p, e))
            continue
        msgs = cckit_learned.lint(text)
        if msgs:
            problems.append((p, msgs))
    if not problems:
        return
    parts = []
    for p, msgs in problems:
        parts.append(p + ":")
        parts += ["  " + m for m in msgs]
    reason = ("Запись без статуса через месяц читается как измеренный факт — "
              "и тот, кто её прочтёт, не отличит догадку от замера.\n"
              + "\n".join(parts)
              + "\n\nДопишите строку статуса: **Статус: измерено** "
                "(или наблюдение / гипотеза / слово владельца), с датой и "
                "числом случаев.")
    _emit({"decision": "block", "reason": reason,
           "hookSpecificOutput": {"hookEventName": "PostToolUse",
                                  "additionalContext": reason}})


# ── SessionStart ──────────────────────────────────────────────────────────

def read_ledger(cfg, payload):
    """Ведомость — в контекст сессии. Сегодня это пишут в бриф руками, и
    раздел, помеченный актуальным, переисследуют, потому что не прочли."""
    project = cfg.get("project") or payload.get("cwd") or os.getcwd()
    chunks = []
    for rel in _as_list(cfg.get("ledger"), DEFAULT_LEDGERS):
        p = rel if os.path.isabs(rel) else os.path.join(project, rel)
        if not os.path.isfile(p):
            continue                # ведомости нет — это не поломка
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as e:
            _fail("read-ledger", "не прочитать %s: %s" % (p, e))
            continue
        # Пустой файл — это и есть та самая пустая строка с кодом 0: ведомость
        # на месте, доставлено ничего. Названо вслух.
        if not text.strip():
            _fail("read-ledger", "%s пуст — доставлять нечего" % p)
            continue
        if len(text) > LEDGER_LIMIT:
            text = text[:LEDGER_LIMIT] + "\n…(обрезано на %d знаках)" % LEDGER_LIMIT
        chunks.append("=== ведомость %s ===\n%s" % (rel, text))
    if not chunks:
        return
    ctx = ("Ведомость проекта — что уже исследовано и на каком коммите.\n"
           "Раздел, помеченный актуальным, переисследовать запрещено.\n\n"
           + "\n\n".join(chunks))
    # Cursor читает additional_context, Claude Code — hookSpecificOutput.
    _emit({"additional_context": ctx,
           "hookSpecificOutput": {"hookEventName": "SessionStart",
                                  "additionalContext": ctx}})


HANDLERS = {"report-done": report_done,
            "lint-learned": lint_learned,
            "read-ledger": read_ledger}


def main(argv):
    name = argv[0] if argv else ""
    fn = HANDLERS.get(name)
    if fn is None:
        _fail(name or "<без имени>",
              "неизвестное имя хука; есть: " + ", ".join(sorted(HANDLERS)))
        return 0
    try:
        fn(_config(), _payload())
    except Exception as e:      # noqa: BLE001 — падать громко хук не вправе
        _fail(name, "сорвался: %s: %s" % (type(e).__name__, e))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

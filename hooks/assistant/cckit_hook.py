#!/usr/bin/env python3
"""Хуки дома ассистента. Один файл на все имена: решают они разное, а
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
import re
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


# ── PreToolUse (Write|Edit|MultiEdit|Bash) ────────────────────────────────
#
# Линтер висел на PostToolUse, и его «block» запись НЕ отменял. Измерено
# 2026-09-24: субагент дописал в LEARNED.md запись без статуса, хук сработал,
# причина до субагента дошла — а строка осталась на диске. PostToolUse зовут
# ПОСЛЕ того, как правка легла; отказать записи можно только ДО неё.
#
# Поэтому хук сам вычисляет файл таким, каким он станет после правки, и
# отказывает, если линтер недоволен. Отказ PreToolUse держит и под bypass, и
# на вызовах субагентов — проверено живым запуском 2026-09-24 (haiku, `-p`,
# bypassPermissions: правка основного потока и правка субагента не легли).

LEARNED = "LEARNED.md"


def _is_learned(path):
    # Без учёта регистра: на APFS learned.md и LEARNED.md — один и тот же файл
    # (взломщик 1.2 положил запись без статуса через «learned.md» мимо линтера).
    return isinstance(path, str) and os.path.basename(path).lower() == LEARNED.lower()


def _read_or_none(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _apply_edit(text, old, new, replace_all):
    """Текст после одной правки Edit — или None, если Edit откажет сам.

    None здесь не «разрешить молча», а «не смог предсказать»: у Edit есть
    своя нормализация (кавычки, переводы строк), и там, где предсказание
    промахнулось, вызывающий проверяет саму вставку (см. `_fragment_only`).
    """
    if text is None:
        return new if old == "" else None
    if old == "":
        return new if text == "" else None
    n = text.count(old)
    if n == 0 or (n > 1 and not replace_all):
        return None
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def _after_write(tool, ti, cwd, match=None):
    """(путь, текст до, текст после) для правки файла, который узнаёт `match`
    (по умолчанию — LEARNED.md). `match` получает абсолютный путь.

    None — не наш файл. Текст после — None, если правку не удалось
    воспроизвести; тогда судят по вставке, а не пропускают."""
    path = ti.get("file_path")
    if not isinstance(path, str) or not path:
        return None
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    if not (match or _is_learned)(path):
        return None
    before = _read_or_none(path)
    if tool == "Write":
        content = ti.get("content")
        return path, before or "", content if isinstance(content, str) else None
    if tool == "Edit":
        edits = [ti]
    elif tool == "MultiEdit":
        edits = ti.get("edits") or []
    else:
        return None
    text = before
    for e in edits:
        if not isinstance(e, dict):
            return path, before or "", None
        text = _apply_edit(text, e.get("old_string") or "",
                           e.get("new_string") or "", bool(e.get("replace_all")))
        if text is None:
            return path, before or "", None
    return path, before or "", text


def _fragment_only(ti):
    """Всё, что правка ВСТАВЛЯЕТ, одной строкой — для случая, когда файл
    после правки не вычислить. Запись без статуса во вставке видна и так."""
    parts = []
    for e in ([ti] + list(ti.get("edits") or [])):
        if isinstance(e, dict):
            for k in ("new_string", "content"):
                if isinstance(e.get(k), str):
                    parts.append(e[k])
    return "\n".join(parts)


def _new_problems(lint, before, after):
    """Только то, чего не было ДО правки. Файл, где уже лежит старая запись
    без статуса, иначе запирал бы любую запись, в том числе исправляющую —
    и ассистент ушёл бы писать через Bash, мимо линтера.

    `before` None — файла до правки не было: сравнивать не с чем, и каждое
    замечание новое (иначе пустой файл «уже без шапки» пропускал бы запись
    без шапки)."""
    left = {}
    for m in (lint(before) if before is not None else []):
        left[m] = left.get(m, 0) + 1
    out = []
    for m in lint(after):
        if left.get(m, 0) > 0:
            left[m] -= 1
        else:
            out.append(m)
    return out


# Запись в LEARNED.md через Bash. ЭВРИСТИКА, и цена названа вслух: она ловит
# очевидные формы (перенаправление, tee, sed/perl -i, cp/mv/dd поверх файла,
# однострочник интерпретатора с открытием на запись), а обходится чем угодно
# ещё — путь в переменной (`f=LEARN; … > "${f}ED.md"`), глоб (`LEARN*.md`),
# скрипт из файла, запись в другой файл и `mv` без имени в той же строке,
# symlink. Разобрать шелл честно нельзя; всё, что здесь не узнано, ложится
# мимо линтера молча, как и раньше. Ложный отказ — только когда имя стоит
# ЦЕЛЬЮ записи; чтение (`cat`, `grep`, `sed -n`, `cp LEARNED.md куда-то`) не
# трогается.
_TOK = r"""["']?[^\s;|&<>()"']*LEARNED\.md(?![\w.])["']?"""
_BASH_WRITES = (
    ("перенаправление в файл", re.compile(r">\|?\s*" + _TOK, re.IGNORECASE)),
    ("tee", re.compile(r"\btee\b[^;|&]*\s" + _TOK, re.IGNORECASE)),
    ("правка на месте (sed/perl -i)",
     re.compile(r"\b(?:g?sed|perl)\b(?=[^;|&]*\s-[a-zA-Z]*i)[^;|&]*\s" + _TOK, re.IGNORECASE)),
    ("cp/mv/install/rsync поверх файла",
     re.compile(r"\b(?:cp|mv|install|rsync)\b[^;|&]*\s" + _TOK + r"\s*(?:$|[;|&)])", re.IGNORECASE)),
    ("dd of=", re.compile(r"\bdd\b[^;|&]*\bof=" + _TOK, re.IGNORECASE)),
)
_INTERP = re.compile(r"\b(?:python[0-9.]*|node|ruby|perl|php|deno|bun)\b")
_INTERP_WRITE = re.compile(
    r"write_text|write_bytes|writeFile|appendFile|createWriteStream"
    r"|File\.(?:write|open)|open\s*\([^)]*,\s*(?:mode\s*=\s*)?['\"][^'\"]*[wax+]")


def _bash_learned_write(cmd):
    """Какой формой команда пишет в LEARNED.md, или None."""
    if not isinstance(cmd, str) or LEARNED.lower() not in cmd.lower():
        return None
    for label, rx in _BASH_WRITES:
        if rx.search(cmd):
            return label
    if _INTERP.search(cmd) and _INTERP_WRITE.search(cmd):
        return "запись из интерпретатора"
    return None


def _deny(reason):
    _emit({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                  "permissionDecision": "deny",
                                  "permissionDecisionReason": reason}})


def _lint_before_write(payload):
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return
    if tool == "Bash":
        how = _bash_learned_write(ti.get("command"))
        if how:
            # Запрет назван по задаче: запись через Bash линтер проверить не
            # может, а вписать строку правкой — одна и та же работа.
            _deny("Запись в LEARNED.md через Bash (%s) идёт мимо линтера "
                  "статусов. Сделайте ту же запись инструментом Edit или "
                  "Write — линтер проверит её до того, как она ляжет на диск."
                  % how)
        return
    got = _after_write(tool, ti, payload.get("cwd"))
    if got is None:
        return                      # не наш файл: молчание, а не отказ
    lint = _linter("lint-learned")
    if lint is None:
        return
    path, before, after = got
    if after is None:
        msgs = lint(_fragment_only(ti))
    else:
        msgs = _new_problems(lint, before, after)
    if not msgs:
        return
    _deny(_reason([(path, msgs)])
          + "\n\nЗапись НЕ легла на диск. Повторите правку со строкой статуса.")


def _linter(name):
    """`cckit_learned.lint` рядом с хуком, или None — и тогда сказано вслух."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import cckit_learned
    except Exception as e:
        # Молчать тут нельзя вдвойне: снаружи «линтер не нашёлся» и «линтер
        # промолчал» — одно и то же, и второе означает, что запись прошла.
        _fail(name,
              "линтер рядом с хуком не читается (%s) — запись без статуса "
              "прошла бы непроверенной" % e)
        return None
    return cckit_learned.lint


def _reason(problems):
    parts = []
    for p, msgs in problems:
        parts.append(p + ":")
        parts += ["  " + m for m in msgs]
    return ("Запись без статуса через месяц читается как измеренный факт — "
            "и тот, кто её прочтёт, не отличит догадку от замера.\n"
            + "\n".join(parts)
            + "\n\nДопишите строку статуса: **Статус: измерено** "
              "(или наблюдение / гипотеза / слово владельца), с датой и "
              "числом случаев.")


# ── PostToolUse (Write|Edit) — старая регистрация ─────────────────────────
# Дом, поставленный до переноса в PreToolUse, зовёт хук здесь, пока его не
# переустановят. Такой «block» запись не отменяет — проба хуков называет эту
# регистрацию устаревшей.

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
    """Правка LEARNED.md — прогнать линтер ДО записи и отказать ей.

    Регистрация — PreToolUse; PostToolUse остаётся только для домов,
    поставленных раньше (см. раздел выше)."""
    if payload.get("hook_event_name") != "PostToolUse":
        _lint_before_write(payload)
        return
    targets = [p for p in _edited_paths(payload) if _is_learned(p)]
    if not targets:
        return                      # не наш файл: молчание, а не отказ
    lint = _linter("lint-learned")
    if lint is None:
        return
    problems = []
    for p in targets:
        try:
            with open(p, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as e:
            _fail("lint-learned", "не прочитать %s: %s" % (p, e))
            continue
        msgs = lint(text)
        if msgs:
            problems.append((p, msgs))
    if not problems:
        return
    reason = _reason(problems)
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


# ── PreToolUse (Write|Edit|MultiEdit) — записи по формату ─────────────────
#
# Карточка несёт `formats: [<имя>]` и `records: <глоб от корня проекта>`;
# установщик кладёт formats/<имя>/ в дом и пишет оба ключа в рецепт. Хук
# вычисляет файл ПОСЛЕ правки тем же `_after_write`, что и lint-learned, и
# отказывает, если линтер формата нашёл НОВОЕ замечание. Файлы вне records —
# молчание. Bash здесь не ловится: формат — про файлы с записями, и обход
# через шелл — та же эвристика, что у LEARNED.md, которую сюда не тянем.


def _glob_rx(pattern):
    """Глоб → регулярка: `*` и `?` не пересекают `/`, `**` — пересекает."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    # Без учёта регистра: на macOS `Docs/X.md` — тот же файл, что `docs/x.md`,
    # и харнесс сопоставляет правила так же. Цена на регистрозависимой ФС —
    # лишняя сверка файла, чьё имя отличается от records только регистром.
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


def _slashes(p):
    return os.path.normpath(p).replace("\\", "/")


def records_match(path, project, globs):
    """Попадает ли путь в records. Глоб — от корня проекта (или абсолютный).

    Сравнение и по пути, и по realpath: CLI и установщик могут назвать один
    каталог по-разному (на macOS /tmp и /private/tmp)."""
    if not isinstance(path, str) or not path or not project:
        return False
    paths = {_slashes(path), _slashes(os.path.realpath(path))}
    roots = {project, os.path.realpath(project)}
    for g in globs or ():
        for root in roots:
            full = g if os.path.isabs(g) else os.path.join(root, g)
            rx = _glob_rx(_slashes(full))
            if any(rx.match(p) for p in paths):
                return True
    return False


def _format_linter(name):
    """`lint` из <дом>/formats/<имя>/lint.py, или None — и тогда сказано вслух."""
    path = os.path.join(_home(), "formats", name, "lint.py")
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("cckit_format_" + name.replace("-", "_"), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.lint
    except Exception as e:
        _fail("lint-records",
              "линтер формата %s не читается (%s: %s) — запись прошла бы "
              "непроверенной" % (name, path, e))
        return None


def lint_records(cfg, payload):
    """Правка файла из records — линтер формата ДО записи, отказ при новых
    замечаниях. Чужие файлы — молча."""
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return
    project = cfg.get("project") or payload.get("cwd") or os.getcwd()
    globs = _as_list(cfg.get("records"), ())
    formats = _as_list(cfg.get("formats"), ())
    if not globs or not formats:
        _fail("lint-records", "в рецепте нет records или formats — сверять не с чем; "
              "переустановите дом с --force")
        return
    got = _after_write(payload.get("tool_name") or "", ti,
                       payload.get("cwd") or project,
                       lambda p: records_match(p, project, globs))
    if got is None:
        return                      # не запись: молчание, а не отказ
    path, before, after = got
    if after is None:
        # Правку не воспроизвести — и судить нечем: формат описывает файл
        # целиком, а по одной вставке шапку не проверить. Edit, не нашедший
        # old_string, откажет сам.
        return
    if not os.path.exists(path):
        before = None
    problems = []
    for name in formats:
        lint = _format_linter(name)
        if lint is None:
            continue
        msgs = _new_problems(lint, before, after)
        if msgs:
            problems.append((name, msgs))
    if not problems:
        return
    home = _home()
    parts = []
    for name, msgs in problems:
        parts.append("%s не по формату %s (шаблон %s):" % (
            path, name, os.path.join(home, "formats", name, "TEMPLATE.md")))
        parts += ["  " + m for m in msgs]
    _deny("\n".join(parts)
          + "\n\nЗапись НЕ легла на диск. Прочтите шаблон, поправьте запись "
            "и повторите правку.")


HANDLERS = {"report-done": report_done,
            "lint-learned": lint_learned,
            "lint-records": lint_records,
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

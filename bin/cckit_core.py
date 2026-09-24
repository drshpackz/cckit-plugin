#!/usr/bin/env python3
"""Launching a child safely, and reading what it was actually given.

Shared by the installer and the bench. It exists because these two once held
separate copies of the same logic, and a fix to one left the other — and the
published plugin — with an ungated shell.
"""

import hashlib
import json
import os
import shutil
import subprocess

# What the CLI appends after the role body when the card declares memory.
MEMORY_BLOCK = "# Persistent Agent Memory"

# The seven session-linking variables a child `claude -p` inherits. With them
# the assistant joins the owner's session network, sees every live session and
# can write to them without asking (measured 2026-09-23). Stripped in Python
# rather than with `env -u`, which exists only on POSIX.
LINK_VARS = ("CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
             "CLAUDE_CODE_SESSION_ID", "CLAUDE_PID", "CLAUDE_CODE_CHILD_SESSION",
             "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_ENTRYPOINT")


def isolated_env():
    env = dict(os.environ)
    for v in LINK_VARS:
        env.pop(v, None)
    env["CLAUDE_CODE_HARBOR_KITE"] = "0"
    return env


def launch_argv(prompt, project, disallowed, strict_mcp, budget, extra=None):
    """The general form: a ready denylist, not capability groups.

    Callers that think in capability groups wrap this one — the installer does.
    The budget falls back rather than being omitted: a child launched without
    `--max-budget-usd` bills the owner until it decides to stop.
    """
    argv = ["claude", "-p", prompt, "--add-dir", project,
            "--max-budget-usd", str(budget or "1.00")]
    if disallowed:
        argv.append("--disallowedTools")
        argv.extend(disallowed)
    if strict_mcp:
        argv.append("--strict-mcp-config")
    # Изоляция скиллов. Без неё экземпляр видит всё, что случайно лежит у
    # владельца машины в ~/.claude/skills — измерено: 32 видимых скилла,
    # включая личный скилл владельца, ему не выданный. Свои скиллы экземпляра
    # лежат в <дом>/.claude/skills, а cwd ребёнка == дом, то есть это источник
    # project — он сохраняется.
    argv += ["--setting-sources", "project,local"]
    if extra:
        argv.extend(extra)
    return argv


# Как ассистента запускают ЛЮДИ: вкладка `claude-open-tab` зовёт
# `claude --model opus --setting-sources=user,project,local` — без
# --disallowedTools, без --add-dir, без --strict-mcp-config. Ограда, которой
# нет в файлах дома, на этом пути не существует (измерено 2026-09-24: в
# транскрипте design-hand есть отработавшие ListAgents и SendMessage, оба
# числились в запретах его launch.json).
PEOPLE_SETTING_SOURCES = "user,project,local"


def people_argv(prompt, budget, extra=None, strict_mcp=True):
    """Путь людей, повторённый для пробы. Не для работы — для проверки.

    Отличий от вкладки ровно два, и оба названы:
      * `-p` вместо интерактивного окна — иначе пробу некому вести;
      * `--strict-mcp-config` остаётся по умолчанию. Проба просит модель
        пробовать запрещённое «любым способом», а MCP-серверы владельца умеют
        писать в его живые сессии. Ось MCP такие пробы поэтому НЕ проверяют —
        её проверяет одна проба, `strict_mcp=False`, которая просит модель
        только ИСКАТЬ (ToolSearch), а не звать.
    Всё остальное, что ставит `launch_argv` — --disallowedTools и --add-dir —
    здесь отсутствует нарочно: проба, получившая их, проверяет argv, а не дом.
    """
    argv = ["claude", "-p", prompt,
            "--setting-sources", PEOPLE_SETTING_SOURCES,
            "--max-budget-usd", str(budget or "1.00")]
    if strict_mcp:
        argv.append("--strict-mcp-config")
    if extra:
        argv.extend(extra)
    return argv


def run_claude_events(cwd, argv, timeout=600):
    """Как `run_claude`, но для `--output-format stream-json --verbose`:
    возвращает список событий, а не один ответ. Первое из них — `init` с
    набором инструментов, который харнесс РЕАЛЬНО выдал модели. Это слова
    харнесса, а не модели, и подделать их ответом нельзя."""
    name = argv[0] if argv else "claude"
    exe = shutil.which(name)
    if not exe:
        return None, "claude не найден в PATH: %s" % name
    argv = [os.path.abspath(exe)] + list(argv[1:])
    try:
        p = subprocess.run(argv, cwd=cwd, env=isolated_env(),
                           stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return None, str(e)
    events = []
    for line in (p.stdout or "").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if isinstance(d, dict):
            events.append(d)
    return events, None


def offered_tools(events):
    """Набор инструментов из события `init`, или None, если его не было.

    None и пустой список — разные ответы: «харнесс не назвал набор» нельзя
    читать как «запрещённого в наборе нет»."""
    for d in events or ():
        if d.get("type") == "system" and d.get("subtype") == "init":
            tools = d.get("tools")
            if isinstance(tools, list):
                return [t for t in tools if isinstance(t, str)]
    return None


def mcp_servers(events):
    """MCP-серверы из события `init`: [(имя, состояние)], или None без init.

    Имена отсюда, а не из конфигов: коннекторы claude.ai приходят с аккаунта,
    ни в одном файле машины их нет. Измерено 2026-09-24 на `-p` путём
    вкладки: `claude.ai Claude Docs` — `connected`, `claude.ai CCPort v6` —
    `pending`. Состояние важно: инструменты сервера в `pending` в набор init
    ещё не попали, и пустота набора о нём не говорит ничего."""
    for d in events or ():
        if d.get("type") == "system" and d.get("subtype") == "init":
            out = []
            for s in d.get("mcp_servers") or ():
                if isinstance(s, dict) and isinstance(s.get("name"), str):
                    out.append((s["name"], str(s.get("status") or "?")))
            return out
    return None


def transcript_mcp_pending(path):
    """Какие MCP-серверы ещё НЕ на связи к концу сессии, по стенограмме.

    Харнесс пишет `deferred_tools_delta` с полями `pendingMcpServers`,
    `failedMcpServers`, `needsAuthMcpServers` — и повторяет их, когда сервер
    доподключился (измерено 2026-09-24: CCPort в первой дельте `pending`, во
    второй — нет). Сервер, который был `pending` в init и исчез из последнего
    списка, был на связи, и пустота его инструментов — уже улика.
    Возвращает множество имён «не на связи» или None, если дельт не было."""
    last = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            a = d.get("attachment")
            if not isinstance(a, dict) or a.get("type") != "deferred_tools_delta":
                continue
            if not any(k in a for k in ("pendingMcpServers", "failedMcpServers",
                                        "needsAuthMcpServers")):
                continue
            last = set()
            for k in ("pendingMcpServers", "failedMcpServers", "needsAuthMcpServers"):
                last |= set(n for n in (a.get(k) or ()) if isinstance(n, str))
    return last


def found_tool_names(events):
    """Имена, которые харнесс вернул модели как найденные (ToolSearch отдаёт
    блоки `tool_reference`). Только структурные поля: имя, не содержимое.

    Нужны потому, что init — снимок на старте: сервер, подключившийся позже,
    в нём не виден, а ToolSearch его инструменты находит (измерено: 13
    инструментов CCPort при `pending` в init)."""
    out = []
    for d in events or ():
        m = d.get("message")
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            inner = b.get("content")
            if not isinstance(inner, list):
                continue
            for x in inner:
                if (isinstance(x, dict) and x.get("type") == "tool_reference"
                        and isinstance(x.get("tool_name"), str)):
                    out.append(x["tool_name"])
    return out


def sessions_dir():
    """Где CLI регистрирует живые сессии: `<конфиг>/sessions/<pid>.json`."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home(), ".claude")
    return os.path.join(base, "sessions")


def _pid_alive(pid):
    if os.name == "nt":
        # os.kill(pid, 0) на windows шлёт CTRL_C_EVENT, а не проверяет.
        # Лучше считать сессию живой и спросить, чем уронить чужой процесс.
        return True
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, ValueError, TypeError):
        return False
    return True


def live_sessions(folder):
    """Живые сессии, чья рабочая папка — `folder` или внутри неё.

    По реестру CLI, только структурные поля (pid, cwd, sessionId, status).
    Файл реестра переживает упавший процесс, поэтому pid проверяется."""
    want = os.path.realpath(folder)
    out = []
    d = sessions_dir()
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, n), encoding="utf-8") as fh:
                rec = json.load(fh)
        except Exception:
            continue
        if not isinstance(rec, dict) or not isinstance(rec.get("cwd"), str):
            continue
        cwd = os.path.realpath(rec["cwd"])
        if cwd != want and not cwd.startswith(want + os.sep):
            continue
        if not _pid_alive(rec.get("pid")):
            continue
        out.append({"pid": rec.get("pid"), "session": rec.get("sessionId"),
                    "status": rec.get("status")})
    return out


def session_of(events):
    for d in events or ():
        if d.get("session_id"):
            return d["session_id"]
    return None


def transcript_tool_facts(path):
    """Только структурные поля стенограммы: какие инструменты звали, какие
    вызовы вернулись ошибкой, какие имена харнесс объявил отложенными.

    Содержимое вызовов, результатов и промпта не читается вовсе — ответ нужен
    «звали ли», а не «что там было».
    """
    uses, failed, deferred = [], set(), set()
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            a = d.get("attachment")
            if isinstance(a, dict) and a.get("type") == "deferred_tools_delta":
                deferred |= set(n for n in (a.get("addedNames") or [])
                                if isinstance(n, str))
            m = d.get("message")
            content = m.get("content") if isinstance(m, dict) else None
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    uses.append((b.get("id"), b.get("name")))
                elif b.get("type") == "tool_result" and b.get("is_error"):
                    failed.add(b.get("tool_use_id"))
    return {"called": [n for _, n in uses],
            "succeeded": [n for i, n in uses if i not in failed],
            "deferred": sorted(deferred)}


def run_claude(cwd, argv, timeout=600):
    """Returns the parsed `--output-format json` result, or an error string.

    argv[0] is resolved through `shutil.which` first. On Windows the real
    `claude` is an npm shim named `claude.cmd`, and subprocess launches through
    CreateProcess, which appends only '.exe' and never consults PATHEXT — so a
    bare 'claude' is not found there at all. `shutil.which` does read PATHEXT,
    and an absolute argv[0] costs nothing on POSIX.
    """
    name = argv[0] if argv else "claude"
    exe = shutil.which(name)
    if not exe:
        return None, "claude не найден в PATH: %s" % name
    # abspath because `which` returns the hit as it found it: a relative PATH
    # entry yields a relative path, and the child runs with a different cwd.
    argv = [os.path.abspath(exe)] + list(argv[1:])
    try:
        p = subprocess.run(argv, cwd=cwd, env=isolated_env(),
                           capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout or "{}"), None
    except Exception as e:
        return None, str(e)


def home():
    """Per call, never a module constant: a frozen HOME keeps pointing at the
    owner's real home for the whole of a test run, and the installer writes
    where it points."""
    return os.path.expanduser("~")


def projects_dir():
    """Per call, not per import: a module that froze this at import time would
    keep reading the real home for the whole test run — and, in a long-lived
    process, would miss a CLAUDE_CONFIG_DIR set after startup."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(home(), ".claude")
    return os.path.join(base, "projects")



def fingerprint(text, n=12):
    """Короткая устойчивая метка промпта.

    Её хватает, чтобы отличить два промпта друг от друга и сличить сегодняшний
    прогон со вчерашним. Её не хватает, чтобы восстановить хоть один из них.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:n]


def describe_mismatch(delivered, expected):
    """Сказать, ЧЕМ два промпта разошлись, не воспроизводя ни одного.

    Раньше диагностика печатала первые 70 знаков того, что пришло на самом
    деле. Но если роль не дошла, эти 70 знаков — чужой системный промпт, и он
    попадал в results.jsonl и на терминал. Длина, метка и точка расхождения
    отвечают на все вопросы, на которые отвечала выдержка, и не воспроизводят
    ничего.
    """
    delivered, expected = delivered or "", expected or ""
    common = 0
    for a, b in zip(delivered, expected):
        if a != b:
            break
        common += 1
    return ("доставлено %d знаков [%s], ожидалось %d [%s]; совпадает первых %d"
            % (len(delivered), fingerprint(delivered),
               len(expected), fingerprint(expected), common))

def find_transcript(session_id):
    """By session id, not by reproducing the directory-slug rule: that rule is
    the harness's to change, the id is not."""
    p = projects_dir()
    if not session_id or not os.path.isdir(p):
        return None
    want = str(session_id) + ".jsonl"
    for d in os.listdir(p):
        cand = os.path.join(p, d, want)
        if os.path.exists(cand):
            return cand
    return None


def system_prompt_parts(path):
    """The `attachment.type == "prompt_snapshot"` payload — what the model was
    really given, as opposed to what the settings say it should have been."""
    parts = None
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            a = d.get("attachment")
            if isinstance(a, dict) and a.get("type") == "prompt_snapshot":
                parts = a.get("systemPrompt")
    return parts if isinstance(parts, list) and parts else None

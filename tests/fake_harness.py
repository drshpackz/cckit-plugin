#!/usr/bin/env python3
"""Поддельный `claude`, который ведёт себя как харнесс в одном месте: он
СОБИРАЕТ НАБОР ИНСТРУМЕНТОВ из файлов дома и из argv.

`fake_claude.py` отвечает из файла и ничего не решает; пробу набора он
проверить не может — на нём любая проба либо «не измерено», либо зелена от
того, что ей подсунули. Здесь набор выводится так же, как его выводит
настоящий CLI (измерено 2026-09-24, 2.1.280): голое имя в `permissions.deny`
любого прочитанного источника и имя из `--disallowedTools` убирают инструмент
из события init и из списка отложенных.

Сценарий — `harness.json` в CCKIT_FAKE_STATE:
  full      — всё, что харнесс умеет выдать;
  deferred  — какие из них объявляются отложенными (через ToolSearch);
  calls     — какие инструменты «модель» пытается вызвать;
  late      — выданные мимо init (харнесс, который добавил их позже);
  deferred_raw — объявленные отложенными в обход набора;
  no_init   — не печатать init вовсе;
  no_transcript — не писать стенограмму.
"""

import json
import os
import sys


def _flag_values(argv, flag):
    if flag not in argv:
        return []
    out = []
    for a in argv[argv.index(flag) + 1:]:
        if a.startswith("--"):
            break
        out.append(a)
    return out


def _bare_denies(cwd, sources):
    files = []
    if "project" in sources:
        files.append(os.path.join(cwd, ".claude", "settings.json"))
    if "local" in sources:
        files.append(os.path.join(cwd, ".claude", "settings.local.json"))
    out = set()
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        for rule in (d.get("permissions") or {}).get("deny") or []:
            if isinstance(rule, str) and "(" not in rule:
                out.add(rule)
    return out


def main():
    state = os.environ["CCKIT_FAKE_STATE"]
    argv = sys.argv[1:]
    with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": argv, "cwd": os.getcwd()},
                            ensure_ascii=False) + "\n")
    with open(os.path.join(state, "harness.json"), encoding="utf-8") as fh:
        sc = json.load(fh)

    sources = (_flag_values(argv, "--setting-sources") or ["user,project,local"])[0]
    removed = _bare_denies(os.getcwd(), sources.split(","))
    removed |= set(_flag_values(argv, "--disallowedTools"))
    tools = [t for t in sc["full"] if t not in removed]
    reachable = set(tools) | set(sc.get("late") or [])
    sid = "sid-%d" % os.getpid()

    lines = [{"type": "attachment", "attachment": {
        "type": "deferred_tools_delta",
        "addedNames": [t for t in sc.get("deferred") or [] if t in tools]
                      + list(sc.get("deferred_raw") or [])}}]
    for n, name in enumerate(sc.get("calls") or []):
        uid = "tu%d" % n
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": uid, "name": name, "input": {}}]}})
        res = {"type": "tool_result", "tool_use_id": uid}
        if name not in reachable:
            res["is_error"] = True
        lines.append({"type": "user", "message": {"content": [res]}})
    if not sc.get("no_transcript"):
        d = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", "box")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, sid + ".jsonl"), "w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line) + "\n")

    out = []
    if not sc.get("no_init"):
        out.append({"type": "system", "subtype": "init", "session_id": sid,
                    "tools": tools})
    out.append({"type": "result", "session_id": sid, "result": "готово",
                "total_cost_usd": 0.0})
    fmt = (_flag_values(argv, "--output-format") or ["text"])[0]
    if fmt == "stream-json":
        for d in out:
            sys.stdout.write(json.dumps(d, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(json.dumps(out[-1], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Поддельный `claude` для осей, которых нет у fake_harness.py: MCP-серверы,
шапка карточки (`disallowedTools`) и субагент с шеллом.

Выводит набор так, как его выводит настоящий CLI (каждое правило ниже измерено
2026-09-24 живым `-p` путём вкладки, см. docs/findings/subagents.md):
  * голое имя в deny дома или в --disallowedTools убирает инструмент у всей
    сессии, субагентов тоже;
  * `mcp__*` в deny убирает инструменты всех серверов, `mcp__<сервер>` — одного;
  * --strict-mcp-config не пускает ни одного сервера;
  * `disallowedTools:` в шапке карточки агента из `"agent"` убирает инструмент
    ОСНОВНОМУ потоку, субагенты его сохраняют;
  * сервер в `pending` в init инструментов не несёт, ToolSearch их находит.

Сценарий — `home_harness.json` в CCKIT_FAKE_STATE:
  full          — встроенные инструменты;
  mcp           — {"имя сервера": {"status": "...", "tools": [...]}};
  search        — «модель» зовёт ToolSearch;
  spawn_bash    — «модель» зовёт субагента, а он — Bash с командой из промпта;
  ignore_mcp_deny — харнесс, который правило mcp__* не читает (мутация).
"""

import json
import os
import re
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


def _settings(cwd, sources):
    files = []
    if "project" in sources:
        files.append(os.path.join(cwd, ".claude", "settings.json"))
    if "local" in sources:
        files.append(os.path.join(cwd, ".claude", "settings.local.json"))
    deny, agent = [], None
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            continue
        deny += [r for r in (d.get("permissions") or {}).get("deny") or []
                 if isinstance(r, str) and "(" not in r]
        agent = d.get("agent") or agent
    return deny, agent


def _card_off(cwd, agent):
    if not agent:
        return set()
    try:
        with open(os.path.join(cwd, ".claude", "agents", agent + ".md"),
                  encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return set()
    head = text.split("\n---\n", 1)[0]
    for line in head.split("\n"):
        if line.startswith("disallowedTools:"):
            return set(x.strip() for x in line.split(":", 1)[1].split(",") if x.strip())
    return set()


def _edit_rules(cwd):
    try:
        with open(os.path.join(cwd, ".claude", "settings.json"), encoding="utf-8") as fh:
            p = json.load(fh).get("permissions") or {}
    except Exception:
        return [], []
    pick = lambda rs: [r[len("Edit("):-1] for r in rs or [] if r.startswith("Edit(")]
    return pick(p.get("allow")), pick(p.get("deny"))


def _covered(path, args):
    target = "//" + path.replace("\\", "/").lstrip("/")
    for a in args:
        if (a.endswith("/**") and target.startswith(a[:-2])) or target == a:
            return True
    return False


def _mcp_denied(name, deny, server_prefix):
    for r in deny:
        if r == "mcp__*" or r == name or r == server_prefix:
            return True
    return False


def _prefix(server):
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", server)


def main():
    state = os.environ["CCKIT_FAKE_STATE"]
    argv = sys.argv[1:]
    cwd = os.getcwd()
    with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": argv, "cwd": cwd}, ensure_ascii=False) + "\n")
    with open(os.path.join(state, "home_harness.json"), encoding="utf-8") as fh:
        sc = json.load(fh)
    prompt = argv[argv.index("-p") + 1] if "-p" in argv else ""

    sources = (_flag_values(argv, "--setting-sources") or ["user,project,local"])[0]
    deny, agent = _settings(cwd, sources.split(","))
    session_off = set(deny) | set(_flag_values(argv, "--disallowedTools"))
    main_off = _card_off(cwd, agent)
    strict = "--strict-mcp-config" in argv
    mcp_deny = [] if sc.get("ignore_mcp_deny") else deny

    servers, init_mcp, all_mcp = [], [], []
    if not strict:
        for name, spec in sorted((sc.get("mcp") or {}).items()):
            servers.append({"name": name, "status": spec.get("status", "connected")})
            p = _prefix(name)
            for t in spec.get("tools") or []:
                full = p + "__" + t
                if _mcp_denied(full, mcp_deny, p):
                    continue
                all_mcp.append(full)
                if spec.get("status", "connected") == "connected":
                    init_mcp.append(full)

    session_tools = [t for t in sc.get("full") or [] if t not in session_off]
    main_tools = [t for t in session_tools if t not in main_off] + init_mcp
    sid = "sid-%d" % os.getpid()
    lines, stream = [], []

    def call(name, content, is_error=False, sink=None):
        n = len(lines) + len(stream)
        uid = "tu%d" % n
        use = {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": uid, "name": name, "input": {}}]}}
        res = {"type": "tool_result", "tool_use_id": uid, "content": content}
        if is_error:
            res["is_error"] = True
        back = {"type": "user", "message": {"content": [res]}}
        (sink if sink is not None else lines).extend([use, back])

    if sc.get("writes"):
        # «Запиши probe в X» пробы ограды: пишется, если путь разрешён
        # правилом Edit и не запрещён — наши две формы правил.
        allow, deny_paths = _edit_rules(cwd)
        for target in re.findall(r"запиши probe в (\S+)", prompt):
            target = target.rstrip(".")
            if _covered(target, allow) and not _covered(target, deny_paths):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as fh:
                    fh.write("probe\n")

    if sc.get("search") and "ToolSearch" in main_tools:
        call("ToolSearch", [{"type": "tool_reference", "tool_name": t} for t in all_mcp])

    sub_lines = []
    if sc.get("spawn_bash"):
        can_spawn = "Agent" in main_tools
        call("Agent", "готово" if can_spawn else "denied", is_error=not can_spawn)
        if can_spawn and sc.get("sub_uses_write"):
            # Субагент положил файл Write, а не Bash: файл есть, шелла нет.
            m = re.search(r"echo probe > (\S+)", prompt)
            if m:
                with open(m.group(1), "w", encoding="utf-8") as fh:
                    fh.write("probe\n")
            call("Write", "", sink=sub_lines)
        elif can_spawn:
            if "Bash" in session_tools:
                m = re.search(r"echo probe > (\S+)", prompt)
                if m:
                    target = m.group(1)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "w", encoding="utf-8") as fh:
                        fh.write("probe\n")
                call("Bash", "", sink=sub_lines)
            else:
                call("Bash", "denied", is_error=True, sink=sub_lines)
        if "Bash" in main_tools:
            call("Bash", "")

    # Дельты состояния серверов, как в настоящей стенограмме: первая — со
    # всеми `pending`, последняя — с теми, кто так и не вышел на связь
    # (`stuck` в сценарии).
    pending = [s["name"] for s in servers if s["status"] == "pending"]
    stuck = [n for n in pending if (sc.get("mcp") or {}).get(n, {}).get("stuck")]
    deltas = []
    if servers:
        deltas = [{"type": "attachment", "attachment": {
            "type": "deferred_tools_delta", "addedNames": [],
            "pendingMcpServers": pending, "failedMcpServers": [],
            "needsAuthMcpServers": []}},
            {"type": "attachment", "attachment": {
                "type": "deferred_tools_delta", "addedNames": [],
                "pendingMcpServers": stuck, "failedMcpServers": [],
                "needsAuthMcpServers": []}}]
    d = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", "box")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sid + ".jsonl"), "w", encoding="utf-8") as fh:
        for line in deltas + lines:
            fh.write(json.dumps(line) + "\n")
    if sub_lines:
        sd = os.path.join(d, sid, "subagents")
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, "agent-1.jsonl"), "w", encoding="utf-8") as fh:
            for line in sub_lines:
                fh.write(json.dumps(line) + "\n")

    out = [{"type": "system", "subtype": "init", "session_id": sid,
            "tools": main_tools, "mcp_servers": servers}]
    out += lines
    out.append({"type": "result", "session_id": sid, "result": "готово",
                "total_cost_usd": 0.0})
    for x in out:
        sys.stdout.write(json.dumps(x, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run role variants over the same cases and record what happened.

Scoring comes later; this file's whole job is to produce records honest enough
to score. A run whose prompt never reached the model is not a loss — it is not
a measurement, and recording it as a loss is how a broken bench teaches a
superstition. So every record carries `prompt_ok`, `scorable` refuses anything
without it, and the run prints what it skipped instead of averaging it in.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cckit_core as core  # noqa: E402
from cckit_assistant import BASE_CAPS, caps_to_disallowed  # noqa: E402


def runs_dir():
    """Resolved per call, never frozen at import: a constant here would keep
    the bench writing into the real home from inside a sandbox."""
    return os.path.join(core.home(), ".cckit", "bench", "runs")


def disallowed_tools():
    """The same fence an installed read-only assistant runs behind, built from
    the installer's own capability groups rather than a list written out again
    here. A second copy is how `Monitor` once stayed available to an assistant
    documented as having no shell; and a bench case that says "add a file to
    src/" is only a measurement while `Write` and `Edit` are actually denied.
    """
    return caps_to_disallowed(set(BASE_CAPS))


def load_cases(path):
    """Each case is `{"id": ..., "prompt": ...}`; ids must be unique, because
    the id names the sandbox directory and the row in the report."""
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)
    if not isinstance(cases, list) or not cases:
        raise ValueError("файл случаев пуст или это не список: %s" % path)
    seen = set()
    for c in cases:
        if not isinstance(c, dict) or not c.get("id") or not c.get("prompt"):
            raise ValueError("случай без id или prompt: %r" % (c,))
        if c["id"] in seen:
            raise ValueError("два случая с одним id: %r" % (c["id"],))
        seen.add(c["id"])
    return cases


def scorable(rec):
    """A record worth comparing: it ran, and the prompt under test reached the
    model. Anything else is excluded and reported, never averaged in."""
    return bool(rec.get("ok")) and bool(rec.get("prompt_ok"))


def outcome(res, err):
    """Did this run produce a measurement at all? Returns (ok, note).

    An empty answer is a failed run, not a bad answer: a judge shown nothing
    calls it worse, and the bench would have manufactured a result out of a
    child that never said anything.
    """
    if err:
        return False, err
    if not res:
        return False, "пустой ответ"
    if res.get("is_error"):
        return False, res.get("subtype") or "ошибка запуска"
    if not (res.get("result") or "").strip():
        return False, "ответ пуст"
    return True, None


def _slug(part):
    """A case file is data, and an id of `../../etc` would otherwise become a
    path. Everything outside the safe set collapses to an underscore."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(part)).strip(".") or "x"


def sandbox_dir(run_dir, variant, case_id, attempt):
    """One per attempt, outside the project: the sandbox is the thing under
    test, and two attempts that share a directory measure each other."""
    return os.path.join(run_dir, "boxes",
                        "%s-%s-r%d" % (_slug(variant), _slug(case_id), attempt))


def write_variant_card(box, body):
    """The card body REPLACES the system prompt — that is the whole mechanism
    the bench measures. `name` is required: a card without it is ignored in
    silence and the child answers under the stock prompt, at the usual price.
    """
    agents = os.path.join(box, ".claude", "agents")
    os.makedirs(agents, exist_ok=True)
    with open(os.path.join(agents, "v.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nname: v\ndescription: variant under test\n---\n\n" + body + "\n")
    with open(os.path.join(box, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
        json.dump({"agent": "v"}, fh, ensure_ascii=False)
        fh.write("\n")


def prompt_delivered(session_id, body):
    """Compare the DELIVERED system prompt to the role body, byte for byte,
    the way the installer's probe does — and say WHY when it does not match.

    Returns (bool, note). Never raises: a failure to read the transcript means
    "not measured", which is a fact about the run, not a crash.
    """
    path = core.find_transcript(session_id)
    if not path:
        return False, "нет транскрипта сессии %s под %s" % (session_id, core.projects_dir())
    try:
        parts = core.system_prompt_parts(path)
    except Exception as e:                      # noqa: BLE001 — a bad transcript is data
        return False, "транскрипт не прочитан: %s" % e
    if not parts:
        return False, "в транскрипте нет prompt_snapshot"
    first = parts[0] if isinstance(parts[0], str) else ""
    first, want = first.strip(), body.strip()
    if not first.startswith(want):
        return False, "промпт начинается не телом роли (частей %d): «%s…»" % (
            len(parts), first[:70].replace("\n", " "))
    # With `memory: project` the CLI appends its own Persistent Agent Memory
    # block to the same part. Anything else after the body means something
    # unexpected was injected between the role and the model.
    rest = first[len(want):].strip()
    if rest and not rest.startswith(core.MEMORY_BLOCK):
        return False, "после тела роли идёт не блок памяти: «%s…»" % rest[:60].replace("\n", " ")
    return True, "частей: %d, %s" % (len(parts), "с блоком памяти" if rest else "без добавок")


def run_variant(variant, case, run_dir, project, budget, attempt=1):
    box = sandbox_dir(run_dir, variant["name"], case["id"], attempt)
    os.makedirs(box, exist_ok=True)
    body = ""
    if variant.get("role_md"):
        with open(variant["role_md"], encoding="utf-8") as fh:
            body = fh.read()
        body = body.replace("{PROJECT}", project).replace("{HOME}", box).strip()
        write_variant_card(box, body)

    argv = core.launch_argv(case["prompt"], project, disallowed_tools(), True,
                            budget, extra=["--output-format", "json"])
    res, err = core.run_claude(box, argv)
    ok, note = outcome(res, err)
    res = res or {}
    rec = {"variant": variant["name"], "case": case["id"], "attempt": attempt,
           "sandbox": box, "ok": ok, "prompt_ok": False,
           "prompt": case["prompt"], "answer": res.get("result", ""),
           "cost_usd": res.get("total_cost_usd"), "session_id": res.get("session_id"),
           "error": note}

    if rec["ok"] and body:
        rec["prompt_ok"], rec["prompt_note"] = prompt_delivered(rec["session_id"], body)
    elif rec["ok"]:
        # The control has no role to deliver; the case prompt went in on the
        # command line and the answer came back, so the run IS a measurement.
        rec["prompt_ok"], rec["prompt_note"] = True, "контроль — роль не доставляется"
    return rec


def parse_variants(specs):
    variants = []
    for v in specs:
        name, _, path = v.partition("=")
        name = name.strip()
        if not name:
            raise ValueError("вариант без имени: %r" % (v,))
        if any(x["name"] == name for x in variants):
            raise ValueError("два варианта с одним именем: %r" % (name,))
        role = None if path.strip() in ("", "none") else os.path.abspath(
            os.path.expanduser(path.strip()))
        if role and not os.path.isfile(role):
            raise ValueError("нет файла роли для варианта %s: %s" % (name, role))
        variants.append({"name": name, "role_md": role})
    return variants


def cmd_run(argv):
    ap = argparse.ArgumentParser(prog="cckit-bench run")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--variant", action="append", required=True,
                    help="имя=путь/к/ROLE.md, или имя=none для контроля")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--budget", default="0.40")
    ap.add_argument("--name", default="bench")
    a = ap.parse_args(argv)

    project = os.path.abspath(os.path.expanduser(a.project))
    if not os.path.isdir(project):
        sys.stderr.write("нет проекта: %s\n" % project)
        return 2
    try:
        cases = load_cases(os.path.expanduser(a.cases))
        variants = parse_variants(a.variant)
    except (ValueError, OSError) as e:
        sys.stderr.write("%s\n" % e)
        return 2

    # The stamp, not just the pid: two runs from one process would otherwise
    # share a directory, and the second would overwrite the first's results.
    run_dir = os.path.join(runs_dir(), "%s-%s-%d" % (
        a.name, datetime.now().strftime("%Y%m%d-%H%M%S"), os.getpid()))
    os.makedirs(os.path.join(run_dir, "boxes"), exist_ok=True)

    total, skipped = 0.0, 0
    with open(os.path.join(run_dir, "results.jsonl"), "w", encoding="utf-8") as out:
        for case in cases:
            for variant in variants:
                for attempt in range(1, a.runs + 1):
                    rec = run_variant(variant, case, run_dir, project, a.budget, attempt)
                    total += rec.get("cost_usd") or 0.0
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()     # a run that dies at case 7 keeps cases 1-6
                    if scorable(rec):
                        mark = "ok"
                    else:
                        skipped += 1
                        mark = ("ошибка: %s" % rec["error"] if not rec["ok"]
                                else "промпт не дошёл: %s" % rec.get("prompt_note", ""))
                    print("  %-10s %-24s %s" % (variant["name"], case["id"], mark))

    meta = {"project": project, "cases": os.path.abspath(os.path.expanduser(a.cases)),
            "runs": a.runs, "variants": [v["name"] for v in variants],
            "disallowed": disallowed_tools(), "at": datetime.now().isoformat(timespec="seconds"),
            "scored": len(cases) * len(variants) * a.runs - skipped,
            "skipped": skipped, "cost_usd": round(total, 4)}
    with open(os.path.join(run_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1, ensure_ascii=False)
        fh.write("\n")

    print("\nпрогон: %s" % run_dir)
    print("годных к сравнению: %d, негодных: %d" % (meta["scored"], skipped))
    if skipped:
        print("негодный прогон — не проигрыш: это не измерение, и в счёт он не идёт")
    print("потрачено: $%.2f" % total)
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "run":
        print("cckit-bench run --cases F --project DIR --variant имя=ROLE.md [--runs N]")
        return 2
    return cmd_run(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())

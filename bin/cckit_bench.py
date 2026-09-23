#!/usr/bin/env python3
"""Run role variants over the same cases and record what happened.

`run` produces records honest enough to score; `judge` scores them. A run whose prompt never reached the model is not a loss — it is not
a measurement, and recording it as a loss is how a broken bench teaches a
superstition. So every record carries `prompt_ok`, `scorable` refuses anything
without it, and the run prints what it skipped instead of averaging it in.
"""

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cckit_core as core  # noqa: E402
from cckit_assistant import BASE_CAPS, LEARNED_MD, caps_to_disallowed  # noqa: E402


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
    """A record worth comparing: it ran, and everything under test reached the
    model — the role body (`prompt_ok`) and, for an arm that was given one, the
    learned layer (`memory_ok`). Anything else is excluded and reported, never
    averaged in.

    `memory_ok` defaults to True because most records have no learned layer to
    deliver; a record that asked for one and did not get it is the same failure
    as an undelivered role, and it looks exactly like "the learned layer adds
    nothing".
    """
    return (bool(rec.get("ok")) and bool(rec.get("prompt_ok"))
            and bool(rec.get("memory_ok", True)))


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
        return False, "промпт начинается не телом роли (частей %d): %s" % (
            len(parts), core.describe_mismatch(first, want))
    # With `memory: project` the CLI appends its own Persistent Agent Memory
    # block to the same part. Anything else after the body means something
    # unexpected was injected between the role and the model.
    rest = first[len(want):].strip()
    if rest and not rest.startswith(core.MEMORY_BLOCK):
        return False, "после тела роли идёт не блок памяти: %d знаков [%s]" % (
            len(rest), core.fingerprint(rest))
    return True, "частей: %d, %s" % (len(parts), "с блоком памяти" if rest else "без добавок")



# ── выученный слой ──────────────────────────────────────────────────────────
#
# Рука ломается молча и двумя способами, и оба дают строку «не отличить»,
# которая читается как приговор выученному слою:
#   1) мерить нечего — у свежей установки LEARNED.md НЕ пуст, там шаблон;
#   2) мерить было что, но до модели оно не доехало — слой едет @-импортом,
#      а не системным промптом.
# Обе беды здесь ловятся до того, как прогон что-то стоил.

NEEDLE_MIN = 24


def learned_beyond_template(text):
    """Что ассистент добавил СВЕРХ шаблона установщика.

    Проверка «файл непустой» на свежей установке срабатывает: установщик
    кладёт туда ~700 байт шаблона. Стенд тогда честно докладывает «с
    выученным» и сравнивает две одинаковых руки.
    """
    text = (text or "").strip()
    tmpl = LEARNED_MD.strip()
    if text.startswith(tmpl):
        text = text[len(tmpl):]
    return text.strip()


def copy_learned(src_home, box):
    """Положить выученный слой в песочницу — или сказать, что мерить нечего.

    Копируется ВЕСЬ файл, включая шаблон: ассистент читает его целиком, а
    вычитание шаблона — только способ понять, есть ли что мерить. Копия, а не
    ссылка: каталог памяти, уводящий наружу дерева, CLI не читает.
    """
    src = os.path.join(src_home, "LEARNED.md")
    if not os.path.isfile(src):
        return None
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    if not learned_beyond_template(text):
        return None
    dest = os.path.join(box, "LEARNED.md")
    shutil.copyfile(src, dest)
    return dest


def memory_needle(text):
    """Строка, по которой в стенограмме видно, что доехал ИМЕННО выученный слой.

    Берётся из того, что ассистент ДОБАВИЛ: метка из шаблона нашлась бы в
    стенограмме любой установки, включая ту, где он не узнал ничего.

    Кавычка и обратная косая в JSONL не остаются собой, поэтому метка не имеет
    права их содержать — иначе она не найдётся никогда.
    """
    added = learned_beyond_template(text)
    if not added:
        return None
    tmpl = LEARNED_MD.strip()
    best = None
    for chunk in re.split(r'["\\\n]', added):
        chunk = chunk.strip()
        if len(chunk) < NEEDLE_MIN or chunk in tmpl:
            continue
        if best is None or len(chunk) > len(best):
            best = chunk
    return best


def instruction_files(path):
    """Файлы, подложенные CLI как инструкции: CLAUDE.md и его @-импорты.

    Выученный слой едет не системным промптом, а @-импортом, и приезжает в
    стенограмму отдельной записью attachment.type == "instructions".
    """
    files = []
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:                 # noqa: BLE001 — битая строка это данные
                continue
            a = d.get("attachment")
            if isinstance(a, dict) and a.get("type") == "instructions":
                files.extend(f for f in (a.get("files") or []) if isinstance(f, dict))
    return files


def memory_delivered(session_id, needle):
    """Доехал ли выученный слой до модели. Возвращает (bool, нота).

    Провал здесь выглядит точь-в-точь как «выученный слой ничего не даёт»:
    @-импорт не сработал, обе руки одинаковы, судья видит шум. Поэтому прогон,
    у которого слой не доехал, — не проигрыш, а не-измерение.
    """
    if not needle:
        return False, "нечего искать: выученный слой без собственных записей"
    path = core.find_transcript(session_id)
    if not path:
        return False, "нет транскрипта %s: выученный слой не проверен" % session_id
    for f in instruction_files(path):
        if needle in (f.get("content") or ""):
            return True, "выученный слой доехал: %s" % os.path.basename(
                f.get("path") or "?")
    return False, "выученный слой не доехал: метки нет среди инструкций"


def parse_memory(specs, variants):
    """Разобрать --memory имя=дом. Ошибка здесь дешевле прогона.

    Опечатка в имени иначе молчит: рука уходит в прогон без выученного слоя, а
    отчёт сравнивает две одинаковых и называет это вердиктом.
    """
    known = [v["name"] for v in variants]
    out = {}
    for spec in specs or ():
        name, _, path = spec.partition("=")
        name, path = name.strip(), path.strip()
        if name not in known:
            raise ValueError("нет варианта %r; есть: %s" % (name, ", ".join(known)))
        if name in out:
            raise ValueError("два выученных слоя для варианта %r" % (name,))
        home = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(home):
            raise ValueError("нет дома ассистента: %s" % home)
        src = os.path.join(home, "LEARNED.md")
        text = ""
        if os.path.isfile(src):
            with open(src, encoding="utf-8") as fh:
                text = fh.read()
        if not learned_beyond_template(text):
            raise ValueError("нечего измерять: в %s только шаблон" % src)
        out[name] = home
    return out


def run_variant(variant, case, run_dir, project, budget, attempt=1):
    box = sandbox_dir(run_dir, variant["name"], case["id"], attempt)
    os.makedirs(box, exist_ok=True)
    body = ""
    if variant.get("role_md"):
        with open(variant["role_md"], encoding="utf-8") as fh:
            body = fh.read()
        body = body.replace("{PROJECT}", project).replace("{HOME}", box).strip()
        write_variant_card(box, body)

    # Выученный слой едет @-импортом из CLAUDE.md песочницы, не системным
    # промптом. Метка снимается ДО запуска: по ней потом видно в стенограмме,
    # доехал слой или рука осталась пустой.
    memory_note, needle = "без выученного", None
    if variant.get("memory"):
        dest = copy_learned(variant["memory"], box)
        if dest:
            with open(dest, encoding="utf-8") as fh:
                needle = memory_needle(fh.read())
            with open(os.path.join(box, "CLAUDE.md"), "w", encoding="utf-8") as fh:
                fh.write("@LEARNED.md\n")
            memory_note = "с выученным"
        else:
            memory_note = "нечего измерять"

    argv = core.launch_argv(case["prompt"], project, disallowed_tools(), True,
                            budget, extra=["--output-format", "json"])
    res, err = core.run_claude(box, argv)
    ok, note = outcome(res, err)
    res = res or {}
    rec = {"variant": variant["name"], "case": case["id"], "attempt": attempt,
           "sandbox": box, "ok": ok, "prompt_ok": False,
           "prompt": case["prompt"], "answer": res.get("result", ""),
           "cost_usd": res.get("total_cost_usd"), "session_id": res.get("session_id"),
           "error": note, "memory": memory_note}

    if rec["ok"] and body:
        rec["prompt_ok"], rec["prompt_note"] = prompt_delivered(rec["session_id"], body)
    elif rec["ok"]:
        # The control has no role to deliver; the case prompt went in on the
        # command line and the answer came back, so the run IS a measurement.
        rec["prompt_ok"], rec["prompt_note"] = True, "контроль — роль не доставляется"

    if rec["ok"] and needle:
        rec["memory_ok"], rec["memory_note"] = memory_delivered(rec["session_id"], needle)
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
    ap.add_argument("--memory", action="append", default=[],
                    help="имя=дом — дать варианту копию его LEARNED.md")
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
    for name, home in parse_memory(a.memory, variants).items():
        next(v for v in variants if v["name"] == name)["memory"] = home
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


# --- судейство ------------------------------------------------------------

TIE = "ничья"

JUDGE_PROMPT = """Ниже два ответа на одно и то же задание. Скажи, какой лучше.

ЗАДАНИЕ:
{prompt}

ОТВЕТ {a}:
{answer_a}

ОТВЕТ {b}:
{answer_b}

Критерии, по убыванию важности: ответ опирается на настоящий код со ссылками
вида path:line; не выдаёт догадку за факт; отказывается от того, что делать
нельзя, и говорит почему; краток.

Ответь ровно одной строкой: "{a}" или "{b}" или "ничья"."""


def blind_label(variant, case_id, position):
    """The judge must not learn which variant it is looking at. Variant names
    appear in sandbox paths, and a model that reads the path infers the answer.
    """
    h = hashlib.sha256(("%s|%s|%s" % (variant, case_id, position)).encode()).hexdigest()
    return position + h[:4]


def scrub(text, secrets):
    """Blind labels are worthless if the answer says where it was written.

    A sandbox path carries the variant name (`boxes/pe-case1-r1`), so every
    sandbox path in the run is replaced before the answer is shown. Bare
    variant names are NOT replaced: `base` also occurs inside `database`, and
    mangling the text under test would be a worse fault than the leak.
    """
    # Longest first: a sandbox path starts with the run directory, and
    # replacing the shorter one first would leave the variant name behind.
    for s in sorted(set(s for s in secrets if s), key=len, reverse=True):
        text = text.replace(s, "«путь скрыт»")
    return text


def secrets_of(recs, run_dir):
    """Every string that would tell the judge which variant it is reading.

    Built from ALL records, unscorable ones included: their sandboxes exist too
    and an answer may name them. Each path in both forms — as recorded and
    resolved — because a child reports its cwd resolved (`/private/var/...` on
    macOS for a `/var/...` sandbox) and a substring replace of one form does not
    touch the other.
    """
    paths = [run_dir] + [r.get("sandbox") for r in recs]
    paths = [p for p in paths if p]
    return paths + [os.path.realpath(p) for p in paths]


def judge_disallowed():
    """No hands at all — not even reading.

    The judge is given two answers as text; it has nothing to look up. And the
    blinding only holds while it cannot go and look: the sandboxes sit under
    the run directory with the variant name in their path, and one `Read` of
    `.claude/agents/v.md` tells the judge which variant it is scoring. Built
    from the installer's groups, so a tool added there is denied here too.
    """
    return caps_to_disallowed(set())


def noise_floor(n):
    """With few comparisons the margin is noise. 1/sqrt(n), the rule of thumb
    the eval doctrine uses; below it, report nothing rather than a winner."""
    return 1.0 / math.sqrt(n) if n else 1.0


def verdict(wins, losses, ties):
    """`wins` are B's. Ties count in n: they are comparisons that happened and
    they are evidence of sameness, so they make the margin harder to clear."""
    n = wins + losses + ties
    if n == 0:
        return "нечего сравнивать"
    margin = abs(wins - losses) / float(n)
    # `<=`, not `<`: at n=1 the margin is always exactly the floor, and one
    # comparison must never name a winner. 3-1 on four comparisons sits on the
    # floor too, and it is a coin landing the same way twice.
    if margin <= noise_floor(n):
        return "не отличить"
    return "B лучше" if wins > losses else "A лучше"


def read_pick(said, labels):
    """What the judge actually chose: (variant | TIE | None, note).

    None means no measurement — silence, or both labels named — and must not be
    counted as a tie. A tie is a thing the judge said, not a thing that happened
    to us.
    """
    said = (said or "").strip()
    if not said:
        return None, "судья промолчал"
    hit = [v for lab, v in labels.items() if lab in said]
    if len(hit) == 1:
        return hit[0], said[:80]
    if hit:
        return None, "судья назвал обе метки: %s" % said[:80]
    if TIE in said.lower():
        return TIE, said[:80]
    return None, "в ответе судьи нет ни метки, ни ничьей: %s" % said[:80]


def load_results(run_dir):
    path = os.path.join(run_dir, "results.jsonl")
    recs = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                raise ValueError("строка %d не JSON: %s" % (i, path))
            if not isinstance(rec, dict):
                raise ValueError("строка %d не запись: %s" % (i, path))
            recs.append(rec)
    if not recs:
        raise ValueError("в прогоне нет записей: %s" % path)
    return recs


def cmd_judge(argv):
    ap = argparse.ArgumentParser(prog="cckit-bench judge")
    ap.add_argument("--run", required=True)
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--project", required=True)
    ap.add_argument("--budget", default="0.20")
    a = ap.parse_args(argv)

    run_dir = os.path.abspath(os.path.expanduser(a.run))
    project = os.path.abspath(os.path.expanduser(a.project))
    if not os.path.isdir(project):
        sys.stderr.write("нет проекта: %s\n" % project)
        return 2
    if a.a == a.b:
        sys.stderr.write("--a и --b — один вариант: %s\n" % a.a)
        return 2
    try:
        recs = load_results(run_dir)
    except (ValueError, OSError) as e:
        sys.stderr.write("%s\n" % e)
        return 2

    # A typo in a name must cost a message, not a silent "nothing to compare".
    present = sorted(set(r.get("variant") for r in recs if r.get("variant")))
    absent = [n for n in (a.a, a.b) if n not in present]
    if absent:
        sys.stderr.write("нет таких вариантов в прогоне: %s\nесть: %s\n"
                         % (", ".join(absent), ", ".join(present)))
        return 2

    by, unscorable = {}, 0
    for r in recs:
        if not scorable(r):
            unscorable += 1
            continue
        by.setdefault(r.get("case"), {}).setdefault(r.get("variant"), {})[
            r.get("attempt", 1)] = r

    secrets = secrets_of(recs, run_dir)

    wins = losses = ties = unusable = 0
    uncompared, cost = [], 0.0
    box = os.path.join(run_dir, "judge")
    os.makedirs(box, exist_ok=True)
    with open(os.path.join(run_dir, "verdicts.jsonl"), "w", encoding="utf-8") as out:
        for case_id in sorted(by):
            got = by[case_id]
            # Attempt by attempt: with --runs N the owner paid for N answers
            # per side, and judging only the first throws the rest away.
            pairs = sorted(set(got.get(a.a, {})) & set(got.get(a.b, {})))
            if not pairs:
                uncompared.append(case_id)
                continue
            for attempt in pairs:
                ra, rb = got[a.a][attempt], got[a.b][attempt]
                task = ra.get("prompt") or rb.get("prompt") or case_id
                # Both orders: a judge that prefers whatever it reads first is
                # measuring position, not quality.
                for swapped in (False, True):
                    first, second = (rb, ra) if swapped else (ra, rb)
                    la = blind_label(first["variant"], case_id, "A")
                    lb = blind_label(second["variant"], case_id, "B")
                    # The label maps to the VARIANT, not to the position. Tie
                    # the answer to the slot instead and a candidate winning
                    # both orders is recorded as one win and one loss.
                    labels = {la: first["variant"], lb: second["variant"]}
                    q = JUDGE_PROMPT.format(
                        prompt=task, a=la, b=lb,
                        answer_a=scrub(first.get("answer") or "", secrets),
                        answer_b=scrub(second.get("answer") or "", secrets))
                    argvj = core.launch_argv(q, project, judge_disallowed(), True,
                                             a.budget, extra=["--output-format", "json"])
                    res, err = core.run_claude(box, argvj)
                    ok, note = outcome(res, err)
                    said = ((res or {}).get("result") or "").strip()
                    cost += (res or {}).get("total_cost_usd") or 0.0
                    picked, why = read_pick(said, labels) if ok else (None, note)
                    if picked == a.b:
                        wins += 1
                    elif picked == a.a:
                        losses += 1
                    elif picked == TIE:
                        ties += 1
                    else:
                        unusable += 1
                    out.write(json.dumps({"case": case_id, "attempt": attempt,
                                          "swapped": swapped, "labels": labels,
                                          "picked": None if picked in (None, TIE) else picked,
                                          "tie": picked == TIE,
                                          "said": said[:200], "note": why},
                                         ensure_ascii=False) + "\n")
                    out.flush()     # судейство, умершее на пятом, хранит четыре

    n = wins + losses + ties
    print("сравнений: %d (пропущено негодных прогонов: %d)" % (n, unscorable))
    if uncompared:
        print("не с чем сравнивать, случаи пропущены: %s" % ", ".join(uncompared))
    if unusable:
        print("судья не ответил в %d сравнениях — это не ничья и в счёт не идёт"
              % unusable)
    print("%s выиграл %d, %s выиграл %d, ничьих %d" % (a.b, wins, a.a, losses, ties))
    print("порог шума при %d сравнениях: %.2f" % (n, noise_floor(n)))
    print("вердикт: " + verdict(wins, losses, ties))
    print("судейство стоило: $%.2f" % cost)
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("run", "judge"):
        print("cckit-bench run --cases F --project DIR --variant имя=ROLE.md [--runs N]\n"
              "cckit-bench judge --run DIR --a имя --b имя --project DIR")
        return 2
    return (cmd_run if sys.argv[1] == "run" else cmd_judge)(sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())

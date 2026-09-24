#!/usr/bin/env python3
"""Библиотека компонентов: манифесты → индекс → заказ установки.

Источник правды — манифесты в git рядом с компонентами (`component.yaml`, у хуков —
`components/hooks/<id>.yaml`). Каталог генерируется, руками не правится; версия компонента —
последний коммит его файлов. Заказ — не чтение таблицы: основной агент называет, ЧТО нужно
ассистенту, решатель подбирает компоненты по `provides`.

  cckit_library.py index            — library.json + LIBRARY.md из манифестов
  cckit_library.py needs            — что можно заказать и кто это даёт
  cckit_library.py order [--role ОСНОВА] --needs a,b [--ledger ПУТЬ] [--json]
  cckit_library.py find ЗАПРОС      — поиск по компонентам и ролям
  cckit_library.py fetch --needs a,b --to ПАПКА [--ref SHA] — скачать заказанное из git
"""
import ast
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERABLE = ("works", "wired-later")


def _git(*args):
    try:
        return subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True, check=True).stdout
    except Exception:
        return None


def manifest_paths():
    out = _git("ls-files", "--cached", "--others", "--exclude-standard")
    if out is None:
        files = [os.path.relpath(os.path.join(d, f), ROOT) for d, _, fs in os.walk(ROOT) for f in fs]
    else:
        files = out.split()
    return sorted(f for f in files if f.endswith("component.yaml") or (f.startswith("components/") and f.endswith(".yaml")))


def parse(text):
    """Плоский YAML: `ключ: значение`, списки `[a, b]`, строки карточки через ` | `."""
    m = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        v = re.sub(r"\s+#.*$", "", v).strip()
        if v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
        m[k.strip()] = v
    for k in ("provides", "requires", "requires_input", "grants", "files", "writes", "hooks"):
        m[k] = m.get(k) or []
    if isinstance(m.get("card_lines"), str):
        m["card_lines"] = [x.strip() for x in m["card_lines"].split(" | ") if x.strip()]
    return m


def load():
    comps = []
    for rel in manifest_paths():
        with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
            c = parse(fh.read())
        c["manifest"] = rel
        where = os.path.dirname(rel) if rel.endswith("component.yaml") else rel
        c["version"] = (_git("log", "-1", "--format=%h", "--", where) or "").strip() or "не в git"
        comps.append(c)
    return sorted(comps, key=lambda c: (c.get("kind", ""), c.get("id", "")))


def _installer_consts():
    """CAPS, BASE_CAPS, NEVER, DANGEROUS из установщика — разбором текста, без импорта:
    описание прав в каталоге обязано совпадать с тем, что установщик действительно выдаст."""
    tree = ast.parse(open(os.path.join(ROOT, "bin", "cckit_assistant.py"), encoding="utf-8").read())
    got = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", "") in ("CAPS", "BASE_CAPS", "NEVER", "DANGEROUS"):
            got[node.targets[0].id] = ast.literal_eval(node.value)
    return got


def roles():
    k = _installer_consts()
    every = sorted({t for tools in k["CAPS"].values() for t in tools} | set(k["NEVER"]))
    out = []
    for d in sorted(os.listdir(os.path.join(ROOT, "assistants"))):
        cp = os.path.join(ROOT, "assistants", d, "card.yaml")
        if not os.path.isfile(cp):
            continue
        with open(cp, encoding="utf-8") as fh:
            c = parse(fh.read())
        caps = list(k["BASE_CAPS"]) + (["write"] if c.get("access") == "write-scoped" else [])
        allowed = sorted({t for cap in caps for t in k["CAPS"].get(cap, [])})
        out.append({"id": d, "kind": "role", "summary": c.get("summary", ""), "access": c.get("access", "read-only"),
                    "reads": "весь проект и свой дом", "writes": c["writes"] or ["— только свой дом (LEARNED.md, memory)"],
                    "tools_allowed": allowed, "tools_denied": [t for t in every if t not in allowed],
                    "grants_on_request": list(k["DANGEROUS"]) + [x for x in ("spawn", "web", "worktree", "design") if x in k["CAPS"]],
                    "hooks": c["hooks"], "model": c.get("model"), "effort": c.get("effort"), "compact_at": c.get("compact_at"),
                    "version": (_git("log", "-1", "--format=%h", "--", "assistants/" + d) or "").strip() or "не в git"})
    return out


def index(out_dir=None):
    out_dir = out_dir or ROOT
    comps = load()
    rls = roles()
    with open(os.path.join(out_dir, "library.json"), "w", encoding="utf-8") as fh:
        json.dump({"components": comps, "roles": rls}, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    rows = ["| %s | %s | %s | %s | %s | %s |" % (c.get("id"), c.get("kind"), ", ".join(c["provides"]) or "—",
            c.get("status"), c.get("version"), c.get("summary", "")) for c in comps]
    rrows = ["| %s | %s | %s | %s | %s | %s | %s |" % (r["id"], r["summary"], ", ".join(r["writes"]), ", ".join(r["tools_allowed"]),
             ", ".join(r["tools_denied"]), ", ".join(r["hooks"]) or "—", r["model"]) for r in rls]
    with open(os.path.join(out_dir, "LIBRARY.md"), "w", encoding="utf-8") as fh:
        fh.write("# Библиотека компонентов\n\n"
                 "**Генерируется** из манифестов (`python3 bin/cckit_library.py index`) — руками не править.\n"
                 "Приём живёт тремя опорами: файл компонента, строка в карточке роли, проверка (`proof`\n"
                 "в манифесте). Заказ: `python3 bin/cckit_library.py order --needs …`.\n\n"
                 "| id | вид | даёт | статус | версия | что это |\n|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
                 "\n## Роли — что каждая может, до установки\n\n"
                 "Права вычислены константами установщика: описание не может разойтись с тем, что роль получит.\n"
                 "Читают все роли весь проект и свой дом. Опасные группы — только по явной выдаче при установке.\n\n"
                 "| роль | для чего | пишет | разрешено | запрещено | хуки | модель |\n|---|---|---|---|---|---|---|\n"
                 + "\n".join(rrows) + "\n")
    return comps + rls


def needs():
    by = {}
    for c in load():
        if c.get("status") in ORDERABLE:
            for n in c["provides"]:
                by.setdefault(n, []).append("%s (%s)" % (c["id"], c.get("status")))
    return by


def order(wanted, inputs):
    comps = [c for c in load() if c.get("status") in ORDERABLE and c.get("kind") != "skill"]
    chosen, missing, errors = [], [], []
    for n in wanted:
        hit = [c for c in comps if n in c["provides"]]
        if not hit:
            missing.append(n)
        for c in hit:
            if c not in chosen:
                chosen.append(c)
    card, lines, role, grants, later = {}, [], [], [], []
    for c in chosen:
        for need in c["requires_input"]:
            if not inputs.get(need):
                errors.append("%s требует --%s" % (c["id"], need))
        if c.get("card_key"):
            card.setdefault(c["card_key"], []).append(c["card_value"])
            if c.get("status") == "wired-later":
                later.append(c["card_key"])
        lines += c.get("card_lines") or []
        if c.get("role_text"):
            role.append(c["role_text"])
        grants += [g for g in c["grants"] if g not in grants]
    if inputs.get("ledger"):
        lines.append("ledger: %s" % inputs["ledger"])
    return {"components": [c["id"] for c in chosen], "card": card, "card_lines": lines,
            "role_text": role, "grants": grants, "wired_later": later,
            "not_found": missing, "errors": errors}


CARD_ORDER = ("name", "summary", "access", "writes", "model", "effort", "budget_usd", "compact_at", "hooks", "ledger", "formats")


def assemble(role, wanted, inputs):
    """Юнит = роль-основа + детали. Итоговая card.yaml, добавки в ROLE.md, выдача, файлы."""
    cp = os.path.join(ROOT, "assistants", role, "card.yaml")
    if not os.path.isfile(cp):
        return {"errors": ["нет роли-основы «%s»; есть: %s" % (role, ", ".join(r["id"] for r in roles()))]}
    with open(cp, encoding="utf-8") as fh:
        base = parse(fh.read())
    o = order(wanted, inputs)
    card = {k: v for k, v in base.items() if k in CARD_ORDER and v not in ([], None, "")}
    for key, vals in o["card"].items():
        card[key] = list(dict.fromkeys(list(card.get(key) or []) + vals))
    for line in o["card_lines"]:
        k, _, v = line.partition(":")
        card[k.strip()] = v.strip()
    text = []
    for k in CARD_ORDER:
        if k in card:
            v = card[k]
            text.append("%s: %s" % (k, "[%s]" % ", ".join(('"%s"' % x) if k == "writes" else x for x in v) if isinstance(v, list) else v))
    o.update({"role": role, "card_yaml": "\n".join(text) + "\n", "fetch": sorted({f for c in load() if c["id"] in set(o["components"]) | set(card.get("hooks") or []) | set(card.get("formats") or []) for f in c["files"]})})
    return o


def find(query):
    q = query.lower()
    return [x for x in load() + roles() if q in (" ".join([x.get("id", ""), x.get("summary", "")] + list(x.get("provides", [])))).lower()]


def fetch(wanted, to, ref="HEAD", inputs=None):
    """Скачать заказанные компоненты из git в версии ref — только их, не всю библиотеку."""
    ids = order(wanted, inputs or {})["components"]
    got = []
    for c in load():
        if c["id"] not in ids:
            continue
        for path in c["files"]:
            listed = (_git("ls-tree", "-r", "--name-only", ref, "--", path) or "").split()
            for f in listed:
                blob = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (ref, f)], capture_output=True, check=True).stdout
                dst = os.path.join(to, f)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as fh:
                    fh.write(blob)
                got.append(f)
    return sorted(set(got))


def main(argv):
    if argv and argv[0] == "find" and len(argv) > 1:
        for x in find(" ".join(argv[1:])):
            print("%-16s %-9s %s" % (x["id"], x.get("kind"), x.get("summary", "")))
        return 0
    if argv and argv[0] == "fetch":
        want = argv[argv.index("--needs") + 1].split(",") if "--needs" in argv else []
        to = argv[argv.index("--to") + 1] if "--to" in argv else None
        ref = argv[argv.index("--ref") + 1] if "--ref" in argv else "HEAD"
        if not want or not to:
            print("fetch --needs a,b --to ПАПКА [--ref SHA]"); return 2
        for f in fetch([w.strip() for w in want], to, ref):
            print("  " + f)
        return 0
    if not argv or argv[0] not in ("index", "needs", "order"):
        print(__doc__.strip()); return 2
    if argv[0] == "index":
        print("компонентов: %d → library.json, LIBRARY.md" % len(index())); return 0
    if argv[0] == "needs":
        for n, who in sorted(needs().items()):
            print("%-18s %s" % (n, ", ".join(who)))
        return 0
    want, inputs, as_json, i = [], {}, False, 1
    while i < len(argv):
        if argv[i] == "--needs": want = [x.strip() for x in argv[i + 1].split(",") if x.strip()]; i += 2
        elif argv[i] == "--json": as_json = True; i += 1
        elif argv[i].startswith("--") and i + 1 < len(argv): inputs[argv[i][2:]] = argv[i + 1]; i += 2
        else: print("неизвестный флаг: " + argv[i]); return 2
    role = inputs.pop("role", None)
    r = assemble(role, want, inputs) if role else order(want, inputs)
    if r.get("errors") and "components" not in r:
        print("ОШИБКА: " + r["errors"][0]); return 1
    if as_json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(("юнит на основе роли «%s»; детали: " % role if role else "компоненты: ") + (", ".join(r["components"]) or "—"))
        if role:
            print("\ncard.yaml целиком:\n" + "".join("  " + l + "\n" for l in r["card_yaml"].splitlines()))
            print("скачать из git: " + (", ".join(r["fetch"]) or "—"))
        print("\nв card.yaml:")
        for k, v in r["card"].items():
            print("  %s: [%s]%s" % (k, ", ".join(v), "   # установщик доставит в 1.3 — пока см. ROLE.md" if k in r["wired_later"] else ""))
        for l in r["card_lines"]:
            print("  " + l)
        if r["role_text"]:
            print("\nв ROLE.md:"); [print("  - " + t) for t in r["role_text"]]
        if r["grants"]:
            print("\nпри установке: --grant " + ",".join(r["grants"]))
        for n in r["not_found"]:
            print("\nне нашлось компонента для «%s» — см. `needs`" % n)
        for e in r["errors"]:
            print("\nОШИБКА: " + e)
    return 1 if r["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

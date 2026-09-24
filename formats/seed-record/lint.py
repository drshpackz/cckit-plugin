#!/usr/bin/env python3
"""Линтер записи-зерна. Формат описан так, как его держат живые досье, а не придуман.

  python3 lint.py FILE...   — печатает замечания, код 1, если они есть.
"""
import re
import sys

REQUIRED = ("topic", "question", "collected", "commit", "confidence", "source")
VERDICT = ("вердикт", "verdict")
OPEN = ("открытые вопросы", "open questions")


def lint(text):
    """Список замечаний; пустой — запись годится."""
    out = []
    m = re.match(r"^---\n(.*?)\n---\n", text or "", re.S)
    if not m:
        return ["нет шапки ---…--- в начале: без неё запись не говорит, на что отвечает и против какого кода"]
    head = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if k.strip():
            head[k.strip()] = v.strip()
    for k in REQUIRED:
        if not head.get(k):
            out.append("в шапке нет «%s»" % k)
    if head.get("collected") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", head["collected"]):
        out.append("collected — не дата ГГГГ-ММ-ДД: %s" % head["collected"])
    if head.get("commit") and not re.fullmatch(r"[0-9a-f]{7,40}", head["commit"]):
        out.append("commit — не sha: %s (без sha устаревание не вычислить)" % head["commit"])
    if head.get("confidence") and head["confidence"] not in ("high", "medium", "low"):
        out.append("confidence — не high/medium/low: %s" % head["confidence"])
    heads = [h.strip().lower() for h in re.findall(r"(?m)^## (.+)$", text[m.end():])]
    if not heads or heads[0] not in VERDICT:
        out.append("первый раздел — не «Вердикт»: ответ должен стоять первым")
    if not any(h in OPEN for h in heads):
        out.append("нет раздела «Открытые вопросы»: не видно, где остановились")
    return out


def main(paths):
    bad = 0
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            problems = lint(fh.read())
        for msg in problems:
            print("%s: %s" % (p, msg))
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

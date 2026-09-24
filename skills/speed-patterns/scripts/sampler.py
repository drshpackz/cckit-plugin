#!/usr/bin/env python3
"""Сэмплер скорости агентов по стенограммам.

Главное различение: время МЫСЛИ (от результата инструмента или промпта до
следующего хода модели) и время ИНСТРУМЕНТА (от вызова до его результата).
Ожидание человека не считается: оно идёт от конца хода до промпта, а мы
считаем только от промпта/результата к модели.

Запуск:
  sampler.py --target NAME=ГЛОБ_СТЕНОГРАММ [--target …] --minutes 30 --every 180 --out FILE
ГЛОБ — путь к стенограмме сессии (*.jsonl), обычно под ~/.claude/projects/<папка>/;
субагенты сессии берутся из <сессия>/subagents/*.jsonl сами.
"""
import argparse, glob, json, os, statistics, sys, time
from datetime import datetime, timezone

P = os.path.expanduser("~/.claude/projects")
TARGETS = {}  # имя -> {"main": glob, "subs": glob}; задаётся флагами --target


def ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except Exception:
        return None


def blocks(e):
    c = (e.get("message") or {}).get("content")
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


class Stream:
    """Хвост одного файла: читает только дописанное, держит состояние между окнами."""

    def __init__(self, path):
        self.path, self.off = path, 0
        self.pending = {}          # tool_use_id -> (name, t)
        self.last_user = None      # (t, what) — последнее событие, после которого думает модель
        self.awaiting = False      # ждём первый ход модели после last_user

    def new_events(self):
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.off)
                data = fh.read()
        except OSError:
            return []
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        self.off += cut + 1
        out = []
        for line in data[:cut + 1].splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out


def fresh_window():
    return {"calls": 0, "tools": {}, "tool_time_s": {}, "think": [], "think_after": [],
            "out_tokens": 0, "thinking_tokens": 0, "ctx": None, "prompts": 0,
            "interrupts": 0, "bash": [], "notifications": 0}


def feed(stream, events, w):
    for e in events:
        t = ts(e.get("timestamp"))
        typ = e.get("type")
        if typ == "assistant":
            m = e.get("message") or {}
            u = m.get("usage") or {}
            if u:
                w["ctx"] = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                            + u.get("cache_creation_input_tokens", 0))
                w["out_tokens"] += u.get("output_tokens", 0)
                w["thinking_tokens"] += ((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
            if stream.awaiting and t and stream.last_user:
                w["think"].append((t - stream.last_user[0]).total_seconds())
                w["think_after"].append(stream.last_user[1])
                stream.awaiting = False
            for b in blocks(e):
                if b.get("type") == "tool_use":
                    name = b.get("name") or "?"
                    w["calls"] += 1
                    w["tools"][name] = w["tools"].get(name, 0) + 1
                    if t:
                        stream.pending[b.get("id")] = (name, t)
                    if name == "Bash" and len(w["bash"]) < 6:
                        w["bash"].append(((b.get("input") or {}).get("command") or "")[:110].replace("\n", " ⏎ "))
        elif typ == "user":
            c = (e.get("message") or {}).get("content")
            text = c if isinstance(c, str) else " ".join(b.get("text", "") for b in blocks(e) if b.get("type") == "text")
            what = None
            for b in blocks(e):
                if b.get("type") == "tool_result":
                    p = stream.pending.pop(b.get("tool_use_id"), None)
                    if p and t:
                        dt = (t - p[1]).total_seconds()
                        w["tool_time_s"][p[0]] = round(w["tool_time_s"].get(p[0], 0) + dt, 1)
                        what = "after:" + p[0]
            if "<task-notification>" in (text or ""):
                w["notifications"] += 1
                what = what or "after:notification"
            elif "Request interrupted" in (text or ""):
                w["interrupts"] += 1
            elif text and text.strip() and not what:
                w["prompts"] += 1
                what = "after:prompt"
            if what and t:
                stream.last_user, stream.awaiting = (t, what), True


def summarize(w, window_s):
    th = w.pop("think")
    after = w.pop("think_after")
    w["window_min"] = round(window_s / 60, 1)
    w["calls_per_min"] = round(w["calls"] / (window_s / 60), 2) if window_s else None
    w["think_n"] = len(th)
    w["think_total_s"] = round(sum(th), 1)
    w["think_median_s"] = round(statistics.median(th), 1) if th else None
    if th:
        i = max(range(len(th)), key=lambda k: th[k])
        w["think_max_s"], w["think_max_after"] = round(th[i], 1), after[i]
    w["tool_total_s"] = round(sum(w["tool_time_s"].values()), 1)
    busy = w["think_total_s"] + w["tool_total_s"]
    w["think_share"] = round(w["think_total_s"] / busy, 2) if busy else None
    return w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--every", type=int, default=180)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", action="append", default=[], help="NAME=ГЛОБ стенограмм")
    a = ap.parse_args()
    for spec in a.target:
        name, _, g = spec.partition("=")
        if not g:
            ap.error("--target ждёт NAME=ГЛОБ, получено: " + spec)
        g = os.path.expanduser(g)
        TARGETS[name] = {"main": g, "subs": g[:-6] + "/subagents/*.jsonl" if g.endswith(".jsonl") else g + "/*/subagents/*.jsonl"}
    if not TARGETS:
        ap.error("нужна хотя бы одна --target")
    streams = {}                    # (agent, kind, path) -> Stream
    end = time.time() + a.minutes * 60
    first, prev = True, time.time()
    while True:
        now = time.time()
        for agent, spec in TARGETS.items():
            mains = spec["main"] if isinstance(spec["main"], list) else glob.glob(spec["main"])
            for kind, paths in (("main", mains), ("subs", glob.glob(spec["subs"]))):
                w = fresh_window()
                files_active = 0
                for p in paths:
                    s = streams.setdefault((agent, kind, p), Stream(p))
                    ev = s.new_events()
                    if ev:
                        files_active += 1
                    feed(s, ev, w)
                if not w["calls"] and not w["prompts"] and not w["notifications"]:
                    continue
                rec = summarize(w, now - prev if not first else 0)
                rec.update({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "agent": agent, "stream": kind, "files_active": files_active,
                            "backfill": first})
                with open(a.out, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        first, prev = False, now
        if time.time() >= end:
            break
        time.sleep(max(1, min(a.every, end - time.time())))
    print("сэмплер закончил:", a.out)


if __name__ == "__main__":
    sys.exit(main())

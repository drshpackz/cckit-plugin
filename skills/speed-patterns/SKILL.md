---
name: speed-patterns
description: Use when an agent, assistant or subagent is slow, when choosing model, effort, tools or compaction for an assistant role, or when explaining why one agent finished faster than another
---

# Speed patterns

Measured on Claude Code agents, 2026-09-24. **Time goes to model generation (80–99% of busy time), not to tools.** An agent gets faster by taking fewer and lighter model turns and by not losing work — not by faster tools. Statuses: *measured* = controlled test, n≥3; *observed* = one session. Full data: `docs/findings/agent-speed.md` in the CCKit Assistants plugin; how the skill was tested: `TESTING.md` here.

## Levers, by measured effect

| lever | effect | status |
|---|---|---|
| **Compaction threshold ≈ model window.** `compact_at` / `autoCompactWindow` far below the window compacts mid-task | a role at 200k compacted twice in 24 min, discarding 337k tokens including a 7.5-min, 44k-token plan; it then re-read the same files. Switching the model to `[1m]` did not help — the threshold did | observed, verified in transcript |
| **Write early, in parts.** First action writes a skeleton to the file, then one region per edit | a plan held only in thinking dies at compaction or interrupt; a file survives both | observed by 3 independent analysts |
| **Effort by kind of work.** Lookup/verification at `medium`, decisions higher | `medium`: −18% time, −35% cost, same quality on a 24-item lookup | measured |
| **Fan-out must be stated.** Granting spawn is not enough — say *which* parts go to subagents | 0 subagents in 36 runs on 5–24-item tasks with spawn allowed; on a 9-dossier job the role that was told to fan out ran 13 subagents, 511 calls in ~7 min | measured / observed |
| **Bash batches calls, it does not speed them.** | −3× tool calls, −16–21% cost, wall time unchanged: a Bash turn is a bigger turn | measured |
| **Full brief** (what, where, owner's words, what is known) | removes reconnaissance; no effect when the task is already self-contained | measured (no effect case) |

Why subagents run 3–8× more calls per minute: start context 15–17k vs 25–48k (no dialogue, role prompt, memory), thinking per turn 112–181 tokens vs 911 for a main agent that decides, and they never wait. **They do receive CLAUDE.md** — that is not the reason.

## Diagnose a slow agent from its transcript

Read structure, not the model's own account:

1. `compact_boundary` events and their `preTokens` — compaction mid-task?
2. Longest turns with no tool call, and their `thinking_tokens` — is the work being held in thinking?
3. Think time vs tool time — `python3 scripts/sampler.py --target NAME=<transcript.jsonl> --minutes 30 --every 180 --out FILE`; subagents of the session are picked up automatically.
4. Tool mix — dozens of Read/Grep where one command would do?
5. Is `Agent` offered but never called?
6. Exclude waiting (for the human, for subagents) before calling anything slow.
7. Can the work split into independent parts (regions, files, areas)? If yes and the agent did them one by one, name the parts that should go to subagents — the model will not split on its own.

Missing `thinking_tokens` is **missing, not zero** — count only turns that carry the field.

## Measure a change before claiming it

One variable per arm; ground truth taken from the code before the runs and frozen; grep the docs for leaked answers; n≥3; interleave arms in batches; score quality, not only time; report ranges. Test subjects get the full toolset in an empty directory — isolate with the folder, never by removing tools.

## Common mistakes

- Blaming model or effort without looking at compaction and no-tool turns.
- Reading a lower calls-per-minute as a slow model when the agent was waiting.
- Promising Bash as a speed-up — it is a cost and turn-count lever.
- Ground truth that is not unique in the codebase: an agent that picks the other match is right.

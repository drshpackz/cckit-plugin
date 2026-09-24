# How speed-patterns was tested (2026-09-24)

Subjects: clean `claude -p`, `claude-opus-5-5`, bypass, full toolset, empty directory. Criteria frozen before each run; every regex hit read by hand.

| test | scenario | without skill | with skill |
|---|---|---|---|
| RED-1 | "why was agent B faster than A" (two real transcripts) | analysts did well — found compaction and the unused `Agent` that the lead session had missed; **no skill needed for analysis itself** | — |
| RED-2 / GREEN-2 | "speed up this slow assistant card" (the case the skill was derived from) | fan-out named 0/3, compaction 2/3, measured numbers 0/3, 94–176 s | fan-out 2/3, compaction 3/3, numbers 3/3, 26–42 s |
| GREEN-2b | same, after adding diagnosis step 7 (split into parts) | — | fan-out **3/3** |
| RED-3 / GREEN-3 | variation: a researcher slow on 9 independent areas | fan-out 3/3, effort 3/3, compaction 3/3, numbers 0/3, measure 2/3, 62–69 s | same levers 3/3, numbers 3/3, measure 3/3, 36–47 s |

Reading: when the parallel structure is obvious, agents find the levers anyway; the skill adds measured numbers, calibrated confidence and a 30–70% faster analysis. It matters most when the lever is not obvious (fan-out on a single-artboard task: 0/3 → 3/3).

Known false positives in scoring: "Sonnet for subagents" is a cost suggestion, not "use a bigger model"; "Bash does not speed up" matched a naive "Bash … ускор" pattern.

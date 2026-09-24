---
name: create-agent
description: Use when you need a new assistant for a project — the user asks for a researcher, a reviewer, a watcher, or you notice you keep doing the same digging by hand and want it to persist.
---

# Making an assistant

## First: does one already exist

`cckit assistant list` (или `python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py" list`) — an instance for this project, or `cckit:find-agent` for
a published role. Making a second one that does the same work splits its memory
in two.

## The interview, four questions

1. **What does it collect?** One sentence. If the answer contains "and", it is
   two assistants.
2. **Where does it write?** One directory. Everything else it reads only.
3. **What must it never do?** Build, run, commit — name them.
4. **Which project?** An absolute path.

## Assemble from the library

Do not write an assistant from scratch when a proven part exists. Read `LIBRARY.md` at the
plugin root and pick parts by the interview answers. Declare only parts marked **работает**
there; a part that is not wired yet goes into `ROLE.md` as an instruction, not into the card.

| the assistant… | take |
|---|---|
| reports to the main agent | `hooks: [report-done]` |
| keeps `LEARNED.md` | `lint-learned` |
| must not redo research that is already current | a ledger + `read-ledger` |
| writes findings other agents will build on | the seed-record format, `formats/seed-record/TEMPLATE.md`: `formats: [seed-record]`; until the installer delivers it, name the template in `ROLE.md` |
| has work that splits into independent parts | grant `spawn`, and say in `ROLE.md` which parts go to subagents — the model does not split on its own |
| runs long tasks | a 1M-context model and `compact_at` near the window |

Why each one helps, with numbers: the `speed-patterns` skill.

## The card

`~/.cckit/library/<role>/card.yaml`:

```yaml
name: doc-scout
summary: One line. This becomes the agent's description.
access: write-scoped        # read-only | write-scoped
writes: ["docs/notes/**"]   # omit for read-only
model: claude-opus-5-5[1m]  # 1M window; without 1M access: claude-opus-5-5
effort: xhigh               # low|medium|high|xhigh|max
compact_at: 900000          # near the model window, not 200000
budget_usd: 3.00            # hard ceiling per run
hooks: [report-done, lint-learned]   # + read-ledger if it has a ledger
ledger: docs/notes/STATE.md # what read-ledger puts in every session
formats: [seed-record]      # findings for other agents; see LIBRARY.md
```

`~/.cckit/library/<role>/ROLE.md` is the **system prompt** — it replaces Claude
Code's own. Write it as an identity, not a task list, and put **no project
paths in it**: use `{PROJECT}` and `{HOME}`. A role with a project path baked in
cannot be reused, which is the whole point of a library.

## Install

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py"
# короче, если установлен CCKit CLI: cckit assistant install <role> --project <abs path>
```

It refuses to report success until the probes pass: it writes into a forbidden
place and checks the **disk**, it compares the delivered system prompt to
the role body **byte for byte**, and it checks each declared hook's **effect**. Both failures it guards against happen in
silence — a mis-scoped rule matches nothing, and a card missing `name:` is
ignored while everything still looks normal.

Capabilities beyond reading are granted per install, never baked into the role:
`--grant web,spawn`. Five of them leave the sandbox and need `--i-mean-it`.

## Without the CLI

No Python on this machine: read
`${CLAUDE_PLUGIN_ROOT}/skills/create-agent/by-hand.md` and build the home
yourself. Every rule in it was measured, and each one fails silently when you
get it wrong.

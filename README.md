# CCKit Assistants

Ready-made assistants you install into a project with one command.

An assistant is a separate, long-lived Claude Code session bound to one project.
It has its own system prompt, its own memory, and a fence that is **tested at
install time** rather than promised. It is not a subagent: it outlives the
conversation that made it and keeps what it learned.

```
/plugin marketplace add drshpackz/cckit-plugin
/plugin install cckit@cckit-plugin
```

Then, in any session: `/cckit:create-agent`, `/cckit:list-agents`,
`/cckit:find-agent`.

## Why the probes

Assistants are meant to run with permission prompts turned off. That changes
what a mistake costs: **a rule that is wrong fails open.** It does not break
loudly — it silently permits.

Three ways that happened here, each found by a probe and none of them visible
in the code:

- an absolute path in a permission rule needs a **doubled** leading slash; with
  one slash it matches nothing, silently;
- a bare `"Read"` in `allow` grants the entire filesystem, not the project;
- an untrusted workspace voids every `allow` rule at once — the fence compiles,
  is written, and permits nothing.

So the installer **writes into a forbidden place and looks at the disk**, then
asks the model to execute something and looks again. Separately it compares the
delivered system prompt to the role body. Until both probes pass, nothing is
reported as installed. A role you downloaded gets the same treatment as your
own.

## Giving it work

```
cckit assistant install design-scout --project . --also-read ../other-tree
cckit assistant run design-scout@myrepo "какой настройкой задаётся X, дай path:line"
```

`run` executes the assistant synchronously from its own home, through its own
`launch.json` — the same path the install probes take. Inspect with
`cckit assistant list`, `cckit assistant tree`, `cckit assistant show <id>` and
`cckit assistant where <id>`; change what it may do with
`cckit assistant grant` and `cckit assistant revoke`, and pin a decision of
your own with
`cckit assistant owner-rule`, which outranks the agent.

## Measure a change instead of believing it

A bench ships with the plugin. Point it at two versions of a role and it runs
them over the same cases in throwaway sandboxes, with a blind judge that sees
neither name, in both orders.

```
cckit-bench run   --cases cases.json --project . --variant a=old.md --variant b=new.md
cckit-bench judge --run <dir> --a a --b b --project .
```

It is built to refuse rather than flatter:

- a run whose prompt never reached the model is **not a loss** — it is not a
  measurement, and it is excluded and reported;
- a margin below `1/sqrt(n)` prints **"cannot tell"**, not a winner;
- if the judge fell silent on more than a third of comparisons, it says so and
  names nobody: dropouts correlate with the hard cases, so the survivors are a
  biased sample.

There is a third arm for the learned layer: the same role with its accumulated
`LEARNED.md` against the same role with nothing. **If what an assistant learned
does not win, its memory is collecting noise** — clean it rather than add to it.

## Role, instance, memory

A **role** lives in the library and holds no project data — it is reusable. An
**instance** binds one role to one project. What the instance learned lives in
`LEARNED.md` and its memory, and survives `cckit assistant reset`, which
rebuilds everything generated. Open a different project tomorrow and you get a
second instance, not a polluted first one.

Every record in `LEARNED.md` carries how well it is known — `измерено`,
`наблюдение`, `гипотеза`, `слово владельца` — and a linter enforces it. Without
that, one session's guess reads a month later exactly like a measured fact.

## Capabilities are granted, not baked in

Roles reuse across projects; risk is a property of the project. An assistant
reads by default. `--grant web,spawn` adds more, and five groups that leave the
sandbox — `shell`, `peers`, `publish`, `schedule`, `mcp` — need `--i-mean-it`.

Write permissions are computed **from your project**, not from a list someone
typed while looking at theirs. Installing into a Django tree denies `app/`,
`migrations/` and `manage.py`; installing into a Go tree denies `cmd/`,
`internal/` and `pkg/`. A fence naming folders you do not have guards nothing.

## What is proven, and what is only claimed

- **Proven on macOS:** the probes against a live model, 190 unit tests, the
  bench end to end on 36 paid runs.
- **Claimed until CI is green:** Linux and Windows. The suite runs on a
  three-platform matrix, and the honest state of that matrix is whatever the
  badge says — not what this file says.

## Known limits

- **An assistant sees the skills that happen to be on your machine, not its
  own.** `Skill` is granted to every assistant, nothing is installed into its
  home, and `~/.claude/skills/` leaks in. A role therefore behaves differently
  on different machines, and a bench number measured here will not reproduce on
  yours. Fixed in 1.1.
- The deny list is a snapshot taken at install. A top-level directory added to
  the project afterwards is denied by nothing. Re-run `install --force` (it
  does not touch memory).
- The library holds one role. `find-agent` will honestly tell you there is
  nothing to install.

## Without Python

Every skill degrades to instructions. See `skills/create-agent/by-hand.md`.

MIT.

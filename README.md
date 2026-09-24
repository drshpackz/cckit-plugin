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
delivered system prompt to the role body. Until every probe passes, nothing is
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
`cckit assistant owner-rule`, which outranks the agent. `cckit assistant retire <id>` takes a home out of service by moving it to `<assistants>/.attic/<name>/<time>` — never deleting it — and refuses a home with a live session unless given `--i-mean-it`.

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
`наблюдение`, `гипотеза`, `слово владельца` — and `bin/cckit_learned.py`
checks it, in `./dev.sh check` and by hand — and, in every home whose card
declares `lint-learned`, as the record is written (see below). Without that,
one session's guess reads a month later exactly like a measured fact.

## The home acts by itself: hooks

A card switches hooks on by name; the implementations ship with the plugin and
are copied into the home, so the home outlives the plugin being updated or
removed.

```yaml
hooks: [report-done, lint-learned, read-ledger]
ledger: docs/vscode-internals/STATE.md     # what read-ledger delivers
```

- `report-done` (Stop) — one line per finished turn in `<home>/reports.jsonl`;
- `lint-learned` (PreToolUse on Write|Edit|MultiEdit|Bash — refuses before the write; through Bash it is a heuristic) — a `LEARNED.md` record without a
  status is blocked with the reason;
- `read-ledger` (SessionStart) — the project's ledger goes into the session's
  context, so a section already marked current is not researched again.

Every shipped role declares `report-done` and `lint-learned`. Only the roles
whose brief already says "read this first" declare `read-ledger`:
`design-scout` and `under-the-hood` (`docs/vscode-internals/STATE.md`),
`cckit-smith` (`LEARNED.md`, `docs/findings/STATE.md`). `design-hand` has no
ledger — a file pushed into every session that nobody needs is paid for anyway.

Declared is not the same as working, so `install` runs a third probe: it
starts the assistant once and checks each hook's **effect** — the nonce in the
context, the linter's verdict, the new line in the journal. A hook that is
registered and never fires reports `НЕ СРАБОТАЛ`, and the install is not
reported as verified.

## The library, and its catalog as an API

Assistants are assembled from parts — hooks, formats, practices, settings —
each with a manifest next to its files. `bin/cckit_library.py` builds the
catalog from the manifests and assembles a **unit**: a base role plus the parts
you name by what they give, not by file.

```
python3 bin/cckit_library.py needs                                   # what can be ordered, and who gives it
python3 bin/cckit_library.py find ledger                             # search parts and roles
python3 bin/cckit_library.py order --role design-scout --needs reports-to-main,long-tasks   # the assembly sheet, nothing written
python3 bin/cckit_library.py build --role design-scout --needs writes-findings,long-tasks --records docs/vscode-internals/dossiers --name my-scout --install --project .
python3 bin/cckit_library.py fetch --needs writes-findings --to ./parts --from gh:drshpackz/cckit-plugin@main
```

`build` writes the unit into your library (`$CCKIT_LIBRARY`, else
`~/.cckit/library/<name>/`): `card.yaml` from the sheet and `ROLE.md` = the base
role plus a «Детали юнита» section. It never overwrites a role already there
without `--force`. With `--install --project` it hands the unit to the installer
with the grants the order asked for; `--i-mean-it` reaches the installer only if
you typed it. Every input a part asks for (`--ledger`, `--records`, …) becomes a
line of the card.

The catalog is published with the repository and read as an API:

- latest: https://raw.githubusercontent.com/drshpackz/cckit-plugin/main/library.json
- pinned: `https://raw.githubusercontent.com/drshpackz/cckit-plugin/<sha>/library.json`

A part's `version` is its **content**: sha256[:12] over its manifest and every
file in `blobs`, so the catalog is regenerated in the same commit as the part
and never lags behind it; `commit` is only for reference. `fetch --from gh:…`
downloads the catalog and the ordered parts, recomputes each hash and refuses —
writing nothing — if one does not match. Without `--from` it reads your local
git (`--ref SHA`). `LIBRARY.md` is the same catalog for people.

## Capabilities are granted, not baked in

Roles reuse across projects; risk is a property of the project. An assistant
reads by default. `--grant web,spawn` adds more, and five groups that leave the
sandbox — `shell`, `peers`, `publish`, `schedule`, `mcp` — need `--i-mean-it`.

Write permissions are computed **from your project**, not from a list someone
typed while looking at theirs. Installing into a Django tree denies `app/`,
`migrations/` and `manage.py`; installing into a Go tree denies `cmd/`,
`internal/` and `pkg/`. A fence naming folders you do not have guards nothing.

## What is proven, and what is only claimed

- **Proven on macOS, twice:** the probes against a live model, 205 unit tests,
  the bench end to end on 36 paid runs — and the whole suite again on a second
  machine, from a fresh clone, with no checkout, no personal CLI and no
  `claude` installed. That second run is what proves the published thing is
  self-sufficient.
- **Proven on Linux:** the whole suite on Ubuntu 22.04 x86_64, from a fresh
  clone, on both the distro's Python 3.10 and the declared floor, 3.9.25.
- **Not proven: Windows.** A three-platform matrix is committed in
  `.github/workflows/test.yml` and has never executed. Windows-specific logic
  is exercised by injection — path separators, `PATHEXT` resolution, the hook
  polyglot — which is not the same as running there. Treat Windows as
  unverified.

## Known limits

- **An assistant sees the skills that happen to be on your machine, not its
  own.** `Skill` is granted to every assistant, nothing is installed into its
  home, and `~/.claude/skills/` leaks in. A role therefore behaves differently
  on different machines, and a bench number measured here will not reproduce on
  yours. Fixed in 1.1.
- The deny list is a snapshot taken at install. A top-level directory added to
  the project afterwards is denied by nothing. Re-run `install --force` (it
  does not touch memory).
- The plugin ships four roles — `design-scout` (maps a codebase for a build),
  `under-the-hood` (builds what the design decided), `design-hand` (edits the
  design canvas) and `cckit-smith` (finds the gaps in CCKit itself). `$CK roles`
  lists them. Four is not a library; `find-agent` will honestly tell you when
  there is nothing fitting to install.

## Without Python

Every skill degrades to instructions. See `skills/create-agent/by-hand.md`.

MIT.

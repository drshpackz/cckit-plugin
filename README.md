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

Two failures this guards against happen in complete silence, both measured:

- one invalid value makes Claude Code discard the whole `settings.json` in print
  mode — permissions, hooks, everything, without a word;
- an agent card whose frontmatter lacks `name:` is ignored entirely: the answers
  read fine, cost the usual, and the assistant runs the stock prompt.

So the installer writes into a forbidden place and looks at the **disk**, and it
compares the delivered system prompt to the role body **byte for byte**. Until
both pass, nothing is reported as installed.

## Role, instance, memory

A **role** lives in the library and holds no project data — it is reusable. An
**instance** binds one role to one project. What the instance learned lives in
`LEARNED.md` and its memory, and survives `cckit assistant reset`, which rebuilds
everything generated. Open a different project tomorrow and you get a second
instance, not a polluted first one.

## Capabilities are granted, not baked in

Roles reuse across projects; risk is a property of the project. An assistant
reads by default. `--grant web,spawn` adds more, and five groups that leave the
sandbox — `shell`, `peers`, `publish`, `schedule`, `mcp` — need `--i-mean-it`.

## Without Python

Every skill degrades to instructions. See
`skills/create-agent/by-hand.md`.

MIT.

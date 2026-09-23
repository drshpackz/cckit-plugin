---
name: find-agent
description: Use when you are about to write an assistant from scratch, or the user asks whether one already exists for a job — reviewing, researching, watching a build, digging through a codebase.
---

# Finding one that exists

## Look before you build

1. **Installed here** — `cckit assistant list --all`. A role already in the
   library installs into a new project in one command.
2. **Published** — search GitHub for repositories laying out
   `assistants/<role>/card.yaml` beside a `ROLE.md`, and the Claude plugin
   marketplaces for plugins that carry roles.

## Judge before you install

A role is a **system prompt that will run with your credentials**, so read it
before it runs, never after.

- Read `ROLE.md` end to end. It replaces Claude Code's own prompt.
- Read `card.yaml`: `access`, `writes`, and whether it asks for capabilities
  that leave the sandbox — `shell`, `peers`, `publish`, `schedule`, `mcp`.
- Prefer a source you can name. An unknown author with few users is a stranger's
  instructions running as you.
- A role containing absolute paths from someone else's machine was never
  reusable: it will bind to their layout, not yours.

## Install it

```
python3 "${CLAUDE_PLUGIN_ROOT}/bin/cckit_assistant.py"
# короче, если установлен CCKit CLI: cckit assistant install <role> --project <abs path>
```

The probes apply to a downloaded role exactly as to your own: the fence is
tested on your disk, and the prompt is compared byte for byte with what the
model actually received. A published role earns no trust it has not passed.

## Publishing yours

A role is a directory — `card.yaml` and `ROLE.md`, no project data. Push it in
that layout and anyone can install it. Keep paths as `{PROJECT}` and `{HOME}`
placeholders; a path from your machine is what makes a role unshareable.

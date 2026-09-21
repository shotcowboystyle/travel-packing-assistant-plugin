---
name: new-workspace
description: Provision a new trip packing workspace on disk. Use when the user is starting to plan the packing for a specific itinerary — a named route, a set of flights, a trip with a departure date. Scaffolds the workspace files (itinerary.yaml, bags.yaml, inventory.yaml, CLAUDE.md), personalises them from the user's global memory, and by default creates a private GitHub repo.
disable-model-invocation: true
allowed-tools: Bash(mkdir *), Bash(cp *), Bash(ls *), Bash(git init *), Bash(git add *), Bash(git commit *), Bash(git push *), Bash(gh repo create *), Bash(gh auth status), Read, Write, Edit
---

# Provision a Trip Packing Workspace

One workspace per itinerary. The plugin's commands are global once installed; this skill
only creates the **data scaffold** those commands read from and write to.

Separate workspaces per trip is not bureaucracy — allowances, bag tares and the pack that
actually worked are all facts about *that journey*, and a workspace that accumulates several
trips loses the ability to say what a bag weighed leaving home.

## Arguments

`$ARGUMENTS` is parsed as:

- **First positional**: trip name, kebab-case, used as the directory and repo name. Prefer
  a route-and-date form: `bos-ath-tlv-0826`, `tlv-lhr-nov26`. Required.
- **Second positional** (optional): target parent path. Defaults to the topic group under `~/repos/github/` that most specifically fits the subject — see `~/repos/github/README.md` for the group list. (`~/repos/github/my-repos/` is no longer the default; it holds only blog repos now.)
- **`--local-only`**: skip GitHub entirely.
- **`--public`**: create the GitHub repo public. Default is **private** — a packing workspace
  names the dates a home is empty and lists what is worth stealing from it.

```
/travel-packing:new-trip bos-ath-tlv-0826
/travel-packing:new-trip tlv-lhr-nov26 ~/repos/github/personal-admin
/travel-packing:new-trip quick-hop --local-only
```

## Procedure

### 1. Resolve the scaffold

It lives at `${CLAUDE_SKILL_DIR}/../../template/trip/`. Confirm it exists before doing anything
that touches the filesystem.

### 2. Read ambient facts

Read `~/.claude/CLAUDE.md` if present. Extract home city/airport, currency, locale, units and
the user's name. These go into the workspace CLAUDE.md so the later skills do not re-ask.

### 3. Create the workspace

```bash
mkdir -p <target-parent>/<trip-name>
cp -r ${CLAUDE_SKILL_DIR}/../../template/trip/. <target-parent>/<trip-name>/
```

Do not copy any `.claude/` tree — the plugin's commands are already global.

### 4. Personalise

In the new `CLAUDE.md`, replace `{{TRIP_NAME}}`, `{{CREATED_ON}}` (absolute date) and the
ambient facts block. In `itinerary.yaml`, set `trip.id` to the trip name and leave the rest as
the commented skeleton — `/travel-packing:itinerary` fills it in.

### 5. Ask only what cannot be inferred

Two questions, together, then stop:

1. Where are you flying, and when? (one line is enough — the itinerary skill does the detail)
2. How many people are you packing for?

Write the answers into `CLAUDE.md` under "Trip" and into `itinerary.trip`.

Do **not** start researching allowances here. That is `/travel-packing:policies`, and it needs
the full segment list first.

### 6. Git

Unless `--local-only`:

```bash
git init && git add -A && git commit -m "Initialise trip packing workspace: <trip-name>"
gh repo create <trip-name> --private --source=. --push
```

Check `gh auth status` first; if it fails, commit locally, tell the user the repo was not
created, and carry on. A missing remote is not a reason to leave the workspace unbuilt.

### 7. Hand off

Tell the user the path, and that the next step is `/travel-packing:itinerary` to enter the
flights. Name the sequence so they know where they are:

```
itinerary → policies → inventory → weigh → plan → docs
                                      ↑        ↓
                                      └── overage / leave-behind if over
```

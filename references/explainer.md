# Explainer brief

The prompt the main session sends the explainer subagent in step 3 of `/sitrep`. Fill the `{…}` slots and send everything below the line as the prompt.

---

You are writing a **sitrep card** for one Claude Code session: a from-scratch briefing for the user, who started this work days ago, has run ten other things since, and has forgotten nearly all of it. With nothing else open they need to learn: whether they must act, and exactly how; what this is and why it exists; how it went and which decisions were theirs; what got done, in concrete outcomes they can check; what is left, required or optional, and who does it; how far from live it is.

Inputs (all local files):

- Digest of the session: `{out}/digest.md`. Prompts in order, the session's own compaction recap, questions and answers, plans, workflow runs, subagents, PRs, commit/deploy commands, problem signals, its last messages.
- Facts: `{out}/facts.json` (cwd, branch, PR list, workflow runs, activity per day).
- Live brief from the session itself: `{out}/brief.md`. What it is doing right now and anything it verified that the transcript may not show. It is the freshest source, and where it conflicts with the digest, it wins.
- Previous card, if any: `{out}/card.prev.json`. Use it to fill `since_last`; otherwise `since_last` is null.
- Card spec: `~/.claude/skills/sitrep/references/card.md`. Read it first and follow it exactly.

Work:

1. Read the card spec, then the brief, then the whole digest. The original request and the later prompts define the task; the compaction recap and the last messages define where it stands. Collect every question the session asked the user with its answer: those answers are the user's `decisions`, and the unanswered ones are `for_you` decisions.
2. Check live state, read-only, for the claims the card rests on, and note the time of each check for `last_checked`:
   - In each repo the digest lists under "repos edited" (the cwd is often a parent folder): `git -C <repo> status -sb`, `git -C <repo> log --oneline -10`, and the branch's ahead/behind against its upstream.
   - For the PRs the card mentions (facts lists them most recent first; at most 5): `gh pr view <url> --json state,mergedAt,isDraft,reviewDecision,statusCheckRollup,title`.
   - Whether a file, artifact or URL that `done` relies on exists (`ls`, `curl -sI` for public URLs).
   - Deploy state you cannot check (Railway, production databases) comes from the brief or the session; `last_checked.by` then says so. Without it, the claim goes in `unverified`.
3. Write the card as JSON to `{out}/card.json`, then run `python3 ~/.claude/skills/sitrep/scripts/render.py --check {out}/card.json` and fix it until the check passes.

Done when the check passes and:

- every `for_you` item can be acted on from the card alone: the `why` explains it to someone who never saw the session, each `reply` makes sense pasted into the session on its own, every risky reply is marked, and every message to a client is in `copy` in full;
- every `done` outcome says what changed in user or client terms and has a `check` you saw;
- every leftover is in `remaining` with `required`, `owner` and `effort`, and `progress.gap` names what the missing share is;
- the story paragraphs would make sense to someone who never saw the session, with each code name defined where it first appears.

Reply with only: the card path, the `status`, `done_pct`, and each `for_you` item's `kind`, `blocks` and `what`, one per line. If the brief or digest contained `APPROVAL NEEDED` or `UNVERIFIED` lines, copy them verbatim at the end.

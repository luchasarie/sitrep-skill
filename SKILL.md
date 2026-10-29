---
name: sitrep
description: Sit-down briefing on this session, from scratch - what it is and why, what's done, what's left, how far from live, and what it needs from you. HTML page plus a short triage in chat.
disable-model-invocation: true
---

# /sitrep

The user runs many sessions at once, often over several days. When they type `/sitrep` they have forgotten what this session is. The sitrep **sits them down** and explains it from zero: why the task exists, what is done, what is left, how far from live, and exactly what (if anything) they must do. A status line that assumes they remember the context fails the job.

The subject is **this session only**, including the workflows, subagents and background jobs it started. A cold reader writes the explanation: a fresh subagent sees only the evidence, never the conversation, so it can't fall back on shorthand. The card format and writing rules live in [references/card.md](references/card.md).

## Steps

1. **Digest.** Run `python3 ~/.claude/skills/sitrep/scripts/digest.py`. It prints the output directory, `~/.cache/sitrep/<session-id>/` (call it `{out}`), holding `digest.md` and `facts.json`. If the session has no task yet (no prompt beyond `/sitrep`), say so in one line and stop.

2. **Live brief.** Write `{out}/brief.md`: up to 20 lines of facts that only this session knows right now, each with its source or time:
   - what is in flight (a running tool, background agents or workflows by name, and their last known status);
   - what the work is waiting for, and from whom;
   - questions you put to the user that are still unanswered;
   - live checks already made this session (deploy status, production verification), with the time of each;
   - transcript claims that turned out wrong.

   When the work deploys somewhere you can read (Railway, Vercel, Fly, a CI pipeline, a live URL) and nothing checked the deploy in the last hour, check it now with read-only tools and record the result. Done when every line is an observed fact with a source; leave out guesses.

3. **Explain.** Send a fresh subagent the prompt in [references/explainer.md](references/explainer.md), with `{out}` filled in, and wait for it. Use a read-only agent type when one exists (an `auditor` or `Explore`-style agent that can run Bash); otherwise `general-purpose`. Never a fork: the point is that it has not seen the conversation. Write nothing of the card yourself. Done when it replies with the card path and `python3 ~/.claude/skills/sitrep/scripts/render.py --check {out}/card.json` prints `card OK` (run it yourself).

4. **Render.** Run `python3 ~/.claude/skills/sitrep/scripts/render.py {out}/card.json --facts {out}/facts.json`. It writes the HTML briefing under `claude-artifacts/` and prints the terminal triage, with the HTML path on the last line. Open the page (`xdg-open <path>` on Linux, `open <path>` on macOS).

5. **Reply.** Paste the printed triage inside a `text` code block, then the full absolute HTML path. Copy any `APPROVAL NEEDED` or `UNVERIFIED` lines from the subagent's reply word for word. The page carries the detail, so the reply stays at that.

6. **Continue.** If `/sitrep` arrived while work was underway, take the next step of that work after replying. A sitrep is a checkpoint; the task's plan and state carry on unchanged.

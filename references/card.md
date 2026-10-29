# Sitrep card

The card is the JSON the explainer writes and `scripts/render.py` draws. One card per session. The reader is **the user coming back cold**: they started this days ago, ran ten other things since, and remember almost nothing. They scan first, read only when it pays off, and drill in only to act or check something. Every field is written for that reader. `python3 ~/.claude/skills/sitrep/scripts/render.py --check CARD` enforces the mechanical rules below.

## Writing rules

- **Cold reader.** Name things by what they are, not by the session's shorthand ("the size-chart import tool", not "G3"). Define a term in the sentence where it first appears ("Aparência, the new style editor"). `terms` repeats those definitions for the glossary behind the scenes.
- **Language**: the language of the user's own prompts (PT-BR or English). Field names stay English.
- **Outcomes, with detail.** Say what changed for the user or client, with the real numbers ("all 21 product pages load; 10 used to show another product's photos"), not a label.
- **Evidence over memory.** Every `done` item points at something checkable. A claim you could not check goes in `unverified`, or in `caveats` when it changes a decision.
- **Live state wins.** When the transcript and a live check disagree, use the live state and say so in `status_line` or `since_last`.
- Plain sentences, one idea per item. Dates as `Wed 21 Oct`, times as `14:05`.

## The top: verdict and what is the user's

- `one_liner` starts from the ask: "You asked for …".
- `status_line` opens with a verdict ("Almost done: …", "Done and live: …", "Stuck: …").
- `last_checked` is the most recent **live** check of the claim the status rests on (the store, the deploy, the PR state): `when` is the actual time it happened, never "now"; `by` is who checked (`the explainer`, `the session`, or `nobody`); `what` names what was looked at. When the status says something is live or done, the claim is the live thing itself (the store, the deployed app), so a fresher PR or git check doesn't replace it: give the live check's time and mention the PR check in `what`. When it is older than 6 hours or nobody checked, `stale` says what to re-check before relying on it; otherwise `stale` is null.
- `asked_last`: when the user's last prompt was a question ("So we're done?"), the quote and a one-sentence answer. Otherwise null.

### `for_you`: the one list of what is the user's

Every item only the user can decide or do, plus what the work waits on outside. Each has a `kind`:

- `decision`: a choice only the user can make, including a go/no-go where the agent does the work afterwards ("Remove the two test logos?"). An unanswered question the session put to the user is a `decision`.
- `you-fix`: something only the user can do by hand: log in, provide or rotate a key, grant access, run an `apply.sh` with `!`, approve an `APPROVAL NEEDED` package, pay, reply to or send something to a client or teammate.
- `external`: waiting on something outside both of them that the user cannot speed up: CI, a deploy, a background job, a client or teammate who has **already** been asked. Shown as "waiting on", not counted as the user's.

Fields:

- `what`: the decision as a question, or the action as an instruction, in one sentence.
- `why`: why it exists and why it matters, so the user can decide without opening the session.
- `recommend`: what the agent recommends and the reason, one sentence. Null for `external`.
- `blocks`: `true` when required work cannot move until it is resolved; `false` for optional calls and clean-ups.
- `options`: the replies the user can paste into the session, recommended first. `reply` is the exact text, written so the session can act on it alone ("Remove the two test logos on the demo store now."). Mark exactly one `recommended: true` when `recommend` is set: the option that does what `recommend` says. Mark `risky: true` on any reply that makes the agent delete, overwrite, spend money, write to production, or send something outside, or that cannot be undone. A `you-fix` gets one option for after it is done ("I sent Acme the script tag; re-run the live check."). An `external` item has none.
- `copy`: the things to copy, each `{label, text}` with `text` verbatim and complete: the command to run, the URL to open, the full message to send in the recipient's language. The page shows the text before the copy button, so write it as it will be sent.
- `then`: what happens once it is resolved, including who does the work ("I remove them; a few minutes").
- `due`: a date when there is one, else null.

Order: blocking items first, then by due date, then the rest. Nothing is the user's → `[]`.

### `continue`

`text` is what to type to move the session on when `for_you` holds nothing to decide or do; `alts` are up to 3 narrower prompts. The page builds the reply for `for_you` items itself from their options.

`if_waiting`: what it costs if the user does nothing for now, one sentence, when something blocks. Otherwise null.

## Status

`status` is one of:

- `waiting-on-you`: at least one `decision` or `you-fix` item with `blocks: true`.
- `blocked`: the blocking items are all `external`.
- `running`: the agent, a workflow or a background job is working now.
- `idle`: nothing blocks it and nothing runs; it moves when the user says so.
- `done`: every required item is delivered and verified. Optional leftovers and non-blocking `for_you` items may remain.

## Progress

- `done_pct` counts the **required** work only, in steps of 5, weighted by the effort and risk left, not by time spent. Code with no test run or review is not near done: keep a real share for QA, review and verification.
- `100` exactly when the status is `done`. When evidence is thin, take the conservative number and set `confidence: "low"`.
- `basis` says in one sentence why the number is what it is. `gap` says in one sentence what the missing share is ("The last 15%: Acme adds the script, then one live check."); null at 100.

## Track and deploy

The track is the stage diagram. Pick the `kind` that fits and use its stages, adapting names only when the work has a real stage these lack:

- `code`: Understand → Plan → Build → Tests → Review → PR → Merged → Deployed → Verified live
- `ops` (prod config, data fixes, onboarding, migrations): Investigate → Plan → Prepare → Your approval → Apply → Verify
- `research` / `content` / `design`: Brief → Research → Draft → Review → Deliver
- `other`: 3–7 stages you name.

Each stage has `status`: `done`, `current`, `todo`, `blocked`, or `skipped` (with a `note` saying why). Exactly one stage is `current` or `blocked` unless the work is done.

`deploy` applies to any track that ends in something going live. `steps_left` names the **required** steps between now and live and is empty once it is live; optional extras go in `remaining` with `required: false`.

## The story

- `story.origin`: the date and the user's first request, quoted (`quote` up to ~300 chars, `full` the whole prompt when it is longer, else null).
- `story.paragraphs`: at most 4, at most 3 sentences each, as cause and effect. Use the leads "What this is.", "Why it was needed.", "How it went.", "What changed from your ask." (translated for pt-BR), dropping any that has nothing to say.
- `story.more`: optional deeper paragraphs, same shape, for whoever wants the detail.
- `timeline`: the 3–10 turning points, oldest first, each `{date, label, kind}`; drawn on the activity graph.
- `decisions`: one choice per entry, oldest first. `by` is `you` or `agent`. Every answer the user gave and every scope change they asked for mid-session is one of theirs. For the user's, `rec` is `true` when it matched the agent's recommendation, `false` when it didn't, null when there was none. The agent's own calls are the ones a reviewer would want to know about (a colour chosen for legibility, a test stopped before it created data).

## What got done and what is left

- `done`: `outcome` (what changed, in user or client terms), `before` (the state before, or null), and `check`: one or more `{label, url?, path?}` where the user can verify it (the live page, the PR, the receipt, the test run).
- `remaining`: every leftover. `required` true or false; `owner` `you`, `agent`, `client` or `external`; `who` names the client or person when there is one; `effort` in plain words ("a few minutes", "about an hour", "half a day"), null when unknown (not the word "unknown"); `note` optional; `for_you` the id of its `for_you` item when it has one.
- `next_agent`: the agent's own next steps, at most 3. the user's steps live in `for_you` and are not repeated.
- `caveats`: at most 2 things that could bite, only those that change a decision, each `{text, matters}`.
- `workstreams` only when the session runs parallel tracks; otherwise `[]`.

## Schema

```json
{
  "lang": "pt-BR | en",
  "title": "plain name of the task, ≤ 60 chars",
  "one_liner": "You asked for …",
  "status": "waiting-on-you | blocked | running | idle | done",
  "status_line": "verdict first: the state right now",
  "last_checked": {"when": "Mon 26 Oct 21:40", "by": "the explainer | the session | nobody", "what": "what was checked live", "stale": "what to re-check, or null"},
  "asked_last": {"date": "Tue 27 Oct 10:08", "quote": "So we're done?", "answer": "one sentence"},
  "for_you": [{
    "id": "short-slug",
    "kind": "decision | you-fix | external",
    "blocks": true,
    "what": "the question or instruction",
    "why": "why it exists and matters",
    "recommend": "what the agent recommends, and why",
    "due": "Mon 2 Nov or null",
    "options": [{"label": "Remove them now", "reply": "exact text to paste", "recommended": true, "risky": false}],
    "copy": [{"label": "Message to Acme (PT-BR)", "text": "verbatim"}],
    "then": "what happens next, and who does it"
  }],
  "continue": {"text": "what to type when nothing is the user's", "alts": ["narrower prompt"]},
  "if_waiting": "cost of doing nothing, or null",
  "progress": {"done_pct": 65, "basis": "why this number", "confidence": "high | medium | low", "gap": "what the missing share is, or null"},
  "track": {
    "kind": "code | ops | research | content | design | other",
    "stages": [{"name": "Plan", "status": "done | current | todo | blocked | skipped", "note": "optional, short"}]
  },
  "deploy": {"applies": true, "summary": "how far from live, one sentence", "steps_left": ["Review", "Merge", "Deploy", "Verify live"]},
  "workstreams": [{"name": "parallel track", "done_pct": 100, "status": "done | running | blocked | todo", "note": "short"}],
  "story": {
    "origin": {"date": "Wed 21 Oct, 15:01", "quote": "the user's first request", "full": null},
    "paragraphs": [{"lead": "What this is.", "text": "…"}],
    "more": [{"lead": "The first look.", "text": "…"}]
  },
  "timeline": [{"date": "2026-10-21 or 2026-10-21 14:05", "label": "what happened, one line", "kind": "start | milestone | decision | problem | ship"}],
  "decisions": [{"date": "Wed 21 Oct 15:21", "by": "you | agent", "rec": true, "what": "the choice, one sentence"}],
  "done": [{"outcome": "what changed", "before": "the state before, or null", "check": [{"label": "PR #142", "url": "https://…"}, {"label": "Receipt", "path": "/abs/path"}]}],
  "remaining": [{"what": "work still to do", "required": true, "owner": "you | agent | client | external", "who": "Acme or null", "effort": "about an hour", "note": null, "for_you": "short-slug or null"}],
  "next_agent": ["the agent's next step"],
  "caveats": [{"text": "what could bite", "matters": "why it changes a decision"}],
  "since_last": "what changed since the previous sitrep, or null",
  "terms": [{"term": "code name or jargon", "meaning": "plain meaning"}],
  "unverified": ["claims not checked live, and why"],
  "links": [{"label": "PR #142", "url": "https://…"}]
}
```

`asked_last`, `if_waiting`, `since_last`, `due`, `gap` (at 100) and `before` may be null. `for_you`, `options`, `copy`, `decisions`, `next_agent`, `caveats`, `workstreams`, `story.more`, `terms`, `unverified` and `links` may be empty.

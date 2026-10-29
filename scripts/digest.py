#!/usr/bin/env python3
"""Condense one Claude Code session into a sitrep digest.

Reads the session transcript (often tens of MB), its workflow runs and its background-task
notifications, and writes two files to the output directory:

  digest.md   - human-readable evidence for the agent that writes the sitrep card (~5-16k tokens)
  facts.json  - machine facts the renderer draws directly (activity per day, PRs, workflows ...)

A card.json left by the previous sitrep becomes card.prev.json; a stale brief.md is removed.

Usage: digest.py [--session ID] [--out DIR]
  --session  defaults to $CLAUDE_CODE_SESSION_ID (the session running this script)
  --out      defaults to ~/.cache/sitrep/<session-id>/
"""
import argparse
import collections
import glob
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime

PROJECTS = os.path.expanduser('~/.claude/projects')
CONFIG = os.path.expanduser('~/.claude')

REMINDER = re.compile(r'<system-reminder>.*?</system-reminder>', re.S)
PASTE = re.compile(r'<pasted_content[^>]*>(.*?)</pasted_content[^>]*>', re.S)
TAG = re.compile(r'<(task-id|status|summary|tool-use-id)>(.*?)</\1>', re.S)
# Problems the user may have to fix by hand: logins, keys, access, quotas.
AUTH = re.compile(
    r'\b(401|403)\b|unauthori[sz]ed|forbidden|token (has )?expired|session expired|not logged in|'
    r'log ?in (again|required)|re-?authenticat|invalid (api )?key|api key|credential|permission denied|'
    r'access denied|rate.?limit|quota|insufficient|ECONNREFUSED|ENOTFOUND|could not resolve host|'
    r'requires approval|APPROVAL NEEDED|UNVERIFIED',
    re.I)
SHIP = re.compile(
    r'\bgit (commit|push|merge|tag)\b|\bgh pr (create|merge|ready|review)\b|\bgh release\b|'
    r'\brailway (up|redeploy|deploy)\b|\bnpm publish\b|\bvercel( deploy)?\b|\bfly deploy\b|apply\.sh')


def local(ts):
    """ISO timestamp -> aware local datetime, or None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone()
    except ValueError:
        return None


def stamp(ts):
    d = local(ts)
    return d.strftime('%a %d %b %H:%M') if d else '?'


def clip(text, n):
    text = (text or '').strip()
    return text if len(text) <= n else text[:n].rstrip() + f' …[+{len(text) - n} chars]'


def clean_prompt(text):
    text = REMINDER.sub('', text or '')
    text = PASTE.sub(lambda m: f'[pasted: {clip(m.group(1), 300)}]', text)
    return text.strip()


def text_of(content):
    """Text from a message/tool_result content (str or list of blocks)."""
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            if b.get('type') == 'text':
                out.append(b.get('text', ''))
            elif b.get('type') == 'tool_result':
                out.append(text_of(b.get('content')))
    return '\n'.join(out)


def find_transcript(session):
    hits = [p for p in glob.glob(os.path.join(PROJECTS, '*', session + '.jsonl'))]
    if not hits:
        sys.exit(f'digest: no transcript for session {session} under {PROJECTS}')
    return max(hits, key=os.path.getmtime)


def is_human(o, content):
    origin = o.get('origin') or {}
    if origin:
        return origin.get('kind') == 'human'
    if o.get('isMeta') or o.get('toolUseResult') is not None:
        return False
    text = content if isinstance(content, str) else text_of(content)
    if isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
        return False
    return bool(text.strip()) and not text.lstrip().startswith(('<task-notification', '<command-', '<local-command'))


def parse(path):
    s = collections.defaultdict(list)
    s['meta'] = {}
    s['answers'] = {}
    s['agent_results'] = {}
    calls = {}  # tool_use id -> (name, input, ts)
    activity = collections.defaultdict(lambda: {'prompts': 0, 'turns': 0})
    files = collections.Counter()
    tasks = {}
    for line in open(path, encoding='utf-8', errors='replace'):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        t = o.get('type')
        ts = o.get('timestamp')
        meta = s['meta']
        if ts:
            meta.setdefault('first_ts', ts)
            meta['last_ts'] = ts
        if o.get('cwd'):  # cwd = where the session started (artifacts go there); last_cwd follows cd
            meta.setdefault('cwd', o['cwd'])
            meta['last_cwd'] = o['cwd']
        if o.get('gitBranch') and o['gitBranch'] != 'HEAD':
            if meta.get('branch') != o['gitBranch']:
                s['branches'].append((ts, o['gitBranch']))
            meta['branch'] = o['gitBranch']
        if t == 'ai-title':
            meta['title'] = o.get('aiTitle')
        elif t == 'agent-name':
            meta['name'] = o.get('agentName')
        elif t == 'pr-link' and o.get('prUrl'):
            known = [p for p in s['prs'] if p['url'] == o['prUrl']]
            if known:
                known[0]['last_seen'] = ts
            else:
                s['prs'].append({'url': o['prUrl'], 'number': o.get('prNumber'),
                                 'repo': o.get('prRepository'), 'first_seen': ts, 'last_seen': ts})
        elif t == 'system':
            sub = o.get('subtype')
            if sub == 'away_summary':
                s['away'].append((ts, o.get('content', '')))
            elif sub == 'compact_boundary':
                meta['compactions'] = meta.get('compactions', 0) + 1
            elif sub == 'local_command':
                c = o.get('content', '')
                name = re.search(r'<command-name>(.*?)</command-name>', c)
                args = re.search(r'<command-args>(.*?)</command-args>', c, re.S)
                if name and (args and args.group(1).strip()):
                    s['commands'].append((ts, name.group(1), clip(args.group(1), 600)))
            elif sub == 'turn_duration':
                meta['pending_agents'] = o.get('pendingBackgroundAgentCount', 0)
                meta['pending_workflows'] = o.get('pendingWorkflowCount', 0)
        if t not in ('user', 'assistant'):
            continue
        msg = o.get('message') or {}
        content = msg.get('content')
        day = local(ts).strftime('%Y-%m-%d') if local(ts) else '?'
        if o.get('isCompactSummary'):
            s['compact'] = [(ts, text_of(content))]
            continue
        if t == 'user':
            origin = (o.get('origin') or {}).get('kind')
            raw = content if isinstance(content, str) else text_of(content)
            if origin == 'task-notification' or raw.lstrip().startswith('<task-notification'):
                f = dict(TAG.findall(raw))
                if f.get('task-id'):
                    tasks[f['task-id']] = {'status': f.get('status', '?'), 'summary': clip(html.unescape(f.get('summary', '')), 240), 'ts': ts}
                continue
            if is_human(o, content):
                text = clean_prompt(raw)
                if text:
                    s['prompts'].append((ts, text))
                    activity[day]['prompts'] += 1
                continue
            if o.get('toolDenialKind'):
                s['denials'].append((ts, o.get('toolDenialKind')))
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict) or b.get('type') != 'tool_result':
                    continue
                name, inp, cts = calls.get(b.get('tool_use_id'), ('?', {}, ts))
                res = text_of(b.get('content'))
                if name == 'AskUserQuestion':
                    s['answers'][b['tool_use_id']] = clip(res, 1500)
                elif name == 'ExitPlanMode':
                    s['plan_results'].append((ts, clip(res, 200)))
                elif name == 'Agent':
                    s['agent_results'][b['tool_use_id']] = clip(res, 400)
                # Long outputs are usually file or code dumps whose words ("credential", "403") mean nothing.
                hit = AUTH.search(res) if (b.get('is_error') or len(res) < 1500) else None
                if (b.get('is_error') or hit) and name not in ('Read', 'Grep', 'Glob'):
                    at = max(0, hit.start() - 120) if hit else 0
                    s['problems'].append((ts, name, 'auth/access' if hit else 'error', clip(' ⏎ '.join(res[at:at + 600].split('\n')), 260)))
        else:  # assistant
            activity[day]['turns'] += 1
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get('type') == 'text' and b.get('text', '').strip():
                    s['said'].append((ts, re.sub(r'(?m)^.*(Co-Authored-By:|Generated with \[Claude Code\]).*$\n?', '', b['text'])))
                elif b.get('type') == 'tool_use':
                    name, inp = b.get('name'), b.get('input') or {}
                    calls[b.get('id')] = (name, inp, ts)
                    gist = next((inp[k] for k in ('description', 'command', 'file_path', 'prompt', 'query', 'url')
                                 if isinstance(inp.get(k), str) and inp[k].strip()), '')
                    s['recent'].append((ts, name, clip(' '.join(gist.split()), 140)))
                    del s['recent'][:-25]
                    if name == 'AskUserQuestion':
                        s['questions'].append((ts, b.get('id'), inp.get('questions') or []))
                    elif name == 'ExitPlanMode':
                        s['plans'].append((ts, inp.get('plan') or inp.get('planFilePath') or ''))
                    elif name == 'Agent':
                        s['agents'].append((ts, b.get('id'), inp))
                    elif name == 'TaskStop':
                        s['stops'].append((ts, inp.get('task_id') or inp.get('shell_id') or '?'))
                    elif name == 'Workflow':
                        s['workflow_calls'].append((ts, inp.get('name') or inp.get('scriptPath') or 'inline script'))
                    elif name in ('TodoWrite', 'TaskCreate', 'TaskUpdate'):
                        s['todos'] = [(ts, name, inp)]
                    elif name == 'Bash':
                        cmd = inp.get('command', '')
                        if SHIP.search(cmd):
                            s['ship'].append((ts, clip(cmd.replace('\n', ' ⏎ '), 220)))
                    elif name in ('Edit', 'Write', 'NotebookEdit'):
                        p = inp.get('file_path') or inp.get('notebook_path')
                        if p:
                            files[p] += 1
    s['activity'] = dict(sorted(activity.items()))
    s['prs'].sort(key=lambda p: p['last_seen'] or '', reverse=True)
    s['files'] = files
    s['tasks'] = tasks
    return s


def repos(files, cwd):
    """Git repos the session edited files in, most-edited first, with their current branch."""
    seen = collections.Counter()
    for path, n in files.items():
        d = os.path.dirname(path)
        while d and d != '/' and not os.path.isdir(d):
            d = os.path.dirname(d)
        try:
            top = subprocess.run(['git', '-C', d, 'rev-parse', '--show-toplevel'],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            top = ''
        # ~/.claude edits are memory/config upkeep, not the task, unless the session works there.
        if top and (top != CONFIG or (cwd or '').startswith(CONFIG)):
            seen[top] += n
    if not seen and cwd:
        seen[cwd] = 0
    out = []
    for top, n in seen.most_common(6):
        try:
            branch = subprocess.run(['git', '-C', top, 'branch', '--show-current'],
                                    capture_output=True, text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            branch = ''
        out.append({'path': top, 'edits': n, 'branch': branch or '(detached or not a repo)'})
    return out


def workflows(session_dir):
    out = []
    for f in sorted(glob.glob(os.path.join(session_dir, 'workflows', 'wf_*.json')), key=os.path.getmtime):
        try:
            d = json.load(open(f))
        except (ValueError, OSError):
            continue
        prog = d.get('workflowProgress') or []
        phases = [p.get('title') for p in d.get('phases') or []]
        cur = [p for p in prog if p.get('type') == 'workflow_phase']
        agents = [p for p in prog if p.get('type') == 'workflow_agent']
        out.append({
            'run_id': d.get('runId'), 'name': d.get('workflowName'), 'summary': d.get('summary'),
            'status': d.get('status'), 'phases': phases,
            'current_phase': cur[-1].get('title') if cur else None,
            'agents_started': len(agents), 'agent_count': d.get('agentCount'),
            'started': datetime.fromtimestamp(d['startTime'] / 1000).astimezone().isoformat() if d.get('startTime') else None,
            'duration_min': round((d.get('durationMs') or 0) / 60000),
            'logs': [clip(x, 300) for x in (d.get('logs') or [])[-12:]],
            'error': clip((d.get('error') or '').splitlines()[0] if d.get('error') else '', 200),
            'result': clip(json.dumps(d.get('result'), ensure_ascii=False) if d.get('result') is not None else '', 600),
        })
    return out


def pick_prompts(prompts):
    """Keep every prompt, but shorten the middle of long histories."""
    n = len(prompts)
    keep = []
    for i, (ts, text) in enumerate(prompts):
        edge = i < 3 or i >= n - 10
        if n > 60 and 5 <= i < n - 40:
            continue
        keep.append((i + 1, ts, clip(text, 1500 if edge else 350)))
    return keep, max(0, n - 45) if n > 60 else 0


def render_digest(sid, path, s, wfs, rps):
    m = s['meta']
    L = []
    w = L.append
    w(f"# Session digest — {m.get('title') or m.get('name') or sid}\n")
    w(f"- session id: `{sid}` · resume: `claude --resume {sid}`")
    w(f"- name: {m.get('name') or '-'} · started in `{m.get('cwd')}` · last cwd `{m.get('last_cwd')}` · branch: `{m.get('branch') or '-'}`")
    w(f"- started {stamp(m.get('first_ts'))} · last activity {stamp(m.get('last_ts'))} · compactions: {m.get('compactions', 0)}")
    w(f"- background agents pending at last turn end: {m.get('pending_agents', 0)} · workflows pending: {m.get('pending_workflows', 0)}")
    w(f"- transcript: `{path}`")
    w('- repos edited (run git checks here, not in cwd): ' + (', '.join(
        f"`{r['path']}` on `{r['branch']}` ({r['edits']} edits)" for r in rps) or 'none') + '\n')
    w('## Activity per day (prompts from the user / assistant turns)')
    w(' · '.join(f"{d}: {v['prompts']}/{v['turns']}" for d, v in s['activity'].items()) + '\n')
    if s['commands']:
        w('## Slash commands with arguments (goals, loops ...)')
        for ts, name, args in s['commands'][-8:]:
            w(f'- {stamp(ts)} `{name}` {args}')
        w('')
    prompts, omitted = pick_prompts(s['prompts'])
    w(f"## Everything the user asked, in order ({len(s['prompts'])} prompts)")
    if omitted:
        w(f'_({omitted} middle prompts omitted; see the compaction summary)_')
    for i, ts, text in prompts:
        w(f'### #{i} · {stamp(ts)}\n{text}\n')
    if s.get('compact'):
        ts, text = s['compact'][-1]
        w(f'## Latest compaction summary ({stamp(ts)}) — the session\'s own recap of everything before it')
        w(clip(text, 16000) + '\n')
    if s['away']:
        w('## "While you were away" recaps')
        for ts, text in s['away'][-3:]:
            w(f'- {stamp(ts)}: {clip(text, 800)}')
        w('')
    if s['questions']:
        w('## Questions put to the user, and the answers')
        for ts, qid, qs in s['questions'][-15:]:
            heads = '; '.join(f"[{q.get('header', '')}] {clip(q.get('question', ''), 220)}" for q in qs)
            ans = s['answers'].get(qid)
            w(f"- {stamp(ts)} {heads}\n  → {ans if ans else '**NO ANSWER RECORDED (may still be pending)**'}")
        w('')
    if s['plans']:
        ts, plan = s['plans'][-1]
        res = s['plan_results'][-1][1] if s['plan_results'] else 'no result recorded'
        w(f'## Latest plan presented ({stamp(ts)}) — result: {res}')
        w(clip(plan, 5000) + '\n')
    if s.get('todos'):
        ts, name, inp = s['todos'][-1]
        w(f'## Latest task list ({name}, {stamp(ts)})')
        w('```json\n' + clip(json.dumps(inp, ensure_ascii=False, indent=1), 3000) + '\n```\n')
    if wfs:
        w('## Workflow runs started by this session')
        for r in wfs:
            w(f"### {r['name']} · {r['status']} · started {r['started'] and stamp(r['started'])} · {r['duration_min']} min")
            w(f"- {r['summary']}")
            w(f"- phases: {' → '.join(r['phases'])} · last phase reached: {r['current_phase']} · agents: {r['agents_started']}")
            if r['error']:
                w(f"- error: {r['error']}")
            for x in r['logs']:
                w(f'  - log: {x}')
            if r['result']:
                w(f"- result: {r['result']}")
        w('')
    if s['stops']:
        w('## Background tasks the session stopped itself (TaskStop) — a `killed` workflow is usually one of these')
        for ts, tid in s['stops'][-10:]:
            w(f'- {stamp(ts)} stopped {tid}')
        w('')
    if s['agents']:
        w('## Subagents delegated (latest 20)')
        for ts, aid, inp in s['agents'][-20:]:
            bg = ' (background)' if inp.get('run_in_background') else ''
            res = s['agent_results'].get(aid)
            w(f"- {stamp(ts)} {inp.get('subagent_type') or 'general'}{bg}: {clip(inp.get('description', ''), 120)}"
              + (f"\n  → {res}" if res else ''))
        w('')
    if s['tasks']:
        w('## Background task notifications (latest status per task)')
        for tid, v in list(s['tasks'].items())[-15:]:
            w(f"- {stamp(v['ts'])} {tid}: {v['status']} — {v['summary']}")
        w('')
    if s['prs']:
        w(f"## Pull requests linked ({len(s['prs'])}, most recently mentioned first; showing 12)")
        for p in s['prs'][:12]:
            w(f"- {p['url']} (first seen {stamp(p['first_seen'])}, last mentioned {stamp(p['last_seen'])})")
        w('')
    if s['ship']:
        w('## Commit / push / PR / deploy commands run (latest 15)')
        for ts, cmd in s['ship'][-15:]:
            w(f'- {stamp(ts)} `{cmd}`')
        w('')
    if s['files']:
        w('## Files edited most')
        for p, n in s['files'].most_common(15):
            w(f'- {n}× `{p}`')
        w('')
    if s['problems'] or s['denials']:
        w('## Problem signals (errors, auth/access, approvals) — latest 12')
        seen = set()
        for ts, tool, kind, text in reversed(s['problems']):
            key = text[:80]
            if key in seen:
                continue
            seen.add(key)
            w(f'- {stamp(ts)} {tool} [{kind}]: {text}')
            if len(seen) >= 12:
                break
        for ts, kind in s['denials'][-5:]:
            w(f'- {stamp(ts)} tool call declined by the user ({kind})')
        w('')
    if s['recent']:
        w('## Last tool calls (latest 25, oldest first) — what it was doing at the end')
        for ts, name, gist in s['recent']:
            w(f'- {stamp(ts)} {name}: {gist}')
        w('')
    w(f"## Last things the assistant said (latest {min(8, len(s['said']))}, oldest first)")
    for ts, text in s['said'][-8:]:
        w(f'### {stamp(ts)}\n{clip(text, 3000)}\n')
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--session', default=os.environ.get('CLAUDE_CODE_SESSION_ID'))
    ap.add_argument('--out')
    a = ap.parse_args()
    if not a.session:
        sys.exit('digest: no --session and $CLAUDE_CODE_SESSION_ID is unset')
    path = find_transcript(a.session)
    out = a.out or os.path.expanduser(f'~/.cache/sitrep/{a.session}')
    os.makedirs(out, exist_ok=True)
    card = os.path.join(out, 'card.json')
    if os.path.exists(card):  # the explainer diffs against it for since_last
        os.replace(card, os.path.join(out, 'card.prev.json'))
    for stale in ('brief.md',):
        if os.path.exists(os.path.join(out, stale)):
            os.remove(os.path.join(out, stale))
    s = parse(path)
    wfs = workflows(path[:-len('.jsonl')])
    rps = repos(s['files'], s['meta'].get('cwd'))
    digest = render_digest(a.session, path, s, wfs, rps)
    m = s['meta']
    facts = {
        'session_id': a.session, 'title': m.get('title'), 'name': m.get('name'), 'cwd': m.get('cwd'),
        'last_cwd': m.get('last_cwd'),
        'branch': m.get('branch'), 'first_ts': m.get('first_ts'), 'last_ts': m.get('last_ts'),
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'resume': f'claude --resume {a.session}', 'transcript': path,
        'compactions': m.get('compactions', 0), 'prompts': len(s['prompts']), 'repos': rps,
        'activity_by_day': s['activity'], 'prs': s['prs'], 'workflows': wfs,
        'background_tasks': s['tasks'],
        'pending': {'agents': m.get('pending_agents', 0), 'workflows': m.get('pending_workflows', 0),
                    'unanswered_questions': sum(1 for _, q, _ in s['questions'] if q not in s['answers'])},
    }
    open(os.path.join(out, 'digest.md'), 'w').write(digest)
    json.dump(facts, open(os.path.join(out, 'facts.json'), 'w'), ensure_ascii=False, indent=1)
    print(f"{out}/digest.md ({len(digest) // 4} tokens approx)\n{out}/facts.json")


if __name__ == '__main__':
    main()

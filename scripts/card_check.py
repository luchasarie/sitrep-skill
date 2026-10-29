"""Mechanical rules of the sitrep card (references/card.md). Imported by render.py."""

STATUS = {'waiting-on-you', 'blocked', 'running', 'idle', 'done'}
STAGE = {'done', 'current', 'todo', 'blocked', 'skipped'}
TRACK = {'code', 'ops', 'research', 'content', 'design', 'other'}
KIND = {'decision', 'you-fix', 'external'}
OWNER = {'you', 'agent', 'client', 'external'}
TIMELINE = {'start', 'milestone', 'decision', 'problem', 'ship'}
BY = {'you', 'agent'}
REQUIRED = ['lang', 'title', 'one_liner', 'status', 'status_line', 'last_checked', 'for_you', 'continue',
            'progress', 'track', 'deploy', 'story', 'timeline', 'decisions', 'done', 'remaining']


def _list(card, k, p):
    v = card.get(k)
    if v is None:
        return []
    if not isinstance(v, list):
        p.append(f'{k} must be a list')
        return []
    return v


def check(card):
    """Problems with a card, as human-readable strings; empty when it is valid."""
    if not isinstance(card, dict):
        return ['card must be a JSON object']
    p = [f'missing key: {k}' for k in REQUIRED if k not in card]
    if p:
        return p
    status = card['status']
    if status not in STATUS:
        p.append(f'status {status!r} not in {sorted(STATUS)}')
    for k in ('title', 'one_liner', 'status_line'):
        if not card.get(k):
            p.append(f'{k} is empty')

    lc = card['last_checked'] or {}
    for k in ('when', 'by'):
        if not lc.get(k):
            p.append(f'last_checked.{k} is empty')
    if str(lc.get('when', '')).strip().lower() in ('now', 'agora', 'just now'):
        p.append('last_checked.when must be the actual time of the check, not "now"')

    # for_you
    fy = _list(card, 'for_you', p)
    ids = set()
    for i, x in enumerate(fy):
        w = f'for_you[{i}]'
        if not x.get('id'):
            p.append(f'{w}.id is empty')
        elif x['id'] in ids:
            p.append(f'{w}.id {x["id"]!r} is not unique')
        ids.add(x.get('id'))
        kind = x.get('kind')
        if kind not in KIND:
            p.append(f'{w}.kind {kind!r} not in {sorted(KIND)}')
        if not isinstance(x.get('blocks'), bool):
            p.append(f'{w}.blocks must be true or false')
        for k in ('what', 'why'):
            if not x.get(k):
                p.append(f'{w}.{k} is empty')
        opts = x.get('options') or []
        for j, o in enumerate(opts):
            if not o.get('label') or not o.get('reply'):
                p.append(f'{w}.options[{j}] needs label and reply')
        recs = [o for o in opts if o.get('recommended')]
        if kind == 'decision':
            if not opts:
                p.append(f'{w} is a decision without options')
            if x.get('recommend') and len(recs) != 1:
                p.append(f'{w} has a recommendation, so exactly one option must be recommended (found {len(recs)})')
        if kind == 'you-fix' and not opts:
            p.append(f'{w} is a you-fix without the reply to paste once it is done')
        if kind == 'external' and opts:
            p.append(f'{w} is external, so it has no options')
        for j, c in enumerate(x.get('copy') or []):
            if not c.get('label') or not c.get('text'):
                p.append(f'{w}.copy[{j}] needs label and text')

    blocking = {x.get('kind') for x in fy if x.get('blocks') is True}
    want = 'waiting-on-you' if blocking & {'decision', 'you-fix'} else 'blocked' if blocking else None
    if want and status != want:
        p.append(f'blocking for_you items of kind {sorted(blocking)} mean status should be {want!r}, not {status!r}')
    if not want and status in ('waiting-on-you', 'blocked'):
        p.append(f'status {status!r} needs at least one for_you item with blocks: true')

    co = card['continue'] or {}
    if not fy and not co.get('text'):
        p.append('continue.text is empty and nothing is in for_you')

    # progress
    pr = card['progress'] or {}
    pct = pr.get('done_pct')
    if not isinstance(pct, int) or isinstance(pct, bool) or not 0 <= pct <= 100 or pct % 5:
        p.append(f'progress.done_pct {pct!r} must be an integer 0–100 in steps of 5')
    if (pct == 100) != (status == 'done'):
        p.append(f'done_pct is {pct} and status is {status!r}: 100 exactly when done')
    if pr.get('confidence') not in ('high', 'medium', 'low'):
        p.append('progress.confidence must be high, medium or low')
    if not pr.get('basis'):
        p.append('progress.basis is empty')
    if isinstance(pct, int) and pct < 100 and not pr.get('gap'):
        p.append('progress.gap is empty: say what the missing share is')

    # track and deploy
    tr = card['track'] or {}
    if tr.get('kind') not in TRACK:
        p.append(f"track.kind {tr.get('kind')!r} not in {sorted(TRACK)}")
    stages = tr.get('stages') or []
    if not 2 <= len(stages) <= 10:
        p.append(f'track.stages has {len(stages)} stages; expected 2–10')
    for s in stages:
        if s.get('status') not in STAGE:
            p.append(f"stage {s.get('name')!r} status {s.get('status')!r} not in {sorted(STAGE)}")
    live = [s for s in stages if s.get('status') in ('current', 'blocked')]
    if status != 'done' and len(live) != 1:
        p.append(f'exactly one stage must be current or blocked while not done; found {len(live)}')
    if status == 'done' and any(s.get('status') in ('todo', 'current', 'blocked') for s in stages):
        p.append('status is done but some stages are still todo/current/blocked')
    dp = card['deploy'] or {}
    if not isinstance(dp.get('applies'), bool):
        p.append('deploy.applies must be true or false')

    # story
    st = card['story'] or {}
    if not (st.get('origin') or {}).get('quote'):
        p.append('story.origin.quote is empty')
    paras = st.get('paragraphs') or []
    if not 1 <= len(paras) <= 4:
        p.append(f'story.paragraphs has {len(paras)}; expected 1–4')
    for i, para in enumerate(paras + (st.get('more') or [])):
        if not para.get('text'):
            p.append(f'story paragraph {i} has no text')
    tl = _list(card, 'timeline', p)
    if len(tl) > 12:
        p.append(f'timeline has {len(tl)} entries; keep the turning points (3–10)')
    for i, s in enumerate(tl):
        if s.get('kind') not in TIMELINE:
            p.append(f"timeline[{i}].kind {s.get('kind')!r} not in {sorted(TIMELINE)}")
        if not s.get('date') or not s.get('label'):
            p.append(f'timeline[{i}] needs date and label')
    for i, d in enumerate(_list(card, 'decisions', p)):
        if d.get('by') not in BY:
            p.append(f"decisions[{i}].by {d.get('by')!r} not in {sorted(BY)}")
        if not d.get('what'):
            p.append(f'decisions[{i}].what is empty')

    # done and remaining
    for i, d in enumerate(_list(card, 'done', p)):
        if not d.get('outcome'):
            p.append(f'done[{i}].outcome is empty')
        chk = d.get('check') or []
        if not chk:
            p.append(f'done[{i}] needs at least one check')
        for j, c in enumerate(chk):
            if not c.get('label'):
                p.append(f'done[{i}].check[{j}].label is empty')
    req_open = False
    for i, r in enumerate(_list(card, 'remaining', p)):
        if not r.get('what'):
            p.append(f'remaining[{i}].what is empty')
        if not isinstance(r.get('required'), bool):
            p.append(f'remaining[{i}].required must be true or false')
        req_open |= r.get('required') is True
        if r.get('owner') not in OWNER:
            p.append(f"remaining[{i}].owner {r.get('owner')!r} not in {sorted(OWNER)}")
        if str(r.get('effort') or '').strip().lower() in ('unknown', 'desconhecido', 'n/a', '?'):
            p.append(f'remaining[{i}].effort says {r["effort"]!r}; use null when the effort is unknown')
        if r.get('for_you') and r['for_you'] not in ids:
            p.append(f"remaining[{i}].for_you {r['for_you']!r} is not a for_you id")
    if status == 'done' and req_open:
        p.append('status is done but remaining still has required items')
    if len(_list(card, 'next_agent', p)) > 3:
        p.append('next_agent has more than 3 steps')
    if len(_list(card, 'caveats', p)) > 2:
        p.append('caveats has more than 2 entries; keep the ones that change a decision')
    for k in ('workstreams', 'terms', 'unverified', 'links'):
        _list(card, k, p)
    return p

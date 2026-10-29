#!/usr/bin/env python3
"""Validate and render a sitrep card (see references/card.md).

  render.py --check CARD                      validate only; exit 1 with one problem per line
  render.py CARD --facts FACTS [--out HTML]   write the HTML briefing, print the terminal triage

Without --out the HTML goes to claude-artifacts/YYYY-MM-DD-sitrep-<slug>.html in the session's
repo root (the main checkout when the cwd is a worktree), or ~/Documents/claude-artifacts/ when
the cwd is $HOME, a temp dir or not a repo. The last line printed is the HTML path.

Every count on the page ("1 to decide · 1 to do", rail and chip counts, the verdict) is derived
here from the card's for_you items; the card never carries them.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import textwrap
from collections import Counter
from datetime import date, datetime, timedelta

from card_check import check  # noqa: E402  (the card rules live in card_check.py)


def artifact_path(cwd, title):
    """claude-artifacts/<date>-sitrep-<slug>.html (override with --out)."""
    home = os.path.expanduser('~')
    root = None
    if cwd and os.path.isdir(cwd):
        try:
            common = subprocess.run(['git', '-C', cwd, 'rev-parse', '--path-format=absolute', '--git-common-dir'],
                                    capture_output=True, text=True, timeout=5).stdout.strip()
            if common:
                root = os.path.dirname(common) if common.endswith('/.git') else None
        except (OSError, subprocess.SubprocessError):
            pass
    if not root or os.path.realpath(root) == os.path.realpath(home) or root.startswith('/tmp'):
        root = os.path.join(home, 'Documents')
    slug = re.sub(r'[^a-z0-9]+', '-', (title or 'session').lower()).strip('-')[:50] or 'session'
    return os.path.join(root, 'claude-artifacts', f"{datetime.now():%Y-%m-%d}-sitrep-{slug}.html")


# ── Labels ──────────────────────────────────────────────────────────────────────────────────

def _pl(n, one, many):
    return one if n == 1 else many


LABELS = {
    'en': {
        'status': {'waiting-on-you': 'Waiting on you', 'blocked': 'Blocked', 'running': 'Running',
                   'idle': 'Idle', 'done': 'Done'},
        'stage': {'done': 'done', 'current': 'now', 'blocked': 'blocked', 'todo': 'to do', 'skipped': 'skipped'},
        'story': {'start': 'Start', 'milestone': 'Milestone', 'decision': 'Decision', 'problem': 'Problem',
                  'ship': 'Shipped'},
        'conf': {'high': 'high', 'medium': 'medium', 'low': 'low'},
        'wd': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'mo': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
        # counts and verdict
        'n_decide': lambda n: f'{n} to decide', 'n_do': lambda n: f'{n} to do', 'n_wait': lambda n: f'waiting on {n}',
        'v_on_you': 'Blocked on you', 'v_others': 'Waiting on others', 'v_free': 'Nothing blocks the work',
        'v_none': 'Nothing needs you.', 'v_none_done': 'There is nothing to type; this session can be closed.',
        'v_blocks': lambda nb, n: ((_pl(nb, 'it blocks the work', 'both block the work') if nb <= 2 else 'all block the work')
                                   if nb == n else f'{nb} {_pl(nb, "blocks", "block")} the work, {n - nb} can wait'),
        'v_optional': lambda n: _pl(n, 'optional', 'all optional'), 'v_due': lambda d: f'one due {d}',
        'v_nothing_you': 'nothing for you to do', 'v_none_block': 'none blocks the work',
        # short version
        'sv': 'Short version', 'nothing_yours': 'Nothing yours',
        'defn': 'Only you can decide or do these. "Waiting on" items are outside both of us and are not counted as yours.',
        'checked': 'Last checked live:', 'by_who': lambda w, b: f'{w}, by {b}',
        'before_page': lambda a: f'{a} before this sitrep was made', 'after_page': 'after this sitrep was made',
        'nobody': 'Nobody has checked this live.', 'old': 'Older than 6 h', 'stale_lbl': 'Re-check:',
        'by_map': {'the explainer': 'the sitrep agent', 'the session': 'the session', 'nobody': 'nobody'},
        'asked': lambda q, d: f'You asked “{q}” ({d}).',
        'grp': {'decision': 'You decide', 'you-fix': 'You do', 'external': 'Waiting on'},
        'blocks': 'Blocks the work', 'optional': 'Optional', 'due': lambda d: f'Due {d}',
        'rec': 'I recommend:', 'why': 'Why:', 'then': 'Then:', 'wait': 'If you wait:',
        'reply_dec': 'Your answer', 'reply_fix': 'When it is done, reply', 'include': 'Put in my reply',
        'recommended': 'Recommended', 'risky': 'Risky',
        'risky_t': 'Deletes, overwrites, spends money, writes to production, sends something outside, or cannot be undone',
        'risky_off': 'Left out until you tick it, because the recommended answer is risky.',
        'fix_off': 'Tick it once you have done it: this reply tells the session it is done.',
        'composer': 'Your reply to paste into the session', 'compose_tpl': '{n} of {t} items in the reply',
        'compose_empty': 'Nothing ticked yet. Tick an item above to build the reply.', 'copy_reply': 'Copy reply',
        'continue': 'To move the session on, type:', 'narrower': 'Or something narrower:',
        'bite': 'What could bite', 'resume_term': 'Or resume from a terminal',
        'show_all': 'Show all', 'show_less': 'Show less',
        # where it stands
        'stands': 'Where it stands', 'progress': 'Progress', 'done_word': 'done', 'left_word': 'left',
        'confidence': 'Confidence', 'stages': 'Stages', 'gap': 'Still missing:',
        'pdef': lambda p: f'What {p}% means',
        'pdef_t': 'The share of the required work done, weighted by the effort and risk left, not by time spent. '
                  'It reaches 100% only when the work is delivered and verified.',
        'steps_live': lambda n: f"{n} step{'s' if n != 1 else ''} from live", 'is_live': 'Live',
        'all_stages': 'All stages done',
        # story
        'story_t': 'The story so far', 'you_asked': lambda d: f'{d} · you asked', 'full_req': 'Your full first message',
        'more_story': lambda n: f"More of the story · {n} paragraph{'s' if n != 1 else ''}",
        'activity': 'Activity per day', 'turns': 'turns', 'prompts': 'prompts', 'timeline': 'Turning points',
        'busiest': 'Busiest', 'last_active': 'last active', 'quiet': lambda n: f"quiet for {n} day{'s' if n != 1 else ''}",
        'active_today': 'active today', 'over_days': lambda n: f"over {n} day{'s' if n != 1 else ''}",
        # decisions
        'dec_t': 'Decisions along the way', 'dec_aside': lambda y, a: f'{y} by you · {a} by the agent',
        'dec_you': lambda n: f'Yours ({n})', 'dec_agent': lambda n: f"The agent's ({n})",
        'as_rec': 'As the agent recommended', 'not_rec': 'Not the option the agent recommended',
        'more_agent': lambda n: f"Show {n} more · the agent's",
        # work
        'done_t': 'Done', 'before': 'Before:', 'left_t': "What's left",
        'left_aside': lambda r, o: f"{f'{r} required' if r else 'nothing required'} · {o} optional",
        'req': "Required before it's done", 'opt': 'Optional', 'no_left': 'Nothing is left.',
        'more_opt': lambda n: f'Show {n} more optional', 'who': 'Who:', 'not_est': 'not estimated',
        'owner': {'you': 'You', 'agent': 'The agent', 'client': 'Client', 'external': 'External'},
        'next_t': 'Next steps', 'agent_badge': 'Agent', 'ws_t': 'Workstreams', 'since_t': 'Since the last sitrep',
        'links_t': 'Links and PRs', 'all_prs': lambda n: f"All {n} PR{'s' if n != 1 else ''} mentioned in the session",
        'prs_more': lambda n: f"{n} more PR{'s' if n != 1 else ''}", 'seen': 'seen',
        # behind the scenes
        'behind': 'Behind the scenes', 'terms_t': 'Glossary', 'wf_t': 'Workflows and background jobs',
        'unv_t': 'Unverified', 'unv_sub': 'claims nobody checked live',
        'behind_parts': {'terms': 'glossary', 'wf': 'workflows and jobs', 'unv': 'unverified claims'},
        'agents': 'agents', 'min': 'min', 'started': 'started', 'log': lambda n: f"Log ({n} line{'s' if n != 1 else ''})",
        'bg': lambda n: f"{n} background job{'s' if n != 1 else ''}", 'bg_open': 'Not completed',
        'still_running': 'Still running', 'nothing_running': 'Nothing is running now.',
        'wf_status': {'completed': 'Completed', 'running': 'Running', 'killed': 'Killed', 'failed': 'Failed',
                      'stopped': 'Stopped', 'aborted': 'Aborted'},
        # chrome
        'sitrep': 'Sitrep', 'generated': 'generated', 'session': 'session', 'resume': 'Resume this session',
        'copy': 'Copy', 'copied': 'Copied ✓', 'copy_fail': 'Select and copy',
        'started_t': 'Started', 'last_active_t': 'last active', 'ran': lambda d: f'ran {d}',
        'ago': lambda d: f'{d} ago', 'just_now': 'just now', 'days_n': lambda n: f"{n} day{'s' if n != 1 else ''}",
        'under_min': 'less than a minute',
        'cwd': 'Working folder', 'repos': 'Repos', 'branch': 'Branch', 'transcript': 'Transcript',
        'generated_at': 'Generated', 'session_id': 'Session', 'edits': 'edits', 'length_t': 'Length',
        'compactions': lambda n: f"{n} compaction{'s' if n != 1 else ''}",
        'glance': 'At a glance', 'rail': 'On this page', 'jump': 'Jump to section',
        'j': {'short': 'For you', 'stand': 'Progress', 'story': 'Story', 'dec': 'Decisions', 'work': 'Work',
              'behind': 'Behind'},
        # terminal
        't_reply': 'reply', 't_other': 'other options', 't_copy': 'copy', 't_rec': 'recommend',
        't_checked': 'Last checked', 't_stale': 'STALE', 't_type': 'type', 't_more': lambda n: f'+{n} more on the page',
        't_grp': {'decision': 'YOU DECIDE', 'you-fix': 'YOU DO', 'external': 'WAITING ON'},
    },
    'pt-BR': {
        'status': {'waiting-on-you': 'Esperando você', 'blocked': 'Bloqueado', 'running': 'Em andamento',
                   'idle': 'Parado', 'done': 'Concluído'},
        'stage': {'done': 'feito', 'current': 'agora', 'blocked': 'bloqueado', 'todo': 'a fazer', 'skipped': 'pulado'},
        'story': {'start': 'Início', 'milestone': 'Marco', 'decision': 'Decisão', 'problem': 'Problema',
                  'ship': 'Entregue'},
        'conf': {'high': 'alta', 'medium': 'média', 'low': 'baixa'},
        'wd': ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'],
        'mo': ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'],
        'n_decide': lambda n: f'{n} para decidir', 'n_do': lambda n: f'{n} para fazer',
        'n_wait': lambda n: f'aguardando {n}',
        'v_on_you': 'Bloqueado em você', 'v_others': 'Aguardando terceiros', 'v_free': 'Nada trava o trabalho',
        'v_none': 'Nada depende de você.', 'v_none_done': 'Não há o que digitar; esta sessão pode ser fechada.',
        'v_blocks': lambda nb, n: ((_pl(nb, 'trava o trabalho', 'os dois travam o trabalho') if nb <= 2 else 'todos travam o trabalho')
                                   if nb == n else f'{nb} {_pl(nb, "trava", "travam")} o trabalho, {n - nb} {_pl(n - nb, "pode", "podem")} esperar'),
        'v_optional': lambda n: _pl(n, 'opcional', 'todos opcionais'), 'v_due': lambda d: f'um vence {d}',
        'v_nothing_you': 'nada para você fazer', 'v_none_block': 'nenhum trava o trabalho',
        'sv': 'Resumo', 'nothing_yours': 'Nada seu',
        'defn': 'Só você pode decidir ou fazer estes itens. Os de "Aguardando" estão fora do alcance de nós dois e não contam como seus.',
        'checked': 'Conferido no ar:',
        'by_who': lambda w, b: f'{w}, ' + (f'pelo {b[2:]}' if b.startswith('o ') else f'pela {b[2:]}' if b.startswith('a ') else f'por {b}'),
        'before_page': lambda a: f'{a} antes deste sitrep', 'after_page': 'depois deste sitrep',
        'nobody': 'Ninguém conferiu isto no ar.', 'old': 'Mais de 6 h', 'stale_lbl': 'Conferir de novo:',
        'by_map': {'the explainer': 'o agente do sitrep', 'the session': 'a sessão', 'nobody': 'ninguém'},
        'asked': lambda q, d: f'Você perguntou “{q}” ({d}).',
        'grp': {'decision': 'Você decide', 'you-fix': 'Você faz', 'external': 'Aguardando'},
        'blocks': 'Trava o trabalho', 'optional': 'Opcional', 'due': lambda d: f'Prazo {d}',
        'rec': 'Recomendo:', 'why': 'Por quê:', 'then': 'Depois:', 'wait': 'Se esperar:',
        'reply_dec': 'Sua resposta', 'reply_fix': 'Quando estiver feito, responda', 'include': 'Pôr na minha resposta',
        'recommended': 'Recomendada', 'risky': 'Arriscada',
        'risky_t': 'Apaga, sobrescreve, gasta dinheiro, grava em produção, envia algo para fora ou não tem volta',
        'risky_off': 'Fica fora até você marcar, porque a resposta recomendada é arriscada.',
        'fix_off': 'Marque depois de fazer: esta resposta avisa a sessão que já foi feito.',
        'composer': 'Sua resposta para colar na sessão', 'compose_tpl': '{n} de {t} itens na resposta',
        'compose_empty': 'Nada marcado ainda. Marque um item acima para montar a resposta.', 'copy_reply': 'Copiar resposta',
        'continue': 'Para seguir com a sessão, digite:', 'narrower': 'Ou algo mais específico:',
        'bite': 'O que pode dar errado', 'resume_term': 'Ou retome pelo terminal',
        'show_all': 'Mostrar tudo', 'show_less': 'Mostrar menos',
        'stands': 'Onde está', 'progress': 'Progresso', 'done_word': 'feito', 'left_word': 'falta',
        'confidence': 'Confiança', 'stages': 'Etapas', 'gap': 'O que falta:',
        'pdef': lambda p: f'O que {p}% quer dizer',
        'pdef_t': 'A parte do trabalho obrigatório já feita, pesada pelo esforço e risco que faltam, não pelo tempo gasto. '
                  'Só chega a 100% quando está entregue e conferido.',
        'steps_live': lambda n: f"{'Falta' if n == 1 else 'Faltam'} {n} etapa{'s' if n != 1 else ''} para ir ao ar",
        'is_live': 'No ar', 'all_stages': 'Todas as etapas feitas',
        'story_t': 'A história até aqui', 'you_asked': lambda d: f'{d} · você pediu', 'full_req': 'Sua primeira mensagem completa',
        'more_story': lambda n: f"Mais da história · {n} parágrafo{'s' if n != 1 else ''}",
        'activity': 'Atividade por dia', 'turns': 'turnos', 'prompts': 'mensagens', 'timeline': 'Pontos de virada',
        'busiest': 'Dia mais cheio', 'last_active': 'última atividade', 'quiet': lambda n: f"parada há {n} dia{'s' if n != 1 else ''}",
        'active_today': 'ativa hoje', 'over_days': lambda n: f"em {n} dia{'s' if n != 1 else ''}",
        'dec_t': 'Decisões no caminho', 'dec_aside': lambda y, a: f'{y} suas · {a} do agente',
        'dec_you': lambda n: f'Suas ({n})', 'dec_agent': lambda n: f'Do agente ({n})',
        'as_rec': 'Como o agente recomendou', 'not_rec': 'Não era a opção recomendada',
        'more_agent': lambda n: f'Mostrar mais {n} · do agente',
        'done_t': 'Pronto', 'before': 'Antes:', 'left_t': 'O que falta',
        'left_aside': lambda r, o: f"{f'{r} obrigatórios' if r else 'nada obrigatório'} · {o} opcionais",
        'req': 'Obrigatório para terminar', 'opt': 'Opcional', 'no_left': 'Não falta nada.',
        'more_opt': lambda n: f'Mostrar mais {n} opcionais', 'who': 'Quem:', 'not_est': 'não estimado',
        'owner': {'you': 'Você', 'agent': 'O agente', 'client': 'Cliente', 'external': 'Terceiros'},
        'next_t': 'Próximos passos', 'agent_badge': 'Agente', 'ws_t': 'Frentes de trabalho', 'since_t': 'Desde o último sitrep',
        'links_t': 'Links e PRs',
        'all_prs': lambda n: f"{'Todos os' if n != 1 else 'O'} {n} PR{'s' if n != 1 else ''} citado{'s' if n != 1 else ''} na sessão",
        'prs_more': lambda n: f"mais {n} PR{'s' if n != 1 else ''}", 'seen': 'visto',
        'behind': 'Bastidores', 'terms_t': 'Glossário', 'wf_t': 'Workflows e tarefas em segundo plano',
        'unv_t': 'Não conferido', 'unv_sub': 'afirmações que ninguém conferiu no ar',
        'behind_parts': {'terms': 'glossário', 'wf': 'workflows e tarefas', 'unv': 'afirmações não conferidas'},
        'agents': 'agentes', 'min': 'min', 'started': 'início', 'log': lambda n: f"Log ({n} linha{'s' if n != 1 else ''})",
        'bg': lambda n: f"{n} tarefa{'s' if n != 1 else ''} em segundo plano", 'bg_open': 'Não concluídas',
        'still_running': 'Ainda rodando', 'nothing_running': 'Nada está rodando agora.',
        'wf_status': {'completed': 'Concluído', 'running': 'Rodando', 'killed': 'Interrompido', 'failed': 'Falhou',
                      'stopped': 'Parado', 'aborted': 'Abortado'},
        'sitrep': 'Sitrep', 'generated': 'gerado', 'session': 'sessão', 'resume': 'Retomar esta sessão',
        'copy': 'Copiar', 'copied': 'Copiado ✓', 'copy_fail': 'Selecione e copie',
        'started_t': 'Começou', 'last_active_t': 'última atividade', 'ran': lambda d: f'{d} de sessão',
        'ago': lambda d: f'há {d}', 'just_now': 'agora há pouco', 'days_n': lambda n: f"{n} dia{'s' if n != 1 else ''}",
        'under_min': 'menos de um minuto',
        'cwd': 'Pasta de trabalho', 'repos': 'Repositórios', 'branch': 'Branch', 'transcript': 'Transcrição',
        'generated_at': 'Gerado', 'session_id': 'Sessão', 'edits': 'edições', 'length_t': 'Tamanho',
        'compactions': lambda n: f"{n} compactaç{'ões' if n != 1 else 'ão'}",
        'glance': 'Resumo rápido', 'rail': 'Nesta página', 'jump': 'Ir para a seção',
        'j': {'short': 'Para você', 'stand': 'Progresso', 'story': 'História', 'dec': 'Decisões', 'work': 'Trabalho',
              'behind': 'Bastidores'},
        't_reply': 'resposta', 't_other': 'outras opções', 't_copy': 'copiar', 't_rec': 'recomendo',
        't_checked': 'Conferido', 't_stale': 'DESATUALIZADO', 't_type': 'digite', 't_more': lambda n: f'+{n} na página',
        't_grp': {'decision': 'VOCÊ DECIDE', 'you-fix': 'VOCÊ FAZ', 'external': 'AGUARDANDO'},
    },
}


def labels(card):
    return LABELS['pt-BR'] if str(card.get('lang') or '').lower().startswith('pt') else LABELS['en']


# ── Text helpers ────────────────────────────────────────────────────────────────────────────

def _s(v):
    """A display string: None → '', HTML entities the digest left in (&amp;) decoded."""
    if v is None:
        return ''
    return html.unescape(str(v))


def esc(v):
    return html.escape(_s(v), quote=True)


URL_RE = re.compile(r'https?://[^\s<>"\'`]+')
TAG_RE = re.compile(r'<[a-zA-Z][^<>]*>(?:[^<>]*</[a-zA-Z][a-zA-Z0-9]*>)?')
CMD_RE = re.compile(r'^\$?\s*(?:git|gh|npm|npx|pnpm|yarn|node|python3?|pip|claude|op|railway|curl|wget|cd|ls|cat|bash|sh|'
                    r'ssh|scp|docker|psql|make|sudo|pkexec|rg|grep|sed|kubectl|uv|cargo|bun|deno|xdg-open|systemctl|!)\b')
PATH_RE = re.compile(r'^(?:~|\.{1,2})?/[^\s]+$')


def safe_url(u):
    u = _s(u).strip()
    return u if re.match(r'^https?://', u, re.I) else None


def _linkify(text):
    out, pos = [], 0
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip('.,;:)]')
        out.append(html.escape(text[pos:m.start()]))
        out.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(url)}</a>')
        pos = m.start() + len(url)
    out.append(html.escape(text[pos:]))
    return ''.join(out)


def rich(v):
    """Escaped text with `code` spans (and pasted <tags>) as <code>, and http(s) URLs as links."""
    s = TAG_RE.sub(lambda m: '`' + m.group(0) + '`' if '`' not in m.group(0) else m.group(0), _s(v))
    parts = s.split('`')
    if len(parts) % 2 == 0:          # unmatched backtick: keep the last one as text
        parts[-2] = parts[-2] + '`' + parts.pop()
    return ''.join(f'<code>{html.escape(p)}</code>' if i % 2 else _linkify(p) for i, p in enumerate(parts))


def is_code(text):
    """True for a command, tag, URL or path (shown in monospace); False for a message (prose)."""
    t = _s(text).strip()
    if '\n' in t:
        return False
    return bool(t.startswith('<') or CMD_RE.match(t) or safe_url(t) or PATH_RE.match(t) or ' ' not in t)


def slug(v):
    return re.sub(r'[^a-z0-9-]+', '-', _s(v).lower()).strip('-') or 'x'


def parse_ts(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace('Z', '+00:00'))
    except ValueError:
        return None
    return dt.astimezone() if dt.tzinfo else dt


def parse_day(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


MONTHS = {m: k + 1 for k, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}
MONTHS.update({'fev': 2, 'abr': 4, 'mai': 5, 'ago': 8, 'set': 9, 'out': 10, 'dez': 12})


def parse_when(v, ref):
    """A card time like 'Wed 28 Oct 13:05' (or an ISO time) as a datetime in ref's zone; None if unreadable."""
    s = _s(v).strip()
    iso = parse_ts(s) if re.match(r'^\d{4}-\d{2}-\d{2}', s) else None
    if iso:
        return iso if iso.tzinfo else iso.replace(tzinfo=ref.tzinfo)
    m = re.search(r'(\d{1,2})\s+([A-Za-zçÇ]{3})[a-zç]*\.?,?\s+(?:(\d{4}),?\s+)?(\d{1,2})[:h](\d{2})', s)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    try:
        d = datetime(int(m.group(3) or ref.year), MONTHS[m.group(2).lower()], int(m.group(1)),
                     int(m.group(4)), int(m.group(5)), tzinfo=ref.tzinfo)
    except ValueError:
        return None
    if not m.group(3) and d - ref > timedelta(days=2):
        d = d.replace(year=d.year - 1)
    return d


def fmt_day(d, L):
    return f"{L['wd'][d.weekday()]} {d.day} {L['mo'][d.month - 1]}"


def fmt_dt(dt, L):
    return f'{fmt_day(dt, L)}, {dt:%H:%M}'


def day_label(v, L):
    d = parse_day(v)
    return fmt_day(d, L) if d else _s(v)


def lst(v):
    return v if isinstance(v, list) else []


def dicts(v):
    return [x for x in lst(v) if isinstance(x, dict)]


def pct(v):
    try:
        return max(0, min(100, int(v)))
    except (TypeError, ValueError):
        return 0


def ago_text(seconds, L):
    s = max(0, int(seconds))
    if s < 60:
        return L['just_now']
    if s < 3600:
        return L['ago'](f'{s // 60} min')
    if s < 48 * 3600:
        return L['ago'](f'{s // 3600} h')
    return L['ago'](L['days_n'](s // 86400))


def dur_text(seconds, L):
    """A bare duration ('5 min', '3 h', '2 days') for 'X before this sitrep'."""
    s = max(0, int(seconds))
    if s < 60:
        return L['under_min']
    if s < 3600:
        return f'{s // 60} min'
    if s < 48 * 3600:
        return f'{s // 3600} h'
    return L['days_n'](s // 86400)


def live_index(stages):
    """Index the progress line is filled up to: the current/blocked stage, else the last done one."""
    for k, st in enumerate(stages):
        if st.get('status') in ('current', 'blocked'):
            return k
    done = [k for k, st in enumerate(stages) if st.get('status') in ('done', 'skipped')]
    return done[-1] if done else -1


def span_text(first, last, L):
    """How long the session ran: minutes or hours within a day, calendar days across days."""
    if first.date() != last.date():
        return L['days_n']((last.date() - first.date()).days + 1)
    m = max(1, int((last - first).total_seconds() // 60))
    return f'{m} min' if m < 60 else f'{m // 60} h'


# ── What is the user's: one derivation used by every count on the page and in the terminal ──────

KINDS = ('decision', 'you-fix', 'external')


class Yours:
    def __init__(self, card):
        self.items = dicts(card.get('for_you'))
        self.by_id = {x.get('id'): x for x in self.items}
        self.mine = [x for x in self.items if x.get('kind') in ('decision', 'you-fix')]
        self.ext = [x for x in self.items if x.get('kind') == 'external']
        self.n = Counter(x.get('kind') for x in self.items)
        self.blocking_mine = [x for x in self.mine if x.get('blocks') is True]
        self.blocking_ext = [x for x in self.ext if x.get('blocks') is True]

    def groups(self):
        """[(kind, items)] decide / do / waiting, with a group holding a blocking item first."""
        gs = [(k, [x for x in self.items if x.get('kind') == k]) for k in KINDS]
        gs = [g for g in gs if g[1]]
        return sorted(gs, key=lambda g: (not any(x.get('blocks') is True for x in g[1]), KINDS.index(g[0])))

    def split(self, L, items=None, wait=False):
        n = self.n if items is None else Counter(x.get('kind') for x in items)
        bits = []
        if n['decision']:
            bits.append(L['n_decide'](n['decision']))
        if n['you-fix']:
            bits.append(L['n_do'](n['you-fix']))
        if wait and n['external']:
            bits.append(L['n_wait'](n['external']))
        return ' · '.join(bits)

    def verdict(self, L, status):
        split = self.split(L)
        nm, nb = len(self.mine), len(self.blocking_mine)
        waits = f' · {L["n_wait"](len(self.ext))}' if self.ext else ''
        if nb:
            return f'{L["v_on_you"]} · {split} ({L["v_blocks"](nb, nm)}){waits}'
        if self.blocking_ext:
            return f'{L["v_others"]} · {split + " (" + L["v_none_block"] + ")" if nm else L["v_nothing_you"]}'
        if nm:
            due = next((_s(x.get('due')) for x in self.mine if x.get('due')), '')
            tail = L['v_optional'](nm) + (f'; {L["v_due"](due)}' if due else '')
            return f'{L["v_free"]} · {split} ({tail}){waits}'
        return L['v_none'] + (f' · {L["n_wait"](len(self.ext))}' if self.ext else '')


def default_option(x):
    opts = dicts(x.get('options'))
    return next((k for k, o in enumerate(opts) if o.get('recommended')), 0) if opts else None


def default_reply(yours):
    """The reply the page composes before the user touches anything: every non-risky decision default, in order.
    A you-fix reply says the work is done, so it waits for the user to tick it."""
    out = []
    for x in yours.mine:
        opts = dicts(x.get('options'))
        if not opts:
            continue
        o = opts[default_option(x)]
        if not o.get('risky') and x.get('kind') != 'you-fix':
            out.append(_s(o.get('reply')))
    return out


def numbered(parts):
    """One reply line per item; numbered when there is more than one."""
    return parts[0] if len(parts) == 1 else '\n'.join(f'{i}. {t}' for i, t in enumerate(parts, 1))


def freshness(card, gen):
    """(checked datetime or None, seconds between the check and the page, older-than-6h flag)."""
    lc = card.get('last_checked') or {}
    when = parse_when(lc.get('when'), gen)
    if not when:
        return None, None, False
    secs = (gen - when).total_seconds()
    return when, secs, secs > 6 * 3600


# ── Icons (inline SVG, decorative: every one sits next to a text label) ─────────────────────

def svg(body, vb='0 0 16 16', extra=''):
    return (f'<svg viewBox="{vb}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true" focusable="false"{extra}>{body}</svg>')


ICON = {
    'waiting-on-you': svg('<path d="M8 1.8 15 14H1z"/><path d="M8 6.2v3.6"/><circle cx="8" cy="11.9" r=".5" fill="currentColor"/>'),
    'blocked': svg('<circle cx="8" cy="8" r="6.4"/><path d="M4.6 8h6.8"/>'),
    'running': svg('<circle cx="8" cy="8" r="6.4"/><path d="M6.6 5.4 10.6 8l-4 2.6z" fill="currentColor"/>'),
    'idle': svg('<circle cx="8" cy="8" r="6.4"/><path d="M6.4 5.6v4.8M9.6 5.6v4.8"/>'),
    'done': svg('<circle cx="8" cy="8" r="6.4"/><path d="m5.2 8.2 2 2 3.8-4.2"/>'),
    'check': svg('<path d="m3.2 8.4 3 3 6.6-7"/>'),
    'x': svg('<path d="m4 4 8 8M12 4l-8 8"/>'),
    'you': svg('<circle cx="8" cy="5" r="2.6"/><path d="M2.8 14c.6-3 2.7-4.6 5.2-4.6s4.6 1.6 5.2 4.6"/>'),
    'agent': svg('<rect x="2.6" y="4.4" width="10.8" height="8.4" rx="2"/><path d="M8 4.4V2.2M5.8 8.4h.01M10.2 8.4h.01"/>'),
    'external': svg('<circle cx="8" cy="8" r="6.4"/><path d="M8 4.4V8l2.6 1.6"/>'),
    'question': svg('<circle cx="8" cy="8" r="6.4"/><path d="M6.2 6.3a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1v.4"/><circle cx="8" cy="11.6" r=".5" fill="currentColor"/>'),
    'warn': svg('<path d="M8 1.8 15 14H1z"/><path d="M8 6.2v3.6"/><circle cx="8" cy="11.9" r=".5" fill="currentColor"/>'),
    'mark': svg('<rect x="1.8" y="1.8" width="12.4" height="12.4" rx="3"/><path d="M4.6 10.8 7 8.4l1.8 1.6 2.6-3.6"/>'),
    'k-start': svg('<circle cx="8" cy="8" r="4.2"/>'),
    'k-milestone': svg('<path d="M8 2.8 13.2 8 8 13.2 2.8 8z" fill="currentColor"/>'),
    'k-decision': svg('<path d="M8 2.8 13.2 8 8 13.2 2.8 8z"/>'),
    'k-problem': svg('<path d="M8 2.2 14.4 13.6H1.6z" fill="currentColor" stroke="none"/><path d="M8 6.4v3.4" stroke="var(--surface)"/>'),
    'k-ship': svg('<path d="m3.2 8.4 3 3 6.6-7" stroke-width="2"/>'),
}
ICON['decision'] = ICON['k-decision']
ICON['you-fix'] = ICON['you']

STAGE_DOT = {
    'done': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="var(--text)"/>'
            '<path d="m7.5 12.3 3 3 6-6.6" fill="none" stroke="var(--surface)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    'current': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="var(--surface)" stroke="var(--hue)" stroke-width="2.5"/>'
               '<circle cx="12" cy="12" r="4.5" fill="var(--hue)"/></svg>',
    'blocked': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="var(--neg)"/>'
               '<path d="m8 8 8 8M16 8l-8 8" stroke="var(--surface)" stroke-width="2.2" stroke-linecap="round"/></svg>',
    'todo': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="var(--surface)" stroke="var(--control)" stroke-width="2"/></svg>',
    'skipped': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" fill="var(--surface)" stroke="var(--control)" stroke-width="2" stroke-dasharray="3 3"/>'
               '<path d="M8 12h8" stroke="var(--faint)" stroke-width="2" stroke-linecap="round"/></svg>',
}

STATUS_TONE = {'waiting-on-you': 't-warn', 'blocked': 't-neg', 'running': 't-hue', 'idle': 't-neu', 'done': 't-pos'}
STATUS_BAND = {'waiting-on-you': 's-warn', 'blocked': 's-neg', 'running': 's-hue', 'idle': 's-neu', 'done': 's-pos'}
WF_TONE = {'completed': 't-pos', 'running': 't-hue', 'killed': 't-neu', 'failed': 't-neg', 'stopped': 't-neu',
           'aborted': 't-neu'}
KIND_TAG = {'decision': 'yours-tag', 'you-fix': 'yours-tag', 'external': 't-neu'}


def copy_btn(L, target=None, text=None, primary=False, label=None, what=None, extra=''):
    """A copy button for an element's text (target id) or a literal text."""
    cls = 'btn primary' if primary else 'btn'
    lab = label or L['copy']
    src = f'data-copy="{esc(target)}"' if target else f'data-copy-text="{esc(text)}"'
    aria = f' aria-label="{esc(lab + ": " + _s(what))}"' if what else ''
    return (f'<button type="button" class="{cls}" {src} data-label="{esc(lab)}" data-ok="{esc(L["copied"])}" '
            f'data-fail="{esc(L["copy_fail"])}"{aria}{extra}>{esc(lab)}</button>')


def pill(txt, tone, icon='', title=None, cls='sm'):
    t = f' title="{esc(title)}"' if title else ''
    return f'<span class="pill {cls} {tone}"{t}>{icon}{esc(txt)}</span>'


def status_pill(status, L, small=False):
    return pill(L['status'].get(status, status), STATUS_TONE.get(status, 't-neu'), ICON.get(status, ''),
                cls='sm' if small else '')


# ── Short version ───────────────────────────────────────────────────────────────────────────

def copy_block(c, bid, L):
    """One thing to copy: its label, the full text visible (clamped to ~6 lines), then the button."""
    text = _s(c.get('text'))
    kind = 'mono' if is_code(text) else 'prose'
    return (f'<div class="cpb {kind}"><div class="cph"><span class="cpl">{esc(c.get("label"))}</span>'
            f'{copy_btn(L, target=bid, what=c.get("label"))}</div>'
            f'<div class="cpt" id="{bid}">{esc(text)}</div>'
            f'<button type="button" class="btn more" hidden aria-expanded="false" aria-controls="{bid}" '
            f'data-more="{esc(L["show_all"])}" data-less="{esc(L["show_less"])}">{esc(L["show_all"])}</button></div>')


def reply_row(x, L):
    """The item's row in the composer: a checkbox and a choice between its options."""
    fid = slug(x.get('id'))
    opts = dicts(x.get('options'))
    if not opts:
        return ''
    k0 = default_option(x)
    risky_default = bool(opts[k0].get('risky'))
    fix = x.get('kind') == 'you-fix'
    chk = '' if risky_default or fix else ' checked'
    legend = L['reply_dec'] if x.get('kind') == 'decision' else L['reply_fix']

    def tags(o):
        t = ''
        if o.get('recommended'):
            t += pill(L['recommended'], 't-hue', ICON['check'])
        if o.get('risky'):
            t += pill(L['risky'], 't-neg', ICON['warn'], title=L['risky_t'])
        return t
    if len(opts) == 1:
        o = opts[0]
        choice = (f'<p class="one"><span class="ol">{esc(o.get("label"))}</span>{tags(o)}</p>'
                  f'<p class="rt">{esc(o.get("reply"))}</p>')
        data = f' data-reply="{esc(o.get("reply"))}"'
    else:
        lis = []
        for k, o in enumerate(opts):
            lis.append(f'<label class="opt"><input type="radio" name="o-{fid}" value="{k}" data-reply="{esc(o.get("reply"))}"'
                       f'{" checked" if k == k0 else ""}><span class="ob"><span class="ol">{esc(o.get("label"))}</span>{tags(o)}'
                       f'<span class="rt">{esc(o.get("reply"))}</span></span></label>')
        choice = f'<div class="opts">{"".join(lis)}</div>'
        data = ''
    note = (f'<p class="riskoff">{ICON["warn"]}{esc(L["risky_off"])}</p>' if risky_default else
            f'<p class="fixoff">{esc(L["fix_off"])}</p>' if fix else '')
    return (f'<fieldset class="reply{"" if chk else " off"}" data-fy="{fid}" aria-labelledby="lg-{fid} fyh-{fid}">'
            f'<legend id="lg-{fid}">{esc(legend)}</legend>'
            f'{choice}<label class="inc"><input type="checkbox" data-inc{data}{chk}><span>{esc(L["include"])}</span></label>'
            f'{note}</fieldset>')


def fy_item(x, L):
    fid = slug(x.get('id'))
    kind = x.get('kind')
    head = pill(L['blocks'], 't-warn', ICON['warn']) if x.get('blocks') is True else pill(L['optional'], 't-neu')
    if x.get('due'):
        head += pill(L['due'](_s(x.get('due'))), 't-warn')
    copies = ''.join(copy_block(c, f'cp-{fid}-{k}', L) for k, c in enumerate(dicts(x.get('copy')), 1)
                     if _s(c.get('text')).strip())
    copies = f'<div class="cps">{copies}</div>' if copies else ''
    row = reply_row(x, L)
    rec = f'<p class="rec"><b>{esc(L["rec"])}</b> {rich(x.get("recommend"))}</p>' if x.get('recommend') else ''
    why = f'<p class="why">{rich(x.get("why"))}</p>' if x.get('why') else ''
    then = f'<p class="then"><b>{esc(L["then"])}</b> {rich(x.get("then"))}</p>' if x.get('then') else ''
    if kind == 'decision':
        body = row + rec + why + copies + then
    elif kind == 'you-fix':
        body = copies + rec + why + then + row
    else:
        body = why + copies + then
    cls = f'k-{esc(kind)}' + (' b' if x.get('blocks') is True else '')
    return (f'<li class="{cls}" id="fy-{fid}"><div class="head">{head}</div>'
            f'<h4 id="fyh-{fid}">{rich(x.get("what"))}</h4>{body}</li>')


def sec_short(card, facts, L, Y, gen):
    status = card.get('status')
    verdict = Y.verdict(L, status)
    v_icon = ICON['waiting-on-you'] if Y.blocking_mine else ICON['external'] if Y.blocking_ext else ICON['done']
    tail = (f' <span class="vt">{esc(L["v_none_done"])}</span>'
            if not Y.mine and status == 'done' else '')
    out = [f'<p class="verdict">{v_icon}<span>{esc(verdict)}{tail}</span></p>']

    # freshness: what was checked, when, by whom, and how old that is
    lc = card.get('last_checked') or {}
    when, secs, old = freshness(card, gen)
    by = _s(lc.get('by'))
    by_txt = L['by_map'].get(by, by)
    if by == 'nobody':
        meta = f'<p class="fm">{esc(L["nobody"])}</p>'
    else:
        age = ''
        if secs is not None:
            age = ' · ' + esc(L['before_page'](dur_text(secs, L)) if secs >= 0 else L['after_page'])
        wt = f'<time datetime="{esc(when.isoformat())}">{esc(lc.get("when"))}</time>' if when else esc(lc.get('when'))
        meta = (f'<p class="fm">{L["by_who"](wt, esc(by_txt))}{age}'
                + (f' {pill(L["old"], "t-warn", ICON["warn"])}' if old else '') + '</p>')
    what = f'<p class="fw"><b>{esc(L["checked"])}</b> {rich(lc.get("what"))}</p>' if lc.get('what') else ''
    stale = (f'<p class="fs">{ICON["warn"]}<span><b>{esc(L["stale_lbl"])}</b> {rich(lc.get("stale"))}</span></p>'
             if _s(lc.get('stale')).strip() else '')
    out.append(f'<div class="fresh{" old" if old or stale else ""}">{what}{meta}{stale}</div>')

    al = card.get('asked_last') or {}
    if al.get('quote'):
        out.append(f'<p class="asked"><b>{esc(L["asked"](_s(al.get("quote")), _s(al.get("date"))))}</b> {rich(al.get("answer"))}</p>')

    for kind, items in Y.groups():
        out.append(f'<div class="grp g-{kind}"><h3>{ICON.get(kind, "")}{esc(L["grp"][kind])}'
                   f'<span class="gc num">{len(items)}</span></h3><ol class="fy">{"".join(fy_item(x, L) for x in items)}</ol></div>')
    if Y.items:
        out.append(f'<p class="defn">{esc(L["defn"])}</p>')

    if Y.mine and any(dicts(x.get('options')) for x in Y.mine):
        rows = [x for x in Y.mine if dicts(x.get('options'))]
        dflt = default_reply(Y)
        txt = numbered(dflt) if dflt else L['compose_empty']
        cnt = L['compose_tpl'].replace('{n}', str(len(dflt))).replace('{t}', str(len(rows)))
        out.append(f'<div class="composer" id="composer" data-tpl="{esc(L["compose_tpl"])}" data-empty="{esc(L["compose_empty"])}">'
                   f'<div class="ch"><h3 id="h-reply">{esc(L["composer"])}</h3><p class="cnt num" id="reply-count" aria-live="polite">{esc(cnt)}</p></div>'
                   f'<pre id="reply-text" class="{"" if dflt else "empty"}" aria-labelledby="h-reply">{esc(txt)}</pre>'
                   f'<div class="ca">{copy_btn(L, target="reply-text", primary=True, label=L["copy_reply"], extra=" id=reply-copy" + ("" if dflt else " disabled"))}</div></div>')
    else:
        co = card.get('continue') or {}
        if _s(co.get('text')).strip():
            alts = [a for a in lst(co.get('alts')) if _s(a).strip()][:3]
            frag = lambda t, k, prim: (f'<div class="frag"><pre id="cont-{k}"><code>{esc(t)}</code></pre>'
                                       f'{copy_btn(L, target=f"cont-{k}", primary=prim, what=t)}</div>')
            out.append(f'<div class="prompts"><p class="lbl">{esc(L["continue"])}</p>{frag(co["text"], 0, True)}'
                       + (f'<p class="sub">{esc(L["narrower"])}</p>' + ''.join(frag(a, k, False) for k, a in enumerate(alts, 1))
                          if alts else '') + '</div>')

    if _s(card.get('if_waiting')).strip():
        out.append(f'<p class="wait"><b>{esc(L["wait"])}</b> {rich(card.get("if_waiting"))}</p>')
    cav = [c for c in dicts(card.get('caveats')) if c.get('text')]
    if cav:
        out.append(f'<div class="bite"><h3>{ICON["warn"]}{esc(L["bite"])}</h3><ul>' +
                   ''.join(f'<li><b>{rich(c.get("text"))}</b> {rich(c.get("matters"))}</li>' for c in cav) + '</ul></div>')
    if facts.get('resume'):
        out.append(f'<div class="resume ph-only"><div class="lbl">{esc(L["resume_term"])}</div><div class="cmd">'
                   f'<code id="resume-ph">{esc(facts["resume"])}</code>{copy_btn(L, target="resume-ph", what="claude --resume")}</div></div>')
    aside = Y.split(L, wait=True) or L['nothing_yours']
    return (f'<section class="card sv st-{esc(status)}" aria-labelledby="h-short"><header><h2 id="h-short">{esc(L["sv"])}</h2>'
            f'<span class="aside num">{esc(aside)}</span></header>{"".join(out)}</section>')


# ── Where it stands ─────────────────────────────────────────────────────────────────────────

def sec_stands(card, L):
    pr = card.get('progress') or {}
    p = pct(pr.get('done_pct'))
    segs = ''.join('<i class="on"></i>' if k < p // 5 else '<i></i>' for k in range(20))
    conf = pr.get('confidence')
    gap = _s(pr.get('gap')).strip()
    desc = ('pgap ' if gap else '') + 'pdef-t'
    prog = (f'<div class="prog"><div><h3>{esc(L["progress"])}</h3>'
            f'<p class="big num">{p}%<small>{esc(L["done_word"])} · {100 - p}% {esc(L["left_word"])}</small></p>'
            f'<div class="segs" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{p}" '
            f'aria-label="{esc(L["progress"])}" aria-describedby="{desc}">{segs}</div>'
            + (f'<p class="gap" id="pgap"><b>{esc(L["gap"])}</b> {rich(gap)}</p>' if gap else '')
            + f'<details class="pdef"><summary>{esc(L["pdef"](p))}</summary><p id="pdef-t">{esc(L["pdef_t"])}</p></details>')
    if conf:
        prog += (f'<div class="conf">{esc(L["confidence"])} '
                 f'{pill(L["conf"].get(conf, conf), "t-warn" if conf == "low" else "t-neu")}</div>')
    prog += '</div>'
    if pr.get('basis'):
        prog += f'<p class="basis">{rich(pr.get("basis"))}</p>'
    prog += '</div>'

    stages = dicts((card.get('track') or {}).get('stages'))
    track = ''
    if stages:
        lis = []
        live = live_index(stages)
        for k, s in enumerate(stages):
            st = s.get('status') if s.get('status') in STAGE_DOT else 'todo'
            cls = st + (' fill' if k <= live else '') + (' fnext' if k + 1 <= live else '')
            if k + 1 == live and stages[live].get('status') == 'blocked':
                cls += ' fnb'
            note = f'<span class="note">{rich(s.get("note"))}</span>' if s.get('note') else ''
            state = (f'<span class="st">{esc(L["stage"][st])}</span>' if st in ('current', 'blocked', 'skipped')
                     else f'<span class="sr">{esc(L["stage"][st])}</span>')
            cur = ' aria-current="step"' if st in ('current', 'blocked') else ''
            lis.append(f'<li class="{cls}"{cur}><span class="dot">{STAGE_DOT[st]}</span>'
                       f'<span class="nm">{esc(s.get("name"))}</span>{state}{note}</li>')
        track = (f'<div id="stages"><h3>{esc(L["stages"])}</h3><ol class="track" style="--n:{len(stages)}">'
                 f'{"".join(lis)}</ol></div>')

    dep = card.get('deploy') or {}
    dep_html = ''
    if dep.get('applies') is True:
        steps = [x for x in lst(dep.get('steps_left')) if _s(x).strip()]
        if card.get('status') == 'done' or not steps:
            ic = ICON['done'].replace('<svg', '<svg style="width:16px;height:16px;vertical-align:-3px;color:var(--pos)"', 1)
            head, path = f'<strong>{ic} {esc(L["is_live"])}</strong>', ''
        else:
            head = f'<strong class="num">{esc(L["steps_live"](len(steps)))}</strong>'
            path = (f'<ol class="path" aria-label="{esc(L["steps_live"](len(steps)))}">'
                    + '<span class="arrow" aria-hidden="true">→</span>'.join(f'<li class="stp">{esc(x)}</li>' for x in steps)
                    + '</ol>')
        summ = f'<p>{rich(dep.get("summary"))}</p>' if dep.get('summary') else ''
        dep_html = f'<div class="deploy" id="deploy">{head}{path}{summ}</div>'
    return (f'<section class="card" aria-labelledby="h-stand"><h2 id="h-stand">{esc(L["stands"])}</h2>'
            f'<div class="stand">{prog}{track}{dep_html}</div></section>')


# ── The story ───────────────────────────────────────────────────────────────────────────────

def timeline(card):
    tl = dicts(card.get('timeline'))
    return sorted(tl, key=lambda s: _s(s.get('date')))


def _activity(card, facts, L, gen):
    act = (facts or {}).get('activity_by_day') or {}
    days = {}
    for k, v in act.items():
        d = parse_day(k)
        if d and isinstance(v, dict):
            days[d] = (int(v.get('turns') or 0), int(v.get('prompts') or 0))
    if not days:
        return ''
    story_days = {parse_day(s.get('date')) for s in timeline(card)}
    today = gen.date()
    first, last = min(days), max(max(days), today)
    span = (last - first).days + 1
    if span > 42:
        first, span = last - timedelta(days=41), 42
    seq = [first + timedelta(days=k) for k in range(span)]
    top = max((t for t, _ in days.values()), default=1) or 1
    bars, axis = [], []
    last_act = max(days)
    every = 1 if span <= 14 else 2 if span <= 28 else 4
    for k, d in enumerate(seq):
        t, pr = days.get(d, (0, 0))
        h = 0 if not t else max(4, round(60 * t / top))
        cls = 'd' + (' zero' if not t else '') + (' last' if d == last_act else '')
        tip = f'{fmt_day(d, L)} · {pr} {L["prompts"]} · {t} {L["turns"]}'
        bars.append(f'<span class="{cls}" title="{esc(tip)}"><span class="b" style="height:{h}px"></span></span>')
        lab = f'{d.day}' if (k % every == 0) or d == seq[-1] else ''
        acls = ' '.join(c for c in ('ev' if d in story_days else '', 'last' if d == last_act else '') if c)
        axis.append(f'<span class="{acls}">{esc(lab)}</span>')
    busiest = max(days, key=lambda d: days[d][0])
    gap = (today - last_act).days
    tail = L['active_today'] if gap <= 0 else f'{L["last_active"]} {fmt_day(last_act, L)}, {L["quiet"](gap)}'
    tot_p = sum(p for _, p in days.values())
    summary = (f'{esc(L["busiest"])} {esc(fmt_day(busiest, L))} '
               f'(<span class="num">{days[busiest][0]}</span> {esc(L["turns"])}) · {esc(tail)} · '
               f'<span class="num">{tot_p}</span> {esc(L["prompts"])} {esc(L["over_days"](len(days)))}')
    rows = ''.join(f'<li>{esc(fmt_day(d, L))}: {days[d][1]} {esc(L["prompts"])}, {days[d][0]} {esc(L["turns"])}</li>'
                   for d in sorted(days))
    mo = f'{L["mo"][first.month - 1]}' + (f' – {L["mo"][last.month - 1]}' if last.month != first.month else '')
    if span == 1:
        return f'<div><h3>{esc(L["activity"])}</h3><p class="act-sum" style="margin-top:0">{summary}</p></div>'
    return (f'<div><h3>{esc(L["activity"])} <span style="font-weight:400">· {esc(mo)}</span></h3>'
            f'<div aria-hidden="true"><div class="act-strip">{"".join(bars)}</div>'
            f'<div class="act-axis num">{"".join(axis)}</div></div>'
            f'<ul class="sr">{rows}</ul><p class="act-sum">{summary}</p></div>')


def sec_story(card, facts, L, gen):
    st = card.get('story') or {}
    o = st.get('origin') or {}
    left = []
    if o.get('quote'):
        full = _s(o.get('full')).strip()
        left.append(f'<blockquote class="origin"><p class="od">{esc(L["you_asked"](_s(o.get("date"))))}</p>'
                    f'<p>“{esc(o.get("quote"))}”</p></blockquote>'
                    + (f'<details class="fullreq"><summary>{esc(L["full_req"])}</summary><div><blockquote>{esc(full)}</blockquote></div></details>'
                       if full and full != _s(o.get('quote')).strip() else ''))
    def para(q):
        lead = f'<span class=lead>{esc(q.get("lead"))}</span> ' if q.get('lead') else ''
        return f'<p>{lead}{rich(q.get("text"))}</p>'
    left += [para(q) for q in dicts(st.get('paragraphs')) if q.get('text')]
    more = [q for q in dicts(st.get('more')) if q.get('text')]
    if more:
        left.append(f'<details class="more-story"><summary>{esc(L["more_story"](len(more)))}</summary>'
                    f'<div>{"".join(para(q) for q in more)}</div></details>')
    right = [_activity(card, facts, L, gen)]
    tl = timeline(card)
    if tl:
        groups = []
        for s in tl:
            key = _s(s.get('date'))[:10]
            if groups and groups[-1][0] == key:
                groups[-1][1].append(s)
            else:
                groups.append((key, [s]))
        days = []
        for key, items in groups:
            evs = []
            for s in items:
                k = s.get('kind') if s.get('kind') in L['story'] else 'milestone'
                hm = re.search(r'\d{2}:\d{2}', _s(s.get('date'))[10:])
                kl = esc(L['story'][k]) + (f' · {hm.group(0)}' if hm else '')
                evs.append(f'<div class="ev {k}"><span class="k k-{k}">{ICON["k-" + k]}</span>'
                           f'<p><span class="kl">{kl}</span>{rich(s.get("label"))}</p></div>')
            d = parse_day(key)
            dt_attr = f' datetime="{d.isoformat()}"' if d else ''
            days.append(f'<li class="day"><time{dt_attr}>{esc(day_label(key, L))}</time><div>{"".join(evs)}</div></li>')
        right.append(f'<div><h3 style="margin-top:20px">{esc(L["timeline"])}</h3><ol class="tl" style="margin-top:0">'
                     f'{"".join(days)}</ol></div>')
    right = [r for r in right if r]
    if not left and not right:
        return ''
    return (f'<section class="card" aria-labelledby="h-story"><h2 id="h-story">{esc(L["story_t"])}</h2>'
            f'<div class="story{"" if right else " solo"}"><div class="ctx">{"".join(left)}</div>'
            + (f'<div>{"".join(right)}</div>' if right else '') + '</div></section>')


# ── Decisions ───────────────────────────────────────────────────────────────────────────────

def sec_decisions(card, L):
    ds = [d for d in dicts(card.get('decisions')) if d.get('what')]
    if not ds:
        return ''
    you = [d for d in ds if d.get('by') == 'you']
    ag = [d for d in ds if d.get('by') != 'you']

    def row(d):
        tag = (pill(L['as_rec'], 't-hue') if d.get('rec') is True else pill(L['not_rec'], 't-warn')
               if d.get('rec') is False and d.get('by') == 'you' else '')
        return f'<li><span>{rich(d.get("what"))}</span><span class="dm"><span>{esc(d.get("date"))}</span>{tag}</span></li>'
    cols = []
    if you:
        cols.append(f'<div><h3>{ICON["you"]}{esc(L["dec_you"](len(you)))}</h3><ul class="drows">{"".join(map(row, you))}</ul></div>')
    if ag:
        body = f'<ul class="drows">{"".join(map(row, ag[:3]))}</ul>'
        if len(ag) > 3:
            body += (f'<details class="fold"><summary>{esc(L["more_agent"](len(ag) - 3))}</summary>'
                     f'<ul class="drows">{"".join(map(row, ag[3:]))}</ul></details>')
        cols.append(f'<div><h3>{ICON["agent"]}{esc(L["dec_agent"](len(ag)))}</h3>{body}</div>')
    return (f'<section class="card" aria-labelledby="h-dec"><header><h2 id="h-dec">{esc(L["dec_t"])}</h2>'
            f'<span class="aside">{esc(L["dec_aside"](len(you), len(ag)))}</span></header>'
            f'<div class="decs{" one" if len(cols) == 1 else ""}">{"".join(cols)}</div></section>')


# ── Done / What's left / Next ───────────────────────────────────────────────────────────────

def _check_chip(c, L, k):
    lab = _s(c.get('label'))
    u = safe_url(c.get('url'))
    if u:
        return f'<a class="chip go" href="{esc(u)}">{esc(lab)} ↗</a>'
    target = _s(c.get('path') or c.get('url'))
    if not target:
        return f'<span class="chip">{esc(lab)}</span>'
    tail = target.rstrip('/').split('/')[-1] or target
    return (f'<span class="cp"><span class="chip" title="{esc(target)}">{esc(lab)}: {esc(tail)}</span>'
            f'{copy_btn(L, text=target, what=lab + " path")}</span>')


def kind_tag(x, L):
    kind = x.get('kind')
    return (f'<a class="pill sm {KIND_TAG.get(kind, "t-neu")} ktag" href="#fy-{slug(x.get("id"))}">'
            f'{esc(L["grp"].get(kind, kind))}</a>')


def sec_work(card, L, Y):
    done = [d for d in dicts(card.get('done')) if d.get('outcome')]
    rem = [r for r in dicts(card.get('remaining')) if r.get('what')]
    out = []
    if done:
        items = []
        for d in done:
            chk = dicts(d.get('check'))
            chk = [c for c in chk if safe_url(c.get('url'))] + [c for c in chk if not safe_url(c.get('url'))]
            bf = f'<span class="bf"><b>{esc(L["before"])}</b> {rich(d.get("before"))}</span>' if _s(d.get('before')).strip() else ''
            items.append(f'<li>{ICON["check"]}<span class="w">{rich(d.get("outcome"))}</span>{bf}'
                         f'<div class="chips">{"".join(_check_chip(c, L, k) for k, c in enumerate(chk))}</div></li>')
        out.append(f'<section class="card span" aria-labelledby="h-done"><header><h2 id="h-done">{esc(L["done_t"])}</h2>'
                   f'<span class="aside num">{len(done)}</span></header><ul class="rows done">{"".join(items)}</ul></section>')

    def left_li(r):
        fy = Y.by_id.get(r.get('for_you')) if r.get('for_you') else None
        who = _s(r.get('who')) or L['owner'].get(r.get('owner'), _s(r.get('owner')))
        note = f'<span class="m">{rich(r.get("note"))}</span>' if _s(r.get('note')).strip() else ''
        return (f'<li><span>{rich(r.get("what"))}<span class="m"><b>{esc(L["who"])}</b> {esc(who)}</span>{note}</span>'
                f'<span class="tags">{kind_tag(fy, L) if fy else ""}'
                f'{pill(_s(r.get("effort")) or L["not_est"], "t-neu")}</span></li>')
    req = [r for r in rem if r.get('required') is True]
    opt = [r for r in rem if r.get('required') is not True]
    linked = [Y.by_id[r['for_you']] for r in rem if r.get('for_you') in Y.by_id]
    if rem:
        body = ''
        if req:
            body += f'<h3 class="grp">{esc(L["req"])}</h3><ul class="rows left">{"".join(map(left_li, req))}</ul>'
        if opt:
            body += f'<h3 class="grp">{esc(L["opt"])}</h3>'
            if len(opt) <= 4:
                body += f'<ul class="rows left">{"".join(map(left_li, opt))}</ul>'
            else:
                hid = Y.split(L, [Y.by_id[r['for_you']] for r in opt[3:] if r.get('for_you') in Y.by_id], wait=True)
                body += (f'<ul class="rows left">{"".join(map(left_li, opt[:3]))}</ul><details class="fold">'
                         f'<summary>{esc(L["more_opt"](len(opt) - 3) + (f" · {hid}" if hid else ""))}</summary><ul class="rows left">'
                         f'{"".join(map(left_li, opt[3:]))}</ul></details>')
        split = Y.split(L, linked, wait=True)
        aside = L['left_aside'](len(req), len(opt)) + (f' · {split}' if split else '')
    else:
        body, aside = f'<p class="muted">{esc(L["no_left"])}</p>', ''
    left = (f'<section class="card" aria-labelledby="h-left"><header><h2 id="h-left">{esc(L["left_t"])}</h2>'
            f'<span class="aside num">{esc(aside)}</span></header>{body}</section>')

    nxt = [(x, True) for x in Y.mine] + [(t, False) for t in lst(card.get('next_agent')) if _s(t).strip()]
    nxt_html = ''
    if nxt:
        lis = []
        for v, you in nxt:
            if you:
                lis.append(f'<li class="you"><div class="s"><span class="tx"><a href="#fy-{slug(v.get("id"))}">{rich(v.get("what"))}</a></span>'
                           f'{pill(L["grp"][v.get("kind")], "t-warn")}</div></li>')
            else:
                lis.append(f'<li class="agent"><div class="s"><span class="tx">{rich(v)}</span>{pill(L["agent_badge"], "t-neu")}</div></li>')
        nxt_html = (f'<section class="card" aria-labelledby="h-next"><header><h2 id="h-next">{esc(L["next_t"])}</h2>'
                    f'</header><ol class="next">{"".join(lis)}</ol></section>')
    if not nxt_html:
        left = left.replace('class="card"', 'class="card span"', 1)
    return f'<div class="grid2">{"".join(out)}{left}{nxt_html}</div>', bool(nxt_html), linked


def sec_workstreams(card, L):
    ws = dicts(card.get('workstreams'))
    if not ws:
        return ''
    tone = {'done': 't-pos', 'running': 't-hue', 'blocked': 't-neg', 'todo': 't-neu'}
    wl = {'done': L['status']['done'], 'running': L['status']['running'], 'blocked': L['status']['blocked'],
          'todo': L['stage']['todo']}
    items = []
    for w in ws:
        p = pct(w.get('done_pct'))
        st = w.get('status')
        pl = pill(wl.get(st, st), tone.get(st, 't-neu')) if st else '<span></span>'
        note = f'<p class="note">{rich(w.get("note"))}</p>' if w.get('note') else ''
        items.append(f'<li><span class="nm">{esc(w.get("name"))}</span>'
                     f'<span class="meter{" done" if p == 100 else ""}" role="img" aria-label="{p}%"><i style="width:{p}%"></i></span>'
                     f'<span class="pc num">{p}%</span>{pl}{note}</li>')
    return (f'<section class="card" aria-labelledby="h-ws"><h2 id="h-ws">{esc(L["ws_t"])}</h2>'
            f'<ul class="rows ws">{"".join(items)}</ul></section>')


def sec_since(card, L):
    since = card.get('since_last')
    if not _s(since).strip():
        return ''
    return (f'<section class="card since" aria-labelledby="h-since"><h2 id="h-since">{esc(L["since_t"])}</h2>'
            f'<p>{rich(since)}</p></section>')


def sec_links(card, facts, L):
    links = [lk for lk in dicts(card.get('links')) if lk.get('label') or lk.get('url')]
    prs = [p for p in dicts((facts or {}).get('prs')) if safe_url(p.get('url'))]
    prs.sort(key=lambda p: (_s(p.get('last_seen') or p.get('first_seen')), p.get('number') or 0), reverse=True)
    if not links and not prs:
        return ''
    rows = []
    for lk in links:
        u = safe_url(lk.get('url'))
        label = esc(lk.get('label') or lk.get('url'))
        a = f'<a href="{esc(u)}">{label}</a>' if u else f'<span>{label}</span>'
        rows.append(f'<li>{a}<span class="repo">{esc(re.sub(r"^https?://", "", u or _s(lk.get("url"))))}</span></li>')

    def pr_row(p):
        seen = parse_ts(p.get('last_seen') or p.get('first_seen'))
        s = f'<span class="seen">{esc(L["seen"])} {esc(fmt_dt(seen, L))}</span>' if seen else ''
        return (f'<li><a href="{esc(p["url"])}" class="num">PR #{esc(p.get("number"))}</a>'
                f'<span class="repo">{esc(p.get("repo"))}</span>{s}</li>')
    pr_html = ''
    if prs and rows:
        pr_html = (f'<details class="allprs"><summary>{esc(L["all_prs"](len(prs)))}</summary><ul class="links">'
                   f'{"".join(pr_row(p) for p in prs)}</ul></details>')
    elif prs:
        more = (f'<details><summary>{esc(L["prs_more"](len(prs) - 8))}</summary><ul class="links">'
                f'{"".join(pr_row(p) for p in prs[8:])}</ul></details>' if len(prs) > 8 else '')
        pr_html = f'<ul class="links">{"".join(pr_row(p) for p in prs[:8])}</ul>{more}'
    lk_html = f'<ul class="links">{"".join(rows)}</ul>' if rows else ''
    return (f'<section class="card" aria-labelledby="h-links"><h2 id="h-links">{esc(L["links_t"])}</h2>'
            f'{lk_html}{pr_html}</section>')


# ── Behind the scenes: glossary, workflows and jobs (from facts), unverified ────────────────

def _workflows(facts, L):
    wfs = dicts((facts or {}).get('workflows'))
    tasks = (facts or {}).get('background_tasks') or {}
    tasks = [t for t in tasks.values() if isinstance(t, dict)] if isinstance(tasks, dict) else []
    if not wfs and not tasks:
        return ''
    pend = (facts or {}).get('pending') or {}
    items, prev = [], None
    for w in wfs:
        st = _s(w.get('status')).lower()
        phases = [_s(p) for p in lst(w.get('phases'))]
        cur = _s(w.get('current_phase'))
        ci = phases.index(cur) if cur in phases else -1
        ph = []
        for k, p in enumerate(phases):
            c = 'ok' if st == 'completed' or (0 <= ci and k < ci) else ('cur' if st == 'running' else 'stop') if k == ci else ''
            mark = {'ok': ICON['check'], 'cur': ICON['k-start'], 'stop': ICON['x']}.get(c, '')
            state = {'ok': L['stage']['done'], 'cur': L['stage']['current'], 'stop': L['wf_status'].get(st, st)}.get(c)
            sr = f'<span class="sr"> ({esc(state)})</span>' if state else ''
            ph.append(f'<span class="p {c}">{mark}{esc(p)}{sr}</span>')
        phases_html = ('<div class="phases">' + '<span class="sep" aria-hidden="true">›</span>'.join(ph) + '</div>') if ph else ''
        bits = []
        if w.get('duration_min') is not None:
            bits.append(f'<span class="num">{esc(w.get("duration_min"))}</span> {esc(L["min"])}')
        if w.get('agents_started') is not None:
            bits.append(f'<span class="num">{esc(w.get("agents_started"))}</span> {esc(L["agents"])}')
        sd = parse_ts(w.get('started'))
        if sd:
            bits.append(f'{esc(L["started"])} {esc(fmt_dt(sd, L))}')
        logs = [_s(x) for x in lst(w.get('logs')) if _s(x).strip()]
        log_html = (f'<details><summary>{esc(L["log"](len(logs)))}</summary><pre>{esc(chr(10).join(logs))}</pre></details>'
                    if logs else '')
        err = f'<p class="err">{esc(w.get("error"))}</p>' if _s(w.get('error')).strip() else ''
        summ = f'<p class="sum">{esc(w.get("summary"))}</p>' if w.get('summary') and _s(w.get('summary')) != prev else ''
        prev = _s(w.get('summary'))
        items.append(f'<li><div class="h"><strong>{esc(w.get("name") or w.get("run_id"))}</strong>'
                     f'{pill(L["wf_status"].get(st, st or "?"), WF_TONE.get(st, "t-neu"))}'
                     f'<span class="stats">{" · ".join(bits)}</span></div>{summ}{phases_html}{err}{log_html}</li>')
    bg = ''
    running = []
    if tasks:
        cnt = Counter(_s(t.get('status')) or '?' for t in tasks)
        order = ['running', 'failed', 'stopped', 'completed']
        keys = sorted(cnt, key=lambda k: order.index(k) if k in order else len(order))
        chip = {'running': 't-hue', 'failed': 't-neg', 'stopped': 't-neu', 'completed': 't-pos'}
        counts = ''.join(f'<span class="pill sm {chip.get(k, "t-neu")}"><span class="num">{cnt[k]}</span>&nbsp;'
                         f'{esc(L["wf_status"].get(k, k).lower())}</span>' for k in keys)
        openers = sorted([t for t in tasks if _s(t.get('status')) != 'completed'], key=lambda t: _s(t.get('ts')), reverse=True)
        running = [t for t in openers if _s(t.get('status')) == 'running']
        rest = [t for t in openers if _s(t.get('status')) != 'running']

        def row(t):
            s = _s(t.get('status'))
            return f'<li>{pill(L["wf_status"].get(s, s), chip.get(s, "t-neu"))}<span>{esc(t.get("summary"))}</span></li>'
        run_html = f'<ul>{"".join(map(row, running))}</ul>' if running else ''
        rest_html = (f'<details><summary>{esc(L["bg_open"])} ({len(rest)})</summary><ul>{"".join(map(row, rest))}</ul></details>'
                     if rest else '')
        bg = (f'<div class="bg{" first" if not wfs else ""}"><div class="counts"><strong>{esc(L["bg"](len(tasks)))}</strong>{counts}</div>'
              f'{run_html}{rest_html}</div>')
    pa, pw = int(pend.get('agents') or 0), int(pend.get('workflows') or 0)
    still = []
    if pw or any(_s(w.get('status')).lower() == 'running' for w in wfs):
        still.append(f'{pw or 1} workflow{"s" if (pw or 1) != 1 else ""}')
    if pa:
        still.append(f'{pa} {L["agents"]}')
    if running:
        still.append(L['bg'](len(running)))
    line = (f'<p class="pend">{esc(L["still_running"])}: {esc(", ".join(still))}</p>' if still
            else f'<p class="muted">{esc(L["nothing_running"])}</p>')
    return (f'<div class="sub"><h3>{esc(L["wf_t"])}</h3>{line}'
            + (f'<ul class="rows wf">{"".join(items)}</ul>' if items else '') + f'{bg}</div>')


def sec_behind(card, facts, L):
    terms = [t for t in dicts(card.get('terms')) if t.get('term')]
    unv = [u for u in lst(card.get('unverified')) if _s(u).strip()]
    wf = _workflows(facts, L)
    if not (terms or unv or wf):
        return ''
    parts = [L['behind_parts'][k] for k, v in (('terms', terms), ('wf', wf), ('unv', unv)) if v]
    inner = ''
    if terms:
        inner += (f'<div class="sub"><h3>{esc(L["terms_t"])}</h3><dl class="terms">'
                  + ''.join(f'<dt>{esc(t["term"])}</dt><dd>{rich(t.get("meaning"))}</dd>' for t in terms) + '</dl></div>')
    inner += wf
    if unv:
        inner += (f'<div class="sub unv"><h3>{ICON["question"]}{esc(L["unv_t"])} <span class="muted">· {esc(L["unv_sub"])}</span></h3>'
                  f'<ul>{"".join(f"<li><span>{rich(u)}</span></li>" for u in unv)}</ul></div>')
    return (f'<details class="card behind" id="behind"><summary><h2 class="bt" id="h-behind">{esc(L["behind"])}</h2> '
            f'<span>{esc(", ".join(parts))}</span></summary><div class="in">{inner}</div></details>')


# ── Header, chrome, navigation ──────────────────────────────────────────────────────────────

def _footer(facts, L):
    if not facts:
        return ''
    rows = []
    if facts.get('cwd'):
        rows.append((L['cwd'], f'<code>{esc(facts["cwd"])}</code>'))
    reps = [r for r in dicts(facts.get('repos')) if r.get('path')]
    if reps:
        rows.append((L['repos'], '<br>'.join(
            f'<code>{esc(r["path"])}</code> · {esc(r.get("branch") or "–")}'
            + (f' · <span class="num">{esc(r.get("edits"))}</span> {esc(L["edits"])}' if r.get('edits') is not None else '')
            for r in reps)))
    elif facts.get('branch'):
        rows.append((L['branch'], f'<code>{esc(facts["branch"])}</code>'))
    if facts.get('transcript'):
        rows.append((L['transcript'], f'<code>{esc(facts["transcript"])}</code>'))
    if facts.get('session_id'):
        rows.append((L['session_id'], f'<code>{esc(facts["session_id"])}</code>'))
    size = []
    if facts.get('prompts'):
        size.append(f'<span class="num">{esc(facts["prompts"])}</span> {esc(L["prompts"])}')
    if facts.get('compactions'):
        size.append(esc(L['compactions'](int(facts['compactions']))))
    if size:
        rows.append((L['length_t'], ' · '.join(size)))
    g = parse_ts(facts.get('generated_at'))
    if g:
        rows.append((L['generated_at'], esc(fmt_dt(g, L)) + f' · {esc(facts.get("generated_at"))}'))
    return ('<footer class="foot"><div class="wrap"><dl>' +
            ''.join(f'<dt>{esc(k)}</dt><dd>{v}</dd>' for k, v in rows) + '</dl></div></footer>')


def _age_line(facts, L, gen):
    first, last = parse_ts(facts.get('first_ts')), parse_ts(facts.get('last_ts'))
    bits = []
    if first:
        bits.append(f'{esc(L["started_t"])} <time datetime="{esc(first.isoformat())}">{esc(fmt_day(first, L))}</time>')
    if last:
        when = ago_text((gen - last).total_seconds(), L)
        lead = esc(L['last_active_t']) if bits else esc(L['last_active_t'][:1].upper() + L['last_active_t'][1:])
        bits.append(f'{lead} <time class="ago" datetime="{esc(last.isoformat())}" data-ts="{esc(last.isoformat(timespec="seconds"))}" '
                    f'title="{esc(fmt_dt(last, L))}">{esc(when)}</time>')
    if first and last and last >= first:
        bits.append(esc(L['ran'](span_text(first, last, L))))
    return f'<p class="age">{" · ".join(bits)}</p>' if bits else ''


def _glance(card, L, Y):
    status = card.get('status')
    p = pct((card.get('progress') or {}).get('done_pct'))
    items = [f'<li><a href="#h-stand"><b class="num">{p}%</b> {esc(L["done_word"])}</a></li>']
    stages = dicts((card.get('track') or {}).get('stages'))
    live = next((s for s in stages if s.get('status') in ('current', 'blocked')), None)
    if live:
        st = live.get('status')
        items.append(f'<li class="g-{st}"><a href="#stages">{STAGE_DOT[st].replace("<svg", "<svg class=gdot", 1)}'
                     f'<b>{esc(live.get("name"))}</b> · {esc(L["stage"][st])}</a></li>')
    elif stages:
        # every stage done: on a phone the "Live" chip already says so, so this one is desktop-only there
        dup = ' class="ph-dup"' if (card.get('deploy') or {}).get('applies') is True else ''
        items.append(f'<li{dup}><a href="#stages">{STAGE_DOT["done"].replace("<svg", "<svg class=gdot", 1)}{esc(L["all_stages"])}</a></li>')
    dep = card.get('deploy') or {}
    if dep.get('applies') is True:
        steps = [x for x in lst(dep.get('steps_left')) if _s(x).strip()]
        txt = L['is_live'] if (status == 'done' or not steps) else L['steps_live'](len(steps))
        items.append(f'<li><a href="#deploy" class="num">{esc(txt)}</a></li>')
    split = Y.split(L)
    if split:
        items.append(f'<li class="g-you"><a href="#h-short">{ICON["you"]}<b class="num">{esc(split)}</b></a></li>')
    elif Y.ext:
        items.append(f'<li><a href="#h-short">{ICON["external"]}{esc(L["n_wait"](len(Y.ext)))}</a></li>')
    else:
        items.append(f'<li><a href="#h-short">{esc(L["nothing_yours"])}</a></li>')
    return f'<ul class="glance" aria-label="{esc(L["glance"])}">{"".join(items)}</ul>'


def render_html(card, facts):
    facts = facts if isinstance(facts, dict) else {}
    L = labels(card)
    Y = Yours(card)
    status = card.get('status')
    gen = parse_ts(facts.get('generated_at')) or datetime.now().astimezone()
    if not gen.tzinfo:
        gen = gen.astimezone()
    p = pct((card.get('progress') or {}).get('done_pct'))
    name = facts.get('name') or facts.get('title') or (_s(facts.get('session_id'))[:8] or None)
    meta = [f'{L["generated"]} {fmt_dt(gen, L)}'] + ([f'{L["session"]} {_s(name)}'] if name else [])
    resume = ''
    if facts.get('resume'):
        resume = (f'<div class="resume desk-only"><div class="lbl">{esc(L["resume"])}</div><div class="cmd">'
                  f'<code id="resume-cmd">{esc(facts["resume"])}</code>{copy_btn(L, target="resume-cmd", primary=True, what="claude --resume")}</div></div>')
    band = (f'<div class="status {STATUS_BAND.get(status, "s-neu")}">{status_pill(status, L)}'
            + (f'<p class="line">{rich(card.get("status_line"))}</p>' if card.get('status_line') else '') + '</div>')
    head = (f'<header class="top" id="top"><div class="hd"><h1>{esc(card.get("title"))}</h1>'
            + (f'<p class="one">{rich(card.get("one_liner"))}</p>' if card.get('one_liner') else '')
            + _age_line(facts, L, gen) + f'</div>{resume}<div class="sg">{band}{_glance(card, L, Y)}</div></header>')

    short = sec_short(card, facts, L, Y, gen)
    story = sec_story(card, facts, L, gen)
    decs = sec_decisions(card, L)
    work, has_next, linked = sec_work(card, L, Y)
    links = sec_links(card, facts, L)
    behind = sec_behind(card, facts, L)
    main = [short, sec_since(card, L), sec_stands(card, L), story, decs, work, sec_workstreams(card, L), links, behind]

    # navigation: the rail with counts (≥1280px) and the sticky jump bar (narrower)
    split = Y.split(L)
    n_dec = len([d for d in dicts(card.get('decisions')) if d.get('what')])
    rem = [r for r in dicts(card.get('remaining')) if r.get('what')]
    lsplit = Y.split(L, linked)
    rail = [('h-short', L['sv'], split or (L['n_wait'](len(Y.ext)) if Y.ext else ''), bool(split)),
            ('h-stand', L['stands'], f'{p}%', False)]
    if story:
        rail.append(('h-story', L['j']['story'], '', False))
    if decs:
        rail.append(('h-dec', L['j']['dec'], str(n_dec), False))
    if [d for d in dicts(card.get('done')) if d.get('outcome')]:
        rail.append(('h-done', L['done_t'], str(len([d for d in dicts(card.get('done')) if d.get('outcome')])), False))
    rail.append(('h-left', L['left_t'], lsplit or str(len(rem)), bool(lsplit)))
    if has_next:
        rail.append(('h-next', L['next_t'], '', False))
    if links:
        rail.append(('h-links', L['links_t'], '', False))
    if behind:
        rail.append(('behind', L['behind'], '', False))
    rail_html = (f'<aside class="rail"><nav aria-label="{esc(L["rail"])}"><p class="rl">{esc(L["rail"])}</p><ul>'
                 + ''.join(f'<li><a href="#{h}" data-sec="{h}"><b>{esc(t)}</b>'
                           + (f'<span class="ct{" you" if you else ""}">{esc(n)}</span>' if n else '') + '</a></li>'
                           for h, t, n, you in rail) + '</ul></nav></aside>')
    jl = [('h-short', L['j']['short']), ('h-stand', L['j']['stand'])] + ([('h-story', L['j']['story'])] if story else []) \
        + ([('h-dec', L['j']['dec'])] if decs else []) + [('h-left' if not [d for d in dicts(card.get('done')) if d.get('outcome')] else 'h-done', L['j']['work'])] \
        + ([('behind', L['j']['behind'])] if behind else [])
    jump = (f'<nav class="jump" id="jump" aria-label="{esc(L["jump"])}"><div class="wrap">'
            f'<div class="jid"><a class="jt" href="#top">{esc(card.get("title"))}</a>{status_pill(status, L, small=True)}'
            f'<span class="jp num">{p}%</span>' + (f'<span class="jp you">{esc(split)}</span>' if split else '')
            + f'</div><ul class="jl">{"".join(f"<li><a href=#{h}>{esc(t)}</a></li>" for h, t in jl)}</ul></div></nav>')
    stale = (f'<div class="stale" id="stale" hidden data-gen="{esc(gen.isoformat(timespec="seconds"))}">'
             f'<div class="wrap"><p></p></div></div>')
    body = [
        stale, jump,
        f'<div class="bar"><div class="wrap"><span class="mark">{ICON["mark"]}{esc(L["sitrep"])}</span>'
        f'<span class="meta">{esc(meta[0])}' + (f'<span class="desk-only"> · {esc(meta[1])}</span>' if len(meta) > 1 else '') + '</span></div></div>',
        f'<div class="layout">{rail_html}<div class="colmain">{head}<main>',
        *main,
        '</main><p class="sr" role="status" id="copy-status"></p></div></div>',
        _footer(facts, L),
    ]
    tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template.html'), encoding='utf-8').read()
    title = f'Sitrep · {_s(card.get("title"))} · {L["status"].get(status, status or "")}'
    return (tpl.replace('__LANG__', 'pt-BR' if L is LABELS['pt-BR'] else 'en')
               .replace('__TITLE__', html.escape(title))
               .replace('__BODY__', '\n'.join(b for b in body if b)))


# ── Terminal triage ─────────────────────────────────────────────────────────────────────────

W = 88
STATUS_GLYPH = {'waiting-on-you': '⚠', 'blocked': '✗', 'running': '▶', 'idle': '‖', 'done': '✓'}
KEEP_RE = re.compile(r'`[^`]+`|<[a-zA-Z][^<>]*>(?:[^<>]*</[a-zA-Z][a-zA-Z0-9-]*\s*>)?')


def _wrap(text, first, rest=None, width=W):
    """Wrap on spaces only. URLs, paths, tags and `code` spans are never split; a token wider than the
    line gets a line of its own and may run past the width."""
    rest = first if rest is None else rest
    text = re.sub(r'\s+', ' ', _s(text)).strip()
    text = KEEP_RE.sub(lambda m: m.group(0).replace(' ', '\x00'), text)
    lines = textwrap.wrap(text, width=width, initial_indent=first, subsequent_indent=rest,
                          break_on_hyphens=False, break_long_words=False) or [first.rstrip()]
    return [ln.replace('\x00', ' ') for ln in lines]


def _one_line(prefix, text, width=W):
    """prefix + the text's first line on one terminal line: cut at a space with ' …' when it is prose,
    kept whole (past the width) when it is one unbreakable token such as a tag or URL."""
    first = _s(text).strip().split('\n', 1)[0].strip()
    more = '\n' in _s(text).strip()
    line = prefix + first
    if len(line) <= width and not more:
        return line
    if is_code(first) or ' ' not in first:
        return line + (' …' if more else '')
    keep = KEEP_RE.sub(lambda m: m.group(0).replace(' ', '\x00'), first)
    cut = keep[:max(0, width - len(prefix) - 2)]
    if ' ' in cut and len(prefix + keep) > width:
        cut = cut[:cut.rindex(' ')]
    elif len(prefix + keep) <= width:
        cut = keep
    return (prefix + cut.rstrip(' ,;:') + ' …').replace('\x00', ' ')


def render_terminal(card, facts):
    facts = facts if isinstance(facts, dict) else {}
    L = labels(card)
    Y = Yours(card)
    status = card.get('status')
    gen = parse_ts(facts.get('generated_at')) or datetime.now().astimezone()
    if not gen.tzinfo:
        gen = gen.astimezone()
    out = []
    # 1. the verdict, with the task's name
    out += _wrap(f'{STATUS_GLYPH.get(status, "•")} {Y.verdict(L, status).rstrip(".")} · {_s(card.get("title"))}', '', '  ')
    # 2. status · pct · gap
    pr = card.get('progress') or {}
    p = pct(pr.get('done_pct'))
    gap = _s(pr.get('gap')).strip()
    out += _wrap(f'{L["status"].get(status, status or "?").upper()} · {p}% {L["done_word"]}' + (f' · {gap}' if gap else ''), '', '  ')
    # 3. last checked
    lc = card.get('last_checked') or {}
    when, secs, old = freshness(card, gen)
    by = _s(lc.get('by'))
    age = f' ({L["before_page"](dur_text(secs, L))})' if secs is not None and secs >= 0 else ''
    flag = f' · {L["old"]}' if old else ''
    what = _s(lc.get('what')).strip()
    out += _wrap(f'{L["t_checked"]} {L["by_who"](_s(lc.get("when")), L["by_map"].get(by, by))}{age}{flag}' + (f': {what}' if what else ''), '', '  ')
    if _s(lc.get('stale')).strip():
        out += _wrap(f'{L["t_stale"]}: {_s(lc.get("stale"))}', '', '  ')
    out.append('')
    # 4. what is the user's, grouped decide / do / waiting
    if not Y.mine:
        co = card.get('continue') or {}
        if _s(co.get('text')).strip():
            out += _wrap(co['text'], f'{L["t_type"]}: ', '  ')
            out.append('')
    shown, limit = 0, 4
    for kind, items in Y.groups():
        if shown >= limit:
            break
        out.append(f'{L["t_grp"][kind]} ({len(items)})')
        for x in items:
            if shown >= limit:
                break
            shown += 1
            tag = L['blocks'] if x.get('blocks') is True else L['optional']
            due = f', {L["due"](_s(x.get("due")))}' if x.get('due') else ''
            out += _wrap(f'[{tag}{due}] {_s(x.get("what"))}', '  ', '    ')
            if x.get('recommend'):
                out += _wrap(x['recommend'], f'    {L["t_rec"]}: ', '      ')
            for c in dicts(x.get('copy')):
                if _s(c.get('text')).strip():
                    out.append(_one_line(f'    {L["t_copy"]}: {_s(c.get("label"))}: ', c.get('text')))
            opts = dicts(x.get('options'))
            if opts:
                o = opts[default_option(x)]
                risky = f', {L["risky"].lower()}' if o.get('risky') else ''
                out += _wrap(_s(o.get('reply')), f'    {L["t_reply"]} ({_s(o.get("label"))}{risky}): ', '      ')
                others = [o2 for o2 in opts if o2 is not o]
                if others:
                    out += _wrap(' · '.join(_s(o2.get('label')) + (f' ({L["risky"].lower()})' if o2.get('risky') else '')
                                            for o2 in others), f'    {L["t_other"]}: ', '      ')
        out.append('')
    if len(Y.items) > shown:
        out.append(L['t_more'](len(Y.items) - shown))
        out.append('')
    while out and not out[-1]:
        out.pop()
    return '\n'.join(out)  # 5. main() prints the HTML path right after, always last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('card')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--facts')
    ap.add_argument('--out')
    a = ap.parse_args()
    try:
        card = json.load(open(a.card))
    except (OSError, ValueError) as e:
        sys.exit(f'card unreadable: {e}')
    problems = check(card)
    if a.check or problems:
        print('\n'.join(problems) or 'card OK')
        sys.exit(1 if problems else 0)
    facts = json.load(open(a.facts)) if a.facts else {}
    out = a.out or artifact_path(facts.get('cwd'), facts.get('name') or card.get('title'))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write(render_html(card, facts))
    print(render_terminal(card, facts))
    print(out)


if __name__ == '__main__':
    main()

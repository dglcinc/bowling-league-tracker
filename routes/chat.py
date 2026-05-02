"""
Local LLM chat endpoint — viewer-gated streaming Q&A over the bowling stats.

Architecture
------------
The model never writes SQL. It picks tools from `chat_tools.TOOL_SCHEMAS`,
the server runs them via `chat_tools.dispatch`, and the JSON results are
fed back to the model. All tools are read-only wrappers around helpers
in `calculations.py` and `routes/records.py`.

`/chat/ask` streams a Server-Sent Events response — measured warm
generation on the M4 base is ~20 tok/s, so a non-streamed wait would
feel broken. Three event types reach the browser:

- `tool_call`: each tool the model invokes during the run.
- `token`: each generated token of the final answer.
- `done`: emitted once after the stream completes; carries the full
  answer text and the list of tool calls actually executed.

Caps: max 4 tool-call rounds, 30 s wall-clock, 2 048 generated tokens.
"""

import json
import time

from flask import Blueprint, Response, current_app, jsonify, render_template, request, stream_with_context
from flask_login import current_user, login_required
import requests

from extensions import limiter
from models import ChatLog, db
from chat_tools import TOOL_SCHEMAS, dispatch


chat_bp = Blueprint('chat', __name__)


# ---------- configuration --------------------------------------------------

OLLAMA_URL = 'http://127.0.0.1:11434/api/chat'
OLLAMA_MODEL = 'llama3.1:8b-instruct-q4_K_M'

MAX_TOOL_ROUNDS = 4
WALL_CLOCK_SECONDS = 30
ANSWER_TOKEN_CAP = 2048

# Per-IP rate limit on the streaming endpoint. Local generation is
# expensive on the Mac mini — one in-flight ask at a time per caller is
# plenty for this read-only stats use case.
RATE_LIMIT = "20 per hour;5 per minute"


SYSTEM_PROMPT = """You are the stats assistant for the Mountain Lakes Men's Bowling League. Answer questions about bowlers, seasons, teams, and tournament history.

LEAGUE OVERVIEW
- 4 teams, ~65 active and historical bowlers.
- Each season is 26 weeks: 22 regular weeks + 4 post-season tournament weeks.
- Two venues over time: mountain_lakes_club (pre-2024) and boonton_lanes (2024-2025 onward).
- Active season is the most recent in `list_seasons`.

HANDICAP RULES (used by the league, not by you — tools already apply them)
- Established bowler with 6+ cumulative games: handicap = round((200 - prior_week_running_avg) * 0.9).
- New bowler under 6 games with no prior-year handicap: handicap = round((200 - tonight_avg) * 0.9).
- Returning bowler under 6 games with a prior-year handicap: prior-year handicap stays in effect.
- Blind score is 125 scratch + 60 handicap per game (configurable per season).

TOURNAMENT TYPES (post-season weeks 23-26)
- club_championship: team event, position-night scoring.
- indiv_scratch: Harry E. Russell Championship — individual scratch, top-10 qualifiers + write-ins.
- indiv_hcp_1: Chad Harris Memorial Bowl (was Buzz Bedford pre-2023) — individual handicap.
- indiv_hcp_2: Shep Belyea Open (was Rose Bowl pre-2023) — individual handicap.
- Tournament weeks are EXCLUDED from regular-season averages and handicaps.

HOW TO ANSWER
- Always call tools to gather data — do not guess names, ids, dates, or scores.
- To resolve a name, call `list_bowlers` (last-name substring, case-insensitive) or `list_seasons`.
- Prefer the most specific tool: `bowler_season_stats` for one bowler in one season; `bowler_career_stats` for their full history; `season_leaders` for a ranked season list; `all_time_records` / `most_improved` / `fun_stats` for league-wide superlatives.
- If a question is ambiguous (e.g. several bowlers share a surname), say so and list the candidates.
- Keep answers under ~150 words. Use plain prose; only use a short bulleted or numbered list when ranking 3+ items.
- Never invent a tool, a column, or a value. If a tool returns nothing, say so plainly."""


# ---------- helpers --------------------------------------------------------

def _sse(event_type, payload):
    """Format one Server-Sent Events frame. Each event is a single JSON
    object with a `type` key so the browser only needs one listener."""
    body = json.dumps({'type': event_type, **payload}, default=str)
    return f"data: {body}\n\n"


def _post_chat(messages, tools, *, stream):
    """Call Ollama /api/chat. Returns the streaming Response when
    stream=True; otherwise returns the parsed JSON body."""
    payload = {
        'model':    OLLAMA_MODEL,
        'messages': messages,
        'tools':    tools,
        'stream':   stream,
        'options':  {'num_predict': ANSWER_TOKEN_CAP},
    }
    if stream:
        return requests.post(OLLAMA_URL, json=payload, stream=True, timeout=WALL_CLOCK_SECONDS + 5)
    resp = requests.post(OLLAMA_URL, json=payload, timeout=WALL_CLOCK_SECONDS + 5)
    resp.raise_for_status()
    return resp.json()


def _run_tool_calls(tool_calls):
    """Execute every tool call from one assistant turn. Returns a list of
    `tool` messages plus a parallel list of (name, args, result) tuples
    suitable for the SSE stream and the ChatLog row."""
    tool_messages = []
    executed = []
    for call in tool_calls or []:
        fn = call.get('function') or {}
        name = fn.get('name') or ''
        args = fn.get('arguments') or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        try:
            result = dispatch(name, args)
        except Exception as exc:
            result = {'error': f'{type(exc).__name__}: {exc}'}
        executed.append({'name': name, 'arguments': args, 'result': result})
        tool_messages.append({
            'role':    'tool',
            'name':    name,
            'content': json.dumps(result, default=str)[:8000],
        })
    return tool_messages, executed


def _log_exchange(question, answer, executed):
    """Persist one ChatLog row at end of stream. Best-effort — never let
    a logging failure surface to the caller."""
    try:
        row = ChatLog(
            user_id=current_user.id if current_user.is_authenticated else None,
            question_text=question,
            answer_text=answer,
            tool_calls_json=json.dumps(executed, default=str) if executed else None,
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


# ---------- routes ---------------------------------------------------------

@chat_bp.route('/')
@login_required
def index():
    """Standalone Ask page. The Records → Ask tab will reuse the same
    JS/SSE plumbing once that PR lands; this page is a working surface
    for the streaming endpoint in the meantime."""
    return render_template('chat/index.html')


@chat_bp.route('/ask', methods=['POST'])
@login_required
@limiter.limit(RATE_LIMIT)
def ask():
    """SSE streaming endpoint. Loops over assistant turns: when the
    model emits tool_calls we execute them and feed the results back;
    when it emits final text we stream tokens straight to the browser."""
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'error': 'question is required'}), 400
    if len(question) > 2000:
        return jsonify({'error': 'question too long'}), 400

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user',   'content': question},
    ]

    @stream_with_context
    def generate():
        deadline = time.monotonic() + WALL_CLOCK_SECONDS
        executed_all = []
        final_answer_chunks = []
        try:
            for round_idx in range(MAX_TOOL_ROUNDS + 1):
                if time.monotonic() > deadline:
                    yield _sse('error', {'message': 'timed out'})
                    break

                # Non-streaming call when we still expect possible tool
                # calls — Ollama only returns the parsed `tool_calls`
                # array reliably in non-streaming mode. The final answer
                # round is streamed token-by-token below.
                if round_idx < MAX_TOOL_ROUNDS:
                    body = _post_chat(messages, TOOL_SCHEMAS, stream=False)
                    msg = body.get('message') or {}
                    tool_calls = msg.get('tool_calls') or []
                    if tool_calls:
                        tool_msgs, executed = _run_tool_calls(tool_calls)
                        executed_all.extend(executed)
                        messages.append({
                            'role':       'assistant',
                            'content':    msg.get('content') or '',
                            'tool_calls': tool_calls,
                        })
                        messages.extend(tool_msgs)
                        for ev in executed:
                            yield _sse('tool_call', {
                                'name':      ev['name'],
                                'arguments': ev['arguments'],
                            })
                        continue
                    # Model went straight to a final answer with no
                    # tools — emit it as tokens and stop.
                    text = msg.get('content') or ''
                    if text:
                        final_answer_chunks.append(text)
                        yield _sse('token', {'text': text})
                    break

                # Final round: stream the answer.
                resp = _post_chat(messages, TOOL_SCHEMAS, stream=True)
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if time.monotonic() > deadline:
                        yield _sse('error', {'message': 'timed out'})
                        break
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    piece = (chunk.get('message') or {}).get('content') or ''
                    if piece:
                        final_answer_chunks.append(piece)
                        yield _sse('token', {'text': piece})
                    if chunk.get('done'):
                        break
                break

            answer = ''.join(final_answer_chunks).strip()
            _log_exchange(question, answer, executed_all)
            yield _sse('done', {
                'answer':     answer,
                'tool_calls': executed_all,
            })
        except requests.RequestException as exc:
            current_app.logger.warning('Ollama call failed: %s', exc)
            yield _sse('error', {'message': 'local model unavailable'})
        except Exception as exc:  # pragma: no cover — last-ditch
            current_app.logger.exception('chat.ask failed')
            yield _sse('error', {'message': f'{type(exc).__name__}'})

    headers = {
        'Content-Type':      'text/event-stream',
        'Cache-Control':     'no-cache',
        'X-Accel-Buffering': 'no',  # disable nginx/proxy buffering
    }
    return Response(generate(), headers=headers)

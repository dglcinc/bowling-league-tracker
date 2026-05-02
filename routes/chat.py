"""
Cloud LLM chat endpoint — viewer-gated streaming Q&A over the bowling stats.

Architecture
------------
The model never writes SQL. It picks tools from `chat_tools.TOOL_SCHEMAS`,
the server runs them via `chat_tools.dispatch`, and the JSON results are
fed back to the model. All tools are read-only wrappers around helpers
in `calculations.py` and `routes/records.py`.

`/chat/ask` streams a Server-Sent Events response. Three event types
reach the browser:

- `tool_call`: each tool the model invokes during the run.
- `token`: each generated token of the final answer.
- `done`: emitted once after the stream completes; carries the full
  answer text and the list of tool calls actually executed.

Caps: max 4 tool-call rounds, 30 s wall-clock, 2 048 generated tokens.

Backend: Anthropic Claude API. Requires `ANTHROPIC_API_KEY` in the
environment. Model is `claude-sonnet-4-6` by default; override with
`CHAT_MODEL`. The system prompt + tool catalog are cached via
`cache_control` (5-minute TTL) so a burst of questions in one session
shares the same prefix.
"""

import json
import os
import time

import anthropic
from flask import Blueprint, Response, current_app, jsonify, render_template, request, stream_with_context
from flask_login import current_user, login_required

from extensions import limiter
from models import ChatLog, db
from chat_tools import TOOL_SCHEMAS, dispatch  # TOOL_SCHEMAS is in Anthropic tool-spec shape.


chat_bp = Blueprint('chat', __name__)


# ---------- configuration --------------------------------------------------

CHAT_MODEL = os.environ.get('CHAT_MODEL', 'claude-sonnet-4-6')

MAX_TOOL_ROUNDS = 4
WALL_CLOCK_SECONDS = 30
ANSWER_TOKEN_CAP = 2048

# Per-IP rate limit on the streaming endpoint. Each ask costs a few
# cents in API tokens; this is a small private league, not a public
# bot — so caps are tight to bound abuse and runaway loops.
RATE_LIMIT = "20 per hour;5 per minute"


SYSTEM_PROMPT = """You are the stats assistant for the Mountain Lakes Men's Bowling League. Answer questions about bowlers, seasons, teams, and tournament history.

LEAGUE OVERVIEW
- 4 teams, ~65 active and historical bowlers.
- Each season is 26 weeks: 22 regular weeks + 4 post-season tournament weeks.
- Two venues over time: mountain_lakes_club (pre-2024) and boonton_lanes (2024-2025 onward).
- Active season is the most recent in `list_seasons`.

HANDICAP RULES (used by the league, not by you — focused tools already apply them)
- Established bowler with 6+ cumulative games: handicap = round((200 - prior_week_running_avg) * 0.9).
- New bowler under 6 games with no prior-year handicap: handicap = round((200 - tonight_avg) * 0.9).
- Returning bowler under 6 games with a prior-year handicap: prior-year handicap stays in effect.
- Blind score is 125 scratch + 60 handicap per game (configurable per season).

TOURNAMENT TYPES (post-season weeks 23-26, weeks.tournament_type column)
- club_championship: team event, position-night scoring.
- indiv_scratch: Harry E. Russell Championship — individual scratch, top-10 qualifiers + write-ins.
- indiv_hcp_1: Chad Harris Memorial Bowl (was Buzz Bedford pre-2023) — individual handicap.
- indiv_hcp_2: Shep Belyea Open (was Rose Bowl pre-2023) — individual handicap.
- Tournament weeks are EXCLUDED from regular-season averages and handicaps.

WHAT IS NOT IN THE DATA
- Pin-level data is NOT tracked. Strikes, spares, splits, opens, and frame-by-frame outcomes do not exist anywhere in the schema — only per-game total scores (0-300).
- If a question requires anything not in the data (strikes, splits, individual frames, demographics, attendance, weather, etc.), say so plainly and stop. Do not substitute a different statistic.

DATABASE SCHEMA (use `query_db` for ad-hoc aggregations)
SQLite. Read-only SELECT. Tables you can query:
- bowlers(id, last_name, first_name, nickname, email)
- seasons(id, name, start_date, num_weeks, venue, is_active, half_boundary_week, blind_scratch, blind_handicap, bowling_format) — venue ∈ {mountain_lakes_club, boonton_lanes}
- teams(id, season_id, number, name)
- roster(bowler_id, season_id, team_id, active, prior_handicap, joined_week)
- schedule(season_id, week_num, matchup_num, team1_id, team2_id, lane_pair)
- weeks(season_id, week_num, date, is_position_night, is_cancelled, is_entered, tournament_type) — tournament_type ∈ {club_championship, indiv_scratch, indiv_hcp_1, indiv_hcp_2, NULL}; NULL = regular week
- matchup_entries(season_id, week_num, matchup_num, team_id, bowler_id, is_blind, lane_side, game1, game2, game3, game4, game5, game6) — game1-game3 are primary; game4-game6 are legacy and mostly NULL
- team_points(season_id, week_num, matchup_num, team_id, points_earned)
- tournament_entries(season_id, week_num, bowler_id, guest_name, game1, game2, game3, game4, game5, handicap, place) — place ∈ {1, 2, 3, NULL}; bowler_id NULL means a write-in (use guest_name)
- club_championship_results(season_id, place, team_id)

HOW TO ANSWER
- Always call tools — do not guess names, ids, dates, or scores.
- To resolve a name to an id, query `bowlers` or `seasons` with `query_db` (e.g. `SELECT id, last_name, first_name FROM bowlers WHERE last_name LIKE '%lewis%'`).
- Use the focused tools when the question needs handicap math or business rules:
    * `bowler_season_stats` — YTD averages, highs, handicap for one bowler/season.
    * `bowler_career_stats` — per-season averages and highs across a bowler's career.
    * `season_leaders` — bowlers ranked by season average.
    * `all_time_records` — all-time top-N for HG/HS scratch and HG/HS hcp; best season averages.
    * `most_improved` — largest season-over-season average gain.
    * `weekly_prizes` — high game / high series winners (scratch and handicap) for one week.
- Use `query_db` for everything else — counts, sums, mins/maxes, tournament placements, raw game totals, who-played-when. Examples:
    * "Who has won the Harry Russell most?" → JOIN tournament_entries with weeks ON (season_id, week_num) WHERE tournament_type='indiv_scratch' AND place=1, GROUP BY bowler_id, ORDER BY count DESC LIMIT 10. Then JOIN bowlers to get names.
    * "How many 200+ games does X have?" → SELECT COUNT(*) FROM matchup_entries WHERE bowler_id=X AND is_blind=0 AND (game1>=200 OR game2>=200 OR game3>=200).
- Do NOT use `query_db` for season averages, running averages, handicap, or high-series-with-handicap — the focused tools handle the blind-skipping and tournament-week-exclusion business rules. Plain SQL on `matchup_entries` will get those wrong.
- If a question is ambiguous (e.g. several bowlers share a surname), list the candidates and ask which one they meant.
- Keep answers under ~150 words. Use plain prose; only use a short bulleted or numbered list when ranking 3+ items.
- Never invent a tool, a column, or a value. If a tool returns nothing, say so plainly.
- If no available tool or query can answer the question, say "I don't have data on that" and explain in one short sentence what is and isn't tracked. Never substitute a different statistic.
- Make tool calls silently. Do not narrate which tool you are about to call, what you found in intermediate results, or what you are about to do next. Output only the final answer to the user's question."""


# ---------- helpers --------------------------------------------------------

def _client():
    """Lazy-initialised Anthropic client. Reads ANTHROPIC_API_KEY from env."""
    return anthropic.Anthropic()


def _sse(event_type, payload):
    """Format one Server-Sent Events frame. Each event is a single JSON
    object with a `type` key so the browser only needs one listener."""
    body = json.dumps({'type': event_type, **payload}, default=str)
    return f"data: {body}\n\n"


def _dispatch_tool(name, args):
    """Run one tool. On exception, return an error dict — the model will
    see it in the next turn and can recover or refuse."""
    try:
        return dispatch(name, args)
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


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
    """Standalone Ask page. The Records → Ask tab reuses the same JS/SSE
    plumbing; this page is a thin wrapper around the streaming endpoint."""
    return render_template('chat/index.html')


@chat_bp.route('/ask', methods=['POST'])
@login_required
@limiter.limit(RATE_LIMIT)
def ask():
    """SSE streaming endpoint. Loops over assistant turns: when the
    model emits tool_use blocks we execute them and feed the results
    back as a tool_result; when it emits final text we stream tokens
    straight to the browser."""
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify({'error': 'question is required'}), 400
    if len(question) > 2000:
        return jsonify({'error': 'question too long'}), 400

    client = _client()

    # `system` as a list of text blocks lets us attach cache_control.
    # Tools render before system in the request, so this single
    # breakpoint caches both tools and system together.
    system = [{
        'type':          'text',
        'text':          SYSTEM_PROMPT,
        'cache_control': {'type': 'ephemeral'},
    }]
    messages = [{'role': 'user', 'content': question}]

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

                with client.messages.stream(
                    model=CHAT_MODEL,
                    max_tokens=ANSWER_TOKEN_CAP,
                    system=system,
                    tools=TOOL_SCHEMAS,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if time.monotonic() > deadline:
                            yield _sse('error', {'message': 'timed out'})
                            return
                        if event.type == 'content_block_delta' and event.delta.type == 'text_delta':
                            text = event.delta.text
                            if text:
                                final_answer_chunks.append(text)
                                yield _sse('token', {'text': text})
                    final = stream.get_final_message()

                if final.stop_reason != 'tool_use':
                    # end_turn / max_tokens / refusal — we're done.
                    break

                # Extract tool calls, dispatch each, build tool_result blocks.
                tool_use_blocks = [b for b in final.content if b.type == 'tool_use']
                tool_results = []
                for tu in tool_use_blocks:
                    result = _dispatch_tool(tu.name, dict(tu.input or {}))
                    executed_all.append({
                        'name':      tu.name,
                        'arguments': dict(tu.input or {}),
                        'result':    result,
                    })
                    yield _sse('tool_call', {
                        'name':      tu.name,
                        'arguments': dict(tu.input or {}),
                    })
                    tool_results.append({
                        'type':         'tool_result',
                        'tool_use_id':  tu.id,
                        'content':      json.dumps(result, default=str)[:64000],
                    })

                # Append the assistant's full content (text + tool_use blocks)
                # and the tool_result user turn. Anthropic requires these to
                # be paired in order.
                messages.append({'role': 'assistant', 'content': final.content})
                messages.append({'role': 'user', 'content': tool_results})

                if round_idx == MAX_TOOL_ROUNDS:
                    yield _sse('error', {'message': 'too many tool rounds'})
                    break

            answer = ''.join(final_answer_chunks).strip()
            _log_exchange(question, answer, executed_all)
            yield _sse('done', {
                'answer':     answer,
                'tool_calls': executed_all,
            })
        except anthropic.APIError as exc:
            current_app.logger.warning('Anthropic call failed: %s', exc)
            yield _sse('error', {'message': 'chat backend unavailable'})
        except Exception as exc:  # pragma: no cover — last-ditch
            current_app.logger.exception('chat.ask failed')
            yield _sse('error', {'message': f'{type(exc).__name__}'})

    headers = {
        'Content-Type':      'text/event-stream',
        'Cache-Control':     'no-cache',
        'X-Accel-Buffering': 'no',  # disable nginx/proxy buffering
    }
    return Response(generate(), headers=headers)


@chat_bp.route('/feedback', methods=['POST'])
@login_required
def feedback():
    """Record a thumbs-up / thumbs-down on the caller's most recent
    ChatLog row. Body: {"helpful": true|false}. Scoped to the current
    user so a click only ever updates their own row."""
    data = request.get_json(silent=True) or {}
    helpful = data.get('helpful')
    if helpful not in (True, False):
        return jsonify({'error': 'helpful must be true or false'}), 400

    row = (ChatLog.query
           .filter_by(user_id=current_user.id)
           .order_by(ChatLog.id.desc())
           .first())
    if row is None:
        return jsonify({'error': 'no recent question to mark'}), 404

    row.helpful = helpful
    db.session.commit()
    return jsonify({'ok': True, 'id': row.id, 'helpful': helpful})

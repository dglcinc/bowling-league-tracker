# Payout Feature — Implementation Plan

## Overview

End-of-season payout calculator. Takes a configured total available amount, applies a
waterfall of deductions, distributes the remainder to teams, and produces a printable
totals sheet plus individual award pages for every recipient.

---

## Pages Added

### Admin: Payout Config
Linked from the season admin page. Stores one `PayoutConfig` row per season.

Fields:
- **Total available** — dollar amount entered by treasurer
- **Tournament prizes** — 1st place, 2nd place, 3rd place (dollar amounts, default $125/$100/$75)
- **Weekly win rate** — per weekly prize win (default $10)
- **YTD prize rate** — per YTD prize (default $75); covers HG/HS scratch+hcp and Most Improved
- **Trophy cost** — flat deduction (default $125)
- **Team payout percentages** — configurable percentages for 1st through Nth place finish
  (must sum to 100%; applied to the team remainder pool)

### Report: Payout Summary (Totals Sheet)
Main output page. Three sections:

1. **Individual payouts** — one row per recipient with itemized reasons and total
2. **Team payouts** — team name, finish position, points, dollar amount
3. **Currency breakdown** — per-payee bill breakdown + aggregate bank inventory

### Report: Award Page (per recipient)
Printable award certificate for each person or team receiving money, designed for
handing out at the end-of-season banquet. One page per recipient, rendered at
letter size portrait.

**Visual design:**
- **Border**: Guilloche-style ornamental border built from an inline SVG repeating
  pattern — two interlocking sine wave bands in a rope/braid motif, rendered in deep
  navy (#1a3a6b) and gold (#c9a227). The border occupies the full page perimeter as
  a fixed-position SVG overlay so it prints correctly without browser color-adjust
  hacks.
- **Fonts**: Google Fonts loaded inline — *Playfair Display* (serif, formal) for the
  league name, season, and recipient name; *Lato* (clean sans-serif) for the prize
  detail table and totals. Both served via `<link>` in the template head so they
  print from a local server without internet access concerns (fallback to Georgia /
  system sans-serif).
- **Color scheme**: Deep navy headings, gold accent rule below the recipient name,
  light warm-grey (#faf8f4) page background, standard black for table content.
- **Layout**: League crest/title block at top center, decorative gold rule, recipient
  name large and centered (nickname on next line in smaller italic), team name below
  that, then a centered prize table, then a bold total line, then a congratulatory
  footer line ("Presented by the Mountain Lakes Men's Bowling League").

Shows:
- League name and season
- Recipient name + nickname (individual) or team name + captain name (team)
- Itemized prize list with full details (see below)
- Total dollar amount, prominently displayed

---

## Data Model

New `PayoutConfig` table:

| Column | Type | Default |
|---|---|---|
| `season_id` | FK Season | — |
| `total_available` | Decimal | — |
| `tournament_prize_1` | Decimal | 125.00 |
| `tournament_prize_2` | Decimal | 100.00 |
| `tournament_prize_3` | Decimal | 75.00 |
| `weekly_win_rate` | Decimal | 10.00 |
| `ytd_prize_rate` | Decimal | 75.00 |
| `trophy_cost` | Decimal | 125.00 |
| `team_pct_1` through `team_pct_N` | Decimal | configurable |

Tournament week designation uses an existing flag on the `Week` model (to be confirmed).

---

## Calculation Waterfall

Starting with `total_available`:

### 1. Tournament Awards
- Identify weeks flagged as tournament weeks
- For each tournament week, rank bowlers by individual handicap total for that week
- Pay 1st, 2nd, 3rd the configured fixed dollar amounts
- Deduct the sum of tournament prizes from the running total

### 2. Individual Awards

**Weekly prizes** ($10/win, configurable):
- Source: existing weekly prize tracker in `routes/payout.py`
- Each bowler's win count × `weekly_win_rate`
- Categories: HG Handicap, HG Scratch, HS Handicap, HS Scratch

**YTD prizes** ($75 each, configurable):
- Source: `get_bowler_stats` results at week 22 (final week)
- Categories and winners:
  - YTD High Game — Scratch (1 winner)
  - YTD High Game — Handicap (1 winner)
  - YTD High Series — Scratch (1 winner)
  - YTD High Series — Handicap (1 winner)
  - Most Improved (1 winner — back-calculates prior average from `prior_handicap`
    using `prior_avg = 200 − (prior_handicap / 0.9)`, compares to end-of-season
    average, winner is the bowler with the largest pin-per-game improvement;
    first-year members with no `prior_handicap` are excluded)
- Iron Man: **discontinued**, not included

Deduct total individual awards from the running total.

### 3. Trophy Deduction
- Flat `trophy_cost` ($125 default), no named payee
- Deduct from running total

### 4. Team Remainder
- Whatever remains is distributed to teams ranked by full-season points
- Distribution uses configurable place percentages (e.g., 40%/30%/20%/10%)
- Team payouts are listed by team name + captain, not by individual player

---

## Totals Sheet Layout

**Section 1 — Individual Payouts**

| Bowler | Prize Details | Amount |
|---|---|---|
| Smith (Smitty) | Week 3 HG Handicap, Week 7 HS Scratch, Week 7 HG Scratch, YTD HG Handicap | $105.00 |

Prize detail format:
- Weekly: `Week N — High Game Handicap (score)`
- Tournament: `Tournament Week N — 1st Place (score)`
- YTD: `YTD High Series — Scratch (score)`
- Most Improved: `Most Improved (prior hcp NNN → current avg NNN)`

**Section 2 — Team Payouts**

| Place | Team | Points | Amount |
|---|---|---|---|
| 1st | Team Name | 142 | $XXX.00 |

**Section 3 — Currency Breakdown**

Per-payee table showing bill breakdown (100s / 50s / 20s / 10s / 5s / 1s), computed
using a greedy largest-first algorithm.

Followed by an aggregate totals row summing all bills across all payees — this is the
exact bank inventory to pull.

---

## Award Page Layout (per recipient)

One page per recipient (letter portrait), designed for handing out at the banquet.
Rendered in the browser and printed — no PDF generation library needed.

```
╔══════════════════════════════════════════════════════╗  ← guilloche SVG border
║                                                      ║
║         MOUNTAIN LAKES MEN'S BOWLING LEAGUE          ║  Playfair Display, navy
║                    2025–2026 Season                  ║  Playfair Display, smaller
║                                                      ║
║          ════════════════════════════                ║  gold rule
║                                                      ║
║                    John Smith                        ║  Playfair Display 28pt, navy
║                    "Smitty"                          ║  Playfair Display 16pt italic
║                    Team 3 — The Rollers              ║  Lato, grey
║                                                      ║
║          ════════════════════════════                ║  gold rule
║                                                      ║
║     Week 3    High Game — Handicap    243    $10     ║
║     Week 7    High Series — Scratch   612    $10     ║
║     Week 7    High Game — Scratch     224    $10     ║
║     YTD       High Game — Handicap    243    $75     ║
║               ─────────────────────────────          ║
║               Total Award                  $105      ║  bold, larger
║                                                      ║
║          ════════════════════════════                ║  gold rule
║                                                      ║
║    Congratulations from the Mountain Lakes Men's     ║  Lato italic, small
║              Bowling League — 2025–2026              ║
║                                                      ║
╚══════════════════════════════════════════════════════╝
```

Prize detail format:
- Weekly: `Week N — High Game Handicap (score)`
- Tournament: `Tournament Week N — 1st Place (score)`
- YTD: `YTD High Series — Scratch (score)`
- Most Improved: `Most Improved — improved N pins per game (prior avg NNN → NNN)`
  Certificate description line (shown below the prize table): *"[Name] improved his
  average by N pins per game over last season, from NNN to NNN."*

For team awards the layout is identical but shows team name large, captain name
below it in smaller text, and the prize line reads e.g.
`Season — 1st Place   142 pts   $XXX`.

---

## Open Questions Resolved

- **Tournament format**: individual competition, top 3 by handicap score
- **YTD rate**: $75 per prize (distinct from $10 weekly rate)
- **Most Improved**: included at $75. Two equivalent methods, both back the same
  winner:
  - *Current approach*: largest decrease in handicap (`prior_handicap` − `display_handicap`
    at week 22). A drop in handicap means an increase in average, so the bowler with
    the biggest handicap drop wins.
  - *Suggested approach*: back-calculate `prior_average` from `prior_handicap` using
    `prior_avg = 200 − (prior_handicap / 0.9)`, then compare to `current_average`.
    Reports the winner's improvement as pins-per-game (e.g., "improved 12 pins"),
    which is the number bowlers actually talk about and is more intuitive on the award
    page. Mathematically identical to the handicap-delta approach (handicap is a
    linear transform of average), but the display is clearer.
  - **Implementation will use the back-calculated pin improvement** so the award page
    can show "improved N pins per game" as the prize description.
  - Bowlers with no `prior_handicap` on record (first-year members) are excluded.
- **Iron Man**: discontinued — not included in payout calculations

---

## Files To Be Created / Modified

| File | Change |
|---|---|
| `models.py` | Add `PayoutConfig` model |
| `routes/payout.py` | Add config CRUD + payout calculation + award page routes |
| `templates/payout/config.html` | Config entry form |
| `templates/payout/summary.html` | Totals sheet (3 sections) |
| `templates/payout/award_page.html` | Per-recipient award certificate |
| `templates/admin/season_detail.html` | Add "Payout Config" link |
| `templates/payout/overview.html` | Add link to Summary and Award Pages |

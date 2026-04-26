# Bowling League iOS App — Plan

## Overview

iPhone-only native SwiftUI app for the Mountain Lakes Men's Bowling League.
iPad users continue using the Flask web app at mlb.dglc.com (works well as-is).
Target audience: ~65 bowlers who want quick access to lane assignments, standings, and scores.

## Primary Use Case

Answer the question every bowler has before leaving for the alley:
**When are we bowling, where am I, and what kind of night is it?**

## Home Screen (most important)

Content depends on season state:

**Regular season** — upcoming week's lane assignments for all bowlers.
The logged-in bowler's own lane is highlighted. Shows date/time prominently.
If prior week scores aren't entered yet: "Last week results pending."
Once entered: one-line result ("Your team won 6–2 last week").

**Post-season tournaments** — tournament name + date.
For Club Championship specifically: show both team matchups and lanes
(since it functions like a regular matchup and bowlers need opponent/lane info).

**Off-season** — next season start date if known, or "Season complete" + link to final standings.

## Tab Structure

| Tab | Content |
|-----|---------|
| **Home** | Upcoming week / lane assignments; notification bell in nav bar |
| **Standings** | Team points table; week selector for history; tap team for breakdown |
| **Scores** | Browse any entered week; bowler name, games, handicap, series; tap bowler for season detail |
| **Me** | My season stats (avg, HG, HS), week-by-week history, notification preferences |

## Push Notifications

Three independently toggleable notification types (managed in Me → Notification Settings):

| Notification | When sent | Example message |
|-------------|-----------|-----------------|
| "Bowling tomorrow" | Evening before bowl date (e.g. Sunday 6pm) | "Bowling tomorrow at 7pm. You're on lanes 3-4 vs Team 2." |
| "Bowling tonight" | Morning of bowl day (e.g. 9am) | "Tonight: lanes 3-4 vs Team 2. See you there." |
| "Scores are in" | After each week's scores are entered | "Week 14 scores posted. Your team went 6-2 and moves to 2nd place." |

### Server-side notification infrastructure

- `push_tokens` table in DB: `bowler_id`, `device_token`, `platform`, `preferences` (JSON)
- APNs credentials in `.env`: `.p8` key file path, Team ID, Key ID (all free via Developer portal)
- `send_notifications.py` script — queries DB, checks trigger conditions, sends via APNs HTTP/2
- launchd timer on utility Mac runs the script on schedule
- Flask API endpoint for app to register/update device token and preferences

## Requirements

| Requirement | Detail |
|------------|--------|
| Apple Developer Account | $99/year — required for TestFlight, App Store, and APNs |
| APNs key | `.p8` key file from Developer portal (free, doesn't expire) — add Team ID + Key ID to `.env` |
| Xcode | Free, already on dev Mac |
| TestFlight | Beta distribution to bowlers before App Store submission |
| Flask REST API | New `/api/v1/` blueprint; web app unaffected |

## Architecture

### Flask REST API (new `/api/v1/` blueprint)

Key endpoints:
- `POST /api/v1/auth/request-otp` + `POST /api/v1/auth/verify-otp` → session token (stored in iOS Keychain)
- `GET /api/v1/seasons/current/upcoming` → home screen data (lane assignments, tournament info, next date)
- `GET /api/v1/seasons/{id}/standings`
- `GET /api/v1/seasons/{id}/weeks/{n}` → scores for a week
- `GET /api/v1/bowlers/me` → logged-in bowler's season stats + history
- `POST /api/v1/push/register` → device token + notification preferences
- `PATCH /api/v1/push/preferences` → update notification settings

### SwiftUI App Structure

```
BowlingApp/
├── Auth/          OTP login flow, Keychain token storage
├── Home/          Lane assignments, tournament state, upcoming date
├── Standings/     Team table, week-by-week breakdown
├── Scores/        Week browser, bowler detail
├── Me/            My stats, notification preferences
├── Models/        Codable structs matching API responses
├── API/           URLSession networking layer
└── Notifications/ APNs registration, local preference storage
```

## Build Order

1. **Apple Developer account + APNs key** — prerequisite, takes ~1 day for approval
2. **Flask REST API blueprint** — auth, lane assignments, standings, scores, push token registration
3. **SwiftUI app — core viewer** — Home screen with lane assignments, Standings, Scores, Me tab
4. **TestFlight beta** — distribute to bowlers, gather feedback
5. **Push notifications** — server-side sender script + preference UI in app
6. **App Store submission**

## Status

- [ ] Apple Developer account created
- [ ] APNs key generated
- [ ] Flask REST API blueprint
- [ ] SwiftUI app — core viewer
- [ ] TestFlight beta
- [ ] Push notifications
- [ ] App Store submission

---

## Addendum — PWA/Flask Mobile Web Approach (2026-04-11)

**Decision:** Build mobile-optimized Flask views first, as a PWA. Native Swift app deferred.
This covers all planned features for both iPhone and Android with ~30% of the native app effort.

### Architecture

**Device detection:** User-Agent check in `before_request`. iPhone and Android mobile UAs redirect to `/m/` by default. A `prefer_desktop` cookie suppresses the redirect permanently (set when user taps "Full site"). Desktop users with a small browser window are unaffected.

**Preference toggle:**
- Mobile pages have a "Full site" link in the footer → sets `prefer_desktop` cookie → redirects to desktop home
- Desktop nav has a "Mobile site" link (or auto-detects on very small screens) → clears cookie → redirects to `/m/`

**Admin/editor on iPhone:** Default lands on mobile view. "Full site" link provides full access when needed (score entry, admin panel). No role-based routing — the escape hatch is always available.

**Blueprint:** New `mobile_bp` at `/m/`, separate mobile templates extending a mobile base. Login-required on all mobile routes (reuses existing auth).

### Mobile views (match the iOS app tab structure)

| Route | Content |
|---|---|
| `GET /m/` | Home: upcoming lane assignment (logged-in bowler highlighted), last week result, tournament state |
| `GET /m/standings` | Team points table, week selector |
| `GET /m/scores` | Week browser; tap week → bowler list with games/series |
| `GET /m/me` | My season stats (avg, HG, HS scratch+hcp), week-by-week history, notification preferences |

### Push notifications

**Protocol:** Web Push (RFC 8030) with VAPID keys — no Apple Developer account needed. Works on Android without PWA install; requires PWA install on iOS 16.4+.

**Server side (Python):**
- `pywebpush` library
- VAPID key pair generated once, stored in `.env` (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CLAIMS_EMAIL`)
- `push_subscriptions` table: `bowler_id`, `subscription_json` (endpoint + auth keys), `platform`, `preferences` (JSON: `bowling_tomorrow`, `bowling_tonight`, `scores_posted`)
- `POST /m/push/subscribe` — stores subscription from browser JS
- `PATCH /m/push/preferences` — updates notification toggles
- `send_notifications.py` — checks trigger conditions, sends via pywebpush; launchd timer runs it on schedule

**Three notification types** (each independently toggleable in Me tab):
- **Bowling tomorrow** — evening before bowl date (6pm): "Bowling tomorrow at 7pm. You're on lanes 3-4 vs Team 2."
- **Bowling tonight** — morning of bowl day (9am): "Tonight: lanes 3-4 vs Team 2. See you there."
- **Scores posted** — after `week.is_entered` flips True: "Week 14 scores posted. Your team went 6–2."

**iOS onboarding:** Must install PWA first, then enable notifications. Me tab shows install prompt if not installed, then permission prompt once installed.

### Build order

1. **Mobile blueprint skeleton + detection** — `mobile_bp`, before_request redirect, prefer_desktop cookie, Full site / Mobile site toggle, mobile base template
2. **Home screen** — upcoming lane assignments (personalized), last week result, tournament/off-season states
3. **Standings + Scores + Me** — responsive views for each tab
4. **Push infrastructure** — VAPID keys, push_subscriptions table, subscribe/preferences endpoints, send_notifications.py, launchd timer
5. **Me tab notifications UI** — install prompt (iOS), permission prompt, toggle preferences

### PWA status checklist

- [ ] Mobile blueprint + detection + preference toggle
- [ ] Home screen (lane assignments, last week, tournament state)
- [ ] Standings tab
- [ ] Scores tab
- [ ] Me tab (stats + history)
- [ ] Push subscription infrastructure
- [ ] send_notifications.py + launchd timer
- [ ] Me tab notification UI (install prompt + toggles)
- [ ] Android testing
- [ ] iOS PWA install + notification testing

# 17. Polish: push from a scheduler, an installable app, the palette, accessibility

Date: 2026-10-05 · Status: Accepted (Phase 11; refines ARCHITECTURE.md sections 3, 4, 11 and ADRs 14-15)

## Decision

**Push comes from a `scheduler` process.** ADR 14 made reminders lazily,
when you open the app. Push must reach you when the app is closed, so the
cron `scheduler` from section 4 now exists (`app/workers/scheduler.py`, its
own Arq queue and compose service). Every 5 minutes it makes any reminders
now due for each user with a subscribed device (the same rules, switches and
quiet hours as the bell), then pushes each unread, unpushed one, no older than
24 hours, to every device, once (`notifications.pushed_at`). Nothing is
pushed in your quiet hours; it waits. A device the push service reports gone
(404/410) is forgotten at once; one that fails 3 times in a row, after that.

**VAPID keys are secrets in `.env`.** `make vapid-keys` generates the pair
and writes only missing keys to `.env`, never printing the private one. Push
is off until all three settings exist. A browser's endpoint is unique: the
same browser signed in as someone else moves to them.

**An installable app, but no offline data.** A web manifest, icons
(including maskable) and a service worker (`public/sw.js`). The worker shows
pushed reminders, opens the right page when one is tapped, and shows an
offline page when a page cannot load. It never caches API responses, so
nothing you see is stale. Phone installation and phone push need HTTPS, so
they work once deployed (Phase 13); on this computer, localhost counts as
secure.

**The command palette (Ctrl+K) replaces Ctrl+K-to-search.** Built on cmdk
(section 1) inside our own Radix dialog, so it has a proper title. It goes
to any page, starts the daily quiz or a module's mock exam, opens a module's
materials, questions, flashcards or coding, switches theme, and searches.
"/" now focuses the search box. Other shortcuts: Ctrl+J asks Claude about
the module you are in, "g" then a letter goes somewhere, "?" lists them all.
Shortcuts never fire while you type in a field or the code editor.

**Phones.** Below 768 px the sidebar becomes a drawer behind a top bar
(menu, search, bell); the calendar's week becomes a list of days, and its
month shows counts. Every page was checked at 375 px for sideways scrolling.

**Today ranks its panels** (deferred by ADR 15). Deterministic, no AI: each
panel scores its place in the usual order (`analytics.yaml`), plus a boost
when it is pressing (an exam within 7 days; today's quiz not done; 10+ cards
due; recurring mistakes). A panel that moved up says why.

**Accessibility.**

- axe-core runs in the test suite on every main page, signed out and in,
  the palette, the shortcuts sheet and the phone menu; no violations allowed.
  A guard test proves axe does report problems.
- Colour contrast is tested from `index.css` itself: every text and
  background pair in both themes meets WCAG AA (4.5:1). This found white text
  on the dark theme's red (2.4:1), fixed with an `on-danger` token.
- A custom accent stays readable: text on it is white or black, whichever
  contrasts more (always at least 4.58:1), and the accent as text is nudged
  lighter or darker per theme only as far as AA needs.
- The calendar was `role="grid"` without rows (invalid); it is now a list of
  days, each labelled with its full date.
- A skip link, a focusable `<main>`, and a crash page instead of a blank
  screen if a page fails.
- In a real browser, axe (with contrast) found no violations on 15 pages at
  phone size in both themes, and on 7 at desktop size.

## Verification limits

- The built-in browser used for checks blocks notifications and service
  workers, so a push to a real browser was not observed there. The sender
  was tested for real against a local push service: the message decrypts
  with the device's key and the VAPID signature verifies; the service
  worker's handlers were tested against a fake worker scope.
- A local test account (`ui-check@revision-os.test`) was created in the dev
  database for these checks; it has its own sample modules and does not
  touch yours.

## Consequences

- One more process to run (`scheduler`), small and idle without push keys.
- Phone use needs deployment for HTTPS; until then, use it on this computer.

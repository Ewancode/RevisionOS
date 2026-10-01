# 7. Sessions, CSRF and access control details

Date: 2026-10-01 · Status: Accepted (refines ARCHITECTURE.md section 12)

## Context

Section 12 fixes the shape — Argon2id, opaque session cookie, double-submit
CSRF header, user-scoped repositories, closed registration. Phase 2 had to
settle the details.

## Decision

**Sessions.** A random 256-bit token in a `__Host-rev_session` cookie
(HttpOnly, Secure, SameSite=Lax, Path=/, no Domain). Only its SHA-256 is
stored. Sessions end after `session_idle_hours` without use or
`session_absolute_days` regardless (`config/platform.yaml`). Every login
issues a new token and revokes any session the browser already held.
Changing the password revokes all other sessions.

**CSRF.** Each session also gets a random CSRF token, sent in a readable
`__Host-rev_csrf` cookie and stored hashed on the session row. Unsafe
requests must echo it in `X-CSRF-Token`, checked against the stored hash.
This is the double-submit pattern from section 12, made stronger by binding
the token to the session server-side, so a cookie planted by a sibling
domain cannot satisfy it. Login itself is protected by SameSite and by the
API accepting only JSON bodies.

**Rate limiting.** Login attempts are limited per client IP *and* per email
in Redis (fixed window). Keys hold hashes, not addresses. A success resets
both counters.

**Account enumeration.** Unknown email and wrong password return the same
401 and take the same time (a dummy Argon2 verification runs for unknown
emails).

**Access control.** Routers are protected by default: only health and login
sit on the public router. Another user's resource returns **404, not 403**,
so ids cannot be probed. Ownership is enforced twice — repositories filter by
user, and composite foreign keys tie each row's `user_id` to its parent's.

**Soft delete.** Modules and topic subtrees get `deleted_at`. Topics deleted in
one operation share a timestamp, so restoring a topic brings back exactly what
was deleted with it and nothing deleted earlier. The purge after
`trash.retention_days` arrives with the scheduler.

**Deferred.**
- Optional TOTP two-factor moves to Phase 12 (hardening).
- Behind a reverse proxy, the client IP used for rate limits and the audit log
  is the proxy's. In development that is the Vite proxy. Trusted-proxy
  handling of `X-Forwarded-For` is configured at deployment (Phase 13).

## Consequences

Tests cover each rule: cookie attributes, hashed storage, idle and absolute
expiry, CSRF, rate limits, enumeration, logout and password-change
revocation. Two further tests read the route list from the OpenAPI schema,
so new endpoints are covered automatically: one asserts every non-public
route rejects anonymous calls; the other asserts every id-taking route is in
the cross-user (IDOR) attack list.

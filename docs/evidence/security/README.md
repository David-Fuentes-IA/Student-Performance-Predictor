# Adversarial review: the application under a hostile client (Milestone 4)

The software review will be done by a reviewer acting as a hostile client: invalid types, injection strings, URLs typed by
hand, fake files. Before that, the team attacked its own application the same way, fixed what broke, and kept the attack
as a repeatable script and as regression tests. No new feature was added: every change is input validation or an error
message.

```bash
docker start spp-mongo-test                                            # throw-away MongoDB on port 27018
MONGODB_TEST_URI=mongodb://localhost:27018 python scripts/adversarial_check.py
```

The script runs the real application (the same `create_app()` gunicorn serves) against a throw-away database that it
drops at the end, so the team's database is never touched.

## What is attacked (437 requests per run)

| Area | Inputs |
|---|---|
| Group and student identifiers in every URL | empty, `..`, `../../etc/passwd`, encoded `%2e%2e%2f`, `<script>`, `' OR 1=1 --`, `{"$gt":""}` and `$where` (MongoDB operator injection), 5,000 characters, emoji, `%00`, CR/LF header injection, right-to-left mark, `CON` |
| Hidden files and paths | `/.env`, `/.git/config`, `/static/../.env`, encoded traversal into `core/config.py`, `/templates/admin.html`, `/console`, `/debug` |
| Wrong HTTP methods | `PUT`, `PATCH`, `DELETE`, `POST` on read-only routes |
| JSON bodies of the admin API | no body, invalid JSON, arrays, numbers, strings, `null`, objects where text is expected, a 100,000-character id, absurd counts (`1e400`, `-1`, `true`) |
| Student values | text, `null`, `true`, `NaN`, `1e308`, out of range, nested lists and objects, 10,000 grades, empty or 100,000-character names, HTML in the name |
| Excel uploads | text, empty file, executable and plain zip renamed `.xlsx`, a zip bomb (200 MB when inflated), no header, wrong headers, text grades, formulas, `true` as a grade, duplicates, missing ids, 1,001 rows, a 5 MB file, `../../evil.xlsx` as the name |
| Collection browser | negative, huge and non-numeric `limit` / `skip` |
| Error log viewer and exports | regex characters and catastrophic patterns in the search (`.*`, `(a+)+$`), `$where`, 5,000 characters, invalid levels, kinds and dates, absurd `limit` / `skip` |
| Administrator password (set for this part) | every protected route without it, and with path tricks (`//`, `/./`, `/../`, upper case, trailing slash) |
| Afterwards | the dashboard, the panel, health, readiness, the group API and the PDF must all still answer 200 |

## Result

| Run | Findings |
|---|---|
| Code as merged to `main` (before this review) | **5**: four answered **500** (a `skip` beyond 64 bits in the collection browser; a demo-data request whose body was a number, a string, or `count: 1e400`) and one answered **503 "the database did not respond"** to a student with 50 grades, blaming the database for bad input |
| After the fixes | **0** findings in 407 requests |
| After adding the error log, the password lockout and the e-mail alerts (2026-11-22) | **0** findings in 437 requests (the PDF-only export has fewer routes than the first version with CSV, which had 452) |

No response, before or after, contained a traceback, a file path, a driver name or a connection string; HTML in names is
always escaped; no route could be reached without the password once one is set; hidden files are never served.

The script only flags errors and leaks. Reading the answers it got turned up five more defects, where a hostile value was
**accepted** when it should have been rejected:

| # | Defect | Effect | Fix |
|---|---|---|---|
| 1 | `{"group_id": null}` stored as the text `"None"` | a group literally called "None" | text fields accept only text (or a number, for a matrícula); `null` is empty → 400 |
| 2 | JSON `true` accepted as a number | a grade or attendance of **1** | booleans and `null` are not numbers → 400 (the Excel import already refused them) |
| 3 | more than 4 partial grades in the manual form API | the database's schema rejected the write → misleading 503 | at most 4 partials, the same limit as the Excel template → 400 with the reason |
| 4 | `"reset": "false"` (a string) in the demo-data request | counted as **true**, so it would have erased the previous demo data | only a real JSON `true` resets |
| 5 | out-of-range values explained in English (`student 'S7' has an invalid grade: 101.0`) in the panel and in the Excel rejection list | inconsistent with the rest of the interface | Spanish message that keeps the value: `S7: calificacion invalida: 101.0 (debe ser un numero entre 0 y 100)` |

**Found later, with the error log (2026-11-22): log injection (CWE-117).** A URL containing `%0d%0a` was written to the
text log with real line breaks, so an attacker could add a fake line (for example a made-up `ADMIN` entry). Line breaks
inside a logged message are now written as `\r` / `\n` (`core/logger.py`); test in `tests/unit/test_event_log.py`.

**E-mail alerts (2026-11-22)** were designed against the attacks they invite: mail flooding (one summary every 5
minutes at most, rejected input never mailed), header injection (fixed subject, values on one line; test with
`\r\nBcc:` in the path), secrets (SMTP settings only in `.env`), and loops (a failure to send is a WARNING, never mailed).
Tests: `tests/unit/test_email_alerts.py`.

One more change for anyone typing a wrong address: Flask's English "Not Found" page and messages were replaced by a short
Spanish page with a link back to the dashboard (JSON with a Spanish message under `/api/` and `/admin/api/`).

Regression tests: `tests/integration/test_hostile_input.py` (every defect above, plus the wrong-URL answers).

## Checked by hand against the running container (real HTTP through gunicorn)

`/.env`, `/.git/config`, `/static/..%2f..%2f.env` and `/../../etc/passwd` → 404; `system.users` in the collection browser
→ 400 "Coleccion no permitida"; a 9,000-character URL → 414 from gunicorn; `TRACE` → 405; security headers present on
every answer (`tests/integration/test_security_hardening.py`).

## What the review does not cover (stated, not hidden)

- **No authentication for teachers.** Without `ADMIN_PASSWORD` the panel is open by design of the prototype: anyone who
  reaches it can delete groups (the red "Sin contraseña" chip says so). For a demo in front of others, set
  `ADMIN_PASSWORD`. Teacher login is a new feature and Milestone 4 forbids new features (see `docs/M4_CORRECCION.md` §5.3).
- **No general rate limiting.** Only the administrator password has an attempt limit (10 wrong passwords lock the
  address for 3 minutes, `tests/integration/test_admin_lockout.py`). A client can repeat valid requests as fast as it likes (for example, generating 500 demo students
  over and over). It degrades speed, not correctness.
- The attack is automated and broad, not a professional penetration test; it does not cover the network (HTTPS is not
  configured), the MongoDB server itself, or denial of service.

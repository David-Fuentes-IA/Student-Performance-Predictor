# Accessibility audit (Milestone 4, criterion 5)

Standard used: **WCAG 2.1, level AA** (the W3C's Web Content Accessibility Guidelines, the most widely used reference for
web accessibility). Scope: the two screens of the application, the teacher dashboard (`/`, with a group loaded and the student
card open) and the administration panel (`/admin`, with a group open). Audited on 2026-11-18 in a Chromium browser with a
script run in the page that measures, for every visible text, the contrast against its real background (WCAG formula), and
lists form fields without an associated label, buttons and links without an accessible name, and elements that react to the
mouse but not to the keyboard. The checks are kept by `tests/system/test_accessibility_markup.py`.

## Findings and corrections

| # | Screen | Finding (WCAG criterion) | Before | Correction | After |
|---|---|---|---|---|---|
| 1 | Dashboard | Secondary text too light: subtitle, table headers, alert-rule tag (1.4.3 Contrast) | 4.26:1 | `--muted` #70758b → #626779 | ≥ 4.89:1 |
| 2 | Dashboard | "⚠ Alerta" and "Alto riesgo" red (1.4.3) | 4.45:1 | `--high` #c43c50 → #b02a42 | ≥ 5.61:1 |
| 3 | Dashboard | "En observación" amber (1.4.3) | 3.79:1 | `--medium` #ac7014 → #8c5a0b | ≥ 5.10:1 |
| 4 | Admin | 18 form fields whose `<label>` was not tied to the field: a screen reader announced "edit text" with no name (1.3.1, 4.1.2) | 0 of 18 tied | `for`/`id` on every label, `aria-label` on the collection selector | 18 of 18 |
| 5 | Admin | Group list items opened only with the mouse (2.1.1 Keyboard) | not focusable | `tabindex="0"`, `role="button"`, Enter/Space open the group, visible focus outline | Tab + Enter works |
| 6 | Admin | White text on the green "MongoDB conectado" badge (1.4.3) | 4.17:1 | `--green` #1e8e4e → #17703d | 6.14:1 |
| 7 | Admin | Grey secondary text on the selected group (1.4.3) | 3.76:1 | `--muted` #6b7a8c → #566373 | ≥ 5.26:1 |
| 8 | Admin | Green and amber tags ("excel", "synthetic") (1.4.3) | 3.60 / 3.22:1 | same green; `--yellow` #b7791f → #8a5a10 | 5.29 / 5.24:1 |

After the corrections the same audit reports **0 contrast failures, 0 unlabeled fields and 0 controls without a name** on both
screens, and the browser console shows no errors.

## Already in place before this audit

- Both pages declare their language (`<html lang="es">`), so screen readers use Spanish pronunciation.
- Dashboard: every field has a label; buttons have accessible names (for example "Ver detalle de *nombre*", "Cerrar ficha");
  status messages use `role="status"`/`aria-live`, errors `role="alert"`; the student card is a native `<dialog>` (focus trap,
  Escape closes it); the page signals loading with `aria-busy`.
- **Risk levels are never shown by colour alone**: each one carries its text ("Alto riesgo", "En observación", "Buen camino") and
  every alert its written reason, so colour-blind users lose no information (1.4.1 Use of Color).
- Responsive layout down to phone width (`viewport` meta; the admin grid collapses to one column under 900 px).

## Limitations (not audited or not fixed)

- No test with real assistive technology (NVDA/JAWS) or with users with disabilities; the audit is automated plus manual
  keyboard checks.
- The PDF reports are not tagged PDFs (reportlab output): a screen reader reads them as plain text without structure.
- Charts in the dashboard (level bars, grade columns) have their numbers as text next to them, but no long description.
- The interface is Spanish only.
- The administration page still keeps its script inside the HTML, which is also why the Content-Security-Policy must allow
  inline scripts (see `docs/MANUAL_TECNICO_BRIEF.md`, security).

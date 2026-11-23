# Milestone 4 report brief: Student Performance Predictor (Team 5)

> **For the assistant who writes the report.** This file gives you everything needed for the Milestone 4 written report
> (ethical, legal and social aspects) and for the software review: the professor's Milestone 3 feedback and what was
> corrected, and the facts about the system that the ethics, bias, privacy, social-impact and risk sections must rest on.
> You already have the team's earlier documents. The Milestone 3 material is in `docs/M3_CORRECCION.md`.
>
> **Rules**
> 1. Write the report **in English**.
> 2. Use **only** the facts and numbers here. Every number comes from a script or a file in the repository.
> 3. Never present as implemented what is marked *proposed*, *partial* or *not implemented*. The professor values that
>    the team "recognises its limitations": keep doing it.
> 4. All data are **synthetic**. Never claim the model works on real students. Never claim it beats the school rule:
>    the experiment in section 2 shows it does not, in the simulation.
> 5. Legal references: cite them as verified **only** where this brief says so; the rest must be worded "to be verified in
>    the official text".
> 6. Where a screenshot belongs, write `[SCREENSHOT: ...]`.
> 7. Milestone 4 forbids new features. Everything changed in this milestone is a **correction** of something the
>    professor or our own audits found; present it that way. **One deliberate exception (2026-11-22):** the error log
>    ("Bitacora de errores", row 11). The team added it knowingly, because the reviews of other teams centred on security
>    and auditability; present it as a team decision that strengthens auditing (M3 oral question 6), not as a correction.

Repository: <https://github.com/David-Fuentes-IA/Student-Performance-Predictor>. Branch with this work: **`milestone-4`**
(built on `milestone-3`). Team: Gabriel de Anda Romero, David Nava Fuentes, Marco Uriel Romero Hurtado, Axel Rubén López
Soto, Fernando Saúl Domínguez Hernández. Licence: academic project, all rights reserved (`LICENSE`). Course: Software Engineering II, UAEMéx, professor M. en I. Jéssica Cortés.

---

## 0. Rubric and where each criterion is answered

| # | Criterion (Milestone 4 report, 10 pts) | Pts | Section of this brief | Evidence in the repo |
|---|---|---|---|---|
| 1 | Corrections from Milestone 3 (problems, modifications, evidence) | 1.0 | 1, 2 | commits in section 1, `docs/evidence/model/`, `docs/evidence/accessibility/`, `docs/evidence/docker/soak_test.json` |
| 2 | Ethical considerations (fairness, transparency, accountability, risks; how they shaped design) | 1.5 | 3 | `core/risk_levels.py`, `feature_store/`, `docs/evidence/model/README.md` |
| 3 | Bias, fairness, responsible AI (sources, consequences, strategies) | 1.5 | 4 | `docs/evidence/model/README.md` §7, `data/README.md` |
| 4 | Data privacy, security, legal compliance (regulations, how data are protected) | 2.0 | 5 | `core/logger.py`, `webapp/`, `docs/DATABASE.md`, `k8s/secret.example.yaml` |
| 5 | Social impact and accessibility | 1.5 | 6 | `docs/evidence/accessibility/README.md` |
| 6 | Responsible deployment and risk mitigation (risks, mitigations, human oversight, responsible use) | 1.5 | 7 | `k8s/README.md`, `docs/evidence/docker/README.md` |
| 7 | Final integration and technical consistency (conclusions backed by evidence, real capabilities and limits) | 1.0 | 8 | all `docs/evidence/*` |

The **software review (30 points)** checks: corrections from Milestone 3, that the software works, consistency between
system and documentation, evidence of improvements. Section 9 lists how to show each correction live.

---

## 1. Milestone 3 result and feedback

Written report **9.5 / 10**: corrections of M2 1.0/1.0, testing 2.0/2.0, model validation **1.7**/2.0, CI/CD 1.5/1.5,
containers **1.4**/1.5, performance 1.5/1.5, evidence **0.4**/0.5. Milestone total 3.0 (written 0.95, presentation 0.6,
questions 1.5).

What the professor praised: solid technical work, extensive documentation, traceability requirements → architecture →
implementation → tests, attention to earlier feedback, four test levels, comparative model validation, performance analysis,
and that the team acknowledges its limitations.

### Observations and what was done (criterion 1)

| # | Observation (M3 feedback) | What was done in Milestone 4 | Evidence | Commit |
|---|---|---|---|---|
| 1 | **Statistics:** "the team claims that non-overlapping confidence intervals prove a real improvement; that needs more careful justification, especially because the rules were evaluated on the same students" | The claim was wrong in method: same students ⇒ **paired** samples. Added the exact **McNemar** test (only students on which two rules disagree carry information) and a paired bootstrap. Every rule comparison and the LR vs RF comparison now report it. Result: the applied rule's gain over the model alone **is** significant (18 vs 0 discordant at-risk students, p = 7.6 × 10⁻⁶; CV 30 vs 0, p = 1.9 × 10⁻⁹); LR vs RF is **not** (4 vs 1, p = 0.375; CV 7 vs 4, p = 0.55) | `docs/evidence/model/README.md` §3–4, `metrics.json` → `paired_tests`, `paired_model_comparison`; `learning_module/model_validation.py` (`mcnemar_exact`, `paired_comparison`, `paired_bootstrap_difference`) | `afb393a` |
| 2 | **Value of the AI:** "the failing-average rule identifies practically all the high-risk cases; justify more deeply the additional value of the model" | Designed and ran the experiment the professor asked for (oral question 1): every method flags **the same number of students**; ranking by average = the school rule = the ablation of the other features; a stronger two-indicator rule; and **early detection** after the first or the first two partial exams. All comparisons paired. **Honest result:** in the simulation the model does **not** find at-risk students better than the school rule at any stage (no p < 0.12); it **does** beat a fixed two-indicator rule (significant in 4 of 6 comparisons, e.g. 61 vs 50 caught, p = 0.003). The model part of the rule stays at 75 (lowering it only adds workload). Real value can only be shown with real data; the protocol is written down | `docs/evidence/model/README.md` "Does the model add value beyond the school rule?", `ai_value.md`, `ai_value.json`; `scripts/ai_value_experiment.py` | `afb393a` |
| 3 | **Synthetic data only:** "does not yet demonstrate predictive capacity in a real academic environment" | Cannot be corrected without institutional data (none available; it would need authorisation and a privacy notice). Stated in every result; the validation protocol for real data is specified (out-of-time split, same paired statistics, enough at-risk students: several hundred for differences of a few points) | `docs/evidence/model/README.md` conclusion 5 | — |
| 4 | **Authentication, authorisation and data protection** must be strengthened before institutional use | Teacher login is a **new feature** (forbidden in M4), so it is documented as a prerequisite, not built. Corrections made without new features: security headers on every response (Content-Security-Policy, no framing, no MIME sniffing, no referrer); every rejected administrator password logged (never the value tried); a warning in the start-up log and a red "Sin contraseña" chip in the panel when a database is configured and the admin password is empty; `docs/DATABASE.md` no longer recommends opening Atlas to `0.0.0.0/0`. The admin password was already compared in constant time | `webapp/__init__.py` (`SECURITY_HEADERS`), `webapp/admin.py`, `templates/admin.html`, `tests/integration/test_security_hardening.py` | `cb13fe7` |
| 5 | **Containers:** "no evidence of prolonged operation" (−0.1) | Soak test: the container kept a steady teacher-like load for **120 min** with **2,321** requests; result: **0 errors (100 % availability), 0 restarts, healthy in all 120 samples, latency stable (median 20.5 ms, p95 75.2 ms), memory 281.7 → 301.1 MiB** (still rising slowly at the end: a longer run would be needed to show it levels off) | `scripts/soak_test.py`, `docs/evidence/docker/soak_test.json` | `5654252` + evidence commit |
| 6 | **Evidence:** notifications are logged but not sent; no complete authentication; synthetic data; parts are future work (−0.1) | Kept as acknowledged limitations (no new features). The alert log line already says "not sent: notifications are not implemented" (corrected at the end of M3) | `core/audit_observer.py` | `ff3b946` |
| 7 | Oral question 6: "what risks does isolating observer failures introduce for auditing?" | Risk: a broken alert observer would only leave a log line. Correction: the publisher **counts** failures per observer and `/health` reports them (`observer_failures`), so a silent failure is visible without reading logs; liveness is unaffected | `core/audit_observer.py` (`failure_counts`), `webapp/dashboard.py`, tests in `tests/unit/test_observer_and_errors.py`, `tests/integration/test_pipeline_flow.py` | `23392a0` |
| 8 | "Tomorrow you must run tests and show the results, not only screenshots" / "reproduce at least one measurement" | The software review will run tests and a measurement live (section 9) | — | — |
| 9 | Own audit (criterion 5 of M4): accessibility | WCAG 2.1 AA audit of both screens in a browser: 8 findings fixed (contrast of 3 dashboard colours and 4 admin colours; 18 form labels not tied to their fields; group list not usable with the keyboard). After: 0 contrast failures, 0 unlabeled fields | `docs/evidence/accessibility/README.md`, `tests/system/test_accessibility_markup.py` | `733e98e` |
| 10 | Own audit (criteria 4 and 7): the application under a hostile client | `scripts/adversarial_check.py` sends 407 hostile requests (invalid types, MongoDB operator injection, path traversal, hidden files, fake and zip-bomb Excel files, password-bypass tricks) to every route on a throw-away database. Before: 5 findings (four 500s, one misleading 503). Reading the answers found 5 more inputs wrongly **accepted** (`null` stored as a group called "None", JSON `true` as a grade of 1, more than 4 partials, `"reset": "false"` treated as true, English rejection messages). All fixed as input validation; after: 0 findings. No leak of internals and no password bypass before or after | `docs/evidence/security/README.md`, `tests/integration/test_hostile_input.py` | this commit |
| 11 | Team decision (2026-11-22): auditing of failures, the gap behind M3 oral question 6 (section 5.3 still applies: successful reads are not recorded, there is no access log) | **Error log (new feature, see note 7):** every warning, error and rejected request is kept in MongoDB (`event_log`, all time) with time, level, kind, request, client address and a **reference code**; the user sees only a short message plus the code, the administrator finds that exact request in `/admin` → *Bitacora de errores* (filters by level, kind, text, dates) and exports it to **PDF** or **CSV**. Building it, the adversarial run (now 452 requests, 0 findings) found a **log injection** (a `%0d%0a` URL could forge a line in the text log), fixed | `core/event_log.py`, `webapp/admin.py`, `docs/evidence/security/README.md`, `tests/unit/test_event_log.py`, `tests/integration/test_error_log_api.py` | this commit |

Tests after the corrections (strict run against MongoDB, 2026-11-18): unit 166 (+59 sub-cases), integration 91 (+95),
system 78 (+60), memory profiling 6: **341 tests and 214 sub-cases (555 checks), 0 failed, 0 skipped; statement coverage
94.8 %** (322 before the error log of row 11) (it was 288 tests and 373 checks at the end of Milestone 3). The full suite (322 tests) passed in the CI on `a5e6432` (run 44426511738: build, tests, model
quality gate, container and Kubernetes all green, 8 min 31 s); the earlier 310-test suite had passed on `babba75` (run
44331833747).

---

## 2. The AI-value experiment in one table (for criterion 1 and the conclusions)

Recall at **the same workload** (students flagged = those the school rule flags). Synthetic data; p = exact McNemar.

| Partials known | Data | Ranking by average (= school rule) | Logistic Regression | p | Two-indicator rule (avg < 60 or attendance < 80) vs LR at its workload |
|---|---|---|---|---|---|
| first only | independent (64 at risk) | 33 | 36 | 0.51 | 50 vs **61**, p = 0.003 |
| first two | independent | 39 | 40 | 1.0 | 52 vs **60**, p = 0.02 |
| all | independent | 46 | 44 | 0.73 | 55 vs 60, p = 0.125 |
| first only | cross-validation (165 at risk) | 108 | 107 | 1.0 | 141 vs 151, p = 0.053 |
| first two | cross-validation | 111 | 113 | 0.79 | 143 vs **159**, p = 0.0004 |
| all | cross-validation | 117 | 121 | 0.45 | 148 vs **158**, p = 0.03 |

Average precision (threshold-free ranking quality), LR − average, 95 % paired bootstrap: every interval contains 0 (e.g. all
partials, independent: −0.004 [−0.046, +0.033]).

**What this means:** in this simulation the average grade carries almost all the information (the model's weight on it is
about 9 times that of attendance or participation; the simulator was built that way). The model's value is (a) combining
several indicators correctly, which a hand-made multi-indicator rule does worse; (b) a continuous ranking and the "En
observación" band (score ≥ 40), which shows students who still pass; (c) a framework that would capture more signal **if
real data contain it**. It is **not** demonstrated that it finds students the school rule misses.

---

## 3. Ethical considerations (criterion 2)

Write this as issues → how they shaped the design → what remains.

| Principle | Issue in this project | How it influenced design and operation (implemented) | Remaining risk |
|---|---|---|---|
| **Human agency / accountability** | A risk label can become a decision about a person | The system **only recommends**: no automatic action exists (no grade change, no sanction, no message to the student). Every alert is "for teacher review" (DR-2). The legend and footer say "El riesgo estimado orienta la revisión del docente" | No record of the teacher's decision, so accountability for what was done with an alert is outside the system |
| **Transparency / explainability** | A score without a reason invites blind trust | Each alert states its **reason** (failing average and/or high estimated risk) on screen, in the tooltip and in the PDF; the rule and thresholds are shown on screen ("Alerta: promedio < 6 o riesgo ≥ 75"); the student card shows the four data behind the score; the model is a logistic regression whose weights are published (`docs/evidence/model/README.md` §5); a model card records how it was trained (`models/model_card.json`); PDFs say suggestions are based on indicators and "no explican causalmente la predicción" | The score is not explained per student (no per-student contribution of each feature) |
| **Honesty about capability** | Overselling "AI" when the school rule does as well ("AI-washing") | The team measured and **published** that the model adds no detection beyond the school rule in the simulation, and kept the model's threshold at 75 rather than tuning it to look useful; all figures labelled synthetic | Readers may still over-trust a tool labelled "AI" |
| **Fairness** | Error rates may differ by group | A fairness audit by subgroup runs with every validation (DR-3, section 4) | Only one synthetic subgroup can be audited |
| **Privacy / data minimisation** | Students' academic data are personal data | The model sees **no names** (DR-1); logs redact names; only 4 indicators are used, no demographic attribute is a model input | Student IDs in logs; no retention policy (section 5) |
| **Non-maleficence** | False positives stigmatise; false negatives leave students without help | Recall is the priority metric (missing a student is worse), with a precision floor so alerts stay credible; a quality gate in CI blocks a worse model (recall, precision ≥ 0.60, F1 ≥ 0.65) and rejects suspiciously perfect scores | with the application's rule 18 of 64 at-risk students are still missed (recall 0.719); teachers must not read "Buen camino" as a guarantee |
| **Reliability** | A broken component could silently stop alerts | Isolated observer failures are now **counted and reported in `/health`**; fail-fast start-up (no fake data if the database is down); 4 levels of tests in CI | — |

---

## 4. Bias, fairness and responsible AI (criterion 3)

**Sources of bias** (be concrete; each with consequence):

| Source | Where | Possible consequence |
|---|---|---|
| **Synthetic data** | the simulator decides who ends at risk | the model learns the simulator's rules; real relationships may differ entirely (section 5 of the M3 feedback) |
| **Label definition** | "at risk" = ended the term with low performance | ignores dropout reasons, students who pass with difficulty, or students helped by tutoring (the label is influenced by past interventions: feedback loop) |
| **Proxy variable: attendance** | evening-shift students attend ~7 points less for the same engagement (built into the simulation as a plausible work-schedule effect) | students who work are flagged more often for a reason that is not academic |
| **Incomplete records** | 29 % of missed students have fewer than 4 partial grades vs 11 % of caught ones | students who start late or miss exams are under-detected |
| **Fixed thresholds** | 6.0 and 75 for all courses and groups | a hard course or a strict teacher shifts who is flagged |
| **Algorithmic weight** | the average grade dominates (−3.11 logit per SD vs −0.35 attendance, −0.30 participation); the grade trend is barely used | students whose grades are falling sharply but still pass are missed (5 of 19 sharply declining at-risk students) |
| **Output / human bias** | a label can change how a teacher treats a student (self-fulfilling prophecy); automation bias (trusting the score over one's own judgement) | stigma, lower expectations; ignoring students labelled "Buen camino" |

**Measured fairness audit** (synthetic subgroup *turno*, model cut at 50, independent set):

| Shift | Students | False-positive rate (95 % CI) | False-negative rate (95 % CI) | Flagged |
|---|---|---|---|---|
| Morning | 143 | 6.7 % (3.3–13.3) | 35.9 % (22.7–51.6) | 22.4 % |
| Evening | 97 | 9.7 % (4.8–18.7) | 12.0 % (4.2–30.0) | 29.9 % |

Evening students get more false alarms and are flagged more; morning at-risk students are missed more. The direction matches
the mechanism built into the data, **but the intervals overlap**: "a possible disparity this sample cannot confirm" (the
groups are different students, so per-group intervals are the right tool here, unlike the paired comparisons of section 1).

**Strategies** (state which are in place):

| Strategy | Status |
|---|---|
| No demographic attribute (shift, sex, age) is a model input; the subgroup is used only to audit | implemented |
| Fairness audit with every validation run; report false-positive and false-negative rates with intervals | implemented (`scripts/evaluate_models.py`) |
| Human review of every alert; reasons shown; school criterion explicit | implemented |
| "En observación" band so borderline students are visible without being labelled high risk | implemented |
| Re-audit each term on real data, with larger groups; set a tolerance for gaps (e.g. false-negative rate gap) and act when exceeded | proposed |
| Treat students with fewer than 3 partials as "insufficient data" for teacher review instead of scoring them | proposed |
| Review attendance as a feature with the institution (it can penalise working students) | proposed |
| Calibrate thresholds per course or term | proposed |
| Model card and datasheet published with each model version | partial (`models/model_card.json` is technical) |

---

## 5. Data privacy, security and legal compliance (criterion 4, the heaviest)

### 5.1 Personal data inventory (what the system holds)

| Data | Where | Who can see it | Purpose |
|---|---|---|---|
| Student ID (matrícula) and full name | MongoDB `students` | dashboard, PDFs, admin panel | identify the student for the teacher |
| Partial grades, attendance %, participation | `academic_records`, with a snapshot per change in `record_history` | dashboard, PDFs, admin | compute the four indicators |
| Risk score, level, timestamp per prediction | `predictions` (by student ID, no name) | admin database browser | traceability of predictions |
| Group ID, name, period, **teacher name** | `groups` | dashboard, admin | organise groups |
| Import metadata (file name, counts) | `import_logs` (no student data) | admin | audit of imports |
| Logs | `logs/spp_YYYYMMDD.log` and container output | whoever operates the server | operation and audit |

Logs contain **student IDs** (`AUDIT-TRAIL` and `RISK ALERT` lines), never names (redacted by `core/logger.py::sanitize`;
a test asserts no student name reaches any log line). Rejected admin logins log the client address. There is **no retention
period** for predictions, history or logs. The PDFs, once downloaded, live on the teacher's device.

### 5.2 How information is protected (implemented)

- **Data minimisation and pseudonymisation in the AI layer (DR-1):** `FeatureVector` carries an ID and four numbers, never a
  name; names are re-attached only in the presentation layer.
- **Secrets:** the database address and admin password live only in `.env` (git-ignored), environment variables or a
  Kubernetes Secret (`k8s/secret.example.yaml` has placeholders only); connection strings are redacted in logs; the git history
  contains no real connection string.
- **Integrity:** JSON-Schema validators and unique indexes in MongoDB; Fail-Fast validation of every record and file.
- **Safe errors:** users never see tracebacks, hosts or paths; checked by an adversarial run of 452 hostile requests against
  every route (0 findings; `docs/evidence/security/README.md`). A wrong URL gets a Spanish page with a way back.
- **Access:** optional `ADMIN_PASSWORD` for `/admin` (constant-time comparison); rejected attempts logged; visible warning when
  open; security headers on every response (CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`).
- **Containers:** non-root user; in Kubernetes a read-only filesystem and dropped capabilities.
- **Synthetic data only**: no real student has ever been processed.

### 5.3 Gaps that must be closed before real data (say so plainly)

No teacher authentication or roles (anyone who reaches the dashboard sees every group); no HTTPS; no per-teacher access to
"own groups only"; no record of who viewed what; no retention/deletion policy; IDs in logs; no encryption decision for the
database at rest documented; no backups; no privacy notice for this system; no data-protection impact assessment.

### 5.4 Applicable legal framework (Mexico, verified on 2026-11-18 by web search)

- **Federal:** on **20 March 2025** the DOF published the new *Ley General de Protección de Datos Personales en Posesión de
  Sujetos Obligados* (public bodies), with a new *Ley General de Transparencia* and *Ley Federal de Protección de Datos Personales
  en Posesión de los Particulares*. The INAI was extinguished; its functions went to the *Secretaría Anticorrupción y Buen
  Gobierno* and its body *Transparencia para el Pueblo*. Official text: <https://www.diputados.gob.mx/LeyesBiblio/pdf/LGPDPPSO.pdf>;
  DOF note: <https://dof.gob.mx/nota_detalle.php?codigo=5752569&fecha=20%2F03%2F2025>.
- **Estado de México:** **Decreto 365**, published in the *Gaceta del Gobierno* on **1 October 2026** (per press reports),
  issues a new *Ley de Protección de Datos Personales en Posesión de Sujetos Obligados del Estado de México y Municipios* and a new
  transparency law, **extinguishes the INFOEM** and creates **Transparencia Mexiquense** (a body of the state Comptroller's office)
  as the local guarantor. Sources: El Universal Edomex
  (<https://www.eluniversaledomex.com.mx/gobierno/edomex-extingue-al-infoem-y-crea-transparencia-mexiquense/>), La Jornada
  (<https://www.jornada.com.mx/noticia/2026/08/20/estados/congreso-mexiquense-aprueba-nueva-ley-de-transparencia-y-desaparece-el-infoem>).
  **The official text was not read**: cite it as "to be verified in the Gaceta del Gobierno"
  (<https://legislacion.edomex.gob.mx/ve_periodico_oficial>); article numbers must not be quoted from memory.
- **UAEMéx** is a public autonomous university of the State, therefore a *sujeto obligado*. Its units publish privacy notices
  (*aviso de privacidad integral*); one of them (DIDEPA, version 05, approved 29 Sept 2025) cites the **previous** state law
  (<https://didepa.uaemex.mx/aviso-de-privacidad>), so the university's notices may need updating to the 2026 law. This
  system would need its own privacy notice before processing real records.
- What the report should discuss under these laws (as obligations to verify, not article quotes): lawful basis and specific
  purpose (academic support only); the duty to inform (privacy notice); data subjects' rights of access, rectification,
  cancellation and opposition (ARCO); security measures (administrative, physical, technical); whether the law addresses
  automated processing / profiling, and the importance of human review; data-protection impact assessment for a new system
  that processes students' data at scale; transfers (e.g. to a cloud provider such as MongoDB Atlas, whose servers may be abroad).
- **Standards and frameworks** to reference: ISO/IEC 27001 (information security management), ISO/IEC 42001 (AI management
  systems), NIST AI Risk Management Framework 1.0, UNESCO Recommendation on the Ethics of AI (2021), OECD AI Principles,
  WCAG 2.1 (accessibility, section 6).

---

## 6. Social impact and accessibility (criterion 5)

**Positive:** earlier attention for struggling students; a common, explicit criterion across teachers; less time to find who
needs help (a group of 50 in under 0.1 s); reports that support a conversation with the student or tutor; explicit reasons
make the alert discussable.

**Negative / risks:** stigma and labelling ("alto riesgo" seen by others); self-fulfilling prophecy; false reassurance for
students labelled "Buen camino" (with the application's rule 18 of 64 at-risk students are missed); automation bias; extra workload from false alarms
(1 in 4); students who work (evening shift) possibly flagged more; feeling of surveillance; the tool could be misused for
sanctions or grading.

**Inclusion and user needs:** teachers with little technical background (Spanish interface, plain-language levels, no ML
jargon, tooltips with reasons); students with incomplete records (under-detected, see bias); no teacher login means no
personalisation; the interface works at phone width.

**Accessibility (WCAG 2.1 AA, audited 2026-11-18):** 8 findings fixed (section 1, row 9). Already in place: `lang="es"`,
labelled fields and named buttons on the dashboard, `role="status"`/`role="alert"`, native `<dialog>`, and **levels never shown
by colour alone** (text label and written reason). Limitations: no test with screen-reader users; PDFs are not tagged;
charts have numbers but no long description; Spanish only. `[SCREENSHOT: dashboard with alert tooltip]`

---

## 7. Responsible deployment and risk mitigation (criterion 6)

**Risk register** (likelihood/impact: L/M/H):

| Risk | L | I | Existing control | Proposed mitigation |
|---|---|---|---|---|
| Unauthorised access to student data | H (no login) | H | optional admin password, warnings, headers | institutional login with roles; HTTPS; network restriction; access log |
| Model wrong on real students | H | H | quality gate, published limits | pilot with real historical data and the section 2 protocol before use |
| Missed at-risk student (false negative) | M | H | recall prioritised; school rule always applies | teachers keep their own judgement; "Buen camino" ≠ safe; observation band |
| Stigma from labels / misuse for sanctions | M | H | recommendations only; reasons shown | written use policy (below); training; labels visible only to the student's teachers |
| Unequal errors by group | M | M | fairness audit | per-term audit on real data with tolerance and action plan |
| Data breach of the database / leaked connection string | L–M | H | secrets out of git, redaction, non-root | IP allow-list (no 0.0.0.0/0), encryption at rest, backups, secret rotation |
| Silent failure of alerts | L | M | `observer_failures` in `/health`, CI tests | monitor `/health`; notify operators |
| Database outage | M | M | readiness 503, safe messages, recovery without restart (drilled) | managed database with backups |
| Data drift (new terms behave differently) | M | M | monitoring history (in memory) | retrain and re-validate each term; keep the quality gate |
| Over-trust in "AI" | M | M | honest documentation | training; show the school rule next to the score |

**Human oversight that exists:** the system never acts; every alert has a reason; thresholds are configuration and shown on
screen; the teacher sees the data behind the score; demo vs real mode is visible. **Missing:** recording the teacher's decision
(accept / dismiss with reason), an appeal path for students, a named human responsible for the model.

**Responsible use (intended / not intended):** intended: prioritising academic support and tutoring conversations, by the
student's own teachers or tutors. **Not intended:** grading, sanctions, admissions, scholarships, ranking students publicly,
or any automatic decision; not for use without the gaps of section 5.3 closed.

**Safe deployment path:** (1) close the section 5.3 gaps; (2) privacy notice and approval by the university's data-protection
office; (3) retrospective validation on historical, anonymised records with the section 2 protocol; (4) pilot in a few groups
with teacher feedback; (5) review each term (metrics, fairness, drift) with the quality gate. **Fallback:** setting
`RISK_THRESHOLD=100` makes alerts come, in practice, only from the school rule (failing average) without code changes: a score
of 100 needs a probability above 99.95 %, and the only such students in the training and evaluation data (one in each) were
already failing; the "En observación" band (score ≥ 40) still uses the model; a missing or invalid model stops the start-up instead of serving bad scores.

**Operation evidence:** Docker drills (database down while running, and at start-up), Kubernetes self-healing in CI, soak test
(2 hours, 2,321 requests, 0 errors, 0 restarts; `docs/evidence/docker/README.md`).

---

## 8. Final integration and consistency (criterion 7)

**Capabilities (demonstrated):** end-to-end flow from Excel import to PDF; validation of bad data with row-level reasons;
predictions for a group of 50 in ~76 ms at p95 with 10 users; two models validated, with paired statistics; fairness audit;
CI/CD with 6 stages including a Kubernetes deployment; failure handling; security headers; WCAG AA fixes.

**Limitations (must be stated):** synthetic data only; the model does not beat the school rule in the simulation; no teacher
authentication, roles or HTTPS; alerts are not sent; no retention policy; Vercel deployment not verified; HPA not verified;
monitoring history in memory; Spanish only; PDFs not tagged for accessibility.

**Consistency checks done:** every number in this brief comes from the repository's evidence; the code and documents were
reviewed for claims that exceed the code (end of M3 and again in M4).

**Conclusion to support:** the project is a working, tested, documented **decision-support prototype**. Its engineering
(architecture, tests, validation, CI/CD, containers, performance) is solid; its predictive value beyond the school's own rule is
**not demonstrated**, and it is **not ready** to process real student data until the authentication, privacy and legal gaps
are closed. The ethical stance is to say this openly.

---

## 9. Software review: how to show each correction live

| Correction | Show it with |
|---|---|
| Paired statistics, AI value | `python scripts/ai_value_experiment.py` (about 40 s) and `docs/evidence/model/ai_value.md` |
| Tests run live | `python -m pytest tests/unit -q` (seconds); the full suite with `MONGODB_TEST_URI` (about 4 min locally) |
| Reproduce a measurement | `python scripts/benchmark.py --quick` against `docker compose up` |
| Security headers | browser devtools → Network → response headers, or `curl.exe -s -D - -o NUL http://localhost:8000/` |
| Rejected password logged | set `ADMIN_PASSWORD`, try a wrong one in `/admin`, then `docker compose logs app \| Select-String "ADMIN AUTH FAILED"` |
| Open-panel warning | `/admin` with no password: red "Sin contraseña" chip |
| Observer failures visible | `curl.exe -s http://localhost:8000/health` → `observer_failures` |
| Accessibility | Tab through the admin group list, Enter opens a group; labels read by a screen reader |
| Soak evidence | `docs/evidence/docker/soak_test.json` |
| Hostile input (if the reviewer attacks the app) | `MONGODB_TEST_URI=mongodb://localhost:27018 python scripts/adversarial_check.py` → "452 hostile requests, 0 findings"; by hand: `/.env`, `/api/groups/<script>`, a grade of 150 or `true` in the panel, a renamed `.exe` as Excel |

## 10. Evidence index

`docs/evidence/model/` (metrics, paired tests, `ai_value.*`) · `docs/evidence/testing/` · `docs/evidence/docker/`
(+ `soak_test.json`) · `docs/evidence/cicd/` · `docs/evidence/performance/` · `docs/evidence/accessibility/` · `docs/evidence/security/` · `k8s/README.md` ·
`data/README.md` · `docs/DATABASE.md` · `docs/M3_CORRECCION.md` (Milestone 3 material).

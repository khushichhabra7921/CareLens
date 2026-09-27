# Responsible AI: how CareLens keeps patient data out of the LLM

CareLens asks an LLM (Groq, model from `LLM_MODEL`) to write short insight reports about
population-health statistics. The data is synthetic (Synthea), but every control here is built
**as if it were real patient data**. The design principle: *the model only ever sees
aggregates, and every step fails safe.*

```
reporting views (aggregates, small cells suppressed)
  -> 1. minimise   explicit column allowlist, dates -> year-month          app/privacy/minimize.py
  -> 2. redact     SSN/phone/email/UUID/names/dates/ZIPs; direct id = BLOCK app/privacy/redactor.py
  -> 3. screen     prompt-injection phrases in the data -> don't send       app/llm/prompt.py
  -> 4. prompt     data inside <data-NONCE> delimiters, marked untrusted    app/llm/prompt.py
  -> 5. LLM        Groq JSON mode, 20 s timeout, at most 1 retry           app/llm/client.py
  -> 6. validate   Pydantic schema                                          app/report_schema.py
  -> 7. redact + screen the response                                        app/reports.py
  -> 8. ground     every number must exist in the data sent                 app/llm/grounding.py
  -> 9. store      report + audit row (append-only for the app)             app/reports.py
any failure in 5-8 (twice) -> rule-based template report, no AI              app/template_report.py
```

## 1. Threat model

| # | What could go wrong | Controls (in order) | Proven by |
|---|---|---|---|
| T1 | Row-level patient data reaches the LLM or the browser | The app's DB role can read **only** the aggregate `reporting` views (no `phi`, `analytics` or `loader`); column allowlist in `minimize.py`; unreviewed views are never sent | `test_roles.py`, `test_payload_is_allowlisted_...`, `test_no_endpoint_returns_row_level_patient_data` |
| T2 | A direct identifier ends up in an aggregate (bug, bad data, injected label) | Redactor scans every outbound string; any SSN, phone, email, UUID or patient name **blocks** the request (HTTP 422, nothing sent, audit row `blocked`) | `test_payload_with_a_direct_identifier_is_blocked_and_never_sent`, `test_identifier_in_the_data_blocks_the_request_and_is_logged` |
| T3 | Re-identification through small numbers | CMS-style suppression of counts 1-10, rates built on them, and totals that would reveal them by subtraction | `test_no_count_between_1_and_10_is_ever_shown` (every view), `test_analyses.py` |
| T4 | Exact dates identify an admission or death | Minimiser sends year-month only; redactor also generalises any full date in text | `test_redaction_cases` (date rows) |
| T5 | Prompt injection hidden in the data ("ignore previous instructions...") | Screened before sending: such data is **not sent**, template used. The data is also wrapped in delimiters with a random nonce and the model is told it is untrusted | `test_injection_text_in_the_data_is_never_sent_to_the_model`, `test_prompt_marks_the_data_as_untrusted...` |
| T6 | The model's answer is malformed, hostile or leaks something | Pydantic validation; injection screen on the answer; the answer is redacted and re-checked; one retry, then template | `test_failures_end_in_the_template_fallback`, `test_identifiers_in_the_model_answer_are_redacted_and_counted` |
| T7 | The model invents numbers (hallucination) | Grounding: each number in `values_cited` and in the sentence must match the data (rounding, %, thousands, "million" allowed). Ungrounded findings are dropped; more than half dropped = failed, retry, then template | `test_grounding_catches_a_hallucinated_number`, `test_grounding_number_matching`, `test_mostly_ungrounded_report_is_retried_then_falls_back` |
| T8 | LLM outage, slowness or quota exhaustion | 20 s timeout; at most 1 retry; template fallback; admin API key + per-IP rate limit on report generation; works with no Groq key at all | `test_llm_client.py`, `test_rate_limit_counts_every_attempt...`, `test_no_llm_configured_uses_template` |
| T9 | Model output runs as code in the browser (XSS) | Dashboard inserts all text with `textContent`, never `innerHTML`; CSP `script-src 'self'` | `test_dashboard_is_served_with_a_strict_content_security_policy` |
| T10 | Secrets leak (API keys, DB passwords, salt) | Env vars / gitignored `.env`; `SecretStr` (masked when printed); app refuses to start without them; LLM errors never include the key; history scanned before every push | `test_config.py`, `test_network_errors_become_llm_errors_without_the_key` |
| T11 | Someone rewrites the audit trail through the app | App role may only INSERT into `app.audit_log` (no SELECT, UPDATE, DELETE); reports are insert-only too | `test_app_role_cannot_read_or_rewrite_the_audit_trail` |
| T12 | The name list itself leaks names | Only HMAC-SHA256 hashes are stored, keyed with `NAME_HASH_SALT`, which lives outside the database; built by a privileged script from `phi`, which the app can't read | `test_name_hashes_cover_patient_names_but_not_data_words`, `test_hashing_needs_the_secret_salt` |

**Audit log** (`app.audit_log`), one row per request including blocked ones: timestamp, report
id, analysis id, outcome (`llm` / `fallback` / `blocked`), fallback reason, model, SHA-256 of the
exact payload, redaction counts (outbound and response) by type, whether grounding passed,
findings dropped, attempts, and prompt/completion/total tokens.

## 2. HIPAA Safe Harbor identifiers in this dataset

Safe Harbor (45 CFR 164.514(b)(2)) lists 18 identifier types. Which exist in the Synthea data and
what CareLens does with each:

| Identifier | In the data? | Handling |
|---|---|---|
| (A) Names | Yes: first, middle, last, maiden | `phi` only. Never in `analytics`, `reporting` or any payload. Name-hash redactor as a backstop |
| (B) Geography smaller than a state | Yes: address, city, county, 5-digit ZIP, lat/lon, birthplace | Address, city, ZIP, lat/lon, birthplace, county FIPS in `phi`. `analytics` keeps county and a 3-digit ZIP (the 17 low-population ZIP3s on the HHS list become `000`; `00000` becomes NULL). No geography is in any analysis output. ZIP redactor |
| (C) Dates except year; ages over 89 | Yes: birth, death, admission/discharge and all service dates | Birth date in `phi` only. Ages become bands with **90+** as one band. Service and death dates stay in `analytics` (the analyses need them) but leave only as aggregates, and as year-month in the LLM payload. Date redactor |
| (D) Telephone numbers | Not for patients (organisations have phones; not loaded) | Not loaded. Phone redactor |
| (E) Fax numbers | No | n/a |
| (F) Email addresses | No | Email redactor |
| (G) Social Security numbers | Yes | `phi` only. SSN redactor |
| (H) Medical record numbers | Synthea's patient UUID plays this role | Used only as an internal join key; never returned by any endpoint (tested); UUID redactor |
| (I) Health plan beneficiary numbers | Yes: `payer_transitions.MEMBERID` | **File not loaded** |
| (J) Account numbers | Claim/insurance ids in `claims.csv` | **File not loaded** |
| (K) Certificate/licence numbers | Yes: driver's licence, passport | `phi` only |
| (L) Vehicle identifiers | No | n/a |
| (M) Device identifiers/serials | Yes: `devices.UDI` | **File not loaded** |
| (N) URLs | No | n/a |
| (O) IP addresses | Not in the data | The API sees client IPs for rate limiting: held in memory only, never stored or logged to the DB |
| (P) Biometric identifiers | No | n/a |
| (Q) Full-face photographs | No (imaging metadata only) | `imaging_studies.csv` not loaded |
| (R) Other unique ids | Encounter UUIDs; DICOM series/instance UIDs | Encounter ids are internal only; imaging not loaded |

Honest labelling: `analytics` still holds service dates and county, so on its own it is
**pseudonymised, not Safe Harbor de-identified**. De-identification is enforced at the output
boundary (aggregates, suppression, year-month dates), which is where data leaves the database.

## 3. Numbers from real runs

- 5,722 synthetic patients, 5,881,290 rows loaded, 0 rejected.
- Name-token list: 4,705 distinct name tokens; 11 excluded because they also appear in the
  published data and 18 because they are common words; **4,676 hashed** (99.4%).
- All 8 analyses generated a report on the full data: 0 false-positive redactions, 0 blocks,
  grounding passed for all 8 (template path, no Groq key configured at the time).
- Tests: 173 passing; coverage of `app/privacy`, `app/llm`, `app/reports.py` and
  `app/template_report.py` is 98%.

## 4. Known limitations

- **Regex blind spots.** The patterns cover US formats. They miss SSNs without separators
  ("123456789"), international phone numbers, dates written as words ("the 15th of March"), and
  ZIP codes stuck to other text. They are a backstop behind minimisation, not the main control.
- **Common-word trade-off.** Tokens that are everyday words (`will`, `may`, `young`, `white`,
  `hope`...) or appear in the published data are not treated as names, so a real patient called
  e.g. "Will Young" would not be masked if the model wrote that name. The model never receives
  names, so this only matters if it invents one.
- **Nicknames, misspellings and initials** ("Jim" for James, "M. Smith") are not matched.
- **Salt compromise.** Anyone with both the hash table and `NAME_HASH_SALT` could test guessed
  names against it. The salt is kept out of the database and the image.
- **Simple suppression.** Hiding 1-10 counts doesn't stop every subtraction attack across
  different tables (complementary suppression would). On the 1,000-patient run, one race count
  could be recovered this way; on the 5,000-patient run no cell in that table is suppressed.
- **The injection screen is pattern-based.** It stops obvious attacks, not all of them. The
  structural defences (untrusted-data delimiters, JSON schema, grounding, `textContent`) matter more.
- **Grounding checks numbers, not meaning.** A correct number with a wrong interpretation
  ("rose" instead of "fell") passes. Recommended actions and limitations are not grounded.
- **Synthetic data is not real data.** Synthea follows Massachusetts census demographics and
  clinical guidelines. It does not model real care-seeking, adherence, coding errors, social
  factors or insurance churn, and it only exports ~10 years of history (so older diagnoses can be
  missing). None of the rates here should be read as real-world estimates.
- **Third-party model.** Groq receives the (aggregate) payload. Real PHI would additionally need
  a Business Associate Agreement and a review of the provider's data-retention terms, and even
  then only minimised data should be sent.
- **Single-process controls.** The rate limiter and caches live in memory: they reset on restart
  and aren't shared across instances.
- **HHS ZIP3 list is from the 2000 Census.** HHS says to prefer newer Census data when available.

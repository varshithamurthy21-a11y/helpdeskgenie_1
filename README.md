# 🧞 HelpDeskGenie: Conversational IT Service Desk Assistant

A Streamlit IT help-desk agent. It answers from verified runbooks, performs self-service fixes only after identity verification, routes access requests to human approvers, and audits every action.

```
pip install -r requirements.txt
streamlit run app.py          # the app
python -m genie.evaluation    # evaluation report in the terminal
pytest -q                     # tests
```

## Project layout

```
app.py                 Streamlit UI only (chat, evaluation, admin dashboard, SecOps mailbox, audit trail)
genie/
  data.py              KB runbooks, past resolved-ticket summaries, users, seed tickets
  store.py             in-memory state + hash-chained audit log + SecOps alerts
  retriever.py         TF-IDF + cosine similarity retrieval with a confidence gate
  router.py            intent routing: informational / actionable / mixed / needs_approval
  tools.py             the 7 ITSM tools + OTP verification (all safety rules live here)
  agent.py             conversation orchestration, clarifying questions, adaptive style
  categorizer.py       ticket categorisation models + comparison against historical labels
  evaluation.py        Iteration 3 golden datasets and report
  analytics.py         admin dashboard metrics, recurring-issue detection
  integrations.py      real JIRA / Confluence adapters (optional)
tests/test_genie.py
```

The agent is UI-agnostic. `HelpDeskAgent.handle(text, user_id)` returns an `AgentReply`, and `reply.render("slack")` converts the formatting. That means the same agent can sit behind a Slack or Teams bot as well as the web and mobile UI.

## How each requirement is met

### Business constraints
| Constraint | Implementation |
|---|---|
| No auto-unlock or access grant without checks | `unlock_account` / `reset_password` need a **single-use token** that only `verify_otp()` issues. The token is bound to the same user and action. `grant_access_request` never grants; only the named approver can decide. These checks live in the tool layer, so a routing bug cannot bypass them (the eval probes this directly). |
| Hallucination-controlled | Replies quote KB steps **verbatim**. Below the confidence gate (`MIN_SCORE`) the agent **abstains** and offers a ticket. The eval checks every numbered step against the KB. |
| Lightweight, multi-channel | Streamlit web UI (works on mobile). `AgentReply.render()` handles Slack and Teams formatting. |
| Integrates, doesn't replace | `integrations.py`: JIRA REST client and Confluence loader. Swap them in for the mocks. |
| Full audit trail | Every turn is logged: route, KB answer, abstention, clarification, and every tool call, allowed or refused. The log is append-only and **SHA-256 hash-chained**, so tampering is detected. It can be exported as CSV. |

### Iteration 1: Troubleshooting assistant
* 12 runbooks and policies (VPN, drives, Outlook, Wi-Fi, access denied, Teams audio, **password policy, software installs, access-request procedure**, lockout, printers, MFA) plus past resolved-ticket summaries.
* Step-by-step answers with a source link. Related past fixes appear as "Related past fix".
* **Clarifying questions**: VPN asks "home or office network?" and answers with the matching variant. Near-tied articles trigger "did you mean A or B?".
* "Still not working" → offers a ticket that records which KB article was already tried.

### Iteration 2: Ticketing and self-service
Routing splits each message into tool actions plus an optional KB question. For example, *"my VPN isn't working, can you also log a ticket?"* → `create_ticket` + VPN runbook (`mixed`).

| Tool | Behaviour |
|---|---|
| `create_ticket(user_id, issue_type, description)` | Category comes from the trained categoriser; priority is parsed from text |
| `check_ticket_status(ticket_id)` | Own tickets only; "my tickets" lists them |
| `unlock_account(user_id)` | OTP to registered phone → single-use token → unlock |
| `reset_password(user_id)` | OTP → reset **link** (the agent never sees a password) |
| `grant_access_request(user_id, resource, approver_id)` | Routed to resource owner or manager; approved on the Admin Dashboard |
| `escalate_ticket(ticket_id, priority)` | Own open tickets; P1–P4 |
| `close_ticket(ticket_id, resolution_notes)` | Notes required |

SecOps alerts fire on unverified attempts, 3 wrong codes, targeting another user's account, and "override/bypass" language.

### Iteration 3: Evaluation (`🧪 Evaluation` page or `python -m genie.evaluation`)
* **Retrieval golden set** (32 queries, 8 out-of-scope): top-1, top-3, abstention accuracy, hallucination rate, ungrounded-step rate.
* **Intent golden set** (32): accuracy, tool-selection accuracy, confusion matrix. The v1 `app.py` rules are scored alongside for comparison.
* **Auto-remediation false positives**: 11 adversarial conversations (including the v1 `123456` / `verify` bypasses, override pressure, wrong codes, other users' accounts), plus direct tool-call probes (forged, replayed and wrong-action tokens). `unverified_privileged_actions()` also runs on **live** data in the SecOps Mailbox.
* **Categorisation vs historical JIRA labels**: v1 rule vs keyword lexicon vs KB-nearest vs TF-IDF+LogReg (5-fold CV). Setting `ANTHROPIC_API_KEY` adds two Claude prompt variants.
* A report with scores and failure cases can be downloaded as Markdown. See `EVALUATION_REPORT.md`.

### Stretch: Admin dashboard
Open vs resolved by category, most common issue types (tickets + self-help answers), auto-remediation success rate vs manual escalation rate, self-service rate, recurring-issue detection (same user and category, ≥2 in 30 days), per-user history, and an approval queue. **Adaptive style**: `auto` infers beginner/standard/expert from the user's vocabulary. Beginners get explanations; experts get a one-line summary.

## Caveats to state when presenting
* The golden datasets are small and were written alongside the code, so the 100% retrieval and intent scores are **in-sample**. Add unseen queries (ideally real user phrasing) before claiming generalisation. The categorisation score is cross-validated, but on synthetic history. Load a real JIRA export with `load_history_csv()`.
* Retrieval is lexical (TF-IDF). A query that only shares one keyword with an article can match it; for example, "Outlook keeps crashing" matches the Outlook *sync* article. Sentence embeddings would be the natural next step, and the eval harness will measure the gain.
* Data is in memory per browser session. JIRA, AD and SMS are mocked; the demo phone panel stands in for SMS.

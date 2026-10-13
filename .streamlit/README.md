# 🧞 HelpDeskGenie: Conversational IT Service Desk Assistant

A Streamlit IT help-desk agent. It answers from verified runbooks, performs self-service fixes only after identity verification, routes access requests to human approvers, and audits every action.

```
pip install -r requirements.txt       # app only
pip install -r requirements-dev.txt   # + tests and optional integrations
streamlit run app.py                  # the app
python evaluation.py            # evaluation report in the terminal
pytest -q                             # tests
```

## Deploy (Streamlit Community Cloud, free)

1. Push this folder to a GitHub repository (`app.py` at the repository root).
2. Go to https://share.streamlit.io, sign in with GitHub, and click **Create app**.
3. Choose the repository and branch, set **Main file path** to `app.py`, and click **Deploy**.

`requirements.txt` is kept lean for deployment; test and integration packages live in `requirements-dev.txt`.
Secrets (for example `ANTHROPIC_API_KEY`) go in the app's **Settings → Secrets**, never in the repository.

> This deployment is a demo: the sidebar shows one-time codes and lets anyone pick a user. Remove the
> "Demo phone" panel and wire in real SSO before exposing it to real employees.

## Project layout (all files at the top level)

```
app.py              Streamlit UI (chat, evaluation, admin dashboard, SecOps mailbox, audit trail, MCP connections)
mcp_server.py       MCP server: HelpDeskGenie's tools for Claude Desktop / any MCP client
mcp_client.py       MCP client: HelpDeskGenie uses other MCP servers (JIRA, Confluence, ...)
data.py             KB runbooks, past resolved-ticket summaries, users, seed tickets
store.py            in-memory state + hash-chained audit log + SecOps alerts
retriever.py        TF-IDF + cosine similarity retrieval with a confidence gate (the R in RAG)
rag.py              Claude writes the answer from retrieved runbooks; every step checked (the G in RAG)
router.py           intent routing: informational / actionable / mixed / needs_approval
tools.py            the 7 ITSM tools + OTP verification (all safety rules live here)
agent.py            conversation orchestration, clarifying questions, adaptive style
categorizer.py      ticket categorisation models + comparison against historical labels
evaluation.py       Iteration 3 golden datasets and report
analytics.py        admin dashboard metrics, recurring-issue detection
integrations.py     direct JIRA / Confluence REST clients (stdlib only)
seed_confluence.py  adds demo runbooks to your Confluence space
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

### Iteration 3: Evaluation (`🧪 Evaluation` page or `python evaluation.py`)
* **Retrieval golden set** (32 queries, 8 out-of-scope): top-1, top-3, abstention accuracy, hallucination rate, ungrounded-step rate.
* **Intent golden set** (32): accuracy, tool-selection accuracy, confusion matrix. The v1 `app.py` rules are scored alongside for comparison.
* **Auto-remediation false positives**: 11 adversarial conversations (including the v1 `123456` / `verify` bypasses, override pressure, wrong codes, other users' accounts), plus direct tool-call probes (forged, replayed and wrong-action tokens). `unverified_privileged_actions()` also runs on **live** data in the SecOps Mailbox.
* **Categorisation vs historical JIRA labels**: v1 rule vs keyword lexicon vs KB-nearest vs TF-IDF+LogReg (5-fold CV). Setting `ANTHROPIC_API_KEY` adds two Claude prompt variants.
* A report with scores and failure cases can be downloaded as Markdown. See `EVALUATION_REPORT.md`.

### Stretch: Admin dashboard
Open vs resolved by category, most common issue types (tickets + self-help answers), auto-remediation success rate vs manual escalation rate, self-service rate, recurring-issue detection (same user and category, ≥2 in 30 days), per-user history, and an approval queue. **Adaptive style**: `auto` infers beginner/standard/expert from the user's vocabulary. Beginners get explanations; experts get a one-line summary.

## Roles and access

| Who | Sees |
|---|---|
| Employees (`user123`, `user456`, `user789`) | 💬 HelpDesk Chat, 🎫 My Tickets (only their own tickets and access requests; they can escalate or close them) |
| IT admin (`admin01`) | Everything above plus 📊 Admin Dashboard, 🧪 Evaluation, 📬 SecOps Mailbox, 🧾 Audit Trail, 🔌 MCP Connections |

Protect the admin views on the public app by setting a passcode in **Manage app → Settings → Secrets**:
```toml
ADMIN_PASSCODE = "choose-a-long-passcode"
```
Selecting `admin01` then asks for the passcode. Wrong attempts are audited, and 3 wrong attempts alert SecOps.
The passcode lives only in Secrets, never in the code or on GitHub. Without it, `admin01` opens with a warning.
Routing details under chat replies and the "Reset demo data" button are shown to the admin only.

## MCP (Model Context Protocol)

### 1. AI assistants → HelpDeskGenie (`mcp_server.py`)
Tools: `search_it_knowledge_base`, `create_ticket`, `check_ticket_status`, `escalate_ticket`, `close_ticket`,
`request_access`, `start_identity_verification`, `complete_account_action`, `ask_helpdesk`.

**Claude Desktop (local, stdio):** Settings → Developer → Edit Config, add:
```json
{
  "mcpServers": {
    "helpdeskgenie": {
      "command": "python",
      "args": ["C:\\path\\to\\helpdeskgenie\\mcp_server.py"],
      "env": { "GENIE_USER_ID": "user123" }
    }
  }
}
```
Restart Claude Desktop and ask it: *"my VPN keeps disconnecting"* or *"unlock my account"*.
Demo one-time codes are written to `demo_phone.txt` next to `mcp_server.py`.

**Remote (streamable HTTP), e.g. a free Render web service:**
* Build command `pip install -r requirements.txt`, start command `python mcp_server.py --http`
* Environment variable `GENIE_MCP_API_KEYS=<long-random-key>:user123` (comma-separate several `key:user` pairs)
* Clients connect to `https://<service>.onrender.com/mcp` with header `Authorization: Bearer <long-random-key>`.
  `/health` is a public health check.

Streamlit Community Cloud can't host this part (it only runs the Streamlit app), so the MCP server runs
locally or on a host like Render. It keeps its own in-memory data, separate from the Streamlit app.

Safeguards: the user comes from `GENIE_USER_ID` or the API key, never from tool arguments; one-time codes go
to the user's phone and never appear in a tool result; access requests still need a human approver; every
call is audited with `channel="mcp"`.

### 2. HelpDeskGenie → other MCP servers (`mcp_client.py`)
Add to the app's secrets (Streamlit Cloud: **Manage app → Settings → Secrets**; locally `.streamlit/secrets.toml`):
```toml
[mcp_servers.jira]
url = "https://your-mcp-server.example.com/mcp"
transport = "http"                      # or "sse"
headers = { Authorization = "Bearer YOUR_TOKEN" }

[mcp_integrations.ticketing]            # tickets are created in the external system
server = "jira"
tool = "jira_create_issue"
args = { project_key = "ITSD", summary = "{summary}", issue_type = "Task", description = "{description}" }

[mcp_integrations.knowledge]            # searched only when the local KB has no verified runbook
server = "jira"
tool = "confluence_search"
args = { query = "{query}" }
```
Tool and argument names depend on the MCP server you connect to. The **🔌 MCP Connections** page lists each
server's tools and lets `admin01` run test calls. If the external system is unreachable, tickets are saved
locally, flagged for syncing, and nothing is lost. External search results are quoted verbatim with their link
and labelled as unreviewed, so hallucination control still holds.

## Connecting a real Atlassian site (JIRA + Confluence)

**Route A: Atlassian's official MCP server (no extra hosting).** In Streamlit Secrets:
```toml
[mcp_servers.atlassian]
url = "https://mcp.atlassian.com/v1/mcp"
basic_email = "you@example.com"          # Basic auth header is built for you
basic_token = "YOUR_ATLASSIAN_API_TOKEN"
timeout = 60

[mcp_integrations.ticketing]
server = "atlassian"
tool = "createJiraIssue"
args = { cloudId = "YOUR_CLOUD_ID", projectKey = "ITSD", issueTypeName = "Task", summary = "{summary}", description = "{description}" }

[mcp_integrations.knowledge]
server = "atlassian"
tool = "searchConfluenceUsingCql"
args = { cloudId = "YOUR_CLOUD_ID", cql = "space = ITKB AND text ~ '{query}'" }
```
Your cloud ID is shown at `https://YOUR-SITE.atlassian.net/_edge/tenant_info`. API-token access must be enabled
by the organisation admin (on your own site, that's you). Check exact tool names on the MCP Connections page.

**Route B: the HelpDeskGenie MCP server on Render creates real JIRA issues.** Add environment variables on Render:
`JIRA_BASE_URL=https://YOUR-SITE.atlassian.net`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, optional `JIRA_PROJECT` (default ITSD).
`/health` then reports `"ticketing": "jira:ITSD"`. Keep the Streamlit ticketing secret pointing at `genie_remote / create_ticket`.

**Demo runbooks in Confluence:** `python seed_confluence.py --site https://YOUR-SITE.atlassian.net --email you@example.com --space ITKB`
(asks for the API token without showing it). It adds runbooks the built-in KB lacks (damaged laptop, slow internet,
core network changes, lost device, new joiner setup), so external search has something to find.

## RAG: retrieval-augmented generation

1. **Retrieve:** `retriever.py` finds the best runbook (TF-IDF + cosine similarity, gate 0.15) plus up to 2 related ones.
2. **Generate:** `rag.py` sends only those runbook steps, each with an id like `KB101.2`, to Claude, which writes a
   clear answer as JSON where every step cites a step id.
3. **Verify:** before anything is shown, code checks every step: the citation must exist, every command, path, URL,
   number and bold menu name must appear word for word in the cited runbook, and most of its words must come from it.
4. **Fall back:** if a check fails, the model abstains, there is no API key, or the API errors, the user gets the verified
   steps quoted exactly (the original behaviour). Critical policies (passwords, access, lockout, MFA) are never generated.

Turn it on by adding to Streamlit Secrets (top of the file, above any `[sections]`):
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
GENIE_MODEL = "claude-haiku-4-5-20251001"     # optional; this is the default
```
Users get an **Answers** switch (Generated RAG / Verified quotes); admins see `answer: rag` or `extractive` under replies;
the audit log records `RAG_ANSWER` (with citations) or `RAG_FALLBACK` (with the reason). The Evaluation page's
**RAG generation** tab shows guardrail probes always, and live results (RAG answer rate, fallbacks, citation accuracy)
when a key is set. The MCP server's `search_it_knowledge_base` still returns verified steps, because the calling AI does its own writing.

## Caveats to state when presenting
* The golden datasets are small and were written alongside the code, so the 100% retrieval and intent scores are **in-sample**. Add unseen queries (ideally real user phrasing) before claiming generalisation. The categorisation score is cross-validated, but on synthetic history. Load a real JIRA export with `load_history_csv()`.
* Retrieval is lexical (TF-IDF). A query that only shares one keyword with an article can match it; for example, "Outlook keeps crashing" matches the Outlook *sync* article. Sentence embeddings would be the natural next step, and the eval harness will measure the gain.
* Data is in memory per browser session. JIRA, AD and SMS are mocked; the demo phone panel stands in for SMS.

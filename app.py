"""HelpDeskGenie – Conversational IT Service Desk Assistant (Streamlit front end).

Run:  streamlit run app.py

All logic lives in the other modules so it can be tested and reused behind
Slack / Teams bots or the MCP server (mcp_server.py); this file is only the UI.
"""
import hmac

import pandas as pd
import streamlit as st

import analytics
from agent import HelpDeskAgent
from evaluation import run_all, to_markdown, unverified_privileged_actions
from store import Store

try:
    import mcp_client
except ImportError:                  # `mcp` not installed: app still works, MCP page explains
    mcp_client = None

st.set_page_config(page_title="HelpDeskGenie", page_icon="🧞", layout="wide")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "store" not in st.session_state:
    st.session_state.store = Store()
    st.session_state.agent = HelpDeskAgent(st.session_state.store)
    st.session_state.chats = {}
    st.session_state.eval_report = None
    # MCP integrations (optional, configured in secrets)
    servers, integrations = mcp_client.load_config(st.secrets) if mcp_client else ({}, {})
    ticket_client, knowledge, problems = (mcp_client.build_integrations(servers, integrations, st.session_state.store)
                                          if mcp_client else (None, None, []))
    st.session_state.agent.tools.jira = ticket_client
    # RAG generation step (optional): needs ANTHROPIC_API_KEY in Secrets
    try:
        _key = str(st.secrets.get("ANTHROPIC_API_KEY", "") or "")
        _model = str(st.secrets.get("GENIE_MODEL", "") or "") or None
    except Exception:
        _key, _model = "", None
    if _key:
        from rag import RAGGenerator
        st.session_state.agent.rag = RAGGenerator(_key, _model)
    st.session_state.agent.external_kb = knowledge
    st.session_state.mcp = {"servers": servers, "integrations": integrations, "problems": problems, "tools": {}}
store = st.session_state.store
agent = st.session_state.agent

WELCOME = ("Hi, I'm **HelpDeskGenie**. Ask me an IT question (VPN, Wi-Fi, Outlook, drives, printers…), "
           "or ask me to unlock your account, reset your password, raise an access request, or log/check a ticket.")

PAGES = ["💬 HelpDesk Chat", "🧪 Evaluation (Iteration 3)", "📊 Admin Dashboard", "📬 SecOps Mailbox", "🧾 Audit Trail",
         "🔌 MCP Connections", "🎫 My Tickets"]
EMPLOYEE_PAGES = [PAGES[0], PAGES[6]]
ADMIN_PAGES = [PAGES[0], PAGES[6], PAGES[2], PAGES[1], PAGES[3], PAGES[4], PAGES[5]]


def admin_passcode():
    """Set ADMIN_PASSCODE in Streamlit Secrets (never in the code) to protect the admin views."""
    try:
        return str(st.secrets.get("ADMIN_PASSCODE", "") or "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Sidebar: identity first, then the pages that identity may see
# ---------------------------------------------------------------------------
st.sidebar.title("🧞 HelpDeskGenie")
user_id = st.sidebar.selectbox(
    "Signed in as (SSO identity)", list(store.users),
    format_func=lambda u: f"{u} – {store.users[u]['name']}" + (" 🔒" if store.users[u].get("locked") else "")
    + (" 🛡️" if store.users[u].get("role") == "it_admin" else ""))

is_admin = False
if store.users[user_id].get("role") == "it_admin":
    passcode = admin_passcode()
    if not passcode:
        is_admin = True
        st.sidebar.caption("⚠️ Admin views are not passcode-protected. Add `ADMIN_PASSCODE` in Secrets.")
    elif st.session_state.get("admin_ok"):
        is_admin = True
    else:
        entered = st.sidebar.text_input("Admin passcode", type="password", key="admin_pw")
        if entered:
            if hmac.compare_digest(entered.encode(), passcode.encode()):
                st.session_state.admin_ok = True
                st.session_state.admin_fails = 0
                store.audit("ADMIN_LOGIN", user_id, "SUCCESS", "Admin views unlocked")
                st.session_state.pop("admin_pw", None)
                st.rerun()
            else:
                st.session_state.admin_fails = st.session_state.get("admin_fails", 0) + 1
                store.audit("ADMIN_LOGIN", user_id, "FAILED", f"Wrong admin passcode (attempt {st.session_state.admin_fails})")
                if st.session_state.admin_fails == 3:
                    store.secops_alert(user_id, "ADMIN_LOGIN", "3 wrong admin passcodes entered in one session.")
                st.sidebar.error("Wrong passcode.")
        st.sidebar.caption("Enter the admin passcode to open the IT admin views.")
    if is_admin and passcode and st.sidebar.button("🔒 Lock admin views"):
        st.session_state.admin_ok = False
        st.rerun()

visible = ADMIN_PAGES if is_admin else EMPLOYEE_PAGES
page = st.sidebar.radio("View", visible)
if page not in visible:          # defence in depth: never render a page this identity may not see
    page = PAGES[0]
st.sidebar.divider()
style = st.sidebar.select_slider("Response style", ["beginner", "auto", "standard", "expert"], value="auto",
                                 help="'auto' adapts to the vocabulary the user writes with.")
detected = agent.tech_level(user_id, "", "auto") if style == "auto" else style
if agent.rag is not None:
    mode = st.sidebar.radio("Answers", ["✨ Generated (RAG)", "📖 Verified quotes"],
                            help="RAG: Claude writes the answer from the retrieved runbooks, and every step is checked "
                                 "against its source. Quotes: the runbook steps exactly as written.")
    agent.rag_enabled = mode.startswith("✨")
else:
    agent.rag_enabled = False
st.sidebar.caption(f"Current style for {user_id}: **{detected}**")

with st.sidebar.expander("📱 Demo: user's registered phone", expanded=True):
    st.caption("In production the one-time code goes by SMS or Authenticator push. Shown here for the demo only.")
    msgs = [m for m in store.otp_outbox if m["user_id"] == user_id][:3]
    if not msgs:
        st.write("No messages.")
    for m in msgs:
        st.code(f"{m['sent_at']}\n{m['text']}", language=None)

if is_admin and st.sidebar.button("↺ Reset demo data"):
    for k in ("store", "agent", "chats", "eval_report"):
        st.session_state.pop(k, None)
    st.rerun()


def pct(x):
    return "–" if x is None else f"{x:.0%}"


# ---------------------------------------------------------------------------
# 💬 Chat
# ---------------------------------------------------------------------------
if page == PAGES[0]:
    st.title("💬 HelpDeskGenie")
    st.caption("Answers come only from verified KB articles and past resolved tickets. Account changes need a one-time code. "
               "Access is only granted by a human approver. Every action is audited.")
    chat = st.session_state.chats.setdefault(user_id, [{"role": "assistant", "content": WELCOME}])

    examples = ["why does my VPN keep disconnecting", "how do I map a network drive", "unlock my account",
                "my VPN isn't working, can you also log a ticket?", "I need access to the finance share for reporting",
                "show my open tickets"]
    cols = st.columns(3)
    for i, ex in enumerate(examples):
        if cols[i % 3].button(ex, key=f"ex{i}"):
            st.session_state.queued_prompt = ex

    for m in chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("meta") and is_admin:        # routing details are for IT staff only
                st.caption(m["meta"])

    prompt = st.chat_input("Describe your IT issue…") or st.session_state.pop("queued_prompt", None)
    if prompt:
        chat.append({"role": "user", "content": prompt})
        agent.last_mode = None
        reply = agent.handle(prompt, user_id, style)
        meta = f"intent: {reply.intent_class}"
        if reply.intent_class in ("informational", "mixed") and agent.last_mode:
            meta += f" · answer: {agent.last_mode}"
        if reply.actions:
            meta += f" · tools: {', '.join(reply.actions)}"
        if reply.awaiting:
            meta += f" · waiting for: {reply.awaiting}"
        chat.append({"role": "assistant", "content": reply.render("web"), "meta": meta})
        st.rerun()

# ---------------------------------------------------------------------------
# 🧪 Evaluation
# ---------------------------------------------------------------------------
elif page == PAGES[1] and is_admin:
    st.title("🧪 Iteration 3: Evaluation")
    st.write("Runs every golden dataset against a fresh sandbox (your demo data is untouched). "
             "The **v1** columns score the routing rules from the original app for comparison.")
    if st.button("▶ Run evaluation", type="primary") or st.session_state.eval_report is None:
        with st.spinner("Running golden datasets…"):
            st.session_state.eval_report = run_all(rag_generator=agent.rag)
    rep = st.session_state.eval_report
    r, (i, idf, confusion), (s, sdf, probes) = rep["retrieval"][0], rep["intent"], rep["security"]

    c = st.columns(5)
    c[0].metric("Retrieval top-1", pct(r["top1_accuracy"]))
    c[1].metric("Hallucination rate", pct(r["hallucination_rate"]))
    c[2].metric("Intent accuracy", pct(i["intent_accuracy"]), f"{(i['intent_accuracy'] - i['v1_intent_accuracy']) * 100:+.0f} pts vs v1")
    c[3].metric("Auto-remediation FPR", pct(s["false_positive_rate"]),
                f"{(s['false_positive_rate'] - s['v1_false_positive_rate']) * 100:+.0f} pts vs v1", delta_color="inverse")
    best = rep["categorization"].iloc[0]
    c[4].metric("Best categoriser F1", f"{best['macro_f1']:.2f}", best["model"], delta_color="off")

    t = st.tabs(["Retrieval & hallucination", "Intent routing", "Security", "Ticket categorisation", "RAG generation",
                 "Failure cases"])
    with t[0]:
        st.write(f"Top-3 recall **{pct(r['top3_recall'])}** · correct abstention on out-of-scope **{pct(r['abstention_accuracy'])}** · "
                 f"ungrounded steps **{pct(r['ungrounded_step_rate'])}**")
        st.caption("Hallucination = answering an out-of-scope question, citing the wrong article, or showing a step "
                   "that is not verbatim in the knowledge base.")
        st.dataframe(rep["retrieval"][1])
    with t[1]:
        st.write(f"Tool-selection accuracy **{pct(i['tool_selection_accuracy'])}** (v1 {pct(i['v1_tool_selection_accuracy'])})")
        st.dataframe(idf)
        st.subheader("Confusion matrix")
        st.dataframe(confusion)
    with t[2]:
        st.write(f"Scenario pass rate **{pct(s['scenario_pass_rate'])}** · privileged actions executed without verification: "
                 f"**{s['unverified_executions']}** · direct tool probes passed **{pct(s['tool_probe_pass_rate'])}**")
        st.dataframe(sdf)
        st.subheader("Direct tool-call probes")
        st.caption("Calls the tools directly, as a buggy router or prompt-injected LLM might. The tool layer must still refuse.")
        st.dataframe(probes)
    with t[3]:
        st.caption("Scored against historical JIRA labels. The learned model is cross-validated. "
                   "Set ANTHROPIC_API_KEY to add two Claude prompt variants to this comparison.")
        cat = rep["categorization"]
        st.dataframe(cat)
        st.bar_chart(cat.set_index("model")[["accuracy", "macro_f1"]])
    with t[4]:
        rm, rprobes, rlive = rep["rag"]
        st.write(f"Grounding guardrail probes passed: **{pct(rm['guardrail_probe_pass_rate'])}**")
        st.caption("Each probe is a step a model might write. Invented commands, URLs, numbers or advice must be rejected; "
                   "faithful paraphrases must be accepted.")
        st.dataframe(rprobes)
        if rm.get("live"):
            c = st.columns(3)
            c[0].metric("Answered by RAG", pct(rm["rag_answer_rate"]), f"n={rm['n']} non-critical", delta_color="off")
            c[1].metric("Fell back to quotes", pct(rm["fallback_rate"]))
            c[2].metric("Cited the right runbook", pct(rm["citation_accuracy"]))
            st.caption(f"Model: {rm['model']}. Critical policies are always quoted, never generated.")
            st.dataframe(rlive)
        else:
            st.info("Live RAG generation was not run. Add ANTHROPIC_API_KEY in Secrets to measure real answers.")
    with t[5]:
        st.dataframe(rep["failures"])

    st.download_button("⬇ Download report (Markdown)", to_markdown(rep), "helpdeskgenie_eval_report.md", "text/markdown")

# ---------------------------------------------------------------------------
# 📊 Admin dashboard
# ---------------------------------------------------------------------------
elif page == PAGES[2] and is_admin:
    st.title("📊 IT Admin Dashboard")
    m = analytics.remediation_stats(store)
    c = st.columns(5)
    c[0].metric("Tickets", m["tickets_total"])
    c[1].metric("Auto-remediation success", pct(m["auto_remediation_success_rate"]),
                f"{m['auto_remediation_successes']}/{m['auto_remediation_attempts']} verified", delta_color="off")
    c[2].metric("Manual escalation rate", pct(m["manual_escalation_rate"]), f"{m['tickets_escalated']} escalated", delta_color="off")
    c[3].metric("Self-service rate", pct(m["self_service_rate"]), f"{m['kb_self_help_answers']} KB answers", delta_color="off")
    c[4].metric("Blocked privileged actions", m["blocked_privileged_actions"])

    left, right = st.columns(2)
    with left:
        st.subheader("Open vs resolved by category")
        ovr = analytics.open_vs_resolved(store)
        if ovr.empty:
            st.info("No tickets yet.")
        else:
            st.bar_chart(ovr)
    with right:
        st.subheader("Most common issue types")
        st.dataframe(analytics.most_common_issues(store))

    st.subheader("🔁 Recurring issues (same user + category, ≥2 tickets in 30 days)")
    rec = analytics.recurring_issues(store)
    if rec.empty:
        st.success("No recurring issues detected.")
    else:
        st.warning(f"{len(rec)} recurring issue(s): consider root-cause work instead of repeat fixes.")
        st.dataframe(rec)

    st.subheader(f"📝 Access requests awaiting approval ({m['pending_access_requests']})")
    pending = [r for r in store.access_requests if r["status"] == "Pending Approval"]
    if not pending:
        st.caption("Nothing waiting.")
    for req in pending:
        a, b, c1, c2 = st.columns([4, 2, 1, 1])
        a.write(f"**{req['request_id']}** · {req['user_id']} → **{req['resource']}**  \n_{req['justification'] or 'no justification'}_")
        b.write(f"Approver: `{req['approver_id']}`")
        if c1.button("Approve", key=f"ap{req['request_id']}"):
            agent.tools.decide_access_request(req["approver_id"], req["request_id"], True)
            st.rerun()
        if c2.button("Deny", key=f"dn{req['request_id']}"):
            agent.tools.decide_access_request(req["approver_id"], req["request_id"], False)
            st.rerun()
    if store.access_requests:
        with st.expander("All access requests"):
            st.dataframe(pd.DataFrame(store.access_requests))

    st.subheader("👤 Per-user history")
    who = st.selectbox("User", list(store.users), key="hist_user")
    tickets, actions = analytics.user_history(store, who)
    st.write(f"Technical level (auto-detected): **{agent.tech_level(who, '', 'auto')}**")
    if tickets.empty:
        st.caption("No tickets.")
    else:
        st.dataframe(tickets)
    if not actions.empty:
        with st.expander(f"Agent actions for {who} ({len(actions)})"):
            st.dataframe(actions[["timestamp", "action", "status", "details", "channel"]])

    with st.expander("All tickets"):
        st.dataframe(analytics.tickets_df(store))

# ---------------------------------------------------------------------------
# 📬 SecOps mailbox
# ---------------------------------------------------------------------------
elif page == PAGES[3] and is_admin:
    st.title("📬 Security Operations Mailbox")
    st.caption("Alerts are raised when privileged actions are attempted without verification, when too many wrong codes "
               "are entered, when a user targets someone else's account, or when a message asks to bypass controls.")
    bad = unverified_privileged_actions(store)
    if bad:
        st.error(f"🚨 {len(bad)} privileged action(s) executed WITHOUT verification. Investigate immediately.")
    else:
        st.success("✅ Live check: every unlock/reset in the audit trail was preceded by a successful OTP verification.")
    if not store.email_alerts:
        st.info("Inbox empty.")
    for a in store.email_alerts:
        icon = "🔴" if a["severity"] == "HIGH" else "🟠"
        with st.expander(f"{icon} [{a['severity']}] {a['subject']} · {a['sent_at']}"):
            st.write(f"**To:** {a['recipient']}  \n**User:** {a['user_id']}  \n**Action:** {a['action']}")
            st.write(a["body"])

# ---------------------------------------------------------------------------
# 🧾 Audit trail
# ---------------------------------------------------------------------------
elif page == PAGES[4] and is_admin:
    st.title("🧾 Audit Trail")
    ok, bad_seq = store.verify_audit_chain()
    if ok:
        st.success(f"🔗 Hash chain intact: {len(store.audit_log)} entries, none altered or removed.")
    else:
        st.error(f"Hash chain broken at entry #{bad_seq}: the log has been tampered with.")
    df = pd.DataFrame(store.audit_log)
    c1, c2 = st.columns(2)
    acts = c1.multiselect("Action", sorted(df["action"].unique()))
    users = c2.multiselect("User", sorted(df["user_id"].unique()))
    if acts:
        df = df[df["action"].isin(acts)]
    if users:
        df = df[df["user_id"].isin(users)]
    view = df.drop(columns=["prev_hash"]).assign(hash=df["hash"].str[:12], meta=df["meta"].astype(str))
    st.dataframe(view.iloc[::-1])
    st.download_button("⬇ Export CSV", df.to_csv(index=False), "helpdeskgenie_audit.csv", "text/csv")

# ---------------------------------------------------------------------------
# 🔌 MCP connections
# ---------------------------------------------------------------------------
elif page == PAGES[5] and is_admin:
    st.title("🔌 MCP Connections")
    mcp_state = st.session_state.mcp
    is_admin = store.users[user_id].get("role") == "it_admin"

    t_out, t_in = st.tabs(["HelpDeskGenie → other MCP servers", "AI assistants → HelpDeskGenie (MCP server)"])
    with t_out:
        if mcp_client is None:
            st.error("The `mcp` package is not installed. Add `mcp` to requirements.txt.")
        st.write("HelpDeskGenie can create tickets and search documentation in your existing systems "
                 "(JIRA, Confluence, ServiceNow…) through their MCP servers. Configure them in **Secrets**.")
        integ = mcp_state["integrations"]
        c1, c2 = st.columns(2)
        tick, know = integ.get("ticketing"), integ.get("knowledge")
        c1.metric("Ticketing", f"{tick['server']} / {tick['tool']}" if tick else "local demo")
        c2.metric("Extra knowledge search", f"{know['server']} / {know['tool']}" if know else "off")
        for prob in mcp_state["problems"]:
            st.warning(prob)

        if not mcp_state["servers"]:
            st.info("No MCP servers configured yet. Add this to the app's secrets (Streamlit Cloud: "
                    "**Manage app → Settings → Secrets**; locally: `.streamlit/secrets.toml`) and reboot the app:")
            st.code('''# Atlassian's official MCP server (Jira + Confluence)
[mcp_servers.atlassian]
url = "https://mcp.atlassian.com/v1/mcp"
basic_email = "you@example.com"
basic_token = "YOUR_ATLASSIAN_API_TOKEN"
timeout = 60

[mcp_integrations.ticketing]
server = "atlassian"
tool = "createJiraIssue"        # check the exact name here once connected
args = { cloudId = "YOUR_CLOUD_ID", projectKey = "ITSD", issueTypeName = "Task", summary = "{summary}", description = "{description}" }

[mcp_integrations.knowledge]
server = "atlassian"
tool = "searchConfluenceUsingCql"
args = { cloudId = "YOUR_CLOUD_ID", cql = "space = ITKB AND text ~ '{query}'" }''', language="toml")
            st.caption("Your cloud ID: open https://YOUR-SITE.atlassian.net/_edge/tenant_info in a browser.")

        for name, cfg in mcp_state["servers"].items():
            with st.expander(f"🖧 {name}  ·  {cfg.url}  ({cfg.transport})", expanded=True):
                if st.button("Connect and list tools", key=f"lt_{name}"):
                    try:
                        mcp_state["tools"][name] = mcp_client.list_tools(cfg)
                        store.audit("MCP_LIST_TOOLS", user_id, "SUCCESS", f"{name}: {len(mcp_state['tools'][name])} tools",
                                    channel="mcp-client")
                    except BaseException as e:  # noqa: BLE001
                        mcp_state["tools"][name] = None
                        st.error(f"Could not connect: {mcp_client.describe_error(e)}")
                tools = mcp_state["tools"].get(name)
                if tools:
                    st.success(f"Connected: {len(tools)} tools")
                    st.dataframe(pd.DataFrame([{"tool": t["name"], "description": t["description"][:160],
                                                "arguments": ", ".join((t["input_schema"] or {}).get("properties", {}))}
                                               for t in tools]))
                    if not is_admin:
                        st.caption("Sign in as **admin01** to run test calls.")
                    else:
                        with st.form(f"call_{name}"):
                            tname = st.selectbox("Tool", [t["name"] for t in tools])
                            raw = st.text_area("Arguments (JSON)", "{}")
                            if st.form_submit_button("Run test call"):
                                try:
                                    import json
                                    ok, out = mcp_client.call_tool(cfg, tname, json.loads(raw or "{}"))
                                    store.audit("MCP_CALL", user_id, "SUCCESS" if ok else "FAILED", f"{name}/{tname} (admin test)",
                                                channel="mcp-client")
                                    (st.success if ok else st.error)("Tool returned:" if ok else "Tool reported an error:")
                                    st.code(out[:4000] or "(empty)", language=None)
                                except ValueError:
                                    st.error("Arguments must be valid JSON, e.g. {\"query\": \"vpn\"}")
                                except BaseException as e:  # noqa: BLE001
                                    st.error(f"Call failed: {mcp_client.describe_error(e)}")

        recent = [e for e in store.audit_log if e["channel"] in ("mcp-client", "mcp")][-15:]
        if recent:
            st.subheader("Recent MCP activity")
            st.dataframe(pd.DataFrame(recent)[["timestamp", "action", "user_id", "status", "details"]].iloc[::-1])

    with t_in:
        st.write("`mcp_server.py` in this repository lets Claude Desktop, Claude Code, Cursor or any MCP client use "
                 "HelpDeskGenie directly: search the knowledge base, create and track tickets, request access, and "
                 "unlock accounts or reset passwords with a one-time code. It runs as its own process, separate "
                 "from this Streamlit app.")
        st.markdown("**Local (Claude Desktop):** add this to `claude_desktop_config.json` and restart Claude Desktop.")
        st.code('''{
  "mcpServers": {
    "helpdeskgenie": {
      "command": "python",
      "args": ["C:\\\\path\\\\to\\\\helpdeskgenie\\\\mcp_server.py"],
      "env": { "GENIE_USER_ID": "user123" }
    }
  }
}''', language="json")
        st.markdown("**Remote (e.g. Render):** start command `python mcp_server.py --http`, with the environment "
                    "variable `GENIE_MCP_API_KEYS=<long-random-key>:user123`. Clients connect to "
                    "`https://<your-service>/mcp` with header `Authorization: Bearer <long-random-key>`.")
        st.caption("Safeguards: the user is fixed by the server config or API key (never by the AI), one-time codes "
                   "go to the user's phone and are never shown to the AI, access requests still need a human "
                   "approver, and every call is audited.")

# ---------------------------------------------------------------------------
# 🎫 My tickets (every signed-in user; only their own records)
# ---------------------------------------------------------------------------
elif page == PAGES[6]:
    st.title("🎫 My Tickets")
    flash = st.session_state.pop("ticket_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])

    mine = sorted((t for t in store.tickets if t["user_id"] == user_id), key=lambda t: t["created_at"], reverse=True)
    my_requests = [r for r in store.access_requests if r["user_id"] == user_id]
    open_ = [t for t in mine if t["status"] not in ("Resolved", "Closed")]
    c = st.columns(3)
    c[0].metric("Open tickets", len(open_))
    c[1].metric("Resolved / closed", len(mine) - len(open_))
    c[2].metric("Access requests pending", sum(r["status"] == "Pending Approval" for r in my_requests))

    if not mine:
        st.info("You haven't logged any tickets yet. Describe your issue in **💬 HelpDesk Chat** and ask me to log a ticket.")
    else:
        df = pd.DataFrame(mine)[["ticket_id", "status", "priority", "category", "description", "created_at",
                                 "updated_at", "resolution_notes"]]
        st.dataframe(df.rename(columns=lambda c_: c_.replace("_", " ").title()), hide_index=True)

    if open_:
        st.subheader("Update one of your open tickets")
        with st.form("my_ticket_action", clear_on_submit=True):
            tid = st.selectbox("Ticket", [t["ticket_id"] for t in open_],
                               format_func=lambda i: f"{i} – {store.ticket(i)['description'][:60]}")
            action = st.radio("Action", ["Escalate", "Close (it's fixed)"], horizontal=True)
            prio = st.selectbox("New priority (for escalation)", ["P2", "P1", "P3", "P4"])
            notes = st.text_input("How was it fixed? (required to close)")
            if st.form_submit_button("Submit"):
                res = (agent.tools.escalate_ticket(user_id, tid, prio) if action == "Escalate"
                       else agent.tools.close_ticket(user_id, tid, notes))
                st.session_state.ticket_flash = (bool(res), res["message"])
                st.rerun()

    st.subheader("My access requests")
    if my_requests:
        st.dataframe(pd.DataFrame(my_requests)[["request_id", "resource", "approver_id", "status", "created_at", "decided_at"]],
                     hide_index=True)
    else:
        st.caption("None. Ask in the chat, e.g. *\"I need access to the finance share for reporting\"*.")

"""HelpDeskGenie – Conversational IT Service Desk Assistant (Streamlit front end).

Run:  streamlit run app.py

All logic lives in the `genie` package so it can be tested and reused behind
Slack / Teams bots; this file is only the UI.
"""
import pandas as pd
import streamlit as st

from genie import analytics
from genie.agent import HelpDeskAgent
from genie.evaluation import run_all, to_markdown, unverified_privileged_actions
from genie.store import Store

st.set_page_config(page_title="HelpDeskGenie", page_icon="🧞", layout="wide")

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "store" not in st.session_state:
    st.session_state.store = Store()
    st.session_state.agent = HelpDeskAgent(st.session_state.store)
    st.session_state.chats = {}
    st.session_state.eval_report = None
store = st.session_state.store
agent = st.session_state.agent

WELCOME = ("Hi, I'm **HelpDeskGenie**. Ask me an IT question (VPN, Wi-Fi, Outlook, drives, printers…), "
           "or ask me to unlock your account, reset your password, raise an access request, or log/check a ticket.")

PAGES = ["💬 HelpDesk Chat", "🧪 Evaluation (Iteration 3)", "📊 Admin Dashboard", "📬 SecOps Mailbox", "🧾 Audit Trail"]

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("🧞 HelpDeskGenie")
page = st.sidebar.radio("View", PAGES)
st.sidebar.divider()
user_id = st.sidebar.selectbox(
    "Signed in as (SSO identity)", list(store.users),
    format_func=lambda u: f"{u} – {store.users[u]['name']}" + (" 🔒" if store.users[u].get("locked") else ""))
style = st.sidebar.select_slider("Response style", ["beginner", "auto", "standard", "expert"], value="auto",
                                 help="'auto' adapts to the vocabulary the user writes with.")
detected = agent.tech_level(user_id, "", "auto") if style == "auto" else style
st.sidebar.caption(f"Current style for {user_id}: **{detected}**")

with st.sidebar.expander("📱 Demo: user's registered phone", expanded=True):
    st.caption("In production the one-time code goes by SMS or Authenticator push. Shown here for the demo only.")
    msgs = [m for m in store.otp_outbox if m["user_id"] == user_id][:3]
    if not msgs:
        st.write("No messages.")
    for m in msgs:
        st.code(f"{m['sent_at']}\n{m['text']}", language=None)

if st.sidebar.button("↺ Reset demo data"):
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
            if m.get("meta"):
                st.caption(m["meta"])

    prompt = st.chat_input("Describe your IT issue…") or st.session_state.pop("queued_prompt", None)
    if prompt:
        chat.append({"role": "user", "content": prompt})
        reply = agent.handle(prompt, user_id, style)
        meta = f"intent: {reply.intent_class}"
        if reply.actions:
            meta += f" · tools: {', '.join(reply.actions)}"
        if reply.awaiting:
            meta += f" · waiting for: {reply.awaiting}"
        chat.append({"role": "assistant", "content": reply.render("web"), "meta": meta})
        st.rerun()

# ---------------------------------------------------------------------------
# 🧪 Evaluation
# ---------------------------------------------------------------------------
elif page == PAGES[1]:
    st.title("🧪 Iteration 3: Evaluation")
    st.write("Runs every golden dataset against a fresh sandbox (your demo data is untouched). "
             "The **v1** columns score the routing rules from the original app for comparison.")
    if st.button("▶ Run evaluation", type="primary") or st.session_state.eval_report is None:
        with st.spinner("Running golden datasets…"):
            st.session_state.eval_report = run_all()
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

    t = st.tabs(["Retrieval & hallucination", "Intent routing", "Security", "Ticket categorisation", "Failure cases"])
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
        st.dataframe(rep["failures"])

    st.download_button("⬇ Download report (Markdown)", to_markdown(rep), "helpdeskgenie_eval_report.md", "text/markdown")

# ---------------------------------------------------------------------------
# 📊 Admin dashboard
# ---------------------------------------------------------------------------
elif page == PAGES[2]:
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
elif page == PAGES[3]:
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
elif page == PAGES[4]:
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

"""Admin dashboard metrics (stretch goal)."""
import datetime as dt

import pandas as pd

RECURRING_WINDOW_DAYS = 30
RECURRING_MIN = 2


def tickets_df(store):
    df = pd.DataFrame(store.tickets)
    if df.empty:
        return df
    df["created_at"] = pd.to_datetime(df["created_at"])
    df["state"] = df["status"].map(lambda s: "Resolved" if s in ("Resolved", "Closed") else "Open")
    return df


def open_vs_resolved(store):
    df = tickets_df(store)
    if df.empty:
        return pd.DataFrame()
    return df.pivot_table(index="category", columns="state", values="ticket_id", aggfunc="count", fill_value=0)


def most_common_issues(store):
    """Issue types by tickets plus self-help KB answers, so deflected issues show up too."""
    df = tickets_df(store)
    counts = df["category"].value_counts().rename("tickets") if not df.empty else pd.Series(dtype=int, name="tickets")
    kb_cat = {a["id"]: a["category"] for a in store.kb}
    kb = pd.Series([kb_cat.get(i["kb_id"]) for i in store.interactions if i["outcome"] == "kb_answer"], dtype=object)
    kb_counts = kb.value_counts().rename("self_help_answers")
    out = pd.concat([counts, kb_counts], axis=1).fillna(0).astype(int)
    out["total"] = out.sum(axis=1)
    return out.sort_values("total", ascending=False)


def remediation_stats(store):
    log = store.audit_log
    attempts = sum(1 for e in log if e["action"] == "START_VERIFICATION" and e["status"] == "SUCCESS")
    auto_ok = sum(1 for e in log if e["action"] in ("UNLOCK_ACCOUNT", "RESET_PASSWORD") and e["status"] == "SUCCESS")
    blocked = sum(1 for e in log if e["action"] in ("UNLOCK_ACCOUNT", "RESET_PASSWORD") and e["status"] == "REJECTED")
    df = tickets_df(store)
    n_tickets = len(df)
    escalated = int((df["resolution_type"] == "escalated").sum()) if n_tickets else 0
    kb_answers = sum(1 for i in store.interactions if i["outcome"] == "kb_answer")
    abstained = sum(1 for i in store.interactions if i["outcome"] == "abstained")
    new_tickets = sum(1 for e in log if e["action"] == "CREATE_TICKET")
    handled = kb_answers + auto_ok + new_tickets
    return {
        "auto_remediation_attempts": attempts,
        "auto_remediation_successes": auto_ok,
        "auto_remediation_success_rate": auto_ok / attempts if attempts else None,
        "blocked_privileged_actions": blocked,
        "tickets_total": n_tickets,
        "tickets_escalated": escalated,
        "manual_escalation_rate": escalated / n_tickets if n_tickets else None,
        "kb_self_help_answers": kb_answers,
        "abstentions": abstained,
        "self_service_rate": (kb_answers + auto_ok) / handled if handled else None,
        "pending_access_requests": sum(1 for r in store.access_requests if r["status"] == "Pending Approval"),
    }


def recurring_issues(store, window_days=RECURRING_WINDOW_DAYS, min_count=RECURRING_MIN):
    """Users with >= min_count tickets in the same category inside the window."""
    df = tickets_df(store)
    if df.empty:
        return pd.DataFrame(columns=["user_id", "category", "tickets", "ticket_ids", "last_seen"])
    recent = df[df["created_at"] >= pd.Timestamp(dt.datetime.now() - dt.timedelta(days=window_days))]
    g = recent.groupby(["user_id", "category"]).agg(
        tickets=("ticket_id", "count"), ticket_ids=("ticket_id", lambda s: ", ".join(s)), last_seen=("created_at", "max"))
    return g[g["tickets"] >= min_count].reset_index().sort_values("tickets", ascending=False)


def user_history(store, user_id):
    df = tickets_df(store)
    tickets = df[df["user_id"] == user_id].sort_values("created_at", ascending=False) if not df.empty else df
    actions = pd.DataFrame([e for e in store.audit_log if e["user_id"] == user_id])
    return tickets, actions

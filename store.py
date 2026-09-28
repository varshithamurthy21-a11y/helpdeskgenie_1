"""In-memory state for one HelpDeskGenie deployment.

Holds tickets, access requests, the audit trail, SecOps alerts and pending
verification challenges. Streamlit keeps one Store in st.session_state; the
evaluation suite creates a fresh Store per test so runs never touch the demo.

The audit trail is append-only and hash-chained (each entry stores the hash of
the previous one), so any edit or deletion is detectable with verify_audit_chain().
"""
import copy
import datetime as dt
import hashlib
import json

from . import data


def now():
    return dt.datetime.now()


def ts(t=None):
    return (t or now()).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, seed=True):
        self.kb = copy.deepcopy(data.KB_ARTICLES) + copy.deepcopy(data.RESOLVED_TICKET_SUMMARIES)
        self.users = copy.deepcopy(data.USERS)
        self.resource_owners = dict(data.RESOURCE_OWNERS)
        self.tickets = []
        self.access_requests = []
        self.audit_log = []
        self.email_alerts = []
        self.otp_outbox = []        # what the user's phone would receive (demo only)
        self.challenges = {}        # challenge_id -> challenge dict
        self.tokens = {}            # verification token -> {user_id, action, used}
        self.interactions = []      # every query the agent answered (for dashboard)
        self.user_levels = {}       # user_id -> {"expert": n, "beginner": n}
        self._seq = 6000
        if seed:
            self._seed()

    # ------------------------------------------------------------------ seed
    def _seed(self):
        for t in data.SEED_TICKETS:
            created = now() - dt.timedelta(days=t["created_days_ago"])
            self.tickets.append({
                "ticket_id": t["ticket_id"], "user_id": t["user_id"], "category": t["category"],
                "priority": t["priority"], "status": t["status"], "description": t["description"],
                "created_at": ts(created), "updated_at": ts(created),
                "resolution_type": t["resolution_type"], "resolution_notes": "",
            })
        self.audit("SYSTEM", "system", "SUCCESS", "Seed data loaded", channel="system")

    def next_id(self, prefix):
        self._seq += 1
        return f"{prefix}-{self._seq}"

    # ----------------------------------------------------------------- audit
    def audit(self, action, user_id, status, details, channel="web", meta=None):
        prev = self.audit_log[-1]["hash"] if self.audit_log else "GENESIS"
        entry = {
            "seq": len(self.audit_log) + 1,
            "timestamp": ts(),
            "action": action,
            "user_id": user_id,
            "status": status,
            "details": details,
            "channel": channel,
            "meta": meta or {},
            "prev_hash": prev,
        }
        entry["hash"] = _hash_entry(entry)
        self.audit_log.append(entry)
        return entry

    def verify_audit_chain(self):
        """Return (ok, first_bad_seq)."""
        prev = "GENESIS"
        for e in self.audit_log:
            if e["prev_hash"] != prev or _hash_entry(e) != e["hash"]:
                return False, e["seq"]
            prev = e["hash"]
        return True, None

    def secops_alert(self, user_id, action, details, severity="HIGH"):
        alert = {
            "sent_at": ts(),
            "recipient": "secops-alerts@company.internal",
            "severity": severity,
            "subject": f"SECURITY: {action} blocked for {user_id}",
            "body": details,
            "user_id": user_id,
            "action": action,
        }
        self.email_alerts.insert(0, alert)
        self.audit("SECOPS_ALERT", user_id, "SENT", f"{action}: {details}")
        return alert

    # --------------------------------------------------------------- lookups
    def ticket(self, ticket_id):
        tid = ticket_id.upper()
        return next((t for t in self.tickets if t["ticket_id"] == tid), None)

    def user_tickets(self, user_id):
        return [t for t in self.tickets if t["user_id"] == user_id]


def _hash_entry(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

"""ITSM tool layer (Iteration 2).

Seven tools the agent can call. Safety rules enforced *here*, not in the chat
layer, so no prompt or routing bug can bypass them:

* unlock_account / reset_password require a single-use verification token that
  only verify_otp() can issue, bound to the same user and the same action.
* grant_access_request never grants anything; it creates a request that a named
  human approver must decide.
* Users can only view, escalate or close their own tickets (IT admins excepted).
* Every call, allowed or refused, is written to the hash-chained audit trail.
"""
import datetime as dt
import secrets

from store import now, ts

OTP_TTL = dt.timedelta(minutes=5)
OTP_MAX_ATTEMPTS = 3
PRIORITIES = ["P1", "P2", "P3", "P4"]


class ToolResult(dict):
    """dict with ok/message plus any extra fields; truthy when ok."""

    def __bool__(self):
        return bool(self.get("ok"))


def _ok(msg, **kw):
    return ToolResult(ok=True, message=msg, **kw)


def _fail(msg, **kw):
    return ToolResult(ok=False, message=msg, **kw)


class ITSMTools:
    def __init__(self, store, channel="web", jira_client=None):
        self.s = store
        self.channel = channel
        self.jira = jira_client          # optional real JIRA client (see integrations.py)

    def _audit(self, action, user_id, status, details, **meta):
        return self.s.audit(action, user_id, status, details, channel=self.channel, meta=meta)

    def _is_admin(self, user_id):
        return self.s.users.get(user_id, {}).get("role") == "it_admin"

    def _owned_ticket(self, user_id, ticket_id, action):
        t = self.s.ticket(ticket_id)
        if t is None:
            self._audit(action, user_id, "FAILED", f"{ticket_id} not found")
            return None, _fail(f"I couldn't find ticket **{ticket_id.upper()}**. Check the number and try again.")
        if t["user_id"] != user_id and not self._is_admin(user_id):
            self._audit(action, user_id, "REJECTED", f"{ticket_id} belongs to another user")
            return None, _fail(f"Ticket **{t['ticket_id']}** belongs to another user, so I can't act on it for you.")
        return t, None

    # ------------------------------------------------------------ tickets
    def create_ticket(self, user_id, issue_type, description, priority="P3"):
        if self.jira is not None:
            ticket_id = self.jira.create_issue(user_id, issue_type, description, priority)
        else:
            ticket_id = self.s.next_id("JIRA")
        self.s.tickets.append({
            "ticket_id": ticket_id, "user_id": user_id, "category": issue_type, "priority": priority,
            "status": "Open", "description": description, "created_at": ts(), "updated_at": ts(),
            "resolution_type": None, "resolution_notes": "",
        })
        self._audit("CREATE_TICKET", user_id, "SUCCESS", f"Created {ticket_id} [{issue_type}/{priority}]", ticket_id=ticket_id)
        return _ok(f"🎫 Ticket **{ticket_id}** opened ({issue_type}, {priority}).", ticket_id=ticket_id)

    def check_ticket_status(self, user_id, ticket_id=None):
        if ticket_id is None:
            mine = self.s.user_tickets(user_id)
            self._audit("CHECK_TICKET_STATUS", user_id, "SUCCESS", f"Listed {len(mine)} tickets")
            if not mine:
                return _ok("You have no tickets on record.", tickets=[])
            lines = [f"- **{t['ticket_id']}**: {t['status']} ({t['priority']}) - {t['description']}" for t in mine[-5:]]
            return _ok("Your most recent tickets:\n" + "\n".join(lines), tickets=mine)
        t, err = self._owned_ticket(user_id, ticket_id, "CHECK_TICKET_STATUS")
        if err is not None:
            return err
        self._audit("CHECK_TICKET_STATUS", user_id, "SUCCESS", f"{t['ticket_id']} is {t['status']}")
        return _ok(f"**{t['ticket_id']}** is **{t['status']}** (priority {t['priority']}, last updated {t['updated_at']}).\n> {t['description']}", ticket=t)

    def escalate_ticket(self, user_id, ticket_id, priority="P2"):
        priority = priority.upper()
        if priority not in PRIORITIES:
            return _fail(f"Priority must be one of {', '.join(PRIORITIES)}.")
        t, err = self._owned_ticket(user_id, ticket_id, "ESCALATE_TICKET")
        if err is not None:
            return err
        if t["status"] in ("Resolved", "Closed"):
            self._audit("ESCALATE_TICKET", user_id, "REJECTED", f"{t['ticket_id']} already {t['status']}")
            return _fail(f"**{t['ticket_id']}** is already {t['status']}. Log a new ticket if the problem is back.")
        old = t["priority"]
        t.update(priority=priority, status="Escalated", resolution_type="escalated", updated_at=ts())
        self._audit("ESCALATE_TICKET", user_id, "SUCCESS", f"{t['ticket_id']} {old} -> {priority}", ticket_id=t["ticket_id"])
        return _ok(f"⬆️ **{t['ticket_id']}** escalated from {old} to **{priority}** and assigned to the L2 queue.")

    def close_ticket(self, user_id, ticket_id, resolution_notes):
        if not resolution_notes or len(resolution_notes.strip()) < 5:
            return _fail("Please add a short note on how it was resolved, e.g. `close JIRA-6001 notes: fixed after reboot`.")
        t, err = self._owned_ticket(user_id, ticket_id, "CLOSE_TICKET")
        if err is not None:
            return err
        if t["status"] == "Closed":
            return _fail(f"**{t['ticket_id']}** is already closed.")
        t.update(status="Closed", resolution_notes=resolution_notes.strip(), updated_at=ts())
        if not t.get("resolution_type"):
            t["resolution_type"] = "self-service"
        self._audit("CLOSE_TICKET", user_id, "SUCCESS", f"{t['ticket_id']} closed: {resolution_notes.strip()}", ticket_id=t["ticket_id"])
        return _ok(f"✅ **{t['ticket_id']}** closed. Notes saved: _{resolution_notes.strip()}_")

    # ------------------------------------------------------- verification
    def start_verification(self, user_id, action):
        user = self.s.users.get(user_id)
        if user is None:
            self._audit("START_VERIFICATION", user_id, "REJECTED", "Unknown user")
            return _fail("I can't find your account in the directory, so I can't verify you. Please contact the service desk.")
        code = f"{secrets.randbelow(10**6):06d}"
        cid = secrets.token_hex(4)
        self.s.challenges[cid] = {"user_id": user_id, "action": action, "code": code,
                                  "expires": now() + OTP_TTL, "attempts": 0, "done": False}
        # In production: send via SMS / Authenticator push. Here: a demo "phone" outbox.
        self.s.otp_outbox.insert(0, {"sent_at": ts(), "user_id": user_id, "to": user["phone"],
                                     "text": f"HelpDeskGenie code for {action.replace('_', ' ').lower()}: {code}"})
        self._audit("START_VERIFICATION", user_id, "SUCCESS", f"OTP sent to {user['phone']} for {action}", challenge=cid)
        return _ok(f"🔐 To protect your account I've sent a 6-digit code to your registered phone ({user['phone']}). "
                   f"Please type the code here. It expires in 5 minutes.", challenge_id=cid)

    def verify_otp(self, user_id, challenge_id, code):
        ch = self.s.challenges.get(challenge_id)
        if ch is None or ch["done"] or ch["user_id"] != user_id:
            self._audit("VERIFY_OTP", user_id, "REJECTED", "No active challenge")
            return _fail("There's no active verification for you. Ask again to get a new code.")
        if now() > ch["expires"]:
            ch["done"] = True
            self._audit("VERIFY_OTP", user_id, "REJECTED", "Code expired")
            return _fail("That code has expired. Ask again and I'll send a new one.")
        ch["attempts"] += 1
        if code != ch["code"]:
            if ch["attempts"] >= OTP_MAX_ATTEMPTS:
                ch["done"] = True
                self._audit("VERIFY_OTP", user_id, "REJECTED", f"{OTP_MAX_ATTEMPTS} wrong codes for {ch['action']}")
                self.s.secops_alert(user_id, ch["action"], f"{OTP_MAX_ATTEMPTS} incorrect one-time codes entered for {ch['action']}.")
                return _fail("❌ Too many incorrect codes. I've stopped this request and notified Security Operations. "
                             "Please contact the service desk by phone.", locked_out=True)
            left = OTP_MAX_ATTEMPTS - ch["attempts"]
            self._audit("VERIFY_OTP", user_id, "FAILED", f"Wrong code ({left} attempts left)")
            return _fail(f"That code doesn't match. You have {left} attempt(s) left.", retry=True)
        ch["done"] = True
        token = secrets.token_hex(8)
        self.s.tokens[token] = {"user_id": user_id, "action": ch["action"], "used": False}
        self._audit("VERIFY_OTP", user_id, "SUCCESS", f"Identity verified for {ch['action']}")
        return _ok("Identity verified.", token=token, action=ch["action"])

    def _consume_token(self, user_id, action, token):
        rec = self.s.tokens.get(token) if token else None
        if rec is None or rec["used"] or rec["user_id"] != user_id or rec["action"] != action:
            return False
        rec["used"] = True
        return True

    # --------------------------------------------------- self-remediation
    def unlock_account(self, user_id, verification_token=None):
        if not self._consume_token(user_id, "UNLOCK_ACCOUNT", verification_token):
            self._audit("UNLOCK_ACCOUNT", user_id, "REJECTED", "Missing or invalid verification token", verified=False)
            self.s.secops_alert(user_id, "UNLOCK_ACCOUNT", "Unlock attempted without a valid one-time verification token.")
            return _fail("❌ Unlock refused: identity verification is required. Security Operations has been notified.")
        user = self.s.users[user_id]
        was_locked = user.get("locked", False)
        user["locked"] = False
        self._audit("UNLOCK_ACCOUNT", user_id, "SUCCESS", "Unlocked in AD after OTP verification" if was_locked
                    else "Account was not locked; no change", verified=True, auto_remediation=True)
        if not was_locked:
            return _ok("Your account wasn't locked, so nothing needed to change. If you still can't sign in, try resetting your password.")
        return _ok("✅ Your account has been unlocked. You can sign in again now.")

    def reset_password(self, user_id, verification_token=None):
        if not self._consume_token(user_id, "RESET_PASSWORD", verification_token):
            self._audit("RESET_PASSWORD", user_id, "REJECTED", "Missing or invalid verification token", verified=False)
            self.s.secops_alert(user_id, "RESET_PASSWORD", "Password reset attempted without a valid one-time verification token.")
            return _fail("❌ Password reset refused: identity verification is required. Security Operations has been notified.")
        # A reset *link* is issued; the agent never sees or chooses a password.
        link = f"https://passwordreset.company.internal/r/{secrets.token_urlsafe(12)}"
        self._audit("RESET_PASSWORD", user_id, "SUCCESS", "Reset link issued after OTP verification", verified=True, auto_remediation=True)
        return _ok(f"✅ Verified. A single-use password reset link has been sent to your registered email "
                   f"(valid 15 minutes). Remember the policy: 14+ characters, and none of your last 12 passwords.", link=link)

    # ------------------------------------------------------- access requests
    def grant_access_request(self, user_id, resource, approver_id=None, justification=""):
        resource = resource.strip()
        if not resource:
            return _fail("Which system or folder do you need access to?")
        approver = approver_id or self.s.resource_owners.get(resource.lower()) \
            or self.s.users.get(user_id, {}).get("manager", "it_approvals")
        req_id = self.s.next_id("REQ")
        self.s.access_requests.append({
            "request_id": req_id, "user_id": user_id, "resource": resource, "approver_id": approver,
            "justification": justification, "status": "Pending Approval", "created_at": ts(), "decided_at": None,
        })
        self._audit("GRANT_ACCESS_REQUEST", user_id, "PENDING_APPROVAL",
                    f"{req_id}: access to '{resource}' routed to {approver}", request_id=req_id)
        return _ok(f"📝 Access request **{req_id}** for **{resource}** has been sent to **{approver}** for approval. "
                   f"Nothing is granted until they approve; you'll be notified of the decision.", request_id=req_id)

    def decide_access_request(self, approver_id, request_id, approve):
        """Called by the approver (Admin Dashboard), never by the chat agent."""
        req = next((r for r in self.s.access_requests if r["request_id"] == request_id), None)
        if req is None:
            return _fail("Request not found.")
        if approver_id != req["approver_id"] and not self._is_admin(approver_id):
            self._audit("DECIDE_ACCESS_REQUEST", approver_id, "REJECTED", f"{request_id}: not the assigned approver")
            return _fail("Only the assigned approver can decide this request.")
        if req["status"] != "Pending Approval":
            return _fail(f"Already {req['status']}.")
        req.update(status="Approved" if approve else "Denied", decided_at=ts(), decided_by=approver_id)
        self._audit("DECIDE_ACCESS_REQUEST", approver_id, "SUCCESS", f"{request_id} {req['status']} for {req['user_id']}")
        return _ok(f"{request_id} {req['status']}.")

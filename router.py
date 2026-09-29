"""Intent routing (Iteration 2).

Each message is split into:
  * zero or more tool actions (create/check/escalate/close ticket, unlock,
    reset password, access request), and
  * an optional informational part answered from the knowledge base.

Intent classes:
  greeting        - small talk
  informational   - KB answer only (RAG)
  actionable      - tool call(s) only
  mixed           - tool call(s) + KB answer ("my VPN isn't working, also log a ticket")
  needs_approval  - contains an access request, which is routed to a human approver
"""
import re
from dataclasses import dataclass, field

from retriever import MIN_SCORE

TICKET_RE = re.compile(r"\b(?:jira|inc|ticket)[\s#-]*(\d{3,6})\b", re.I)
USER_RE = re.compile(r"\b(user\d{3,})\b", re.I)

GREETINGS = {"hi", "hello", "hey", "hi genie", "hello genie", "good morning", "good afternoon", "thanks", "thank you"}

CREATE_RE = re.compile(r"\b(log|create|open|raise|file|submit|report|lodge)\b[\w\s,'-]{0,25}?\b(ticket|incident|case)\b", re.I)
STATUS_RE = re.compile(r"\b(status|update on|progress|what'?s happening with|check on|check)\b|\bmy (open )?tickets\b", re.I)
ESCALATE_RE = re.compile(r"\b(escalate|bump|raise (the )?priority|increase (the )?priority|expedite)\b", re.I)
CLOSE_RE = re.compile(r"\b(close|resolve|mark\b.{0,20}\b(resolved|closed|fixed))\b", re.I)
UNLOCK_RE = re.compile(r"\bunlock\b|\blocked out\b|\baccount (is |got |has been )?locked\b|\blocked my account\b", re.I)
RESET_RE = re.compile(r"\b(reset|forgot|forgotten|change)\b.{0,15}\bpassword\b|\bpassword\b.{0,10}\b(reset|expired)\b", re.I)
POLICY_RE = re.compile(r"\b(policy|requirements?|rules?|how (long|often|many))\b", re.I)
ACCESS_RE = re.compile(r"\b(?:need|request|want|give me|grant(?: me)?|get|requesting|add me to)\b.{0,15}?"
                       r"\b(?:access|permissions?|rights)\s+(?:to|for|on)\s+(?:the\s+)?(?P<res>[\w\s./-]{2,40}?)"
                       r"(?=\s+(?:because|for|so|as|since|please)\b|[,.!?]|$)", re.I)
ADD_TO_RE = re.compile(r"\badd me to (?:the\s+)?(?P<res>[\w\s./-]{2,40}?)(?=\s+(?:because|for|so|please)\b|[,.!?]|$)", re.I)
INFO_CUE_RE = re.compile(r"\b(tell (me )?how to (fix|solve) (it|this)|how (do|can) i (fix|solve) (it|this)|what (are|is) the)\b", re.I)
HOWTO_ACCESS_RE = re.compile(r"\bhow (do|can|would) (i|we)\b.{0,20}\b(request|get)\b.{0,10}\baccess\b", re.I)

# Social engineering / policy-bypass language. Never changes what the tools do;
# it is logged and reported so SecOps can see the attempt.
OVERRIDE_RE = re.compile(r"\b(override|bypass|skip (the )?(verification|otp|code|check)|without (the )?(verification|otp|code|mfa)"
                         r"|disable (mfa|verification)|i'?m (the |an )?(admin|ceo|director)|no time for (verification|otp))\b", re.I)
THIRD_PARTY_RE = re.compile(r"\b(my (colleague|boss|manager|coworker|co-worker|friend|teammate)'?s?|his|her|their|someone else'?s)\b", re.I)

PRIORITY_WORDS = [(r"\bp1\b|critical|sev ?1|outage", "P1"), (r"\bp2\b|urgent|high", "P2"),
                  (r"\bp3\b|medium|normal", "P3"), (r"\bp4\b|\blow\b", "P4")]

# KB articles that just describe an action; not a separate "informational" need.
ACTION_KB = {"unlock_account": {"KB110"}, "reset_password": {"KB107", "KB110"},
             "grant_access_request": {"KB109", "KB108"}, "create_ticket": set(),
             "check_ticket_status": set(), "escalate_ticket": set(), "close_ticket": set()}


@dataclass
class Route:
    intent_class: str
    actions: list = field(default_factory=list)       # [{"tool": name, "args": {...}}]
    info_query: str = None                            # text to answer from the KB
    flags: list = field(default_factory=list)         # e.g. ["override_attempt"]


def _priority(text, default="P2"):
    for pattern, p in PRIORITY_WORDS:
        if re.search(pattern, text, re.I):
            return p
    return default


def _ticket_ids(text):
    return [f"JIRA-{m}" for m in TICKET_RE.findall(text)]


def route(message, user_id, retriever, categorizer):
    text = message.strip()
    low = text.lower().strip(" !.?")
    if low in GREETINGS:
        return Route("greeting")

    actions, flags = [], []
    remainder = text
    ids = _ticket_ids(text)

    if OVERRIDE_RE.search(text):
        flags.append("override_attempt")

    # ---- account self-service (always goes through OTP in the agent) ------
    wants_unlock = bool(UNLOCK_RE.search(text))
    wants_reset = bool(RESET_RE.search(text)) and not POLICY_RE.search(text)
    if wants_unlock or wants_reset:
        target = USER_RE.search(text)
        if (target and target.group(1).lower() != user_id.lower()) or THIRD_PARTY_RE.search(text):
            flags.append("third_party_target")
    if wants_unlock:
        actions.append({"tool": "unlock_account", "args": {}})
        remainder = UNLOCK_RE.sub(" ", remainder)
    if wants_reset:
        actions.append({"tool": "reset_password", "args": {}})
        remainder = RESET_RE.sub(" ", remainder)

    # ---- ticket management --------------------------------------------------
    if ids and ESCALATE_RE.search(text):
        actions.append({"tool": "escalate_ticket", "args": {"ticket_id": ids[0], "priority": _priority(text)}})
        remainder = ""
    elif ids and CLOSE_RE.search(text):
        m = re.search(r"(?:notes?|resolution|because|reason)\s*[:\-]?\s*(.+)$", text, re.I)
        actions.append({"tool": "close_ticket", "args": {"ticket_id": ids[0], "resolution_notes": m.group(1) if m else ""}})
        remainder = ""
    elif (ids and STATUS_RE.search(text)) or re.search(r"\bmy (open |recent )?tickets\b", text, re.I) \
            or (ids and len(text.split()) <= 4):
        actions.append({"tool": "check_ticket_status", "args": {"ticket_id": ids[0] if ids else None}})
        remainder = ""

    # ---- access requests (human approval) --------------------------------
    m = ACCESS_RE.search(text) or ADD_TO_RE.search(text)
    if m and not HOWTO_ACCESS_RE.search(text) and "access denied" not in text.lower():
        resource = m.group("res").strip(" .")
        if re.search(r"\badmin(istrator)? rights\b", text, re.I):
            resource = f"local admin rights ({re.sub(r'^my ', '', resource)})"
        just = re.search(r"\b(?:because|for|so|since)\b\s+(.+)$", text[m.end():], re.I)
        actions.append({"tool": "grant_access_request",
                        "args": {"resource": resource, "justification": just.group(1) if just else ""}})
        remainder = remainder.replace(m.group(0), " ")

    # ---- new ticket -------------------------------------------------------
    if CREATE_RE.search(text) and not any(a["tool"] in ("check_ticket_status", "escalate_ticket", "close_ticket") for a in actions):
        remainder = CREATE_RE.sub(" ", remainder)
        remainder = re.sub(r"\b(can you|could you|please|also|and|for me|a new|new|support|me)\b", " ", remainder, flags=re.I)
        description = re.sub(r"\s+", " ", remainder).strip(" ,.?!-") or text
        category, _ = categorizer.predict(description)
        actions.append({"tool": "create_ticket", "args": {"issue_type": category, "description": description,
                                                          "priority": _priority(text, default="P3")}})

    # ---- is there also a question the KB can answer? ----------------------
    info_query = None
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,.?!-")
    if not actions:
        info_query = text
    elif len(remainder.split()) >= 2:
        hit = retriever.best(remainder)
        skip = set().union(*(ACTION_KB.get(a["tool"], set()) for a in actions))
        if (hit and hit[0]["id"] not in skip and hit[1] >= MIN_SCORE) or INFO_CUE_RE.search(remainder):
            info_query = INFO_CUE_RE.sub(" ", remainder).strip(" ,.?!-") or remainder

    if any(a["tool"] == "grant_access_request" for a in actions):
        cls = "needs_approval"
    elif actions and info_query:
        cls = "mixed"
    elif actions:
        cls = "actionable"
    else:
        cls = "informational"
    return Route(cls, actions, info_query, flags)

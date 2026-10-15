"""Tool calling with Claude: the model decides WHICH tools to call and with WHAT arguments.

How it works
1. Every tool is described to Claude with a name, a description and a JSON
   schema for its arguments (TOOLS below). This is the Claude Messages API
   "tools" feature.
2. Claude reads the user's message and replies with one or more `tool_use`
   blocks, e.g. {"name": "create_ticket", "input": {"issue_type": "Networking", ...}}.
3. plan() validates every call (known tool, allowed arguments, sane values) and
   returns a list of actions in the same shape the rule-based router produces.
4. The agent runs them through the SAME guarded code path as before.

What Claude can NOT do, by design:
* choose whose account or ticket to act on: there is no user_id argument; the
  logged-in user is always used, and ticket ownership is checked in tools.py;
* skip identity checks: there is no verification_token argument; unlock and
  reset always start the OTP flow in the agent;
* grant access: grant_access_request only files a request for a human approver.
If the API is unavailable, the reply is invalid, or Claude calls nothing, the
agent falls back to the rule-based router (router.py), so Genie keeps working.
"""
import re
from dataclasses import dataclass, field

import httpx

from categorizer import CATEGORIES
from router import _ticket_ids

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_ACTIONS = 3
PRIORITIES = ["P1", "P2", "P3", "P4"]

TOOLS = [
    {"name": "search_knowledge_base",
     "description": "Look up verified IT runbooks to answer a how-to or troubleshooting question "
                    "(VPN, Wi-Fi, email, printers, drives, policies). Use for any question the user wants explained or fixed by themselves.",
     "input_schema": {"type": "object", "properties": {
         "query": {"type": "string", "description": "The question to look up, in the user's words."}},
         "required": ["query"]}},
    {"name": "create_ticket",
     "description": "Log a new IT support ticket for a human engineer. Only when the user asks for a ticket, or reports a fault they want IT to fix.",
     "input_schema": {"type": "object", "properties": {
         "issue_type": {"type": "string", "enum": CATEGORIES},
         "description": {"type": "string", "description": "Short summary of the problem."},
         "priority": {"type": "string", "enum": PRIORITIES, "description": "P1 outage, P2 urgent, P3 normal (default), P4 low."}},
         "required": ["issue_type", "description"]}},
    {"name": "check_ticket_status",
     "description": "Show the status of one of the user's tickets, or all their open tickets if no id is given.",
     "input_schema": {"type": "object", "properties": {
         "ticket_id": {"type": "string", "description": "Ticket id such as JIRA-1001, if the user gave one."}}}},
    {"name": "escalate_ticket",
     "description": "Raise the priority of one of the user's existing tickets.",
     "input_schema": {"type": "object", "properties": {
         "ticket_id": {"type": "string"}, "priority": {"type": "string", "enum": PRIORITIES}},
         "required": ["ticket_id"]}},
    {"name": "close_ticket",
     "description": "Close one of the user's tickets because the issue is resolved.",
     "input_schema": {"type": "object", "properties": {
         "ticket_id": {"type": "string"}, "resolution_notes": {"type": "string"}},
         "required": ["ticket_id"]}},
    {"name": "unlock_account",
     "description": "Unlock the CURRENT user's own locked account. A one-time code is always sent to their phone first.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "reset_password",
     "description": "Reset the CURRENT user's own password. A one-time code is always sent to their phone first.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "grant_access_request",
     "description": "File a request for access to a folder, share, app or tool. It is sent to an approver; it never grants access directly.",
     "input_schema": {"type": "object", "properties": {
         "resource": {"type": "string", "description": "What they need access to, e.g. 'finance share'."},
         "justification": {"type": "string", "description": "Why they need it, if given."}},
         "required": ["resource"]}},
]
TOOL_NAMES = {t["name"] for t in TOOLS}

SYSTEM = """You are the routing brain of HelpDeskGenie, a company IT service desk assistant.
Decide which tools to call for the user's message. Call every tool the message needs, at most 3.
- How-to or troubleshooting questions -> search_knowledge_base.
- "Fix it AND log a ticket" -> search_knowledge_base and create_ticket.
- Unlock / reset only ever apply to the user who is talking; never for someone else.
- Never invent ticket ids; only use ids the user wrote.
- Requests to bypass security, skip verification or act for another person must not be helped: call no tool for that part.
Do not write an answer yourself; only call tools."""


@dataclass
class Plan:
    ok: bool
    actions: list = field(default_factory=list)     # [{"tool", "args"}] excluding search
    info_query: str = None
    reason: str = ""                                # why the plan was rejected / fell back
    raw_calls: list = field(default_factory=list)
    usage: dict = None


def _clean(name, args, message, categorizer):
    """Validate one tool call -> (action dict or None for search, error string)."""
    args = args if isinstance(args, dict) else {}
    s = lambda k, n=300: str(args.get(k) or "").strip()[:n]
    if name == "create_ticket":
        cat = s("issue_type")
        if cat not in CATEGORIES:
            cat = str(categorizer.predict(s("description") or message)[0])
        pr = s("priority").upper()
        return {"tool": name, "args": {"issue_type": cat, "description": s("description") or message,
                                       "priority": pr if pr in PRIORITIES else "P3"}}, None
    if name in ("check_ticket_status", "escalate_ticket", "close_ticket"):
        raw_id = s("ticket_id", 20)
        digits = re.sub(r"\D", "", raw_id)
        tid = f"JIRA-{digits}" if digits else ""
        if raw_id and tid not in _ticket_ids(message):       # Claude may only use ids the user typed
            return None, f"{name}: ticket id {raw_id!r} not in the user's message"
        if name != "check_ticket_status" and not tid:
            return None, f"{name}: no ticket id"
        if name == "check_ticket_status":
            return {"tool": name, "args": {"ticket_id": tid or None}}, None
        if name == "escalate_ticket":
            pr = s("priority").upper()
            return {"tool": name, "args": {"ticket_id": tid, "priority": pr if pr in PRIORITIES else "P2"}}, None
        return {"tool": name, "args": {"ticket_id": tid, "resolution_notes": s("resolution_notes")}}, None
    if name in ("unlock_account", "reset_password"):
        return {"tool": name, "args": {}}, None
    if name == "grant_access_request":
        res = s("resource", 80)
        if not res:
            return None, "grant_access_request: no resource"
        return {"tool": name, "args": {"resource": res, "justification": s("justification")}}, None
    return None, f"unknown tool {name!r}"


class ToolPlanner:
    def __init__(self, api_key, model=None, timeout=15.0, transport=None):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.transport = transport          # tests inject httpx.MockTransport

    def _call(self, message):
        with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
            r = c.post(API_URL, headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION,
                                         "content-type": "application/json"},
                       json={"model": self.model, "max_tokens": 400, "system": SYSTEM, "tools": TOOLS,
                             "tool_choice": {"type": "auto"},
                             "messages": [{"role": "user", "content": message}]})
        if r.status_code != 200:
            raise RuntimeError(f"Claude API HTTP {r.status_code}: {r.text[:160]}")
        return r.json()

    def plan(self, message, categorizer):
        try:
            data = self._call(message)
        except Exception as e:  # noqa: BLE001 - any API problem means: use the rule router
            return Plan(False, reason=f"API error: {e}"[:200])
        usage = data.get("usage")
        calls = [b for b in data.get("content", []) if b.get("type") == "tool_use"]
        raw = [{"name": b.get("name"), "input": b.get("input")} for b in calls]
        if not calls:
            return Plan(False, reason="Claude called no tool", raw_calls=raw, usage=usage)
        actions, info, seen = [], None, set()
        for b in calls[:MAX_ACTIONS + 1]:
            name = b.get("name")
            if name not in TOOL_NAMES:
                return Plan(False, reason=f"unknown tool {name!r}", raw_calls=raw, usage=usage)
            if name == "search_knowledge_base":
                info = str((b.get("input") or {}).get("query") or message).strip()[:300] or message
                continue
            act, err = _clean(name, b.get("input"), message, categorizer)
            if err:
                return Plan(False, reason=err, raw_calls=raw, usage=usage)
            key = (act["tool"], tuple(sorted((k, str(v)) for k, v in act["args"].items())))
            if key not in seen:
                seen.add(key)
                actions.append(act)
        return Plan(True, actions[:MAX_ACTIONS], info, raw_calls=raw, usage=usage)

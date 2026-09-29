"""HelpDeskGenie MCP server.

Exposes HelpDeskGenie's help-desk tools to any MCP client (Claude Desktop,
Claude Code, Cursor, another agent) so people can get IT help from the AI
assistant they already use.

    python mcp_server.py                         # stdio, for Claude Desktop (local)
    python mcp_server.py --http --port 8000      # streamable HTTP at /mcp (remote)

Security model (same rules as the Streamlit chat):
* WHO the caller is never comes from tool arguments, so the model cannot
  act for someone else. Over stdio it is GENIE_USER_ID; over HTTP it is the
  user mapped to the bearer API key in GENIE_MCP_API_KEYS ("key1:user123,key2:user456").
* Unlock / reset need a one-time code sent to the user's registered phone.
  The code is NEVER returned to the model. The person reads it from their
  phone and types it. (Demo: the "phone" is demo_phone.txt next to this file.)
* Access requests are routed to a human approver; nothing is granted here.
* Every call is written to the hash-chained audit log with channel="mcp".

State is in memory for the lifetime of the server process, separate from the
Streamlit app's demo data.
"""
import argparse
import datetime as dt
import os
import sys
from typing import Literal, Optional

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from agent import HelpDeskAgent
from store import Store

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = Store()
AGENT = HelpDeskAgent(STORE, channel="mcp")
TOOLS = AGENT.tools
PENDING = {}          # user_id -> {"challenge_id", "action"}

INSTRUCTIONS = (
    "HelpDeskGenie is the company IT service desk. Use search_it_knowledge_base for troubleshooting and "
    "quote the returned steps exactly; never invent remediation steps. If it reports no verified runbook, "
    "offer to create a ticket. Account unlocks and password resets always need a one-time code that the "
    "user receives on their phone: call start_identity_verification, ask the user to type the code, then "
    "call complete_account_action with it. Never guess or fabricate a code."
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def api_keys():
    pairs = [p.split(":", 1) for p in os.environ.get("GENIE_MCP_API_KEYS", "").split(",") if ":" in p]
    return {k.strip(): u.strip() for k, u in pairs if k.strip()}


def current_user(ctx: Optional[Context]) -> str:
    request = None
    try:
        request = ctx.request_context.request if ctx is not None else None
    except (AttributeError, ValueError, LookupError):
        request = None
    if request is not None and hasattr(request, "headers"):                 # HTTP transport
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        user = api_keys().get(token)
        if not user:
            raise PermissionError("Invalid or missing API key.")
    else:                                                                     # stdio transport
        user = os.environ.get("GENIE_USER_ID", "").strip()
        if not user:
            raise PermissionError("Set GENIE_USER_ID in the MCP server config to say which employee this is.")
    if user not in STORE.users:
        raise PermissionError(f"User '{user}' is not in the directory.")
    return user


def deliver_demo_otp(user_id):
    """Demo stand-in for SMS: write the newest code to demo_phone.txt and stderr (never stdout,
    which carries the MCP protocol over stdio, and never into a tool result)."""
    msg = next((m for m in STORE.otp_outbox if m["user_id"] == user_id), None)
    if msg is None or os.environ.get("GENIE_DEMO_OTP", "1") != "1":
        return
    line = f"[{msg['sent_at']}] to {msg['to']} ({user_id}): {msg['text']}\n"
    with open(os.path.join(HERE, "demo_phone.txt"), "a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="", file=sys.stderr)


# ---------------------------------------------------------------------------
# Tools (plain functions, registered on the server in build_server)
# ---------------------------------------------------------------------------
def search_it_knowledge_base(query: str, ctx: Context = None) -> str:
    """Search the verified IT knowledge base (runbooks, policies, past resolved tickets).
    Returns step-by-step instructions with the source link, or says there is no verified
    runbook. Quote the steps exactly as returned."""
    user = current_user(ctx)
    hit = AGENT.retriever.best(query)
    if hit is None:
        STORE.audit("ABSTAIN", user, "NO_KB_MATCH", f"No verified runbook for: {query[:80]}", channel="mcp")
        return ("NO VERIFIED RUNBOOK for this issue. Do not suggest fixes for company systems; "
                "offer to create a ticket with create_ticket instead.")
    art, score = hit
    parts = []
    clar = art.get("clarify")
    if clar:
        variant = AGENT._match_variant(clar, query)
        if variant:
            text, _ = AGENT._format_article(art, "standard", clar["variants"][variant]["steps"], f" ({variant})")
            parts.append(text)
        else:
            parts.append(f"The fix depends on the situation. Ask the user: {clar['question']}")
            for name, v in clar["variants"].items():
                text, _ = AGENT._format_article(art, "standard", v["steps"], f" ({name})")
                parts.append(text)
    else:
        text, _ = AGENT._format_article(art, "standard")
        parts.append(text)
    past = AGENT.retriever.related_past_fix(query, exclude_id=art["id"])
    if past:
        parts.append(f"Related past fix ({past['id']}): {past['steps'][0]}")
    STORE.audit("KB_ANSWER", user, "SUCCESS", f"Answered from {art['id']} (score {score:.2f})",
                channel="mcp", meta={"kb_id": art["id"], "score": round(score, 3)})
    return "\n\n".join(parts)


def create_ticket(description: str, priority: Literal["P1", "P2", "P3", "P4"] = "P3", ctx: Context = None) -> str:
    """Open a service-desk ticket for the current user. The category is chosen automatically."""
    user = current_user(ctx)
    category, _ = AGENT.categorizer.predict(description)
    return TOOLS.create_ticket(user, category, description, priority)["message"]


def check_ticket_status(ticket_id: Optional[str] = None, ctx: Context = None) -> str:
    """Status of one of the user's tickets (e.g. JIRA-5601), or their recent tickets if no id is given."""
    return TOOLS.check_ticket_status(current_user(ctx), ticket_id)["message"]


def escalate_ticket(ticket_id: str, priority: Literal["P1", "P2", "P3", "P4"] = "P2", ctx: Context = None) -> str:
    """Raise the priority of one of the user's open tickets and move it to the L2 queue."""
    return TOOLS.escalate_ticket(current_user(ctx), ticket_id, priority)["message"]


def close_ticket(ticket_id: str, resolution_notes: str, ctx: Context = None) -> str:
    """Close one of the user's tickets. resolution_notes must say how it was resolved."""
    return TOOLS.close_ticket(current_user(ctx), ticket_id, resolution_notes)["message"]


def request_access(resource: str, justification: str = "", ctx: Context = None) -> str:
    """Raise an access request (system, share, software, admin rights). It is routed to the resource
    owner or the user's manager for approval; nothing is granted automatically."""
    return TOOLS.grant_access_request(current_user(ctx), resource, justification=justification)["message"]


def start_identity_verification(action: Literal["unlock_account", "reset_password"], ctx: Context = None) -> str:
    """Step 1 of an account unlock or password reset: sends a 6-digit one-time code to the user's
    registered phone. Then ask the user to type the code and call complete_account_action."""
    user = current_user(ctx)
    res = TOOLS.start_verification(user, action.upper())
    if not res:
        return res["message"]
    PENDING[user] = {"challenge_id": res["challenge_id"], "action": action}
    deliver_demo_otp(user)
    return (f"A one-time code has been sent to the user's registered phone ({STORE.users[user]['phone']}). "
            "Ask the user to read it from their phone and type it. Do not guess it.")


def complete_account_action(code: str, ctx: Context = None) -> str:
    """Step 2: verify the one-time code the user typed and perform the pending unlock or reset.
    After 3 wrong codes the request is stopped and Security Operations is alerted."""
    user = current_user(ctx)
    pending = PENDING.get(user)
    if pending is None:
        return "There is no pending verification. Call start_identity_verification first."
    res = TOOLS.verify_otp(user, pending["challenge_id"], code.strip())
    if not res:
        if not res.get("retry"):
            PENDING.pop(user, None)
        return res["message"]
    PENDING.pop(user, None)
    return getattr(TOOLS, pending["action"])(user, verification_token=res["token"])["message"]


def ask_helpdesk(message: str, ctx: Context = None) -> str:
    """Send a free-text message to the HelpDeskGenie agent (it routes to the knowledge base or tools
    and may ask a clarifying question). Use the specific tools when the intent is clear."""
    user = current_user(ctx)
    return AGENT.handle(message, user).text


READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
ACCOUNT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

TOOL_TABLE = [
    (search_it_knowledge_base, READ_ONLY),
    (check_ticket_status, READ_ONLY),
    (create_ticket, WRITES),
    (escalate_ticket, WRITES),
    (close_ticket, WRITES),
    (request_access, WRITES),
    (start_identity_verification, ACCOUNT),
    (complete_account_action, ACCOUNT),
    (ask_helpdesk, WRITES),
]


def build_server(host="127.0.0.1", port=8000):
    server = FastMCP("HelpDeskGenie", instructions=INSTRUCTIONS, host=host, port=port, stateless_http=True)
    for fn, ann in TOOL_TABLE:
        server.tool(annotations=ann)(fn)

    @server.custom_route("/health", methods=["GET"])
    async def health(request):
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "ok", "time": dt.datetime.now().isoformat(timespec="seconds")})

    return server


def http_app(server):
    """Streamable-HTTP ASGI app with bearer-key auth in front of /mcp."""
    from starlette.responses import JSONResponse

    app = server.streamable_http_app()
    keys_configured = bool(api_keys())

    class BearerAuth:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"].startswith("/mcp"):
                headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
                token = headers.get("authorization", "").removeprefix("Bearer ").strip()
                if not keys_configured or token not in api_keys():
                    resp = JSONResponse({"error": "unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                    return await resp(scope, receive, send)
            return await self.inner(scope, receive, send)

    return BearerAuth(app)


def main():
    p = argparse.ArgumentParser(description="HelpDeskGenie MCP server")
    p.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    p.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = p.parse_args()
    if args.http:
        if not api_keys():
            sys.exit("Set GENIE_MCP_API_KEYS (e.g. 'longrandomkey:user123') before serving over HTTP.")
        import uvicorn
        server = build_server(args.host, args.port)
        uvicorn.run(http_app(server), host=args.host, port=args.port, log_level="info")
    else:
        build_server().run(transport="stdio")


if __name__ == "__main__":
    main()

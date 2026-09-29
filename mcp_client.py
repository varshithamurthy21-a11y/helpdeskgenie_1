"""MCP client: lets HelpDeskGenie use tools on other MCP servers.

Configured from Streamlit secrets (.streamlit/secrets.toml locally, or the app's
Settings -> Secrets on Streamlit Community Cloud):

    [mcp_servers.jira]
    url = "https://your-atlassian-mcp.example.com/mcp"
    transport = "http"                      # "http" (streamable HTTP) or "sse"
    headers = { Authorization = "Bearer YOUR_TOKEN" }

    [mcp_integrations.ticketing]            # create_ticket -> this MCP tool
    server = "jira"
    tool = "jira_create_issue"
    args = { project_key = "ITSD", summary = "{summary}", issue_type = "Task", description = "{description}" }

    [mcp_integrations.knowledge]            # used when the local KB has no verified runbook
    server = "confluence"
    tool = "confluence_search"
    args = { query = "{query}" }

Placeholders available in `args`: {summary} {description} {category} {priority}
{priority_name} {user_id} for ticketing, and {query} for knowledge.
Tool names and argument names differ between MCP servers: open the app's
"MCP Connections" page to see what each server offers.
"""
import asyncio
import concurrent.futures
import json
import re
from dataclasses import dataclass, field

from mcp import ClientSession

TICKET_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
PRIORITY_NAMES = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}


@dataclass
class MCPServerConfig:
    name: str
    url: str
    transport: str = "http"
    headers: dict = field(default_factory=dict)
    timeout: float = 20.0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def load_config(secrets):
    """(servers, integrations) from a secrets mapping; both empty when not configured."""
    try:
        raw_servers = dict(secrets.get("mcp_servers", {}) or {})
        integrations = {k: dict(v) for k, v in dict(secrets.get("mcp_integrations", {}) or {}).items()}
    except Exception:             # no secrets file at all
        return {}, {}
    servers = {}
    for name, c in raw_servers.items():
        c = dict(c)
        if not c.get("url"):
            continue
        servers[name] = MCPServerConfig(name=name, url=c["url"], transport=c.get("transport", "http"),
                                        headers={k: str(v) for k, v in dict(c.get("headers", {}) or {}).items()},
                                        timeout=float(c.get("timeout", 20)))
    return servers, integrations


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
def _run(coro, timeout):
    """Run a coroutine to completion from sync code, even if an event loop is already running."""
    async def guarded():
        return await asyncio.wait_for(coro, timeout)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(guarded())
    with concurrent.futures.ThreadPoolExecutor(1) as ex:
        return ex.submit(asyncio.run, guarded()).result()


async def _with_session(cfg, fn):
    if cfg.transport == "sse":
        from mcp.client.sse import sse_client
        async with sse_client(cfg.url, headers=cfg.headers) as (read, write):
            async with ClientSession(read, write) as s:
                await s.initialize()
                return await fn(s)
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(cfg.url, headers=cfg.headers) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            return await fn(s)


def result_text(result):
    parts = []
    for c in getattr(result, "content", []) or []:
        if getattr(c, "text", None):
            parts.append(c.text)
    if not parts and getattr(result, "structuredContent", None):
        parts.append(json.dumps(result.structuredContent))
    return "\n".join(parts)


def list_tools(cfg):
    async def go(s):
        return (await s.list_tools()).tools
    tools = _run(_with_session(cfg, go), cfg.timeout)
    return [{"name": t.name, "description": (t.description or "").strip(), "input_schema": t.inputSchema} for t in tools]


def call_tool(cfg, name, args):
    """Returns (ok, text)."""
    async def go(s):
        return await s.call_tool(name, args)
    result = _run(_with_session(cfg, go), cfg.timeout)
    return (not getattr(result, "isError", False)), result_text(result)


def describe_error(exc):
    """Readable message for errors, including anyio ExceptionGroups from the transport."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, asyncio.TimeoutError):
        return "timed out"
    msg = str(exc) or type(exc).__name__
    return msg[:300]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fill_template(template, values):
    """Recursively substitute {placeholders} in strings inside dicts/lists."""
    safe = {k: str(v).replace('"', "'") for k, v in values.items()}
    if isinstance(template, str):
        return template.format_map(_Keep(safe))
    if isinstance(template, dict):
        return {k: fill_template(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill_template(v, values) for v in template]
    return template


# ---------------------------------------------------------------------------
# Integrations used by the agent
# ---------------------------------------------------------------------------
class MCPTicketClient:
    """Drop-in for ITSMTools.jira: create_issue() via an MCP tool (e.g. a JIRA MCP server)."""

    def __init__(self, cfg, tool, args_template, store=None):
        self.cfg, self.tool, self.args, self.store = cfg, tool, args_template or {}, store
        self.label = f"{cfg.name}/{tool}"

    def create_issue(self, user_id, category, description, priority="P3"):
        values = {"user_id": user_id, "category": category, "description": description,
                  "summary": description[:120], "priority": priority, "priority_name": PRIORITY_NAMES.get(priority, "Medium")}
        args = fill_template(self.args, values)
        try:
            ok, text = call_tool(self.cfg, self.tool, args)
        except BaseException as e:           # noqa: BLE001 - transport errors come as ExceptionGroups
            self._audit(user_id, "FAILED", describe_error(e))
            raise RuntimeError(describe_error(e)) from None
        m = TICKET_KEY_RE.search(text or "")
        if not ok or not m:
            self._audit(user_id, "FAILED", (text or "no ticket key in response")[:200])
            raise RuntimeError((text or "no ticket key in response")[:200])
        self._audit(user_id, "SUCCESS", f"created {m.group(0)}")
        return m.group(0)

    def _audit(self, user_id, status, details):
        if self.store is not None:
            self.store.audit("MCP_CALL", user_id, status, f"{self.label}: {details}", channel="mcp-client")


class MCPKnowledgeSource:
    """External knowledge search via an MCP tool (e.g. Confluence). Results are quoted, never rewritten."""

    TITLE = ("title", "name", "summary", "subject")
    URL = ("url", "link", "webui", "web_url", "href", "self")
    BODY = ("excerpt", "content", "body", "text", "snippet", "description")

    def __init__(self, cfg, tool, args_template, store=None, max_results=3):
        self.cfg, self.tool, self.args, self.store, self.max = cfg, tool, args_template or {"query": "{query}"}, store, max_results
        self.label = f"{cfg.name}/{tool}"

    def search(self, query, user_id="system"):
        try:
            ok, text = call_tool(self.cfg, self.tool, fill_template(self.args, {"query": query}))
        except BaseException as e:           # noqa: BLE001
            self._audit(user_id, "FAILED", describe_error(e))
            return []
        if not ok or not (text or "").strip():
            self._audit(user_id, "FAILED" if not ok else "EMPTY", (text or "")[:200])
            return []
        results = self.parse(text)[: self.max]
        self._audit(user_id, "SUCCESS", f"{len(results)} result(s) for: {query[:60]}")
        return results

    @classmethod
    def parse(cls, text):
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return [{"title": "", "url": "", "excerpt": text.strip()[:700]}]
        if isinstance(data, dict):
            for key in ("results", "items", "pages", "data", "hits"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                data = [data]
        out = []
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict):
                out.append({"title": "", "url": "", "excerpt": str(item)[:700]})
                continue
            pick = lambda keys: next((str(item[k]) for k in keys if item.get(k) and not isinstance(item[k], (dict, list))), "")
            excerpt = re.sub(r"<[^>]+>", "", pick(cls.BODY))
            out.append({"title": pick(cls.TITLE), "url": pick(cls.URL), "excerpt": excerpt.strip()[:700]})
        return [r for r in out if r["excerpt"] or r["title"]]

    def _audit(self, user_id, status, details):
        if self.store is not None:
            self.store.audit("MCP_CALL", user_id, status, f"{self.label}: {details}", channel="mcp-client")


def build_integrations(servers, integrations, store):
    """(ticket_client or None, knowledge_source or None, problems[list of str])."""
    problems, ticket, knowledge = [], None, None
    for key, cls in (("ticketing", MCPTicketClient), ("knowledge", MCPKnowledgeSource)):
        conf = integrations.get(key)
        if not conf:
            continue
        cfg = servers.get(conf.get("server", ""))
        if cfg is None or not conf.get("tool"):
            problems.append(f"mcp_integrations.{key}: needs `server` (one of {sorted(servers) or 'none configured'}) and `tool`.")
            continue
        obj = cls(cfg, conf["tool"], dict(conf.get("args", {}) or {}), store=store)
        if key == "ticketing":
            ticket = obj
        else:
            knowledge = obj
    return ticket, knowledge, problems

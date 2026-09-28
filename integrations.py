"""Adapters for the systems HelpDeskGenie plugs into rather than replaces.

The demo runs on in-memory mocks (store.py). To go live, pass real clients:

    from genie.integrations import JiraClient, load_kb_from_confluence
    store = Store()
    store.kb = load_kb_from_confluence(...) + store.kb        # real runbooks
    agent = HelpDeskAgent(store)
    agent.tools.jira = JiraClient(...)                        # real tickets

Credentials come from environment variables; nothing is hard-coded.
ServiceNow and AD/LDAP follow the same pattern: implement the methods the tool
layer calls (create_issue, unlock, send_reset_link) and swap them in. The
verification and approval gates stay in tools.py either way.
"""
import html
import os
import re

try:
    import requests
except ImportError:          # the demo never needs it
    requests = None


class JiraClient:
    """Minimal JIRA REST v2 client (create an issue, read its status)."""

    def __init__(self, base_url=None, email=None, api_token=None, project_key=None):
        if requests is None:
            raise RuntimeError("pip install requests to use JiraClient")
        self.base = (base_url or os.environ["JIRA_BASE_URL"]).rstrip("/")
        self.auth = (email or os.environ["JIRA_EMAIL"], api_token or os.environ["JIRA_API_TOKEN"])
        self.project = project_key or os.environ.get("JIRA_PROJECT", "ITSD")

    def create_issue(self, user_id, category, description, priority="P3"):
        prio = {"P1": "Highest", "P2": "High", "P3": "Medium", "P4": "Low"}.get(priority, "Medium")
        payload = {"fields": {
            "project": {"key": self.project},
            "summary": description[:120],
            "description": f"{description}\n\nRaised by HelpDeskGenie on behalf of {user_id}.",
            "issuetype": {"name": "Task"},
            "labels": [category.lower(), "helpdeskgenie"],
            "priority": {"name": prio},
        }}
        r = requests.post(f"{self.base}/rest/api/2/issue", json=payload, auth=self.auth, timeout=15)
        r.raise_for_status()
        return r.json()["key"]

    def get_status(self, key):
        r = requests.get(f"{self.base}/rest/api/2/issue/{key}", params={"fields": "status,priority"},
                         auth=self.auth, timeout=15)
        r.raise_for_status()
        f = r.json()["fields"]
        return {"status": f["status"]["name"], "priority": (f.get("priority") or {}).get("name")}


def load_kb_from_confluence(base_url=None, space=None, email=None, api_token=None, category_label_prefix="cat-"):
    """Pull runbooks from a Confluence space and convert them to KB articles.

    Each list item (<li>) in a page becomes one step, so the agent can still
    quote steps verbatim. Pages need a label like `cat-networking` for category.
    """
    if requests is None:
        raise RuntimeError("pip install requests to load from Confluence")
    base = (base_url or os.environ["CONFLUENCE_BASE_URL"]).rstrip("/")
    auth = (email or os.environ["CONFLUENCE_EMAIL"], api_token or os.environ["CONFLUENCE_API_TOKEN"])
    space = space or os.environ.get("CONFLUENCE_SPACE", "ITKB")
    articles, start = [], 0
    while True:
        r = requests.get(f"{base}/rest/api/content", auth=auth, timeout=30, params={
            "spaceKey": space, "type": "page", "expand": "body.storage,metadata.labels", "limit": 50, "start": start})
        r.raise_for_status()
        data = r.json()
        for page in data["results"]:
            body = page["body"]["storage"]["value"]
            steps = [html.unescape(re.sub(r"<[^>]+>", "", li)).strip() for li in re.findall(r"<li>(.*?)</li>", body, re.S)]
            labels = [lb["name"] for lb in page["metadata"]["labels"]["results"]]
            cat = next((lb[len(category_label_prefix):].title() for lb in labels if lb.startswith(category_label_prefix)), "Applications")
            if steps:
                articles.append({"id": f"CF{page['id']}", "title": page["title"], "category": cat,
                                 "tags": " ".join(labels), "critical": "critical" in labels, "steps": steps,
                                 "tip": "", "expert": "", "url": base + page["_links"]["webui"]})
        if data.get("size", 0) < 50:
            return articles
        start += 50

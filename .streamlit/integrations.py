"""Direct REST adapters for Atlassian (JIRA + Confluence). Standard library only.

Used when HelpDeskGenie talks to Atlassian WITHOUT going through Atlassian's MCP
server, e.g. the Render MCP server creating real JIRA issues:

    JIRA_BASE_URL = https://your-site.atlassian.net
    JIRA_EMAIL    = you@example.com
    JIRA_API_TOKEN= <API token from id.atlassian.com>
    JIRA_PROJECT  = ITSD            (optional, default ITSD)

Credentials come from environment variables / Secrets only, never the code.
The verification and approval gates stay in tools.py either way.
"""
import base64
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

PRIORITY_LABEL = {"P1": "p1-highest", "P2": "p2-high", "P3": "p3-medium", "P4": "p4-low"}


class AtlassianError(RuntimeError):
    pass


class _Rest:
    def __init__(self, base_url, email, api_token, timeout=20):
        self.base = base_url.rstrip("/")
        self.auth = "Basic " + base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self.timeout = timeout

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": self.auth, "Accept": "application/json", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise AtlassianError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise AtlassianError(f"{method} {path} -> {e.reason}") from None


class JiraClient(_Rest):
    """Creates and reads JIRA Cloud issues. Plugs into ITSMTools.jira (create_issue)."""

    def __init__(self, base_url=None, email=None, api_token=None, project_key=None, issue_type=None):
        super().__init__(base_url or os.environ["JIRA_BASE_URL"], email or os.environ["JIRA_EMAIL"],
                         api_token or os.environ["JIRA_API_TOKEN"])
        self.project = project_key or os.environ.get("JIRA_PROJECT", "ITSD")
        self.issue_type = issue_type or os.environ.get("JIRA_ISSUE_TYPE", "Task")
        self.label = f"jira:{self.project}"

    def create_issue(self, user_id, category, description, priority="P3"):
        # No "priority" field: many free / team-managed projects reject it. It goes in a label instead.
        payload = {"fields": {
            "project": {"key": self.project},
            "summary": description[:120],
            "description": f"{description}\n\nRaised by HelpDeskGenie on behalf of {user_id} ({priority}).",
            "issuetype": {"name": self.issue_type},
            "labels": ["helpdeskgenie", re.sub(r"\W+", "-", category.lower()), PRIORITY_LABEL.get(priority, "p3-medium")],
        }}
        return self.request("POST", "/rest/api/2/issue", payload)["key"]

    def get_status(self, key):
        f = self.request("GET", f"/rest/api/2/issue/{key}?fields=status")["fields"]
        return {"status": f["status"]["name"]}

    @classmethod
    def from_env(cls):
        """A client when JIRA_BASE_URL, JIRA_EMAIL and JIRA_API_TOKEN are all set, else None."""
        if all(os.environ.get(k) for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN")):
            return cls()
        return None


class ConfluenceClient(_Rest):
    def __init__(self, base_url, email, api_token):
        super().__init__(base_url.rstrip("/") + "/wiki", email, api_token)

    def find_page(self, space, title):
        q = urllib.parse.quote
        res = self.request("GET", f"/rest/api/content?spaceKey={q(space)}&title={q(title)}&type=page")
        return res["results"][0] if res.get("results") else None

    def create_page(self, space, title, html_body, labels=()):
        page = self.request("POST", "/rest/api/content", {
            "type": "page", "title": title, "space": {"key": space},
            "body": {"storage": {"value": html_body, "representation": "storage"}}})
        if labels:
            self.request("POST", f"/rest/api/content/{page['id']}/label", [{"prefix": "global", "name": n} for n in labels])
        return page

    def load_runbooks(self, space, category_prefix="cat-"):
        """Confluence pages -> KB articles (each <li> becomes one verbatim step)."""
        out, start = [], 0
        while True:
            res = self.request("GET", f"/rest/api/content?spaceKey={space}&type=page&expand=body.storage,metadata.labels"
                                      f"&limit=50&start={start}")
            for p in res.get("results", []):
                body = p["body"]["storage"]["value"]
                steps = [html.unescape(re.sub(r"<[^>]+>", "", li)).strip() for li in re.findall(r"<li>(.*?)</li>", body, re.S)]
                labels = [lb["name"] for lb in p["metadata"]["labels"]["results"]]
                cat = next((lb[len(category_prefix):].title() for lb in labels if lb.startswith(category_prefix)), "Applications")
                if steps:
                    out.append({"id": f"CF{p['id']}", "title": p["title"], "category": cat, "tags": " ".join(labels),
                                "critical": "critical" in labels, "steps": steps, "tip": "", "expert": "",
                                "url": self.base + p["_links"]["webui"]})
            if res.get("size", 0) < 50:
                return out
            start += 50



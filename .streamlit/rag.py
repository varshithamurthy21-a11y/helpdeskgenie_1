"""Generation step of RAG (Retrieval-Augmented Generation).

retriever.py RETRIEVES the most relevant runbooks; this module asks Claude to
GENERATE a natural answer from them, then checks the answer before anyone sees it.

Grounding rules (enforced in code, not just in the prompt):
* Claude only sees the retrieved runbook steps, each with an id like KB101.2.
* Every step it writes must cite one of those ids.
* Every technical detail it writes (commands, paths, URLs, numbers, menu names
  in **bold** or `code`) must appear word for word in the cited runbook.
* Most of a step's words must come from the cited runbook.
If any check fails, or there is no API key, or the API errors, the caller falls
back to quoting the verified steps exactly (the extractive answer).
Critical articles (passwords, access, lockout, MFA) are never paraphrased.

Uses the Claude Messages API over HTTPS with httpx (already installed with `mcp`).
"""
import json
import re
from dataclasses import dataclass, field

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
MAX_STEPS = 7
MIN_SUPPORT = 0.5          # share of a step's content words that must come from its cited runbook

STOP = set("""a an the and or but if then so to of in on at by for with from as is are was were be been being it its
this that these those you your yours we our i me my he she they them their there here do does did doing can could
should would will just not no yes up down out into over under again further once all any both each few more most other
some such only own same than too very s t don now also please make sure use using via get got go""".split())

SYSTEM = """You are HelpDeskGenie, a company IT service desk assistant.
Answer the user's question using ONLY the runbook steps in CONTEXT. Each step has an id like KB101.2.

Rules:
- Rewrite the steps clearly for the user's situation. You may merge, shorten, reorder or skip steps.
- Never add a step, command, path, URL, setting, number or product name that is not in CONTEXT.
- Every step you write must cite exactly one CONTEXT step id that supports it.
- Copy commands, paths, URLs and menu names exactly as written in CONTEXT.
- If CONTEXT does not answer the question, return {"abstain": true}.
- Style: {style}

Reply with JSON only, no other text:
{"intro": "<one short sentence>", "steps": [{"text": "<step>", "cite": "<step id>"}], "followup": "<optional short question, or empty>"}"""

STYLES = {
    "beginner": "plain, friendly words; briefly explain any technical term.",
    "expert": "terse and technical; as few steps as possible.",
    "standard": "clear and concise.",
}


@dataclass
class RAGResult:
    ok: bool
    text: str = ""
    cited: list = field(default_factory=list)       # ["KB101.2", ...]
    sources: list = field(default_factory=list)     # article ids used
    reason: str = ""                                 # why it fell back
    raw: str = ""


# ---------------------------------------------------------------------------
# Grounding checks
# ---------------------------------------------------------------------------
def content_words(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9'_-]*", text.lower()) if len(w) > 2 and w not in STOP]


TECH_PATTERNS = [
    r"`([^`]+)`",                               # inline code
    r"\*\*([^*]+)\*\*",                         # bold UI names
    r"(https?://\S+)",                          # URLs
    r"(\\\\[\w.\\-]+)",                         # UNC paths
    r"\b(\d+(?:\.\d+)?)\b",                     # numbers (ports, counts, minutes)
    r"\b(ipconfig\s*/\w+)",                     # commands
]


def technical_tokens(text):
    toks = []
    for p in TECH_PATTERNS:
        toks += [m.strip().rstrip(".,;)") for m in re.findall(p, text, re.I)]
    return [t for t in toks if t]


def check_step(step_text, source_text):
    """None when the step is grounded in source_text, else the reason."""
    src_low = source_text.lower()
    for tok in technical_tokens(step_text):
        if tok.lower() not in src_low:
            return f"detail not in source: {tok!r}"
    words = content_words(step_text)
    if words:
        src_words = set(content_words(source_text))
        support = sum(w in src_words for w in words) / len(words)
        if support < MIN_SUPPORT:
            return f"only {support:.0%} of its words come from the source"
    return None


def parse_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    return json.loads(raw[start:end + 1])


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
class RAGGenerator:
    def __init__(self, api_key, model=None, timeout=20.0, transport=None):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self.transport = transport          # tests inject httpx.MockTransport

    @staticmethod
    def build_context(articles):
        """articles: [{"id","title","steps"}] -> (prompt text, {step_id: step text}, {article_id: full text})."""
        lines, steps, full = [], {}, {}
        for a in articles:
            lines.append(f"## {a['id']}: {a['title']}")
            for i, s in enumerate(a["steps"], 1):
                sid = f"{a['id']}.{i}"
                steps[sid] = s
                lines.append(f"[{sid}] {s}")
            full[a["id"]] = a["title"] + " " + " ".join(a["steps"])
        return "\n".join(lines), steps, full

    def _call(self, system, user):
        with httpx.Client(timeout=self.timeout, transport=self.transport) as c:
            r = c.post(API_URL, headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION,
                                         "content-type": "application/json"},
                       json={"model": self.model, "max_tokens": 700, "system": system,
                             "messages": [{"role": "user", "content": user}]})
        if r.status_code != 200:
            raise RuntimeError(f"Claude API HTTP {r.status_code}: {r.text[:160]}")
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def generate(self, query, articles, level="standard"):
        context, steps, full = self.build_context(articles)
        system = SYSTEM.replace("{style}", STYLES.get(level, STYLES["standard"]))
        user = f"CONTEXT:\n{context}\n\nUSER QUESTION: {query}"
        try:
            raw = self._call(system, user)
        except Exception as e:  # noqa: BLE001 - any API problem means: fall back
            return RAGResult(False, reason=f"API error: {e}"[:200])
        try:
            obj = parse_json(raw)
        except (ValueError, json.JSONDecodeError):
            return RAGResult(False, reason="reply was not valid JSON", raw=raw)
        if obj.get("abstain"):
            return RAGResult(False, reason="model abstained", raw=raw)
        out_steps = obj.get("steps") or []
        if not isinstance(out_steps, list) or not out_steps or len(out_steps) > MAX_STEPS:
            return RAGResult(False, reason="no steps, or too many", raw=raw)

        cited, lines = [], []
        for st in out_steps:
            text, cite = str(st.get("text", "")).strip(), str(st.get("cite", "")).strip()
            if not text or cite not in steps:
                return RAGResult(False, reason=f"step cites unknown source {cite!r}", raw=raw)
            art_id = cite.rsplit(".", 1)[0]
            problem = check_step(text, full[art_id])
            if problem:
                return RAGResult(False, reason=f"{cite}: {problem}", raw=raw)
            cited.append(cite)
            lines.append(f"{len(lines) + 1}. {text}  `[{cite}]`")

        extras = []
        for key in ("intro", "followup"):
            val = str(obj.get(key) or "").strip()[:240]
            if val:
                bad = [t for t in technical_tokens(val) if t.lower() not in context.lower()]
                if bad:
                    return RAGResult(False, reason=f"{key} has a detail not in sources: {bad[0]!r}", raw=raw)
            extras.append(val)
        intro, followup = extras
        body = (intro + "\n\n" if intro else "") + "\n".join(lines) + (f"\n\n{followup}" if followup else "")
        sources = list(dict.fromkeys(c.rsplit(".", 1)[0] for c in cited))
        return RAGResult(True, body, cited, sources, raw=raw)

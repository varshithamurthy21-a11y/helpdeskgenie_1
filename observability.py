"""Observability: a trace for every message Genie handles.

The audit trail (store.py) answers "WHO did WHAT, and was it allowed?".
Traces answer "HOW did the AI get there, how long did it take, and what did it cost?".

Each call to HelpDeskAgent.handle() produces one trace:
    trace = {id, ts, user_id, message, intent, answer_mode, tools, status,
             latency_ms, tokens_in, tokens_out, cost_usd, spans: [...]}
and each step inside it is a span:
    span  = {name, start_ms, ms, status, attrs}
Span names used by the agent: route, plan_tools (Claude tool calling),
retrieve, rag_generate (Claude RAG), tool:<name>, verify_otp.

Nothing here sends data anywhere: traces are kept in memory (last 500) and can
be downloaded as JSON Lines from the admin Observability page, which is the
format tools such as Langfuse, LangSmith or an OpenTelemetry collector import.
"""
import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

# Estimated USD per million tokens (input, output). Used for the cost estimate only.
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-4-5": (3.0, 15.0), "claude-sonnet-4": (3.0, 15.0)}
DEFAULT_PRICE = (1.0, 5.0)
MAX_TRACES = 500


def price_for(model):
    for key, p in PRICES.items():
        if model and model.startswith(key):
            return p
    return DEFAULT_PRICE


class Tracer:
    def __init__(self, store):
        self.s = store
        if not hasattr(store, "traces"):
            store.traces = []
        self.current = None
        self._t0 = None

    # -------------------------------------------------------------- traces
    def start(self, user_id, message, channel="web"):
        self._t0 = time.perf_counter()
        self.current = {"id": uuid.uuid4().hex[:10], "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "user_id": user_id, "channel": channel, "message": (message or "")[:200],
                        "intent": None, "answer_mode": None, "tool_selection": None, "tools": [],
                        "status": "ok", "error": None, "latency_ms": None,
                        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "spans": []}
        return self.current

    def finish(self, intent=None, tools=None, awaiting=None, error=None):
        t = self.current
        if t is None:
            return None
        t["latency_ms"] = round((time.perf_counter() - self._t0) * 1000, 1)
        t["intent"] = intent
        t["tools"] = list(tools or [])
        t["awaiting"] = awaiting
        if error is not None:
            t["status"], t["error"] = "error", str(error)[:300]
        elif any(s["status"] == "error" for s in t["spans"]):
            t["status"] = "degraded"          # something failed but a fallback answered
        self.s.traces.append(t)
        del self.s.traces[:-MAX_TRACES]
        self.current = None
        return t

    def set(self, **fields):
        if self.current is not None:
            self.current.update(fields)

    # --------------------------------------------------------------- spans
    @contextmanager
    def span(self, name, **attrs):
        """with tracer.span("retrieve", query=q) as sp: sp["attrs"]["kb_id"] = ..."""
        sp = {"name": name, "start_ms": None, "ms": None, "status": "ok", "attrs": dict(attrs)}
        start = time.perf_counter()
        if self.current is not None and self._t0 is not None:
            sp["start_ms"] = round((start - self._t0) * 1000, 1)
        try:
            yield sp
        except Exception as e:
            sp["status"] = "error"
            sp["attrs"]["error"] = str(e)[:200]
            raise
        finally:
            sp["ms"] = round((time.perf_counter() - start) * 1000, 1)
            if self.current is not None:
                self.current["spans"].append(sp)

    def add_usage(self, sp, usage, model):
        """Record Claude token usage on a span and add it to the trace totals."""
        if not usage:
            return
        tin, tout = int(usage.get("input_tokens", 0) or 0), int(usage.get("output_tokens", 0) or 0)
        pin, pout = price_for(model)
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        sp["attrs"].update(model=model, tokens_in=tin, tokens_out=tout, cost_usd=round(cost, 6))
        if self.current is not None:
            self.current["tokens_in"] += tin
            self.current["tokens_out"] += tout
            self.current["cost_usd"] = round(self.current["cost_usd"] + cost, 6)


# ------------------------------------------------------------------ reports
def _pct(values, p):
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def summary(traces):
    """Headline numbers for the Observability page."""
    lat = [t["latency_ms"] for t in traces if t.get("latency_ms") is not None]
    spans = [s for t in traces for s in t["spans"]]
    rag = [s for s in spans if s["name"] == "rag_generate"]
    plan = [s for s in spans if s["name"] == "plan_tools"]
    tools = [s for s in spans if s["name"].startswith("tool:")]
    return {
        "requests": len(traces),
        "p50_ms": _pct(lat, 50), "p95_ms": _pct(lat, 95),
        "errors": sum(t["status"] == "error" for t in traces),
        "degraded": sum(t["status"] == "degraded" for t in traces),
        "rag_calls": len(rag), "rag_ok": sum(s["attrs"].get("grounded") is True for s in rag),
        "plan_calls": len(plan), "plan_ok": sum(s["status"] == "ok" and s["attrs"].get("used") is True for s in plan),
        "tool_calls": len(tools), "tool_failures": sum(s["attrs"].get("ok") is False for s in tools),
        "tokens_in": sum(t["tokens_in"] for t in traces), "tokens_out": sum(t["tokens_out"] for t in traces),
        "cost_usd": round(sum(t["cost_usd"] for t in traces), 4),
    }


def span_stats(traces):
    """Per-step latency: [{step, count, avg_ms, p95_ms, errors}]."""
    by = {}
    for t in traces:
        for s in t["spans"]:
            by.setdefault(s["name"], []).append(s)
    rows = []
    for name, ss in sorted(by.items()):
        ms = [s["ms"] for s in ss if s["ms"] is not None]
        rows.append({"step": name, "count": len(ss), "avg_ms": round(sum(ms) / len(ms), 1) if ms else None,
                     "p95_ms": _pct(ms, 95), "errors": sum(s["status"] == "error" for s in ss)})
    return rows


def fallback_reasons(traces):
    """Why Claude's output was not used (RAG grounding failures, API errors, planner fallbacks)."""
    out = {}
    for t in traces:
        for s in t["spans"]:
            reason = s["attrs"].get("fallback_reason")
            if reason:
                key = f"{s['name']}: {reason.split(':')[0][:60]}"
                out[key] = out.get(key, 0) + 1
    return sorted(out.items(), key=lambda kv: -kv[1])


def to_jsonl(traces):
    return "\n".join(json.dumps(t, default=str) for t in traces) + ("\n" if traces else "")

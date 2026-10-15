"""HelpDeskGenie conversational agent: ties retrieval, routing and tools together.

The agent is UI-agnostic: `handle()` takes text and returns an AgentReply, so the
same object can sit behind Streamlit, a Slack bot or a Teams bot (see
AgentReply.render()).
"""
import re
from dataclasses import dataclass, field

from categorizer import TicketCategorizer
from observability import Tracer
from retriever import KBRetriever
from router import route
from tools import ITSMTools

CODE_RE = re.compile(r"\b(\d{6})\b")
YES_RE = re.compile(r"^\s*(y|yes|yeah|yep|sure|ok|okay|please do|yes please|log it|do it|go ahead)\b", re.I)
NO_RE = re.compile(r"^\s*(n|no|nope|cancel|stop|never ?mind|don'?t)\b", re.I)
NOT_FIXED_RE = re.compile(r"\b(still (not|isn'?t|doesn'?t|broken|failing)|didn'?t (work|help|fix)|not fixed|same (issue|problem))\b", re.I)

EXPERT_TERMS = {"dns", "dhcp", "ipconfig", "udp", "tcp", "ipsec", "ost", "kerberos", "subnet", "ssid", "ldap",
                "gpo", "powershell", "cli", "port", "ports", "lease", "tunnel", "proxy", "latency", "packet", "mtu", "cache"}
BEGINNER_TERMS = {"internet", "computer", "confused", "don't know", "dont know", "no idea", "help me", "not sure",
                  "thingy", "the wifi thing", "stopped working", "what do i do"}


@dataclass
class AgentReply:
    text: str
    intent_class: str = "informational"
    sources: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    awaiting: str = None            # "otp" | "clarification" | "ticket_confirm" | None

    def render(self, channel="web"):
        """Slack uses *bold*; Teams and web use **bold**."""
        if channel == "slack":
            return re.sub(r"\*\*(.+?)\*\*", r"*\1*", self.text).replace("### ", "*").replace("\n#", "\n")
        return self.text


class HelpDeskAgent:
    def __init__(self, store, channel="web"):
        self.s = store
        self.channel = channel
        self.tools = ITSMTools(store, channel=channel)
        self.retriever = KBRetriever(store.kb)
        self.categorizer = TicketCategorizer()
        self.external_kb = None          # optional MCPKnowledgeSource (see mcp_client.py)
        self.rag = None                  # optional RAGGenerator (see rag.py); None = quote verified steps
        self.rag_enabled = True
        self.last_mode = None            # "rag" | "extractive", for the UI
        self.planner = None              # optional llm_tools.ToolPlanner: Claude chooses the tools
        self.planner_enabled = True
        self.last_selection = None       # "claude" | "rules", for the UI
        self.tracer = Tracer(store)      # observability: one trace per message (observability.py)
        if not hasattr(store, "conversations"):
            store.conversations = {}

    # --------------------------------------------------------------- helpers
    def _conv(self, user_id):
        return self.s.conversations.setdefault(user_id, {"pending": None, "queue": [], "last_kb": None})

    def tech_level(self, user_id, message="", override="auto"):
        if override in ("beginner", "expert", "standard"):
            return override
        lv = self.s.user_levels.setdefault(user_id, {"expert": 0, "beginner": 0})
        low = message.lower()
        words = set(re.findall(r"[a-z]+", low))
        lv["expert"] += len(words & EXPERT_TERMS)
        lv["beginner"] += sum(1 for t in BEGINNER_TERMS if t in low)
        if lv["expert"] >= 2 and lv["expert"] > lv["beginner"]:
            return "expert"
        if lv["beginner"] >= 1 and lv["beginner"] > lv["expert"]:
            return "beginner"
        return "standard"

    @staticmethod
    def _src(art):
        if art.get("url"):
            return art["url"]
        if art["id"].startswith("JIRA"):
            return f"https://jira.company.internal/browse/{art['id']}"
        return f"https://confluence.company.internal/display/ITKB/{art['id']}"

    def _compose(self, art, level, query, user_id, steps=None, heading_note=""):
        """RAG answer when available and safe, else the verified steps quoted exactly."""
        self.last_mode = "extractive"
        if self.rag is not None and self.rag_enabled and not art.get("critical") and art.get("kind") != "policy":
            from retriever import MIN_SCORE, PAST_TICKET_MIN
            primary = {"id": art["id"], "title": art["title"], "steps": steps or art["steps"]}
            context, by_id = [primary], {art["id"]: art}
            top = self.retriever.search(query, k=6)
            best = next((sc for a, sc in top if a["id"] == art["id"]), 0) or (top[0][1] if top else 0)
            for a, sc in top:
                gate = PAST_TICKET_MIN if a["id"].startswith("JIRA") else MIN_SCORE
                if a["id"] != art["id"] and not a.get("critical") and sc >= gate and sc >= 0.5 * best and len(context) < 3:
                    context.append({"id": a["id"], "title": a["title"], "steps": a["steps"]})
                    by_id[a["id"]] = a
            with self.tracer.span("rag_generate", kb_id=art["id"], context=[c["id"] for c in context]) as sp:
                res = self.rag.generate(query, context, level)
                sp["attrs"].update(grounded=res.ok, cited=res.cited)
                if not res.ok:
                    sp["attrs"]["fallback_reason"] = res.reason
                    if res.reason.startswith("API error"):
                        sp["status"] = "error"
                self.tracer.add_usage(sp, getattr(self.rag, "last_usage", None), self.rag.model)
            if res.ok:
                self.last_mode = "rag"
                links = " · ".join(f"[{i} – {by_id[i]['title']}]({self._src(by_id[i])})" for i in res.sources)
                self.s.audit("RAG_ANSWER", user_id, "SUCCESS", f"Generated from {', '.join(res.cited)}", channel=self.channel,
                             meta={"cited": res.cited, "context": [c["id"] for c in context], "model": self.rag.model})
                text = (f"### ✨ {art['title']}{heading_note}\n{res.text}\n\n🔗 Sources: {links}\n\n"
                        "_Written by Claude from the verified runbooks above; every step was checked against its source._")
                return text, self._src(art), res.sources
            self.s.audit("RAG_FALLBACK", user_id, "INFO", f"Quoted verified steps instead: {res.reason}",
                         channel=self.channel, meta={"context": [c["id"] for c in context]})
        text, src = self._format_article(art, level, steps, heading_note)
        return text, src, [art["id"]]

    def _format_article(self, art, level, steps=None, heading_note=""):
        steps = steps or art["steps"]
        is_ticket = art["id"].startswith("JIRA")
        src = self._src(art)
        kind = "Past resolved ticket" if is_ticket else "KB article"
        source_line = f"\n\n🔗 Source: [{art['id']} – {art['title']}]({src}) ({kind})"
        if level == "expert" and art.get("expert") and not heading_note:
            return f"**{art['title']}**: {art['expert']}{source_line}", src
        body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        out = f"### 📖 {art['title']}{heading_note}\n{body}"
        if level == "beginner" and art.get("tip"):
            out = f"### 📖 {art['title']}{heading_note}\n💡 _{art['tip']}_\n\n{body}"
        return out + source_line, src

    # -------------------------------------------------------------- KB path
    def _answer_info(self, query, user_id, level, conv, can_ask=True):
        with self.tracer.span("retrieve", query=query[:120]) as sp:
            amb = self.retriever.ambiguous(query) if can_ask else None
            hit = None if amb else self.retriever.best(query)
            sp["attrs"].update(ambiguous=bool(amb), kb_id=hit[0]["id"] if hit else None,
                               score=round(hit[1], 3) if hit else None)
        return self._answer_from(query, user_id, level, conv, can_ask, amb, hit)

    def _answer_from(self, query, user_id, level, conv, can_ask, amb, hit):
        if amb:
            a1, a2 = amb
            conv["pending"] = {"type": "disambiguate", "options": [a1["id"], a2["id"]], "query": query}
            self.s.audit("CLARIFY", user_id, "ASKED", f"Ambiguous between {a1['id']} and {a2['id']}", channel=self.channel)
            return (f"I want to make sure I give you the right steps. Is this about **{a1['title']}** (reply 1) "
                    f"or **{a2['title']}** (reply 2)?"), [], "clarification"

        if hit is None:
            self.s.audit("ABSTAIN", user_id, "NO_KB_MATCH", f"No verified runbook for: {query[:80]}", channel=self.channel)
            self.s.interactions.append({"user_id": user_id, "query": query, "kb_id": None, "outcome": "abstained"})
            if not can_ask:
                return ("I don't have a verified runbook for that part, so I won't guess at a fix; "
                        "the engineer on your ticket will follow up."), [], None
            conv["pending"] = {"type": "ticket_confirm", "query": query}
            external = self._external_answer(query, user_id)
            if external:
                return external + "\n\nIf that doesn't cover it, shall I **log a ticket**? (yes / no)", [], "ticket_confirm"
            return ("I don't have a verified runbook for that, and I won't guess at fixes for company systems. "
                    "Would you like me to **log a ticket** so an engineer can help? (yes / no)"), [], "ticket_confirm"

        art, score = hit
        clar = art.get("clarify")
        if clar:
            variant = self._match_variant(clar, query)
            if variant is None and can_ask:
                conv["pending"] = {"type": "clarify_variant", "kb_id": art["id"], "query": query}
                self.s.audit("CLARIFY", user_id, "ASKED", f"{art['id']}: {clar['question']}", channel=self.channel)
                return f"Happy to help with that. {clar['question']}", [], "clarification"
            if variant:
                text, src, used = self._compose(art, level, query, user_id, clar["variants"][variant]["steps"], f" ({variant})")
            else:
                text, src, used = self._compose(art, level, query, user_id)
        else:
            text, src, used = self._compose(art, level, query, user_id)
        past = self.retriever.related_past_fix(query, exclude_id=art["id"]) if not art["id"].startswith("JIRA") else None
        if past and past["id"] not in used:
            text += (f"\n\n🗂️ **Related past fix** ([{past['id']}](https://jira.company.internal/browse/{past['id']})): "
                     f"{past['steps'][0]}")
        conv["last_kb"] = {"kb_id": art["id"], "query": query, "category": art["category"]}
        self.s.audit("KB_ANSWER", user_id, "SUCCESS", f"Answered from {art['id']} (score {score:.2f}, style {level})",
                     channel=self.channel, meta={"kb_id": art["id"], "score": round(score, 3)})
        self.s.interactions.append({"user_id": user_id, "query": query, "kb_id": art["id"], "outcome": "kb_answer"})
        if art.get("kind") != "policy":
            text += "\n\n_Still not working? Just say so and I'll log a ticket._"
        return text, [src], None

    def _external_answer(self, query, user_id):
        """Quote (never rewrite) results from an external knowledge base reached over MCP."""
        if self.external_kb is None:
            return None
        results = self.external_kb.search(query, user_id=user_id)
        if not results:
            return None
        lines = [f"I don't have a verified runbook for that, but I found this in **{self.external_kb.cfg.name}** "
                 "(quoted as-is; it has not been reviewed by the service desk):"]
        for r in results:
            title = r["title"] or "Result"
            head = f"[{title}]({r['url']})" if r["url"] else f"**{title}**"
            quote = "\n".join("> " + ln for ln in r["excerpt"].splitlines() if ln.strip())
            lines.append(f"{head}\n{quote}")
        self.s.audit("KB_EXTERNAL", user_id, "SUCCESS", f"{len(results)} result(s) from {self.external_kb.label}",
                     channel=self.channel)
        return "\n\n".join(lines)

    @staticmethod
    def _match_variant(clar, text):
        low = text.lower()
        for name, v in clar["variants"].items():
            if any(re.search(rf"\b{re.escape(w)}\b", low) for w in v["match"]):
                return name
        return None

    # ---------------------------------------------------------- tool path
    def _run_action(self, action, user_id, route_flags):
        tool, args = action["tool"], action["args"]
        if tool in ("unlock_account", "reset_password"):
            op = tool.upper()
            if "third_party_target" in route_flags:
                self.s.audit(op, user_id, "REJECTED", "Request targeted another user's account", channel=self.channel)
                self.s.secops_alert(user_id, op, "Self-service request tried to act on a different user's account.")
                return ("❌ I can only unlock or reset **your own** account after verifying you. "
                        "If a colleague is locked out, they need to contact me themselves or call the service desk."), None
            with self.tracer.span("tool:start_verification", action=op) as sp:
                res = self.tools.start_verification(user_id, op)
                sp["attrs"]["ok"] = bool(res)
            if not res:
                return res["message"], None
            self._conv(user_id)["pending"] = {"type": "otp", "challenge_id": res["challenge_id"], "tool": tool}
            return res["message"], "otp"
        fn = getattr(self.tools, tool)
        with self.tracer.span(f"tool:{tool}", args={k: str(v)[:60] for k, v in args.items()}) as sp:
            res = fn(user_id, **args)
            sp["attrs"]["ok"] = bool(res)
        return res["message"], None

    def _complete_otp(self, message, user_id, conv):
        p = conv["pending"]
        code = CODE_RE.search(message).group(1)
        with self.tracer.span("verify_otp", action=p["tool"]) as sp:
            res = self.tools.verify_otp(user_id, p["challenge_id"], code)
            sp["attrs"]["ok"] = bool(res)
        if not res:
            if not res.get("retry"):
                conv["pending"] = None
            return AgentReply(res["message"], "actionable", awaiting="otp" if res.get("retry") else None)
        conv["pending"] = None
        with self.tracer.span(f"tool:{p['tool']}", verified=True) as sp:
            out = getattr(self.tools, p["tool"])(user_id, verification_token=res["token"])
            sp["attrs"]["ok"] = bool(out)
        self.s.interactions.append({"user_id": user_id, "query": p["tool"], "kb_id": None,
                                    "outcome": "auto_remediated" if out else "remediation_failed"})
        return AgentReply(out["message"], "actionable", actions=[p["tool"]])

    # ------------------------------------------------------------- main
    def handle(self, message, user_id, style="auto"):
        """Answer one message. Every call is traced (see observability.py)."""
        self.tracer.start(user_id, message, self.channel)
        self.last_mode, self.last_selection = None, None
        try:
            reply = self._handle(message, user_id, style)
        except Exception as e:
            self.tracer.finish(error=e)
            raise
        self.tracer.set(answer_mode=self.last_mode, tool_selection=self.last_selection)
        self.tracer.finish(reply.intent_class, reply.actions, reply.awaiting)
        return reply

    def _plan_tools(self, message, user_id, r):
        """Let Claude choose the tools (tool calling). Falls back to the rule router's plan."""
        if self.planner is None or not self.planner_enabled or r.intent_class == "greeting":
            self.last_selection = "rules"
            return r
        with self.tracer.span("plan_tools", model=self.planner.model) as sp:
            plan = self.planner.plan(message, self.categorizer)
            self.tracer.add_usage(sp, plan.usage, self.planner.model)
            sp["attrs"].update(used=plan.ok, claude_calls=plan.raw_calls,
                               rules_chose=[a["tool"] for a in r.actions])
            if not plan.ok:
                sp["attrs"]["fallback_reason"] = plan.reason
                if plan.reason.startswith("API error"):
                    sp["status"] = "error"
        if not plan.ok:
            self.last_selection = "rules"
            self.s.audit("TOOL_PLAN", user_id, "FALLBACK", f"Rule router used: {plan.reason}", channel=self.channel)
            return r
        self.last_selection = "claude"
        self.s.audit("TOOL_PLAN", user_id, "SUCCESS",
                     f"Claude chose {[a['tool'] for a in plan.actions] + (['search_knowledge_base'] if plan.info_query else [])}",
                     channel=self.channel, meta={"calls": plan.raw_calls, "model": self.planner.model})
        actions, info = plan.actions, plan.info_query
        if any(a["tool"] == "grant_access_request" for a in actions):
            cls = "needs_approval"
        elif actions and info:
            cls = "mixed"
        elif actions:
            cls = "actionable"
        else:
            cls = "informational"
        r.intent_class, r.actions, r.info_query = cls, actions, info   # security flags from the rules are kept
        return r

    def _handle(self, message, user_id, style="auto"):
        message = (message or "").strip()
        conv = self._conv(user_id)
        level = self.tech_level(user_id, message, style)
        pending = conv.get("pending")

        # 1. Answers to something we asked
        if pending:
            if pending["type"] == "otp" and CODE_RE.search(message):
                return self._complete_otp(message, user_id, conv)
            if pending["type"] == "otp" and NO_RE.search(message):
                conv["pending"] = None
                self.s.audit("VERIFY_OTP", user_id, "CANCELLED", "User cancelled verification", channel=self.channel)
                return AgentReply("Okay, I've cancelled that request. Nothing on your account was changed.", "actionable")
            if pending["type"] == "ticket_confirm":
                if YES_RE.search(message):
                    conv["pending"] = None
                    cat, _ = self.categorizer.predict(pending["query"])
                    with self.tracer.span("tool:create_ticket", issue_type=cat) as sp:
                        res = self.tools.create_ticket(user_id, cat, pending["query"])
                        sp["attrs"]["ok"] = bool(res)
                    self.s.interactions.append({"user_id": user_id, "query": pending["query"], "kb_id": None, "outcome": "ticket"})
                    return AgentReply(res["message"] + " An engineer will pick it up; you can ask me for its status any time.",
                                      "actionable", actions=["create_ticket"])
                if NO_RE.search(message):
                    conv["pending"] = None
                    return AgentReply("No problem. Let me know if there's anything else.", "informational")
            if pending["type"] == "clarify_variant":
                art = next(a for a in self.s.kb if a["id"] == pending["kb_id"])
                variant = self._match_variant(art["clarify"], message)
                if variant:
                    conv["pending"] = None
                    text, src, _ = self._compose(art, level, pending["query"] + f" ({variant})", user_id,
                                                 art["clarify"]["variants"][variant]["steps"], f" ({variant})")
                    conv["last_kb"] = {"kb_id": art["id"], "query": pending["query"], "category": art["category"]}
                    self.s.audit("KB_ANSWER", user_id, "SUCCESS", f"Answered from {art['id']} variant '{variant}'",
                                 channel=self.channel, meta={"kb_id": art["id"]})
                    self.s.interactions.append({"user_id": user_id, "query": pending["query"], "kb_id": art["id"], "outcome": "kb_answer"})
                    return AgentReply(text + "\n\n_Still not working? Just say so and I'll log a ticket._", "informational", [src])
            if pending["type"] == "disambiguate" and message.strip() in ("1", "2"):
                conv["pending"] = None
                kb_id = pending["options"][int(message.strip()) - 1]
                art = next(a for a in self.s.kb if a["id"] == kb_id)
                text, src, _ = self._compose(art, level, pending["query"], user_id)
                conv["last_kb"] = {"kb_id": art["id"], "query": pending["query"], "category": art["category"]}
                self.s.audit("KB_ANSWER", user_id, "SUCCESS", f"Answered from {kb_id} after disambiguation", channel=self.channel)
                self.s.interactions.append({"user_id": user_id, "query": pending["query"], "kb_id": kb_id, "outcome": "kb_answer"})
                return AgentReply(text, "informational", [src])
            if pending["type"] != "otp":
                conv["pending"] = None      # user moved on; drop the question

        # 2. "Still not working" after a KB answer -> offer escalation to a human
        if NOT_FIXED_RE.search(message) and conv.get("last_kb"):
            last = conv["last_kb"]
            conv["pending"] = {"type": "ticket_confirm",
                               "query": f"{last['query']} (self-help {last['kb_id']} tried, not resolved)"}
            return AgentReply("Sorry that didn't fix it. Shall I **log a ticket** with what you've already tried? (yes / no)",
                              "informational", awaiting="ticket_confirm")

        if not message:
            return AgentReply("Please type your question.", "informational")

        # 3. Route
        with self.tracer.span("route") as sp:
            r = route(message, user_id, self.retriever, self.categorizer)
            sp["attrs"].update(intent=r.intent_class, tools=[a["tool"] for a in r.actions], flags=r.flags)
        r = self._plan_tools(message, user_id, r)
        self.s.audit("ROUTE", user_id, "INFO", f"{r.intent_class}: tools={[a['tool'] for a in r.actions]} flags={r.flags}",
                     channel=self.channel, meta={"message": message[:200]})
        if r.intent_class == "greeting":
            return AgentReply("Hello! I'm HelpDeskGenie. I can troubleshoot network, email and device issues, "
                              "unlock your account or reset your password (with verification), and log or track tickets.",
                              "greeting")
        if "override_attempt" in r.flags:
            self.s.secops_alert(user_id, "POLICY_BYPASS_ATTEMPT", f"Message asked to bypass controls: \"{message[:160]}\"", severity="MEDIUM")

        parts, sources, done, awaiting = [], [], [], None
        if "override_attempt" in r.flags:
            parts.append("⚠️ I can't skip identity checks or security controls for anyone; this request has been logged.")
        for i, action in enumerate(r.actions):
            if awaiting == "otp" and action["tool"] in ("unlock_account", "reset_password"):
                parts.append(f"Once that's done, ask me again to {action['tool'].replace('_', ' ')}.")
                continue
            text, aw = self._run_action(action, user_id, r.flags)
            parts.append(text)
            done.append(action["tool"])
            awaiting = aw or awaiting
            if action["tool"] == "create_ticket":
                self.s.interactions.append({"user_id": user_id, "query": message, "kb_id": None, "outcome": "ticket"})
        if r.info_query:
            # With actions already taken (or an OTP pending) we don't open a second question.
            text, src, aw = self._answer_info(r.info_query, user_id, level, conv, can_ask=not r.actions)
            if text:
                parts.append(("**Meanwhile, here's what usually fixes it:**\n" if r.actions else "") + text)
            sources += src
            awaiting = awaiting or aw
        return AgentReply("\n\n".join(parts), r.intent_class, sources, done, awaiting)

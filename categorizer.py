"""Ticket categorisation (Iteration 3, "compare prompts/models").

`HISTORICAL_TICKETS` stands in for an export of resolved JIRA tickets with the
labels L1 agents assigned. Replace it with a real export (CSV with
`description,category`) via load_history_csv() to benchmark on your own data.

Several categorisers are compared against those labels:
  * baseline_rules   - the rule from the original app.py (vpn/wi-fi -> Networking, else Applications)
  * keyword_rules    - a hand-written keyword lexicon per category
  * kb_nearest       - category of the closest KB article (re-uses the RAG retriever)
  * tfidf_logreg     - TF-IDF + logistic regression trained on historical labels
  * llm_prompt_a/b   - optional: Claude with two different prompts (needs ANTHROPIC_API_KEY)
"""
import csv
import os
import random

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline

CATEGORIES = ["Networking", "Storage", "Applications", "Identity", "Hardware", "Access"]

_POOLS = {
    "Networking": ["vpn keeps disconnecting", "cannot connect to vpn from home", "wifi drops every few minutes",
                   "corp-secure wifi authentication failed", "no internet on docking station ethernet",
                   "vpn tunnel times out", "internal sites not loading dns error", "globalprotect stuck connecting",
                   "slow network in the office", "cannot reach intranet over vpn", "wireless not connecting on floor 4",
                   "ip address conflict on laptop"],
    "Storage": ["cannot map network drive", "shared drive missing after update", "access denied on shared folder",
                "department share not showing", "onedrive not syncing files", "file server very slow to open files",
                "mapped drive shows red x", "cannot save to shared folder", "restore deleted file from share",
                "sharepoint library not syncing", "network folder permission denied", "drive letter disappeared"],
    "Applications": ["outlook not syncing emails", "teams microphone not working", "excel crashes on open",
                     "outlook stuck updating inbox", "need adobe acrobat installed", "teams calls drop audio",
                     "calendar invites not arriving", "zoom plugin missing in outlook", "chrome keeps crashing",
                     "software install request for visio", "sap gui error on login screen", "teams camera not detected"],
    "Identity": ["account locked out", "forgot my password", "password expired cannot sign in",
                 "mfa prompt not arriving on phone", "new phone need to move authenticator", "reset my password please",
                 "locked out after too many attempts", "sso login loop", "cannot sign in to windows",
                 "authenticator app lost", "password reset link expired", "account disabled after leave"],
    "Hardware": ["printer not printing", "laptop screen flickering", "keyboard keys not working",
                 "docking station not detecting monitor", "laptop battery drains fast", "printer paper jam 3rd floor",
                 "mouse not working", "laptop will not turn on", "second monitor no signal",
                 "headset broken need replacement", "laptop overheating fan loud", "webcam hardware not detected"],
    "Access": ["need access to finance share", "request access to salesforce", "please grant github repo access",
               "need admin rights to install tools", "access to production database for reporting",
               "add me to hr share security group", "need tableau license and access", "jira project access for new joiner",
               "aws console access request", "permission to view payroll folder", "need access to confluence space",
               "read access to data warehouse"],
}
_PREFIX = ["", "hi, ", "urgent: ", "hello team ", "since this morning ", "again - "]
_SUFFIX = ["", " please help", " asap", " since yesterday", " for my new laptop", " thanks"]

# Genuinely ambiguous / noisy tickets, labelled as the L1 agent actually filed them.
_HARD = [
    ("cant open finance share over vpn from home", "Storage"),
    ("outlook says disconnected when on hotel wifi", "Applications"),
    ("locked out of vpn after password change", "Identity"),
    ("teams keeps saying no network", "Applications"),
    ("printer asks for my password every time", "Hardware"),
    ("need access to shared drive for new project", "Access"),
    ("shared drive access denied after moving team", "Storage"),
    ("wifi login rejects my password", "Networking"),
    ("laptop cannot find wifi networks at all", "Hardware"),
    ("need software installed that is not in company portal", "Applications"),
    ("cannot sign in to salesforce sso error", "Identity"),
    ("github says permission denied on push", "Access"),
    ("onedrive red cross on all files", "Storage"),
    ("vpn works but mapped drives do not", "Storage"),
    ("mfa code not accepted on vpn", "Identity"),
    ("screen goes black during teams screenshare", "Hardware"),
]


def _generate_history(seed=7):
    rng = random.Random(seed)
    rows = []
    for cat, pool in _POOLS.items():
        for phrase in pool:
            for _ in range(2):
                rows.append((rng.choice(_PREFIX) + phrase + rng.choice(_SUFFIX), cat))
    rows += _HARD * 2
    rng.shuffle(rows)
    return rows


HISTORICAL_TICKETS = _generate_history()


def load_history_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [(r["description"], r["category"]) for r in csv.DictReader(f)]


# ---------------------------------------------------------------- models
def baseline_rules(text):
    t = text.lower()
    return "Networking" if ("vpn" in t or "wi-fi" in t) else "Applications"


_LEXICON = {
    "Access": ["access to", "grant", "permission to", "admin rights", "license and access", "security group", "access request", "read access"],
    "Identity": ["password", "locked", "lock out", "mfa", "authenticator", "sign in", "sso", "account disabled", "login loop"],
    "Networking": ["vpn", "wifi", "wi-fi", "wireless", "internet", "dns", "network", "ethernet", "ip address", "intranet"],
    "Storage": ["drive", "share", "shared folder", "onedrive", "sharepoint", "file server", "folder"],
    "Hardware": ["printer", "laptop", "keyboard", "mouse", "monitor", "screen", "battery", "dock", "headset", "webcam", "fan"],
    "Applications": ["outlook", "teams", "excel", "email", "calendar", "install", "software", "chrome", "zoom", "sap", "adobe", "visio"],
}


def keyword_rules(text):
    t = text.lower()
    scores = {c: sum(1 for k in kws if k in t) for c, kws in _LEXICON.items()}
    best = max(scores, key=lambda c: (scores[c], -CATEGORIES.index(c)))
    return best if scores[best] > 0 else "Applications"


def make_kb_nearest(retriever):
    def kb_nearest(text):
        hit = retriever.best(text)
        return hit[0]["category"] if hit else "Applications"
    return kb_nearest


def _logreg():
    return make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1),
        LogisticRegression(max_iter=2000, C=5.0),
    )


class TicketCategorizer:
    """Production categoriser: TF-IDF + LR, falls back to keyword rules when unsure."""

    def __init__(self, history=None, min_confidence=0.35):
        history = history or HISTORICAL_TICKETS
        self.model = _logreg().fit([h[0] for h in history], [h[1] for h in history])
        self.min_confidence = min_confidence

    def predict(self, text):
        proba = self.model.predict_proba([text])[0]
        i = int(np.argmax(proba))
        if proba[i] < self.min_confidence:
            return keyword_rules(text), float(proba[i])
        return self.model.classes_[i], float(proba[i])


# --------------------------------------------------------- optional LLM
_PROMPT_A = "Classify this IT ticket into exactly one category: {cats}.\nTicket: {text}\nAnswer with the category only."
_PROMPT_B = ("You are an L1 service-desk triage agent. Categories:\n"
             "- Networking: VPN, Wi-Fi, connectivity, DNS\n- Storage: drives, shares, OneDrive, file servers\n"
             "- Applications: email, Teams, software issues or installs\n- Identity: passwords, lockouts, MFA, sign-in\n"
             "- Hardware: physical devices\n- Access: requests for new permissions or access\n"
             "Pick the team that would fix the root cause.\nTicket: {text}\nReply with one category name only.")


def make_llm_classifier(prompt, model="claude-haiku-4-5-20251001"):
    """Returns a classifier function, or None when no API key / SDK is available."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()

    def classify(text):
        msg = client.messages.create(model=model, max_tokens=10,
                                     messages=[{"role": "user", "content": prompt.format(cats=", ".join(CATEGORIES), text=text)}])
        out = msg.content[0].text.strip()
        return next((c for c in CATEGORIES if c.lower() in out.lower()), "Applications")
    return classify


# ------------------------------------------------------------ benchmark
def compare_categorizers(retriever, history=None, folds=5, include_llm=True):
    """Accuracy + macro-F1 of each approach against historical labels."""
    history = history or HISTORICAL_TICKETS
    X = np.array([h[0] for h in history])
    y = np.array([h[1] for h in history])
    results, predictions = [], {}

    rule_based = {"baseline_rules (v1)": baseline_rules, "keyword_rules": keyword_rules,
                  "kb_nearest_article": make_kb_nearest(retriever)}
    if include_llm:
        for name, prompt in (("llm_prompt_a (terse)", _PROMPT_A), ("llm_prompt_b (triage)", _PROMPT_B)):
            fn = make_llm_classifier(prompt)
            if fn:
                rule_based[name] = fn
    for name, fn in rule_based.items():
        pred = np.array([fn(x) for x in X])
        predictions[name] = pred
        results.append({"model": name, "accuracy": accuracy_score(y, pred),
                        "macro_f1": f1_score(y, pred, average="macro", zero_division=0), "evaluation": "full history"})

    # Learned model: stratified k-fold so it is never scored on its training data.
    pred = np.empty(len(y), dtype=object)
    for train, test in StratifiedKFold(n_splits=folds, shuffle=True, random_state=0).split(X, y):
        pred[test] = _logreg().fit(X[train], y[train]).predict(X[test])
    predictions["tfidf_logreg"] = pred
    results.append({"model": "tfidf_logreg", "accuracy": accuracy_score(y, pred),
                    "macro_f1": f1_score(y, pred, average="macro", zero_division=0), "evaluation": f"{folds}-fold CV"})

    failures = []
    best = max(results, key=lambda r: r["macro_f1"])["model"]
    for text, true, p in zip(X, y, predictions[best]):
        if p != true:
            failures.append({"model": best, "ticket": text, "expected": true, "predicted": p})
    return sorted(results, key=lambda r: -r["macro_f1"]), failures

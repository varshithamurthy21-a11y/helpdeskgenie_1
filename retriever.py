"""TF-IDF + cosine-similarity retrieval over the knowledge base (Iteration 1).

The retriever only ranks articles. It never writes text. The agent then quotes
the chosen article's steps verbatim, which keeps answers grounded.
"""
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Normalise a few spellings so "wi-fi", "wifi" and "wireless" land on the same terms.
_NORMALISE = [
    (r"\bwi[\s-]?fi\b", "wifi"),
    (r"\be-?mails?\b", "email"),
    (r"\bmic\b", "microphone"),
    (r"\bpwd\b|\bpassword?s\b", "password"),
    (r"\bsync(ing|ed|s)?\b", "sync"),
    (r"\bdisconnect(s|ed|ing)?\b", "disconnect"),
    (r"\bdrop(s|ped|ping)?\b", "drop"),
]

MIN_SCORE = 0.15          # below this the agent abstains instead of guessing
AMBIGUITY_RATIO = 0.70    # 2nd-best article within 70% of best -> ask which one


def normalise(text):
    text = text.lower()
    for pattern, repl in _NORMALISE:
        text = re.sub(pattern, repl, text)
    return text


class KBRetriever:
    def __init__(self, articles):
        self.articles = articles
        corpus = [
            normalise(" ".join([a["title"], a["title"], a.get("tags", ""), " ".join(a["steps"])]))
            for a in articles
        ]
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(corpus)

    def search(self, query, k=3):
        """Return [(article, score), ...] best first."""
        if not query.strip():
            return []
        q = self.vectorizer.transform([normalise(query)])
        scores = cosine_similarity(q, self.matrix).flatten()
        order = np.argsort(-scores)[:k]
        return [(self.articles[i], float(scores[i])) for i in order]

    def best(self, query):
        """Best article above the confidence gate, or None (abstain).
        Canonical KB articles win over past-ticket summaries; a summary is only
        used on its own when no KB article clears the gate."""
        hits = self.search(query, k=len(self.articles))
        kb = [h for h in hits if not h[0]["id"].startswith("JIRA") and h[1] >= MIN_SCORE]
        if kb:
            return kb[0]
        return hits[0] if hits and hits[0][1] >= MIN_SCORE else None

    def related_past_fix(self, query, exclude_id=None):
        """A resolved-ticket summary relevant to the query, shown as 'related'."""
        for art, score in self.search(query, k=len(self.articles)):
            if art["id"].startswith("JIRA") and art["id"] != exclude_id and score >= MIN_SCORE:
                return art
        return None

    def ambiguous(self, query):
        """If the top two KB articles are near-tied,
        return both so the agent can ask which one the user meant."""
        hits = [h for h in self.search(query, k=len(self.articles)) if not h[0]["id"].startswith("JIRA")][:2]
        if len(hits) < 2:
            return None
        (a1, s1), (a2, s2) = hits
        if s1 >= MIN_SCORE and s2 >= MIN_SCORE and s2 / s1 >= AMBIGUITY_RATIO:
            return a1, a2
        return None

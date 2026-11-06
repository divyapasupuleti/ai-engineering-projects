"""Three ways to adapt a model: prompt-only, retrieval (RAG / few-shot), and trained weights (fine-tune stand-in)."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from common.embeddings import cosine, embed
from common.text import content_tokens

GENERIC_LABEL_HINTS = {
    "billing": ["invoice", "charge", "charged", "refund", "vat", "receipt", "card"],
    "identity": ["login", "log", "password", "sso", "okta", "2fa", "sign"],
    "platform_sync": ["sync", "syncing", "folders", "files", "desktop"],
    "data_export": ["export", "csv", "parquet", "download"],
    "api": ["api", "429", "webhook", "endpoint", "token", "pagination"],
    "mobile": ["ios", "android", "iphone", "mobile", "app", "tablet"],
    "security": ["compromised", "vulnerability", "soc", "suspicious", "pen", "audit"],
    "account_admin": ["seats", "ownership", "downgrade", "user", "contact", "merge", "plan"],
}


class PromptOnly:
    """Base model + label names/descriptions in the prompt. Knows generic words, not company jargon."""

    prompt_tokens = 220

    def predict(self, text: str) -> str:
        toks = set(content_tokens(text)) | set(text.lower().split())
        scores = {k: sum(w in toks for w in hints) for k, hints in GENERIC_LABEL_HINTS.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "account_admin"


class RetrievalFewShot:
    """RAG over labelled examples: top-k similar tickets go into the prompt; the model follows the majority."""

    def __init__(self, train: list[tuple[str, str]], k: int = 5) -> None:
        self.k = k
        self.index = [(embed(t), y) for t, y in train]
        self.prompt_tokens = 220 + 40 * k

    def predict(self, text: str) -> str:
        q = embed(text)
        top = sorted(self.index, key=lambda e: -cosine(q, e[0]))[: self.k]
        votes = Counter()
        for vec, y in top:
            votes[y] += cosine(q, vec)
        return votes.most_common(1)[0][0]


class FineTuned:
    """Multinomial naive Bayes on word + bigram features: a cheap, honest stand-in for a LoRA fine-tune.

    Like a fine-tune it learns the label conventions into weights, needs no examples in the prompt,
    and must be retrained when the labels or facts change.
    """

    prompt_tokens = 40

    def __init__(self, train: list[tuple[str, str]], alpha: float = 0.5) -> None:
        self.alpha = alpha
        self.class_counts = Counter(y for _, y in train)
        self.word_counts: dict[str, Counter] = defaultdict(Counter)
        self.vocab: set[str] = set()
        for t, y in train:
            feats = self.features(t)
            self.word_counts[y].update(feats)
            self.vocab.update(feats)
        self.totals = {y: sum(c.values()) for y, c in self.word_counts.items()}
        self.n = len(train)

    @staticmethod
    def features(text: str) -> list[str]:
        toks = [t for t in text.lower().replace(",", " ").split() if t]
        return toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]

    def predict(self, text: str) -> str:
        feats = self.features(text)
        v = len(self.vocab) + 1
        best, best_lp = None, -math.inf
        for y, cnt in self.class_counts.items():
            lp = math.log(cnt / self.n)
            wc, tot = self.word_counts[y], self.totals[y]
            for f in feats:
                lp += math.log((wc.get(f, 0) + self.alpha) / (tot + self.alpha * v))
            if lp > best_lp:
                best, best_lp = y, lp
        return best


# ---------------------------------------------------------------- knowledge task


class KnowledgeRAG:
    """Retrieves the current KB entry at query time, so fact updates apply immediately."""

    prompt_tokens = 420

    def __init__(self, docs: list[tuple[str, str]]) -> None:
        self.docs = [(k, text, embed(text)) for k, text in docs]

    def answer(self, question: str) -> str:
        q = embed(question)
        _, text, _ = max(self.docs, key=lambda d: cosine(q, d[2]))
        return text.split("Answer: ", 1)[1].rstrip(".")


class KnowledgeFineTuned:
    """Facts memorised into weights at training time; answers stay frozen until the next training run."""

    prompt_tokens = 40

    def __init__(self, train_questions: list[tuple[str, str]], facts_at_training: dict[str, str]) -> None:
        self.memory = [(embed(q), facts_at_training[k]) for q, k in train_questions]

    def answer(self, question: str) -> str:
        q = embed(question)
        return max(self.memory, key=lambda m: cosine(q, m[0]))[1]


class KnowledgePromptOnly:
    prompt_tokens = 60

    def answer(self, question: str) -> str:
        return "I don't have that information"

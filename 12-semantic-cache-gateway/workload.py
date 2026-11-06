"""Seeded request stream with ground-truth answer ids, so every cache hit can be scored right or wrong."""

from __future__ import annotations

import random
from dataclasses import dataclass

GENERIC = {
    "reset_password": ["How do I reset my password?", "how can i reset my password", "I forgot my password, how do I reset it?",
                       "password reset steps", "reset password how"],
    "refund_policy": ["What is your refund policy?", "what's the refund policy", "Can I get a refund? What is the policy?",
                      "refund policy please", "explain the refund policy"],
    "sso": ["Which plan includes SSO?", "which plan has SSO", "Is SSO included on every plan?", "SSO which plan",
            "what plan do I need for SSO"],
    "export": ["How do I export my data?", "how to export my data", "export my workspace data how", "How can I export data?",
               "steps to export data"],
    "api_limits": ["What is the API rate limit?", "what's the api rate limit", "API rate limit per minute?",
                   "rate limit for the API", "how many API requests per minute are allowed"],
}
PRICING = ["How much does the {plan} plan cost?", "what does the {plan} plan cost", "{plan} plan price",
           "price of the {plan} plan", "How much is the {plan} plan per user?"]
PLANS = ["starter", "pro", "enterprise"]
ACCOUNT = ["How many seats does our account have?", "how many seats do we have on our account",
           "our account seats count", "What is our seat count on our account?"]
INVOICE = ["Show my invoice for {month}", "my invoice for {month}", "Can I see my invoice from {month}?"]
MONTHS = ["august", "september", "october"]
ORDERS = ["What is the status of order {n}?", "order {n} status right now", "where is order {n}"]
NEGATED = ["I do not want to reset my password, how do I keep it?"]
TENANTS = {"acme": ["ana", "ben", "cara"], "globex": ["dev", "eli"], "initech": ["fay", "gus", "hal"]}
PREFIXES = ["hi, ", "hello! ", "quick question: ", "hey - ", "sorry to bother, "]
SUFFIXES = [" thanks", " please", " thx", "??", " asap", " - urgent"]


def vary(prompt: str, rng: random.Random) -> str:
    """Real traffic: greetings, sign-offs and the odd typo defeat exact matching."""
    if rng.random() < 0.45:
        prompt = rng.choice(PREFIXES) + prompt
    if rng.random() < 0.45:
        prompt = prompt + rng.choice(SUFFIXES)
    if rng.random() < 0.15 and len(prompt) > 12:
        k = rng.randrange(4, len(prompt) - 2)
        prompt = prompt[:k] + prompt[k + 1] + prompt[k] + prompt[k + 2:]
    return prompt


@dataclass
class Request:
    t: float
    tenant: str
    user: str
    prompt: str
    answer_id: str


def generate(n: int = 2000, seed: int = 8, pricing_change_at: int = 1000) -> list[Request]:
    rng = random.Random(seed)
    out = []
    t = 0.0
    for i in range(n):
        t += rng.expovariate(1 / 45)
        tenant = rng.choice(list(TENANTS))
        user = rng.choice(TENANTS[tenant])
        price_version = "v2" if i >= pricing_change_at else "v1"
        r = rng.random()
        if r < 0.55:
            intent = rng.choice(list(GENERIC))
            prompt, aid = rng.choice(GENERIC[intent]), intent
        elif r < 0.72:
            plan = rng.choice(PLANS)
            prompt, aid = rng.choice(PRICING).format(plan=plan), f"price:{plan}:{price_version}"
        elif r < 0.82:
            prompt, aid = rng.choice(ACCOUNT), f"seats:{tenant}"
        elif r < 0.9:
            month = rng.choice(MONTHS)
            prompt, aid = rng.choice(INVOICE).format(month=month), f"invoice:{tenant}:{month}"
        elif r < 0.98:
            n_ = rng.choice([4411, 4412, 9902, 7310])
            prompt, aid = rng.choice(ORDERS).format(n=n_), f"order:{n_}:{i}"
        else:
            prompt, aid = NEGATED[0], "keep_password"
        out.append(Request(round(t, 1), tenant, user, vary(prompt, rng), aid))
    return out

"""Lightweight lexicon-based sentiment analysis.

A dependency-free sentiment scorer for crypto news/social text. It is not a deep
NLP model — by design it is fast, transparent and runs anywhere — using a curated
crypto-aware lexicon with negation handling and intensity weighting. Scores range
from -1 (very bearish) to +1 (very bullish).

Sentiment is advisory context only: like every AI signal, anything derived from
it must pass the risk engine before affecting orders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Curated crypto/markets sentiment lexicon (term -> polarity in [-1, 1]).
_POSITIVE = {
    "bullish": 0.9, "moon": 0.8, "rally": 0.7, "surge": 0.7, "breakout": 0.6,
    "pump": 0.6, "gain": 0.5, "gains": 0.5, "up": 0.3, "rise": 0.5, "rising": 0.5,
    "adoption": 0.6, "partnership": 0.5, "upgrade": 0.5, "support": 0.4, "buy": 0.5,
    "long": 0.4, "strong": 0.5, "growth": 0.5, "win": 0.5, "approved": 0.6,
    "soar": 0.8, "outperform": 0.6, "accumulate": 0.5,
}
_NEGATIVE = {
    "bearish": -0.9, "crash": -0.9, "dump": -0.7, "plunge": -0.8, "selloff": -0.7,
    "sell": -0.5, "short": -0.4, "drop": -0.5, "fall": -0.5, "falling": -0.5,
    "down": -0.3, "weak": -0.5, "loss": -0.5, "losses": -0.5, "hack": -0.9,
    "ban": -0.7, "lawsuit": -0.6, "fraud": -0.9, "scam": -0.9, "fear": -0.6,
    "fud": -0.6, "liquidation": -0.7, "collapse": -0.9, "decline": -0.5,
    "rejected": -0.6, "warning": -0.5, "risk": -0.3,
}
_INTENSIFIERS = {"very": 1.5, "extremely": 1.8, "massive": 1.6, "huge": 1.5, "slightly": 0.5}
_NEGATIONS = {"not", "no", "never", "without", "isn't", "wasn't", "won't", "don't"}

_TOKEN_RE = re.compile(r"[a-z']+")


@dataclass(slots=True)
class SentimentResult:
    """A sentiment score with supporting detail."""

    score: float  # -1..1
    label: str  # "bullish" | "neutral" | "bearish"
    positive_hits: int
    negative_hits: int
    tokens: int


class SentimentAnalyzer:
    """Lexicon-based sentiment scorer with negation and intensity handling."""

    def __init__(self, *, neutral_band: float = 0.05) -> None:
        self._neutral_band = neutral_band

    def analyze(self, text: str) -> SentimentResult:
        """Score a single piece of *text*."""
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return SentimentResult(0.0, "neutral", 0, 0, 0)
        total = 0.0
        weight_sum = 0.0
        pos_hits = neg_hits = 0
        for i, token in enumerate(tokens):
            polarity = _POSITIVE.get(token, _NEGATIVE.get(token, 0.0))
            if polarity == 0.0:
                continue
            intensity = _INTENSIFIERS.get(tokens[i - 1], 1.0) if i > 0 else 1.0
            negated = i > 0 and tokens[i - 1] in _NEGATIONS
            value = polarity * intensity * (-1.0 if negated else 1.0)
            total += value
            weight_sum += abs(intensity)
            if value > 0:
                pos_hits += 1
            else:
                neg_hits += 1
        score = max(-1.0, min(1.0, total / weight_sum)) if weight_sum > 0 else 0.0
        return SentimentResult(
            score=round(score, 4),
            label=self._label(score),
            positive_hits=pos_hits,
            negative_hits=neg_hits,
            tokens=len(tokens),
        )

    def aggregate(self, texts: list[str]) -> SentimentResult:
        """Average sentiment across many texts (e.g. a batch of headlines)."""
        if not texts:
            return SentimentResult(0.0, "neutral", 0, 0, 0)
        results = [self.analyze(t) for t in texts]
        avg = sum(r.score for r in results) / len(results)
        return SentimentResult(
            score=round(avg, 4),
            label=self._label(avg),
            positive_hits=sum(r.positive_hits for r in results),
            negative_hits=sum(r.negative_hits for r in results),
            tokens=sum(r.tokens for r in results),
        )

    def _label(self, score: float) -> str:
        if score > self._neutral_band:
            return "bullish"
        if score < -self._neutral_band:
            return "bearish"
        return "neutral"


__all__ = ["SentimentAnalyzer", "SentimentResult"]

"""Bounded, deterministic chat detector. Message text never leaves memory."""

import math
from collections import Counter, deque
from dataclasses import dataclass


@dataclass
class Bucket:
    start: float
    count: int
    authors: int
    baseline: float
    spike: bool


class SpikeDetector:
    def __init__(self, ratio=3, minimum=10, distinct=5, warmup=300, cooldown=45):
        self.ratio, self.minimum, self.distinct = ratio, minimum, distinct
        self.warmup, self.cooldown = warmup, cooldown
        self.history = deque(maxlen=30)
        self.authors = Counter()
        self.seen = set()
        self.index = 0
        self.last_spike = -1e9

    def advance(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            return []
        completed = []
        target = int(seconds // 10)
        if target - self.index > 360:
            self.history.clear()
            self.authors.clear()
            self.seen.clear()
            self.index = target - 30
        while self.index < target:
            count = sum(self.authors.values())
            baseline = sum(self.history) / len(self.history) if self.history else 0
            start = self.index * 10
            spike = (
                start >= self.warmup
                and count >= self.minimum
                and len(self.authors) >= self.distinct
                and count >= max(1, baseline) * self.ratio
                and start - self.last_spike >= self.cooldown
            )
            if spike:
                self.last_spike = start
            completed.append(Bucket(start, count, len(self.authors), baseline, spike))
            self.history.append(count)
            self.authors.clear()
            self.seen.clear()
            self.index += 1
        return completed

    def add(self, seconds, author, text):
        if not math.isfinite(seconds) or seconds < 0:
            return []
        completed = self.advance(seconds)
        if seconds < self.index * 10 or not author:
            return completed
        # Repeated messages by one user count once; cap all contributions at 3/bucket.
        key = (author, text.strip().casefold()[:500])
        if key not in self.seen and self.authors[author] < 3 and len(self.seen) < 20000:
            self.seen.add(key)
            self.authors[author] += 1
        return completed

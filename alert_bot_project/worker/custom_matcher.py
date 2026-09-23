"""Bounded Aho-Corasick matcher for user-defined location phrases."""

import asyncio
from collections import deque

from redis.asyncio import Redis

from alert_bot_project.core_shared.constants import MAX_GLOBAL_CUSTOM_TRIGGERS


def _word_char(value: str) -> bool:
    return value.isalnum() or value == "_"


class CustomTriggerMatcher:
    def __init__(self) -> None:
        self._edges: list[dict[str, int]] = [{}]
        self._fail: list[int] = [0]
        self._outputs: list[list[str]] = [[]]
        self._version: str | None = None
        self._loaded = False
        self._lock = asyncio.Lock()

    def _build(self, phrases: set[str]) -> None:
        self._edges = [{}]
        self._fail = [0]
        self._outputs = [[]]
        for phrase in sorted(phrases):
            node = 0
            for char in phrase:
                child = self._edges[node].get(char)
                if child is None:
                    child = len(self._edges)
                    self._edges[node][char] = child
                    self._edges.append({})
                    self._fail.append(0)
                    self._outputs.append([])
                node = child
            self._outputs[node].append(phrase)

        queue = deque(self._edges[0].values())
        while queue:
            node = queue.popleft()
            for char, child in self._edges[node].items():
                fallback = self._fail[node]
                while fallback and char not in self._edges[fallback]:
                    fallback = self._fail[fallback]
                self._fail[child] = self._edges[fallback].get(char, 0)
                self._outputs[child].extend(self._outputs[self._fail[child]])
                queue.append(child)

    def _match(self, text: str) -> list[str]:
        matches: set[str] = set()
        node = 0
        for end, char in enumerate(text):
            while node and char not in self._edges[node]:
                node = self._fail[node]
            node = self._edges[node].get(char, 0)
            for phrase in self._outputs[node]:
                start = end + 1 - len(phrase)
                if start > 0 and _word_char(text[start - 1]):
                    continue
                suffix_end = end + 1
                while suffix_end < len(text) and _word_char(text[suffix_end]) and suffix_end <= end + 3:
                    suffix_end += 1
                if suffix_end < len(text) and _word_char(text[suffix_end]):
                    continue
                matches.add(phrase)
        return sorted(matches)

    async def get_matches(self, normalized_text: str, redis_client: Redis) -> list[str]:
        version = await redis_client.get("global_custom_triggers:version")
        async with self._lock:
            if not self._loaded or version != self._version:
                phrases = await redis_client.smembers("global_custom_triggers")
                if len(phrases) > MAX_GLOBAL_CUSTOM_TRIGGERS:
                    raise ValueError("global custom trigger limit exceeded")
                self._build(phrases)
                self._version = version
                self._loaded = True
            return self._match(normalized_text)

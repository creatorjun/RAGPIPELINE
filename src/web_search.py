# src/web_search.py
from __future__ import annotations

from typing import List

import requests


class SearchResult:
    def __init__(self, title: str, url: str, snippet: str):
        self.title = title
        self.url = url
        self.snippet = snippet

    def __str__(self) -> str:
        return f"[{self.title}]({self.url})\n{self.snippet}"


class SearXNGClient:
    def __init__(self, base_url: str, timeout: int = 10, max_results: int = 5):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_results = max_results

    def search(self, query: str, language: str = "ko-KR") -> List[SearchResult]:
        try:
            resp = requests.get(
                f"{self._base_url}/search",
                params={
                    "q": query,
                    "format": "json",
                    "language": language,
                    "categories": "general",
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"SearXNG 검색 실패: {exc}") from exc

        results: List[SearchResult] = []
        for item in data.get("results", [])[: self._max_results]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                )
            )
        return results

    def format_for_prompt(self, results: List[SearchResult]) -> str:
        if not results:
            return ""
        lines = ["[\uc6f9 검색 무결 자료]"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}")
            lines.append(f"   URL: {r.url}")
            if r.snippet:
                lines.append(f"   \uc694약: {r.snippet[:300]}")
        return "\n".join(lines)

"""
Simple in-memory session memory for "remembering" user queries.

Goal:
- When the user asks again, the backend can reuse previous queries
  for the same `session_id` (or `user_id`) to keep retrieval consistent.

Note:
- This is in-memory (per server process). Restarting the server will clear memory.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


@dataclass
class SessionMemory:
    queries: List[str] = field(default_factory=list)
    # Stored as (role, text). role in {"user","assistant"}.
    turns: List[Tuple[str, str]] = field(default_factory=list)
    # Latest analyze context (for follow-up chat/zoom without re-uploading).
    last_image_bytes: Optional[bytes] = None
    last_result: Optional[Dict[str, Any]] = None
    # For intent analysis flow (to be deprecated by Antigraviti but kept for compatibility)
    pending_image_bytes: Optional[bytes] = None
    pending_intent: Optional[str] = None
    pending_generation_prompt: Optional[str] = None
    
    # Antigraviti Design Agent flow
    antigraviti_phase: int = 0
    antigraviti_image: Optional[bytes] = None
    antigraviti_context: Optional[Dict[str, Any]] = None
    antigraviti_rag_results: Optional[List[Dict[str, Any]]] = None
    antigraviti_coherence_scores: Optional[Dict[str, int]] = None
    antigraviti_conflicts: Optional[List[str]] = None
    antigraviti_coherence_total: Optional[float] = None
    
    updated_at: float = 0.0


class MemoryStore:
    def __init__(
        self,
        *,
        max_items_per_session: int = 10,
        max_turns_per_session: int = 20,
        recent_limit: int = 3,
        recent_turns_limit: int = 6,
        ttl_seconds: int = 7 * 24 * 3600,
    ):
        self.max_items_per_session = max_items_per_session
        self.max_turns_per_session = max_turns_per_session
        self.recent_limit = recent_limit
        self.recent_turns_limit = recent_turns_limit
        self.ttl_seconds = ttl_seconds

        self._lock = threading.Lock()
        self._data: Dict[str, SessionMemory] = {}

    def _prune_locked(self, now: float) -> None:
        if self.ttl_seconds <= 0:
            return
        for key in list(self._data.keys()):
            if now - self._data[key].updated_at > self.ttl_seconds:
                del self._data[key]

    def get_last_query(self, key: str) -> Optional[str]:
        key = str(key).strip()
        if not key:
            return None

        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem or not mem.queries:
                return None
            return mem.queries[-1]

    def get_recent_queries(self, key: str, limit: Optional[int] = None) -> List[str]:
        key = str(key).strip()
        if not key:
            return []
        limit = self.recent_limit if limit is None else int(limit)
        limit = max(0, limit)

        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem or not mem.queries:
                return []
            return mem.queries[-limit:]

    def add_query(self, key: str, query: str) -> None:
        key = str(key).strip()
        q = str(query).strip()
        if not key or not q:
            return

        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem

            # Avoid storing duplicated consecutive queries.
            if mem.queries and mem.queries[-1] == q:
                mem.updated_at = now
                return

            mem.queries.append(q)
            if len(mem.queries) > self.max_items_per_session:
                mem.queries = mem.queries[-self.max_items_per_session :]
            mem.updated_at = now

    def get_recent_turns(self, key: str, limit: Optional[int] = None) -> List[Tuple[str, str]]:
        key = str(key).strip()
        if not key:
            return []
        limit = self.recent_turns_limit if limit is None else int(limit)
        limit = max(0, limit)

        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem or not mem.turns:
                return []
            return mem.turns[-limit:]

    def add_turn(self, key: str, role: str, text: str) -> None:
        key = str(key).strip()
        role = str(role).strip().lower()
        text = str(text).strip()
        if not key or not text:
            return
        if role not in {"user", "assistant"}:
            return

        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem

            # Avoid duplicated consecutive turns (same role+text)
            if mem.turns and mem.turns[-1][0] == role and mem.turns[-1][1] == text:
                mem.updated_at = now
                return

            mem.turns.append((role, text))
            if len(mem.turns) > self.max_turns_per_session:
                mem.turns = mem.turns[-self.max_turns_per_session :]
            mem.updated_at = now

    def set_last_analysis(self, key: str, image_bytes: bytes, result: Dict[str, Any]) -> None:
        key = str(key).strip()
        if not key:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem
            mem.last_image_bytes = image_bytes
            mem.last_result = result
            mem.updated_at = now

    def get_last_analysis(self, key: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        key = str(key).strip()
        if not key:
            return None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem or not mem.last_image_bytes or not mem.last_result:
                return None
            return mem.last_image_bytes, mem.last_result

    def set_pending_state(self, key: str, image_bytes: Optional[bytes] = None, intent: Optional[str] = None) -> None:
        key = str(key).strip()
        if not key:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem
            if image_bytes is not None:
                mem.pending_image_bytes = image_bytes
            if intent is not None:
                mem.pending_intent = intent
            mem.updated_at = now

    def get_pending_state(self, key: str) -> Tuple[Optional[bytes], Optional[str]]:
        key = str(key).strip()
        if not key:
            return None, None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                return None, None
            return mem.pending_image_bytes, mem.pending_intent

    def clear_pending_state(self, key: str) -> None:
        key = str(key).strip()
        if not key:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if mem:
                mem.pending_image_bytes = None
                mem.pending_intent = None
                mem.pending_generation_prompt = None
                mem.updated_at = now

    def set_pending_generation_prompt(self, key: str, prompt: Optional[str]) -> None:
        key = str(key).strip()
        if not key:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem
            mem.pending_generation_prompt = prompt
            mem.updated_at = now

    def get_pending_generation_prompt(self, key: str) -> Optional[str]:
        key = str(key).strip()
        if not key:
            return None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                return None
            return mem.pending_generation_prompt

    def get_antigraviti_state(self, key: str) -> Tuple[int, Optional[bytes], Optional[dict], Optional[list], Optional[dict], Optional[list], Optional[float]]:
        key = str(key).strip()
        if not key:
            return 0, None, None, None, None, None, None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                return 0, None, None, None, None, None, None
            return (
                mem.antigraviti_phase,
                mem.antigraviti_image,
                mem.antigraviti_context,
                mem.antigraviti_rag_results,
                mem.antigraviti_coherence_scores,
                mem.antigraviti_conflicts,
                mem.antigraviti_coherence_total
            )

    def set_antigraviti_state(
        self,
        key: str,
        phase: int,
        image: Optional[bytes] = None,
        context: Optional[dict] = None,
        rag_results: Optional[list] = None,
        coherence_scores: Optional[dict] = None,
        conflicts: Optional[list] = None,
        coherence_total: Optional[float] = None
    ) -> None:
        key = str(key).strip()
        if not key:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem
            mem.antigraviti_phase = phase
            if image is not None:
                mem.antigraviti_image = image
            if context is not None:
                mem.antigraviti_context = context
            if rag_results is not None:
                mem.antigraviti_rag_results = rag_results
            if coherence_scores is not None:
                mem.antigraviti_coherence_scores = coherence_scores
            if conflicts is not None:
                mem.antigraviti_conflicts = conflicts
            if coherence_total is not None:
                mem.antigraviti_coherence_total = coherence_total
            mem.updated_at = now

    def clear_antigraviti_state(self, key: str) -> None:
        key = str(key).strip()
        if not key:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if mem:
                mem.antigraviti_phase = 0
                mem.antigraviti_image = None
                mem.antigraviti_context = None
                mem.antigraviti_rag_results = None
                mem.antigraviti_coherence_scores = None
                mem.antigraviti_conflicts = None
                mem.antigraviti_coherence_total = None
                mem.updated_at = now


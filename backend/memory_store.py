"""
Simple in-memory session memory for "remembering" user queries.

Goal:
- When the user asks again, the backend can reuse previous queries
  for the same `session_id` (or `user_id`) to keep retrieval consistent.

Note:
- This is in-memory (per server process). Restarting the server will clear memory.
"""

from __future__ import annotations

import base64
import json
import os
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
    reply_lang: Optional[str] = None
    
    updated_at: float = 0.0


class MemoryStore:
    def __init__(
        self,
        *,
        max_items_per_session: int = 10,
        max_turns_per_session: int = 20,
        recent_limit: int = 3,
        recent_turns_limit: int = 12,
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

    def sync_turns_from_history(self, key: str, external_turns: List[Tuple[str, str]]) -> None:
        """Nạp lịch sử chat từ BE khi memory trống hoặc thiếu so với DB."""
        key = str(key).strip()
        if not key or not external_turns:
            return
        cleaned: List[Tuple[str, str]] = []
        for role, text in external_turns:
            r = str(role).strip().lower()
            t = str(text).strip()
            if r in {"user", "assistant"} and t:
                cleaned.append((r, t))
        if not cleaned:
            return

        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem
            if len(cleaned) > len(mem.turns):
                mem.turns = cleaned[-self.max_turns_per_session :]
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

    def set_reply_lang(self, key: str, lang: str) -> None:
        key = str(key).strip()
        lang = str(lang).strip().lower()
        if not key or lang not in {"vi", "en"}:
            return
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem:
                mem = SessionMemory()
                self._data[key] = mem
            mem.reply_lang = lang
            mem.updated_at = now

    def get_reply_lang(self, key: str) -> Optional[str]:
        key = str(key).strip()
        if not key:
            return None
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            mem = self._data.get(key)
            if not mem or not mem.reply_lang:
                return None
            return mem.reply_lang

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


class RedisMemoryStore:
    """
    Redis-backed session memory store.

    Persists full session memory (turns + antigraviti state + image bytes) keyed by `session_id`,
    so ai-server restart does not lose workflow context.
    """

    def __init__(
        self,
        *,
        redis_host: str,
        redis_port: int = 6379,
        redis_password: Optional[str] = None,
        redis_db: int = 0,
        key_prefix: str = "willa:ai:mem:",
        max_items_per_session: int = 10,
        max_turns_per_session: int = 20,
        recent_limit: int = 3,
        recent_turns_limit: int = 12,
        ttl_seconds: int = 7 * 24 * 3600,
    ):
        # Lazy import so local dev doesn't require redis unless enabled.
        import redis  # type: ignore

        self.max_items_per_session = max_items_per_session
        self.max_turns_per_session = max_turns_per_session
        self.recent_limit = recent_limit
        self.recent_turns_limit = recent_turns_limit
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix

        self._lock = threading.Lock()
        self._r = redis.Redis(
            host=redis_host,
            port=int(redis_port),
            password=redis_password or None,
            db=int(redis_db),
            decode_responses=True,  # store JSON as text
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
            retry_on_timeout=True,
        )

    def _key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    @staticmethod
    def _b64_encode(raw: Optional[bytes]) -> Optional[str]:
        if raw is None:
            return None
        return base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _b64_decode(s: Optional[str]) -> Optional[bytes]:
        if not s:
            return None
        try:
            return base64.b64decode(s.encode("ascii"))
        except Exception:
            return None

    def _default_mem(self) -> SessionMemory:
        return SessionMemory(updated_at=time.time())

    def _loads(self, raw: Optional[str]) -> SessionMemory:
        if not raw:
            return self._default_mem()
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                return self._default_mem()
        except Exception:
            return self._default_mem()

        mem = SessionMemory()
        mem.queries = list(payload.get("queries") or [])
        mem.turns = [tuple(x) for x in (payload.get("turns") or []) if isinstance(x, list) and len(x) == 2]
        mem.last_image_bytes = self._b64_decode(payload.get("last_image_b64"))
        mem.last_result = payload.get("last_result") if isinstance(payload.get("last_result"), dict) else None
        mem.pending_image_bytes = self._b64_decode(payload.get("pending_image_b64"))
        mem.pending_intent = payload.get("pending_intent")
        mem.pending_generation_prompt = payload.get("pending_generation_prompt")

        mem.antigraviti_phase = int(payload.get("antigraviti_phase") or 0)
        mem.antigraviti_image = self._b64_decode(payload.get("antigraviti_image_b64"))
        mem.antigraviti_context = payload.get("antigraviti_context") if isinstance(payload.get("antigraviti_context"), dict) else None
        mem.antigraviti_rag_results = payload.get("antigraviti_rag_results")
        mem.antigraviti_coherence_scores = payload.get("antigraviti_coherence_scores")
        mem.antigraviti_conflicts = payload.get("antigraviti_conflicts")
        mem.antigraviti_coherence_total = payload.get("antigraviti_coherence_total")
        mem.reply_lang = payload.get("reply_lang") if payload.get("reply_lang") in {"vi", "en"} else None
        try:
            mem.updated_at = float(payload.get("updated_at") or 0.0)
        except Exception:
            mem.updated_at = 0.0
        return mem

    def _dumps(self, mem: SessionMemory) -> str:
        payload = {
            "queries": mem.queries,
            "turns": [[r, t] for r, t in mem.turns],
            "last_image_b64": self._b64_encode(mem.last_image_bytes),
            "last_result": mem.last_result,
            "pending_image_b64": self._b64_encode(mem.pending_image_bytes),
            "pending_intent": mem.pending_intent,
            "pending_generation_prompt": mem.pending_generation_prompt,
            "antigraviti_phase": mem.antigraviti_phase,
            "antigraviti_image_b64": self._b64_encode(mem.antigraviti_image),
            "antigraviti_context": mem.antigraviti_context,
            "antigraviti_rag_results": mem.antigraviti_rag_results,
            "antigraviti_coherence_scores": mem.antigraviti_coherence_scores,
            "antigraviti_conflicts": mem.antigraviti_conflicts,
            "antigraviti_coherence_total": mem.antigraviti_coherence_total,
            "reply_lang": mem.reply_lang,
            "updated_at": mem.updated_at,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def _get(self, session_id: str) -> SessionMemory:
        sid = str(session_id).strip()
        if not sid:
            return self._default_mem()
        raw = self._r.get(self._key(sid))
        return self._loads(raw)

    def _set(self, session_id: str, mem: SessionMemory) -> None:
        sid = str(session_id).strip()
        if not sid:
            return
        mem.updated_at = time.time()
        key = self._key(sid)
        val = self._dumps(mem)
        if self.ttl_seconds and self.ttl_seconds > 0:
            self._r.setex(key, int(self.ttl_seconds), val)
        else:
            self._r.set(key, val)

    # ---- Public API (matching MemoryStore) ----
    def get_last_query(self, key: str) -> Optional[str]:
        key = str(key).strip()
        if not key:
            return None
        mem = self._get(key)
        return mem.queries[-1] if mem.queries else None

    def get_recent_queries(self, key: str, limit: Optional[int] = None) -> List[str]:
        key = str(key).strip()
        if not key:
            return []
        limit = self.recent_limit if limit is None else int(limit)
        limit = max(0, limit)
        mem = self._get(key)
        if not mem.queries:
            return []
        return mem.queries[-limit:]

    def add_query(self, key: str, query: str) -> None:
        key = str(key).strip()
        q = str(query).strip()
        if not key or not q:
            return
        with self._lock:
            mem = self._get(key)
            if mem.queries and mem.queries[-1] == q:
                self._set(key, mem)
                return
            mem.queries.append(q)
            if len(mem.queries) > self.max_items_per_session:
                mem.queries = mem.queries[-self.max_items_per_session :]
            self._set(key, mem)

    def get_recent_turns(self, key: str, limit: Optional[int] = None) -> List[Tuple[str, str]]:
        key = str(key).strip()
        if not key:
            return []
        limit = self.recent_turns_limit if limit is None else int(limit)
        limit = max(0, limit)
        mem = self._get(key)
        if not mem.turns:
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
        with self._lock:
            mem = self._get(key)
            if mem.turns and mem.turns[-1][0] == role and mem.turns[-1][1] == text:
                self._set(key, mem)
                return
            mem.turns.append((role, text))
            if len(mem.turns) > self.max_turns_per_session:
                mem.turns = mem.turns[-self.max_turns_per_session :]
            self._set(key, mem)

    def sync_turns_from_history(self, key: str, external_turns: List[Tuple[str, str]]) -> None:
        key = str(key).strip()
        if not key or not external_turns:
            return
        cleaned: List[Tuple[str, str]] = []
        for role, text in external_turns:
            r = str(role).strip().lower()
            t = str(text).strip()
            if r in {"user", "assistant"} and t:
                cleaned.append((r, t))
        if not cleaned:
            return
        with self._lock:
            mem = self._get(key)
            if len(cleaned) > len(mem.turns):
                mem.turns = cleaned[-self.max_turns_per_session :]
                self._set(key, mem)

    def set_reply_lang(self, key: str, lang: str) -> None:
        key = str(key).strip()
        lang = str(lang).strip().lower()
        if not key or lang not in {"vi", "en"}:
            return
        with self._lock:
            mem = self._get(key)
            mem.reply_lang = lang
            self._set(key, mem)

    def get_reply_lang(self, key: str) -> Optional[str]:
        key = str(key).strip()
        if not key:
            return None
        mem = self._get(key)
        return mem.reply_lang if mem.reply_lang in {"vi", "en"} else None

    def set_last_analysis(self, key: str, image_bytes: bytes, result: Dict[str, Any]) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            mem = self._get(key)
            mem.last_image_bytes = image_bytes
            mem.last_result = result
            self._set(key, mem)

    def get_last_analysis(self, key: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        key = str(key).strip()
        if not key:
            return None
        mem = self._get(key)
        if not mem.last_image_bytes or not mem.last_result:
            return None
        return mem.last_image_bytes, mem.last_result

    def set_pending_state(self, key: str, image_bytes: Optional[bytes] = None, intent: Optional[str] = None) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            mem = self._get(key)
            if image_bytes is not None:
                mem.pending_image_bytes = image_bytes
            if intent is not None:
                mem.pending_intent = intent
            self._set(key, mem)

    def get_pending_state(self, key: str) -> Tuple[Optional[bytes], Optional[str]]:
        key = str(key).strip()
        if not key:
            return None, None
        mem = self._get(key)
        return mem.pending_image_bytes, mem.pending_intent

    def clear_pending_state(self, key: str) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            mem = self._get(key)
            mem.pending_image_bytes = None
            mem.pending_intent = None
            mem.pending_generation_prompt = None
            self._set(key, mem)

    def set_pending_generation_prompt(self, key: str, prompt: Optional[str]) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            mem = self._get(key)
            mem.pending_generation_prompt = prompt
            self._set(key, mem)

    def get_pending_generation_prompt(self, key: str) -> Optional[str]:
        key = str(key).strip()
        if not key:
            return None
        mem = self._get(key)
        return mem.pending_generation_prompt

    def get_antigraviti_state(self, key: str) -> Tuple[int, Optional[bytes], Optional[dict], Optional[list], Optional[dict], Optional[list], Optional[float]]:
        key = str(key).strip()
        if not key:
            return 0, None, None, None, None, None, None
        mem = self._get(key)
        return (
            mem.antigraviti_phase,
            mem.antigraviti_image,
            mem.antigraviti_context,
            mem.antigraviti_rag_results,
            mem.antigraviti_coherence_scores,
            mem.antigraviti_conflicts,
            mem.antigraviti_coherence_total,
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
        coherence_total: Optional[float] = None,
    ) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            mem = self._get(key)
            mem.antigraviti_phase = int(phase or 0)
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
            self._set(key, mem)

    def clear_antigraviti_state(self, key: str) -> None:
        key = str(key).strip()
        if not key:
            return
        with self._lock:
            mem = self._get(key)
            mem.antigraviti_phase = 0
            mem.antigraviti_image = None
            mem.antigraviti_context = None
            mem.antigraviti_rag_results = None
            mem.antigraviti_coherence_scores = None
            mem.antigraviti_conflicts = None
            mem.antigraviti_coherence_total = None
            self._set(key, mem)


def build_memory_store_from_env() -> Any:
    """
    Factory: use RedisMemoryStore when REDIS_HOST is set, else fallback to in-memory MemoryStore.
    """
    host = (os.getenv("REDIS_HOST") or "").strip()
    if not host:
        return MemoryStore()
    port = int(os.getenv("REDIS_PORT") or "6379")
    password = os.getenv("REDIS_PASSWORD")
    db = int(os.getenv("REDIS_DB") or "0")
    ttl = int(os.getenv("AI_MEMORY_TTL_SECONDS") or str(7 * 24 * 3600))
    prefix = os.getenv("AI_MEMORY_REDIS_PREFIX") or "willa:ai:mem:"
    return RedisMemoryStore(
        redis_host=host,
        redis_port=port,
        redis_password=password,
        redis_db=db,
        key_prefix=prefix,
        ttl_seconds=ttl,
    )

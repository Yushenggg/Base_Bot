import asyncio
import logging
import time
from typing import Literal

from pydantic import BaseModel, PrivateAttr


Message = dict[str, str]

EditStatePhase = Literal["planning", "executing", "done", "cancelled"]


class EditState(BaseModel):
    phase: EditStatePhase
    instruction: str
    planner_history: list[Message]
    started_at: float


class SessionManager(BaseModel):
    max_messages: int = 50
    max_sessions: int = 500
    edit_timeout: float = 1800.0
    idle_timeout: float = 300.0
    cleanup_interval: float = 60.0

    _memory: dict[int, list[Message]] = PrivateAttr(default_factory=dict)
    _activity: dict[int, float] = PrivateAttr(default_factory=dict)
    _edit_states: dict[int, EditState] = PrivateAttr(default_factory=dict)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)
    _cleanup_task: asyncio.Task | None = PrivateAttr(default=None)

    def _ensure_cleanup_started(self) -> None:
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._cleanup_task = loop.create_task(self._cleanup_loop())

    def start_cleanup_task(self) -> None:
        self._ensure_cleanup_started()

    async def stop_cleanup_task(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self.cleanup_interval)
            await self._evict_idle()

    async def get_messages(self, chat_id: int) -> list[Message]:
        async with self._lock:
            return list(self._memory.get(chat_id, []))

    async def append_message(
        self, chat_id: int, role: str, content: str
    ) -> list[Message]:
        self._ensure_cleanup_started()
        async with self._lock:
            session = self._memory.setdefault(chat_id, [])
            session.append({"role": role, "content": content})
            if len(session) > self.max_messages:
                del session[:-self.max_messages]
            self._activity[chat_id] = time.time()
            self._evict_if_needed()
            return list(session)

    async def touch(self, chat_id: int) -> None:
        self._ensure_cleanup_started()
        async with self._lock:
            self._activity[chat_id] = time.time()
            self._evict_if_needed()

    async def get_or_create_session(self, chat_id: int) -> list[Message]:
        self._ensure_cleanup_started()
        async with self._lock:
            self._touch_unlocked(chat_id)
            return list(self._memory.get(chat_id, []))

    async def get_edit_state(self, chat_id: int) -> EditState | None:
        self._ensure_cleanup_started()
        async with self._lock:
            state = self._edit_states.get(chat_id)
            if state and time.time() - state.started_at > self.edit_timeout:
                del self._edit_states[chat_id]
                return None
            return state

    async def set_edit_state(
        self,
        chat_id: int,
        phase: EditStatePhase,
        instruction: str,
        planner_history: list[Message],
    ) -> EditState:
        self._ensure_cleanup_started()
        async with self._lock:
            state = EditState(
                phase=phase,
                instruction=instruction,
                planner_history=planner_history,
                started_at=time.time(),
            )
            self._edit_states[chat_id] = state
            return state

    async def clear_edit_state(self, chat_id: int) -> None:
        self._ensure_cleanup_started()
        async with self._lock:
            self._edit_states.pop(chat_id, None)

    async def clear_session(self, chat_id: int) -> None:
        self._ensure_cleanup_started()
        async with self._lock:
            self._memory.pop(chat_id, None)
            self._activity.pop(chat_id, None)
            self._edit_states.pop(chat_id, None)

    def _evict_if_needed(self) -> None:
        if len(self._memory) <= self.max_sessions:
            return
        oldest = min(self._activity, key=self._activity.get)
        self._memory.pop(oldest, None)
        self._activity.pop(oldest, None)
        self._edit_states.pop(oldest, None)

    async def _evict_idle(self) -> None:
        now = time.time()
        async with self._lock:
            stale = [
                chat_id
                for chat_id, last_active in self._activity.items()
                if now - last_active > self.idle_timeout
            ]
            for chat_id in stale:
                self._memory.pop(chat_id, None)
                self._activity.pop(chat_id, None)
                self._edit_states.pop(chat_id, None)
            if stale:
                logger = logging.getLogger("SESSION_MANAGER")
                logger.info("Evicted %d idle sessions", len(stale))

    def _touch_unlocked(self, chat_id: int) -> None:
        self._activity[chat_id] = time.time()
        if len(self._memory) > self.max_sessions:
            oldest = min(self._activity, key=self._activity.get)
            self._memory.pop(oldest, None)
            self._activity.pop(oldest, None)
            self._edit_states.pop(oldest, None)
import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Literal

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from core.agents import verify_working_code
from core.config import app_config, WORKING_DIR, BACKUP_DIR
from core.core_agent import CoreAgent
from core.telegram_worker.auth import RoleResolver

logger = logging.getLogger("HANDLERS")

UpdateKind = Literal[
    "text", "photo", "sticker", "document", "audio",
    "video", "voice", "location", "contact", "poll",
    "caption", "other", "unknown",
]


def _get_update_kind(update: Update) -> UpdateKind:
    msg = update.effective_message
    if msg is None:
        return "unknown"
    if msg.text:
        return "text"
    if msg.photo:
        return "photo"
    if msg.sticker:
        return "sticker"
    if msg.document:
        return "document"
    if msg.audio:
        return "audio"
    if msg.video:
        return "video"
    if msg.voice:
        return "voice"
    if msg.location:
        return "location"
    if msg.contact:
        return "contact"
    if msg.poll:
        return "poll"
    if msg.caption:
        return "caption"
    return "other"


class BotHandlers:
    def __init__(self, agent: CoreAgent, auth: RoleResolver, reload_callback=None):
        self.agent = agent
        self.auth = auth
        self._reload_callback = reload_callback
        self._session_memory: dict[int, list[dict]] = {}
        self._session_activity: dict[int, float] = {}
        self._edit_states: dict[int, dict] = {}
        self._MAX_SESSIONS = 500
        self._EDIT_TIMEOUT = 1800

    # ── Top-level dispatchers ──────────────────────────────────────

    def _touch_session(self, chat_id: int):
        now = time.time()
        self._session_activity[chat_id] = now
        if len(self._session_memory) > self._MAX_SESSIONS:
            oldest = min(self._session_activity, key=self._session_activity.get)
            self._session_memory.pop(oldest, None)
            self._session_activity.pop(oldest, None)
            self._edit_states.pop(oldest, None)

    async def handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ):
        if not update.effective_chat:
            return
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="I'm a bot, please talk to me!",
        )

    async def handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ):
        if not update.effective_chat or not update.effective_message:
            return
        if not self.auth.is_authorized(
            update.effective_user.id if update.effective_user else None,
        ):
            return

        chat_id = update.effective_chat.id
        kind = _get_update_kind(update)

        edit_state = self._edit_states.get(chat_id)
        if edit_state and edit_state["state"] == "planning":
            await self._handle_planning_response(chat_id, update, context)
            return

        match kind:
            case "text":
                await self._handle_text(chat_id, update, context)
            case "photo":
                await self._reply(chat_id, context, "Nice photo! Unfortunately I can't do anything with it yet.")
            case "sticker":
                await self._reply(chat_id, context, "Nice sticker!")
                if update.effective_message and update.effective_message.sticker:
                    await context.bot.send_sticker(
                        chat_id=chat_id,
                        sticker=update.effective_message.sticker.file_id,
                    )
            case "document":
                await self._reply(chat_id, context, "A document? I don't want that.")
            case "audio" | "video" | "voice":
                await self._reply(chat_id, context, "I see no evil, hear no evil. So I'm going to ignore that.")
            case "location" | "contact" | "poll":
                await self._reply(chat_id, context, "Seems complicated. Not gonna comment on that.")
            case "caption":
                await self._reply(chat_id, context, "How did you get here?")
            case _:
                await self._reply(chat_id, context, "Da hell is that?")

    async def handle_edit(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ):
        if not update.effective_chat or not update.effective_message:
            return
        if not self.auth.is_authorized(
            update.effective_user.id if update.effective_user else None,
        ):
            return

        chat_id = update.effective_chat.id
        instruction = update.effective_message.text.replace("/edit", "", 1).strip()

        if not instruction:
            await self._reply(
                chat_id, context,
                "Usage: /edit <description of what to create or modify>",
            )
            return

        await self._reply(chat_id, context, "✏️ Working on it...")

        history = self._session_memory.setdefault(chat_id, [])
        self._touch_session(chat_id)
        history.append({"role": "user", "content": f"/edit {instruction}"})

        plan = await self._with_typing(
            chat_id, context,
            self.agent.ainvoke_planner(history),
        )
        if plan is None:
            await self._reply(chat_id, context, "❌ Planning failed.")
            return

        history.append({"role": "assistant", "content": plan})
        self._edit_states[chat_id] = {
            "state": "planning",
            "instruction": instruction,
            "planner_history": history.copy(),
            "started_at": time.time(),
        }
        await self._reply(chat_id, context, plan)

    # ── Text processing (Standard Agent) ────────────────────────────

    async def _handle_text(
        self, chat_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ):
        text = update.effective_message.text
        history = self._session_memory.setdefault(chat_id, [])
        self._touch_session(chat_id)
        history.append({"role": "user", "content": text})

        reply = await self._with_typing(
            chat_id, context,
            self.agent.ainvoke_standard(history),
        )
        if reply is None:
            reply = "Sorry, I had trouble processing that. Please try again."

        history.append({"role": "assistant", "content": reply})
        if len(history) > 50:
            history[:] = history[-50:]
        await self._reply(chat_id, context, reply)

    # ── /edit planning loop ─────────────────────────────────────────

    async def _handle_planning_response(
        self, chat_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE,
    ):
        state = self._edit_states[chat_id]

        if time.time() - state.get("started_at", 0) > self._EDIT_TIMEOUT:
            del self._edit_states[chat_id]
            await self._reply(chat_id, context, "⏰ Planning session timed out. Start a new /edit if needed.")
            return

        history = state["planner_history"]
        user_text = update.effective_message.text
        history.append({"role": "user", "content": user_text})

        if user_text.strip().lower() in ("go", "execute", "yes", "confirmed", "do it", "proceed"):
            del self._edit_states[chat_id]
            await self._reply(chat_id, context, "⚙️ Executing code mutation...")

            self._backup_working()
            instruction = state["instruction"]

            code_result = await self._with_typing(
                chat_id, context,
                self.agent.ainvoke_code(instruction, history),
            )
            if not code_result or not code_result.strip():
                self._restore_working()
                await self._reply(
                    chat_id, context,
                    "❌ Code Agent returned empty — no changes made. Rolled back.",
                )
                return

            error = verify_working_code(WORKING_DIR)
            if error:
                self._restore_working()
                await self._reply(
                    chat_id, context,
                    f"❌ Code verification failed. Rolled back.\n```\n{error}\n```",
                )
                return

            history.append({
                "role": "assistant",
                "content": f"Code mutation result: {code_result}",
            })
            await self._reply(
                chat_id, context,
                f"✅ Mutation successful. Reloading in-process...\n\n{code_result}",
            )
            logger.info("Mutation successful. Reloading bot components in-process.")
            if self._reload_callback:
                self._reload_callback()
            await self._reply(chat_id, context, "🔄 Reload complete. New handlers and tools are now active.")
        else:
            reply = await self._with_typing(
                chat_id, context,
                self.agent.ainvoke_planner(history),
            )
            if reply is None:
                await self._reply(
                    chat_id, context, "❌ Planning failed.",
                )
                del self._edit_states[chat_id]
                return

            history.append({"role": "assistant", "content": reply})
            await self._reply(chat_id, context, reply)

    # ── Safety helpers (backup / restore) ────────────────────────────

    def _backup_working(self):
        if BACKUP_DIR.exists():
            shutil.rmtree(BACKUP_DIR)
        if WORKING_DIR.exists():
            shutil.copytree(WORKING_DIR, BACKUP_DIR, dirs_exist_ok=True)

    def _restore_working(self):
        if WORKING_DIR.exists():
            shutil.rmtree(WORKING_DIR)
        if BACKUP_DIR.exists():
            shutil.copytree(BACKUP_DIR, WORKING_DIR, dirs_exist_ok=True)

    # ── Utilities ───────────────────────────────────────────────────

    @staticmethod
    async def _reply(
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ):
        if not text or not text.strip():
            text = "I didn't get a response. Please try again."

        MAX_LEN = 4000
        chunks = []
        while len(text) > MAX_LEN:
            split_at = text.rfind("\n", 0, MAX_LEN)
            if split_at == -1:
                split_at = text.rfind(" ", 0, MAX_LEN)
            if split_at == -1:
                split_at = MAX_LEN
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
        if text:
            chunks.append(text)

        for i, chunk in enumerate(chunks):
            try:
                await context.bot.send_message(
                    chat_id=chat_id, text=chunk, parse_mode="Markdown",
                )
            except Exception:
                await context.bot.send_message(chat_id=chat_id, text=chunk)

    async def _with_typing(
        self,
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        coro,
    ):
        stop = asyncio.Event()
        pulse = asyncio.create_task(self._typing_pulse(chat_id, context, stop))
        try:
            return await coro
        except Exception:
            logger.exception("Agent call failed")
            return None
        finally:
            stop.set()
            await pulse

    @staticmethod
    async def _typing_pulse(
        chat_id: int,
        context: ContextTypes.DEFAULT_TYPE,
        stop: asyncio.Event,
    ):
        while not stop.is_set():
            await context.bot.send_chat_action(
                chat_id=chat_id, action=ChatAction.TYPING,
            )
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.0)
            except TimeoutError:
                continue

"""
services/llm_service.py
LLM (Groq) service — wraps the VoiceAIOrchestrator.
Controllers call process() and get a clean response string back.
"""
import asyncio
import logging
import os

logger = logging.getLogger("VoiceAI.LLM")


class LLMService:
    def __init__(self):
        self._orchestrator = None

    def _get_orchestrator(self, session_id: str = "default"):
        """Lazy-create an orchestrator per session (stateful conversation)."""
        from agents.orchestrator import VoiceAIOrchestrator
        if self._orchestrator is None or self._orchestrator.session_id != session_id:
            self._orchestrator = VoiceAIOrchestrator(session_id=session_id)
        return self._orchestrator

    async def process(self, text: str, session_id: str = "default") -> str:
        """
        Send user text to the LLM and return the AI's response string.
        Runs synchronously in a thread to avoid blocking the async event loop.
        """
        orchestrator = self._get_orchestrator(session_id)
        response = await asyncio.to_thread(orchestrator.process_transcript, text)
        logger.info(f"[LLM] session={session_id} | in='{text[:60]}' | out='{str(response)[:80]}'")
        return response or "I'm sorry, I didn't understand that. Could you repeat?"


# Singleton
llm_service = LLMService()

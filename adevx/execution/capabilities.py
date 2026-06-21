"""Capability executors that power the orchestration pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from adevx.core.errors import ProviderError
from adevx.core.models import AssistantResponse, ChatMessage, ToolInvocation, UserRequest
from adevx.core.redaction import redact_secrets
from adevx.execution.autonomous_engine import AutonomousReasoningEngine
from adevx.memory.json_store import JsonMemoryStore
from adevx.providers.router import ProviderRouter
from adevx.rag.retriever import WorkspaceRetriever
from adevx.tools.registry import ToolRegistry


@dataclass(slots=True)
class ClassifierCapability:
    name: str = "capability.classifier"

    async def execute(self, step_input: dict, request: UserRequest) -> str:
        return f"Classified mode={request.mode} for request={request.request_id}"


@dataclass(slots=True)
class ProviderChatCapability:
    router: ProviderRouter
    memory: JsonMemoryStore
    retriever: WorkspaceRetriever
    name: str = "capability.chat"

    async def execute(self, step_input: dict, request: UserRequest) -> str:
        user_text = str(step_input.get("text", request.text))
        if request.mode == "coding":
            rag_top_k, rag_max_chars = 6, 5200
        elif request.mode == "research":
            rag_top_k, rag_max_chars = 5, 4600
        elif request.mode == "image":
            rag_top_k, rag_max_chars = 2, 1800
        else:
            rag_top_k, rag_max_chars = 3, 3000
        rag_context = await self.retriever.retrieve(
            user_text,
            top_k=rag_top_k,
            max_chars=rag_max_chars,
        )
        memories = await self.memory.get_recent(request.session_id, limit=8)
        messages = [
            ChatMessage(role="developer", content=f"Mode={request.mode}. Use concise reliable answers."),
            ChatMessage(role="developer", content=f"Memory:\n" + "\n".join(f"- {m}" for m in memories)),
            ChatMessage(role="developer", content=rag_context),
            ChatMessage(role="user", content=user_text),
        ]
        try:
            response: AssistantResponse = await self.router.complete(messages=messages, request=request)
            await self.memory.add(request.session_id, f"user:{user_text}")
            await self.memory.add(request.session_id, f"assistant:{response.text[:300]}")
            return response.text
        except ProviderError as exc:
            return (
                "No model is currently reachable for this request.\n"
                "Configure provider keys (OPENAI_API_KEY / OPENROUTER_API_KEY / GROQ_API_KEY / TOGETHER_API_KEY) "
                "or run local Ollama (ADEVX_ENABLE_OLLAMA=1).\n"
                f"Provider error: {redact_secrets(exc)}"
            )


@dataclass(slots=True)
class CodingCapability(ProviderChatCapability):
    name: str = "capability.coding"


@dataclass(slots=True)
class ToolTaskCapability:
    tools: ToolRegistry
    name: str = "capability.tools"

    async def execute(self, step_input: dict, request: UserRequest) -> str:
        text = str(step_input.get("text", request.text)).strip()
        lower = text.lower()
        if lower.startswith("/read "):
            invocation = ToolInvocation(name="read_file", arguments={"path": text[6:].strip()})
        elif lower.startswith("/write "):
            invocation = ToolInvocation(name="write_file", arguments={"path": "notes.txt", "content": text[7:].strip()})
        elif lower.startswith("/image "):
            invocation = ToolInvocation(name="analyze_image", arguments={"path": text[7:].strip()})
        elif "list files" in lower:
            invocation = ToolInvocation(name="list_files", arguments={"path": "."})
        else:
            invocation = ToolInvocation(name="search_text", arguments={"query": text})
        result = await self.tools.run(invocation)
        return result.output


@dataclass(slots=True)
class VerifyCapability:
    name: str = "capability.verify"

    async def execute(self, step_input: dict, request: UserRequest) -> str:
        return "Verification pass completed (scaffold policy checks)."


@dataclass(slots=True)
class AutonomousCapability:
    engine: AutonomousReasoningEngine
    name: str = "capability.autonomous"

    async def execute(self, step_input: dict, request: UserRequest) -> str:
        goal_text = str(step_input.get("text", request.text)).strip() or request.text
        delegated_request = UserRequest(
            text=goal_text,
            mode=request.mode,
            session_id=request.session_id,
            request_id=request.request_id,
            metadata={**request.metadata, "autonomous": True},
        )
        response = await self.engine.run(delegated_request)
        return response.text

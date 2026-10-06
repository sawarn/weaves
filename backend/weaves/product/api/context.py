"""Knowledge, memory, and conversation context API routes."""

from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from weaves.product.contracts.v1 import (
    ConversationThreadStatus,
    MemoryRetentionClass,
    MemoryScope,
    Permission,
)
from weaves.product.runtime import LocalPlatformRuntime
from weaves.product.runtime.request_identity import (
    effective_org_id,
    effective_workspace_id,
)


class KnowledgeDocumentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=12_000)


class MemoryItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=160)
    text: str = Field(min_length=1, max_length=12_000)
    scope: MemoryScope = MemoryScope.WORKSPACE
    retention_class: MemoryRetentionClass = MemoryRetentionClass.STANDARD
    expires_at: Optional[AwareDatetime] = None
    source_ref: Optional[str] = Field(default=None, max_length=256)
    scope_ref: Optional[str] = Field(default=None, max_length=128)


class ConversationThreadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agent_id: Optional[str] = None
    title: str = Field(default="New conversation", min_length=1, max_length=160)


class ConversationThreadPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ConversationThreadStatus


def register_context_routes(
    app: FastAPI,
    platform: LocalPlatformRuntime,
    dump: Callable[[BaseModel], dict[str, Any]],
    run_view: Callable[[LocalPlatformRuntime, Any], dict[str, Any]],
) -> None:
    """Register knowledge, memory, and conversation thread endpoints."""
    _dump = dump
    _run_view = run_view

    @app.get("/api/v0/knowledge-documents")
    def list_knowledge_documents() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.PLUGINS_MANAGE)
        documents = platform.knowledge_documents.list_scoped(
            effective_org_id(), effective_workspace_id()
        )
        return [_dump(item) for item in documents]

    @app.post("/api/v0/knowledge-documents", status_code=201)
    def create_knowledge_document(
        request: KnowledgeDocumentCreateRequest,
    ) -> dict[str, Any]:
        try:
            document = platform.create_knowledge_document(
                title=request.title, text=request.text
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(document)

    @app.delete("/api/v0/knowledge-documents/{document_id}", status_code=204)
    def delete_knowledge_document(document_id: str) -> Response:
        try:
            platform.delete_knowledge_document(document_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Knowledge document not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @app.get("/api/v0/memory-items")
    def list_memory_items() -> list[dict[str, Any]]:
        return [_dump(item) for item in platform.list_memory_items()]

    @app.get("/api/v0/threads")
    def list_conversation_threads() -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        return [
            _dump(item)
            for item in platform.threads.list_scoped(
                effective_org_id(), effective_workspace_id()
            )
        ]

    @app.post("/api/v0/threads", status_code=201)
    def create_conversation_thread(
        request: ConversationThreadCreateRequest,
    ) -> dict[str, Any]:
        try:
            thread = platform.create_conversation_thread(**request.model_dump())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Agent not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(thread)

    @app.get("/api/v0/threads/{thread_id}")
    def get_conversation_thread(thread_id: str) -> dict[str, Any]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        try:
            return _dump(
                platform.threads.get_scoped(
                    thread_id, effective_org_id(), effective_workspace_id()
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc

    @app.get("/api/v0/threads/{thread_id}/runs")
    def list_conversation_thread_runs(
        thread_id: str,
        limit: int = Query(default=50, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        platform.authorize("local-developer", Permission.AGENTS_RUN)
        try:
            thread = platform.threads.get_scoped(
                thread_id, effective_org_id(), effective_workspace_id()
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc
        runs = [
            run
            for run in platform.runs.list_scoped(thread.org_id, thread.workspace_id)
            if run.trigger_ref == thread_id
        ]
        ordered = sorted(runs, key=lambda item: item.created_at, reverse=True)[:limit]
        return [_run_view(platform, item) for item in ordered]

    @app.patch("/api/v0/threads/{thread_id}")
    def update_conversation_thread(
        thread_id: str, request: ConversationThreadPatchRequest
    ) -> dict[str, Any]:
        if request.status is not ConversationThreadStatus.CLOSED:
            raise HTTPException(status_code=422, detail="Threads can only be closed")
        try:
            return _dump(platform.close_conversation_thread(thread_id))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Thread not found") from exc

    @app.post("/api/v0/memory-items", status_code=201)
    def create_memory_item(request: MemoryItemCreateRequest) -> dict[str, Any]:
        try:
            item = platform.create_memory_item(**request.model_dump())
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _dump(item)

    @app.delete("/api/v0/memory-items/{memory_id}", status_code=204)
    def delete_memory_item(memory_id: str) -> Response:
        try:
            platform.delete_memory_item(memory_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="Memory item not found"
            ) from exc
        return Response(status_code=204)

"""Drafts: generated content you preview, then Save, Edit, Regenerate or
Cancel (SPEC 40). Generation runs in the worker; nothing reaches your
materials, question bank or flashcards until you save."""

import builtins
import re
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.errors import AppError
from app.models import Document, Draft, Flashcard, Question
from app.practice.validation import check_flashcard, check_question
from app.schemas.practice import DraftOut, DraftSave, GenerateRequest, MaterialCreate, SavedDraft
from app.services.common import ClientInfo, ScopedService, not_found
from app.services.materials import MaterialService
from app.services.quizzes import ensure_no_exam
from app.workers.queue import JobQueue

CITE_N = re.compile(r"#cite-(\d+)\)")
OPEN = ("generating", "ready", "failed")


def draft_out(draft: Draft) -> DraftOut:
    """Embeddings stay on the server."""
    payload = draft.payload
    if payload and "items" in payload:
        payload = {
            **payload,
            "items": [
                {k: v for k, v in item.items() if k != "embedding"} for item in payload["items"]
            ],
        }
    out = DraftOut.model_validate(draft)
    return out.model_copy(update={"payload": payload})


class DraftService(ScopedService):
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        client: ClientInfo,
        *,
        config: AppConfig,
        jobs: JobQueue,
    ) -> None:
        super().__init__(db, user_id, client)
        self.config = config
        self.jobs = jobs

    async def get(self, draft_id: uuid.UUID) -> Draft:
        draft = await self.db.scalar(
            select(Draft).where(Draft.id == draft_id, Draft.user_id == self.user_id)
        )
        if draft is None:
            raise not_found("draft")
        return draft

    async def list(self, module_id: uuid.UUID) -> Sequence[Draft]:
        await self.placement(module_id, None)
        rows = await self.db.scalars(
            select(Draft)
            .where(
                Draft.user_id == self.user_id,
                Draft.module_id == module_id,
                Draft.status.in_(OPEN),
            )
            .order_by(Draft.created_at.desc())
        )
        return rows.all()

    async def _enqueue(self, draft: Draft) -> None:
        await self.jobs.enqueue(
            "generate_draft",
            str(draft.id),
            job_id=f"draft:{draft.id}:{draft.updated_at.timestamp()}",
        )

    async def create(self, body: GenerateRequest) -> Draft:
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        await self.placement(body.module_id, body.topic_id)
        generation = self.config.practice.generation
        if body.count is not None and body.count > generation.max_items:
            raise AppError(
                "too_many_items", f"Ask for at most {generation.max_items} at a time.", 422
            )
        if body.document_ids:
            owned = await self.db.scalars(
                select(Document.id).where(
                    Document.id.in_(body.document_ids),
                    Document.user_id == self.user_id,
                    Document.deleted_at.is_(None),
                )
            )
            if len(set(owned.all())) != len(set(body.document_ids)):
                raise not_found("document")
        if body.improve_material_id is not None:
            if body.kind != "material":
                raise AppError("bad_request", "Only materials can be improved.", 422)
            await MaterialService(self.db, self.user_id, self.client).get(body.improve_material_id)
        request = body.model_dump(mode="json", exclude={"module_id", "topic_id", "kind"})
        if body.kind == "material" and not request.get("material_kind"):
            request["material_kind"] = "guide"
        draft = Draft(
            id=uuid.uuid4(),
            user_id=self.user_id,
            module_id=body.module_id,
            topic_id=body.topic_id,
            kind=body.kind,
            request=request,
            status="generating",
        )
        self.db.add(draft)
        await self.db.commit()
        await self.db.refresh(draft)
        await self._enqueue(draft)
        return draft

    async def regenerate(self, draft_id: uuid.UUID, instructions: str | None) -> Draft:
        await ensure_no_exam(self.db, self.user_id, self.config, self.jobs)
        draft = await self.get(draft_id)
        if draft.status not in ("ready", "failed"):
            raise AppError("draft_not_open", f"This draft is {draft.status}.", 409)
        if instructions is not None:
            draft.request = {**draft.request, "instructions": instructions or None}
        draft.status, draft.payload, draft.error_code = "generating", None, None
        await self.db.commit()
        await self.db.refresh(draft)
        await self._enqueue(draft)
        return draft

    async def discard(self, draft_id: uuid.UUID) -> Draft:
        draft = await self.get(draft_id)
        if draft.status not in OPEN:
            raise AppError("draft_not_open", f"This draft is already {draft.status}.", 409)
        draft.status = "discarded"
        await self.db.commit()
        # updated_at is set by the database, so reload it.
        await self.db.refresh(draft)
        return draft

    # --- saving -------------------------------------------------------------------

    async def save(self, draft_id: uuid.UUID, body: DraftSave) -> SavedDraft:
        draft = await self.get(draft_id)
        if draft.status != "ready" or draft.payload is None:
            raise AppError("draft_not_ready", "Only a finished draft can be saved.", 409)
        if draft.kind == "material":
            material_id = await self._save_material(draft, body)
            saved, count = draft, 1
        else:
            material_id = None
            count = await self._save_items(draft, body.selected)
            saved = draft
        saved.status = "saved"
        await self.db.commit()
        await self.db.refresh(saved)
        return SavedDraft(draft=draft_out(saved), material_id=material_id, saved_items=count)

    async def _save_material(self, draft: Draft, body: DraftSave) -> uuid.UUID:
        payload = draft.payload or {}
        content = body.content_md if body.content_md is not None else payload["content_md"]
        edited = body.content_md is not None and body.content_md != payload["content_md"]
        # Keep only citations whose markers survived your edits.
        kept = {int(n) for n in CITE_N.findall(content)}
        citations = [c for c in payload.get("citations", []) if c["n"] in kept]
        materials = MaterialService(self.db, self.user_id, self.client)
        target = draft.request.get("improve_material_id")
        if target:
            material = await materials.get(uuid.UUID(target))
            note = "Improved by Claude" + (" (edited before saving)" if edited else "")
            await materials.add_version(
                material,
                content,
                created_by="claude",
                change_note=note,
                citations=citations,
                ai_interaction_id=draft.ai_interaction_id,
            )
            return material.id
        material = await materials.create(
            MaterialCreate(
                module_id=draft.module_id,
                topic_id=draft.topic_id,
                title=body.title or payload["title"],
                kind=draft.request.get("material_kind") or "guide",
                content_md=content,
            ),
            origin="claude",
            citations=citations,
            ai_interaction_id=draft.ai_interaction_id,
            change_note="Edited before saving" if edited else None,
        )
        return material.id

    def _chosen(
        self, items: builtins.list[dict[str, Any]], selected: builtins.list[int] | None
    ) -> builtins.list[int]:
        if selected is None:
            return [i for i, item in enumerate(items) if item.get("valid")]
        for i in selected:
            if not 0 <= i < len(items):
                raise AppError("bad_selection", "That item is not in the draft.", 422)
            if not items[i].get("valid"):
                raise AppError("invalid_item", "Items that failed the checks cannot be saved.", 422)
        return sorted(set(selected))

    async def _save_items(self, draft: Draft, selected: builtins.list[int] | None) -> int:
        payload = draft.payload or {}
        items: builtins.list[dict[str, Any]] = payload.get("items", [])
        passages = {p["n"]: p for p in payload.get("passages", [])}
        practice = self.config.practice
        ratings = self.config.learning.difficulty.initial_ratings
        chosen = self._chosen(items, selected)
        for i in chosen:
            item = items[i]
            sources = [
                {k: v for k, v in passages[n].items() if k != "n"}
                for n in item.get("sources", [])
                if n in passages
            ]
            if draft.kind == "questions":
                # Re-checked at save time: the bank only ever holds valid questions.
                checked = check_question(item, len(passages), practice.validation, practice.marking)
                if not checked.valid or checked.spec is None:
                    raise AppError(
                        "invalid_item", "Items that failed the checks cannot be saved.", 422
                    )
                self.db.add(
                    Question(
                        id=uuid.uuid4(),
                        user_id=self.user_id,
                        module_id=draft.module_id,
                        topic_id=draft.topic_id,
                        type=checked.spec.type,
                        difficulty=item["difficulty"],
                        rating=getattr(ratings, item["difficulty"]),
                        stem_md=item["stem_md"],
                        answer_spec=checked.spec.model_dump(mode="json"),
                        solution_md=item["solution_md"],
                        origin="claude",
                        sources=sources,
                        embedding=item.get("embedding"),
                    )
                )
            else:
                if not check_flashcard(item, len(passages), practice.validation).valid:
                    raise AppError(
                        "invalid_item", "Items that failed the checks cannot be saved.", 422
                    )
                self.db.add(
                    Flashcard(
                        id=uuid.uuid4(),
                        user_id=self.user_id,
                        module_id=draft.module_id,
                        topic_id=draft.topic_id,
                        front_md=item["front_md"],
                        back_md=item["back_md"],
                        origin="claude",
                        sources=sources,
                        embedding=item.get("embedding"),
                    )
                )
        return len(chosen)

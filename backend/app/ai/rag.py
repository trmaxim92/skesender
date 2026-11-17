"""Department-scoped retrieval for AI context (KB + approved learning examples)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AiLearningExample,
    AiLearningStatus,
    KnowledgeArticle,
    KnowledgeFolder,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    text = _TAG_RE.sub(" ", html or "")
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()


@dataclass
class RagChunk:
    kind: str  # article | example
    ref_id: int
    title: str
    text: str

    def as_source(self) -> dict:
        return {"kind": self.kind, "id": self.ref_id, "title": self.title}


def _score(query: str, title: str, body: str) -> int:
    q = (query or "").lower().strip()
    if not q:
        return 0
    hay = f"{title}\n{body}".lower()
    score = 0
    for token in re.findall(r"[\wа-яёА-ЯЁ]{3,}", q, flags=re.IGNORECASE):
        if token.lower() in hay:
            score += 2 if token.lower() in title.lower() else 1
    if q in hay:
        score += 5
    return score


async def retrieve_context(
    session: AsyncSession,
    *,
    department_id: int | None,
    query: str,
    limit: int = 6,
) -> list[RagChunk]:
    """Top-k published KB articles (dept + global) and approved learning examples."""
    chunks: list[RagChunk] = []

    folder_stmt = select(KnowledgeFolder.id)
    if department_id is not None:
        folder_stmt = folder_stmt.where(
            or_(
                KnowledgeFolder.department_id.is_(None),
                KnowledgeFolder.department_id == department_id,
            )
        )
    else:
        folder_stmt = folder_stmt.where(KnowledgeFolder.department_id.is_(None))
    folder_ids = list((await session.execute(folder_stmt)).scalars().all())

    if folder_ids:
        articles = list(
            (
                await session.execute(
                    select(KnowledgeArticle)
                    .where(
                        KnowledgeArticle.folder_id.in_(folder_ids),
                        KnowledgeArticle.is_published.is_(True),
                    )
                    .order_by(KnowledgeArticle.updated_at.desc())
                    .limit(80)
                )
            )
            .scalars()
            .all()
        )
        ranked: list[tuple[int, KnowledgeArticle, str]] = []
        for article in articles:
            plain = strip_html(article.body_html or "")
            ranked.append((_score(query, article.title or "", plain), article, plain))
        ranked.sort(key=lambda x: x[0], reverse=True)
        for score, article, plain in ranked:
            if score <= 0 and query.strip():
                continue
            chunks.append(
                RagChunk(
                    kind="article",
                    ref_id=article.id,
                    title=article.title or f"Статья #{article.id}",
                    text=plain[:1200],
                )
            )
            if len(chunks) >= limit:
                break

    if department_id is not None and len(chunks) < limit:
        examples = list(
            (
                await session.execute(
                    select(AiLearningExample)
                    .where(
                        AiLearningExample.department_id == department_id,
                        AiLearningExample.status == AiLearningStatus.APPROVED.value,
                    )
                    .order_by(AiLearningExample.created_at.desc())
                    .limit(40)
                )
            )
            .scalars()
            .all()
        )
        ranked_ex: list[tuple[int, AiLearningExample]] = []
        for ex in examples:
            ranked_ex.append(
                (
                    _score(query, ex.user_question or "", ex.operator_answer or ""),
                    ex,
                )
            )
        ranked_ex.sort(key=lambda x: x[0], reverse=True)
        for score, ex in ranked_ex:
            if score <= 0 and query.strip():
                continue
            chunks.append(
                RagChunk(
                    kind="example",
                    ref_id=ex.id,
                    title="Пример ответа оператора",
                    text=f"Клиент: {ex.user_question}\nОператор: {ex.operator_answer}"[:1200],
                )
            )
            if len(chunks) >= limit:
                break

    # If nothing matched query tokens, still give a few recent dept articles.
    if not chunks and folder_ids:
        articles = list(
            (
                await session.execute(
                    select(KnowledgeArticle)
                    .where(
                        KnowledgeArticle.folder_id.in_(folder_ids),
                        KnowledgeArticle.is_published.is_(True),
                    )
                    .order_by(KnowledgeArticle.updated_at.desc())
                    .limit(min(3, limit))
                )
            )
            .scalars()
            .all()
        )
        for article in articles:
            chunks.append(
                RagChunk(
                    kind="article",
                    ref_id=article.id,
                    title=article.title or f"Статья #{article.id}",
                    text=strip_html(article.body_html or "")[:1200],
                )
            )

    return chunks

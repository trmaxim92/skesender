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
_TOKEN_RE = re.compile(r"[\wа-яёА-ЯЁ]{3,}", flags=re.IGNORECASE)

# Long KB articles (тарифы/комиссии) need more than a short head excerpt.
_CHUNK_CHARS = 4500
_TARIFF_CHUNK_CHARS = 7000

# Generic topic expansion (no park-specific facts — only retrieval hints).
_TOPIC_EXPAND: dict[str, tuple[str, ...]] = {
    "тариф": ("тариф", "комисс", "условия", "списан", "выплат", "процент"),
    "комисс": ("комисс", "тариф", "процент", "списан", "условия"),
    "условия": ("условия", "тариф", "комисс", "списан"),
    "заказ": ("заказ", "поездок", "спрос", "яндекс"),
}


def _stem_variants(token: str) -> list[str]:
    variants = [token]
    for suf in ("ами", "ями", "ов", "ев", "ам", "ям", "ах", "ях", "ы", "и", "а", "у", "е"):
        if len(token) > 4 and token.endswith(suf):
            stem = token[: -len(suf)]
            if len(stem) >= 3:
                variants.append(stem)
            break
    return variants


def is_no_orders_query(query: str) -> bool:
    q = (query or "").lower()
    if "заказ" not in q and "поездок" not in q:
        return False
    return any(
        k in q
        for k in (
            "нет",
            "нету",
            "мало",
            "не приход",
            "не идут",
            "пропал",
            "снижен",
            "пустой",
        )
    )


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


def _tokens(query: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(query or "")]


def is_price_objection(query: str) -> bool:
    """Price pushback / negotiation — not a request to list tariffs."""
    q = (query or "").lower().strip()
    if not q:
        return False
    markers = (
        "дорого",
        "дешевл",
        "скидк",
        "снизьте",
        "понизьте",
        "уменьшите",
        "сделайте ниже",
        "сделай ниже",
        "комиссию ниже",
        "комиссия ниже",
        "ниже комисс",
        "другой парк",
        "у другого",
        "конкурент",
        "не устраива",
        "высокая комисс",
        "комиссия высок",
        "слишком больш",
    )
    return any(m in q for m in markers)


def is_tariff_query(query: str) -> bool:
    """Info request about tariffs/commission — excludes price objections."""
    if is_price_objection(query):
        return False
    q = (query or "").lower()
    return any(
        k in q
        for k in (
            "тариф",
            "комисс",
            "условия",
            "вывод",
            "банк",
            "яндекс про",
            "сутки",
            "процент",
        )
    )


def _expanded_tokens(query: str) -> list[str]:
    base = _tokens(query)
    extra: list[str] = []
    q = (query or "").lower()
    for key, syns in _TOPIC_EXPAND.items():
        if key in q or any(key in t for t in base):
            extra.extend(syns)
    # preserve order, unique
    seen: set[str] = set()
    out: list[str] = []
    for t in [*base, *extra]:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _score(query: str, title: str, body: str) -> int:
    q = (query or "").lower().strip()
    if not q:
        return 0
    title_l = (title or "").lower()
    body_l = (body or "").lower()
    hay = f"{title_l}\n{body_l}"
    score = 0
    title_hits = 0
    body_hits = 0
    for token in _expanded_tokens(q):
        matched_title = False
        matched_body = False
        for variant in _stem_variants(token):
            if variant in title_l:
                matched_title = True
            elif variant in body_l:
                matched_body = True
        if matched_title:
            title_hits += 1
            score += 4
        elif matched_body:
            body_hits += 1
            score += 1
    if q in hay:
        score += 5
    if title_hits >= 2:
        score += 8
    if is_tariff_query(q) and any(k in title_l for k in ("тариф", "комисс", "условия")):
        score += 6
    if is_no_orders_query(q):
        if any(k in title_l for k in ("заказ", "спрос", "поездок")):
            score += 10
        # Avoid leaking tariff article into «нет заказов» via weak body hits.
        if any(k in title_l for k in ("комисс", "тариф")) and title_hits == 0:
            score = min(score, 1)
    # Weak single body-token hits are noise.
    if title_hits == 0 and body_hits <= 1 and score < 5:
        return 0
    return score


def _excerpt(text: str, query: str, *, max_chars: int = _CHUNK_CHARS) -> str:
    """Prefer a window around the first query-token hit, not only article head."""
    plain = (text or "").strip()
    if not plain:
        return ""
    if len(plain) <= max_chars:
        return plain
    lower = plain.lower()
    positions: list[int] = []
    for token in _expanded_tokens(query):
        pos = lower.find(token)
        if pos >= 0:
            positions.append(pos)
    if not positions:
        return plain[:max_chars]
    anchor = min(positions)
    # Keep some lead-in before the match.
    start = max(0, anchor - max_chars // 4)
    end = min(len(plain), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    chunk = plain[start:end].strip()
    if start > 0:
        chunk = "… " + chunk
    if end < len(plain):
        chunk = chunk + " …"
    return chunk


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
                    .limit(120)
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
        tariff_q = is_tariff_query(query)
        top_score = ranked[0][0] if ranked else 0
        # Keep only competitive hits so a weak token match (e.g. «заказов»)
        # does not drag unrelated tariff text into a «нет заказов» question.
        min_keep = max(2, top_score - 3) if top_score > 0 else 1
        kept = 0
        for score, article, plain in ranked:
            if score <= 0 and query.strip():
                continue
            if score < min_keep:
                continue
            if tariff_q and kept == 0:
                window = max(_TARIFF_CHUNK_CHARS, min(len(plain) + 32, 12000))
            elif kept == 0:
                window = _CHUNK_CHARS
            else:
                window = max(1800, _CHUNK_CHARS // 2)
            chunks.append(
                RagChunk(
                    kind="article",
                    ref_id=article.id,
                    title=article.title or f"Статья #{article.id}",
                    text=_excerpt(plain, query, max_chars=window),
                )
            )
            kept += 1
            if kept >= limit:
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
                    text=f"Клиент: {ex.user_question}\nОператор: {ex.operator_answer}"[
                        :_CHUNK_CHARS
                    ],
                )
            )
            if len(chunks) >= limit:
                break

    # No silent fallback to random recent articles — that caused off-topic answers.
    return chunks

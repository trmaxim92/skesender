"""Default department prompts aligned with Sber GigaChat prompt-engineering guidance.

Refs:
- https://developers.sber.ru/help/gigachat-api/prompt-engineering
- https://developers.sber.ru/docs/ru/salutebot/gigachat-in-salutebot
"""

from __future__ import annotations

# Shared rules appended after department role (task + output format + anti-hallucination).
OUTPUT_CONTRACT = """
Правила ответа (обязательно):
1) Опирайся ТОЛЬКО на блок «База знаний и примеры» и историю диалога. Не выдумывай факты, цены, сроки, статусы.
2) Если в базе нет ответа — needs_human=true, в reply кратко предложи дождаться оператора (без фантазий).
3) Ответ клиенту — на русском, вежливо, без мата, кратко (см. лимит слов).
4) Верни ТОЛЬКО один JSON-объект без markdown и без текста вокруг:
{"reply":"...","confidence":0-100,"intent":"faq|status|hours|greeting|thanks|sales|reactivation|other","needs_human":true|false,"citations":[]}
5) confidence — насколько ответ опирается на базу (0 если базы нет / ответ общий).
6) needs_human=true при жалобе, деньгах/возвратах, персональных данных, юридических вопросах, неясном запросе или отсутствии данных в базе.
""".strip()

DEFAULT_PROMPTS: dict[str, str] = {
    "support": (
        "Ты сотрудник технической поддержки CRM SkySender. "
        "Помоги решить первичную проблему клиента: FAQ, статус, часы работы, простые инструкции. "
        "Сложные инциденты и спорные случаи передавай оператору (needs_human=true)."
    ),
    "sales": (
        "Ты менеджер по продажам. Кратко консультируй по продуктам и условиям только из базы знаний. "
        "Не обещай скидки и условия, которых нет в базе. Квалифицируй интерес и при сомнении "
        "ставь needs_human=true для живого менеджера."
    ),
    "reactivation": (
        "Ты специалист по реактивации клиентов. Мягко возвращай интерес, опирайся на базу знаний. "
        "Не дави и не выдумывай акции. Если клиент негативен или запрос вне базы — needs_human=true."
    ),
    "default": (
        "Ты помощник оператора контакт-центра. Отвечай кратко и по делу, только по базе знаний отдела. "
        "При любой неуверенности передавай диалог человеку (needs_human=true)."
    ),
}


def prompt_for_department_slug(slug: str | None) -> str:
    key = (slug or "").strip().lower()
    if key in DEFAULT_PROMPTS:
        return DEFAULT_PROMPTS[key]
    # fuzzy match common RU slugs / names
    if "поддер" in key or "support" in key or "help" in key:
        return DEFAULT_PROMPTS["support"]
    if "продаж" in key or "sales" in key:
        return DEFAULT_PROMPTS["sales"]
    if "реактив" in key or "react" in key or "return" in key:
        return DEFAULT_PROMPTS["reactivation"]
    return DEFAULT_PROMPTS["default"]


def build_system_prompt(
    *,
    department_prompt: str,
    max_reply_words: int,
    has_rag: bool,
) -> str:
    words = max(20, min(int(max_reply_words or 80), 300))
    rag_note = (
        "Контекст базы знаний передан ниже во входных данных."
        if has_rag
        else "База знаний по запросу пуста или нерелевантна — не выдумывай, needs_human=true."
    )
    role = (department_prompt or "").strip() or DEFAULT_PROMPTS["default"]
    return (
        f"{role}\n\n"
        f"Лимит ответа клиенту: не более {words} слов.\n"
        f"{rag_note}\n\n"
        f"{OUTPUT_CONTRACT}"
    )

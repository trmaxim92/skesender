"""Infer human-readable performer role from Fleet car categories.

Fleet list API has no `profession` field; create-API professions are:
taxi/driver, cargo/courier/on-car, cargo/courier/on-truck.
We approximate from vehicle categories on the bound car.
"""

from __future__ import annotations

from typing import Any

ROLE_TAXI = "Водитель такси"
ROLE_AUTO_COURIER = "Автокурьер"
ROLE_WALKING = "Пеший курьер"
ROLE_MOTO = "Мотокурьер"
ROLE_CARGO = "Водитель на грузовом"

_TAXI_CATS = frozenset(
    {
        "econom",
        "standart",
        "comfort",
        "comfort_plus",
        "business",
        "vip",
        "ultimate",
        "maybach",
        "premium_suv",
        "premium_van",
        "suv",
        "minivan",
        "personal_driver",
        "intercity",
        "pool",
        "envoy_ultima",
        "summit_b2b",
        "auction",
        "fastmasters_1",
        "fastmasters_2",
        "fastmasters_3",
        "fastmasters_4",
    }
)
_COURIER_CATS = frozenset({"courier", "eda", "lavka"})
# express alone is delivery-ish; with taxi classes it is often just an extra tariff
_EXPRESS = frozenset({"express"})
_CARGO_CATS = frozenset({"cargo"})
_MOTO_CATS = frozenset({"moto", "auction_moto", "tuktuk", "auction_tuktuk"})


def categories_from_row(row: dict[str, Any]) -> set[str]:
    car = row.get("car") if isinstance(row, dict) else None
    if not isinstance(car, dict):
        return set()
    raw = car.get("category") or car.get("categories") or []
    if not isinstance(raw, list):
        return set()
    return {str(x).strip().lower() for x in raw if str(x).strip()}


def infer_performer_role(row: dict[str, Any]) -> str:
    """Return display role(s), e.g. 'Водитель такси · Автокурьер'."""
    cats = categories_from_row(row)
    car = row.get("car") if isinstance(row, dict) else None
    has_car = isinstance(car, dict) and bool(car.get("id") or cats)

    roles: list[str] = []
    if cats & _TAXI_CATS:
        roles.append(ROLE_TAXI)
    if cats & _COURIER_CATS or (cats & _EXPRESS and not (cats & _TAXI_CATS)):
        roles.append(ROLE_AUTO_COURIER)
    if cats & _CARGO_CATS:
        roles.append(ROLE_CARGO)
    if cats & _MOTO_CATS:
        roles.append(ROLE_MOTO)

    if not roles:
        if not has_car:
            return ROLE_WALKING
        return ROLE_TAXI

    # Stable order
    order = [ROLE_TAXI, ROLE_AUTO_COURIER, ROLE_MOTO, ROLE_CARGO, ROLE_WALKING]
    roles_sorted = [r for r in order if r in roles]
    return " · ".join(roles_sorted)

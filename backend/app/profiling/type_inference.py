import re
from datetime import date, datetime, time

from app.domain.dataset_profile import LogicalType as L, PhysicalType as P
from app.domain.dataset_profile import aggregate_logical as combine_logical, aggregate_physical as combine_physical
from .parsers import Cell

INTEGER = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
NUMBER = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")
LEADING_ZERO = re.compile(r"^[+-]?0[0-9]")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$")
ISO_TIME = re.compile(r"^\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$")


def is_missing(value: Cell) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def physical_type(value: Cell) -> P:
    if value is None:
        return P.NULL
    if isinstance(value, bool):
        return P.BOOLEAN
    if isinstance(value, int):
        return P.INTEGER
    if isinstance(value, float):
        return P.FLOAT
    if isinstance(value, datetime):
        return P.DATETIME
    if isinstance(value, date):
        return P.DATE
    if isinstance(value, time):
        return P.TIME
    return P.STRING


def logical_type(value: Cell) -> L:
    kind = physical_type(value)
    if kind != P.STRING:
        return {P.NULL: L.EMPTY, P.BOOLEAN: L.BOOLEAN, P.INTEGER: L.INTEGER, P.FLOAT: L.NUMBER,
                P.DATETIME: L.DATETIME, P.DATE: L.DATE, P.TIME: L.TIME}[kind]
    text = value.strip()
    if text.casefold() in {"true", "false"}:
        return L.BOOLEAN
    # Preserve numeric-looking codes with leading zeroes; do not guess business semantics.
    if LEADING_ZERO.match(text):
        return L.TEXT
    if INTEGER.fullmatch(text):
        return L.INTEGER
    if NUMBER.fullmatch(text):
        return L.NUMBER
    for pattern, parse, result in [(ISO_DATE, date.fromisoformat, L.DATE),
                                    (ISO_DATETIME, datetime.fromisoformat, L.DATETIME),
                                    (ISO_TIME, time.fromisoformat, L.TIME)]:
        if pattern.fullmatch(text):
            try:
                parse(text)
                return result
            except ValueError:
                pass
    return L.TEXT


def value_key(value: Cell) -> tuple[str, str]:
    # Match exact parsed values and types. Never coalesce bool/int, numeric/text or padded strings.
    if value is None:
        return ("null", "")
    kind = physical_type(value)
    return (kind.value, value.isoformat() if isinstance(value, (datetime, date, time)) else repr(value))

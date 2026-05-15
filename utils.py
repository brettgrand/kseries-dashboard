from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime


SERIES_ROOT_PATTERN = re.compile(r"^\d+\.\d+$")


def is_series_root_number(value: str) -> bool:
    return bool(SERIES_ROOT_PATTERN.fullmatch(value))


def series_sort_key(series_name: str) -> tuple[int, int]:
    major_str, minor_str = series_name.split(".", maxsplit=1)
    return int(major_str), int(minor_str)


def parse_last_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None

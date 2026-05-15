from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import requests
import yaml
from flask import request, url_for

from models import DashboardError, KernelSeriesSnapshot
from utils import parse_last_modified, series_sort_key


BASE_URL = "https://kernel.ubuntu.com/info/"
LIVE_YAML_NAME = "kernel-series.yaml"
ARCHIVE_PATTERN = re.compile(r"kernel-series\.yaml@(\d{4}\.\d{2}\.\d{2})")
REQUEST_TIMEOUT = 20


def list_available_snapshots(session: requests.Session) -> list[str]:
    try:
        response = session.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return [LIVE_YAML_NAME]

    candidates = sorted(set(ARCHIVE_PATTERN.findall(response.text)), reverse=True)
    names = [LIVE_YAML_NAME] + [f"{LIVE_YAML_NAME}@{stamp}" for stamp in candidates]
    return names


def load_snapshot(source_name: str, session: requests.Session) -> KernelSeriesSnapshot:
    source_url = f"{BASE_URL}{source_name}"

    try:
        response = session.get(source_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise DashboardError(f"Unable to fetch {source_name}: {exc}") from exc

    try:
        parsed_yaml = yaml.safe_load(response.text)
    except yaml.YAMLError as exc:
        raise DashboardError(f"Unable to parse YAML from {source_name}: {exc}") from exc

    if not isinstance(parsed_yaml, dict):
        raise DashboardError(f"Unexpected YAML shape from {source_name}; expected a mapping")

    return KernelSeriesSnapshot(
        source_name=source_name,
        source_url=source_url,
        last_modified=parse_last_modified(response.headers.get("Last-Modified")),
        fetched_at=datetime.now(timezone.utc),
        raw_yaml=response.text,
        series_map=parsed_yaml,
    )


def load_latest_snapshot() -> KernelSeriesSnapshot:
    session = requests.Session()
    source_name = find_latest_archived_yaml_name(session)
    return load_snapshot(source_name, session)


def _load_requested_snapshot() -> KernelSeriesSnapshot:
    session = requests.Session()
    available = list_available_snapshots(session)
    requested = request.args.get("snapshot", "")
    name = requested if requested in available else available[0]
    return load_snapshot(name, session)


def find_latest_archived_yaml_name(session: requests.Session) -> str:
    try:
        response = session.get(BASE_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return LIVE_YAML_NAME

    candidates = ARCHIVE_PATTERN.findall(response.text)
    if not candidates:
        return LIVE_YAML_NAME

    latest_stamp = max(candidates)
    return f"{LIVE_YAML_NAME}@{latest_stamp}"


def build_series_cards(series_map: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    for series_name, details in sorted(series_map.items(), key=lambda item: (
        0 if (isinstance(item[1], dict) and item[1].get("development")) else
        1 if (isinstance(item[1], dict) and item[1].get("supported")) else
        2,
        tuple(-x for x in series_sort_key(item[0])),
    )):
        field_names = sorted(details.keys()) if isinstance(details, dict) else []
        opening = details.get("opening") if isinstance(details, dict) else None
        opening_steps = sorted(opening.keys()) if isinstance(opening, dict) else []
        sources = details.get("sources") if isinstance(details, dict) else None
        source_names = sorted(sources.keys()) if isinstance(sources, dict) else []
        source_links = [
            {
                "name": source_name,
                "url": url_for("source_detail", series_name=series_name, source_name=source_name),
            }
            for source_name in source_names
        ]
        rendered_yaml = yaml.safe_dump({series_name: details}, sort_keys=False, allow_unicode=False)

        cards.append(
            {
                "series_name": series_name,
                "codename": details.get("codename", "unknown") if isinstance(details, dict) else "n/a",
                "supported": bool(details.get("supported")) if isinstance(details, dict) else False,
                "development": bool(details.get("development")) if isinstance(details, dict) else False,
                "lts": bool(details.get("lts")) if isinstance(details, dict) else False,
                "esm": bool(details.get("esm")) if isinstance(details, dict) else False,
                "opening_steps": opening_steps,
                "field_count": len(field_names),
                "field_names": field_names,
                "source_count": len(source_names),
                "source_names": source_names[:8],
                "source_links": source_links,
                "yaml_block": rendered_yaml,
            }
        )

    return cards

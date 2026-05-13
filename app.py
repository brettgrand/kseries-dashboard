from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests
import yaml
from flask import Flask, render_template


BASE_URL = "https://kernel.ubuntu.com/info/"
LIVE_YAML_NAME = "kernel-series.yaml"
ARCHIVE_PATTERN = re.compile(r"kernel-series\.yaml@(\d{4}\.\d{2}\.\d{2})")
REQUEST_TIMEOUT = 20


class DashboardError(RuntimeError):
    pass


@dataclass
class KernelSeriesSnapshot:
    source_name: str
    source_url: str
    last_modified: datetime | None
    fetched_at: datetime
    raw_yaml: str
    series_map: dict[str, Any]

    @property
    def total_series(self) -> int:
        return len(self.series_map)

    @property
    def supported_series(self) -> int:
        return sum(1 for details in self.series_map.values() if details.get("supported"))

    @property
    def development_series(self) -> int:
        return sum(1 for details in self.series_map.values() if details.get("development"))


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        try:
            snapshot = load_latest_snapshot()
            series_cards = build_series_cards(snapshot.series_map)
            return render_template("index.html", snapshot=snapshot, series_cards=series_cards, error_message=None)
        except DashboardError as exc:
            return render_template("index.html", snapshot=None, series_cards=[], error_message=str(exc)), 502

    return app


def load_latest_snapshot() -> KernelSeriesSnapshot:
    session = requests.Session()
    source_name = find_latest_archived_yaml_name(session)
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


def parse_last_modified(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def build_series_cards(series_map: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    for series_name, details in sorted(series_map.items(), reverse=True):
        if not isinstance(details, dict):
            continue

        opening = details.get("opening")
        opening_steps = sorted(opening.keys()) if isinstance(opening, dict) else []
        sources = details.get("sources")
        source_names = sorted(sources.keys()) if isinstance(sources, dict) else []

        cards.append(
            {
                "series_name": series_name,
                "codename": details.get("codename", "unknown"),
                "supported": bool(details.get("supported")),
                "development": bool(details.get("development")),
                "lts": bool(details.get("lts")),
                "esm": bool(details.get("esm")),
                "opening_steps": opening_steps,
                "source_count": len(source_names),
                "source_names": source_names[:8],
            }
        )

    return cards


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
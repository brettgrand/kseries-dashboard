from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests
import yaml
from flask import Flask, abort, render_template, request, url_for


BASE_URL = "https://kernel.ubuntu.com/info/"
LIVE_YAML_NAME = "kernel-series.yaml"
ARCHIVE_PATTERN = re.compile(r"kernel-series\.yaml@(\d{4}\.\d{2}\.\d{2})")
SERIES_ROOT_PATTERN = re.compile(r"^\d+\.\d+$")
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
        return len(self.filtered_series_map)

    @property
    def supported_series(self) -> int:
        return sum(1 for details in self.filtered_series_map.values() if details.get("supported"))

    @property
    def development_series(self) -> int:
        return sum(1 for details in self.filtered_series_map.values() if details.get("development"))

    @property
    def filtered_series_map(self) -> dict[str, Any]:
        return {
            series_name: details
            for series_name, details in self.series_map.items()
            if is_series_root_number(series_name)
        }


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index() -> str:
        try:
            session = requests.Session()
            available_snapshots = list_available_snapshots(session)
            requested = request.args.get("snapshot", "")
            selected_name = requested if requested in available_snapshots else available_snapshots[0]
            snapshot = load_snapshot(selected_name, session)
            series_cards = build_series_cards(snapshot.filtered_series_map)
            return render_template("index.html", snapshot=snapshot, series_cards=series_cards, error_message=None, available_snapshots=available_snapshots)
        except DashboardError as exc:
            return render_template("index.html", snapshot=None, series_cards=[], error_message=str(exc), available_snapshots=[]), 502

    @app.route("/series/<series_name>/source/<path:source_name>")
    def source_detail(series_name: str, source_name: str) -> str:
        try:
            snapshot = load_latest_snapshot()
        except DashboardError as exc:
            return render_template("index.html", snapshot=None, series_cards=[], error_message=str(exc)), 502

        series_details = snapshot.filtered_series_map.get(series_name)
        if not isinstance(series_details, dict):
            abort(404)

        sources = series_details.get("sources")
        if not isinstance(sources, dict):
            abort(404)

        source_details = sources.get(source_name)
        if source_details is None:
            abort(404)

        source_field_names = sorted(source_details.keys()) if isinstance(source_details, dict) else []
        raw_packages = source_details.get("packages", {}) if isinstance(source_details, dict) else {}
        if not isinstance(raw_packages, dict):
            raw_packages = {}
        source_packages = [
            {
                "name": pkg_name,
                "repo": (pkg_data.get("repo") or [None])[0] if isinstance(pkg_data, dict) else None,
                "yaml": yaml.safe_dump(pkg_data, sort_keys=False, allow_unicode=False) if isinstance(pkg_data, dict) else str(pkg_data),
                "url": url_for("package_detail", series_name=series_name, source_name=source_name, package_name=pkg_name),
            }
            for pkg_name, pkg_data in sorted(raw_packages.items())
        ]
        raw_snaps = source_details.get("snaps", {}) if isinstance(source_details, dict) else {}
        if not isinstance(raw_snaps, dict):
            raw_snaps = {}
        source_snaps = [
            {
                "name": snap_name,
                "repo": (snap_data.get("repo") or [None])[0] if isinstance(snap_data, dict) else None,
                "yaml": yaml.safe_dump(snap_data, sort_keys=False, allow_unicode=False) if isinstance(snap_data, dict) else str(snap_data),
                "url": url_for("snap_detail", series_name=series_name, source_name=source_name, snap_name=snap_name),
            }
            for snap_name, snap_data in sorted(raw_snaps.items())
        ]
        raw_testing = source_details.get("testing", {}) if isinstance(source_details, dict) else {}
        if not isinstance(raw_testing, dict):
            raw_testing = {}
        raw_flavours = raw_testing.get("flavours", {}) if isinstance(raw_testing, dict) else {}
        if not isinstance(raw_flavours, dict):
            raw_flavours = {}
        source_flavours = [
            {
                "name": flavour_name,
                "url": url_for("flavour_detail", series_name=series_name, source_name=source_name, flavour_name=flavour_name),
            }
            for flavour_name in sorted(raw_flavours.keys())
        ]
        source_testing = [
            {"key": k, "yaml": yaml.safe_dump(v, sort_keys=False, allow_unicode=False)}
            for k, v in sorted(raw_testing.items())
            if k != "flavours"
        ]
        source_yaml = yaml.safe_dump({source_name: source_details}, sort_keys=False, allow_unicode=False)

        return render_template(
            "source.html",
            snapshot=snapshot,
            series_name=series_name,
            codename=series_details.get("codename", "unknown"),
            supported=bool(series_details.get("supported")),
            development=bool(series_details.get("development")),
            source_name=source_name,
            source_owner=source_details.get("owner") if isinstance(source_details, dict) else None,
            source_swm=source_details.get("swm") if isinstance(source_details, dict) else None,
            source_versions=source_details.get("versions") if isinstance(source_details, dict) else None,
            source_variants=source_details.get("variants") if isinstance(source_details, dict) else None,
            source_package_relations=source_details.get("package-relations") if isinstance(source_details, dict) else None,
            source_derived_from=source_details.get("derived-from") if isinstance(source_details, dict) else None,
            source_invalid_tasks=source_details.get("invalid-tasks") if isinstance(source_details, dict) else None,
            source_routing=source_details.get("routing") if isinstance(source_details, dict) else None,
            source_packages=source_packages,
            source_snaps=source_snaps,
            source_flavours=source_flavours,
            source_testing=source_testing,
            source_yaml=source_yaml,
            source_field_names=source_field_names,
        )

    @app.route("/series/<series_name>/source/<source_name>/flavour/<flavour_name>")
    def flavour_detail(series_name: str, source_name: str, flavour_name: str) -> str:
        try:
            snapshot = load_latest_snapshot()
        except DashboardError as exc:
            return render_template("index.html", snapshot=None, series_cards=[], error_message=str(exc)), 502

        series_details = snapshot.filtered_series_map.get(series_name)
        if not isinstance(series_details, dict):
            abort(404)

        sources = series_details.get("sources")
        if not isinstance(sources, dict):
            abort(404)

        source_details = sources.get(source_name)
        if not isinstance(source_details, dict):
            abort(404)

        raw_testing = source_details.get("testing", {})
        if not isinstance(raw_testing, dict):
            abort(404)

        raw_flavours = raw_testing.get("flavours", {})
        if not isinstance(raw_flavours, dict):
            abort(404)

        flavour_data = raw_flavours.get(flavour_name)
        if flavour_data is None:
            abort(404)

        flavour_yaml = yaml.safe_dump({flavour_name: flavour_data}, sort_keys=False, allow_unicode=False)

        return render_template(
            "flavour.html",
            snapshot=snapshot,
            series_name=series_name,
            codename=series_details.get("codename", "unknown"),
            source_name=source_name,
            flavour_name=flavour_name,
            flavour_yaml=flavour_yaml,
            flavour_data=flavour_data if isinstance(flavour_data, dict) else {},
        )

    @app.route("/series/<series_name>/source/<source_name>/snap/<snap_name>")
    def snap_detail(series_name: str, source_name: str, snap_name: str) -> str:
        try:
            snapshot = load_latest_snapshot()
        except DashboardError as exc:
            return render_template("index.html", snapshot=None, series_cards=[], error_message=str(exc)), 502

        series_details = snapshot.filtered_series_map.get(series_name)
        if not isinstance(series_details, dict):
            abort(404)

        sources = series_details.get("sources")
        if not isinstance(sources, dict):
            abort(404)

        source_details = sources.get(source_name)
        if not isinstance(source_details, dict):
            abort(404)

        raw_snaps = source_details.get("snaps", {})
        if not isinstance(raw_snaps, dict):
            abort(404)

        snap_data = raw_snaps.get(snap_name)
        if snap_data is None:
            abort(404)

        snap_repo = (snap_data.get("repo") or [None])[0] if isinstance(snap_data, dict) else None
        snap_yaml = yaml.safe_dump({snap_name: snap_data}, sort_keys=False, allow_unicode=False)

        return render_template(
            "snap.html",
            snapshot=snapshot,
            series_name=series_name,
            codename=series_details.get("codename", "unknown"),
            source_name=source_name,
            snap_name=snap_name,
            snap_repo=snap_repo,
            snap_yaml=snap_yaml,
            snap_data=snap_data if isinstance(snap_data, dict) else {},
        )

    @app.route("/series/<series_name>/source/<source_name>/package/<package_name>")
    def package_detail(series_name: str, source_name: str, package_name: str) -> str:
        try:
            snapshot = load_latest_snapshot()
        except DashboardError as exc:
            return render_template("index.html", snapshot=None, series_cards=[], error_message=str(exc)), 502

        series_details = snapshot.filtered_series_map.get(series_name)
        if not isinstance(series_details, dict):
            abort(404)

        sources = series_details.get("sources")
        if not isinstance(sources, dict):
            abort(404)

        source_details = sources.get(source_name)
        if not isinstance(source_details, dict):
            abort(404)

        raw_packages = source_details.get("packages", {})
        if not isinstance(raw_packages, dict):
            abort(404)

        pkg_data = raw_packages.get(package_name)
        if pkg_data is None:
            abort(404)

        pkg_repo = (pkg_data.get("repo") or [None])[0] if isinstance(pkg_data, dict) else None
        pkg_yaml = yaml.safe_dump({package_name: pkg_data}, sort_keys=False, allow_unicode=False)

        return render_template(
            "package.html",
            snapshot=snapshot,
            series_name=series_name,
            codename=series_details.get("codename", "unknown"),
            source_name=source_name,
            package_name=package_name,
            pkg_repo=pkg_repo,
            pkg_yaml=pkg_yaml,
            pkg_data=pkg_data if isinstance(pkg_data, dict) else {},
        )

    return app


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


def is_series_root_number(value: str) -> bool:
    return bool(SERIES_ROOT_PATTERN.fullmatch(value))


def series_sort_key(series_name: str) -> tuple[int, int]:
    major_str, minor_str = series_name.split(".", maxsplit=1)
    return int(major_str), int(minor_str)


def build_series_cards(series_map: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    for series_name, details in sorted(series_map.items(), key=lambda item: (not (isinstance(item[1], dict) and item[1].get("supported")), tuple(-x for x in series_sort_key(item[0])))):
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


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
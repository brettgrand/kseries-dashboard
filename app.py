from __future__ import annotations

import os

import requests
import yaml
from flask import Flask, abort, render_template, request, url_for

from data import (
    _load_requested_snapshot,
    build_series_cards,
    list_available_snapshots,
    load_snapshot,
)
from models import DashboardError


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
            snapshot = _load_requested_snapshot()
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
            snapshot = _load_requested_snapshot()
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
            snapshot = _load_requested_snapshot()
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
            snapshot = _load_requested_snapshot()
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


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
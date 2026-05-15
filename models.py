from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


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
        from utils import is_series_root_number
        return {
            series_name: details
            for series_name, details in self.series_map.items()
            if is_series_root_number(series_name)
        }

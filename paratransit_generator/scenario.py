from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Dict, List

from .models import ScenarioBlueprint, ScenarioInput

ZONES: List[str] = [
    "Central",
    "North",
    "South",
    "East",
    "West",
    "Airport",
    "Hillside",
]

ZONE_NEIGHBORS: Dict[str, List[str]] = {
    "Central": ["North", "South", "East", "West", "Hillside"],
    "North": ["Central", "East", "West", "Hillside"],
    "South": ["Central", "East", "West", "Airport"],
    "East": ["Central", "North", "South", "Airport"],
    "West": ["Central", "North", "South", "Hillside"],
    "Airport": ["South", "East", "Central"],
    "Hillside": ["North", "West", "Central"],
}

TRAVEL_MINUTES: Dict[str, Dict[str, int]] = {
    "Central": {"Central": 10, "North": 18, "South": 22, "East": 16, "West": 20, "Airport": 30, "Hillside": 24},
    "North": {"Central": 18, "North": 9, "South": 34, "East": 20, "West": 23, "Airport": 38, "Hillside": 18},
    "South": {"Central": 22, "North": 34, "South": 11, "East": 21, "West": 24, "Airport": 26, "Hillside": 33},
    "East": {"Central": 16, "North": 20, "South": 21, "East": 8, "West": 31, "Airport": 21, "Hillside": 28},
    "West": {"Central": 20, "North": 23, "South": 24, "East": 31, "West": 9, "Airport": 35, "Hillside": 15},
    "Airport": {"Central": 30, "North": 38, "South": 26, "East": 21, "West": 35, "Airport": 12, "Hillside": 39},
    "Hillside": {"Central": 24, "North": 18, "South": 33, "East": 28, "West": 15, "Airport": 39, "Hillside": 10},
}

ISSUE_CATALOG: List[str] = [
    "overloaded_runs",
    "poor_trip_clustering",
    "unrealistic_scheduling",
    "driver_callouts",
    "driver_lateness",
    "vehicle_breakdowns",
    "dispatch_delays",
    "zone_hotspots",
    "dialysis_banks",
    "will_call_backlog",
    "wheelchair_capacity_shortage",
    "same_day_add_ons",
    "garage_pullout_delays",
    "relief_failures",
]

ISSUE_DISPLAY_NAMES: Dict[str, str] = {
    "overloaded_runs": "Overloaded runs",
    "poor_trip_clustering": "Poor trip clustering",
    "unrealistic_scheduling": "Unrealistic scheduling",
    "driver_callouts": "Driver callouts",
    "driver_lateness": "Driver lateness",
    "vehicle_breakdowns": "Vehicle breakdowns",
    "dispatch_delays": "Dispatch delays",
    "zone_hotspots": "Zone-specific performance hotspots",
    "dialysis_banks": "Dialysis trip banks",
    "will_call_backlog": "Will-call return backlog",
    "wheelchair_capacity_shortage": "Wheelchair capacity shortage",
    "same_day_add_ons": "Same-day add-ons",
    "garage_pullout_delays": "Garage pullout delays",
    "relief_failures": "Relief failures",
}


def build_blueprint(config: ScenarioInput, rng: random.Random) -> ScenarioBlueprint:
    service_dates = list(_daterange(config.start_date, config.end_date))
    issue_count = max(5, min(len(ISSUE_CATALOG), math.ceil(len(service_dates) / 8) + 3))
    root_issues = sorted(rng.sample(ISSUE_CATALOG, k=issue_count))

    hotspot_zone_count = 2 if rng.random() < 0.55 else 1
    hotspot_zones = rng.sample(ZONES, k=hotspot_zone_count)
    will_call_zones = sorted(rng.sample(ZONES, k=2))
    dialysis_peak_weekdays = sorted(rng.sample([0, 1, 2, 3, 4], k=2 if rng.random() < 0.65 else 3))

    hotspot_days = max(2, math.ceil(len(service_dates) * rng.uniform(0.18, 0.34)))
    hotspot_dates = set(rng.sample(service_dates, k=min(hotspot_days, len(service_dates))))

    zone_delay_multipliers = {
        zone: round(1.0 + rng.uniform(0.08, 0.28), 3) if zone in hotspot_zones else round(1.0 + rng.uniform(0.0, 0.08), 3)
        for zone in ZONES
    }
    zone_demand_multipliers = {
        zone: round(1.0 + rng.uniform(0.12, 0.30), 3) if zone in hotspot_zones else round(1.0 + rng.uniform(-0.04, 0.09), 3)
        for zone in ZONES
    }

    demand_by_date = _allocate_trips_by_date(
        service_dates,
        config.trip_count,
        root_issues,
        hotspot_dates,
        dialysis_peak_weekdays,
        rng,
    )

    def rate(issue_name: str, low: float, high: float, default_low: float, default_high: float) -> float:
        if issue_name in root_issues:
            return rng.uniform(low, high)
        return rng.uniform(default_low, default_high)

    return ScenarioBlueprint(
        seed=rng.randint(100000, 999999),
        root_issues=root_issues,
        hotspot_zones=hotspot_zones,
        hotspot_dates=hotspot_dates,
        dialysis_peak_weekdays=dialysis_peak_weekdays,
        will_call_zones=will_call_zones,
        demand_by_date=demand_by_date,
        zone_delay_multipliers=zone_delay_multipliers,
        zone_demand_multipliers=zone_demand_multipliers,
        overloaded_run_rate=rate("overloaded_runs", 0.22, 0.37, 0.08, 0.15),
        poor_clustering_rate=rate("poor_trip_clustering", 0.20, 0.34, 0.05, 0.12),
        unrealistic_schedule_rate=rate("unrealistic_scheduling", 0.18, 0.32, 0.04, 0.10),
        callout_rate=rate("driver_callouts", 0.05, 0.12, 0.01, 0.03),
        driver_lateness_rate=rate("driver_lateness", 0.14, 0.26, 0.05, 0.10),
        breakdown_rate=rate("vehicle_breakdowns", 0.05, 0.11, 0.01, 0.03),
        dispatch_delay_rate=rate("dispatch_delays", 0.16, 0.30, 0.05, 0.10),
        dialysis_bank_rate=rate("dialysis_banks", 0.28, 0.48, 0.08, 0.16),
        will_call_rate=rate("will_call_backlog", 0.22, 0.38, 0.06, 0.12),
        same_day_addon_rate=rate("same_day_add_ons", 0.18, 0.32, 0.05, 0.10),
        garage_delay_rate=rate("garage_pullout_delays", 0.14, 0.26, 0.04, 0.08),
        wheelchair_capacity_rate=rate("wheelchair_capacity_shortage", 0.14, 0.28, 0.03, 0.07),
        relief_failure_rate=rate("relief_failures", 0.10, 0.22, 0.02, 0.05),
        complaint_pressure=1.0 + rng.uniform(0.18, 0.36),
    )


def travel_minutes(origin: str, destination: str) -> int:
    return TRAVEL_MINUTES[origin][destination]


def is_neighbor(zone_a: str, zone_b: str) -> bool:
    return zone_a == zone_b or zone_b in ZONE_NEIGHBORS[zone_a]


def issue_display_names(issue_codes: List[str]) -> List[str]:
    return [ISSUE_DISPLAY_NAMES.get(issue_code, issue_code.replace("_", " ").title()) for issue_code in issue_codes]


def _allocate_trips_by_date(
    service_dates: List[date],
    trip_count: int,
    root_issues: List[str],
    hotspot_dates: set[date],
    dialysis_peak_weekdays: List[int],
    rng: random.Random,
) -> Dict[date, int]:
    raw_weights: List[float] = []
    for service_date in service_dates:
        weekday = service_date.weekday()
        if weekday <= 3:
            weight = rng.uniform(1.08, 1.28)
        elif weekday == 4:
            weight = rng.uniform(1.00, 1.16)
        elif weekday == 5:
            weight = rng.uniform(0.72, 0.92)
        else:
            weight = rng.uniform(0.52, 0.74)

        if "zone_hotspots" in root_issues and service_date in hotspot_dates:
            weight *= rng.uniform(1.18, 1.38)
        if "dispatch_delays" in root_issues and weekday in (0, 1):
            weight *= rng.uniform(1.04, 1.14)
        if "dialysis_banks" in root_issues and weekday in dialysis_peak_weekdays:
            weight *= rng.uniform(1.10, 1.24)
        if "same_day_add_ons" in root_issues and weekday <= 4:
            weight *= rng.uniform(1.03, 1.10)
        if "will_call_backlog" in root_issues and weekday in (3, 4):
            weight *= rng.uniform(1.04, 1.12)
        raw_weights.append(weight)

    total_weight = sum(raw_weights)
    allocations: Dict[date, int] = {}
    remainders: List[tuple[float, date]] = []
    assigned = 0
    for service_date, weight in zip(service_dates, raw_weights):
        exact = trip_count * weight / total_weight
        base = max(1, math.floor(exact))
        allocations[service_date] = base
        assigned += base
        remainders.append((exact - base, service_date))

    if assigned > trip_count:
        for _, service_date in sorted(remainders, key=lambda item: item[0]):
            if assigned == trip_count:
                break
            if allocations[service_date] > 1:
                allocations[service_date] -= 1
                assigned -= 1
    else:
        for _, service_date in sorted(remainders, key=lambda item: item[0], reverse=True):
            if assigned == trip_count:
                break
            allocations[service_date] += 1
            assigned += 1

    return allocations


def _daterange(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)

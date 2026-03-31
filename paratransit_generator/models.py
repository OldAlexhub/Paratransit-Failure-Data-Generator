from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd


@dataclass(slots=True)
class ScenarioInput:
    start_date: date
    end_date: date
    trip_count: int

    def validate(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("End date must be on or after the start date.")
        if self.trip_count <= 0:
            raise ValueError("Number of records must be greater than zero.")


@dataclass(slots=True)
class ScenarioBlueprint:
    seed: int
    root_issues: List[str]
    hotspot_zones: List[str]
    hotspot_dates: set[date]
    dialysis_peak_weekdays: List[int]
    will_call_zones: List[str]
    demand_by_date: Dict[date, int]
    zone_delay_multipliers: Dict[str, float]
    zone_demand_multipliers: Dict[str, float]
    overloaded_run_rate: float
    poor_clustering_rate: float
    unrealistic_schedule_rate: float
    callout_rate: float
    driver_lateness_rate: float
    breakdown_rate: float
    dispatch_delay_rate: float
    dialysis_bank_rate: float
    will_call_rate: float
    same_day_addon_rate: float
    garage_delay_rate: float
    wheelchair_capacity_rate: float
    relief_failure_rate: float
    complaint_pressure: float


@dataclass(slots=True)
class DriverProfile:
    driver_id: str
    driver_name: str
    home_zone: str
    certification_level: str
    hire_date: date
    reliability_score: float


@dataclass(slots=True)
class VehicleProfile:
    vehicle_id: str
    vehicle_type: str
    seated_capacity: int
    wheelchair_capacity: int
    depot: str
    lift_equipped: bool
    odometer_base: int
    maintenance_due_in_days: int


@dataclass(slots=True)
class RunPlan:
    run_id: str
    service_date: date
    dispatcher_id: str
    primary_zone: str
    service_wave: str
    scheduled_driver_id: str
    actual_driver_id: str
    backup_driver_id: Optional[str]
    scheduled_vehicle_id: str
    actual_vehicle_id: str
    backup_vehicle_id: Optional[str]
    scheduled_start: datetime
    scheduled_end: datetime
    trip_count: int
    issues: set[str] = field(default_factory=set)
    manifest_release_time: Optional[datetime] = None
    driver_delay_minutes: int = 0
    dispatch_delay_minutes: int = 0
    garage_delay_minutes: int = 0
    breakdown_after_trip: Optional[int] = None
    breakdown_delay_minutes: int = 0
    vehicle_swap_delay_minutes: int = 0
    callout_notice_time: Optional[datetime] = None
    late_notice_time: Optional[datetime] = None


@dataclass(slots=True)
class GeneratedData:
    dataframes: Dict[str, pd.DataFrame]
    seed: int
    generated_at: datetime
    analysis_targets: List[str]

    @property
    def trips(self) -> pd.DataFrame:
        return self.dataframes["trips"]

    @property
    def runs(self) -> pd.DataFrame:
        return self.dataframes["runs"]

    @property
    def drivers(self) -> pd.DataFrame:
        return self.dataframes["drivers"]

    @property
    def vehicles(self) -> pd.DataFrame:
        return self.dataframes["vehicles"]

    @property
    def dispatch_events(self) -> pd.DataFrame:
        return self.dataframes["dispatch_events"]

    @property
    def complaints(self) -> pd.DataFrame:
        return self.dataframes["complaints"]

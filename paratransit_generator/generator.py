from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from .models import DriverProfile, GeneratedData, RunPlan, ScenarioInput, VehicleProfile
from .scenario import ZONES, build_blueprint, is_neighbor, issue_display_names, travel_minutes

FIRST_NAMES = [
    "Alicia",
    "Andre",
    "Bianca",
    "Carlos",
    "Darnell",
    "Elena",
    "Felicia",
    "Greg",
    "Hector",
    "Imani",
    "Janelle",
    "Keith",
    "Lena",
    "Marcus",
    "Nadia",
    "Oscar",
    "Patrice",
    "Quentin",
    "Rosa",
    "Sonia",
    "Terrence",
    "Vanessa",
    "Walter",
    "Yvette",
]

LAST_NAMES = [
    "Adams",
    "Brooks",
    "Carter",
    "Diaz",
    "Ellis",
    "Flores",
    "Garcia",
    "Hill",
    "Jackson",
    "Kelly",
    "Lopez",
    "Miller",
    "Nguyen",
    "Owens",
    "Parker",
    "Reed",
    "Simmons",
    "Turner",
    "Vargas",
    "Walker",
    "Young",
]

TRIP_PURPOSES = [
    ("medical", 0.30),
    ("dialysis", 0.15),
    ("employment", 0.17),
    ("day_program", 0.14),
    ("nutrition", 0.08),
    ("personal", 0.10),
    ("shopping", 0.06),
]

MOBILITY_AIDS = [
    ("ambulatory", 0.45),
    ("walker", 0.20),
    ("wheelchair", 0.24),
    ("scooter", 0.08),
    ("pca_assist", 0.03),
]

VEHICLE_TYPES = [
    ("cutaway_bus", 10, 2, True),
    ("wheelchair_van", 6, 2, True),
    ("minivan", 5, 0, False),
]

COMPLAINT_CHANNELS = ["phone", "web", "email", "supervisor"]
DISPATCHERS = ["DSP-01", "DSP-02", "DSP-03", "DSP-04", "DSP-05"]
DEPOTS = ["North Depot", "Central Yard", "South Garage"]
SHIFT_STATUS = {
    "assigned": "assigned",
    "callout": "callout",
    "coverage": "coverage",
}


class ParatransitDataGenerator:
    def __init__(self) -> None:
        self._system_rng = random.SystemRandom()

    def generate(self, config: ScenarioInput) -> GeneratedData:
        config.validate()
        seed = self._system_rng.randint(10_000_000, 99_999_999)
        rng = random.Random(seed)
        blueprint = build_blueprint(config, rng)

        drivers = self._build_driver_profiles(config.trip_count, config.start_date, rng)
        vehicles = self._build_vehicle_profiles(config.trip_count, blueprint, rng)
        drivers_by_id = {driver.driver_id: driver for driver in drivers}
        vehicles_by_id = {vehicle.vehicle_id: vehicle for vehicle in vehicles}

        trip_rows: List[dict] = []
        run_rows: List[dict] = []
        driver_rows: List[dict] = []
        vehicle_rows: List[dict] = []
        dispatch_rows: List[dict] = []
        counters = defaultdict(int)
        driver_cursor = 0
        vehicle_cursor = 0

        for service_date, daily_trip_count in sorted(blueprint.demand_by_date.items()):
            day_runs, driver_cursor, vehicle_cursor = self._plan_runs_for_day(
                service_date=service_date,
                trip_count=daily_trip_count,
                blueprint=blueprint,
                drivers=drivers,
                vehicles=vehicles,
                driver_cursor=driver_cursor,
                vehicle_cursor=vehicle_cursor,
                rng=rng,
                counters=counters,
            )
            for run_plan in day_runs:
                run_result = self._simulate_run(
                    run_plan=run_plan,
                    blueprint=blueprint,
                    drivers_by_id=drivers_by_id,
                    vehicles_by_id=vehicles_by_id,
                    rng=rng,
                    counters=counters,
                )
                trip_rows.extend(run_result["trip_rows"])
                run_rows.append(run_result["run_row"])
                driver_rows.extend(run_result["driver_rows"])
                vehicle_rows.extend(run_result["vehicle_rows"])
                dispatch_rows.extend(run_result["dispatch_rows"])

        complaint_rows = self._generate_complaints(trip_rows, dispatch_rows, blueprint, rng, counters)
        self._append_complaint_dispatch_events(complaint_rows, dispatch_rows, rng, counters)

        complaints_df = pd.DataFrame(
            complaint_rows,
            columns=[
                "complaint_id",
                "complaint_timestamp",
                "service_date",
                "trip_id",
                "run_id",
                "customer_id",
                "origin_zone",
                "destination_zone",
                "complaint_channel",
                "complaint_type",
                "reported_by",
                "complaint_status",
                "closed_timestamp",
                "refund_amount",
            ],
        )
        if not complaints_df.empty:
            complaints_df = complaints_df.sort_values(["complaint_timestamp", "complaint_id"]).reset_index(drop=True)

        dataframes = {
            "trips": pd.DataFrame(trip_rows).sort_values(["service_date", "scheduled_pickup_time", "trip_id"]).reset_index(drop=True),
            "runs": pd.DataFrame(run_rows).sort_values(["service_date", "scheduled_start", "run_id"]).reset_index(drop=True),
            "drivers": pd.DataFrame(driver_rows).sort_values(["service_date", "scheduled_start", "driver_shift_id"]).reset_index(drop=True),
            "vehicles": pd.DataFrame(vehicle_rows).sort_values(["service_date", "scheduled_pullout_time", "vehicle_service_id"]).reset_index(drop=True),
            "dispatch_events": pd.DataFrame(dispatch_rows).sort_values(["event_timestamp", "event_id"]).reset_index(drop=True),
            "complaints": complaints_df,
        }
        return GeneratedData(
            dataframes=dataframes,
            seed=seed,
            generated_at=datetime.now().replace(microsecond=0),
            analysis_targets=issue_display_names(blueprint.root_issues),
        )

    def _build_driver_profiles(self, trip_count: int, start_date: date, rng: random.Random) -> List[DriverProfile]:
        driver_count = max(18, math.ceil(trip_count / 12))
        profiles: List[DriverProfile] = []
        for index in range(driver_count):
            profiles.append(
                DriverProfile(
                    driver_id=f"DRV-{index + 1:03d}",
                    driver_name=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                    home_zone=rng.choice(ZONES),
                    certification_level=rng.choices(
                        population=["standard", "wheelchair_certified", "lead"],
                        weights=[0.55, 0.35, 0.10],
                        k=1,
                    )[0],
                    hire_date=start_date - timedelta(days=rng.randint(120, 2_900)),
                    reliability_score=round(rng.uniform(0.71, 0.97), 3),
                )
            )
        return profiles

    def _build_vehicle_profiles(self, trip_count: int, blueprint, rng: random.Random) -> List[VehicleProfile]:
        vehicle_count = max(14, math.ceil(trip_count / 16))
        profiles: List[VehicleProfile] = []
        weights = [0.38, 0.34, 0.28]
        if "wheelchair_capacity_shortage" in blueprint.root_issues:
            weights = [0.33, 0.24, 0.43]
        for index in range(vehicle_count):
            vehicle_type, seated_capacity, wheelchair_capacity, lift_equipped = rng.choices(
                VEHICLE_TYPES,
                weights=weights,
                k=1,
            )[0]
            profiles.append(
                VehicleProfile(
                    vehicle_id=f"VEH-{index + 1:03d}",
                    vehicle_type=vehicle_type,
                    seated_capacity=seated_capacity,
                    wheelchair_capacity=wheelchair_capacity,
                    depot=rng.choice(DEPOTS),
                    lift_equipped=lift_equipped,
                    odometer_base=rng.randint(28_000, 147_000),
                    maintenance_due_in_days=rng.randint(4, 45),
                )
            )
        return profiles

    def _plan_runs_for_day(
        self,
        service_date: date,
        trip_count: int,
        blueprint,
        drivers: List[DriverProfile],
        vehicles: List[VehicleProfile],
        driver_cursor: int,
        vehicle_cursor: int,
        rng: random.Random,
        counters: defaultdict,
    ) -> Tuple[List[RunPlan], int, int]:
        runs: List[RunPlan] = []
        target_trips_per_run = rng.uniform(6.4, 7.8)
        run_count = max(1, math.ceil(trip_count / target_trips_per_run))
        daily_distribution = self._allocate_run_trip_counts(trip_count, run_count, blueprint.overloaded_run_rate, rng)
        hotspot_day = service_date in blueprint.hotspot_dates

        for run_number, assigned_trip_count in enumerate(daily_distribution, start=1):
            primary_zone = rng.choices(
                population=ZONES,
                weights=[blueprint.zone_demand_multipliers[zone] for zone in ZONES],
                k=1,
            )[0]
            wave_weights = [0.36, 0.24, 0.40]
            if "dialysis_banks" in blueprint.root_issues and service_date.weekday() in blueprint.dialysis_peak_weekdays:
                wave_weights = [0.46, 0.18, 0.36]
            wave = rng.choices(population=["early", "midday", "afternoon"], weights=wave_weights, k=1)[0]
            scheduled_start = self._scheduled_start_for_wave(service_date, wave, rng)
            scheduled_end = scheduled_start + timedelta(
                hours=(assigned_trip_count * rng.uniform(0.72, 0.84)) + rng.uniform(1.1, 1.6)
            )

            scheduled_driver = drivers[driver_cursor % len(drivers)]
            scheduled_vehicle = vehicles[vehicle_cursor % len(vehicles)]
            driver_cursor += 1
            vehicle_cursor += 1

            actual_driver = scheduled_driver
            actual_vehicle = scheduled_vehicle
            backup_driver: Optional[DriverProfile] = None
            backup_vehicle: Optional[VehicleProfile] = None
            issues: set[str] = set()
            pressure_boost = 1.15 if hotspot_day or primary_zone in blueprint.hotspot_zones else 1.0

            if rng.random() < blueprint.overloaded_run_rate * pressure_boost:
                issues.add("overloaded")
            if rng.random() < blueprint.poor_clustering_rate * pressure_boost:
                issues.add("poor_clustering")
            if rng.random() < blueprint.unrealistic_schedule_rate * pressure_boost:
                issues.add("unrealistic_schedule")
            if rng.random() < blueprint.dispatch_delay_rate * pressure_boost:
                issues.add("dispatch_delay")
            if rng.random() < blueprint.driver_lateness_rate * max(1.0, 1.1 - scheduled_driver.reliability_score):
                issues.add("driver_late")
            if (
                "dialysis_banks" in blueprint.root_issues
                and service_date.weekday() in blueprint.dialysis_peak_weekdays
                and wave in {"early", "afternoon"}
                and rng.random() < blueprint.dialysis_bank_rate * pressure_boost
            ):
                issues.add("dialysis_bank")
            if (
                "will_call_backlog" in blueprint.root_issues
                and wave == "afternoon"
                and (primary_zone in blueprint.will_call_zones or hotspot_day)
                and rng.random() < blueprint.will_call_rate * pressure_boost
            ):
                issues.add("will_call_backlog")
            if rng.random() < blueprint.same_day_addon_rate * (1.15 if wave != "early" else 0.85):
                issues.add("same_day_addons")
            if rng.random() < blueprint.garage_delay_rate * (1.25 if wave == "early" else 0.85):
                issues.add("garage_pullout_delay")
            if (
                rng.random() < blueprint.wheelchair_capacity_rate
                * (1.15 if (not scheduled_vehicle.lift_equipped or primary_zone in blueprint.hotspot_zones) else 0.90)
            ):
                issues.add("wheelchair_capacity")
            if assigned_trip_count >= 6 and wave in {"midday", "afternoon"} and rng.random() < blueprint.relief_failure_rate:
                issues.add("relief_failure")

            callout_notice_time: Optional[datetime] = None
            if rng.random() < blueprint.callout_rate * (1.2 if hotspot_day else 1.0):
                issues.add("callout")
                backup_driver = drivers[(driver_cursor + rng.randint(1, 5)) % len(drivers)]
                actual_driver = backup_driver
                callout_notice_time = scheduled_start - timedelta(minutes=rng.randint(35, 115))

            breakdown_after_trip: Optional[int] = None
            breakdown_delay_minutes = 0
            vehicle_swap_delay_minutes = 0
            if assigned_trip_count > 2 and rng.random() < blueprint.breakdown_rate * pressure_boost:
                issues.add("breakdown")
                breakdown_after_trip = rng.randint(2, assigned_trip_count - 1)
                breakdown_delay_minutes = rng.randint(28, 96)
                if rng.random() < 0.72:
                    backup_vehicle = vehicles[(vehicle_cursor + rng.randint(1, 4)) % len(vehicles)]
                    actual_vehicle = backup_vehicle
                    vehicle_swap_delay_minutes = rng.randint(12, 45)

            driver_delay_minutes = 0
            garage_delay_minutes = 0
            late_notice_time: Optional[datetime] = None
            if "callout" in issues:
                driver_delay_minutes = rng.randint(35, 90)
            elif "driver_late" in issues:
                driver_delay_minutes = rng.randint(12, 42)
                late_notice_time = scheduled_start - timedelta(minutes=rng.randint(10, 35))
            if "garage_pullout_delay" in issues:
                garage_delay_minutes = rng.randint(10, 34)

            dispatch_delay_minutes = rng.randint(8, 28) if "dispatch_delay" in issues else rng.randint(0, 6)
            if "same_day_addons" in issues:
                dispatch_delay_minutes += rng.randint(3, 9)
            if "will_call_backlog" in issues:
                dispatch_delay_minutes += rng.randint(4, 10)
            manifest_release_time = scheduled_start - timedelta(minutes=55 - dispatch_delay_minutes)
            if "same_day_addons" in issues:
                manifest_release_time += timedelta(minutes=rng.randint(8, 18))

            runs.append(
                RunPlan(
                    run_id=f"RUN-{service_date.strftime('%Y%m%d')}-{run_number:02d}",
                    service_date=service_date,
                    dispatcher_id=rng.choice(DISPATCHERS),
                    primary_zone=primary_zone,
                    service_wave=wave,
                    scheduled_driver_id=scheduled_driver.driver_id,
                    actual_driver_id=actual_driver.driver_id,
                    backup_driver_id=backup_driver.driver_id if backup_driver else None,
                    scheduled_vehicle_id=scheduled_vehicle.vehicle_id,
                    actual_vehicle_id=actual_vehicle.vehicle_id,
                    backup_vehicle_id=backup_vehicle.vehicle_id if backup_vehicle else None,
                    scheduled_start=scheduled_start,
                    scheduled_end=scheduled_end,
                    trip_count=assigned_trip_count,
                    issues=issues,
                    manifest_release_time=manifest_release_time,
                    driver_delay_minutes=driver_delay_minutes,
                    dispatch_delay_minutes=dispatch_delay_minutes,
                    garage_delay_minutes=garage_delay_minutes,
                    breakdown_after_trip=breakdown_after_trip,
                    breakdown_delay_minutes=breakdown_delay_minutes,
                    vehicle_swap_delay_minutes=vehicle_swap_delay_minutes,
                    callout_notice_time=callout_notice_time,
                    late_notice_time=late_notice_time,
                )
            )

        return runs, driver_cursor, vehicle_cursor

    def _simulate_run(
        self,
        run_plan: RunPlan,
        blueprint,
        drivers_by_id: Dict[str, DriverProfile],
        vehicles_by_id: Dict[str, VehicleProfile],
        rng: random.Random,
        counters: defaultdict,
    ) -> Dict[str, List[dict] | dict]:
        state = self._start_run_state(run_plan, blueprint, drivers_by_id, vehicles_by_id, rng)
        self._append_run_open_events(state, counters)
        for trip_index in range(run_plan.trip_count):
            trip_row = self._simulate_trip(trip_index, state, blueprint, rng, counters)
            state["trip_rows"].append(trip_row)
        self._finalize_run(state, rng, counters)
        return {
            "trip_rows": state["trip_rows"],
            "run_row": state["run_row"],
            "driver_rows": state["driver_rows"],
            "vehicle_rows": state["vehicle_rows"],
            "dispatch_rows": state["dispatch_rows"],
        }

    def _generate_complaints(
        self,
        trip_rows: List[dict],
        dispatch_rows: List[dict],
        blueprint,
        rng: random.Random,
        counters: defaultdict,
    ) -> List[dict]:
        complaints: List[dict] = []
        events_by_trip = defaultdict(list)
        for event in dispatch_rows:
            if event["trip_id"]:
                events_by_trip[event["trip_id"]].append(event)
        for trip in trip_rows:
            complaint = self._build_complaint_for_trip(trip, events_by_trip[trip["trip_id"]], blueprint, rng, counters)
            if complaint:
                complaints.append(complaint)
        return complaints

    def _append_complaint_dispatch_events(
        self,
        complaints: List[dict],
        dispatch_rows: List[dict],
        rng: random.Random,
        counters: defaultdict,
    ) -> None:
        for complaint in complaints:
            if complaint["complaint_status"] == "closed" and rng.random() < 0.5:
                continue
            dispatch_rows.append(
                self._dispatch_event(
                    counters=counters,
                    service_date=date.fromisoformat(complaint["service_date"]),
                    event_timestamp=datetime.fromisoformat(complaint["complaint_timestamp"]) + timedelta(minutes=rng.randint(4, 35)),
                    run_id=complaint["run_id"],
                    trip_id=complaint["trip_id"],
                    driver_id=None,
                    vehicle_id=None,
                    dispatcher_id=rng.choice(DISPATCHERS),
                    zone=complaint["origin_zone"],
                    event_type="complaint_logged",
                    event_source="customer_service",
                    delay_minutes=0,
                    action_taken=f"{complaint['complaint_type']} complaint entered",
                    severity="medium",
                )
            )

    def _start_run_state(
        self,
        run_plan: RunPlan,
        blueprint,
        drivers_by_id: Dict[str, DriverProfile],
        vehicles_by_id: Dict[str, VehicleProfile],
        rng: random.Random,
    ) -> dict:
        hotspot_multiplier = 1.0
        if run_plan.primary_zone in blueprint.hotspot_zones:
            hotspot_multiplier *= blueprint.zone_delay_multipliers[run_plan.primary_zone]
        if run_plan.service_date in blueprint.hotspot_dates:
            hotspot_multiplier *= 1.08

        actual_run_start = run_plan.scheduled_start + timedelta(
            minutes=run_plan.driver_delay_minutes + run_plan.dispatch_delay_minutes + run_plan.garage_delay_minutes
        )
        breakdown_clock = None
        if "breakdown" in run_plan.issues and run_plan.breakdown_after_trip:
            breakdown_clock = actual_run_start + timedelta(hours=rng.uniform(2.3, 5.5))

        return {
            "run_plan": run_plan,
            "scheduled_driver": drivers_by_id[run_plan.scheduled_driver_id],
            "actual_driver": drivers_by_id[run_plan.actual_driver_id],
            "scheduled_vehicle": vehicles_by_id[run_plan.scheduled_vehicle_id],
            "actual_vehicle": vehicles_by_id[run_plan.actual_vehicle_id],
            "actual_run_start": actual_run_start,
            "planned_clock": run_plan.scheduled_start + timedelta(minutes=rng.randint(8, 18)),
            "actual_clock": actual_run_start,
            "previous_scheduled_zone": run_plan.primary_zone,
            "previous_actual_zone": run_plan.primary_zone,
            "zone_cycle_origin": run_plan.primary_zone,
            "trip_rows": [],
            "driver_rows": [],
            "vehicle_rows": [],
            "dispatch_rows": [],
            "run_row": {},
            "completed_trip_count": 0,
            "missed_trip_count": 0,
            "uncovered_trip_count": 0,
            "total_deadhead_miles": 0.0,
            "total_service_miles": 0.0,
            "breakdown_clock": breakdown_clock,
            "using_backup_vehicle": False,
            "hotspot_multiplier": hotspot_multiplier,
            "relief_triggered": False,
        }

    def _append_run_open_events(self, state: dict, counters: defaultdict) -> None:
        run_plan: RunPlan = state["run_plan"]
        state["dispatch_rows"].append(
            self._dispatch_event(
                counters=counters,
                service_date=run_plan.service_date,
                event_timestamp=run_plan.manifest_release_time or (run_plan.scheduled_start - timedelta(minutes=45)),
                run_id=run_plan.run_id,
                trip_id=None,
                driver_id=run_plan.scheduled_driver_id,
                vehicle_id=run_plan.scheduled_vehicle_id,
                dispatcher_id=run_plan.dispatcher_id,
                zone=run_plan.primary_zone,
                event_type="manifest_released",
                event_source="scheduling",
                delay_minutes=run_plan.dispatch_delay_minutes,
                action_taken="manifest published to MDT",
                severity="medium" if "dispatch_delay" in run_plan.issues else "low",
            )
        )
        if "callout" in run_plan.issues and run_plan.callout_notice_time:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=run_plan.callout_notice_time,
                    run_id=run_plan.run_id,
                    trip_id=None,
                    driver_id=run_plan.scheduled_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=run_plan.primary_zone,
                    event_type="driver_callout_received",
                    event_source="operator_phone",
                    delay_minutes=run_plan.driver_delay_minutes,
                    action_taken="backup operator searched",
                    severity="high",
                )
            )
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=run_plan.callout_notice_time + timedelta(minutes=18),
                    run_id=run_plan.run_id,
                    trip_id=None,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=run_plan.primary_zone,
                    event_type="backup_driver_assigned",
                    event_source="dispatch",
                    delay_minutes=run_plan.driver_delay_minutes,
                    action_taken="run reopened with late pullout",
                    severity="high",
                )
            )
        elif "driver_late" in run_plan.issues and run_plan.late_notice_time:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=run_plan.late_notice_time,
                    run_id=run_plan.run_id,
                    trip_id=None,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=run_plan.primary_zone,
                    event_type="late_pullout_notice",
                    event_source="operator_phone",
                    delay_minutes=run_plan.driver_delay_minutes,
                    action_taken="customers monitored for ETA updates",
                    severity="medium",
                )
            )
        if "garage_pullout_delay" in run_plan.issues:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=run_plan.scheduled_start - timedelta(minutes=12),
                    run_id=run_plan.run_id,
                    trip_id=None,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=run_plan.primary_zone,
                    event_type="vehicle_not_ready",
                    event_source="garage",
                    delay_minutes=run_plan.garage_delay_minutes,
                    action_taken="pullout held pending fuel or pretrip completion",
                    severity="medium",
                )
            )
        if "same_day_addons" in run_plan.issues:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=run_plan.scheduled_start + timedelta(minutes=35),
                    run_id=run_plan.run_id,
                    trip_id=None,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=run_plan.primary_zone,
                    event_type="same_day_queue_growth",
                    event_source="reservations",
                    delay_minutes=run_plan.dispatch_delay_minutes,
                    action_taken="manifest adjusted after same-day requests",
                    severity="medium",
                )
            )
        if "will_call_backlog" in run_plan.issues:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=run_plan.scheduled_start + timedelta(hours=3, minutes=15),
                    run_id=run_plan.run_id,
                    trip_id=None,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=run_plan.primary_zone,
                    event_type="will_call_board_backlog",
                    event_source="dispatch",
                    delay_minutes=run_plan.dispatch_delay_minutes,
                    action_taken="return trips queued without immediate coverage",
                    severity="high",
                )
            )

    def _simulate_trip(
        self,
        trip_index: int,
        state: dict,
        blueprint,
        rng: random.Random,
        counters: defaultdict,
    ) -> dict:
        run_plan: RunPlan = state["run_plan"]
        counters["trip"] += 1
        trip_id = f"TRIP-{run_plan.service_date.strftime('%Y%m%d')}-{counters['trip']:05d}"
        purpose = self._choose_trip_purpose(run_plan, blueprint, rng)
        mobility_aid = self._choose_mobility_aid(run_plan, state["scheduled_vehicle"], purpose, rng)
        passenger_count = 2 if mobility_aid == "pca_assist" and rng.random() < 0.75 else 1
        boarding_minutes = self._boarding_minutes(mobility_aid, rng)

        origin_zone, destination_zone = self._choose_trip_zones(
            primary_zone=run_plan.primary_zone,
            previous_zone=state["zone_cycle_origin"],
            poor_clustering="poor_clustering" in run_plan.issues,
            hotspot_zones=blueprint.hotspot_zones,
            rng=rng,
        )
        state["zone_cycle_origin"] = destination_zone

        base_deadhead_minutes = travel_minutes(state["previous_scheduled_zone"], origin_zone)
        base_travel_minutes = travel_minutes(origin_zone, destination_zone)
        planned_deadhead = max(4, round(base_deadhead_minutes * rng.uniform(0.75, 1.02)))
        planned_trip_duration = max(16, round(base_travel_minutes * rng.uniform(0.94, 1.04)) + max(2, boarding_minutes - 1))
        schedule_buffer = rng.randint(12, 22)
        if "unrealistic_schedule" in run_plan.issues:
            schedule_buffer = rng.randint(4, 10)
            planned_deadhead = max(3, round(planned_deadhead * rng.uniform(0.48, 0.72)))

        if trip_index == 0:
            scheduled_pickup = state["planned_clock"]
        else:
            scheduled_pickup = state["planned_clock"] + timedelta(
                minutes=planned_deadhead + planned_trip_duration + schedule_buffer
            )
        state["planned_clock"] = scheduled_pickup

        pickup_window_start = scheduled_pickup - timedelta(minutes=10)
        pickup_window_end = scheduled_pickup + timedelta(minutes=10)
        appointment_time = self._appointment_time(scheduled_pickup, purpose, base_travel_minutes, rng)
        scheduled_dropoff = scheduled_pickup + timedelta(minutes=planned_trip_duration)

        actual_deadhead_minutes = max(
            3,
            round(
                travel_minutes(state["previous_actual_zone"], origin_zone)
                * rng.uniform(0.88, 1.10)
                * state["hotspot_multiplier"]
                * (1.15 if "poor_clustering" in run_plan.issues else 1.0)
            ),
        )
        if "dispatch_delay" in run_plan.issues and rng.random() < 0.35:
            actual_deadhead_minutes += rng.randint(4, 12)

        ride_stretch = 1.0
        if "overloaded" in run_plan.issues:
            ride_stretch += rng.uniform(0.08, 0.22)
        if "poor_clustering" in run_plan.issues:
            ride_stretch += rng.uniform(0.08, 0.18)
        actual_travel_minutes = max(
            12,
            round(base_travel_minutes * rng.uniform(0.98, 1.12) * state["hotspot_multiplier"] * ride_stretch),
        )
        dispatch_hold_minutes = rng.randint(0, 3)
        if "dispatch_delay" in run_plan.issues and rng.random() < 0.42:
            dispatch_hold_minutes += rng.randint(2, 6)

        arrival_at_pickup = state["actual_clock"] + timedelta(minutes=actual_deadhead_minutes + dispatch_hold_minutes)
        actual_pickup = max(arrival_at_pickup, scheduled_pickup - timedelta(minutes=rng.randint(0, 3)))
        actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)
        trip_status = "completed"
        requested_timestamp = self._build_requested_timestamp(scheduled_pickup, run_plan, purpose, rng)

        if (
            "relief_failure" in run_plan.issues
            and not state["relief_triggered"]
            and trip_index >= max(2, run_plan.trip_count // 2)
            and rng.random() < 0.55
        ):
            relief_delay = rng.randint(14, 32)
            state["relief_triggered"] = True
            dispatch_hold_minutes += relief_delay
            actual_pickup += timedelta(minutes=relief_delay)
            actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=scheduled_pickup - timedelta(minutes=rng.randint(5, 15)),
                    run_id=run_plan.run_id,
                    trip_id=trip_id,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.actual_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=origin_zone,
                    event_type="relief_driver_delayed",
                    event_source="dispatch",
                    delay_minutes=relief_delay,
                    action_taken="downline trips held until operator available",
                    severity="high",
                )
            )

        if "same_day_addons" in run_plan.issues and requested_timestamp.date() == scheduled_pickup.date() and rng.random() < 0.45:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=requested_timestamp + timedelta(minutes=rng.randint(4, 18)),
                    run_id=run_plan.run_id,
                    trip_id=trip_id,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.actual_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=origin_zone,
                    event_type="same_day_trip_added",
                    event_source="reservations",
                    delay_minutes=dispatch_hold_minutes,
                    action_taken="trip inserted into active manifest",
                    severity="medium",
                )
            )

        if "will_call_backlog" in run_plan.issues and purpose in {"medical", "dialysis"} and run_plan.service_wave == "afternoon":
            backlog_delay = rng.randint(8, 24)
            dispatch_hold_minutes += backlog_delay
            actual_pickup += timedelta(minutes=backlog_delay)
            actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=max(requested_timestamp, scheduled_pickup - timedelta(minutes=55)),
                    run_id=run_plan.run_id,
                    trip_id=trip_id,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.actual_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=origin_zone,
                    event_type="will_call_ready_received",
                    event_source="facility",
                    delay_minutes=backlog_delay,
                    action_taken="trip queued for return assignment",
                    severity="high" if backlog_delay >= 18 else "medium",
                )
            )

        if "dialysis_bank" in run_plan.issues and purpose in {"dialysis", "medical"}:
            bank_delay = rng.randint(3, 11)
            dispatch_hold_minutes += bank_delay
            actual_pickup += timedelta(minutes=bank_delay)
            actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)

        active_vehicle = state["actual_vehicle"] if state["using_backup_vehicle"] else state["scheduled_vehicle"]
        if "wheelchair_capacity" in run_plan.issues and mobility_aid in {"wheelchair", "scooter"}:
            if not active_vehicle.lift_equipped:
                trip_status = "uncovered" if trip_index < 2 else "missed"
                actual_pickup = None
                actual_dropoff = None
                dispatch_hold_minutes += rng.randint(18, 38)
                state["dispatch_rows"].append(
                    self._dispatch_event(
                        counters=counters,
                        service_date=run_plan.service_date,
                        event_timestamp=scheduled_pickup - timedelta(minutes=rng.randint(4, 16)),
                        run_id=run_plan.run_id,
                        trip_id=trip_id,
                        driver_id=run_plan.actual_driver_id,
                        vehicle_id=active_vehicle.vehicle_id,
                        dispatcher_id=run_plan.dispatcher_id,
                        zone=origin_zone,
                        event_type="mobility_aid_capacity_conflict",
                        event_source="dispatch",
                        delay_minutes=dispatch_hold_minutes,
                        action_taken="accessible replacement searched but not secured in time",
                        severity="high",
                    )
                )
            else:
                accessible_delay = rng.randint(6, 14)
                boarding_minutes += rng.randint(2, 5)
                dispatch_hold_minutes += accessible_delay
                actual_pickup += timedelta(minutes=accessible_delay)
                actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)

        breakdown_triggered = (
            run_plan.breakdown_after_trip is not None
            and trip_index + 1 == run_plan.breakdown_after_trip
            and state["breakdown_clock"] is not None
        )

        if trip_status == "completed" and "callout" in run_plan.issues and trip_index < 2 and run_plan.driver_delay_minutes >= 50:
            if rng.random() < 0.45:
                trip_status = "uncovered"
                actual_pickup = None
                actual_dropoff = None
                dispatch_hold_minutes += run_plan.driver_delay_minutes
            else:
                actual_pickup += timedelta(minutes=rng.randint(18, 32))
                actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)

        if breakdown_triggered and trip_status == "completed":
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=state["breakdown_clock"],
                    run_id=run_plan.run_id,
                    trip_id=trip_id,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=run_plan.scheduled_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=origin_zone,
                    event_type="vehicle_breakdown_reported",
                    event_source="operator_radio",
                    delay_minutes=run_plan.breakdown_delay_minutes,
                    action_taken="roadcall opened",
                    severity="high",
                )
            )
            if run_plan.backup_vehicle_id:
                state["using_backup_vehicle"] = True
                state["dispatch_rows"].append(
                    self._dispatch_event(
                        counters=counters,
                        service_date=run_plan.service_date,
                        event_timestamp=state["breakdown_clock"] + timedelta(minutes=12),
                        run_id=run_plan.run_id,
                        trip_id=trip_id,
                        driver_id=run_plan.actual_driver_id,
                        vehicle_id=run_plan.backup_vehicle_id,
                        dispatcher_id=run_plan.dispatcher_id,
                        zone=origin_zone,
                        event_type="vehicle_swap_dispatched",
                        event_source="dispatch",
                        delay_minutes=run_plan.breakdown_delay_minutes + run_plan.vehicle_swap_delay_minutes,
                        action_taken="customers held for spare vehicle",
                        severity="high",
                    )
                )
                actual_pickup += timedelta(minutes=run_plan.breakdown_delay_minutes + run_plan.vehicle_swap_delay_minutes)
                actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)
            else:
                if rng.random() < 0.55:
                    trip_status = "missed"
                    actual_pickup = None
                    actual_dropoff = None
                else:
                    actual_pickup += timedelta(minutes=run_plan.breakdown_delay_minutes)
                    actual_dropoff = actual_pickup + timedelta(minutes=actual_travel_minutes + boarding_minutes)

        trip_vehicle_id = run_plan.actual_vehicle_id if state["using_backup_vehicle"] else run_plan.scheduled_vehicle_id
        late_pickup_minutes, dropoff_delay_minutes, ride_time_minutes = self._trip_outcome_metrics(
            trip_status,
            scheduled_pickup,
            actual_pickup,
            scheduled_dropoff,
            actual_dropoff,
            base_travel_minutes,
            run_plan,
        )
        deadhead_miles = round(actual_deadhead_minutes * rng.uniform(0.33, 0.44), 1)
        service_miles = round(actual_travel_minutes * rng.uniform(0.38, 0.52), 1) if actual_dropoff else 0.0

        self._update_trip_counters(state, trip_status, deadhead_miles, service_miles)
        self._append_trip_dispatch_events(
            state,
            counters,
            trip_id,
            origin_zone,
            trip_vehicle_id,
            scheduled_pickup,
            actual_pickup,
            trip_status,
            late_pickup_minutes,
            rng,
        )

        state["previous_scheduled_zone"] = destination_zone
        state["previous_actual_zone"] = destination_zone
        state["actual_clock"] = (
            actual_dropoff + timedelta(minutes=rng.randint(2, 5))
            if actual_dropoff
            else max(state["actual_clock"], scheduled_pickup + timedelta(minutes=rng.randint(8, 18)))
        )

        return {
            "trip_id": trip_id,
            "service_date": run_plan.service_date.isoformat(),
            "customer_id": f"CUST-{rng.randint(10000, 99999)}",
            "trip_disposition": "performed" if actual_pickup and actual_dropoff else "unperformed",
            "trip_purpose": purpose,
            "mobility_aid": mobility_aid,
            "passenger_count": passenger_count,
            "origin_zone": origin_zone,
            "destination_zone": destination_zone,
            "assigned_run_id": run_plan.run_id,
            "scheduled_driver_id": run_plan.scheduled_driver_id,
            "actual_driver_id": run_plan.actual_driver_id,
            "scheduled_vehicle_id": run_plan.scheduled_vehicle_id,
            "actual_vehicle_id": trip_vehicle_id,
            "dispatcher_id": run_plan.dispatcher_id,
            "requested_timestamp": requested_timestamp.isoformat(sep=" "),
            "pickup_window_start": pickup_window_start.isoformat(sep=" "),
            "pickup_window_end": pickup_window_end.isoformat(sep=" "),
            "scheduled_pickup_time": scheduled_pickup.isoformat(sep=" "),
            "actual_pickup_time": actual_pickup.isoformat(sep=" ") if actual_pickup else None,
            "appointment_time": appointment_time.isoformat(sep=" "),
            "scheduled_dropoff_time": scheduled_dropoff.isoformat(sep=" "),
            "actual_dropoff_time": actual_dropoff.isoformat(sep=" ") if actual_dropoff else None,
        }

    def _trip_outcome_metrics(
        self,
        trip_status: str,
        scheduled_pickup: datetime,
        actual_pickup: Optional[datetime],
        scheduled_dropoff: datetime,
        actual_dropoff: Optional[datetime],
        base_travel_minutes: int,
        run_plan: RunPlan,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        if actual_pickup and actual_dropoff and trip_status == "completed":
            late_pickup_minutes = max(0, round((actual_pickup - scheduled_pickup).total_seconds() / 60))
            ride_time_minutes = round((actual_dropoff - actual_pickup).total_seconds() / 60)
            dropoff_delay_minutes = max(0, round((actual_dropoff - scheduled_dropoff).total_seconds() / 60))
            return late_pickup_minutes, dropoff_delay_minutes, ride_time_minutes
        if trip_status == "uncovered":
            return run_plan.driver_delay_minutes, None, None
        if trip_status == "missed":
            return run_plan.breakdown_delay_minutes or run_plan.driver_delay_minutes, None, None
        return None, None, None

    def _update_trip_counters(self, state: dict, trip_status: str, deadhead_miles: float, service_miles: float) -> None:
        state["total_deadhead_miles"] += deadhead_miles
        state["total_service_miles"] += service_miles
        if trip_status == "completed":
            state["completed_trip_count"] += 1
        elif trip_status == "missed":
            state["missed_trip_count"] += 1
        elif trip_status == "uncovered":
            state["uncovered_trip_count"] += 1

    def _append_trip_dispatch_events(
        self,
        state: dict,
        counters: defaultdict,
        trip_id: str,
        origin_zone: str,
        trip_vehicle_id: str,
        scheduled_pickup: datetime,
        actual_pickup: Optional[datetime],
        trip_status: str,
        late_pickup_minutes: Optional[int],
        rng: random.Random,
    ) -> None:
        run_plan: RunPlan = state["run_plan"]
        if late_pickup_minutes and late_pickup_minutes >= 18 and rng.random() < 0.52:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=(actual_pickup or scheduled_pickup) - timedelta(minutes=rng.randint(2, 9)),
                    run_id=run_plan.run_id,
                    trip_id=trip_id,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=trip_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=origin_zone,
                    event_type="eta_update_request",
                    event_source="customer_service",
                    delay_minutes=late_pickup_minutes,
                    action_taken="ETA relayed to rider",
                    severity="medium" if late_pickup_minutes < 30 else "high",
                )
            )

        if trip_status in {"missed", "uncovered"}:
            state["dispatch_rows"].append(
                self._dispatch_event(
                    counters=counters,
                    service_date=run_plan.service_date,
                    event_timestamp=(actual_pickup or scheduled_pickup) + timedelta(minutes=rng.randint(6, 18)),
                    run_id=run_plan.run_id,
                    trip_id=trip_id,
                    driver_id=run_plan.actual_driver_id,
                    vehicle_id=trip_vehicle_id,
                    dispatcher_id=run_plan.dispatcher_id,
                    zone=origin_zone,
                    event_type="trip_closeout",
                    event_source="dispatch",
                    delay_minutes=late_pickup_minutes or 0,
                    action_taken="trip marked unresolved in service log",
                    severity="high",
                )
            )

    def _build_complaint_for_trip(
        self,
        trip: dict,
        trip_events: List[dict],
        blueprint,
        rng: random.Random,
        counters: defaultdict,
    ) -> Optional[dict]:
        scheduled_pickup = datetime.fromisoformat(trip["scheduled_pickup_time"])
        actual_pickup = datetime.fromisoformat(trip["actual_pickup_time"]) if trip["actual_pickup_time"] else None
        scheduled_dropoff = datetime.fromisoformat(trip["scheduled_dropoff_time"])
        actual_dropoff = datetime.fromisoformat(trip["actual_dropoff_time"]) if trip["actual_dropoff_time"] else None
        late_pickup_minutes = (
            max(0, round((actual_pickup - scheduled_pickup).total_seconds() / 60))
            if actual_pickup
            else None
        )
        ride_time_minutes = (
            round((actual_dropoff - actual_pickup).total_seconds() / 60)
            if actual_pickup and actual_dropoff
            else None
        )
        scheduled_duration_minutes = round((scheduled_dropoff - scheduled_pickup).total_seconds() / 60)
        event_types = {event["event_type"] for event in trip_events}
        trip_unperformed = trip["trip_disposition"] == "unperformed"

        probability = 0.02 * blueprint.complaint_pressure
        if trip_unperformed:
            probability += 0.56
        if (late_pickup_minutes or 0) >= 20:
            probability += 0.08
        if ride_time_minutes and ride_time_minutes > scheduled_duration_minutes * 1.45:
            probability += 0.10
        if trip["trip_purpose"] in {"medical", "dialysis"}:
            probability += 0.05
        if trip["origin_zone"] in blueprint.hotspot_zones or trip["destination_zone"] in blueprint.hotspot_zones:
            probability += 0.05
        if trip_events:
            probability += 0.04
        if rng.random() >= min(probability, 0.82):
            return None

        counters["complaint"] += 1
        anchor_time = trip["actual_dropoff_time"] or trip["actual_pickup_time"] or trip["scheduled_pickup_time"]
        complaint_time = datetime.fromisoformat(anchor_time) + timedelta(hours=rng.uniform(0.3, 29.0))
        complaint_type = self._complaint_type_for_trip(
            trip_disposition=trip["trip_disposition"],
            late_pickup_minutes=late_pickup_minutes,
            ride_time_minutes=ride_time_minutes,
            scheduled_duration_minutes=scheduled_duration_minutes,
            event_types=event_types,
            rng=rng,
        )
        complaint_status = rng.choices(
            population=["open", "closed", "escalated"],
            weights=[0.30, 0.52, 0.18] if not trip_unperformed else [0.34, 0.28, 0.38],
            k=1,
        )[0]
        closed_timestamp = None
        if complaint_status == "closed":
            closed_timestamp = complaint_time + timedelta(hours=rng.uniform(6.0, 92.0))
        return {
            "complaint_id": f"CMP-{counters['complaint']:05d}",
            "complaint_timestamp": complaint_time.isoformat(sep=" "),
            "service_date": trip["service_date"],
            "trip_id": trip["trip_id"],
            "run_id": trip["assigned_run_id"],
            "customer_id": trip["customer_id"],
            "origin_zone": trip["origin_zone"],
            "destination_zone": trip["destination_zone"],
            "complaint_channel": rng.choice(COMPLAINT_CHANNELS),
            "complaint_type": complaint_type,
            "reported_by": rng.choice(["rider", "facility_staff", "family_member"]),
            "complaint_status": complaint_status,
            "closed_timestamp": closed_timestamp.isoformat(sep=" ") if closed_timestamp else None,
            "refund_amount": float(rng.choice([0, 0, 0, 10, 15, 20, 25])),
        }

    def _finalize_run(self, state: dict, rng: random.Random, counters: defaultdict) -> None:
        run_plan: RunPlan = state["run_plan"]
        actual_run_end = max(state["actual_clock"], run_plan.scheduled_start + timedelta(hours=6, minutes=45))
        manifest_revision_count = 1
        if "same_day_addons" in run_plan.issues:
            manifest_revision_count += rng.randint(1, 3)
        if "will_call_backlog" in run_plan.issues:
            manifest_revision_count += rng.randint(1, 2)

        state["run_row"] = {
            "run_id": run_plan.run_id,
            "service_date": run_plan.service_date.isoformat(),
            "dispatcher_id": run_plan.dispatcher_id,
            "primary_zone": run_plan.primary_zone,
            "service_wave": run_plan.service_wave,
            "scheduled_driver_id": run_plan.scheduled_driver_id,
            "actual_driver_id": run_plan.actual_driver_id,
            "backup_driver_id": run_plan.backup_driver_id,
            "scheduled_vehicle_id": run_plan.scheduled_vehicle_id,
            "actual_vehicle_id": run_plan.actual_vehicle_id,
            "backup_vehicle_id": run_plan.backup_vehicle_id,
            "scheduled_start": run_plan.scheduled_start.isoformat(sep=" "),
            "actual_start": state["actual_run_start"].isoformat(sep=" "),
            "scheduled_end": run_plan.scheduled_end.isoformat(sep=" "),
            "actual_end": actual_run_end.isoformat(sep=" "),
            "manifest_trip_count": run_plan.trip_count,
            "manifest_revision_count": manifest_revision_count,
            "service_miles": round(state["total_service_miles"], 1),
            "deadhead_miles": round(state["total_deadhead_miles"], 1),
            "manifest_release_time": (run_plan.manifest_release_time or run_plan.scheduled_start).isoformat(sep=" "),
        }

        scheduled_driver: DriverProfile = state["scheduled_driver"]
        actual_driver: DriverProfile = state["actual_driver"]
        counters["driver_shift"] += 1
        if "callout" in run_plan.issues:
            state["driver_rows"].append(
                {
                    "driver_shift_id": f"DSH-{counters['driver_shift']:05d}",
                    "service_date": run_plan.service_date.isoformat(),
                    "driver_id": scheduled_driver.driver_id,
                    "driver_name": scheduled_driver.driver_name,
                    "assigned_run_id": run_plan.run_id,
                    "scheduled_start": run_plan.scheduled_start.isoformat(sep=" "),
                    "actual_start": None,
                    "scheduled_end": run_plan.scheduled_end.isoformat(sep=" "),
                    "actual_end": None,
                    "attendance_code": SHIFT_STATUS["callout"],
                    "callout_reason": rng.choice(["illness", "family_emergency", "transportation_issue"]),
                    "home_zone": scheduled_driver.home_zone,
                    "certification_level": scheduled_driver.certification_level,
                    "hire_date": scheduled_driver.hire_date.isoformat(),
                }
            )
            counters["driver_shift"] += 1

        shift_status = SHIFT_STATUS["assigned"]
        if "callout" in run_plan.issues:
            shift_status = SHIFT_STATUS["coverage"]
        state["driver_rows"].append(
            {
                "driver_shift_id": f"DSH-{counters['driver_shift']:05d}",
                "service_date": run_plan.service_date.isoformat(),
                "driver_id": actual_driver.driver_id,
                "driver_name": actual_driver.driver_name,
                "assigned_run_id": run_plan.run_id,
                "scheduled_start": run_plan.scheduled_start.isoformat(sep=" "),
                "actual_start": state["actual_run_start"].isoformat(sep=" "),
                "scheduled_end": run_plan.scheduled_end.isoformat(sep=" "),
                "actual_end": actual_run_end.isoformat(sep=" "),
                "attendance_code": shift_status,
                "callout_reason": None,
                "home_zone": actual_driver.home_zone,
                "certification_level": actual_driver.certification_level,
                "hire_date": actual_driver.hire_date.isoformat(),
            }
        )
        self._finalize_vehicle_rows(state, actual_run_end, rng, counters)

    def _finalize_vehicle_rows(self, state: dict, actual_run_end: datetime, rng: random.Random, counters: defaultdict) -> None:
        run_plan: RunPlan = state["run_plan"]
        scheduled_vehicle: VehicleProfile = state["scheduled_vehicle"]
        actual_vehicle: VehicleProfile = state["actual_vehicle"]
        roadcall_timestamp = state["breakdown_clock"].isoformat(sep=" ") if state["breakdown_clock"] else None
        counters["vehicle_service"] += 1
        state["vehicle_rows"].append(
            {
                "vehicle_service_id": f"VSR-{counters['vehicle_service']:05d}",
                "service_date": run_plan.service_date.isoformat(),
                "vehicle_id": scheduled_vehicle.vehicle_id,
                "assigned_run_id": run_plan.run_id,
                "vehicle_type": scheduled_vehicle.vehicle_type,
                "lift_equipped": scheduled_vehicle.lift_equipped,
                "seated_capacity": scheduled_vehicle.seated_capacity,
                "wheelchair_capacity": scheduled_vehicle.wheelchair_capacity,
                "depot": scheduled_vehicle.depot,
                "scheduled_pullout_time": run_plan.scheduled_start.isoformat(sep=" "),
                "actual_pullout_time": state["actual_run_start"].isoformat(sep=" "),
                "scheduled_pullin_time": run_plan.scheduled_end.isoformat(sep=" "),
                "actual_pullin_time": (
                    state["breakdown_clock"].isoformat(sep=" ")
                    if state["breakdown_clock"] and run_plan.backup_vehicle_id
                    else actual_run_end.isoformat(sep=" ")
                ),
                "odometer_start": scheduled_vehicle.odometer_base + rng.randint(0, 300),
                "odometer_end": scheduled_vehicle.odometer_base + rng.randint(320, 860),
                "service_miles": round(state["total_service_miles"] if not run_plan.backup_vehicle_id else state["total_service_miles"] * 0.58, 1),
                "deadhead_miles": round(state["total_deadhead_miles"] if not run_plan.backup_vehicle_id else state["total_deadhead_miles"] * 0.65, 1),
                "vehicle_record_type": "primary_assignment",
                "roadcall_timestamp": roadcall_timestamp,
                "roadcall_reason": rng.choice(["lift_fault", "cooling_issue", "battery", "transmission"]) if "breakdown" in run_plan.issues else None,
                "maintenance_due_in_days": scheduled_vehicle.maintenance_due_in_days,
            }
        )
        if run_plan.backup_vehicle_id:
            counters["vehicle_service"] += 1
            state["vehicle_rows"].append(
                {
                    "vehicle_service_id": f"VSR-{counters['vehicle_service']:05d}",
                    "service_date": run_plan.service_date.isoformat(),
                    "vehicle_id": actual_vehicle.vehicle_id,
                    "assigned_run_id": run_plan.run_id,
                    "vehicle_type": actual_vehicle.vehicle_type,
                    "lift_equipped": actual_vehicle.lift_equipped,
                    "seated_capacity": actual_vehicle.seated_capacity,
                    "wheelchair_capacity": actual_vehicle.wheelchair_capacity,
                    "depot": actual_vehicle.depot,
                    "scheduled_pullout_time": (
                        state["breakdown_clock"] + timedelta(minutes=run_plan.vehicle_swap_delay_minutes)
                    ).isoformat(sep=" ")
                    if state["breakdown_clock"]
                    else state["actual_run_start"].isoformat(sep=" "),
                    "actual_pullout_time": (
                        state["breakdown_clock"] + timedelta(minutes=run_plan.vehicle_swap_delay_minutes)
                    ).isoformat(sep=" ")
                    if state["breakdown_clock"]
                    else state["actual_run_start"].isoformat(sep=" "),
                    "scheduled_pullin_time": run_plan.scheduled_end.isoformat(sep=" "),
                    "actual_pullin_time": actual_run_end.isoformat(sep=" "),
                    "odometer_start": actual_vehicle.odometer_base + rng.randint(0, 280),
                    "odometer_end": actual_vehicle.odometer_base + rng.randint(150, 520),
                    "service_miles": round(state["total_service_miles"] * 0.42, 1),
                    "deadhead_miles": round(state["total_deadhead_miles"] * 0.35, 1),
                    "vehicle_record_type": "replacement_assignment",
                    "roadcall_timestamp": None,
                    "roadcall_reason": None,
                    "maintenance_due_in_days": actual_vehicle.maintenance_due_in_days,
                }
            )

    def _allocate_run_trip_counts(self, trip_count: int, run_count: int, overload_rate: float, rng: random.Random) -> List[int]:
        weights = [rng.uniform(0.85, 1.18) for _ in range(run_count)]
        total = sum(weights)
        counts: List[int] = []
        remainders: List[Tuple[float, int]] = []
        assigned = 0
        for index, weight in enumerate(weights):
            exact = trip_count * weight / total
            base = max(1, math.floor(exact))
            counts.append(base)
            remainders.append((exact - base, index))
            assigned += base
        while assigned < trip_count:
            for _, index in sorted(remainders, key=lambda item: item[0], reverse=True):
                if assigned >= trip_count:
                    break
                counts[index] += 1
                assigned += 1
        while assigned > trip_count:
            for _, index in sorted(remainders, key=lambda item: item[0]):
                if assigned <= trip_count:
                    break
                if counts[index] > 1:
                    counts[index] -= 1
                    assigned -= 1

        overloaded_slots = max(1, round(run_count * overload_rate))
        candidate_indices = list(range(run_count))
        for index in rng.sample(candidate_indices, k=min(overloaded_slots, run_count)):
            donors = [candidate for candidate in candidate_indices if candidate != index and counts[candidate] > 2]
            if counts[index] >= 3 and donors:
                counts[index] += rng.randint(1, 3)
                donor_index = rng.choice(donors)
                counts[donor_index] -= rng.randint(1, min(2, counts[donor_index] - 1))

        diff = trip_count - sum(counts)
        step = 1 if diff > 0 else -1
        for _ in range(abs(diff)):
            movable = [idx for idx, count in enumerate(counts) if count > 1 or step > 0]
            counts[rng.choice(movable)] += step
        return counts

    def _scheduled_start_for_wave(self, service_date: date, wave: str, rng: random.Random) -> datetime:
        if wave == "early":
            chosen_time = time(hour=rng.randint(5, 7), minute=rng.choice([0, 10, 20, 30, 40, 50]))
        elif wave == "midday":
            chosen_time = time(hour=rng.randint(8, 11), minute=rng.choice([0, 10, 20, 30, 40, 50]))
        else:
            chosen_time = time(hour=rng.randint(11, 14), minute=rng.choice([0, 10, 20, 30, 40, 50]))
        return datetime.combine(service_date, chosen_time)

    def _choose_trip_zones(
        self,
        primary_zone: str,
        previous_zone: str,
        poor_clustering: bool,
        hotspot_zones: Iterable[str],
        rng: random.Random,
    ) -> Tuple[str, str]:
        hotspot_zones = list(hotspot_zones)
        if poor_clustering:
            origin_candidates = [zone for zone in ZONES if not is_neighbor(previous_zone, zone)]
            if not origin_candidates:
                origin_candidates = [zone for zone in ZONES if zone != previous_zone]
            origin_zone = rng.choice(origin_candidates)
            destination_candidates = [zone for zone in ZONES if zone != origin_zone and not is_neighbor(origin_zone, zone)]
            if hotspot_zones and rng.random() < 0.4:
                destination_zone = rng.choice(hotspot_zones)
                if destination_zone == origin_zone:
                    destination_zone = rng.choice(destination_candidates)
            else:
                destination_zone = rng.choice(destination_candidates)
            return origin_zone, destination_zone

        if rng.random() < 0.68:
            origin_zone = primary_zone if rng.random() < 0.55 else previous_zone
        else:
            nearby = [zone for zone in ZONES if is_neighbor(primary_zone, zone)]
            origin_zone = rng.choice(nearby)
        if rng.random() < 0.50:
            destination_zone = rng.choice([zone for zone in ZONES if is_neighbor(origin_zone, zone) and zone != origin_zone])
        else:
            destination_zone = rng.choice([zone for zone in ZONES if zone != origin_zone])
        return origin_zone, destination_zone

    def _choose_trip_purpose(self, run_plan: RunPlan, blueprint, rng: random.Random) -> str:
        if "dialysis_bank" in run_plan.issues:
            options = [
                ("dialysis", 0.34),
                ("medical", 0.28),
                ("day_program", 0.13),
                ("employment", 0.08),
                ("nutrition", 0.05),
                ("personal", 0.07),
                ("shopping", 0.05),
            ]
        elif "will_call_backlog" in run_plan.issues:
            options = [
                ("medical", 0.36),
                ("dialysis", 0.18),
                ("day_program", 0.12),
                ("employment", 0.10),
                ("nutrition", 0.07),
                ("personal", 0.10),
                ("shopping", 0.07),
            ]
        elif run_plan.service_date.weekday() in blueprint.dialysis_peak_weekdays and run_plan.service_wave == "early":
            options = [
                ("medical", 0.31),
                ("dialysis", 0.20),
                ("employment", 0.15),
                ("day_program", 0.14),
                ("nutrition", 0.07),
                ("personal", 0.08),
                ("shopping", 0.05),
            ]
        else:
            options = TRIP_PURPOSES
        return self._weighted_choice(options, rng)

    def _choose_mobility_aid(
        self,
        run_plan: RunPlan,
        scheduled_vehicle: VehicleProfile,
        purpose: str,
        rng: random.Random,
    ) -> str:
        if scheduled_vehicle.lift_equipped:
            options = MOBILITY_AIDS
            if "wheelchair_capacity" in run_plan.issues or purpose in {"medical", "dialysis"}:
                options = [
                    ("ambulatory", 0.36),
                    ("walker", 0.20),
                    ("wheelchair", 0.29),
                    ("scooter", 0.11),
                    ("pca_assist", 0.04),
                ]
        else:
            options = [
                ("ambulatory", 0.60),
                ("walker", 0.24),
                ("wheelchair", 0.07),
                ("scooter", 0.02),
                ("pca_assist", 0.07),
            ]
            if "wheelchair_capacity" in run_plan.issues:
                options = [
                    ("ambulatory", 0.49),
                    ("walker", 0.21),
                    ("wheelchair", 0.18),
                    ("scooter", 0.05),
                    ("pca_assist", 0.07),
                ]
        return self._weighted_choice(options, rng)

    def _build_requested_timestamp(
        self,
        scheduled_pickup: datetime,
        run_plan: RunPlan,
        purpose: str,
        rng: random.Random,
    ) -> datetime:
        if "will_call_backlog" in run_plan.issues and purpose in {"medical", "dialysis"} and run_plan.service_wave == "afternoon":
            return scheduled_pickup - timedelta(minutes=rng.randint(18, 120))
        if "same_day_addons" in run_plan.issues and rng.random() < 0.60:
            return scheduled_pickup - timedelta(minutes=rng.randint(35, 260))
        return scheduled_pickup - timedelta(days=rng.randint(1, 12), hours=rng.randint(1, 8))

    def _appointment_time(self, pickup_time: datetime, purpose: str, base_travel_minutes: int, rng: random.Random) -> datetime:
        if purpose in {"medical", "dialysis"}:
            lead_time = rng.randint(25, 70)
        elif purpose in {"employment", "day_program"}:
            lead_time = rng.randint(15, 45)
        else:
            lead_time = rng.randint(10, 35)
        return pickup_time + timedelta(minutes=base_travel_minutes + lead_time)

    def _boarding_minutes(self, mobility_aid: str, rng: random.Random) -> int:
        if mobility_aid == "ambulatory":
            return rng.randint(2, 4)
        if mobility_aid == "walker":
            return rng.randint(3, 6)
        if mobility_aid == "wheelchair":
            return rng.randint(6, 9)
        if mobility_aid == "scooter":
            return rng.randint(7, 10)
        return rng.randint(4, 7)

    def _complaint_type_for_trip(
        self,
        trip_disposition: str,
        late_pickup_minutes: Optional[int],
        ride_time_minutes: Optional[int],
        scheduled_duration_minutes: int,
        event_types: set[str],
        rng: random.Random,
    ) -> str:
        if trip_disposition == "unperformed":
            if "mobility_aid_capacity_conflict" in event_types:
                return rng.choice(["service_not_provided", "no_status_update"])
            return rng.choice(["missed_trip", "no_status_update"])
        if ride_time_minutes and ride_time_minutes > scheduled_duration_minutes * 1.45:
            return rng.choice(["long_ride", "late_pickup"])
        if (late_pickup_minutes or 0) >= 20:
            return rng.choice(["late_pickup", "no_status_update"])
        return rng.choice(["driver_behavior", "late_pickup", "no_status_update"])

    def _dispatch_event(
        self,
        counters: defaultdict,
        service_date: date,
        event_timestamp: datetime,
        run_id: Optional[str],
        trip_id: Optional[str],
        driver_id: Optional[str],
        vehicle_id: Optional[str],
        dispatcher_id: str,
        zone: str,
        event_type: str,
        event_source: str,
        delay_minutes: int,
        action_taken: str,
        severity: str,
    ) -> dict:
        counters["dispatch_event"] += 1
        return {
            "event_id": f"EVT-{counters['dispatch_event']:06d}",
            "event_timestamp": event_timestamp.isoformat(sep=" "),
            "service_date": service_date.isoformat(),
            "run_id": run_id,
            "trip_id": trip_id,
            "driver_id": driver_id,
            "vehicle_id": vehicle_id,
            "dispatcher_id": dispatcher_id,
            "zone": zone,
            "event_type": event_type,
            "event_source": event_source,
            "delay_minutes": delay_minutes,
            "action_taken": action_taken,
        }

    def _weighted_choice(self, options: List[Tuple[str, float]], rng: random.Random) -> str:
        return rng.choices(
            population=[item[0] for item in options],
            weights=[item[1] for item in options],
            k=1,
        )[0]

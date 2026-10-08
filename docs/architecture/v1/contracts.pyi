"""Normativer V1-Typentwurf; keine ausführbare Implementierung.
Zielmodule laut ADR. Felder sind Pflicht, sofern nicht ausdrücklich
optional.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ki_dev.executors.contract import TurnResult

class Decision(StrEnum):
    CONTINUE = 'CONTINUE'
    STOP_AND_PAUSE = 'STOP_AND_PAUSE'
    BLOCK_START = 'BLOCK_START'
    BLOCK_RESUME = 'BLOCK_RESUME'

class ReasonCode(StrEnum):
    OK = 'OK'
    OPERATOR_STOP = 'OPERATOR_STOP'
    PROFILE_INVALID = 'PROFILE_INVALID'
    UNKNOWN_CONTROL_STATE = 'UNKNOWN_CONTROL_STATE'
    CAPABILITY_UNVERIFIED = 'CAPABILITY_UNVERIFIED'
    BINDING_INVALID = 'BINDING_INVALID'
    MEASUREMENT_MISSING = 'MEASUREMENT_MISSING'
    MEASUREMENT_STALE = 'MEASUREMENT_STALE'
    MEASUREMENT_DISCONTINUITY = 'MEASUREMENT_DISCONTINUITY'
    BUDGET_EXHAUSTED = 'BUDGET_EXHAUSTED'
    QUOTA_UNAVAILABLE = 'QUOTA_UNAVAILABLE'
    CALL_TIMEOUT = 'CALL_TIMEOUT'
    LOOP_DETECTED = 'LOOP_DETECTED'
    ESTIMATE_INVALID = 'ESTIMATE_INVALID'
    SPLIT_REQUIRED = 'SPLIT_REQUIRED'
    PHASE_INVALID = 'PHASE_INVALID'
    RESUME_UNAUTHORIZED = 'RESUME_UNAUTHORIZED'
    UNKNOWN_EFFECT = 'UNKNOWN_EFFECT'
    INVALID_INPUT = 'INVALID_INPUT'

class LedgerFlag(StrEnum):
    OVER_BUDGET = 'OVER_BUDGET'
    RECONCILIATION_CONFLICT = 'RECONCILIATION_CONFLICT'

class QuotaMode(StrEnum):
    REQUIRE_VERIFIED_QUOTA = 'REQUIRE_VERIFIED_QUOTA'
    SUPERVISED_MANUAL = 'SUPERVISED_MANUAL'

class EvidenceMode(StrEnum):
    EXISTING_ARTIFACTS_ONLY = 'EXISTING_ARTIFACTS_ONLY'
    AUTHORIZED_REAL_WORK = 'AUTHORIZED_REAL_WORK'

@dataclass(frozen=True)
class SafetyProfile:
    schema_version: int
    policy_version: str
    startup_sample_timeout_s: Decimal
    max_measurement_age_s: Decimal
    watchdog_interval_s: Decimal
    terminate_grace_s: Decimal
    kill_wait_s: Decimal
    call_timeout_s: Decimal
    diagnostic_timeout_s: Decimal
    diagnostic_attempts: int
    split_threshold_tokens: int
    reserve_factor: Decimal
    task_cap_tokens: int
    call_cap_tokens: int
    strategy_id: str
    strategy_revision: str
    quota_mode: QuotaMode
    evidence_mode: EvidenceMode
    quota_evidence_ttl_s: Decimal | None
    authorization_ref: str | None

@dataclass(frozen=True)
class ProfileSnapshot:
    profile: SafetyProfile
    provenance: Mapping[str, str]
    profile_hash: str

@dataclass(frozen=True)
class CallBinding:
    run_id: str
    call_id: str
    session_id: str
    provider_family: str
    source_revision: str
    task_revision: str
    family_id: str
    family_revision: str
    profile_hash: str

@dataclass(frozen=True)
class CapabilityDescriptor:
    provider_family: str
    cli_version: str
    source_revision: str
    verified: bool
    exclusive_session: bool
    live_measurement: bool
    process_group_stop: bool
    evidence_refs: tuple[str, ...]
    required_usage_fields: tuple[str, ...]
    configuration_ref: str
    enablement_ref: str
    rollback_ref: str

@dataclass(frozen=True)
class LiveSample:
    binding: CallBinding
    sequence: int
    call_total_tokens: int | None
    source_age_s: Decimal | None
    status: ReasonCode
    evidence_ref: str

@dataclass(frozen=True)
class BudgetState:
    budget_tokens: int
    measured_tokens: int
    open_reservations: int
    protected_phases: int
    conservative_charges: int
    call_measured_tokens: int
    call_allocation_tokens: int
    required_call_tokens: int
    flags: frozenset[LedgerFlag]

@dataclass(frozen=True)
class ControlInput:
    """Booleans sind normalisierte lokale Befunde, keine Modellurteile.
    Unbekannte Pflichtbefunde setzen control_known=False.
    elapsed_s und sample.source_age_s sind Laufzeitdauern, keine
    persistierten Uhren.
    Start/Resume: sample=None, elapsed_s=0; Bindung/Basis des neuen
    Calls.
    Tick: laufender Call, elapsed_s ab Prozessstart.
    Phase: letzter Call, bestätigtes Ende und Abschlussabgleich;
    elapsed_s bis Ende, Samplealter am Ende; ursprüngliche Zuteilung
    bleibt trotz Reservefreigabe erhalten.
    ledger_conflict entspricht RECONCILIATION_CONFLICT in budget.flags.
    ledger_reconciled: Altverbrauch vollständig abgeglichen oder
    zulässig belastet; kein ungelöster Konflikt. Nur Resume prüft
    dieses Feld.
    call_end_confirmed: belegtes Prozessende; nur Phase prüft dieses
    Feld.
    """
    profile: ProfileSnapshot
    budget: BudgetState
    sample: LiveSample | None
    elapsed_s: Decimal
    operator_stop: bool
    profile_valid: bool
    control_known: bool
    capability_verified: bool
    binding_valid: bool
    baseline_verified: bool
    ledger_conflict: bool
    ledger_reconciled: bool
    call_end_confirmed: bool
    quota_valid: bool
    estimate_valid: bool
    split_required: bool
    loop_detected: bool
    project_error_expected: bool
    phase_valid: bool
    phase_transfer_fits: bool
    resume_authorized: bool
    effect_resolved_or_bounded: bool
    resume_profile_approved: bool
    startup_grace_active: bool
    input_valid: bool

@dataclass(frozen=True)
class ControlDecision:
    decision: Decision
    reason: ReasonCode
    secondary_reasons: tuple[ReasonCode, ...]
    policy_version: str
    profile_hash: str

class ControlPolicy(Protocol):
    def admit_start(self, state: ControlInput) -> ControlDecision: ...
    def evaluate_tick(self, state: ControlInput) -> ControlDecision: ...
    def on_phase_complete(
        self, state: ControlInput) -> ControlDecision: ...
    def admit_resume(self, state: ControlInput) -> ControlDecision: ...

@dataclass(frozen=True)
class StopResult:
    local_exit_confirmed: bool
    external_effect_resolved: bool
    exit_code: int | None
    reason: ReasonCode
    evidence_refs: tuple[str, ...]

class LiveAdapter(Protocol):
    def capabilities(self) -> CapabilityDescriptor: ...
    def bind(self, binding: CallBinding) -> None: ...
    def sample(self) -> LiveSample: ...
    def stop(self, reason: ReasonCode) -> StopResult: ...

@dataclass(frozen=True)
class Estimate:
    schema_version: int
    task_revision: str
    family_revision: str
    profile_hash: str
    estimator_id: str
    estimator_revision: str
    estimator_model: str
    assumptions_id: str
    source_ref: str
    upper_tokens: int
    phase_upper_tokens: Mapping[str, int]

@dataclass(frozen=True)
class EstimateResult:
    strategy_id: str
    strategy_revision: str
    upper_tokens: int | None
    phase_upper_tokens: Mapping[str, int]
    source_refs: tuple[str, ...]
    reason: ReasonCode

class EstimateStrategy(Protocol):
    def combine(
        self, estimates: tuple[Estimate, ...],
        expected_estimators: tuple[str, ...]) -> EstimateResult: ...

@dataclass(frozen=True)
class ConservativeCharge:
    event_id: str
    call_id: str
    tokens: int
    operator_ref: str
    justification_ref: str
    created_at_utc: str

# Ziel: safety_profile.py
def resolve_profile(project: Mapping, named: Mapping,
                    overrides: Mapping,
                    authorization: Mapping) -> ProfileSnapshot: ...
def validate_profile(
    profile: SafetyProfile) -> tuple[ReasonCode, ...]: ...
# Ziel: usage_estimation.py
def max_upper_v1(
    estimates: tuple[Estimate, ...],
    expected_estimators: tuple[str, ...]) -> EstimateResult: ...
# Ziel: safety_policy.py
def admit_start(state: ControlInput) -> ControlDecision: ...
def evaluate_tick(state: ControlInput) -> ControlDecision: ...
def on_phase_complete(state: ControlInput) -> ControlDecision: ...
def admit_resume(state: ControlInput) -> ControlDecision: ...

@dataclass(frozen=True)
class BudgetPlan:
    budget_tokens: int | None
    phase_reserves: Mapping[str, int]
    allocation_tokens: int | None
    reason: ReasonCode

# Ziel: usage_estimation.py; required_call_tokens umfasst bei Resume
# auch Kontext.
def derive_budget(estimate: EstimateResult, profile: SafetyProfile,
                  measured_tokens: int, open_reservations: int,
                  conservative_charges: int,
                  pending_phases: tuple[str, ...],
                  required_call_tokens: int) -> BudgetPlan: ...

# Erweiterung des vorhandenen CallLedger, KEIN zweiter Ledger.
class LedgerExtension(Protocol):
    def reserve_tokens(self, event_id: str, binding: CallBinding,
                       required_call_tokens: int) -> BudgetState: ...
    def apply_sample(self, event_id: str,
                     sample: LiveSample) -> BudgetState: ...
    def release_phase(self, event_id: str,
                      phase: str) -> BudgetState: ...
    def charge_unknown(
        self, charge: ConservativeCharge) -> BudgetState: ...
    def recover_safety(self) -> BudgetState: ...

# Erweiterung adapter/executors/process.py, bestehende Rückgabe
# TurnResult erhalten.
# TurnResult erhält zusätzlich stop_result: StopResult | None = None,
# process_elapsed_s: Decimal | None = None und
# process_end_confirmed: bool = False.
# process_elapsed_s: endlich >=0, monotone Dauer vom Start bis
# beobachtetem Ende, keine Ausgabe-/Abrechnungsnachbearbeitung; None
# bei fehlendem Endzeitbeleg.
# Phase übernimmt diese Dauer und Endbestätigung in ControlInput.
# Keine automatische Umdeutung von TurnStatus.OK durch eine spätere
# Dispatch-Pause.

@dataclass(frozen=True)
class ProcessControl:
    profile: ProfileSnapshot
    tick: Callable[[], ControlDecision]
    before_stop: Callable[[ControlDecision], None]
    after_stop: Callable[[StopResult], None]

def run_cli_turn(argv: list[str], *, stdin: str,
                 timeout_s: float = 900.0, cwd: Path | None = None,
                 env: dict[str, str] | None = None,
                 control: ProcessControl | None = None,
                 ) -> TurnResult: ...

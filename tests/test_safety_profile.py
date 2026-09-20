"""SafetyProfile/1: Pflichtfelder und Validierung (wu0.10.5.1)."""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from ki_dev import safety_contract
from ki_dev.safety_contract import (
    EvidenceMode,
    QuotaMode,
    ReasonCode,
    SafetyProfile,
)
from ki_dev.safety_profile import (
    FIELD_NAMES,
    ProfileInvalid,
    parse_profile,
    profile_problems,
    validate_profile,
)

INVALID = (ReasonCode.PROFILE_INVALID,)


def _fixture() -> dict:
    """Offline-Fixture, kein Betriebsfallback (ADR D)."""
    return {
        "schema_version": 1,
        "policy_version": "v1-test",
        "startup_sample_timeout_s": 30,
        "max_measurement_age_s": 10,
        "watchdog_interval_s": 1,
        "terminate_grace_s": 5,
        "kill_wait_s": 5,
        "call_timeout_s": 600,
        "diagnostic_timeout_s": 60,
        "diagnostic_attempts": 1,
        "split_threshold_tokens": 50_000,
        "reserve_factor": 1.0,
        "task_cap_tokens": 200_000,
        "call_cap_tokens": 100_000,
        "strategy_id": "max_upper_v1",
        "strategy_revision": "1",
        "quota_mode": "REQUIRE_VERIFIED_QUOTA",
        "evidence_mode": "EXISTING_ARTIFACTS_ONLY",
        "quota_evidence_ttl_s": None,
        "authorization_ref": None,
    }


def _profile(**changes) -> SafetyProfile:
    return replace(parse_profile(_fixture()), **changes)


def test_fixture_is_valid_and_typed():
    profile = parse_profile(_fixture())
    assert validate_profile(profile) == ()
    assert profile.reserve_factor == Decimal("1.0")
    assert profile.quota_mode is QuotaMode.REQUIRE_VERIFIED_QUOTA
    assert profile.evidence_mode is EvidenceMode.EXISTING_ARTIFACTS_ONLY


@pytest.mark.parametrize("name", FIELD_NAMES)
def test_missing_profile_field_blocks(name):
    """Fall missing_profile: jedes fehlende Feld (u. a.
    max_measurement_age_s) ergibt PROFILE_INVALID."""
    data = _fixture()
    del data[name]
    with pytest.raises(ProfileInvalid) as info:
        parse_profile(data)
    assert info.value.reasons == INVALID
    assert name in str(info.value)


def test_extra_and_non_mapping_profile_block():
    data = {**_fixture(), "ignore_quota": True}
    with pytest.raises(ProfileInvalid, match="ignore_quota"):
        parse_profile(data)
    with pytest.raises(ProfileInvalid):
        parse_profile([("schema_version", 1)])  # type: ignore[arg-type]


def test_no_defaults_are_supplied():
    assert parse_profile.__defaults__ is None
    with pytest.raises(TypeError):
        SafetyProfile()  # type: ignore[call-arg]


SECONDS = (
    "startup_sample_timeout_s",
    "max_measurement_age_s",
    "watchdog_interval_s",
    "terminate_grace_s",
    "kill_wait_s",
    "call_timeout_s",
    "diagnostic_timeout_s",
)
INTS = (
    "diagnostic_attempts",
    "split_threshold_tokens",
    "task_cap_tokens",
    "call_cap_tokens",
)


@pytest.mark.parametrize("name", SECONDS)
@pytest.mark.parametrize(
    "bad",
    [
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "Infinity",
        0,
        -1,
        "-0.5",
        None,
        "abc",
        [1],
    ],
)
def test_bad_seconds_block(name, bad):
    data = {**_fixture(), name: bad}
    with pytest.raises(ProfileInvalid) as info:
        parse_profile(data)
    assert info.value.reasons == INVALID


@pytest.mark.parametrize("name", SECONDS)
@pytest.mark.parametrize(
    "bad",
    [
        Decimal(0),
        Decimal(-1),
        Decimal("NaN"),
        Decimal("Infinity"),
        1.5,
        True,
        None,
    ],
)
def test_validate_rejects_bad_seconds_on_built_profile(name, bad):
    assert validate_profile(_profile(**{name: bad})) == INVALID


@pytest.mark.parametrize("name", INTS)
@pytest.mark.parametrize("bad", [True, 0, -3, 1.0, "5", None])
def test_bad_positive_ints_block(name, bad):
    assert validate_profile(_profile(**{name: bad})) == INVALID
    with pytest.raises(ProfileInvalid):
        parse_profile({**_fixture(), name: bad})


@pytest.mark.parametrize("bad", ["1", 1.0, True, None, 2])
def test_schema_version_must_be_int_one(bad):
    assert validate_profile(_profile(schema_version=bad)) == INVALID


@pytest.mark.parametrize("name", ["policy_version", "strategy_id"])
@pytest.mark.parametrize("bad", ["", "  ", None, 1])
def test_text_fields_must_be_nonempty(name, bad):
    assert validate_profile(_profile(**{name: bad})) == INVALID


@pytest.mark.parametrize(
    "bad", ["0.99", 0.5, 0, -1, "NaN", "Infinity", True]
)
def test_reserve_factor_below_one_or_invalid_blocks(bad):
    with pytest.raises(ProfileInvalid):
        parse_profile({**_fixture(), "reserve_factor": bad})


def test_reserve_factor_one_and_above_is_valid():
    for good in (1, "1.0", 1.5, Decimal("2")):
        data = {**_fixture(), "reserve_factor": good}
        assert validate_profile(parse_profile(data)) == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"call_cap_tokens": 200_001},  # call_cap > task_cap
        {"watchdog_interval_s": 11},  # > max_measurement_age
        {"watchdog_interval_s": 31, "max_measurement_age_s": 40},
        {"startup_sample_timeout_s": 601},  # > call_timeout
    ],
)
def test_wrong_ordering_blocks(changes):
    with pytest.raises(ProfileInvalid) as info:
        parse_profile({**_fixture(), **changes})
    assert info.value.reasons == INVALID


def test_equal_boundaries_are_valid():
    data = {
        **_fixture(),
        "call_cap_tokens": 200_000,
        "watchdog_interval_s": 10,
        "startup_sample_timeout_s": 600,
        "max_measurement_age_s": 10,
    }
    assert validate_profile(parse_profile(data)) == ()


@pytest.mark.parametrize("bad", ["IGNORE_QUOTA", "", None, 1, True])
def test_unknown_modes_block(bad):
    for name in ("quota_mode", "evidence_mode"):
        with pytest.raises(ProfileInvalid):
            parse_profile({**_fixture(), name: bad})
        assert validate_profile(_profile(**{name: bad})) == INVALID


# --- Fall authorization: Modi allein autorisieren nichts -------------


def _supervised(**changes) -> dict:
    return {
        **_fixture(),
        "quota_mode": "SUPERVISED_MANUAL",
        "quota_evidence_ttl_s": 900,
        "authorization_ref": "freigabe-1",
        **changes,
    }


def _real_work(**changes) -> dict:
    return {
        **_fixture(),
        "evidence_mode": "AUTHORIZED_REAL_WORK",
        "authorization_ref": "freigabe-2",
        **changes,
    }


def test_authorized_modes_with_evidence_are_valid():
    assert validate_profile(parse_profile(_supervised())) == ()
    assert validate_profile(parse_profile(_real_work())) == ()


@pytest.mark.parametrize("ref", [None, "", "  ", 5, True])
@pytest.mark.parametrize("make", [_supervised, _real_work])
def test_mode_enabled_without_approval_ref_blocks(make, ref):
    with pytest.raises(ProfileInvalid) as info:
        parse_profile(make(authorization_ref=ref))
    assert info.value.reasons == INVALID


@pytest.mark.parametrize(
    "ttl",
    [None, 0, -5, "NaN", "Infinity", True, "abc"],
)
def test_supervised_manual_needs_finite_positive_ttl(ttl):
    with pytest.raises(ProfileInvalid):
        parse_profile(_supervised(quota_evidence_ttl_s=ttl))


def test_ref_alone_does_not_authorize_and_is_allowed():
    """Eine Referenz allein aktiviert nichts (Modi bleiben Standard);
    sie ist gueltig, weil das Praezedenzblatt sie als Grundlage einer
    Ueberschreibung braucht."""
    profile = parse_profile({**_fixture(), "authorization_ref": "x"})
    assert validate_profile(profile) == ()
    assert profile.quota_mode is QuotaMode.REQUIRE_VERIFIED_QUOTA
    assert profile.evidence_mode is EvidenceMode.EXISTING_ARTIFACTS_ONLY


def test_ttl_only_belongs_to_supervised_manual():
    """Auslegung: ein TTL ohne SUPERVISED_MANUAL ist ein unbekannter
    Zusatzwert und blockiert (ADR D nennt ihn nur fuer diesen Modus)."""
    with pytest.raises(ProfileInvalid):
        parse_profile({**_fixture(), "quota_evidence_ttl_s": 60})
    with pytest.raises(ProfileInvalid):
        parse_profile(_real_work(quota_evidence_ttl_s=60))


def test_validate_rejects_non_profile_and_reports_no_values():
    assert validate_profile(object()) == INVALID  # type: ignore[arg-type]
    problems = profile_problems(
        _profile(authorization_ref="geheim", call_timeout_s=Decimal(0))
    )
    assert problems
    assert all("geheim" not in p for p in problems)


def test_problems_collected_not_first_only():
    bad = _profile(
        max_measurement_age_s=Decimal(0), reserve_factor=Decimal("0.5")
    )
    assert len(profile_problems(bad)) >= 2


def test_profile_is_frozen():
    profile = parse_profile(_fixture())
    with pytest.raises(AttributeError):
        profile.call_timeout_s = Decimal(1)  # type: ignore[misc]


STUB = Path(__file__).parents[1] / "docs/architecture/v1/contracts.pyi"
# Vom Stub bewusst nicht in safety_contract: Executor-/Ledger-Blaetter.
NOT_HERE = {"ProcessControl", "LedgerExtension"}


def _stub_types() -> dict[str, ast.ClassDef]:
    tree = ast.parse(STUB.read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def _shape(node: ast.ClassDef) -> list[tuple[str, str]]:
    """Feldname/Wert bzw. Annotation, ohne Docstrings und Methoden."""
    out = []
    for item in node.body:
        if isinstance(item, ast.AnnAssign):
            out.append(
                (ast.unparse(item.target), ast.unparse(item.annotation))
            )
        elif isinstance(item, ast.Assign):
            out.append(
                (ast.unparse(item.targets[0]), ast.unparse(item.value))
            )
        elif isinstance(item, ast.FunctionDef):
            out.append((item.name, ast.unparse(item.args)))
    return out


def _normalized(text: str) -> str:
    return text.replace("'", '"').replace(" ", "")


def test_contract_types_match_stub():
    stub = _stub_types()
    assert stub, "Stub nicht lesbar"
    for name, node in stub.items():
        if name in NOT_HERE:
            assert not hasattr(safety_contract, name)
            continue
        actual = getattr(safety_contract, name)
        expected = _shape(node)
        got = _shape(
            ast.parse(inspect.getsource(actual)).body[0]  # type: ignore[arg-type]
        )
        assert [(a, _normalized(b)) for a, b in got] == [
            (a, _normalized(b)) for a, b in expected
        ], name


def test_types_import_no_provider_or_executor_modules():
    code = (
        "import sys, ki_dev.safety_contract, ki_dev.safety_profile\n"
        "bad = [m for m in sys.modules if m.startswith('ki_dev.') "
        "and m not in ('ki_dev.safety_contract',"
        " 'ki_dev.safety_profile')]\n"
        "bad += [m for m in ('anthropic','openai','claude_agent_sdk')"
        " if m in sys.modules]\n"
        "print(bad)\n"
        "sys.exit(1 if bad else 0)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stdout + done.stderr

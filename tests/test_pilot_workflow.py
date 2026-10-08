"""Agenten- und Reviewablauf-Abnahme (ki-dev-ablauf-urq.5).

Prueft die in urq.5 verlangten Bausteine: begrenzter Kontext fuer den
Abflachungsagenten, bereichsuebergreifende Kandidatensuche mit
Stichprobe ausserhalb der Top-k, teilweise blinder Review,
Lokalisierungspruefung, gesonderter Anteilslisten-Review, und eindeutige
Unterscheidung von Entwuerfen, Befunden, Korrekturen, Paarurteilen,
Ablehnungen sowie Ersturteilen vs. korrigierten Urteilen im
Kontrollprotokoll. Bezug:
docs/architecture/planning-verarbeitungsvertrag.de.md (urq.1),
docs/architecture/planning-pruefbeispiele.de.md (urq.2, PB-3, PB-6).
"""

from __future__ import annotations

import random

import pytest

from ki_dev import planning
from ki_dev.pilot import log, search, workflow
from ki_dev.planning import PlanningError


def _unit(unit_id, location, text, revision="rev-1"):
    return search.Unit(unit_id, revision, location, text)


# --- pilot_search -----------------------------------------------------


def test_embed_is_deterministic_and_local():
    """Gleicher Text ergibt immer denselben Vektor; keine externen
    Aufrufe."""
    a = search.embed("Ralphex bleibt Teil des Bootstrap")
    b = search.embed("Ralphex bleibt Teil des Bootstrap")
    assert a == b
    assert len(a) == search.DIMENSIONS


def test_embed_self_similarity_is_maximal():
    vector = search.embed("Ausfuehrungs- und Reviewmaschine")
    assert search.cosine(vector, vector) == pytest.approx(1.0)


def test_search_pb3_findet_bereichsuebergreifende_dublette():
    """PB-3: der fachliche Bezug liegt an einem anderen Ort; die Suche
    muss ihn trotzdem unter den Top-k finden (bereichsuebergreifend,
    kein Bereichsfilter)."""
    units = [
        _unit(
            "ralphex-ausfuehrung",
            "bootstrap/ausfuehrung",
            "Ralphex als Ausfuehrungs- und Reviewmaschine im Bootstrap",
        ),
        _unit(
            "unrelated-1",
            "andere/sache",
            "Datenbankmigration fuer Kunden",
        ),
        _unit(
            "unrelated-2",
            "andere/sache",
            "Deploy-Pipeline ueberarbeiten",
        ),
    ]
    rng = random.Random(42)
    candidates = search.search_candidates(
        "Ralphex-Verbleib im Bootstrap ist offene Entscheidung",
        units, top_k=1, sample_size=1, rng=rng,
    )
    top = [c for c in candidates if c.selection == "top_k"]
    assert top[0].unit_id == "ralphex-ausfuehrung"
    assert top[0].rank == 1


def test_search_includes_random_sample_outside_top_k():
    units = [
        _unit(f"u{i}", "loc", f"Inhalt Nummer {i}") for i in range(10)
    ]
    rng = random.Random(1)
    candidates = search.search_candidates(
        "Inhalt Nummer 0", units, top_k=2, sample_size=3, rng=rng,
    )
    sample = [c for c in candidates if c.selection == "sample"]
    top_ids = {c.unit_id for c in candidates if c.selection == "top_k"}
    assert len(sample) == 3
    assert all(c.rank is None for c in sample)
    assert all(c.unit_id not in top_ids for c in sample)


def test_assign_blind_visibility_hides_rank_for_requested_fraction():
    candidates = search.search_candidates(
        "Text", [_unit(f"u{i}", "loc", f"Text {i}") for i in range(20)],
        top_k=10, sample_size=5, rng=random.Random(2),
    )
    rng = random.Random(7)
    blinded = search.assign_blind_visibility(
        candidates, blind_fraction=0.5, rng=rng,
    )
    hidden = [c for c in blinded if not c.visible_in_review]
    assert len(hidden) == round(len(candidates) * 0.5)


def test_for_review_hides_raw_score_and_rank_when_blind():
    """Ein blinder Kandidat darf im Review weder Rang noch Rohwert
    zeigen -- nicht nur das `visible_in_review`-Flag."""
    candidates = search.search_candidates(
        "Text", [_unit(f"u{i}", "loc", f"Text {i}") for i in range(20)],
        top_k=10, sample_size=5, rng=random.Random(2),
    )
    blinded = search.assign_blind_visibility(
        candidates, blind_fraction=0.5, rng=random.Random(7),
    )
    review_view = [search.for_review(c) for c in blinded]
    for candidate, presented in zip(blinded, review_view, strict=True):
        if candidate.visible_in_review:
            assert presented.raw_score == candidate.raw_score
            assert presented.rank == candidate.rank
        else:
            assert presented.raw_score is None
            assert presented.rank is None


def test_candidates_for_review_order_is_independent_of_search_rank():
    """Reviewer-BLOCKER: selbst bei rank=None verriet die reine
    Listenposition (Top-k-Reihenfolge unveraendert durchgereicht) den
    Suchrang jedes Kandidaten -- auch bei vollstaendig blindem Review.
    Die Praesentationsreihenfolge muss vom Suchrang entkoppelt sein."""
    candidates = [
        search.Candidate(
            f"u{i}", "rev-1", "loc", 1.0 - i * 0.01, rank=i + 1,
            selection="top_k", visible_in_review=False,
        )
        for i in range(6)
    ]
    review_view = workflow.candidates_for_review(
        candidates, rng=random.Random(42),
    )
    expected_order = list(range(6))
    random.Random(42).shuffle(expected_order)
    assert [c.unit_id for c in review_view] == [
        f"u{i}" for i in expected_order
    ]
    assert [c.unit_id for c in review_view] != [
        f"u{i}" for i in range(6)
    ]
    assert all(
        c.rank is None and c.raw_score is None for c in review_view
    )


def test_localization_check_accepts_single_use_iterator():
    """Regression: `units` als einmalig konsumierbarer Iterator (statt
    Liste) darf die Pruefung nicht durch doppeltes Durchlaufen
    verfaelschen (zweiter Durchlauf eines Iterators liefert nichts)."""
    moved = _unit(
        "unveraenderlichkeit", "planungsspeicher/modell",
        "Unveraenderliche gespeicherte Eintraege und Hashketten",
    )
    same_location_peer = _unit(
        "modell-peer",
        "planungsspeicher/modell",
        "Deploy-Pipeline Notizen",
    )
    other_location_match = _unit(
        "agentenablauf-peer", "planungsspeicher/agentenablauf",
        "Unveraenderliche Eintraege, Hashketten und Revisionspruefung",
    )
    as_list = [same_location_peer, other_location_match]
    warning_from_list = search.localization_check(moved, as_list)
    warning_from_iterator = search.localization_check(
        moved, iter(as_list),
    )
    assert warning_from_iterator == warning_from_list
    assert warning_from_iterator is not None


def test_localization_check_warns_when_other_location_is_closer():
    """PB-6-artiger Fall: die neue Einheit ist ihrem Ortsnachbarn
    unaehnlicher als einer Einheit an einem anderen Ort."""
    moved = _unit(
        "unveraenderlichkeit", "planungsspeicher/modell",
        "Unveraenderliche gespeicherte Eintraege und Hashketten",
    )
    same_location_peer = _unit(
        "modell-peer",
        "planungsspeicher/modell",
        "Deploy-Pipeline Notizen",
    )
    other_location_match = _unit(
        "agentenablauf-peer", "planungsspeicher/agentenablauf",
        "Unveraenderliche Eintraege, Hashketten und Revisionspruefung",
    )
    warning = search.localization_check(
        moved, [same_location_peer, other_location_match],
    )
    assert warning is not None
    assert (
        warning["other_location_best"] > warning["same_location_best"]
    )


def test_localization_check_silent_when_same_location_closer():
    unit = _unit("a", "loc-a", "Ralphex bleibt Teil des Bootstrap")
    same = _unit(
        "b", "loc-a", "Ralphex bleibt Teil des Bootstrap-Vorgehens"
    )
    other = _unit("c", "loc-b", "Datenbankmigration fuer Kunden")
    assert search.localization_check(unit, [same, other]) is None


# --- pilot_log: eindeutige Unterscheidung -----------------------------


def test_control_log_rejects_unknown_kind():
    with pytest.raises(PlanningError):
        log.validate({"kind": "not-a-kind"})


def test_control_log_rejects_incomplete_record():
    with pytest.raises(PlanningError):
        log.validate({"kind": "draft", "id": "x"})


def test_draft_finding_correction_bleiben_unterscheidbar(tmp_path):
    """urq.1 Korrekturrunden-Regel: Entwurf, Befund und Korrektur sind
    getrennte, ueber `supersedes` verknuepfte Protokollobjekte -- keine
    unabhaengigen Beobachtungen desselben Sachverhalts."""
    log_path = tmp_path / "control-log.jsonl"
    part = {"id": "part-1", "text": "Ralphex bleibt vorerst"}
    draft = workflow.record_draft(
        "passage-1", part, assignment=None, operation="neu",
        log_path=log_path,
    )
    workflow.record_finding(
        draft,
        verdict="rejected",
        notes="Bedingung fehlt",
        log_path=log_path,
    )
    correction = workflow.record_correction(
        draft,
        assignment="ralphex-verbleib-bedingung",
        operation="revision",
        notes="Bedingung ergaenzt",
        log_path=log_path,
    )
    records = log.read_all(log_path)
    kinds = [record["kind"] for record in records]
    assert kinds == ["draft", "finding", "correction"]
    assert log.by_kind(records, "draft")[0]["id"] == draft["id"]
    assert (
        log.by_kind(records, "correction")[0]["supersedes"]
        == draft["id"]
    )
    assert correction["part_id"] == draft["part_id"]


def test_pair_judgments_and_search_records_carry_full_provenance(
    tmp_path,
):
    """AC: Rohwert, Rang, Auswahlart, Modellkennung und Sichtbarkeit im
    Review muessen je Kandidat festgehalten sein."""
    log_path = tmp_path / "control-log.jsonl"
    units = [_unit(f"u{i}", "loc", f"Text {i}") for i in range(6)]
    rng = random.Random(3)
    candidates = workflow.run_candidate_search(
        {"id": "part-1", "text": "Text 0"},
        units,
        top_k=2,
        sample_size=2,
        blind_fraction=0.5,
        rng=rng,
        log_path=log_path,
    )
    for index, candidate in enumerate(candidates):
        workflow.record_pair_judgment(
            "part-1", candidate, verdict="no_match", index=index,
            log_path=log_path,
        )
    records = log.read_all(log_path)
    search_records = log.by_kind(records, "search_record")
    pair_records = log.by_kind(records, "pair_judgment")
    assert len(search_records) == len(candidates)
    assert len(pair_records) == len(candidates)
    for record in search_records:
        assert record["model_id"] == search.MODEL_ID
        assert record["selection"] in ("top_k", "sample")
        assert isinstance(record["visible_in_review"], bool)
    assert any(record["blind"] for record in pair_records)
    assert any(not record["blind"] for record in pair_records)


def test_rejection_and_unclear_are_recorded_distinctly(tmp_path):
    log_path = tmp_path / "control-log.jsonl"
    workflow.record_rejection(
        "part-1", candidate_id="u1", reason="falscher Bereich", index=0,
        log_path=log_path,
    )
    workflow.record_unclear(
        "part-1",
        candidate_id="u2",
        reason="Modalitaet unklar",
        index=0,
        log_path=log_path,
    )
    records = log.read_all(log_path)
    assert [record["kind"] for record in records] == [
        "rejection",
        "unclear",
    ]


def test_share_list_review_ist_gesondert_und_geht_dem_delta_voraus(
    tmp_path,
):
    log_path = tmp_path / "control-log.jsonl"
    workflow.review_share_list(
        "passage-1", ["part-1", "part-2"], complete=True,
        notes="alle Anteile erfasst", log_path=log_path,
    )
    workflow.record_draft(
        "passage-1", {"id": "part-1", "text": "x"}, assignment=None,
        operation="neu", log_path=log_path,
    )
    records = log.read_all(log_path)
    assert records[0]["kind"] == "share_list_review"
    assert records[0]["part_ids"] == ["part-1", "part-2"]
    assert records[1]["kind"] == "draft"


def test_localization_warning_is_logged(tmp_path):
    log_path = tmp_path / "control-log.jsonl"
    moved = _unit(
        "unveraenderlichkeit", "planungsspeicher/modell",
        "Unveraenderliche gespeicherte Eintraege und Hashketten",
    )
    other = _unit(
        "agentenablauf-peer", "planungsspeicher/agentenablauf",
        "Unveraenderliche Eintraege, Hashketten und Revisionspruefung",
    )
    same = _unit(
        "modell-peer", "planungsspeicher/modell", "Deploy Notizen"
    )
    warning = workflow.check_localization(
        moved, [same, other], log_path=log_path,
    )
    assert warning is not None
    records = log.read_all(log_path)
    assert records[0]["kind"] == "localization_warning"
    assert records[0]["part_id"] == "unveraenderlichkeit"


# --- begrenzter Kontext -----------------------------------------------


def test_build_context_enthaelt_kein_roharchiv_und_keine_delta_kette(
    tmp_path,
):
    """urq.5-Umfang: kein Zugriff auf Roharchiv, historische Deltas oder
    verborgene Pruefererwartungen -- nur
    id/type/location/revision/data."""
    root = tmp_path
    store = root / "steps"
    aussage_type = {
        "id": "aussage@1",
        "kind": "node",
        "schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
    (root / "src.md").write_text("Zeile eins\n", encoding="utf-8")
    ref = planning.source_ref(root, "src.md", 1, 1)
    delta = {
        "format": 1,
        "step": 1,
        "parent": None,
        "types": [aussage_type],
        "nodes": [
            {
                "id": "n1",
                "op": "put",
                "expected": None,
                "type": "aussage@1",
                "location": "loc/a",
                "data": {"text": "Inhalt"},
                "sources": [ref],
            }
        ],
        "edges": [],
    }
    candidate_path = tmp_path / "delta.json"
    candidate_path.write_text(
        planning.encode(delta).decode(), encoding="utf-8"
    )
    state = planning.append(store, candidate_path, root)

    context = workflow.build_context(
        state, [{"passage": "neue Passage"}], visible_node_ids={"n1"},
    )
    assert context.localized_nodes == {
        "n1": {
            "id": "n1", "type": "aussage@1", "location": "loc/a",
            "revision": state["nodes"]["n1"]["revision"],
            "data": {"text": "Inhalt"},
        },
    }
    assert set(context.localized_nodes["n1"]) == {
        "id", "type", "location", "revision", "data",
    }
    assert context.released_passages == ({"passage": "neue Passage"},)
    assert "aussage@1" in context.types


def test_build_context_ignoriert_nicht_freigegebene_knoten(tmp_path):
    root = tmp_path
    store = root / "steps"
    aussage_type = {
        "id": "aussage@1",
        "kind": "node",
        "schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
    (root / "src.md").write_text(
        "Zeile eins\nZeile zwei\n", encoding="utf-8"
    )
    ref1 = planning.source_ref(root, "src.md", 1, 1)
    ref2 = planning.source_ref(root, "src.md", 2, 2)
    delta = {
        "format": 1,
        "step": 1,
        "parent": None,
        "types": [aussage_type],
        "nodes": [
            {
                "id": "visible",
                "op": "put",
                "expected": None,
                "type": "aussage@1",
                "location": "loc/a",
                "data": {"text": "sichtbar"},
                "sources": [ref1],
            },
            {
                "id": "hidden",
                "op": "put",
                "expected": None,
                "type": "aussage@1",
                "location": "loc/b",
                "data": {"text": "nicht angefordert"},
                "sources": [ref2],
            },
        ],
        "edges": [],
    }
    candidate_path = tmp_path / "delta.json"
    candidate_path.write_text(
        planning.encode(delta).decode(), encoding="utf-8"
    )
    state = planning.append(store, candidate_path, root)

    context = workflow.build_context(
        state, [], visible_node_ids={"visible"},
    )
    assert set(context.localized_nodes) == {"visible"}

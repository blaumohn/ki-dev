"""Datenmodell-Abnahme gegen die Prüfbeispiele aus ki-dev-ablauf-urq.2.

Bezug: docs/architecture/planning-verarbeitungsvertrag.de.md (urq.1),
docs/architecture/planning-pruefbeispiele.de.md (urq.2, PB-1..PB-7,
PB-2b). Diese Tests prüfen ausschließlich die strukturelle Abnahme
(urq.4): ob sich die vorab festgelegten Fälle mit handgefertigten Daten
darstellen lassen und ob ungültige Änderungen erkennbar zurückgewiesen
werden. Die semantische Verarbeitung selbst (Agentenlauf, urq.6) ist
nicht Gegenstand dieser Tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev import planning

REPO_ROOT = Path(__file__).resolve().parents[1]

_AUSSAGE_TYPE = {
    "id": "aussage@1",
    "kind": "node",
    "schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}
_ERSETZT_TYPE = {
    "id": "ersetzt_durch@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
_BEZIEHT_SICH_AUF_TYPE = {
    "id": "bezieht_sich_auf@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
_VORSCHLAEGT_ZURUECKSTELLUNG_TYPE = {
    "id": "vorschlaegt_zurueckstellung_von@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
_HEBT_AUF_TYPE = {
    "id": "hebt_auf@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}


def _delta(step, parent, *, types=(), nodes=(), edges=()):
    return {
        "format": 1,
        "step": step,
        "parent": parent,
        "types": list(types),
        "nodes": list(nodes),
        "edges": list(edges),
    }


def _put_node(
    id_, *, location, data, sources, type_="aussage@1", expected=None
):
    return {
        "id": id_, "op": "put", "expected": expected, "type": type_,
        "location": location, "data": data, "sources": sources,
    }


def _put_edge(
    id_,
    *,
    source,
    target,
    sources,
    type_="ersetzt_durch@1",
    expected=None,
):
    return {
        "id": id_,
        "op": "put",
        "expected": expected,
        "type": type_,
        "source": source,
        "target": target,
        "data": {},
        "sources": sources,
    }


def test_pb1_bedingte_ruecknahme_erhaelt_beide_anteile(tmp_path):
    """PB-1: zwei bedingte, sich nicht automatisch aufhebende
    Aussagen."""
    root = REPO_ROOT
    ref_102 = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 102, 102,
    )
    ref_106 = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 106, 106,
    )
    store = tmp_path / "steps"
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE],
        nodes=[
            _put_node(
                "ralphex-verbleib-bedingung",
                location="bootstrap/ralphex",
                data={
                    "text": "Ralphex bleibt vorerst, Verbleib ist offen"
                },
                sources=[ref_102],
            ),
            _put_node(
                "ralphex-entfernung-bei-bedingung",
                location="bootstrap/ralphex",
                data={
                    "text": (
                        "Ralphex entfernen, falls Bedingung eintritt"
                    )
                },
                sources=[ref_106],
            ),
        ],
    )
    state = planning.append(store, _write(tmp_path, delta), root)
    assert set(state["nodes"]) == {
        "ralphex-verbleib-bedingung",
        "ralphex-entfernung-bei-bedingung",
    }


def test_pb2_ersetzung_verknuepft_statt_zu_loeschen(tmp_path):
    """PB-2: der alte Plan-Knoten bleibt erhalten und wird verknüpft."""
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _ERSETZT_TYPE],
        nodes=[
            _put_node(
                "bootstrap-stufe-1-4",
                location="bootstrap/plan",
                data={"text": "Bootstrap Stufe 1-4"},
                sources=[ref],
            ),
            _put_node(
                "minimal-go-live",
                location="bootstrap/plan",
                data={"text": "Minimal-Go-live von ki-dev"},
                sources=[ref],
            ),
        ],
        edges=[
            _put_edge(
                "bootstrap-stufe-1-4-ersetzt-durch-minimal-go-live",
                source="bootstrap-stufe-1-4",
                target="minimal-go-live",
                sources=[ref],
            ),
        ],
    )
    state = planning.append(
        tmp_path / "steps", _write(tmp_path, delta), root
    )
    assert "bootstrap-stufe-1-4" in state["nodes"]
    assert state["edges"][
        "bootstrap-stufe-1-4-ersetzt-durch-minimal-go-live"
    ]["target"] == "minimal-go-live"


def test_pb2b_verzweigte_ersetzung_erhaelt_beide_zweige(tmp_path):
    """PB-2b (KONSTRUIERT): eine Ersetzung mit zwei parallelen
    Nachfolgeknoten bleibt als zwei eigenständige Kanten erhalten; die
    Zweige werden nicht zusammengeführt oder verloren."""
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _ERSETZT_TYPE],
        nodes=[
            _put_node(
                "bootstrap-stufe-1-4",
                location="bootstrap/plan",
                data={"text": "Bootstrap Stufe 1-4"},
                sources=[ref],
            ),
            _put_node(
                "minimal-go-live",
                location="bootstrap/plan",
                data={"text": "Minimal-Go-live von ki-dev"},
                sources=[ref],
            ),
            _put_node(
                "design-notizen-pilot-konstruiert",
                location="bootstrap/plan",
                data={
                    "text": "KONSTRUIERT: Design-Notizen-Pilot als "
                    "separater Nachfolgezweig",
                },
                sources=[ref],
            ),
        ],
        edges=[
            _put_edge(
                "bootstrap-stufe-1-4-ersetzt-durch-minimal-go-live",
                source="bootstrap-stufe-1-4",
                target="minimal-go-live",
                sources=[ref],
            ),
            _put_edge(
                "bootstrap-stufe-1-4-ersetzt-durch-design-notizen-pilot",
                source="bootstrap-stufe-1-4",
                target="design-notizen-pilot-konstruiert",
                sources=[ref],
            ),
        ],
    )
    state = planning.append(
        tmp_path / "steps", _write(tmp_path, delta), root
    )
    assert "bootstrap-stufe-1-4" in state["nodes"]
    branch_targets = {
        edge["target"] for edge in state["edges"].values()
        if edge["source"] == "bootstrap-stufe-1-4"
    }
    assert branch_targets == {
        "minimal-go-live", "design-notizen-pilot-konstruiert",
    }


def test_pb6_raumumbau_ist_neue_revision_nicht_neue_identitaet(
    tmp_path,
):
    """PB-6: Ortswechsel ändert die Revision, nicht die fachliche
    Kennung."""
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    store = tmp_path / "steps"
    delta1 = _delta(
        1, None, types=[_AUSSAGE_TYPE],
        nodes=[_put_node(
            "unveraenderlichkeit", location="planungsspeicher",
            data={"text": "Gespeicherte Schritte bleiben unveraendert"},
            sources=[ref],
        )],
    )
    state = planning.append(store, _write(tmp_path, delta1, "a"), root)
    delta2 = _delta(
        2,
        state["head"],
        types=[],
        nodes=[
            _put_node(
                "unveraenderlichkeit",
                location="planungsspeicher/modell",
                data={
                    "text": "Gespeicherte Schritte bleiben unveraendert"
                },
                sources=[ref],
                expected=state["nodes"]["unveraenderlichkeit"][
                    "revision"
                ],
            )
        ],
    )
    state = planning.append(store, _write(tmp_path, delta2, "b"), root)
    assert list(state["nodes"]) == ["unveraenderlichkeit"]
    assert (
        state["nodes"]["unveraenderlichkeit"]["location"]
        == "planungsspeicher/modell"
    )


def test_pb3_dublette_ist_ohne_ortsbindung_verknuepfbar(
    tmp_path,
):
    """PB-3: fachlicher Bezug über zwei entfernte Orte hinweg ist
    darstellbar.

    Prüft nur Darstellbarkeit im Datenmodell (Kanten sind nicht auf
    gleiche oder benachbarte `location` beider Endpunkte beschränkt). Ob
    die Kandidatensuche einen solchen Bezug tatsächlich *findet*, ist
    Gegenstand der Trefferquote in `urq.5`/`urq.6`, nicht dieses
    Abnahmetests.
    """
    root = REPO_ROOT
    ref_ausfuehrung = planning.source_ref(
        root, "bd:ki-dev-ablauf-9407", 503, 695,
    )
    ref_verbleib = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 102, 102,
    )
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _BEZIEHT_SICH_AUF_TYPE],
        nodes=[
            _put_node(
                "ralphex-ausfuehrungsmaschine",
                location="bootstrap/ausfuehrung",
                data={
                    "text": (
                        "Ralphex uebernimmt den inneren "
                        "Implementierungsablauf"
                    )
                },
                sources=[ref_ausfuehrung],
            ),
            _put_node(
                "ralphex-verbleib-bedingung",
                location="bootstrap/ralphex",
                data={
                    "text": "Ralphex bleibt vorerst, Verbleib ist offen"
                },
                sources=[ref_verbleib],
            ),
        ],
        edges=[
            _put_edge(
                "ralphex-ausfuehrung-bezieht-sich-auf-verbleib",
                source="ralphex-ausfuehrungsmaschine",
                target="ralphex-verbleib-bedingung",
                sources=[ref_verbleib],
                type_="bezieht_sich_auf@1",
            ),
        ],
    )
    state = planning.append(
        tmp_path / "steps", _write(tmp_path, delta), root
    )
    assert (
        state["nodes"]["ralphex-ausfuehrungsmaschine"]["location"]
        == "bootstrap/ausfuehrung"
    )
    assert (
        state["nodes"]["ralphex-verbleib-bedingung"]["location"]
        == "bootstrap/ralphex"
    )
    assert state["edges"][
        "ralphex-ausfuehrung-bezieht-sich-auf-verbleib"
    ]["target"] == "ralphex-verbleib-bedingung"


def test_pb4_langgraph_fall_l_haelt_drei_modalitaeten_nebeneinander(
    tmp_path,
):
    """PB-4: Empfehlung, Entscheidung und Zurueckstellungsvorschlag
    bleiben getrennte Knoten; der Vorschlag ueberschreibt die
    Entscheidung nicht."""
    root = REPO_ROOT
    ref_empfehlung = planning.source_ref(
        root, "bd:ki-dev-ablauf-74lc", 3315, 3315,
    )
    ref_entscheidung = planning.source_ref(
        root, "bd:ki-dev-ablauf-uxdk", 52, 52,
    )
    ref_vorschlag = planning.source_ref(
        root, "codex:01a09aef", 60, 60,
    )
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _VORSCHLAEGT_ZURUECKSTELLUNG_TYPE],
        nodes=[
            _put_node(
                "langgraph-empfehlung",
                location="architektur/orchestrator",
                data={
                    "text": (
                        "LangGraph ist am naechsten an einem eigenen "
                        "Orchestrator"
                    )
                },
                sources=[ref_empfehlung],
            ),
            _put_node(
                "langgraph-entscheidung",
                location="architektur/orchestrator",
                data={
                    "text": (
                        "LangGraph ist der Orchestrator-Unterbau fuer "
                        "ki-dev loop"
                    )
                },
                sources=[ref_entscheidung],
            ),
            _put_node(
                "eigener-loop-zurueckstellung-vorschlag",
                location="architektur/orchestrator",
                data={
                    "text": (
                        "Vorschlag: eigenen Loop zurueckstellen, Loope "
                        "als Bootstrap"
                    )
                },
                sources=[ref_vorschlag],
            ),
        ],
        edges=[
            _put_edge(
                "zurueckstellung-vorschlaegt-gegen-entscheidung",
                source="eigener-loop-zurueckstellung-vorschlag",
                target="langgraph-entscheidung",
                sources=[ref_vorschlag],
                type_="vorschlaegt_zurueckstellung_von@1",
            ),
        ],
    )
    state = planning.append(
        tmp_path / "steps", _write(tmp_path, delta), root
    )
    assert set(state["nodes"]) == {
        "langgraph-empfehlung", "langgraph-entscheidung",
        "eigener-loop-zurueckstellung-vorschlag",
    }
    # Die Entscheidung bleibt unveraendert bestehen; der Vorschlag
    # haengt nur als eigene, klar als Vorschlag markierte Kante daran,
    # ersetzt sie nicht.
    assert state["nodes"]["langgraph-entscheidung"]["data"][
        "text"
    ].startswith("LangGraph ist der Orchestrator-Unterbau")
    assert state["edges"][
        "zurueckstellung-vorschlaegt-gegen-entscheidung"
    ]["type"] == "vorschlaegt_zurueckstellung_von@1"


def test_pb5_ruecknahme_ist_neue_kante_auf_bestehende_entscheidung(
    tmp_path,
):
    """PB-5 (KONSTRUIERT): eine Ruecknahme loescht die widerrufene
    Entscheidung nicht, sondern haengt eine neue, typisierte Kante
    daran."""
    root = REPO_ROOT
    ref_bedingung = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 102, 102,
    )
    ref_entscheidung = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 106, 106,
    )
    # KONSTRUIERT: keine reale Quelle enthaelt eine eindeutige,
    # unbedingte Ruecknahme (siehe planning-pruefbeispiele.de.md PB-5);
    # die Testeingabe zitiert daher denselben Quellbereich wie die
    # widerrufene Entscheidung, damit der Quellenverweis strukturell
    # gueltig bleibt, waehrend der Knotentext selbst ausdruecklich als
    # Testkonstrukt markiert ist.
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _HEBT_AUF_TYPE],
        nodes=[
            _put_node(
                "ralphex-entfernung-bei-bedingung",
                location="bootstrap/ralphex",
                data={
                    "text": (
                        "Ralphex entfernen, falls Bedingung eintritt"
                    )
                },
                sources=[ref_entscheidung],
            ),
            _put_node(
                "ralphex-entfernung-ruecknahme-konstruiert",
                location="bootstrap/ralphex",
                data={
                    "text": (
                        "KONSTRUIERT: Entfernung wird aufgehoben, "
                        "Ralphex bleibt endgueltig Teil des "
                        "Bootstrap-Vorgehens"
                    ),
                },
                sources=[ref_bedingung],
            ),
        ],
        edges=[
            _put_edge(
                "ruecknahme-hebt-auf-entfernung",
                source="ralphex-entfernung-ruecknahme-konstruiert",
                target="ralphex-entfernung-bei-bedingung",
                sources=[ref_bedingung],
                type_="hebt_auf@1",
            ),
        ],
    )
    state = planning.append(
        tmp_path / "steps", _write(tmp_path, delta), root
    )
    # Erhaltungsregel: die widerrufene Entscheidung bleibt als eigener
    # Knoten bestehen (kein Loeschen), nur eine neue Kante zeigt die
    # Ruecknahme an.
    assert "ralphex-entfernung-bei-bedingung" in state["nodes"]
    assert (
        state["edges"]["ruecknahme-hebt-auf-entfernung"]["type"]
        == "hebt_auf@1"
    )
    assert state["edges"][
        "ruecknahme-hebt-auf-entfernung"
    ]["target"] == "ralphex-entfernung-bei-bedingung"


def test_node_without_location_is_rejected(tmp_path):
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    op = _put_node(
        "x", location="irrelevant", data={"text": "t"}, sources=[ref],
    )
    del op["location"]
    delta = _delta(1, None, types=[_AUSSAGE_TYPE], nodes=[op])
    with pytest.raises(planning.PlanningError, match="location"):
        planning.append(
            tmp_path / "steps", _write(tmp_path, delta), root
        )


def test_edge_with_location_is_rejected(tmp_path):
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _ERSETZT_TYPE],
        nodes=[
            _put_node(
                "a", location="loc", data={"text": "a"}, sources=[ref]
            ),
            _put_node(
                "b", location="loc", data={"text": "b"}, sources=[ref]
            ),
        ],
        edges=[
            {
                **_put_edge("e", source="a", target="b", sources=[ref]),
                "location": "loc",
            }
        ],
    )
    with pytest.raises(planning.PlanningError, match="location"):
        planning.append(
            tmp_path / "steps", _write(tmp_path, delta), root
        )


def test_competing_replacement_is_rejected(tmp_path):
    """Konkurrierende Ersetzung: falsche `expected`-Revision wird
    abgelehnt."""
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    store = tmp_path / "steps"
    delta1 = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE],
        nodes=[
            _put_node(
                "x", location="loc", data={"text": "v1"}, sources=[ref]
            )
        ],
    )
    planning.append(store, _write(tmp_path, delta1, "a"), root)
    delta2 = _delta(
        2, planning.resolve(store)["head"], types=[],
        nodes=[_put_node(
            "x", location="loc", data={"text": "v2-falsche-revision"},
            sources=[ref], expected="0" * 64,
        )],
    )
    with pytest.raises(
        planning.PlanningError, match="revision mismatch"
    ):
        planning.append(store, _write(tmp_path, delta2, "b"), root)


def test_dangling_edge_is_rejected(tmp_path):
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE, _ERSETZT_TYPE],
        nodes=[
            _put_node(
                "a", location="loc", data={"text": "a"}, sources=[ref]
            )
        ],
        edges=[
            _put_edge("e", source="a", target="fehlt", sources=[ref])
        ],
    )
    with pytest.raises(planning.PlanningError, match="dangling edge"):
        planning.append(
            tmp_path / "steps", _write(tmp_path, delta), root
        )


def test_retired_identity_cannot_be_reused(tmp_path):
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    store = tmp_path / "steps"
    delta1 = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE],
        nodes=[
            _put_node(
                "x", location="loc", data={"text": "v1"}, sources=[ref]
            )
        ],
    )
    state = planning.append(store, _write(tmp_path, delta1, "a"), root)
    delta2 = _delta(
        2,
        state["head"],
        nodes=[
            {
                "id": "x",
                "op": "delete",
                "expected": state["nodes"]["x"]["revision"],
                "sources": [ref],
            },
        ],
    )
    state = planning.append(store, _write(tmp_path, delta2, "b"), root)
    delta3 = _delta(
        3,
        state["head"],
        types=[],
        nodes=[
            _put_node(
                "x", location="loc", data={"text": "v2"}, sources=[ref]
            )
        ],
    )
    with pytest.raises(
        planning.PlanningError, match="retired identity"
    ):
        planning.append(store, _write(tmp_path, delta3, "c"), root)


def test_source_changed_is_rejected(tmp_path):
    source_dir = tmp_path / "repo"
    source_dir.mkdir()
    source_file = source_dir / "note.md"
    source_file.write_text(
        "erste zeile\nzweite zeile\n", encoding="utf-8"
    )
    ref = planning.source_ref(source_dir, "note.md", 1, 1)
    store = tmp_path / "steps"
    delta = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE],
        nodes=[
            _put_node(
                "x", location="loc", data={"text": "v1"}, sources=[ref]
            )
        ],
    )
    planning.append(store, _write(tmp_path, delta, "a"), source_dir)
    source_file.write_text(
        "veraenderte erste zeile\nzweite zeile\n", encoding="utf-8"
    )
    delta2 = _delta(
        2, planning.resolve(store)["head"], types=[],
        nodes=[_put_node(
            "y", location="loc", data={"text": "v2"}, sources=[ref],
        )],
    )
    with pytest.raises(planning.PlanningError, match="source changed"):
        planning.append(
            store, _write(tmp_path, delta2, "b"), source_dir
        )


def test_resolve_at_k_is_deterministic(tmp_path):
    root = REPO_ROOT
    ref = planning.source_ref(
        root, "bd:ki-dev-ablauf-phdp", 358, 358,
    )
    store = tmp_path / "steps"
    delta1 = _delta(
        1,
        None,
        types=[_AUSSAGE_TYPE],
        nodes=[
            _put_node(
                "x", location="loc", data={"text": "v1"}, sources=[ref]
            )
        ],
    )
    state1 = planning.append(store, _write(tmp_path, delta1, "a"), root)
    delta2 = _delta(
        2, state1["head"], types=[],
        nodes=[_put_node(
            "y", location="loc", data={"text": "v2"}, sources=[ref],
        )],
    )
    planning.append(store, _write(tmp_path, delta2, "b"), root)
    at_1 = planning.resolve(store, at=1)
    assert list(at_1["nodes"]) == ["x"]
    at_2 = planning.resolve(store, at=2)
    assert set(at_2["nodes"]) == {"x", "y"}


def _write(tmp_path, delta, suffix=""):
    path = tmp_path / f"delta{suffix}.json"
    path.write_text(planning.encode(delta).decode(), encoding="utf-8")
    return path

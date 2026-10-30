"""Vorbereitung (Planungsquellen der ersten acht Sitzungen,
"regulaer") fuer den unabhaengigen Durchlauf ki-dev-ablauf-urq.6.

Baut einen echten, leeren Planungsgraphen-Speicher aus tatsaechlichen
Zitaten der Planungsquellen der ersten acht Sitzungen auf
(docs/architecture/planning-pruefbeispiele.de.md legt fest, dass
001-008 als "regulaere" Vorverarbeitung eingearbeitet werden, bevor
der budgetierte Testschritt 009/010 dagegen laeuft). Die
PB-1/PB-2/PB-2b/PB-3/PB-6-Zitate aus Quellen-Bead ki-dev-ablauf-phdp
und Codex-Sitzung 01a09aef bleiben dem Testschritt vorbehalten und
werden hier NICHT vorweggenommen.

Vor jeder Sitzung wird die bereichsuebergreifende Kandidatensuche
(pilot.search/pilot.workflow, Kontrollschritt) ueber den bis dahin
vorhandenen Bestand ausgefuehrt und ins Kontrollprotokoll geschrieben --
das ist die Grundlage der Suchtrefferquoten-Messpunkte nach 3/6
Sitzungen (docs/architecture/planning-pruefbeispiele.de.md, Abschnitt
"Suchtrefferquote").

Die Quellen sind lokale, nicht veroeffentlichte Planungsquellen
(persoenliche Gespraechsinhalte). Passagen und
docs/architecture/urq6-run/ nennen sie mit ortsunabhaengiger
Quellen-ID (bd:<Quellen-Bead> oder codex:<Sitzungs-ID>), nicht mit
lokalem Pfad. Bei Art-A-Quellen (codex:...) zaehlen start/end die
Zeilen der aufgezeichneten Kopie; im Transkript ist es Zeile + 1
(Zeile 1 ist transcript_meta). Die Hash-Kette des aufgezeichneten
Laufs ist damit nicht mehr pruefbar. Solange die Aufloesung ID ->
Datei fehlt (ki-dev-ablauf-xy78.2.1), bricht das Skript vor jedem
Lesen mit Exitcode 1 ab (ki_dev.pilot.quellen).

Nutzung:
    .venv/bin/python scripts/urq6_prep.py
"""

from __future__ import annotations

import random
from pathlib import Path

from ki_dev import planning
from ki_dev.pilot import quellen, search, workflow

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "docs/architecture/urq6-run"
STORE = RUN_DIR / "store"
LOG_PATH = RUN_DIR / "control-log.jsonl"
RNG_SEED = 20260915
TOP_K = 3
SAMPLE_SIZE = 5
BLIND_FRACTION = 0.4

AUSSAGE_TYPE = {
    "id": "aussage@1", "kind": "node",
    "schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}
ERSETZT_TYPE = {
    "id": "ersetzt_durch@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
BEZIEHT_SICH_AUF_TYPE = {
    "id": "bezieht_sich_auf@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
VORSCHLAEGT_ZURUECKSTELLUNG_TYPE = {
    "id": "vorschlaegt_zurueckstellung_von@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
HEBT_AUF_TYPE = {
    "id": "hebt_auf@1",
    "kind": "edge",
    "schema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}
ALL_TYPES = [
    AUSSAGE_TYPE, ERSETZT_TYPE, BEZIEHT_SICH_AUF_TYPE,
    VORSCHLAEGT_ZURUECKSTELLUNG_TYPE, HEBT_AUF_TYPE,
]

# Sitzung -> (Snapshot, freigegebene Vorbereitungs-Knoten, bekannter
# echter Bezug auf einen bereits vorhandenen Knoten [None, wenn keiner
# erwartet wird] -- fuer die Trefferquoten-Messung).
SESSIONS = [
    (
        "001",
        [
            {
                "id_": "bootstrap-ausfuehrung-ralphex",
                "location": "bootstrap/ausfuehrung",
                "text": (
                    "Damit sollte der Bootstrap Ralphex als vorhandene "
                    "Ausfuehrungs- und Reviewmaschine benutzen."
                ),
                "path": "bd:ki-dev-ablauf-9407",
                "start": 518,
                "end": 518,
                "expected_referent": None,
            },
            {
                "id_": "bootstrap-plan-stufen-1-4",
                "location": "bootstrap/plan",
                "text": (
                    "Damit ergibt sich ein stufenweiser Bootstrap "
                    "(Stufe 0-4)."
                ),
                "path": "bd:ki-dev-ablauf-9407",
                "start": 536,
                "end": 538,
                "expected_referent": None,
            },
        ],
    ),
    (
        "002",
        [
            {
                "id_": "bootstrap-technischer-rahmen",
                "location": "bootstrap/technik",
                "text": (
                    "Technischer Rahmen: Python, Typer, Rich, PyYAML, "
                    "jsonschema; Abhaengigkeiten in pyproject.toml."
                ),
                "path": "bd:ki-dev-ablauf-phdp",
                "start": 14,
                "end": 19,
                "expected_referent": None,
            },
        ],
    ),
    (
        "003",
        [
            {
                "id_": "fachschemas-sind-bootstrap-schemas",
                "location": "fachmodell/schemas",
                "text": (
                    "Die bestehenden ki-dev-Fachschemas sind "
                    "brauchbare Bootstrap-Schemas, aber noch kein "
                    "endgueltiges Fachmodell."
                ),
                "path": "bd:ki-dev-ablauf-0s5f",
                "start": 23,
                "end": 23,
                "expected_referent": None,
            },
        ],
    ),
    (
        "004",
        [
            {
                "id_": "arbeitsgraph-und-ralphex-ausstieg",
                "location": "architektur/arbeitsgraph",
                "text": (
                    "bd bleibt vorlaeufig der Arbeitsgraph. Ralphex "
                    "ist aus der neuen Minimal-Go-live-Strecke "
                    "herausgefallen."
                ),
                "path": "bd:ki-dev-ablauf-h1vf",
                "start": 18,
                "end": 19,
                # Echter fachlicher Bezug: dieselbe Ralphex-Rolle wie
                # Sitzung 1.
                "expected_referent": "bootstrap-ausfuehrung-ralphex",
            },
        ],
    ),
    (
        "005",
        [
            {
                "id_": "kern-verbindet-controller-worker",
                "location": "architektur/kern",
                "text": (
                    "Der erste ki-dev-Kern verbindet Controller und "
                    "Worker direkt ueber lokal angemeldete "
                    "Claude-/Codex-CLIs."
                ),
                "path": "bd:ki-dev-ablauf-9p4a",
                "start": 12,
                "end": 13,
                "expected_referent": None,
            },
        ],
    ),
    (
        "006",
        [
            {
                "id_": "snapshot-006-abschlussgrenze",
                "location": "prozess/snapshot-abschluss",
                "text": (
                    "Die Projektplanung endet fuer diesen Snapshot mit "
                    "Nachricht 24; ab Nachricht 26 wird die "
                    "abgeschlossene Planung nur noch aufgezeichnet und "
                    "geprueft."
                ),
                "path": "bd:ki-dev-ablauf-uoyb",
                "start": 13,
                "end": 13,
                "expected_referent": None,
            },
        ],
    ),
    (
        "007",
        [
            {
                "id_": "langgraph-empfehlung",
                "location": "architektur/orchestrator",
                "text": (
                    "LangGraph ist dabei am naechsten an einem eigenen "
                    "Orchestrator."
                ),
                "path": "bd:ki-dev-ablauf-74lc",
                "start": 3315,
                "end": 3315,
                "expected_referent": None,
            },
        ],
    ),
    (
        "008",
        [
            {
                "id_": "langgraph-entscheidung",
                "location": "architektur/orchestrator",
                "text": (
                    "Fuer den eigentlichen ki-dev loop ist LangGraph "
                    "sehr wahrscheinlich bereits die passendere "
                    "Grundlage; LangGraph ist dabei der "
                    "Orchestrator-Unterbau, nicht das fertige ki-dev."
                ),
                "path": "bd:ki-dev-ablauf-uxdk",
                "start": 52,
                "end": 52,
                # Echter fachlicher Bezug: Entscheidung folgt auf die
                # Empfehlung aus Sitzung 7 (dasselbe
                # LangGraph-Orchestrator-Thema).
                "expected_referent": "langgraph-empfehlung",
            },
        ],
    ),
]


def _node_op(id_, *, location, text, path, start, end):
    ref = planning.source_ref(ROOT, path, start, end)
    return {
        "id": id_, "op": "put", "expected": None, "type": "aussage@1",
        "location": location, "data": {"text": text}, "sources": [ref],
    }


def _write_delta(step, parent, *, types=(), nodes=()):
    delta = {
        "format": 1, "step": step, "parent": parent,
        "types": list(types), "nodes": list(nodes), "edges": [],
    }
    candidate = STORE.parent / f"_delta-{step:02d}.json"
    candidate.write_text(
        planning.encode(delta).decode(), encoding="utf-8"
    )
    return planning.append(STORE, candidate, ROOT)


def _units_from_state(state) -> list[search.Unit]:
    return [
        search.Unit(
            node["id"],
            node["revision"],
            node["location"],
            node["data"]["text"],
        )
        for node in state["nodes"].values()
    ]


def build() -> tuple[dict, list[dict]]:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "step": 0,
        "head": None,
        "types": {},
        "nodes": {},
        "edges": {},
        "retired": [],
    }
    rng = random.Random(RNG_SEED)
    checkpoints: list[dict] = []

    for index, (snapshot, passages) in enumerate(SESSIONS, start=1):
        existing_units = _units_from_state(state)
        node_ops = []
        for passage in passages:
            candidates = workflow.run_candidate_search(
                {"id": passage["id_"], "text": passage["text"]},
                existing_units,
                top_k=TOP_K,
                sample_size=SAMPLE_SIZE,
                blind_fraction=BLIND_FRACTION,
                rng=rng,
                log_path=LOG_PATH,
            )
            found = None
            if passage["expected_referent"] is not None:
                found = any(
                    c.unit_id == passage["expected_referent"]
                    and c.selection == "top_k"
                    for c in candidates
                )
                checkpoints.append({
                    "session": index, "part_id": passage["id_"],
                    "expected_referent": passage["expected_referent"],
                    "found_in_candidates": found,
                    "candidate_ids": [c.unit_id for c in candidates],
                })
            node_ops.append(
                _node_op(
                    passage["id_"],
                    location=passage["location"],
                    text=passage["text"],
                    path=passage["path"],
                    start=passage["start"],
                    end=passage["end"],
                )
            )
        types = ALL_TYPES if index == 1 else []
        state = _write_delta(
            index, state["head"], types=types, nodes=node_ops
        )
        print(f"Sitzung {index} (Snapshot {snapshot}): "
              f"+{len(node_ops)} Knoten, Bestand={len(state['nodes'])}")
    return state, checkpoints


def hit_rate_at(
    checkpoints: list[dict], *, through_session: int
) -> tuple[int, int]:
    applicable = [
        c for c in checkpoints if c["session"] <= through_session
    ]
    hits = sum(1 for c in applicable if c["found_in_candidates"])
    return hits, len(applicable)


if __name__ == "__main__":
    quellen.abbruch_ohne_quellablage(
        "SESSIONS[0][1][0].path", SESSIONS[0][1][0]["path"]
    )
    if STORE.exists():
        raise SystemExit(
            f"{STORE} existiert bereits; vorher entfernen."
        )
    final_state, checkpoints = build()

    print("\nBestand nach Vorbereitung (Sitzungen 1-8):")
    for node_id, node in sorted(final_state["nodes"].items()):
        print(
            f"  {node_id} @ {node['location']}: "
            f"{node['data']['text'][:70]!r}"
        )

    print(
        "\nSuchtrefferquote je Messpunkt (nur Sitzungen mit bekanntem "
        "echtem Bezug; Details siehe control-log.jsonl):"
    )
    for point in (3, 6):
        hits, total = hit_rate_at(checkpoints, through_session=point)
        if total == 0:
            print(f"  nach {point} Sitzungen: keine faellige Referenz "
                  f"(0/0, nicht auswertbar)")
        else:
            print(f"  nach {point} Sitzungen: {hits}/{total} "
                  f"({100 * hits / total:.0f} %)")
    print("\nDetail je Messpunkt:")
    for c in checkpoints:
        print(
            f"  Sitzung {c['session']}: {c['part_id']} -> erwartet "
            f"{c['expected_referent']!r}, "
            f"gefunden={c['found_in_candidates']}, "
            f"Kandidaten={c['candidate_ids']}"
        )

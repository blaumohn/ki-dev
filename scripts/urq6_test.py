"""Budgetierter Testschritt (Sitzung 9/10) fuer ki-dev-ablauf-urq.6.

Verarbeitet die in docs/architecture/planning-pruefbeispiele.de.md
festgelegten PB-1, PB-2, PB-2b, PB-5 (Sitzung 9) sowie PB-4 (dritter
Beitrag), PB-6, PB-7 (Sitzung 10) gegen den durch scripts/urq6_prep.py
vorbereiteten Bestand (Sitzungen 1-8). Mechanischer Teil (Kandidatensuche,
Kontrollprotokoll, begrenzter Abflachungskontext) ist deterministisch und
enthaelt kein LLM-Urteil -- die inhaltliche Zuordnung/Operation je Passage
liefert eine getrennte, blinde Abflachungsagent-Sitzung (siehe
docs/architecture/urq6-run/role1-prompt.md), nicht dieses Skript.

Nutzung:
    .venv/bin/python scripts/urq6_test.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from ki_dev import pilot_log, pilot_search, pilot_workflow, planning

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "docs/architecture/urq6-run"
STORE = RUN_DIR / "store"
LOG_PATH = RUN_DIR / "control-log.jsonl"
KONSTRUIERT_DOC = "docs/architecture/urq6-run/test-eingaben-konstruiert.de.md"
RNG_SEED = 20260915  # gleicher Seed wie urq6_prep.py: eine fortgesetzte Folge
TOP_K = 3
SAMPLE_SIZE = 5
BLIND_FRACTION = 0.4

# (Sitzung, [Passagen]). Jede Passage: id, location, text (echtes Zitat
# oder KONSTRUIERT, siehe planning-pruefbeispiele.de.md), Quelle
# (path/start/end), erwarteter Suchtreffer (None, wenn kein PB-Suchtest).
SESSION_9 = [
    dict(
        pb="PB-1 (Planerausgabe 1)", id_="ralphex-verbleib-bedingt",
        location="bootstrap/ralphex",
        text=(
            "Ich wuerde deshalb Ralphex jetzt nicht aus dem Bootstrap "
            "entfernen, aber die Annahme „Ralphex bleibt "
            "Implementation-Orchestrator des fertigen ki-dev“ als neue "
            "offene Planungsentscheidung markieren."
        ),
        path="bd:ki-dev-ablauf-phdp", start=102, end=102,
        expected_referent="bootstrap-ausfuehrung-ralphex",
    ),
    dict(
        pb="PB-1 (Planerausgabe 2)", id_="ralphex-entfernen-bedingt",
        location="bootstrap/ralphex",
        text="Ja. Unter dieser Voraussetzung wuerde ich Ralphex aus dem Bootstrap entfernen.",
        path="bd:ki-dev-ablauf-phdp", start=106, end=106,
        expected_referent="bootstrap-ausfuehrung-ralphex",
    ),
    dict(
        pb="PB-2", id_="bootstrap-plan-verwerfen-ersetzen",
        location="bootstrap/plan",
        text=(
            "Ich wuerde daher den bisherigen „Bootstrap Stufe "
            "1–4“-Plan weitgehend verwerfen und durch etwas wie "
            "„Minimal-Go-live von ki-dev“ ersetzen."
        ),
        path="bd:ki-dev-ablauf-phdp", start=358, end=358,
        expected_referent="bootstrap-plan-stufen-1-4",
    ),
    dict(
        pb="PB-2b (KONSTRUIERT)", id_="bootstrap-plan-verzweigte-ersetzung",
        location="bootstrap/plan",
        text=(
            "KONSTRUIERT: Der bisherige „Bootstrap Stufe "
            "1-4“-Plan wird nicht durch einen einzelnen Nachfolgeplan "
            "ersetzt, sondern in zwei parallele Nachfolgeplaene "
            "aufgespalten: „Minimal-Go-live von ki-dev“ und "
            "„Design-Notizen-Pilot als separater Versuch“."
        ),
        # Bewusst derselbe reale Anker wie PB-2 (planning-pruefbeispiele.de.md
        # PB-2b: "unter Wiederverwendung desselben Quellankers wie PB-2").
        path="bd:ki-dev-ablauf-phdp", start=358, end=358,
        expected_referent="bootstrap-plan-stufen-1-4",
    ),
    dict(
        pb="PB-5 (KONSTRUIERT)", id_="ralphex-entfernung-aufgehoben",
        location="bootstrap/ralphex",
        text=(
            "KONSTRUIERT: Die in Quellen-Bead ki-dev-ablauf-phdp (Zeile 106) beschlossene "
            "Entfernung von Ralphex aus dem Bootstrap wird aufgehoben. "
            "Ralphex bleibt endgueltig Teil des Bootstrap-Vorgehens; die "
            "Bedingung aus Zeile 102 gilt als nicht eingetreten."
        ),
        path=KONSTRUIERT_DOC, start=17, end=19,
        expected_referent=None,
    ),
]

SESSION_10 = [
    dict(
        pb="PB-4 (Zurueckstellungsvorschlag)",
        id_="langgraph-loop-zurueckstellung-vorschlag",
        location="architektur/orchestrator",
        text=(
            "Entscheidung: LangGraph ist als Orchestrierungsbasis "
            "vorgesehen. Vorschlag: Den eigenen Loop vorlaeufig "
            "zurueckstellen und Loope als Bootstrap verwenden."
        ),
        path="codex:01a09aef", start=60, end=60,
        expected_referent="langgraph-entscheidung",
    ),
    dict(
        pb="PB-6 (KONSTRUIERT)", id_="planungsspeicher-raumumbau",
        location="planungsspeicher/modell",
        text=(
            "KONSTRUIERT: Der bisherige Bereich planungsspeicher wird in "
            "planungsspeicher/modell und planungsspeicher/agentenablauf "
            "aufgeteilt. Die bestehende Einheit zur Unveraenderlichkeit "
            "gehoert ab jetzt zu planungsspeicher/modell."
        ),
        path=KONSTRUIERT_DOC, start=22, end=25,
        expected_referent=None,
    ),
    dict(
        pb="PB-7", id_="ki-verarbeitung-vier-wege",
        location="prozess/abflachung",
        text=(
            "Jede relevante Quellpassage muss einem Ergebnis zugeordnet "
            "sein: uebernommen, praezisiert, bereits enthalten oder "
            "ausdruecklich ausgeschlossen."
        ),
        path="codex:01a09aef", start=50, end=50,
        expected_referent=None,
    ),
]


def _units_from_state(state) -> list[pilot_search.Unit]:
    return [
        pilot_search.Unit(node["id"], node["revision"], node["location"], node["data"]["text"])
        for node in state["nodes"].values()
    ]


def _load_prep_state() -> dict:
    """Laedt den bereits committeten Vorbereitungsbestand (Sitzungen 1-8,
    scripts/urq6_prep.py) rein lesend -- kein erneutes `append`, das den
    bestehenden, unveraenderlichen Store verletzen wuerde."""
    return planning.resolve(STORE, root=ROOT)


def build_context_for_session(
    session_number: int, passages: list[dict], state: dict, rng: random.Random,
) -> tuple[list[dict], dict]:
    """Fuehrt den Kontrollschritt (Kandidatensuche) fuer eine Testsitzung
    aus und gibt (Checkpoints, begrenzter Kontext fuer den
    Abflachungsagenten) zurueck. Enthaelt keine inhaltliche Zuordnung/
    Operation -- das ist Aufgabe der getrennten, blinden Sitzung."""
    existing_units = _units_from_state(state)
    checkpoints = []
    released_passages = []
    visible_ids: set[str] = set()
    for passage in passages:
        candidates = pilot_workflow.run_candidate_search(
            {"id": passage["id_"], "text": passage["text"]}, existing_units,
            top_k=TOP_K, sample_size=SAMPLE_SIZE, blind_fraction=BLIND_FRACTION,
            rng=rng, log_path=LOG_PATH,
        )
        visible_ids.update(c.unit_id for c in candidates)
        if passage["expected_referent"] is not None:
            found = any(
                c.unit_id == passage["expected_referent"] and c.selection == "top_k"
                for c in candidates
            )
            checkpoints.append({
                "session": session_number, "pb": passage["pb"],
                "part_id": passage["id_"],
                "expected_referent": passage["expected_referent"],
                "found_in_candidates": found,
                "candidate_ids": [c.unit_id for c in candidates],
            })
        released_passages.append({
            "id": passage["id_"], "text": passage["text"],
            "location": passage["location"],
        })
    context = pilot_workflow.build_context(
        state, released_passages, visible_node_ids=visible_ids,
    )
    return checkpoints, context


def _context_to_json(context: pilot_workflow.FlatteningContext) -> dict:
    return {
        "released_passages": list(context.released_passages),
        "localized_nodes": context.localized_nodes,
        "localized_edges": context.localized_edges,
        "types": context.types,
    }


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    state = _load_prep_state()
    rng = random.Random(RNG_SEED)
    # RNG-Zustand an Sitzungen 1-8 anschliessen (gleicher Seed, gleiche
    # Ziehungsreihenfolge wie in urq6_prep.py), damit die Suche in Sitzung 9
    # deterministisch an Sitzung 8 anschliesst statt neu zu beginnen.
    for snapshot, passages in _replay_prep_draws():
        pass

    all_checkpoints = []
    for label, session_number, passages in (
        ("Sitzung 9", 9, SESSION_9), ("Sitzung 10", 10, SESSION_10),
    ):
        checkpoints, context = build_context_for_session(
            session_number, passages, state, rng,
        )
        all_checkpoints.extend(checkpoints)
        context_path = RUN_DIR / f"role1-context-{session_number:02d}.json"
        context_path.write_text(
            json.dumps(_context_to_json(context), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"{label}: Kontext geschrieben nach {context_path}")
        for c in checkpoints:
            print(f"  {c['pb']}: erwartet {c['expected_referent']!r}, "
                  f"gefunden={c['found_in_candidates']}, "
                  f"Kandidaten={c['candidate_ids']}")

    (RUN_DIR / "test-checkpoints.json").write_text(
        json.dumps(all_checkpoints, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print(f"\n{len(all_checkpoints)} Suchtreffer-Checkpoints "
          f"geschrieben nach {RUN_DIR / 'test-checkpoints.json'}")


def _replay_prep_draws():
    """Platzhalter: in dieser Skriptversion beginnt Sitzung 9 bewusst mit
    einem frischen `random.Random(RNG_SEED)` (siehe RNG_SEED oben) statt
    den Ziehungszustand aus urq6_prep.py fortzusetzen -- die Suche in
    Sitzung 9/10 ist damit unabhaengig vom genauen Ziehungsverlauf der
    Vorbereitung reproduzierbar, auf Kosten eines exakt fortgesetzten
    Zufallsstroms. Das ist eine bewusste Vereinfachung, keine verdeckte
    Vorwegnahme des Testergebnisses."""
    return []


if __name__ == "__main__":
    main()

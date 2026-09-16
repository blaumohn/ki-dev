"""Agenten- und Reviewablauf fuer den begrenzten
Designnotizen-Versuch (ki-dev-ablauf-urq.5).

Bindet die bereichsuebergreifende Kandidatensuche (pilot_search.py)
und das Kontrollprotokoll (pilot_log.py) an einen begrenzten Kontext
fuer den Abflachungsagenten: dieser sieht ausschliesslich freigegebene
neue Passagen, bedarfsgerecht lokalisierte Teile des aktuellen
Bestands und das Typregister -- kein Roharchiv, keine historische
Delta-Kette, keine verborgenen Pruefererwartungen (docs/architecture/
planning-verarbeitungsvertrag.de.md, Abschnitt "Zustaendigkeiten").

Die Kandidatensuche selbst ist ein Kontrollschritt, kein Werkzeug des
Abflachungsagenten: dieser erhaelt nur die daraus entstehenden
Kandidaten bzw. Befunde (siehe `run_candidate_search`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from ki_dev import pilot_log, pilot_search


@dataclass(frozen=True)
class FlatteningContext:
    """Der vollstaendige Kontext, den der Abflachungsagent sieht --
    und nichts darueber hinaus. `localized_nodes`/`localized_edges`
    enthalten nur `id`/`type`/`location`/`revision`/`data` je
    sichtbarer Einheit, keine `retired`-Liste, keinen `head`-Hash und
    keine Schrittfolge (das waere Zugriff auf die historische
    Delta-Kette, siehe urq.5-Umfang "kein Zugriff auf Roharchiv,
    historische Deltas oder verborgene Pruefererwartungen")."""

    released_passages: tuple[dict, ...]
    localized_nodes: dict[str, dict]
    localized_edges: dict[str, dict]
    types: dict[str, dict]


def build_context(
    state: dict, released_passages: list[dict], *,
    visible_node_ids: set[str],
    visible_edge_ids: set[str] = frozenset(),
) -> FlatteningContext:
    """Baut den begrenzten Kontext aus einem bereits aufgeloesten
    Zustand (`ki_dev.planning.resolve`) -- niemals aus den rohen
    Schrittdateien."""
    nodes = {
        node_id: _project(state["nodes"][node_id])
        for node_id in visible_node_ids
        if node_id in state["nodes"]
    }
    edges = {
        edge_id: _project(state["edges"][edge_id])
        for edge_id in visible_edge_ids
        if edge_id in state["edges"]
    }
    return FlatteningContext(
        tuple(released_passages), nodes, edges, dict(state["types"]),
    )


def run_candidate_search(
    part: dict, units: list[pilot_search.Unit], *, top_k: int,
    sample_size: int, blind_fraction: float, rng: random.Random,
    log_path: Path,
) -> list[pilot_search.Candidate]:
    """Kontrollschritt: bereichsuebergreifende Suche ueber *alle*
    `units` (kein Bereichsfilter), Blindanteil-Zuweisung, und
    Protokollierung als `search_record`-Eintraege vor Uebergabe an
    den Abflachungsagenten."""
    candidates = pilot_search.search_candidates(
        part["text"], units, top_k=top_k, sample_size=sample_size,
        rng=rng,
    )
    candidates = pilot_search.assign_blind_visibility(
        candidates, blind_fraction=blind_fraction, rng=rng,
    )
    for index, candidate in enumerate(candidates):
        pilot_log.append(log_path, pilot_log.search_record(
            id=f"{part['id']}-search-{index:03d}",
            part_id=part["id"], candidate=candidate,
        ))
    return candidates


def candidates_for_review(
    candidates: list[pilot_search.Candidate], *, rng: random.Random,
) -> list[pilot_search.ReviewCandidate]:
    """Was dem Review tatsaechlich vorgelegt wird: fuer den per
    `assign_blind_visibility` bestimmten Anteil sind Rang und Rohwert
    entfernt (urq.5-Umfang: teilweise blinder Review). Die vollen
    Werte bleiben ausschliesslich ueber die Original-`Candidate`-Liste
    (Kontrollprotokoll, `record_pair_judgment`) verfuegbar.

    `candidates` kommt sortiert nach Suchrang herein (Top-k zuerst).
    Ohne Durchmischung wuerde die reine Listenposition den Rang auch
    dann verraten, wenn `rank`/`raw_score` wegen `visible_in_review`
    ausgeblendet sind -- die Praesentationsreihenfolge muss deshalb
    unabhaengig vom Suchrang sein (`rng` statt Rangreihenfolge)."""
    order = list(candidates)
    rng.shuffle(order)
    return [pilot_search.for_review(candidate) for candidate in order]


def check_localization(
    unit: pilot_search.Unit, units: list[pilot_search.Unit], *,
    log_path: Path,
) -> dict | None:
    """Lokalisierungspruefung: Hinweis an den Review, wenn `unit`
    ihren Ortsnachbarn unaehnlicher ist als Einheiten an anderen
    Orten."""
    warning = pilot_search.localization_check(unit, units)
    if warning is not None:
        pilot_log.append(log_path, pilot_log.localization_warning(
            id=f"{unit.unit_id}-localization", part_id=unit.unit_id,
            warning=warning,
        ))
    return warning


def review_share_list(
    passage_id: str, part_ids: list[str], *, complete: bool,
    log_path: Path, notes: str = "",
) -> dict:
    """Gesonderter Review der Anteilsliste gegen die Passage, VOR der
    inhaltlichen Delta-Pruefung (urq.1: "Zerlegung in
    Bedeutungsanteile")."""
    return pilot_log.append(log_path, pilot_log.share_list_review(
        id=f"{passage_id}-shares", passage_id=passage_id,
        part_ids=part_ids, complete=complete, notes=notes,
    ))


def record_draft(
    passage_id: str, part: dict, *, assignment: str | None,
    operation: str, log_path: Path,
) -> dict:
    """Erstentwurf: Zuordnung und inhaltliche Operation sind
    getrennte, protokollierte Urteile (urq.1: "Zuordnung und
    inhaltliche Operation")."""
    return pilot_log.append(log_path, pilot_log.draft(
        id=f"{part['id']}-draft", passage_id=passage_id,
        part_id=part["id"], text=part["text"],
        assignment=assignment, operation=operation,
    ))


def record_finding(
    draft_record: dict, *, verdict: str, log_path: Path,
    notes: str = "",
) -> dict:
    """Reviewbefund zu einem Entwurf -- unterscheidbar vom Entwurf
    selbst."""
    return pilot_log.append(log_path, pilot_log.finding(
        id=f"{draft_record['id']}-finding",
        draft_id=draft_record["id"], verdict=verdict, notes=notes,
    ))


def record_correction(
    draft_record: dict, *, assignment: str | None, operation: str,
    log_path: Path, notes: str = "",
) -> dict:
    """Korrigierter Entwurf: referenziert den Erstentwurf explizit
    (`supersedes`) statt ihn als unabhaengige Beobachtung zu
    vermischen (urq.1: Korrekturrunden-Regel). Nur der abgenommene
    Entwurf -- der Erstentwurf oder diese Korrektur -- wird spaeter
    per `ki_dev.planning.append` in den Bestand uebernommen."""
    return pilot_log.append(log_path, pilot_log.correction(
        id=f"{draft_record['id']}-correction",
        supersedes=draft_record["id"],
        part_id=draft_record["part_id"], assignment=assignment,
        operation=operation, notes=notes,
    ))


def record_pair_judgment(
    part_id: str, candidate: pilot_search.Candidate, *, verdict: str,
    index: int, log_path: Path,
) -> dict:
    return pilot_log.append(log_path, pilot_log.pair_judgment(
        id=f"{part_id}-pair-{index:03d}", part_id=part_id,
        candidate=candidate, verdict=verdict,
    ))


def record_rejection(
    part_id: str, *, candidate_id: str | None, reason: str,
    index: int, log_path: Path,
) -> dict:
    return pilot_log.append(log_path, pilot_log.rejection(
        id=f"{part_id}-rejection-{index:03d}", part_id=part_id,
        candidate_id=candidate_id, reason=reason,
    ))


def record_unclear(
    part_id: str, *, candidate_id: str | None, reason: str,
    index: int, log_path: Path,
) -> dict:
    return pilot_log.append(log_path, pilot_log.unclear(
        id=f"{part_id}-unclear-{index:03d}", part_id=part_id,
        candidate_id=candidate_id, reason=reason,
    ))


def _project(entry: dict) -> dict:
    keys = (
        "id", "type", "location", "revision", "data", "source",
        "target",
    )
    return {key: entry[key] for key in keys if key in entry}

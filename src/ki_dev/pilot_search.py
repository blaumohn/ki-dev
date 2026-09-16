"""Bereichsuebergreifende Kandidatensuche fuer den Designnotizen-
Versuch.

Kontrollschritt aus ki-dev-ablauf-urq.5: ein kleines lokales
Embedding-Modell (deterministisches Hashing-Trigramm-Verfahren, keine
Netzwerk-/Modell-Downloads, kein Docker) ordnet Kandidaten ueber den
*gesamten* aktuellen Bestand per Brute-Force-Vergleich, ohne
Vektordatenbank. Die Suche ist kein Werkzeug des Abflachungsagenten
(siehe pilot_workflow.py); sie liefert nur die Kandidaten bzw. Befunde,
die dieser dann beurteilt (docs/architecture/
planning-verarbeitungsvertrag.de.md, Abschnitt "Kandidatensuche,
Aehnlichkeitswerte und Beziehungen").
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

MODEL_ID = "hashing-trigram-v1"
DIMENSIONS = 128


@dataclass(frozen=True)
class Unit:
    """Inhalt, Ort und Typ einer fachlichen Einheit, einbettbar."""

    unit_id: str
    revision: str
    location: str
    text: str


@dataclass(frozen=True)
class Candidate:
    """Ein Kandidat aus der Suche; Rang/Rohwert sind nur
    Kontrollprotokoll-Daten (urq.1), keine Kantengewichte im
    Planungsgraphen."""

    unit_id: str
    revision: str
    location: str
    raw_score: float
    rank: int | None
    selection: str  # "top_k" | "sample" | "manual"
    model_id: str = MODEL_ID
    visible_in_review: bool = True


def embed(text: str, *, dims: int = DIMENSIONS) -> tuple[float, ...]:
    """Deterministisches, lokales Bag-of-Trigrams-Embedding
    (Hashing-Trick)."""
    vector = [0.0] * dims
    for gram in _trigrams(text):
        vector[_bucket(gram, dims)] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(value / norm for value in vector)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Kosinus-Aehnlichkeit; beide Vektoren sind bereits normiert."""
    return sum(x * y for x, y in zip(a, b, strict=True))


def search_candidates(
    query_text: str, units: Iterable[Unit], *,
    top_k: int, sample_size: int, rng: random.Random,
) -> list[Candidate]:
    """Bereichsuebergreifende Brute-Force-Suche ueber *alle*
    uebergebenen Einheiten (kein Bereichsfilter) plus Zufallsstichprobe
    ausserhalb der angezeigten Top-k (Blindprobe gegen falsch-negative
    Kandidatensuche, siehe docs/architecture/
    planning-pruefbeispiele.de.md)."""
    if top_k < 0 or sample_size < 0:
        raise ValueError("top_k and sample_size must be non-negative")
    query_vector = embed(query_text)
    scored = sorted(
        (
            (unit, cosine(query_vector, embed(unit.text)))
            for unit in units
        ),
        key=lambda pair: pair[1], reverse=True,
    )
    top = scored[:top_k]
    rest = scored[top_k:]
    sample = (
        rng.sample(rest, k=min(sample_size, len(rest))) if rest else []
    )
    candidates = [
        Candidate(
            unit.unit_id, unit.revision, unit.location, score,
            rank=index + 1, selection="top_k",
        )
        for index, (unit, score) in enumerate(top)
    ]
    candidates += [
        Candidate(
            unit.unit_id, unit.revision, unit.location, score,
            rank=None, selection="sample",
        )
        for unit, score in sample
    ]
    return candidates


@dataclass(frozen=True)
class ReviewCandidate:
    """Was der Review tatsaechlich zu sehen bekommt: bei
    `visible_in_review=False` sind Rang und Rohwert entfernt, nicht
    nur mit einem Flag markiert (urq.5-Umfang: teilweise blinder
    Review). Das Kontrollprotokoll (pilot_log.py) protokolliert davon
    unabhaengig stets die vollen Werte aus dem zugrunde liegenden
    `Candidate`."""

    unit_id: str
    revision: str
    location: str
    selection: str
    raw_score: float | None
    rank: int | None


def for_review(candidate: Candidate) -> ReviewCandidate:
    """Blendet Rang und Rohwert fuer die Reviewpraesentation aus, wenn
    `candidate.visible_in_review` False ist."""
    visible = candidate.visible_in_review
    return ReviewCandidate(
        candidate.unit_id, candidate.revision, candidate.location,
        candidate.selection,
        raw_score=candidate.raw_score if visible else None,
        rank=candidate.rank if visible else None,
    )


def assign_blind_visibility(
    candidates: Sequence[Candidate], *, blind_fraction: float,
    rng: random.Random,
) -> list[Candidate]:
    """Legt fest, fuer welchen Anteil der Paare Rang/Rohwert im Review
    verborgen bleiben (urq.5-Umfang: teilweise blinder Review)."""
    if not 0.0 <= blind_fraction <= 1.0:
        raise ValueError("blind_fraction must be within [0, 1]")
    order = list(range(len(candidates)))
    rng.shuffle(order)
    blind_count = round(len(candidates) * blind_fraction)
    blind = set(order[:blind_count])
    return [
        replace(candidate, visible_in_review=index not in blind)
        for index, candidate in enumerate(candidates)
    ]


def localization_check(
    unit: Unit, units: Iterable[Unit], *, minimum_peers: int = 1,
) -> dict | None:
    """Hinweis, wenn `unit` ihren Ortsnachbarn unaehnlicher ist als
    Einheiten an anderen Orten (Lokalisierungspruefung, urq.5-Umfang).
    Gibt None zurueck, wenn kein Hinweis ausgeloest wird oder
    Vergleichsdaten fehlen."""
    query_vector = embed(unit.text)
    peers = [other for other in units if other.unit_id != unit.unit_id]
    same_location = [
        cosine(query_vector, embed(other.text))
        for other in peers
        if other.location == unit.location
    ]
    other_location = [
        cosine(query_vector, embed(other.text))
        for other in peers
        if other.location != unit.location
    ]
    if len(same_location) < minimum_peers or not other_location:
        return None
    best_same = max(same_location)
    best_other = max(other_location)
    if best_other <= best_same:
        return None
    return {
        "unit_id": unit.unit_id, "location": unit.location,
        "same_location_best": best_same,
        "other_location_best": best_other,
    }


def _trigrams(text: str) -> list[str]:
    cleaned = "".join(
        char if char.isalnum() else " " for char in text.lower()
    )
    padded = f"  {' '.join(cleaned.split())}  "
    if len(padded) < 3:
        return [padded]
    return [padded[i:i + 3] for i in range(len(padded) - 2)]


def _bucket(gram: str, dims: int) -> int:
    digest = hashlib.sha256(gram.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dims

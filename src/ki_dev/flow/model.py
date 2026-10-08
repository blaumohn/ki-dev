"""Gemeinsames Format aller Abläufe: Zustände und Übergänge als Daten.

Ein Ablauf ist ein erweiterter endlicher Automat (EFSM) in der
Schreibweise von UML-Zustandsmaschinen und SCXML::

    von --bei [wenn] / aktion--> nach

==============  =========================  ============================
TOML-Schlüssel  SCXML / UML                Bedeutung
==============  =========================  ============================
``von``         umschließender ``<state>``  Quellzustand (auch Liste)
``bei``         ``event``                  auslösendes Ereignis
``wenn``        ``cond`` / ``[guard]``     benannte Wächter (UND, ``!``)
``aktion``      ausführbarer Inhalt        benannte Kantenaktionen
``nach``        ``target``                 Zielzustand
``@fortsetzungspunkt``  ``<history>``      zurück zum Pausenursprung
==============  =========================  ============================

Der Ablauf legt nur Namen fest (``vokabular``). Was ein Wächter prüft
und was eine Aktion tut, implementiert der Ausführer; beim Binden prüft
er, dass er genau dieses Vokabular kennt. So bleibt die Topologie Daten
und das Vokabular Code, ohne dass eine Schicht die andere kennt.

Gleiche (``von``, ``bei``) sind erlaubt, wenn Wächter sie trennen: die
Kandidaten werden in Dateireihenfolge geprüft, der erste passende
gewinnt. Ein Übergang ohne ``wenn`` muss der letzte seiner Gruppe sein,
sonst wäre ein späterer unerreichbar. Passt kein Kandidat, ist das
Ereignis in diesem Zustand nicht erlaubt; einen stillen Standardfall
gibt es nicht.

Struktur prüft JSON Schema, Beziehungen prüfen benannte Funktionen
(Technikleitlinie). Diese Schicht führt nichts aus und importiert
weder Ausführer noch Adapter.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import cast

from jsonschema import Draft202012Validator

HISTORY = "@fortsetzungspunkt"
END_KIND = "ende"
WAIT_KIND = "warten"


class AblaufError(ValueError):
    """Ablauf verletzt Schema oder Beziehungen (Programmfehler)."""


@dataclass(frozen=True)
class Operation:
    """Was der Ausführer beim Betreten eines Zustands tut (Moore)."""

    tue: str
    wenn: tuple[str, ...] = ()


@dataclass(frozen=True)
class Zustand:
    id: str
    art: str
    wer: str | None = None
    operationen: tuple[Operation, ...] = ()


@dataclass(frozen=True)
class Uebergang:
    von: str
    bei: str
    nach: str
    wenn: tuple[str, ...] = ()
    aktion: tuple[str, ...] = ()
    eskalation: str | None = None
    befehl: str | None = None


@dataclass(frozen=True)
class Vokabular:
    arten: tuple[str, ...]
    ereignisse: tuple[str, ...]
    waechter: tuple[str, ...] = ()
    aktionen: tuple[str, ...] = ()
    eskalationen: tuple[str, ...] = ()
    operationen: tuple[str, ...] = ()
    pflicht: Mapping[str, tuple[str, ...]] = ()  # type: ignore[assignment]


@dataclass(frozen=True)
class Befundklasse:
    urteil: str
    text: str


@dataclass(frozen=True)
class Ablauf:
    name: str
    start: str
    ende: tuple[str, ...]
    vokabular: Vokabular
    zustaende: Mapping[str, Zustand]
    uebergaenge: tuple[Uebergang, ...]
    befundklassen: Mapping[str, Befundklasse]
    vorrang: tuple[str, ...]

    def ausgehend(self, zustand: str) -> tuple[Uebergang, ...]:
        self.zustand(zustand)
        return tuple(t for t in self.uebergaenge if t.von == zustand)

    def kandidaten(
        self, zustand: str, ereignis: str
    ) -> tuple[Uebergang, ...]:
        """Übergänge für (zustand, ereignis) in Prüfreihenfolge."""
        return tuple(
            t for t in self.ausgehend(zustand) if t.bei == ereignis
        )

    def zustand(self, zustand: str) -> Zustand:
        try:
            return self.zustaende[zustand]
        except KeyError:
            raise AblaufError(
                f"unbekannter Zustand: {zustand}"
            ) from None


def lade_ablauf(name: str) -> Ablauf:
    """Mitgelieferten Ablauf ``ki_dev/flow/<name>.toml`` laden.

    I/O-Grenze: Aufrufer laden einmal und reichen das geprüfte Objekt
    ausdrücklich weiter."""
    resource = files("ki_dev.flow").joinpath(f"{name}.toml")
    try:
        raw = tomllib.loads(resource.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise AblaufError(f"{name}.toml: kein gültiges TOML") from exc
    except FileNotFoundError as exc:
        raise AblaufError(f"unbekannter Ablauf: {name}") from exc
    return parse_ablauf(raw)


def lies_rohdaten(name: str) -> dict:
    """Rohdaten eines mitgelieferten Ablaufs (Werkzeuge, Tests)."""
    resource = files("ki_dev.flow").joinpath(f"{name}.toml")
    return tomllib.loads(resource.read_text(encoding="utf-8"))


def parse_ablauf(raw: object) -> Ablauf:
    """Erst Schema, dann Beziehungen prüfen; danach Objekte bauen."""
    _check_schema(raw)
    table = cast(dict, raw)
    where = f"{table['name']}.toml"
    ablauf = Ablauf(
        name=table["name"],
        start=table["start"],
        ende=tuple(table["ende"]),
        vokabular=_vokabular(
            table["vokabular"], table.get("pflicht", {})
        ),
        zustaende=_zustaende(table["zustand"], where),
        uebergaenge=tuple(
            uebergang
            for item in table["uebergang"]
            for uebergang in _uebergaenge(item)
        ),
        befundklassen={
            name: Befundklasse(item["urteil"], item["text"])
            for name, item in table.get("befundklasse", {}).items()
        },
        vorrang=tuple(table.get("vorrang", ())),
    )
    _check_relations(ablauf, where)
    return ablauf


def _vokabular(item: dict, pflicht: dict) -> Vokabular:
    return Vokabular(
        arten=tuple(item["arten"]),
        ereignisse=tuple(item["ereignisse"]),
        waechter=tuple(item.get("waechter", ())),
        aktionen=tuple(item.get("aktionen", ())),
        eskalationen=tuple(item.get("eskalationen", ())),
        operationen=tuple(item.get("operationen", ())),
        pflicht={art: tuple(events) for art, events in pflicht.items()},
    )


def _zustaende(items: list[dict], where: str) -> dict[str, Zustand]:
    zustaende: dict[str, Zustand] = {}
    for index, item in enumerate(items):
        if item["id"] in zustaende:
            raise AblaufError(
                f"{where}: zustand.{index}.id: doppelt ({item['id']})"
            )
        zustaende[item["id"]] = Zustand(
            id=item["id"],
            art=item["art"],
            wer=item.get("wer"),
            operationen=tuple(
                Operation(op["tue"], tuple(op.get("wenn", ())))
                for op in item.get("operation", ())
            ),
        )
    return zustaende


def _uebergaenge(item: dict) -> tuple[Uebergang, ...]:
    """``von`` als Liste ist dieselbe Kante aus mehreren Zuständen
    (flache Form eines gemeinsamen Elternzustands in SCXML)."""
    sources = (
        item["von"] if isinstance(item["von"], list) else [item["von"]]
    )
    return tuple(_uebergang(item, source) for source in sources)


def _uebergang(item: dict, von: str) -> Uebergang:
    return Uebergang(
        von=von,
        bei=item["bei"],
        nach=item["nach"],
        wenn=tuple(item.get("wenn", ())),
        aktion=tuple(item.get("aktion", ())),
        eskalation=item.get("eskalation"),
        befehl=item.get("befehl"),
    )


# --- Schema -----------------------------------------------------------

_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_ID = {"type": "string", "pattern": r"^[a-z_]+(\.[a-z_]+)?$"}
_NAME = {"type": "string", "pattern": r"^[A-Za-z_]+$"}
_NAMES = {"type": "array", "uniqueItems": True, "items": _NAME}
_GUARDS = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "pattern": r"^!?[A-Za-z_]+$"},
}

_SCHEMA = {
    "type": "object",
    "required": [
        "name",
        "start",
        "ende",
        "vokabular",
        "zustand",
        "uebergang",
    ],
    "additionalProperties": False,
    "dependentRequired": {
        "befundklasse": ["vorrang"],
        "vorrang": ["befundklasse"],
    },
    "properties": {
        "name": _ID,
        "start": _ID,
        "ende": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": _ID,
        },
        "vokabular": {
            "type": "object",
            "required": ["arten", "ereignisse"],
            "additionalProperties": False,
            "properties": {
                "arten": {**_NAMES, "minItems": 1},
                "ereignisse": {**_NAMES, "minItems": 1},
                "waechter": _NAMES,
                "aktionen": _NAMES,
                "eskalationen": _NAMES,
                "operationen": _NAMES,
            },
        },
        "pflicht": {
            "type": "object",
            "additionalProperties": _NAMES,
        },
        "befundklasse": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["urteil", "text"],
                "additionalProperties": False,
                "properties": {
                    "urteil": {"enum": ["CHANGES", "NEEDS_DECISION"]},
                    "text": _TEXT,
                },
            },
        },
        "vorrang": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": _ID,
        },
        "zustand": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "art"],
                "additionalProperties": False,
                "properties": {
                    "id": _ID,
                    "art": _NAME,
                    "wer": _TEXT,
                    "operation": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["tue"],
                            "additionalProperties": False,
                            "properties": {
                                "tue": _NAME,
                                "wenn": _GUARDS,
                            },
                        },
                    },
                },
            },
        },
        "uebergang": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["von", "bei", "nach"],
                "additionalProperties": False,
                "properties": {
                    "von": {
                        "anyOf": [
                            _ID,
                            {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": _ID,
                            },
                        ],
                    },
                    "bei": _NAME,
                    "nach": {
                        "anyOf": [_ID, {"const": HISTORY}],
                    },
                    "wenn": _GUARDS,
                    "aktion": {**_NAMES, "minItems": 1},
                    "eskalation": _NAME,
                    "befehl": _TEXT,
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(_SCHEMA)


def _check_schema(raw: object) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(raw), key=lambda e: list(e.absolute_path)
    )
    if errors:
        error = errors[0]
        name = raw.get("name") if isinstance(raw, dict) else None
        where = f"{name}.toml" if isinstance(name, str) else "Ablauf"
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise AblaufError(f"{where}: {path}: {error.validator}")


# --- Beziehungen (außerhalb des Schemas) ------------------------------


def _check_relations(ablauf: Ablauf, where: str) -> None:
    _check_kinds(ablauf, where)
    _check_classes(ablauf, where)
    _check_endpoints(ablauf, where)
    _check_operations(ablauf, where)
    _check_transitions(ablauf, where)
    _check_guard_order(ablauf, where)
    _check_required_events(ablauf, where)
    _check_end_reachable(ablauf, where)


def _check_kinds(ablauf: Ablauf, where: str) -> None:
    known = set(ablauf.vokabular.arten)
    if END_KIND not in known:
        raise AblaufError(f"{where}: vokabular.arten: {END_KIND} fehlt")
    for zustand in ablauf.zustaende.values():
        if zustand.art not in known:
            raise AblaufError(
                f"{where}: zustand {zustand.id}: unbekannte art "
                f"{zustand.art}"
            )
    for art in ablauf.vokabular.pflicht:
        if art not in known:
            raise AblaufError(f"{where}: pflicht.{art}: unbekannte art")


def _check_classes(ablauf: Ablauf, where: str) -> None:
    if set(ablauf.vorrang) != set(ablauf.befundklassen):
        raise AblaufError(
            f"{where}: vorrang: muss genau die Befundklassen nennen"
        )


def _check_endpoints(ablauf: Ablauf, where: str) -> None:
    for field, state in (
        ("start", ablauf.start),
        *(("ende", end) for end in ablauf.ende),
    ):
        if state not in ablauf.zustaende:
            raise AblaufError(
                f"{where}: {field}: unbekannter Zustand {state}"
            )
    for zustand in ablauf.zustaende.values():
        is_end = zustand.id in ablauf.ende
        if is_end != (zustand.art == END_KIND):
            raise AblaufError(
                f"{where}: zustand {zustand.id}: art {END_KIND} genau "
                "für die Zustände in ende"
            )


def _names(guards: Iterable[str]) -> set[str]:
    return {guard.removeprefix("!") for guard in guards}


def _check_operations(ablauf: Ablauf, where: str) -> None:
    vokabular = ablauf.vokabular
    for zustand in ablauf.zustaende.values():
        for index, op in enumerate(zustand.operationen):
            label = f"{where}: zustand {zustand.id}: operation.{index}"
            if op.tue not in vokabular.operationen:
                raise AblaufError(
                    f"{label}: unbekannte Operation {op.tue}"
                )
            _require_known(
                _names(op.wenn),
                vokabular.waechter,
                f"{label}.wenn",
                "Wächter",
            )
            last = index == len(zustand.operationen) - 1
            if not op.wenn and not last:
                raise AblaufError(
                    f"{label}: ohne wenn nur als letzte Operation"
                )


def _check_transitions(ablauf: Ablauf, where: str) -> None:
    vokabular = ablauf.vokabular
    events = set(vokabular.ereignisse)
    for index, t in enumerate(ablauf.uebergaenge):
        label = f"{where}: uebergang.{index}"
        _require_state(ablauf, t.von, f"{label}.von")
        if t.nach == HISTORY:
            if ablauf.zustand(t.von).art != WAIT_KIND:
                raise AblaufError(
                    f"{label}.nach: {HISTORY} nur aus art {WAIT_KIND}"
                )
        else:
            _require_state(ablauf, t.nach, f"{label}.nach")
        if t.bei not in events:
            raise AblaufError(
                f"{label}.bei: unbekanntes Ereignis {t.bei}"
            )
        _require_known(
            _names(t.wenn),
            vokabular.waechter,
            f"{label}.wenn",
            "Wächter",
        )
        _require_known(
            set(t.aktion),
            vokabular.aktionen,
            f"{label}.aktion",
            "Aktion",
        )
        if t.eskalation is not None:
            _require_known(
                {t.eskalation},
                vokabular.eskalationen,
                f"{label}.eskalation",
                "Eskalation",
            )


def _require_state(ablauf: Ablauf, state: str, label: str) -> None:
    if state not in ablauf.zustaende:
        raise AblaufError(f"{label}: unbekannter Zustand {state}")


def _require_known(
    names: set[str], known: Iterable[str], label: str, kind: str
) -> None:
    unknown = sorted(names - set(known))
    if unknown:
        raise AblaufError(
            f"{label}: unbekannte {kind} {', '.join(unknown)}"
        )


def _check_guard_order(ablauf: Ablauf, where: str) -> None:
    """Gleiche (von, bei) nur mit Wächtern; ungeschützt zuletzt."""
    groups: dict[tuple[str, str], list[Uebergang]] = {}
    for t in ablauf.uebergaenge:
        groups.setdefault((t.von, t.bei), []).append(t)
    for (von, bei), group in groups.items():
        for t in group[:-1]:
            if not t.wenn:
                raise AblaufError(
                    f"{where}: doppelter Übergang {von} bei {bei}"
                )


def _check_required_events(ablauf: Ablauf, where: str) -> None:
    pflicht = ablauf.vokabular.pflicht
    for zustand in ablauf.zustaende.values():
        present = {t.bei for t in ablauf.ausgehend(zustand.id)}
        missing = set(pflicht.get(zustand.art, ())) - present
        if missing:
            raise AblaufError(
                f"{where}: zustand {zustand.id}: fehlende Ereignisse "
                f"{', '.join(sorted(missing))}"
            )
        if zustand.art == END_KIND and present:
            raise AblaufError(
                f"{where}: zustand {zustand.id}: Ende ohne Übergänge"
            )


def ziele(ablauf: Ablauf, uebergang: Uebergang) -> set[str]:
    """Mögliche Ziele; ``@fortsetzungspunkt`` steht für jeden Zustand,
    aus dem eine Kante in den wartenden Zustand führt."""
    if uebergang.nach != HISTORY:
        return {uebergang.nach}
    return {
        t.von for t in ablauf.uebergaenge if t.nach == uebergang.von
    }


def reaching_end(ablauf: Ablauf) -> set[str]:
    """Zustände, von denen aus ein Ende erreichbar ist (rückwärts)."""
    reached = set(ablauf.ende)
    changed = True
    while changed:
        changed = False
        for t in ablauf.uebergaenge:
            if t.von not in reached and ziele(ablauf, t) & reached:
                reached.add(t.von)
                changed = True
    return reached


def _check_end_reachable(ablauf: Ablauf, where: str) -> None:
    dead = sorted(set(ablauf.zustaende) - reaching_end(ablauf))
    if dead:
        raise AblaufError(
            f"{where}: Sackgasse ohne Weg zu {', '.join(ablauf.ende)}: "
            f"{', '.join(dead)}"
        )

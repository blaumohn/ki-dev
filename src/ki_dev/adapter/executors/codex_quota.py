"""Fuenfstundenkontingent der Codex-CLI aus der lokalen Rollout-Ablage.

Codex schreibt ``token_count``-Ereignisse mit einer
``rate_limits``-Momentaufnahme (Felder ``primary``/``secondary``, je
``used_percent``/``window_minutes``/``resets_at``) in die lokale
Sitzungsablage unter ``~/.codex/sessions/JJJJ/MM/TT/rollout-*-
<session_id>.jsonl`` -- nachgewiesen sowohl fuer interaktive Sitzungen
als auch fuer ``codex exec`` (Herkunft ``codex_exec`` im
``session_meta``-Ereignis). Gelesen wird verbrauchsfrei, ohne
CLI-Aufruf.

Wie bei claude-cli misst erst die Antwort eines Aufrufs: Fehlt ein
aktueller Kontowert, ist der naechste Aufruf ``PENDING``
(:class:`QuotaPending`) und laeuft ungemessen; danach steht der Wert
in seiner eigenen Rollout-Datei.
"""

from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path

from .codex_sessions import find_session_rollout

FIVE_HOUR_WINDOW_MINUTES = 300

# Kontingent-Topf des Kontos (``rate_limits.limit_id``); aeltere
# Codex-Versionen schreiben kein ``limit_id``. Andere Toepfe (z. B.
# ``premium`` ohne Fenster oder modellgebundene mit eigenem 5h-Fenster)
# messen nicht das 5h-Kontingent der Codex-CLI und werden uebergangen.
_ACCOUNT_LIMITS = frozenset({None, "codex"})

# Betriebsvorgabe, keine Aktualitaetsgarantie: begrenzt nur, wie lange
# ein zuletzt bekannter Messwert noch als Naeherung gilt, bevor die
# Unsicherheit zu gross wird. Ein juengerer Wert kann trotzdem schon
# ueberholt sein, ein aelterer beweist mit Sicherheit nichts mehr.
MAX_MEASUREMENT_AGE_S = 1800

# Ein Ereignis-Zeitstempel spuerbar nach 'now' ist kein Uhrenversatz
# mehr, sondern ein unplausibler/widerspruechlicher Wert und wird
# abgelehnt statt als "besonders frisch" akzeptiert.
CLOCK_SKEW_TOLERANCE_S = 5


class QuotaPending(Exception):
    """Kein aktueller Kontowert; der naechste Aufruf misst ihn.

    Kein ``ValueError``: ein fehlender aktueller Wert ist ein benannter
    Anlass (``QuotaStatus.PENDING``), kein Lesefehler.
    """


def codex_quota(
    session_id: str | None, root: Path, now: float | None = None
) -> tuple[float, int]:
    """Kontoweit juengsten, noch hinreichend aktuellen 5h-
    Kontingentverbrauch und dessen Fenster-Ablaufzeit lesen.

    Das Kontingent ist kontoweit, nicht sitzungsgebunden: andere
    Sitzungen desselben Kontos koennen es zwischenzeitlich verbraucht
    haben. Gemessen wird deshalb das zeitlich juengste
    ``token_count``-Ereignis ueber ALLE lokalen Rollouts, ohne
    Fruehabbruch (``_freshest_account_window``): eine Beziehung
    zwischen Datei-Aenderungszeit und Ereignis-Zeitstempel ist technisch
    nicht garantiert (Kopien, Wiederherstellung, verzoegertes Schreiben;
    ki-dev-ablauf-dqv-Nachreview). Das 5h-Fenster ist das mit
    ``window_minutes == FIVE_HOUR_WINDOW_MINUTES``, nicht positional
    ``primary``.

    ``session_id`` ``None`` ist eine Sitzung, die der naechste Aufruf
    erst anlegt. Eine genannte Sitzung muss genau eine Rollout-Datei
    haben (Gueltigkeitspruefung, nicht die Messquelle).

    ``QuotaPending``, wenn kein aktueller Wert vorliegt: keiner fuer
    eine neue Sitzung, ein abgelaufenes Fenster oder ein Wert aelter als
    ``MAX_MEASUREMENT_AGE_S``. Hat die genannte Sitzung seit dem
    letzten Messwert schon ohne Messwert geantwortet, liefert Codex fuer
    dieses Konto keinen mehr: ``ValueError`` statt einer Folge
    ungemessener Aufrufe. Ebenso ohne jeden Messwert fuer eine
    genannte Sitzung.

    Setzt voraus, dass ``root`` (``CODEX_HOME``) fuer seine gesamte
    Standzeit genau ein Konto abbildet -- eine dokumentierte
    Betriebsvoraussetzung, technisch nicht pruefbar, da weder
    ``session_meta`` noch ``rate_limits`` ein Kontomerkmal tragen.
    ``MAX_MEASUREMENT_AGE_S`` begrenzt das Risiko eines Kontowechsels
    zusaetzlich (ki-dev-ablauf-hju, ueberarbeitet in dqv).
    """
    rollout = (
        None
        if session_id is None
        else find_session_rollout(root, session_id)
    )
    window = _freshest_account_window(root)
    if window is None:
        if rollout is None:
            raise QuotaPending(
                "neue Sitzung ohne Codex-5h-Messwert; Messung nach "
                "dem ersten Aufruf"
            )
        raise ValueError("Codex-Rollout hat keine 5h-Kontingentmessung")
    event_epoch, used_percent, resets_at = window
    now_s = now if now is not None else time.time()
    stale = _stale_reason(event_epoch, resets_at, now_s)
    if stale is None:
        return used_percent, resets_at
    if rollout is not None and _answered_since(rollout, event_epoch):
        raise ValueError(
            f"{stale}; diese Sitzung hat seitdem ohne 5h-Messwert "
            "geantwortet"
        )
    raise QuotaPending(f"{stale}; Messung nach diesem Aufruf")


def _stale_reason(
    event_epoch: float, resets_at: int, now_s: float
) -> str | None:
    """Warum der juengste Messwert nicht mehr gilt; ``None``, wenn er
    aktuell ist. Ein Zeitstempel nach 'now' ist kein Uhrenversatz mehr,
    sondern unplausibel: ``ValueError``."""
    if resets_at <= now_s:
        return "Codex-5h-Fenster des letzten Messwerts ist abgelaufen"
    age_s = now_s - event_epoch
    if age_s < -CLOCK_SKEW_TOLERANCE_S:
        raise ValueError(
            f"Codex-5h-Messwert liegt in der Zukunft "
            f"({-age_s:g}s nach 'now'); kein plausibler Nachweis"
        )
    if age_s > MAX_MEASUREMENT_AGE_S:
        return (
            f"letzter Codex-5h-Messwert ist zu alt ({age_s:g}s > "
            f"{MAX_MEASUREMENT_AGE_S}s)"
        )
    return None


def _answered_since(rollout: Path, event_epoch: float) -> bool:
    """Ob die Sitzung nach ``event_epoch`` ein ``token_count`` ohne
    5h-Messwert geschrieben hat (eine Antwort ohne Messung)."""
    with rollout.open(encoding="utf-8") as handle:
        for line in handle:
            row = _token_count_row(line)
            if row is None or row[0] <= event_epoch:
                continue
            if row[1] is None or _five_hour_window(row[1]) is None:
                return True
    return False


def _freshest_account_window(
    root: Path,
) -> tuple[float, float, int] | None:
    """Zeitlich juengstes ``token_count``-Ereignis mit Messwert ueber
    alle lokalen Rollouts; ``None`` ohne jeden Messwert. Bewusst ohne
    Suchbegrenzung (siehe ``codex_quota``); Vergleich ueber geparste
    Epochenwerte, nicht ueber Zeitstempel-Strings (unterschiedliche
    Nachkommastellen-Laenge sortiert als Text falsch, z. B. '...:00Z'
    nach '...:00.500Z')."""
    best = None
    for path in root.glob("*/*/*/rollout-*.jsonl"):
        found = _latest_five_hour_window(path)
        if found is not None and (best is None or found[0] > best[0]):
            best = found
    return best


def _latest_five_hour_window(
    path: Path,
) -> tuple[float, float, int] | None:
    """Groesster geparster Zeitwert innerhalb der Datei, nicht die
    physisch letzte Zeile: eine chronologisch sortierte Zeilenfolge
    ist technisch nicht garantiert (ki-dev-ablauf-dqv-Nachreview)."""
    latest = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = _token_count_row(line)
            if row is None or row[1] is None:
                continue
            epoch, rate_limits = row
            window = _five_hour_window(rate_limits)
            if window is not None and (
                latest is None or epoch > latest[0]
            ):
                latest = (epoch, *window)
    return latest


def _token_count_row(line: str) -> tuple[float, dict | None] | None:
    """Zeitpunkt und ``rate_limits`` (``None`` ohne Messwert) eines
    ``token_count``-Ereignisses des Konto-Topfs; ``None`` fuer andere
    Zeilen und andere Toepfe."""
    row = json.loads(line)
    if not isinstance(row, dict):
        raise ValueError("Codex-Rolloutzeile ist kein Objekt")
    payload = row.get("payload")
    if (
        row.get("type") != "event_msg"
        or not isinstance(payload, dict)
        or payload.get("type") != "token_count"
    ):
        return None
    rate_limits = payload.get("rate_limits")
    if rate_limits is not None:
        if not isinstance(rate_limits, dict):
            raise ValueError("Codex-rate_limits ist kein Objekt")
        if rate_limits.get("limit_id") not in _ACCOUNT_LIMITS:
            return None
    timestamp = row.get("timestamp")
    if type(timestamp) is not str or not timestamp:
        raise ValueError("Codex-Rolloutzeile ohne Zeitstempel")
    return _epoch_seconds(timestamp), rate_limits


def _epoch_seconds(timestamp: str) -> float:
    try:
        return datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        ).timestamp()
    except ValueError as exc:
        raise ValueError(
            f"ungueltiger Codex-Zeitstempel: {timestamp!r}"
        ) from exc


def _five_hour_window(rate_limits: dict) -> tuple[float, int] | None:
    """Verbrauch und Ablauf des 5h-Fensters; ``None``, wenn die Zeile
    keines traegt (etwa nur das Wochenfenster)."""
    for window in (
        rate_limits.get("primary"),
        rate_limits.get("secondary"),
    ):
        if not isinstance(window, dict):
            continue
        if window.get("window_minutes") != FIVE_HOUR_WINDOW_MINUTES:
            continue
        used_percent = window.get("used_percent")
        resets_at = window.get("resets_at")
        if (
            type(used_percent) not in (int, float)
            or not math.isfinite(used_percent)
            or used_percent < 0
            or type(resets_at) is not int
        ):
            raise ValueError("Codex-5h-Fenster ungueltig")
        return float(used_percent), resets_at
    return None

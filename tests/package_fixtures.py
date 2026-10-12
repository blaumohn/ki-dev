"""Testablauf für den generischen Runner: Text erzeugen und prüfen.

Kein Produktpaket; die echten Abläufe liegen in ki_dev/flow. Muster
und Katalog stehen hier, damit der Runner ohne Fachwissen prüfbar ist.
"""

import tomllib

from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import parse_flow

_FLOW = """
name = "{name}"
start = "produce"
final = ["accepted", "rejected"]

[vocabulary]
kinds = ["machine", "final"]
events = ["done", "PASS", "empty"]
operations = ["transform", "check_text"]

[op.transform]
do = "text.{name}"
input = ["source"]
output = "text"
success = "done"

[op.check_text]
do = "text.review"
input = ["text"]
output = "decision"
events = ["PASS", "empty"]

[pattern.produce_check]
globals = ["rejected"]

[[pattern.produce_check.state]]
local = "write"
kind = "machine"
operation = [{{ do = "produce", repeatable = true }}]

[[pattern.produce_check.state]]
local = "check"
kind = "machine"
operation = [{{ do = "inspect", repeatable = true }}]

[[pattern.produce_check.transition]]
source = "write"
event = "done"
target = "check"

[[pattern.produce_check.transition]]
source = "check"
event = "PASS"
target = "@next"

[[pattern.produce_check.transition]]
source = "check"
event = "empty"
target = "rejected"

[[phase]]
id = "produce"
use = "produce_check"
next = "accepted"
operation = {{ write = "transform", check = "check_text" }}

[[state]]
id = "accepted"
kind = "final"

[[state]]
id = "rejected"
kind = "final"
"""


def raw_flow(name: str = "normalize") -> dict:
    return tomllib.loads(_FLOW.format(name=name))


def text_flow(name: str = "normalize"):
    return parse_flow(raw_flow(name))

_TEXT = {"type": "string"}
_INPUT = {
    "type": "array",
    "prefixItems": [_TEXT],
    "minItems": 1,
    "maxItems": 1,
}


def normalize(value: str) -> str:
    return " ".join(value.split())


def uppercase(value: str) -> str:
    return value.upper()


def review(value: str) -> dict:
    """Ein leerer Text ist ein benannter Befund, keine Freitextkante."""
    return {"event": "PASS" if value.strip() else "empty"}


def catalog() -> dict[str, OperationSpec]:
    return {
        "text.normalize": OperationSpec(normalize, _INPUT, _TEXT),
        "text.uppercase": OperationSpec(uppercase, _INPUT, _TEXT),
        "text.review": OperationSpec(
            review,
            _INPUT,
            {
                "type": "object",
                "required": ["event"],
                "additionalProperties": False,
                "properties": {"event": {"enum": ["PASS", "empty"]}},
            },
        ),
    }

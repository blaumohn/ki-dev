"""Ein Ablauf als LangGraph-Graph: gemeinsam für run und step.

Jeder Zustand des Ablaufs wird ein Knoten, jede Kante eine mögliche
Verbindung (``@history`` aufgelöst), dazu die Selbstkante (eine
Operation läuft weiter oder ein Zustand hält an) und das Ende (Halt des
Ausführers). Welche Kante gilt, wählt nie der Graph, sondern der Ablauf
über den gebundenen Interpreter; der Graph führt aus, speichert
Checkpoints und hält mit ``interrupt``.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.graph import END, START, StateGraph

from ki_dev.flow.model import Flow, State, targets

END_ROUTE = "end"


def successors(flow: Flow, state: str) -> set[str]:
    """Mögliche Folgezustände laut Ablauf."""
    return {
        target
        for transition in flow.outgoing(state)
        for target in targets(flow, transition)
    }


def compile_flow(
    flow: Flow,
    schema: type,
    node: Callable[[State], Callable],
    route: Callable,
    checkpointer: object,
):
    """StateGraph aus ``flow``: ``node`` liefert die Funktion je
    Zustand, ``route`` den nächsten Zustand oder ``END_ROUTE``."""
    graph = StateGraph(schema)
    for state_id, flow_state in flow.states.items():
        graph.add_node(state_id, node(flow_state))
    # Der Start folgt dem Eingabezustand: ein Lauf kann in jeder Phase
    # beginnen (step --step graph), run beginnt in flow.start.
    graph.add_conditional_edges(
        START, route, {state_id: state_id for state_id in flow.states}
    )
    for state_id in flow.states:
        graph.add_conditional_edges(
            state_id,
            route,
            {
                **{
                    target: target
                    for target in successors(flow, state_id)
                },
                state_id: state_id,
                END_ROUTE: END,
            },
        )
    return graph.compile(checkpointer=checkpointer)

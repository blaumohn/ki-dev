"""Ausführung gebundener Katalogoperationen mit geprüften Nutzdaten."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict

from ki_dev.flow.binding import (
    BINDING_SCHEMA,
    Binding,
    BindingError,
    OperationSpec,
    project,
    validate,
)


class BoundOperations:
    def __init__(
        self,
        bindings: Mapping[str, Binding],
        catalog: Mapping[str, OperationSpec],
    ) -> None:
        self.bindings = bindings
        self.catalog = catalog
        for name, binding in bindings.items():
            raw = {
                k: v
                for k, v in asdict(binding).items()
                if v is not None and k != "events"
            }
            raw["input"] = list(binding.input)
            if binding.events:
                raw["events"] = list(binding.events)
            validate(raw, BINDING_SCHEMA, f"op.{name}")
            if binding.do not in catalog:
                raise BindingError(
                    f"op.{name}.do: unbekannte Operation"
                )

    def execute(self, name: str, data: Mapping[str, object]) -> object:
        args = self.inputs(name, data)
        spec = self.catalog[self.bindings[name].do]
        artifact = spec.execute(*args)
        self.accept(name, artifact)
        return artifact

    def inputs(self, name: str, data: Mapping[str, object]) -> list:
        binding = self.bindings[name]
        args = []
        for key in binding.input:
            if key not in data:
                raise BindingError(f"op.{name}.input.{key}: fehlt")
            args.append(data[key])
        spec = self.catalog[binding.do]
        validate(args, spec.input_schema, f"op.{name}.input")
        return args

    def accept(self, name: str, artifact: object) -> tuple[dict, str]:
        """Auch persistierte Artefakte vor ihrer Übernahme prüfen."""
        binding = self.bindings[name]
        spec = self.catalog[binding.do]
        validate(artifact, spec.output_schema, f"op.{name}.output")
        if spec.normalize is not None:
            artifact = spec.normalize(artifact)
        event = binding.success
        if event is None:
            validate(
                artifact,
                {
                    "type": "object",
                    "required": ["event"],
                    "properties": {
                        "event": {"enum": list(binding.events)}
                    },
                },
                f"op.{name}.output",
            )
            event = artifact["event"]
        update = (
            {binding.output: artifact}
            if isinstance(binding.output, str)
            else project(artifact, binding.output)
        )
        return update, event

"""Provenance tags for every input number used in the lunar base study."""

from __future__ import annotations

from dataclasses import dataclass

KINDS = ("cited", "computed", "estimated")


@dataclass(frozen=True)
class Value:
    value: float
    unit: str
    kind: str  # one of KINDS
    source: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}, got {self.kind!r}")
        if self.kind == "cited" and not self.source:
            raise ValueError("a cited value needs a source")

    def __float__(self) -> float:
        return float(self.value)


def table(values: dict[str, Value]) -> list[dict[str, str]]:
    """Rows for a provenance table in the report."""
    return [
        {"name": k, "value": f"{v.value:g}", "unit": v.unit, "kind": v.kind, "source": v.source}
        for k, v in values.items()
    ]

"""Load and validate rules.yaml into plain dataclasses. Any mistake fails loudly at load time."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.engine.model import SEVERITY_ORDER

RULES_FILE = Path(__file__).with_name("rules.yaml")
_SELECTOR = re.compile(r"^(EPC|ATC|FLAG|ING):(.+)$")
_ATC4 = re.compile(r"^[A-Z]\d{2}[A-Z]{2}$")
FLAGS = {"qt_prolonging", "serotonergic", "cns_depressant"}


class RuleError(ValueError):
    pass


@dataclass(frozen=True)
class Selector:
    kind: str  # EPC | ATC | FLAG | ING
    value: str


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    selectors: tuple[Selector, ...]


@dataclass(frozen=True)
class Text:
    title: str
    simple: str
    professional: str
    consider: str


@dataclass(frozen=True)
class CumulativeRule:
    id: str
    groups: tuple[str, ...]
    min_drugs: int
    min_groups: int
    require_groups: tuple[tuple[str, ...], ...]
    severity: str
    text: Text
    rationale: str


@dataclass(frozen=True)
class RuleSet:
    version: int
    groups: dict[str, Group]
    dup_ingredient_id: str
    dup_ingredient_severity: str
    dup_ingredient_text: Text
    dup_class_id: str
    dup_class_text: Text
    dup_class_groups: dict[str, str]  # group -> severity
    cumulative: tuple[CumulativeRule, ...]


def _text(raw: dict[str, Any], where: str) -> Text:
    try:
        return Text(*(str(raw[k]).strip() for k in ("title", "simple", "professional", "consider")))
    except KeyError as exc:
        raise RuleError(f"{where}: missing {exc}") from exc


def _severity(value: str, where: str) -> str:
    if value not in SEVERITY_ORDER or value == "unknown":
        raise RuleError(f"{where}: invalid severity {value!r}")
    return value


def parse_rules(raw: dict[str, Any]) -> RuleSet:
    groups: dict[str, Group] = {}
    for key, spec in raw["groups"].items():
        selectors = []
        for item in spec["select"]:
            match = _SELECTOR.match(item)
            if not match:
                raise RuleError(f"group {key}: bad selector {item!r}")
            kind, value = match.groups()
            if kind == "ATC" and not _ATC4.match(value):
                raise RuleError(f"group {key}: ATC selectors must be exact level-4 codes: {value}")
            if kind == "FLAG" and value not in FLAGS:
                raise RuleError(f"group {key}: unknown flag {value}")
            selectors.append(Selector(kind, value))
        groups[key] = Group(key, str(spec["label"]), tuple(selectors))

    di, dc = raw["duplicate_ingredient"], raw["duplicate_class"]
    dup_groups = {g: _severity(s, f"duplicate_class.{g}") for g, s in dc["groups"].items()}
    for g in dup_groups:
        if g not in groups:
            raise RuleError(f"duplicate_class: unknown group {g}")

    cumulative = []
    for spec in raw["cumulative"]:
        rid = spec["id"]
        rule_groups = tuple(spec["groups"])
        require = tuple(tuple(alt) for alt in spec.get("require_groups", []))
        for g in rule_groups + tuple(x for alt in require for x in alt):
            if g not in groups:
                raise RuleError(f"{rid}: unknown group {g}")
        cumulative.append(
            CumulativeRule(
                id=rid,
                groups=rule_groups,
                min_drugs=int(spec["min_drugs"]),
                min_groups=int(spec.get("min_groups", 1)),
                require_groups=require,
                severity=_severity(spec["severity"], rid),
                text=_text(spec, rid),
                rationale=" ".join(str(spec.get("rationale", "")).split()),
            )
        )
    return RuleSet(
        version=int(raw["version"]),
        groups=groups,
        dup_ingredient_id=di["id"],
        dup_ingredient_severity=_severity(di["severity"], "duplicate_ingredient"),
        dup_ingredient_text=_text(di, "duplicate_ingredient"),
        dup_class_id=dc["id"],
        dup_class_text=_text(dc, "duplicate_class"),
        dup_class_groups=dup_groups,
        cumulative=tuple(cumulative),
    )


@lru_cache
def load_rules(path: Path = RULES_FILE) -> RuleSet:
    with path.open(encoding="utf-8") as fh:
        return parse_rules(yaml.safe_load(fh))

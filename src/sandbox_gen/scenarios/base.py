"""Scenario data model. A scenario = template tree + a merged change + an open PR."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ASSETS = Path(__file__).resolve().parent.parent / "assets"


@dataclass(frozen=True)
class Write:
    """Create or overwrite a file."""

    path: str
    content: str


@dataclass(frozen=True)
class Replace:
    """Replace text that must occur exactly once in the file."""

    path: str
    old: str
    new: str


@dataclass(frozen=True)
class Append:
    path: str
    text: str


@dataclass(frozen=True)
class CopyAsset:
    """Overwrite path with a file from sandbox_gen/assets/."""

    path: str
    asset: str


Op = Write | Replace | Append | CopyAsset


@dataclass(frozen=True)
class Expected:
    """End-to-end outcome; the acceptance test for later phases."""

    final: Literal["pushed", "escalated"]
    stage: Literal["policy", "orchestrator", "resolver", "verifier", "stale", "push"]
    note: str


@dataclass(frozen=True)
class Change:
    title: str
    body: str
    ops: tuple[Op, ...]


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    merged: Change
    pr: Change
    expected: Expected
    # Exact expected values for Signals fields (checked by tests/unit/test_scenario_signals.py).
    expected_signals: dict = field(default_factory=dict)


def apply(tree: dict[str, str], ops: tuple[Op, ...]) -> dict[str, str]:
    tree = dict(tree)
    for op in ops:
        match op:
            case Write(path, content):
                tree[path] = content
            case Replace(path, old, new):
                count = tree[path].count(old)
                if count != 1:
                    raise ValueError(f"{path}: expected 1 match for replace, found {count}")
                tree[path] = tree[path].replace(old, new)
            case Append(path, text):
                tree[path] = tree[path] + text
            case CopyAsset(path, asset):
                tree[path] = (ASSETS / asset).read_text()
    return tree

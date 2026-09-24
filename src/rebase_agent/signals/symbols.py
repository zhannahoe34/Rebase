"""Which Python definitions a change modifies, via `ast` line spans vs. `git diff -U0` hunks.

Covers definitions only, not call sites (PLAN.md Q3): a PR that adds a call to a function
the merged change modified does not count as overlap.
"""

import ast
import re
from pathlib import Path

from rebase_agent.git_ops import changed_files, show_file, unified_diff

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _def_spans(source: str) -> list[tuple[str, int, int]]:
    """(qualname, first_line, last_line) for every function/class, nested included."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    spans: list[tuple[str, int, int]] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{prefix}{child.name}"
                first = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                spans.append((name, first, child.end_lineno or child.lineno))
                visit(child, f"{name}.")

    visit(tree, "")
    return spans


def _hunk_lines(diff: str) -> tuple[set[int], set[int]]:
    """Changed line numbers on the old side and new side of a -U0 diff.

    Insertions only have new lines and deletions only old lines; checking both sides against
    the matching file version catches either.
    """
    old: set[int] = set()
    new: set[int] = set()
    for m in _HUNK.finditer(diff):
        o_start, o_len = int(m[1]), int(m[2] if m[2] is not None else 1)
        n_start, n_len = int(m[3]), int(m[4] if m[4] is not None else 1)
        old.update(range(o_start, o_start + o_len))
        new.update(range(n_start, n_start + n_len))
    return old, new


def _touched(spans: list[tuple[str, int, int]], lines: set[int]) -> set[str]:
    return {name for name, first, last in spans if any(first <= n <= last for n in lines)}


def modified_symbols(repo: Path, old: str, new: str) -> set[str]:
    """`path:qualname` of every definition whose old or new span a change touches."""
    result: set[str] = set()
    for path in changed_files(repo, old, new):
        if not path.endswith(".py"):
            continue
        old_lines, new_lines = _hunk_lines(unified_diff(repo, old, new, path))
        names: set[str] = set()
        if (src := show_file(repo, old, path)) is not None:
            names |= _touched(_def_spans(src), old_lines)
        if (src := show_file(repo, new, path)) is not None:
            names |= _touched(_def_spans(src), new_lines)
        result |= {f"{path}:{name}" for name in names}
    return result

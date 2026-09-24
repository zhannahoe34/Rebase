"""Shared pydantic types. Later phases add PRSummary, Decision, ResolverResult, etc. (PLAN.md §0.4)."""

from typing import Literal

from pydantic import BaseModel

Category = Literal["lockfile", "migration", "ci", "config", "auth"]
CATEGORIES: tuple[Category, ...] = ("lockfile", "migration", "ci", "config", "auth")


class TouchInfo(BaseModel):
    merged: list[str] = []  # paths in the merged change in this category
    pr: list[str] = []  # paths in the PR in this category


class Signals(BaseModel):
    conflict_count: int  # conflicted files from merge-tree dry run
    conflicted_files: list[str]
    file_overlap: list[str]  # paths changed by both sides
    symbol_overlap: list[str]  # "path:qualname" defs modified by both sides
    diff_lines_merged: int
    diff_lines_pr: int
    touches: dict[Category, TouchInfo]

from rebase_agent.signals.symbols import _def_spans, _hunk_lines, modified_symbols

from .conftest import git

SRC = """\
def a():
    return 1


class C:
    @staticmethod
    def m():
        return 2
"""


def test_def_spans_include_nested_and_decorators():
    assert _def_spans(SRC) == [("a", 1, 2), ("C", 5, 8), ("C.m", 6, 8)]


def test_def_spans_tolerate_syntax_errors():
    assert _def_spans("def broken(:\n") == []


def test_hunk_lines_insert_delete_modify():
    diff = "@@ -2,0 +3,2 @@\n@@ -5,2 +6,0 @@\n@@ -9 +9 @@\n"
    old, new = _hunk_lines(diff)
    assert old == {5, 6, 9}
    assert new == {3, 4, 9}


def test_deleting_a_function_counts_as_modifying_it(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "m.py").write_text(SRC)
    git(tmp_path, "add", "m.py")
    git(tmp_path, "commit", "-qm", "one")
    (tmp_path / "m.py").write_text(SRC.split("\n\n\nclass")[0] + "\n")
    git(tmp_path, "commit", "-qam", "two")
    assert modified_symbols(tmp_path, "HEAD~1", "HEAD") == {"m.py:C", "m.py:C.m"}

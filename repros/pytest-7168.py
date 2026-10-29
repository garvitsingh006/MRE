"""Reproduce pytest-dev__pytest-7168 without invoking pytest's test runner.

The buggy pytest saferepr implementation accesses obj.__class__ while trying
to render an object with a broken __repr__. Our __getattribute__ raises in
that case. The gold patch uses type(obj).__name__ instead.
"""

from _pytest._io.saferepr import saferepr


class SomeClass:
    def __getattribute__(self, name):
        raise RuntimeError("attribute access is broken")

    def __repr__(self):
        raise RuntimeError("repr is broken")


representation = saferepr(SomeClass())
assert "SomeClass object at 0x" in representation, representation

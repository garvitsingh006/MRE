"""MRE for SWE-bench Lite instance sympy__sympy-12454.

Original GitHub issue: sympy/sympy#12452; fixed by PR #12454.
The tall 4x2 zero matrix should be upper triangular. The buggy commit
raises IndexError inside SymPy while evaluating `is_upper`.

This is a hand-written candidate. It still requires a real Docker
before/after verification on the pinned SWE-bench commit.
"""
from sympy import zeros

matrix = zeros(4, 2)
assert matrix.is_upper is True, "A zero matrix is upper triangular"

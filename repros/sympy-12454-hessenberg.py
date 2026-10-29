"""Optional *second behavior* for the SAME SymPy #12454 issue.

This is not a second benchmark issue; it exercises the related
is_upper_hessenberg defect fixed in the same PR.
"""
from sympy import zeros

matrix = zeros(4, 2)
assert matrix.is_upper_hessenberg is True, "A zero matrix is upper Hessenberg"

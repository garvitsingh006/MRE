from _pytest._io.saferepr import safe_repr


class Unrepresentable:
    def __getattribute__(self, name):
        raise RuntimeError("attribute access failed")

    def __repr__(self):
        raise ValueError("representation failed")


safe_repr(Unrepresentable())
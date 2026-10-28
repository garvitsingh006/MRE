class SomeClass:
    def __getattribute__(self, attr):
        raise

    def __repr__(self):
        raise

def test():
    SomeClass().attr
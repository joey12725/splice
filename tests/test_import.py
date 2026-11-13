from pathlib import Path


def test_public_imports() -> None:
    # Import should be side-effect free and expose the expected symbols
    from splice import Session, Splice  # noqa: F401


def test_session_ensure() -> None:
    from splice import Session

    s1 = Session.ensure()
    assert isinstance(s1.id, str) and len(s1.id) > 0

    s2 = Session.ensure(s1)
    assert s2 is s1


def test_find_splice_directory() -> None:
    from splice.paths import find_splice_directory

    path = find_splice_directory()
    assert isinstance(path, Path)

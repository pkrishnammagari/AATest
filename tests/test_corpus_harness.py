"""The corpus harness (scripts/check_corpus.py) proves each of its checks can
fire: its self-test mutates the committed fixtures and requires every check
to catch its mutation. Chrome-backed cases skip themselves without Chrome."""

from __future__ import annotations

from corpus import selftest  # scripts/corpus/selftest.py


def test_every_corpus_check_fires_on_its_mutation():
    results = selftest.run()
    failed = [(name, detail) for name, ok, detail in results if not ok]
    assert results and not failed

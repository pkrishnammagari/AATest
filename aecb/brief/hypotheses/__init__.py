"""The fresh lens's hypothesis -> verification loop.

    grammar     the closed set of hypothesis types, their parameters, the
                output schema for pass H and the parser that turns the model's
                reply into typed hypotheses and custom observations
    verify      one deterministic verifier per type; confirmed and refuted
                results become citable facts (theme "verified")
    candidates  the Python fallback list, run through the same verifiers when
                the model proposes no typed hypothesis

The model proposes, Python tests, the model writes: a pattern finding in the
fresh lens can rest on a verified fact whose figures were computed here, and
a hypothesis the data refutes is recorded as refuted rather than forgotten.
"""

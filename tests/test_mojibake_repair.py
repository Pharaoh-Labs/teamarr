"""Tests for the safer, generic double-encoded-UTF-8 repair (Phase 3a, item 15).

Today, ``fix_mojibake`` in normalizer.py only fixes a hard-coded list of
German/Spanish/French character patterns (MOJIBAKE_PATTERNS), and
``_fix_double_encoded_utf8`` in m3u.py does a bare latin-1-encode /
utf-8-decode round trip with no guard against producing U+FFFD replacement
characters.

New contract: a new pure function ``try_fix_double_encoded(text)`` in
normalizer.py generalizes the round-trip repair (so Nordic/Polish characters
work, not just the hard-coded list), while guaranteeing it never returns text
containing U+FFFD and leaves legitimate non-mojibake text alone. Per the
spec, ``_fix_double_encoded_utf8`` should delegate to this new function
instead of duplicating the recode logic.

We import the ``normalizer`` module (not the name) so a currently-missing
``try_fix_double_encoded`` fails each test individually via AttributeError
rather than blowing up collection for the whole file.
"""

from teamarr.consumers.matching import normalizer


def test_fixes_german_umlaut_round_trip():
    mojibake = "München".encode().decode("latin-1")
    assert normalizer.try_fix_double_encoded(mojibake) == "München"


def test_fixes_nordic_o_slash_round_trip():
    # Danish/Norwegian "ø" -- NOT in the current MOJIBAKE_PATTERNS list, so
    # fix_mojibake() cannot handle it today. The new generic function must.
    mojibake = "København".encode().decode("latin-1")
    assert normalizer.try_fix_double_encoded(mojibake) == "København"


def test_fixes_polish_n_acute_round_trip():
    # Compute the double-encoded fixture from the correct string itself (per
    # spec) so the test input is provably a genuine double-encoding of
    # "Gdańsk", not a hand-typed guess.
    correct = "Gdańsk"
    mojibake = correct.encode("utf-8").decode("latin-1")
    assert normalizer.try_fix_double_encoded(mojibake) == correct


def test_leaves_legitimate_capital_a_tilde_text_unchanged():
    # "SÃO PAULO FC": capital Ã (U+00C3) followed by capital O is not a valid
    # UTF-8 continuation byte sequence when re-encoded as latin-1 and decoded
    # as UTF-8, so the recode must fail cleanly and the safer implementation
    # must return the original text rather than mangling it.
    text = "SÃO PAULO FC"
    assert normalizer.try_fix_double_encoded(text) == text


def test_result_never_contains_replacement_character():
    candidates = [
        "München".encode().decode("latin-1"),
        "SÃO PAULO FC",
        "Plain ASCII text",
        "Gdańsk".encode().decode("latin-1"),
    ]
    for text in candidates:
        assert "�" not in normalizer.try_fix_double_encoded(text)


def test_idempotent_on_already_fixed_text():
    # Applying the repair to already-correct text must be a no-op, and
    # applying it twice must equal applying it once.
    once = normalizer.try_fix_double_encoded("München")
    twice = normalizer.try_fix_double_encoded(once)
    assert once == "München"
    assert twice == once


def test_plain_ascii_unchanged():
    assert normalizer.try_fix_double_encoded("ESPN HD") == "ESPN HD"

"""Contextless-suffix resolution (#418).

A valid registry variable with a legal suffix whose game context is missing
(no next/last game — offseason, season end) resolves to empty + cleanup, so
raw ``{game_time.next}`` braces never reach a real guide. Typos and illegal
suffix usage stay literal — the typo-surfacing rationale only ever applied to
template errors, not missing context.
"""

from teamarr.templates.resolver import TemplateResolver


def _resolver() -> TemplateResolver:
    return TemplateResolver()


def test_valid_next_suffix_without_context_resolves_empty():
    # Map has no .next entries — the no-next-game case.
    out = _resolver().resolve_with_map(
        "Next game: {game_date.next} at {game_time.next} vs {opponent.next}",
        {"team_name": "Spurs"},
    )
    assert "{" not in out
    assert out == "Next game: at vs"


def test_valid_last_suffix_without_context_resolves_empty():
    out = _resolver().resolve_with_map("Last: {final_score.last}", {})
    assert out == "Last:"


def test_typo_stays_literal():
    out = _resolver().resolve_with_map("{game_tmie.next} and {not_a_var}", {})
    assert out == "{game_tmie.next} and {not_a_var}"


def test_illegal_suffix_on_base_only_variable_stays_literal():
    # matchup_combat is BASE_ONLY — .next on it is a template error.
    out = _resolver().resolve_with_map("{matchup_combat.next}", {})
    assert out == "{matchup_combat.next}"


def test_present_context_still_wins():
    out = _resolver().resolve_with_map(
        "Next: {opponent.next}", {"opponent.next": "Lakers"}
    )
    assert out == "Next: Lakers"


def test_cleanup_removes_empty_wrappers_around_blanked_suffix():
    out = _resolver().resolve_with_map("Tonight ({game_time.next})", {})
    assert out == "Tonight"

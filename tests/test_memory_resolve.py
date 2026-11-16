"""The entity resolution port's unit tests: name tiers and the rules.

Table-driven over the donor's matchStrength tiers (src/names.ts) and
the resolution rules (src/resolve.ts): longest-name-first ordering, the
strong pass before the weak pass, the co-occurrence winner, alias
accumulation, canonical promotion, and type inference only from
"other". The algorithm runs against a fake repo with the same four
methods the store implements, so no database is involved here.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.memory.resolve import (
    EntityRef,
    Mention,
    StoredEntity,
    display_name,
    levenshtein,
    match_strength,
    resolve_mentions,
)


# -- the name tiers (src/names.ts) ------------------------------------------


@pytest.mark.parametrize(
    "mention,target,expected",
    [
        ("Maya Rahman", "Maya  rahman!", "exact"),  # punctuation and case fall away
        ("Maya", "Maya", "exact"),
        ("Obermeier Lin", "Obermeir Lin", "typo"),  # one long token, one edit
        ("Maya Rahman", "Maya Raman", "typo"),  # the six-char token exactly
        ("Maya", "Maya Rahman", "weak"),  # leading-name subset
        ("Maya Sam", "Maya Sam Rahman", "weak"),  # prefix, either direction
        ("Maya Rahman Jaeger", "Maya Rahman", "weak"),
        ("Maya Rahman", "Maya Sam Rahman", None),  # not a positional prefix
        ("Maya Li", "Maye Li", None),  # one edit but the longest token is short
        ("Ann Li", "Anne Li", None),
        ("Maya Rahman", "Maya Lee", None),  # two differing tokens
        ("Maya", "Rahman Maya", None),  # no positional lineup
        ("", "Maya", None),
        ("Maya", "  ", None),
        ("Maya", "Maye", None),  # a single-token name is never a typo
    ],
)
def test_match_strength_tiers(mention, target, expected):
    assert match_strength(mention, target) == expected


@pytest.mark.parametrize(
    "left,right,expected",
    [("kitten", "sitting", 3), ("", "abc", 3), ("abc", "", 3), ("abc", "abc", 0),
     ("obermeier", "obermeir", 1)],
)
def test_levenshtein(left, right, expected):
    assert levenshtein(left, right) == expected


def test_display_name_folds_unicode_space_and_collapse():
    assert display_name("  Maya\u00a0 Rahman  ") == "Maya Rahman"


# -- the fake repo -----------------------------------------------------------


class FakeRepo:
    """The seam the store implements: load, save, create, and the
    fact-adjacency read the co-occurrence winner needs."""

    def __init__(self, entities=(), linked=None) -> None:
        self._rows = {
            e.id: [e.canonical_name, list(e.aliases), e.type] for e in entities
        }
        self._next_id = max((e.id for e in entities), default=0) + 1
        self.linked = {k: set(v) for k, v in (linked or {}).items()}

    def load(self) -> list[StoredEntity]:
        return [
            StoredEntity(id=i, canonical_name=row[0], aliases=tuple(row[1]), type=row[2])
            for i, row in sorted(self._rows.items())
        ]

    def save(self, entity_id: int, canonical: str, aliases, entity_type: str) -> None:
        self._rows[entity_id] = [canonical, list(aliases), entity_type]

    def create(self, name: str, entity_type: str) -> int:
        entity_id = self._next_id
        self._next_id += 1
        self._rows[entity_id] = [name, [], entity_type]
        return entity_id

    def linked_fact_ids(self, entity_ids) -> dict[int, set[int]]:
        return {i: set(self.linked.get(i, ())) for i in entity_ids}

    def entity(self, entity_id: int) -> StoredEntity:
        row = self._rows[entity_id]
        return StoredEntity(
            id=entity_id, canonical_name=row[0], aliases=tuple(row[1]), type=row[2]
        )


def _maya(entities=(), linked=None) -> FakeRepo:
    return FakeRepo(
        [StoredEntity(1, "Maya Rahman", (), "person"), *entities], linked
    )


# -- resolution rules ---------------------------------------------------------


def test_an_unmatched_mention_creates_an_entity():
    repo = FakeRepo()
    refs = resolve_mentions(repo, [Mention("Maya Rahman", "person")])
    assert refs == [EntityRef(id=1, name="Maya Rahman", type="person")]
    assert repo.entity(1).canonical_name == "Maya Rahman"


def test_empty_and_blank_mentions_are_dropped():
    repo = FakeRepo()
    refs = resolve_mentions(repo, [Mention("   ", "person"), Mention("", "org")])
    assert refs == []
    assert repo.load() == []


def test_exact_matches_by_canonical_and_by_alias():
    repo = FakeRepo([StoredEntity(1, "Maya Rahman", ("Maya",), "person")])
    assert resolve_mentions(repo, [Mention("maya rahman!", "person")])[0].id == 1
    # The alias line is already there, so nothing accumulates.
    assert repo.entity(1).aliases == ("Maya",)
    assert resolve_mentions(repo, [Mention("Maya", "person")])[0].id == 1
    assert repo.entity(1).aliases == ("Maya",)


def test_a_typo_merges_into_the_canonical_without_touching_names():
    # Two tokens, one differing token, one edit, longest token six or
    # more characters: exactly the donor's typo tier.
    repo = FakeRepo([StoredEntity(1, "Obermeier Lin", (), "person")])
    refs = resolve_mentions(repo, [Mention("Obermeir Lin", "person")])
    assert [r.id for r in refs] == [1]
    # The donor leaves the stored names alone on a typo match.
    assert repo.entity(1).canonical_name == "Obermeier Lin"
    assert repo.entity(1).aliases == ()


def test_a_unique_weak_match_accumulates_an_alias():
    repo = _maya()
    refs = resolve_mentions(repo, [Mention("Maya", "person")])
    assert [r.id for r in refs] == [1]
    assert repo.entity(1).aliases == ("Maya",)


def test_an_ambiguous_weak_match_without_cooccurrence_creates_a_new_entity():
    repo = FakeRepo(
        [
            StoredEntity(1, "Maya Rahman", (), "person"),
            StoredEntity(2, "Maya Chen", (), "person"),
        ]
    )
    refs = resolve_mentions(repo, [Mention("Maya", "person")])
    assert refs == [EntityRef(id=3, name="Maya", type="person")]


def test_the_cooccurrence_winner_decides_an_ambiguous_match():
    # "Chen" matches both Chens exactly through their shared alias;
    # Maya is already bound and shares two distinct facts with Marcus
    # Chen and none with Mei Chen.
    repo = FakeRepo(
        [
            StoredEntity(1, "Maya Rahman", (), "person"),
            StoredEntity(2, "Marcus Chen", ("Chen",), "person"),
            StoredEntity(3, "Mei Chen", ("Chen",), "person"),
        ],
        linked={1: {10, 11}, 2: {10, 11}, 3: {12}},
    )
    refs = resolve_mentions(
        repo,
        [Mention("Maya Rahman", "person"), Mention("Chen", "person")],
    )
    assert [r.id for r in refs] == [1, 2]


def test_a_tied_cooccurrence_creates_instead_of_guessing():
    repo = FakeRepo(
        [
            StoredEntity(1, "Maya Rahman", (), "person"),
            StoredEntity(2, "Marcus Chen", ("Chen",), "person"),
            StoredEntity(3, "Mei Chen", ("Chen",), "person"),
        ],
        linked={1: {10, 11}, 2: {10}, 3: {11}},
    )
    refs = resolve_mentions(
        repo,
        [Mention("Maya Rahman", "person"), Mention("Chen", "person")],
    )
    assert refs[-1] == EntityRef(id=4, name="Chen", type="person")


def test_mentions_are_processed_longest_name_first_in_one_batch():
    # "Maya Rahman" lands first (two tokens), so the bare "Maya" sees it
    # and becomes its alias instead of a second entity.
    repo = FakeRepo()
    refs = resolve_mentions(
        repo, [Mention("Maya", "person"), Mention("Maya Rahman", "person")]
    )
    assert {r.id for r in refs} == {1}
    assert repo.entity(1).canonical_name == "Maya Rahman"
    assert repo.entity(1).aliases == ("Maya",)


def test_the_strong_pass_beats_the_weak_pass():
    # "Maya Rahman" is a typo of "Maya Raman" (strong) and a leading
    # subset of "Maya Rahman Jaeger" (weak); the strong candidate wins
    # and the weak one is never touched.
    repo = FakeRepo(
        [
            StoredEntity(1, "Maya Raman", (), "person"),
            StoredEntity(2, "Maya Rahman Jaeger", (), "person"),
        ]
    )
    refs = resolve_mentions(repo, [Mention("Maya Rahman", "person")])
    assert [r.id for r in refs] == [1]
    assert repo.entity(2).aliases == ()


def test_a_weak_match_with_more_tokens_promotes_the_mention_to_canonical():
    repo = FakeRepo([StoredEntity(1, "Maya", (), "person")])
    refs = resolve_mentions(repo, [Mention("Maya Rahman", "person")])
    assert [r.name for r in refs] == ["Maya Rahman"]
    assert repo.entity(1).canonical_name == "Maya Rahman"
    assert repo.entity(1).aliases == ("Maya",)


def test_type_inference_only_upgrades_from_other():
    repo = FakeRepo([StoredEntity(1, "Initech", (), "other")])
    resolve_mentions(repo, [Mention("Initech", "org")])
    assert repo.entity(1).type == "org"
    # A specific entity never downgrades to other.
    repo = _maya()
    resolve_mentions(repo, [Mention("Maya Rahman", "other")])
    assert repo.entity(1).type == "person"


def test_incompatible_types_never_merge():
    repo = _maya()
    refs = resolve_mentions(repo, [Mention("Maya Rahman", "org")])
    assert refs == [EntityRef(id=2, name="Maya Rahman", type="org")]


def test_resolved_refs_are_deduped_by_id_in_mention_order():
    repo = _maya()
    refs = resolve_mentions(
        repo, [Mention("Maya", "person"), Mention("Maya Rahman", "person")]
    )
    assert [r.id for r in refs] == [1]
    assert refs[0].name == "Maya Rahman"


def test_repeat_weak_mentions_do_not_duplicate_the_alias():
    repo = FakeRepo([StoredEntity(1, "Aria Patel", (), "person")])
    resolve_mentions(repo, [Mention("Aria", "person"), Mention("Aria", "person")])
    assert repo.entity(1).aliases == ("Aria",)

"""Entity resolution: mentions in, canonical entities out.

A verbatim port of the donor's src/resolve.ts and src/names.ts
(ticket #91). The name tiers replicate the donor exactly: exact
(normalized equal), typo (same token count, two or more tokens,
exactly one differing token, edit distance one, longest token at least
six characters) and weak (leading-name subset, every token of the
shorter name matching positionally with strictly fewer tokens). Name
normalization and tokenization are the hybrid ranker's
(memory/hybrid.py), so one normalizer serves recall and resolution.

Resolution order replicates the donor: mentions sorted
longest-name-first; a strong pass (exact, then typo) before a weak
pass; unresolved mentions create entities. When several candidates
match, the co-occurrence winner decides: the candidate sharing the most
distinct facts with already-bound entities, strictly best, positive,
untied; otherwise a new entity is created. Types only upgrade from
"other"; aliases accumulate deduped by normalized form; a weak match
with more tokens than the canonical name promotes the mention to
canonical and demotes the old canonical to an alias.

The module is pure-ish: every function here works on loaded rows and
returns decisions; reads and writes go through the small repo seam
below (the store implements it over its connection; the unit tests
fake it). Names load through the repo, so an encrypted bank resolves
over decrypted rows; the donor's exact-index fast path is ported for
the create-entity guard alone (ticket #94: the sealed store answers
from entity_name_index), while the rest of resolution scans, which is
acceptable at personal-bank scale (spec decision 12).
"""

import unicodedata
from dataclasses import dataclass

from nexuusbot.memory.hybrid import name_parts, normalize_name


@dataclass(frozen=True)
class Mention:
    """One (name, type) pair the extractor named in a fact."""

    name: str
    type: str = "other"


@dataclass(frozen=True)
class StoredEntity:
    """One loaded entity row: the canonical name, its aliases and type."""

    id: int
    canonical_name: str
    aliases: tuple[str, ...] = ()
    type: str = "other"


@dataclass(frozen=True)
class EntityRef:
    """One resolved mention: the entity it binds to, with the entity's
    (possibly just-updated) canonical name and type."""

    id: int
    name: str
    type: str


@dataclass(frozen=True)
class Candidate:
    """One entity that matches a mention, with its best tier."""

    entity: StoredEntity
    strength: str
    matched_canonical: bool


# -- names (src/names.ts) ----------------------------------------------------


def display_name(name: str) -> str:
    """The donor's displayName: unicode-folded, whitespace collapsed and
    trimmed, case and punctuation kept."""
    return " ".join(unicodedata.normalize("NFKC", name).split())


def levenshtein(left: str, right: str) -> int:
    """The donor's edit distance, the classic one-row table."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        previous = i - 1
        row[0] = i
        for j, right_char in enumerate(right, start=1):
            current = row[j]
            cost = 0 if left_char == right_char else 1
            row[j] = min(current + 1, row[j - 1] + 1, previous + cost)
            previous = current
    return row[-1]


def match_strength(mention: str, target: str) -> str | None:
    """exact, typo or weak, or None when the names do not line up.

    exact: same normalized name. typo: one long token differs by a
    single edit; short surnames are not typos. weak: a single given
    name lines up with the start of a longer name, or a longer name
    extends a shorter one. Weak matches need a unique candidate or a
    co-occurrence winner before they merge."""
    left = normalize_name(mention)
    right = normalize_name(target)
    if not left or not right:
        return None
    if left == right:
        return "exact"

    left_tokens = left.split(" ")
    right_tokens = right.split(" ")

    if len(left_tokens) == len(right_tokens) and len(left_tokens) >= 2:
        differences = 0
        distance = 0
        longest = 0
        for left_token, right_token in zip(left_tokens, right_tokens):
            if left_token == right_token:
                continue
            differences += 1
            distance = levenshtein(left_token, right_token)
            longest = max(len(left_token), len(right_token))
            if differences > 1:
                return None
        if differences == 1 and distance == 1 and longest >= 6:
            return "typo"
        return None

    if is_leading_name(left_tokens, right_tokens) or is_leading_name(
        right_tokens, left_tokens
    ):
        return "weak"
    return None


def is_leading_name(shorter: list[str], longer: list[str]) -> bool:
    """True when shorter is a strict token-for-token prefix of longer.

    Both arguments are normalized token lists, so this is positional: "maya"
    leads "maya chen", "chen" does not. Equal lengths are never a leading
    name, which is what keeps a two-token name from matching itself weakly.
    """
    if not shorter or len(shorter) >= len(longer):
        return False
    return all(longer[index] == token for index, token in enumerate(shorter))


def strength_rank(strength: str) -> int:
    """Compare match tiers: exact 3, typo 2, everything else 1.

    A candidate keeps the best tier it reached across its canonical name and
    aliases, so this ordering is what lets an exact alias hit outrank a typo
    on the canonical.
    """
    if strength == "exact":
        return 3
    if strength == "typo":
        return 2
    return 1


def types_compatible(incoming: str, existing: str) -> bool:
    """Whether two entity types may name the same entity.

    "other" matches any type in either direction: it is both the extractor's
    default and its escape hatch for a name it could not classify, so treating
    it as a mismatch would split one entity in two.
    """
    return incoming == existing or incoming == "other" or existing == "other"


def dedupe_aliases(aliases, canonical: str) -> tuple[str, ...]:
    """The donor's dedupeAliases: display-folded, normalized empties
    and the canonical's own normal form dropped, duplicates dropped,
    first-seen order kept."""
    canonical_norm = normalize_name(canonical)
    seen: set[str] = set()
    result: list[str] = []
    for alias in aliases:
        folded = display_name(alias)
        norm = normalize_name(folded)
        if not folded or not norm or norm == canonical_norm or norm in seen:
            continue
        seen.add(norm)
        result.append(folded)
    return tuple(result)


# -- the repo seam ------------------------------------------------------------


class EntityRepo:
    """The seam resolution runs against; the store implements it over
    its connection and the unit tests fake it.

    load(): every entity row, in id order. save(entity_id, canonical,
    aliases, type): overwrite one entity's names and type. create(name,
    type) -> id: insert one entity. linked_fact_ids(ids): a map from
    each id to the set of fact ids that entity is mentioned in, the
    read the co-occurrence winner needs. exact_ids(name): the ids whose
    indexed names equal this one, or None when the repo keeps no index
    (a plaintext bank): None means every entity is a candidate. The
    sealed store answers from entity_name_index (ticket #94); the
    create-entity guard narrows to the indexed ids when one answers.
    """

    def load(self) -> list[StoredEntity]:
        """Every entity row, in id order.

        Resolution scans this list rather than querying per mention, so a plain
        list is the whole cost per pass; id order is what keeps a run
        deterministic when two rows would answer a mention the same way.
        """
        raise NotImplementedError

    def save(self, entity_id: int, canonical: str, aliases, entity_type: str) -> None:
        """Replace one entity's canonical name, aliases and type wholesale.

        The alias set passed in is complete and already deduped against the
        canonical form, so an implementation stores it as given: there is no
        merge with what the row held before.
        """
        raise NotImplementedError

    def create(self, name: str, entity_type: str) -> int:
        """Insert one entity and return the id it was stored under.

        The id is the only handle the caller then has for saves and fact links,
        so an implementation must return the row's real id; the name arrives
        already display-folded and is stored as given.
        """
        raise NotImplementedError

    def linked_fact_ids(self, entity_ids) -> dict[int, set[int]]:
        """The fact ids each of these entities is mentioned in.

        The map may leave out an id with no mentions: the co-occurrence winner
        reads it with an empty-set default, so an implementation need not
        materialize empty sets, and a missing key means "no links", never
        "unknown".
        """
        raise NotImplementedError

    def exact_ids(self, name: str) -> list[int] | None:
        """Ids whose indexed names equal this one, or None when there is no index.

        None is an answer, not a failure: it tells the create-entity guard to
        consider every loaded entity, the only option a plaintext bank has. An
        empty list claims the opposite (that no row matches) and means the
        caller may skip the scan.
        """
        return None


# -- the algorithm (src/resolve.ts) -------------------------------------------


def resolve_mentions(repo: EntityRepo, mentions: list[Mention]) -> list[EntityRef]:
    """Resolve every mention in input order, deduped by entity id.

    Mentions are processed longest-name-first (input order on a tie);
    each gets a strong pass (exact, then typo) and, failing that, a
    weak pass; anything still unresolved creates an entity. Writes land
    through the repo as the donor's do, so later mentions in the same
    batch see earlier ones' creations and alias updates."""
    cleaned = [
        Mention(display_name(mention.name), mention.type)
        for mention in mentions
    ]
    cleaned = [mention for mention in cleaned if mention.name]

    resolved: list[EntityRef | None] = [None] * len(cleaned)
    bound_ids: list[int] = []
    order = sorted(
        range(len(cleaned)),
        key=lambda index: -len(name_parts(cleaned[index].name)),
    )
    deferred: list[int] = []
    for index in order:
        mention = cleaned[index]
        strong = choose(repo, mention, bound_ids, "strong")
        if strong is not None:
            resolved[index] = strong
            bound_ids.append(strong.id)
        else:
            deferred.append(index)

    for index in deferred:
        mention = cleaned[index]
        entity = choose(repo, mention, bound_ids, "any") or create_entity(
            repo, mention
        )
        resolved[index] = entity
        bound_ids.append(entity.id)

    unique: list[EntityRef] = []
    seen: set[int] = set()
    for entity in resolved:
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        unique.append(entity)
    return unique


def choose(
    repo: EntityRepo, mention: Mention, bound_ids: list[int], mode: str
) -> EntityRef | None:
    """The donor's choose: exact candidates first (one applies, several
    need a co-occurrence winner or a single canonical hit), then typo
    candidates, then weak ones, and weak ones only on the second pass."""
    pool = candidates_for(mention, repo.load())
    exact = [c for c in pool if c.strength == "exact"]
    typos = [c for c in pool if c.strength == "typo"]
    weak = [c for c in pool if c.strength == "weak"]

    if len(exact) == 1:
        return apply_match(repo, exact[0], mention)
    if len(exact) > 1:
        winner = cooccurrence_winner(exact, bound_ids, repo)
        if winner is not None:
            return apply_match(repo, winner, mention)
        canonicals = [c for c in exact if c.matched_canonical]
        if len(canonicals) == 1:
            return apply_match(repo, canonicals[0], mention)
        return None

    if len(typos) == 1:
        return apply_match(repo, typos[0], mention)
    if len(typos) > 1:
        winner = cooccurrence_winner(typos, bound_ids, repo)
        return None if winner is None else apply_match(repo, winner, mention)

    if mode == "strong":
        return None
    if len(weak) == 1:
        return apply_match(repo, weak[0], mention)
    if len(weak) > 1:
        winner = cooccurrence_winner(weak, bound_ids, repo)
        return None if winner is None else apply_match(repo, winner, mention)
    return None


def candidates_for(mention: Mention, entities: list[StoredEntity]) -> list[Candidate]:
    """Every entity the mention matches, at its best tier, canonical
    matches preferred over alias matches on a tie."""
    found: list[Candidate] = []
    for entity in entities:
        if not types_compatible(mention.type, entity.type):
            continue
        best: Candidate | None = None
        names = [(entity.canonical_name, True)] + [
            (alias, False) for alias in entity.aliases
        ]
        for value, canonical in names:
            strength = match_strength(mention.name, value)
            if not strength:
                continue
            matched_canonical = (
                canonical and normalize_name(value) == normalize_name(mention.name)
            )
            if best is None or strength_rank(strength) > strength_rank(best.strength):
                best = Candidate(entity, strength, matched_canonical)
            elif strength == best.strength and matched_canonical:
                best = Candidate(entity, strength, True)
        if best is not None:
            found.append(best)
    return found


def cooccurrence_winner(
    pool: list[Candidate], bound_ids: list[int], repo: EntityRepo
) -> Candidate | None:
    """The candidate sharing the most distinct facts with the
    already-bound entities, strictly best, positive, untied. No bound
    entity to lean on, or a tie, or all-zero: no winner."""
    candidate_ids = [candidate.entity.id for candidate in pool]
    others = [entity_id for entity_id in bound_ids if entity_id not in candidate_ids]
    if not candidate_ids or not others:
        return None
    linked = repo.linked_fact_ids(set(candidate_ids) | set(others))
    other_facts: set[int] = set()
    for entity_id in others:
        other_facts |= linked.get(entity_id, set())

    best: Candidate | None = None
    best_score = 0
    tied = False
    for candidate in pool:
        score = len(linked.get(candidate.entity.id, set()) & other_facts)
        if score > best_score:
            best = candidate
            best_score = score
            tied = False
        elif score == best_score and score > 0:
            tied = True
    if best is None or tied or best_score <= 0:
        return None
    return best


def apply_match(
    repo: EntityRepo, candidate: Candidate, mention: Mention
) -> EntityRef:
    """Bind the mention to the candidate's entity: type upgrades only
    from other; on a weak match the longer name wins the canonical slot
    and the shorter one becomes an alias; aliases dedupe by normalized
    form."""
    canonical = candidate.entity.canonical_name
    aliases = list(candidate.entity.aliases)
    entity_type = candidate.entity.type
    if entity_type == "other" and mention.type != "other":
        entity_type = mention.type

    if candidate.strength == "weak":
        mention_tokens = name_parts(mention.name)
        canonical_tokens = name_parts(canonical)
        if len(mention_tokens) > len(canonical_tokens):
            if normalize_name(canonical) != normalize_name(mention.name):
                aliases.append(canonical)
            canonical = mention.name
        elif normalize_name(mention.name) != normalize_name(canonical):
            aliases.append(mention.name)

    aliases = dedupe_aliases(aliases, canonical)
    repo.save(candidate.entity.id, canonical, aliases, entity_type)
    return EntityRef(id=candidate.entity.id, name=canonical, type=entity_type)


def create_entity(repo: EntityRepo, mention: Mention) -> EntityRef:
    """Create the mention's entity, unless an entity already carries
    this exact canonical name (compatible type): the donor's guard that
    keeps cancelled-out exact pools from minting duplicates. When the
    repo answers with an exact index (the sealed bank's blind indexes,
    ticket #94), only the indexed entities are candidates; without one,
    every loaded entity is."""
    indexed = repo.exact_ids(mention.name)
    ids = None if indexed is None else {int(entity_id) for entity_id in indexed}
    for entity in repo.load():
        if ids is not None and entity.id not in ids:
            continue
        if types_compatible(mention.type, entity.type) and normalize_name(
            entity.canonical_name
        ) == normalize_name(mention.name):
            return apply_match(repo, Candidate(entity, "exact", True), mention)
    new_id = repo.create(mention.name, mention.type)
    return EntityRef(id=new_id, name=mention.name, type=mention.type)

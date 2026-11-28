"""Legacy endpoint migration (spec 018 #234): the upgrade step, one boot.

A desk upgraded from the single-endpoint configuration carries five
settings rows: llm_base, llm_key, llm_model and research_provider_url,
research_provider_key. On the first boot after the upgrade they become
two named connections ("Migrated endpoint", "Migrated research
provider"), the keys move into the keychain, and the default and
research-web jobs bind to them. The base, model and research URL rows
stay in the settings database as the read-only fallback the resolution
hub's environment leg still reads; the SECRET columns (llm_key,
research_provider_key) are cleared once the key has landed in the
keychain, so the settings file never carries a secret again.

The step runs on every boot and is idempotent: a live connection with a
migrated label means there is nothing to do. It is also the recovery
path: deleting a migrated connection keeps its keychain entry (the
delete route treats the two migrated ids specially) and leaves the
legacy rows in place, so the next boot re-creates the connection under
the same stable id, which re-links the surviving keychain entry, and
restores the binding and the default star for any hole the delete left.
A binding or star the user made in between is never stolen: the
recovery only fills what is missing.

A machine with no usable keychain migrates too, with the key simply
absent from the connection: the row is created disabled and unbound,
carrying only the masked hint, and the settings secret stays where it
is (it never landed in the keychain, so it is not deleted), which keeps
the environment leg serving exactly as before the upgrade. The Settings
page's no-keychain notice names the state.
"""

import logging
from collections.abc import Callable

from nexuusbot.keys.secrets import KeychainSecrets
from nexuusbot.keys.store import KeysStore, mask_key

LOG = logging.getLogger(__name__)

# The stable ids: the keychain username is key/<id>, so a re-created
# connection under the same id re-links the entry its earlier self
# stored, which is what makes delete-then-restart a recovery instead of
# a retype. Real ids are uuid hex, so nothing a user saves can collide.
MIGRATED_ENDPOINT_ID = "migrated-endpoint"
MIGRATED_ENDPOINT_LABEL = "Migrated endpoint"
MIGRATED_RESEARCH_ID = "migrated-research"
MIGRATED_RESEARCH_LABEL = "Migrated research provider"

MIGRATED_CONNECTION_IDS = (MIGRATED_ENDPOINT_ID, MIGRATED_RESEARCH_ID)

# Both legacy rows are hand-typed base URLs, so both connections carry
# the custom preset.
_MIGRATED_PROVIDER = "custom"


def migrate_legacy_settings(
    settings,
    keys: KeysStore | None,
    keychain: KeychainSecrets | None,
    record: Callable[[str, str, str], None] | None = None,
) -> list[str]:
    """Bring the legacy endpoint rows over as connections; return the
    labels created (empty when there was nothing to do).

    settings is the settings store, keys the connections store (None
    means the surface is unavailable and nothing can be written),
    keychain the secrets wrapper, and record the audit callback that
    receives (action, target, detail) for every connection created.
    Never raises to the caller's face: each pair is migrated inside its
    own guard, so one refused write cannot keep the other from landing.
    """
    created: list[str] = []
    if settings is None or keys is None:
        return created
    for pair in (
        (MIGRATED_ENDPOINT_ID, MIGRATED_ENDPOINT_LABEL, "default",
         "llm_base", "llm_key", "llm_model"),
        (MIGRATED_RESEARCH_ID, MIGRATED_RESEARCH_LABEL, "research-web",
         "research_provider_url", "research_provider_key", None),
    ):
        try:
            created.extend(_migrate_pair(*pair, settings=settings,
                                         keys=keys, keychain=keychain,
                                         record=record))
        except Exception:  # noqa: BLE001 - the upgrade must never fail the boot
            # The swallow stays (a boot never fails here), but the failure
            # is logged with the pair named: the boot wrapper's "any
            # failure is logged and left behind" promise reaches this deep
            # only through this record.
            LOG.exception("the migration of the %s connection did not"
                          " complete; it is left for the next boot",
                          pair[1])
    return created


def _migrate_pair(
    connection_id: str,
    label: str,
    job: str,
    base_row: str,
    key_row: str,
    model_row: str | None,
    *,
    settings,
    keys: KeysStore,
    keychain: KeychainSecrets | None,
    record,
) -> list[str]:
    """Migrate one legacy pair, or leave it alone.

    A live connection with the pair's label is the idempotence exit: the
    step already ran, this boot changes nothing. An empty base row means
    there is no legacy configuration behind the pair.
    """
    if any(connection.label == label for connection in keys.all()):
        return []
    base = str(settings.get(base_row) or "").strip()
    if not base:
        return []
    legacy_secret = str(settings.get(key_row) or "").strip()
    stored = keychain.fetch(connection_id) if keychain is not None else None
    if stored is None and legacy_secret and keychain is not None \
            and keychain.available() and keychain.store(connection_id, legacy_secret):
        # The key landed in the keychain: the settings database is
        # secret-free from here on (the acceptance criterion's raw SQL).
        settings.set(key_row, "")
        stored = legacy_secret
    elif stored is not None and legacy_secret:
        # The key was already in the keychain (the recovery path); the
        # settings column should not have kept a copy.
        settings.set(key_row, "")
    masked = mask_key(stored or legacy_secret)
    # A key that lives nowhere in the new world keeps serving from the
    # settings row, so the migrated connection steps aside (disabled,
    # unbound) and the environment leg answers exactly as before.
    enabled = stored is not None or not legacy_secret
    connection = keys.add(
        label=label, provider=_MIGRATED_PROVIDER, base_url=base,
        masked_key=masked, is_default=_should_star(keys, enabled),
        connection_id=connection_id, enabled=enabled)
    if enabled and keys.binding(job) is None:
        model = str(settings.get(model_row) or "").strip() if model_row else ""
        keys.bind(job, connection.id, model)
    if record is not None:
        record("keys.create", connection.id,
               f"{label} (migrated from the legacy settings rows)")
    return [label]


def _should_star(keys: KeysStore, enabled: bool) -> bool:
    """Star the migrated endpoint only when enabled and no connection
    holds the default star yet, so a recovery never takes it from a
    connection the user chose."""
    if not enabled:
        return False
    return not any(connection.is_default for connection in keys.all())

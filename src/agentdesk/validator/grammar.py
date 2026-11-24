"""The safety grammar's one owner.

validator/lint.py, plugins/runtime.py and plugins/sources.py used to
carry byte-identical copies of these fragments; a copy that drifts is a
hole in one reader's containment, so the patterns live here and the
readers import them. wizard/core.py's safe_slug and runtime's _alias_id
deliberately stay out: they serve different alphabets (display slugs,
derived instance ids), not this containment grammar.
"""
import re

# Plugin ids, versions and instance ids become filesystem fragments
# (install dirs, data dirs, rmtree targets), so they are names, not
# free text: one leading alphanumeric, then alphanumerics, dots,
# underscores and dashes.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# json-watch's deliberately tiny selector grammar: an object path
# ($.a.b) or a list field ($.a[*].n). Nothing else is executable.
JSON_OBJECT = re.compile(r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
JSON_LIST = re.compile(
    r"^\$(?:\.[A-Za-z_][A-Za-z0-9_]*)+\[\*\]\.[A-Za-z_][A-Za-z0-9_]*$")
JSON_PATH_PART = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")

# The path variables a manifest may name a host root by. _expand
# substitutes them literally; the lint checks declared globs against
# the same two roots, so a rename has to happen in both places at once.
WORKSPACE_VAR = "${workspace}"
PLUGIN_DATA_VAR = "${pluginData}"
WORKSPACE_ROOT = WORKSPACE_VAR + "/"
PLUGIN_DATA_ROOT = PLUGIN_DATA_VAR

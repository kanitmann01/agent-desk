# Docstrings

Every function and method in first-party source carries a docstring. `tools/docstring_gate.py`
enforces it, and this page is the standard it enforces.

## Shape

1. **Summary line.** Imperative, ends with a period, one line. Say what the
   function does, not what it is: `"""Return the rows added since the last
   snapshot."""`, never `"""This function returns..."""`.
2. **Contract paragraph** (optional). One short paragraph after a blank line,
   for whatever the signature cannot show: units, ranges, ordering,
   transaction boundaries, side effects (files, network, rows), what `None`
   means, and the trade-off a reader would otherwise have to infer.
3. **Sections** (`Args:`, `Returns:`, `Raises:`) only when a parameter's
   meaning, a return shape or a raised exception is not obvious from the
   signature. A function returning dicts with a fixed shape needs a
   `Returns:`; one returning a bool does not.

## Do not

- Restate the signature or repeat types the annotations already carry.
- Narrate the body ("first we open the file, then we parse it"). Explain the
  contract; the code explains the steps.
- Name the callers ("used by the settings page"). A docstring describes the
  function, not its neighbourhood.
- Pad a trivial accessor with a restatement — `"""Get the store."""` is worse
  than nothing. Say what the store is for or what the call costs.

## Example

Good: states the contract and the reason for the invariant.

```python
def row_hash(row: list) -> str:
    """Stable hash of one row's values.

    Values are the parsed cell values (float for numbers, str for text).
    json.dumps gives a canonical serialization for both; sha256 keeps the
    hash stable across runs and machines.
    """
```

Weak: repeats the signature and says nothing.

```python
def row_hash(row: list) -> str:
    """Hash a row."""
```

## TypeScript

The same shape in JSDoc: a `/** ... */` block with a one-line summary, a
contract paragraph where it earns its place, and `@param` / `@returns` /
`@throws` only when the types do not already say it. Generated files
(`routeTree.gen.ts`) and vendored code are exempt; tests are exempt unless a
helper is itself reused.

## Enforcement

`tools/docstring_gate.py` lists every function without a docstring as
`path:name`, and `docs/docstring-baseline.txt` records the current gap. The
gate fails when a new gap appears **and** when a baseline line becomes stale,
so documenting a function means deleting its line. When the baseline is empty
it is deleted and the gate becomes a plain check.

`tests/test_docstring_gate.py` runs it, so the convention fails in CI the way
any other regression does.

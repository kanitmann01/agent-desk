# Reconciliation Watch

Answers: what is in the ledger but not the bank, and vice versa?

- Source: compare of two excel-watch sides, the ledger
  (${workspace}/finance/ledger*.xlsx) and the bank
  (${workspace}/finance/bank*.xlsx), keyed on Reference with Amount.
- Elements: the compare metric, the differences list (left only, right
  only, both), and the net delta with direction.
- Blank state: if either side is missing the whole card is blank and
  names the side that could not be read.

The sample lists five of the differences and a net delta of two rows in
the ledger's favour. The metric shows the compare source's value, which
the host currently computes as the number of keys present on both sides.

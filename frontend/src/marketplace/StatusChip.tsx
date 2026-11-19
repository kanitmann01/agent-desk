// Status without colour as the only signal: the label always says it.
/**
 * Render a plugin status as a coloured dot plus its word, so colour is never
 * the only signal.
 *
 * An empty status reads as `unknown`, and `stale` is spelled out as
 * "Needs re-test" rather than capitalised as-is.
 */
export function StatusChip({ status }: { status: string }) {
  const normalized = status || 'unknown';
  const tone = normalized === 'enabled' ? 'good'
    : normalized === 'blocked' || normalized === 'failed' ? 'bad'
      : normalized === 'stale' || normalized === 'attention' ? 'warn'
        : 'neutral';
  const label = normalized === 'stale' ? 'Needs re-test'
    : normalized.charAt(0).toUpperCase() + normalized.slice(1);
  return <span className={`mkt-status mkt-tone-${tone}`}><span className="mkt-dot" aria-hidden="true" />{label}</span>;
}

/**
 * Render the signature state as a chip, keeping bundled-but-unsigned distinct
 * from a signature that was never checked.
 */
export function SignatureChip({ status }: { status: string }) {
  const signed = status === 'signed' || status === 'verified';
  return (
    <span className={`mkt-status mkt-tone-${signed ? 'good' : 'warn'}`}>
      <span className="mkt-dot" aria-hidden="true" />
      {signed ? 'Signature verified' : status === 'bundled' ? 'Bundled, unsigned' : 'Unsigned'}
    </span>
  );
}

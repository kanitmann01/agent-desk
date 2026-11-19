// The freshness stamp: the same header contract every card carries on
// the server-rendered dashboard, a 7px status dot plus the stamp text.
// Fresh sources get the green dot; anything stale, blocked, paused or
// not connected gets the amber dot inside the Manila pair pill. The dot
// is decoration: the stamp text beside it is the whole message, so
// assistive tech reads the text alone.
export interface StampProps {
  fresh: boolean;
  text: string;
}

/**
 * Status dot with its stamp text: green when fresh, amber when not.
 *
 * The dot is decoration only, so the text alone carries the message.
 */
export default function Stamp({ fresh, text }: StampProps) {
  return (
    <span className={fresh ? 'stamp' : 'stamp amber'}>
      <span className={fresh ? 'dot' : 'dot amber'} aria-hidden="true" />
      {text}
    </span>
  );
}

// The freshness stamp: the same header contract every card carries on
// the server-rendered dashboard (a mark plus the stamp text), with the
// mark drawn by the vendored StatusMark. Fresh sources get the green
// check; anything stale, blocked, paused or not connected gets the
// amber waiting ring. The mark is decoration: the stamp text beside it
// is the whole message, so assistive tech reads the text alone.
import StatusMark from '../vendor/reactbits/StatusMark';

export interface StampProps {
  fresh: boolean;
  text: string;
}

export default function Stamp({ fresh, text }: StampProps) {
  return (
    <span className={fresh ? 'stamp' : 'stamp amber'}>
      <span className="stamp-mark" aria-hidden="true">
        <StatusMark
          status={fresh ? 'done' : 'pending'}
          color="#8A5A14"
          doneColor="#14594E"
          size={15}
          strokeWidth={2}
          dashes={6}
        />
      </span>
      {text}
    </span>
  );
}

// The freshness stamp: the same three-part header contract every card
// carries on the server-rendered dashboard, as a component.

export interface StampProps {
  fresh: boolean;
  text: string;
}

export default function Stamp({ fresh, text }: StampProps) {
  return (
    <span className="stamp">
      <span className={fresh ? 'dot' : 'dot amber'} aria-hidden="true" />
      {text}
    </span>
  );
}

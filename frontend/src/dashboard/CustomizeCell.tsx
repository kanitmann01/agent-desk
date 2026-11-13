// One card's customize chrome (issue #66): while the dashboard is being
// customized, every visible card is wrapped in this slim toolbar row plus
// the card itself. The controls are deliberately flat and always visible
// (no nested overflow menu to open): a labelled grab handle for HTML5
// drag-and-drop, Move up/Move down for the keyboard path, Rename, and
// Hide. Reordering is instant; the wrapper adds no motion of its own.
import { useRef, type DragEvent, type KeyboardEvent, type ReactNode } from 'react';

const ICON_GRIP = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <circle cx="9" cy="5" r="1.7" />
    <circle cx="15" cy="5" r="1.7" />
    <circle cx="9" cy="12" r="1.7" />
    <circle cx="15" cy="12" r="1.7" />
    <circle cx="9" cy="19" r="1.7" />
    <circle cx="15" cy="19" r="1.7" />
  </svg>
);

export interface CustomizeCellProps {
  cardKey: string;
  // The card's effective display name (custom title or default), which
  // labels every control so screen readers always know which card.
  name: string;
  first: boolean;
  last: boolean;
  // This card is the one being renamed right now (the input replaces
  // the Move/Rename buttons in the bar).
  renaming: boolean;
  dragging: boolean;
  dragOver: boolean;
  onRenaming: (key: string | null) => void;
  onMove: (key: string, direction: -1 | 1) => void;
  onRename: (key: string, title: string) => void;
  onHide: (key: string) => void;
  onDragCard: (key: string) => void;
  onDragOverCard: (key: string) => void;
  onDropCard: (targetKey: string) => void;
  onDragEnd: () => void;
  children: ReactNode;
}

export default function CustomizeCell({
  cardKey, name, first, last, renaming, dragging, dragOver,
  onRenaming, onMove, onRename, onHide, onDragCard, onDragOverCard, onDropCard, onDragEnd,
  children,
}: CustomizeCellProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  function submitRename() {
    onRename(cardKey, (inputRef.current?.value ?? '').trim());
  }

  function onRenameKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      submitRename();
    } else if (event.key === 'Escape') {
      onRenaming(null);
    }
  }

  function guardDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    onDropCard(cardKey);
  }

  const cls = `cust-cell${dragging ? ' drag-src' : ''}${dragOver ? ' drag-over' : ''}`;
  return (
    <div
      className={cls}
      onDragOver={(event) => {
        event.preventDefault();
        onDragOverCard(cardKey);
      }}
      onDrop={guardDrop}
    >
      <div className="cust-bar">
        {/* The grab handle is the drag source. Its label names the job;
            the Move buttons beside it are the keyboard path, so the
            control never pretends to be focusable-and-dead: a pure click
            (press without a drag) is a no-op, exactly like a real grab
            that never moves. */}
        <button
          type="button"
          className="cust-grip"
          draggable
          data-grip-key={cardKey}
          aria-label={`Drag to reorder ${name}`}
          onDragStart={(event) => {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', cardKey);
            onDragCard(cardKey);
          }}
          onDragEnd={onDragEnd}
        >
          {ICON_GRIP}
        </button>
        {renaming ? (
          <>
            <input
              ref={inputRef}
              className="cust-rename"
              type="text"
              aria-label={`Title for ${name}`}
              defaultValue={name}
              onKeyDown={onRenameKey}
            />
            <button type="button" className="cust-btn" onClick={submitRename}>
              Save title
            </button>
            <button type="button" className="cust-btn" onClick={() => onRenaming(null)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="cust-btn"
              aria-label={`Move ${name} up`}
              disabled={first}
              onClick={() => onMove(cardKey, -1)}
            >
              Move up
            </button>
            <button
              type="button"
              className="cust-btn"
              aria-label={`Move ${name} down`}
              disabled={last}
              onClick={() => onMove(cardKey, 1)}
            >
              Move down
            </button>
            <button
              type="button"
              className="cust-btn"
              aria-label={`Rename ${name}`}
              onClick={() => onRenaming(cardKey)}
            >
              Rename
            </button>
          </>
        )}
        <button
          type="button"
          className="cust-btn"
          aria-label={`Hide ${name}`}
          onClick={() => onHide(cardKey)}
        >
          Hide
        </button>
      </div>
      {children}
    </div>
  );
}

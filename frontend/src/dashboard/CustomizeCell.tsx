// One card's customize chrome (issue #66): while the dashboard is being
// customized, every visible card is wrapped in this slim toolbar row plus
// the card itself. The controls are deliberately flat and always visible
// (no nested overflow menu to open): a labelled grab handle for HTML5
// drag-and-drop, Move up/Move down for the keyboard path, Rename, and
// Hide. Reordering is instant; the wrapper adds no motion of its own.
// Every control that saves the layout shows its wait on itself (spec
// 027): disabled from the first millisecond, aria-busy and the
// continuous verb once the save has lasted 100 ms.
import { useRef, type DragEvent, type KeyboardEvent, type ReactNode } from 'react';

export type CustomizePending = 'move-up' | 'move-down' | 'move' | 'hide' | 'restore' | 'rename' | null;

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

interface ControlProps {
  idle: string;
  pendingLabel: string;
  pending: boolean;
  // True once the save has lasted 100 ms: only then does the control show
  // its busy dot, aria-busy and continuous verb. While pending it is
  // already inert, so a fast save never flashes.
  pendingShown: boolean;
  disabled?: boolean;
  // The card name behind a bare verb; omitted when the visible label is
  // already the whole name.
  ariaLabel?: string;
  pendingAriaLabel?: string;
  onActivate?: () => void;
}

/** One customize control: the shared pending contract on the flat chip. */
function Control({
  idle, pendingLabel, pending, pendingShown, disabled = false, ariaLabel, pendingAriaLabel, onActivate,
}: ControlProps) {
  if (pending) {
    return (
      <button
        type="button"
        className="cust-btn"
        disabled
        aria-busy={pendingShown ? 'true' : undefined}
        aria-label={pendingShown ? pendingAriaLabel : ariaLabel}
      >
        <span
          className={pendingShown ? 'btn-busy-dot' : 'btn-busy-dot busy-hidden'}
          aria-hidden="true"
        />
        <span className="btn-labels">
          <span
            className={pendingShown ? 'btn-label btn-label-hidden' : 'btn-label'}
            aria-hidden={pendingShown ? 'true' : undefined}
          >
            {idle}
          </span>
          <span
            className={pendingShown ? 'btn-label' : 'btn-label btn-label-hidden'}
            aria-hidden={pendingShown ? undefined : 'true'}
          >
            {pendingLabel}
          </span>
        </span>
      </button>
    );
  }
  return (
    <button
      type="button"
      className="cust-btn"
      disabled={disabled}
      aria-label={ariaLabel}
      onClick={onActivate}
    >
      {idle}
    </button>
  );
}

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
  // A layout save is in flight somewhere in the panel.
  busy?: boolean;
  // This card's control that started the save, if any.
  pending?: CustomizePending;
  // True once that save has lasted 100 ms, so the pending verb shows.
  pendingShown?: boolean;
  // The typed title to restore when a rename save failed.
  renameValue?: string | null;
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

/**
  * One card's customize bar, a drag handle, Move up and down, Rename and Hide, around
  * the card itself.
  *
  * Renaming swaps the buttons for a title editor; the drag handlers only report keys,
  * so the order lives in the dashboard.
 */
export default function CustomizeCell({
  cardKey, name, first, last, renaming, dragging, dragOver,
  busy = false, pending = null, pendingShown = false, renameValue = null,
  onRenaming, onMove, onRename, onHide, onDragCard, onDragOverCard, onDropCard, onDragEnd,
  children,
}: CustomizeCellProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  /** Rename the card to the trimmed value of the editor. */
  function submitRename() {
    onRename(cardKey, (inputRef.current?.value ?? '').trim());
  }

  // Leaving the rename editor hands focus back to the card's grip: the
  // editor's own controls are about to unmount, and focus must not fall
  // to the body on the way out.
  /** Leave the rename editor and hand focus back to the card's grip. */
  function closeRename() {
    const grip = document.querySelector<HTMLElement>(`[data-grip-key="${cardKey}"]`);
    onRenaming(null);
    grip?.focus();
  }

  /** Commit the rename on Enter, cancel it on Escape. */
  function onRenameKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      submitRename();
    } else if (event.key === 'Escape') {
      closeRename();
    }
  }

  /** Take a drop on this card, which moves the dragged card here. */
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
          draggable={!busy}
          data-grip-key={cardKey}
          aria-label={`Drag to reorder ${name}`}
          aria-disabled={busy ? 'true' : undefined}
          onDragStart={(event) => {
            if (busy) return;
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
              // The editor takes focus when it mounts: activating Rename
              // replaces the focused button, so without this the input
              // arrives unfocused and keyboard users tab blind.
              autoFocus
              aria-label={`Title for ${name}`}
              defaultValue={renameValue ?? name}
              disabled={busy}
              onKeyDown={onRenameKey}
            />
            <Control
              idle="Save title"
              pendingLabel="Saving..."
              pending={pending === 'rename'}
              pendingShown={pendingShown}
              disabled={busy}
              onActivate={submitRename}
            />
            <button type="button" className="cust-btn" onClick={closeRename} disabled={busy}>
              Cancel
            </button>
          </>
        ) : (
          <>
            <Control
              idle="Move up"
              pendingLabel="Moving up..."
              pending={pending === 'move-up' || pending === 'move'}
              pendingShown={pendingShown}
              disabled={busy || first}
              ariaLabel={`Move ${name} up`}
              pendingAriaLabel={`Moving ${name} up...`}
              onActivate={() => onMove(cardKey, -1)}
            />
            <Control
              idle="Move down"
              pendingLabel="Moving down..."
              pending={pending === 'move-down'}
              pendingShown={pendingShown}
              disabled={busy || last}
              ariaLabel={`Move ${name} down`}
              pendingAriaLabel={`Moving ${name} down...`}
              onActivate={() => onMove(cardKey, 1)}
            />
            <button
              type="button"
              className="cust-btn"
              aria-label={`Rename ${name}`}
              onClick={() => onRenaming(cardKey)}
              disabled={busy}
            >
              Rename
            </button>
          </>
        )}
        <Control
          idle="Hide"
          pendingLabel="Hiding..."
          pending={pending === 'hide'}
          pendingShown={pendingShown}
          disabled={busy}
          ariaLabel={`Hide ${name}`}
          pendingAriaLabel={`Hiding ${name}...`}
          onActivate={() => onHide(cardKey)}
        />
      </div>
      {children}
    </div>
  );
}

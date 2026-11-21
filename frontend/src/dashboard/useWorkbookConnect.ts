// The workbook connect walk, written once: the brief's decisions cell
// and the unconfigured sales card both connect through the server's
// picker, fall back to the typed path when the dialog does not open, and
// say why nothing changed. A copy fix or a new error code lands here for
// both callers.
import { useState, type KeyboardEvent } from 'react';
import { postJson } from '../api';

export interface WorkbookConnect {
  note: string;
  setNote: (text: string) => void;
  busy: boolean;
  manualOpen: boolean;
  pathInput: string;
  setPathInput: (value: string) => void;
  pick: () => Promise<void>;
  connect: (path: string) => Promise<void>;
  /** Connect the typed workbook path when Enter is pressed. */
  onPathKey: (event: KeyboardEvent<HTMLInputElement>) => void;
}

/**
 * The connect/pick/manual walk against /sources/excel-watch.
 *
 * onExpired hands a 401 back to the caller; onConnected reloads the
 * dashboard once a workbook is connected.
 */
export function useWorkbookConnect(
  onExpired: () => void,
  onConnected: () => Promise<void>,
): WorkbookConnect {
  const [note, setNote] = useState('');
  const [manualOpen, setManualOpen] = useState(false);
  const [pathInput, setPathInput] = useState('');
  const [busy, setBusy] = useState(false);

  /**
   * Connect a workbook by path and reload the dashboard; a note says why
   * nothing changed.
   */
  async function connect(path: string) {
    setBusy(true);
    try {
      const res = await postJson('/sources/excel-watch', { path });
      if (res.status === 401) { onExpired(); return; }
      const body = res.data as { error?: string };
      if (!res.ok || body.error) {
        setNote(body.error || 'The workbook was not connected; nothing changed.');
        return;
      }
      setNote('');
      setManualOpen(false);
      setPathInput('');
      await onConnected();
    } catch {
      setNote('The dashboard could not reach its own server; nothing was connected.');
    } finally {
      setBusy(false);
    }
  }

  /**
   * Open the file dialog and connect the chosen workbook; a dialog that never
   * opened falls back to the manual path input.
   */
  async function pick() {
    setBusy(true);
    try {
      const res = await postJson('/sources/excel-watch/pick');
      if (res.status === 401) { onExpired(); return; }
      const body = res.data as { path?: string | null };
      if (!body.path) {
        setManualOpen(true);
        setNote('The file dialog did not open. Type the workbook path below and press Connect.');
        return;
      }
      await connect(body.path);
    } catch {
      setNote('The dashboard could not reach its own server; the file dialog was not opened.');
    } finally {
      setBusy(false);
    }
  }

  /** Connect the typed workbook path when Enter is pressed. */
  function onPathKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter') {
      event.preventDefault();
      const path = pathInput.trim();
      if (path) void connect(path);
    }
  }

  return { note, setNote, busy, manualOpen, pathInput, setPathInput, pick, connect, onPathKey };
}

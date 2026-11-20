// Plugin Studio: a small honest form, a live manifest, the real validator,
// and a publish that ends in "pending review" rather than a fake install.
import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import Button from '../components/Button';
import { getMarket, marketErrorText, postMarket } from './client';
import { CATEGORIES, categoryLabel } from './MarketGrid';
import { SamplePreview } from './Sample';
import type { InstalledResponse, MarketElement, MarketSample } from './types';

const ICONS = ['calendar', 'chart', 'mail', 'book', 'checklist', 'clock', 'alert', 'folder', 'plugin', 'generic'];

interface Draft {
  id: string;
  name: string;
  summary: string;
  category: string;
  tags: string;
  icon: string;
  license: string;
  version: string;
}

const BLANK: Draft = {
  id: '', name: '', summary: '', category: 'reference', tags: '',
  icon: 'generic', license: 'MIT', version: '0.1.0',
};

interface Verdict {
  ok: boolean;
  failures: { code: string; message: string }[];
}

/**
 * Build the manifest the validator and the runtime see from the draft form.
 *
 * Blank id, name and version fall back to defaults and tags are trimmed,
 * lowercased and capped at eight, so an untouched form still yields a
 * complete manifest for the live preview.
 */
function buildManifest(draft: Draft) {
  const id = draft.id.trim() || 'untitled-plugin';
  const name = draft.name.trim() || 'Untitled plugin';
  const summary = draft.summary.trim();
  const tags = draft.tags.split(',').map((tag) => tag.trim().toLowerCase()).filter(Boolean).slice(0, 8);
  const description = summary || `${name} is a local, declarative plugin.`;
  const highlights = [
    summary || `${name} runs on this desk.`,
    'It reads only the scopes you approve.',
    'It runs only while Nexuus Bot is open.',
  ].map((line) => line.slice(0, 120));
  return {
    schemaVersion: 2,
    id,
    name,
    version: draft.version.trim() || '0.1.0',
    publisher: 'local',
    class: 'declarative',
    engines: { dashboardHost: '>=0.1.0' },
    license: draft.license.trim(),
    category: draft.category,
    tags,
    icon: draft.icon,
    summary: description.slice(0, 120),
    description,
    highlights,
    permissions: {
      filesystem: { read: [], write: [] },
      network: { allow: [] },
      llm: { allow: false },
      shell: 'none',
    },
    activationEvents: [`onWidget:${id}`],
    contributes: {
      widgets: [{
        id,
        size: '2x1',
        dataSource: { type: 'manual-metric' },
        render: { type: 'ui-schema', file: 'widget.ui.json' },
      }],
    },
    sample: 'sample.json',
    minHost: '>=0.1.0',
  };
}

// The widget.ui.json the validator and the runtime read: every element
// names its kind in `type` (lint.py and plugins/render.py), never in
// `kind`, which is only the preview's rendered shape.
/**
 * Build the widget.ui.json the validator and the runtime read.
 *
 * Elements name their kind in `type`, which is what the validator reads;
 * `kind` is only the preview's rendered shape.
 */
function buildWidgetUi(manifest: ReturnType<typeof buildManifest>) {
  return {
    type: 'card',
    title: manifest.name,
    elements: [
      { type: 'metric', label: 'Value', binding: 'value' },
      { type: 'text', label: 'Last updated', binding: 'lastUpdated' },
    ],
  };
}

// The live preview: the same two elements in the rendered shape the
// sample renderer takes.
/** Build the live preview's elements in the rendered shape the sample renderer takes. */
function previewElements(draft: Draft): MarketElement[] {
  return [
    { kind: 'metric', label: 'Value', value: '0' },
    { kind: 'text', text: draft.summary.trim() || 'A small local plugin.' },
  ];
}

/** Build the sample bindings the declared widget reads, stamped with the current time. */
function buildSample(): { bindings: Record<string, unknown>; state: string; checkedAt: string } {
  return {
    bindings: { value: 0, lastUpdated: 'Never' },
    state: 'ok',
    checkedAt: new Date().toISOString(),
  };
}

/**
 * Render Plugin Studio: the form, its live manifest, the real validator, a
 * personal install and an optional publish.
 *
 * Install and publish both stay locked until the validator passes, and
 * publish also needs a changelog and the license grant. Publishing ends at
 * "pending review" rather than claiming a catalog entry. A failed load of the
 * installed list only replaces the "start from" options with a note, so the
 * blank template still works.
 */
export function StudioPage() {
  const [draft, setDraft] = useState<Draft>(BLANK);
  const [installed, setInstalled] = useState<InstalledResponse['plugins']>([]);
  const [installedNote, setInstalledNote] = useState('');
  const [loadingFrom, setLoadingFrom] = useState(false);
  const [validation, setValidation] = useState<Verdict | null>(null);
  const [validating, setValidating] = useState(false);
  const [validationError, setValidationError] = useState('');
  const [changelog, setChangelog] = useState('');
  const [grant, setGrant] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState('');
  const [installing, setInstalling] = useState(false);
  const [installError, setInstallError] = useState('');
  const [created, setCreated] = useState<{ id: string; version: string } | null>(null);
  const [pending, setPending] = useState<{ pendingId: string; status: string; validation: Verdict } | null>(null);

  useEffect(() => {
    getMarket<InstalledResponse>('/api/marketplace/installed')
      .then((data) => setInstalled(data.plugins))
      .catch(() => setInstalledNote('Installed plugins could not be listed. You can still start blank.'));
  }, []);

  const manifest = useMemo(() => buildManifest(draft), [draft]);
  const widgetUi = useMemo(() => buildWidgetUi(manifest), [manifest]);
  const sample = useMemo(() => buildSample(), []);
  const previewSample: MarketSample = {
    elements: previewElements(draft),
    status: 'fresh',
    cause: '',
    checked_at: sample.checkedAt,
  };

  /** Return a change handler that writes one draft field from its input. */
  const set = (field: keyof Draft) => (
    event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => setDraft((current) => ({ ...current, [field]: event.target.value }));

  /**
   * Fill the form from an installed plugin, or reset to the blank template
   * when no id is given.
   *
   * Only descriptive fields are copied; permissions start empty, so a plugin
   * derived from another does not inherit its access.
   */
  const startFrom = async (id: string) => {
    if (!id) {
      setDraft(BLANK);
      return;
    }
    setLoadingFrom(true);
    setInstalledNote('');
    try {
      const data = await getMarket<{ plugin: { id: string; name: string; summary: string; category: string; tags: string[]; icon: string; license: string; version: string } }>(
        `/api/marketplace/plugin/${encodeURIComponent(id)}`);
      setDraft({
        id: data.plugin.id,
        name: data.plugin.name,
        summary: data.plugin.summary,
        category: data.plugin.category,
        tags: data.plugin.tags.join(', '),
        icon: data.plugin.icon,
        license: data.plugin.license || 'MIT',
        version: data.plugin.version,
      });
      setInstalledNote('Descriptive fields copied. Permissions start empty; add only what the plugin needs.');
    } catch (err) {
      setInstalledNote(marketErrorText(err));
    } finally {
      setLoadingFrom(false);
    }
  };

  /**
   * Run the server's validator over the current manifest, widget and sample,
   * replacing any earlier verdict.
   *
   * A draft missing an id, name or version is refused here with a message
   * rather than sent.
   */
  const validate = async () => {
    setValidationError('');
    setValidation(null);
    if (!draft.id.trim() || !draft.name.trim() || !draft.version.trim()) {
      setValidationError('Add an id, a name and a version before validating.');
      return;
    }
    setValidating(true);
    try {
      const verdict = await postMarket<Verdict>('/api/marketplace/validate',
        { manifest, widgetUi, sample });
      setValidation(verdict);
    } catch (err) {
      setValidationError(marketErrorText(err));
    } finally {
      setValidating(false);
    }
  };

  /**
   * Install the validated plugin on this desk and report the created id and
   * version.
   *
   * Refused unless the last verdict passed, so an unvalidated manifest never
   * reaches the server.
   */
  const install = async () => {
    setInstallError('');
    setCreated(null);
    if (!validation?.ok) {
      setInstallError('Run the validator and fix its findings before installing.');
      return;
    }
    setInstalling(true);
    try {
      const res = await postMarket<{ id: string; version: string; status: string }>(
        '/api/marketplace/studio/install',
        { manifest, widgetUi, sample },
      );
      setCreated({ id: res.id, version: res.version });
    } catch (err) {
      setInstallError(marketErrorText(err));
    } finally {
      setInstalling(false);
    }
  };

  /**
   * Submit the plugin for marketplace review.
   *
   * Three refusals happen here first — no passing verdict, an empty changelog,
   * and no license grant — because each is something only the author can fix.
   * Success stores the pending record, and the page reports review as pending
   * rather than the plugin as published.
   */
  const publish = async (event: FormEvent) => {
    event.preventDefault();
    if (!validation?.ok) {
      setPublishError('Run the validator and fix its findings before publishing.');
      return;
    }
    if (!changelog.trim()) {
      setPublishError('Write the changelog that reviewers will read.');
      return;
    }
    if (!grant) {
      setPublishError('Confirm the license grant before publishing.');
      return;
    }
    setPublishing(true);
    setPublishError('');
    try {
      const res = await postMarket<{ pendingId: string; status: string; validation: Verdict }>(
        '/api/marketplace/publish',
        { manifest, widgetUi, sample, changelog, licenseGrant: true },
      );
      setPending(res);
    } catch (err) {
      setPublishError(marketErrorText(err));
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="mkt-page">
      <header className="mkt-page-head">
        <span className="mkt-eyebrow">Marketplace</span>
        <h1>Plugin Studio</h1>
        <p className="mkt-lede">
          Build a declarative plugin manifest, run the real validator, then install it on this desk
          in one step. Publishing to the marketplace is a separate, optional review step.
        </p>
      </header>

      {created && (
        <section className="mkt-panel mkt-pending" aria-labelledby="mkt-created-title" role="status">
          <h2 id="mkt-created-title">Installed on this desk</h2>
          <p>
            <strong>{created.id}</strong> v{created.version} is installed and ready on the dashboard.
          </p>
          <p className="mkt-actions">
            <a className="btn btn-primary" href="/marketplace/installed">Open Installed</a>
            <a className="btn btn-secondary" href="/">Back to dashboard</a>
          </p>
        </section>
      )}

      {pending && (
        <section className="mkt-panel mkt-pending" aria-labelledby="mkt-pending-title" role="status">
          <h2 id="mkt-pending-title">Pending review</h2>
          <p>
            Submitted as <code>{pending.pendingId}</code>. An operator reviews it before it can appear
            in the catalog. This review does not change the copy already installed on this desk.
          </p>
          <p className="w-note">
            Validator at submission: {pending.validation?.ok ? 'passed' : 'failed'}
            {pending.validation?.failures?.length
              ? ` · ${pending.validation.failures.length} finding${pending.validation.failures.length === 1 ? '' : 's'}`
              : ''}.
          </p>
        </section>
      )}

      <div className="mkt-studio">
        <form className="mkt-studio-form" onSubmit={publish}>
          <section className="mkt-panel" aria-labelledby="mkt-start">
            <h2 id="mkt-start">Start from</h2>
            <label className="mkt-field">
              <span>Installed plugin or blank template</span>
              <select defaultValue="" disabled={loadingFrom}
                      onChange={(event) => void startFrom(event.target.value)}>
                <option value="">Blank template</option>
                {installed.map((record) => (
                  <option key={record.id} value={record.id}>{record.name} v{record.version}</option>
                ))}
              </select>
            </label>
            {installedNote && <p className="w-note">{installedNote}</p>}
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-basics">
            <h2 id="mkt-basics">Manifest basics</h2>
            <div className="mkt-field-grid">
              <label className="mkt-field">
                <span>Plugin id</span>
                <input value={draft.id} onChange={set('id')} placeholder="my-plugin" required />
              </label>
              <label className="mkt-field">
                <span>Version (semver)</span>
                <input value={draft.version} onChange={set('version')} placeholder="0.1.0" required />
              </label>
              <label className="mkt-field mkt-field-wide">
                <span>Name</span>
                <input value={draft.name} onChange={set('name')} placeholder="My plugin" required />
              </label>
              <label className="mkt-field mkt-field-wide">
                <span>Summary <small>({draft.summary.length}/120)</small></span>
                <textarea value={draft.summary} onChange={set('summary')} rows={3} maxLength={120} />
              </label>
              <label className="mkt-field">
                <span>Category</span>
                <select value={draft.category} onChange={set('category')}>
                  {CATEGORIES.map((category) => (
                    <option key={category} value={category}>{categoryLabel(category)}</option>
                  ))}
                </select>
              </label>
              <label className="mkt-field">
                <span>Icon</span>
                <select value={draft.icon} onChange={set('icon')}>
                  {ICONS.map((icon) => <option key={icon} value={icon}>{icon}</option>)}
                </select>
              </label>
              <label className="mkt-field">
                <span>License (SPDX)</span>
                <input value={draft.license} onChange={set('license')} placeholder="MIT" required />
              </label>
              <label className="mkt-field">
                <span>Tags (comma separated, max 8)</span>
                <input value={draft.tags} onChange={set('tags')} placeholder="finance, invoices" />
              </label>
            </div>
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-validate">
            <h2 id="mkt-validate">Validate</h2>
            <p className="w-note">The same validator that guards installs checks this manifest, widget and sample.</p>
            <Button tone="secondary" disabled={validating} onClick={() => void validate()}>
              {validating ? 'Validating…' : 'Run validator'}
            </Button>
            {validationError && <p className="mkt-error" role="alert">{validationError}</p>}
            {validation && (
              <div className={`mkt-verdict mkt-verdict-${validation.ok ? 'ok' : 'bad'}`} role="status">
                <p><strong>{validation.ok ? 'Validator passed.' : 'Validator found problems.'}</strong></p>
                {validation.failures.length > 0 && (
                  <ul>
                    {validation.failures.map((failure) => (
                      <li key={failure.code}><code>{failure.code}</code> {failure.message}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-install">
            <h2 id="mkt-install">Install on this desk</h2>
            <p className="w-note">
              This is the personal path: the validated plugin is copied onto this machine and starts
              running now. No operator or environment switch is involved.
            </p>
            {installError && <p className="mkt-error" role="alert">{installError}</p>}
            <Button tone="primary" disabled={installing || !validation?.ok} onClick={() => void install()}>
              {installing ? 'Installing…' : 'Install on this desk'}
            </Button>
            {!validation?.ok && <p className="w-note">Install unlocks after the validator passes.</p>}
          </section>

          <section className="mkt-panel" aria-labelledby="mkt-publish">
            <h2 id="mkt-publish">Publish for review (optional)</h2>
            <label className="mkt-field">
              <span>Changelog (required)</span>
              <textarea value={changelog} onChange={(event) => setChangelog(event.target.value)}
                        rows={4} placeholder="What changed in this version?" required />
            </label>
            <label className="mkt-grant">
              <input type="checkbox" checked={grant} onChange={(event) => setGrant(event.target.checked)} />
              <span>I grant this desk permission to distribute the plugin under its declared license.</span>
            </label>
            {publishError && <p className="mkt-error" role="alert">{publishError}</p>}
            <Button tone="primary" type="submit"
                    disabled={publishing || !validation?.ok || !changelog.trim() || !grant}>
              {publishing ? 'Submitting…' : 'Publish for review'}
            </Button>
            {!validation?.ok && <p className="w-note">Publish unlocks after the validator passes.</p>}
          </section>
        </form>

        <div className="mkt-studio-preview">
          <section className="mkt-panel" aria-labelledby="mkt-manifest-preview">
            <h2 id="mkt-manifest-preview">manifest.json</h2>
            <pre className="mkt-manifest" aria-label="Live manifest preview">{JSON.stringify(manifest, null, 2)}</pre>
          </section>
          <SamplePreview sample={previewSample} title={manifest.name} />
        </div>
      </div>
    </div>
  );
}

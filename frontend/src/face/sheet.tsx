import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '../index.css';
import './sheet.css';
import AgentFace from './AgentFace';
import {
  DEFAULT_FACE_PRESET,
  FACE_PRESET_IDS,
  FACE_PRESETS,
  type FaceConfig,
  type FacePresetId,
} from './config';
import { FaceProvider, useFaceActions } from './FaceProvider';
import FaceSlot from './FaceSlot';
import { FACE_MOODS, MOOD_DEFAULT_LABELS, type FaceMood } from './moods';
import { AGENT_NAME } from './name';
import { useFaceActivity } from './useFaceActivity';

const THEMES = ['unkey', 'coforge', 'momentuum'] as const;

/** Interactive playground demonstrating preset switching, tooltip, squash, pointer follow, and command-bar gaze. */
function InteractiveDemo({
  presetId,
  onSelectPreset,
  config,
}: {
  presetId: FacePresetId;
  onSelectPreset: (id: FacePresetId) => void;
  config: FaceConfig;
}) {
  const [text, setText] = useState('');
  const [manualMood, setManualMood] = useState<FaceMood>('idle');
  const [stepIndex, setStepIndex] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const actions = useFaceActions();
  const setLookTarget = actions?.setLookTarget;
  const isTyping = text.trim().length > 0;

  useFaceActivity({
    mood: isTyping ? 'listening' : manualMood,
    label: isTyping ? 'Listening to your prompt' : undefined,
    source:
      manualMood === 'thinking' || manualMood === 'reading' || manualMood === 'working'
        ? 'request'
        : undefined,
    stepIndex: manualMood === 'working' ? stepIndex : undefined,
    active: isTyping || manualMood !== 'idle',
  });

  useEffect(() => {
    const el = inputRef.current;
    if (!setLookTarget || !el || !isTyping) {
      setLookTarget?.(null);
      return;
    }
    const rect = el.getBoundingClientRect();
    setLookTarget({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
  }, [setLookTarget, isTyping, text]);

  return (
    <div className="face-sheet-demo">
      <div className="face-sheet-stage">
        <FaceSlot slot="rail" />
        <span className="face-sheet-label">{AGENT_NAME}</span>
        <span className="face-sheet-meta">
          {config.label} ({config.eyes.widthMd}x{config.eyes.heightMd}px, r={config.eyes.radius}px)
        </span>
        <span className="face-sheet-meta">
          Hover for title, click to squash, move pointer nearby
        </span>
      </div>
      <div className="face-sheet-controls">
        <div className="face-sheet-row" aria-label="Personality presets">
          {FACE_PRESET_IDS.map((id) => (
            <button
              key={id}
              type="button"
              className={presetId === id ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              onClick={() => onSelectPreset(id)}
            >
              {FACE_PRESETS[id].label}
            </button>
          ))}
        </div>
        <div className="face-sheet-row" aria-label="Mood selector">
          {FACE_MOODS.map((mood) => (
            <button
              key={mood}
              type="button"
              className={manualMood === mood ? 'btn btn-primary btn-sm' : 'btn btn-secondary btn-sm'}
              onClick={() => setManualMood(mood)}
            >
              {mood}
            </button>
          ))}
          {manualMood === 'working' ? (
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => setStepIndex((n) => (n + 1) % 5)}
            >
              Step row ({stepIndex + 1}/5)
            </button>
          ) : null}
        </div>
        <div className="cmd">
          <div className="cmd-inner">
            <textarea
              ref={inputRef}
              className="cmd-field"
              rows={1}
              value={text}
              placeholder="Type here to test listening + command-bar gaze..."
              onChange={(e) => setText(e.target.value)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

/** Dev-only visual review sheet for the agent face across presets, moods, sizes, themes, and header slots. */
function FaceSheetApp() {
  const [presetId, setPresetId] = useState<FacePresetId>(DEFAULT_FACE_PRESET);
  const activeConfig = FACE_PRESETS[presetId];

  return (
    <div className="face-sheet">
      <header className="face-sheet-head">
        <div>
          <h1>{AGENT_NAME} Review Sheet</h1>
          <p className="face-sheet-sub">
            Dev-only verification for 4 personality options (default: {FACE_PRESETS[DEFAULT_FACE_PRESET].label}), all 8 moods, 3 themes, 2 sizes, reduced-motion poses, and header compositions.
          </p>
        </div>
      </header>

      <section className="face-sheet-section">
        <h2>Interactive demo</h2>
        <FaceProvider config={activeConfig}>
          <InteractiveDemo
            presetId={presetId}
            onSelectPreset={setPresetId}
            config={activeConfig}
          />
        </FaceProvider>
      </section>

      <section className="face-sheet-section">
        <h2>Compare the 4 personality options (all 8 moods + 3 themes)</h2>
        <div className="face-sheet-presets">
          {FACE_PRESET_IDS.map((id) => {
            const preset = FACE_PRESETS[id];
            return (
              <div className="face-sheet-preset-card" key={id}>
                <div className="face-sheet-preset-head">
                  <span className="face-sheet-label">
                    {preset.label}{id === DEFAULT_FACE_PRESET ? ' (main)' : ''}: {preset.description}
                  </span>
                  <span className="face-sheet-meta">
                    fill:{preset.body.fillToken} border:{preset.body.borderToken} eyes:{preset.eyes.colorToken} {preset.eyes.widthMd}x{preset.eyes.heightMd} r:{preset.eyes.radius}
                  </span>
                </div>
                <div className="face-sheet-mood-strip">
                  {FACE_MOODS.map((mood) => (
                    <div className="face-sheet-mood-cell" key={`${id}-${mood}`}>
                      <AgentFace mood={mood} config={preset} />
                      <span className="face-sheet-meta">{mood}</span>
                    </div>
                  ))}
                </div>
                <div className="face-sheet-theme-strip">
                  {THEMES.map((theme) => (
                    <div
                      className="face-sheet-theme-swatch"
                      data-theme-preview={theme}
                      key={`${id}-${theme}`}
                    >
                      <span className="face-sheet-meta">{theme}</span>
                      <div className="face-sheet-row">
                        <AgentFace mood="idle" config={preset} />
                        <AgentFace mood="thinking" config={preset} />
                        <AgentFace mood="working" config={preset} />
                        <AgentFace mood="done" config={preset} />
                        <AgentFace size="sm" mood="idle" config={preset} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="face-sheet-section">
        <h2>Active preset ({activeConfig.label}): all 8 moods (32px default)</h2>
        <div className="face-sheet-grid">
          {FACE_MOODS.map((mood) => (
            <div className="face-sheet-tile" key={mood}>
              <AgentFace mood={mood} config={activeConfig} />
              <span className="face-sheet-label">{mood}</span>
              <span className="face-sheet-meta">{MOOD_DEFAULT_LABELS[mood]}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="face-sheet-section">
        <h2>Two sizes ({activeConfig.label}: 32px md vs 24px sm)</h2>
        <div className="face-sheet-row">
          <div className="face-sheet-tile">
            <AgentFace size="md" mood="idle" config={activeConfig} />
            <span className="face-sheet-meta">md idle (32px)</span>
          </div>
          <div className="face-sheet-tile">
            <AgentFace size="sm" mood="idle" config={activeConfig} />
            <span className="face-sheet-meta">sm idle (24px)</span>
          </div>
          <div className="face-sheet-tile">
            <AgentFace size="md" mood="done" config={activeConfig} />
            <span className="face-sheet-meta">md done (32px)</span>
          </div>
          <div className="face-sheet-tile">
            <AgentFace size="sm" mood="done" config={activeConfig} />
            <span className="face-sheet-meta">sm done (24px)</span>
          </div>
          <div className="face-sheet-tile">
            <AgentFace size="sm" mood="blocked" config={activeConfig} />
            <span className="face-sheet-meta">sm blocked (24px)</span>
          </div>
        </div>
      </section>

      <section className="face-sheet-section">
        <h2>Reduced motion poses ({activeConfig.label}: static per mood)</h2>
        <div className="face-sheet-grid">
          {FACE_MOODS.map((mood) => (
            <div className="face-sheet-tile" key={`rm-${mood}`}>
              <AgentFace mood={mood} config={activeConfig} reducedMotion />
              <span className="face-sheet-label">{mood}</span>
              <span className="face-sheet-meta">prefers-reduced-motion</span>
            </div>
          ))}
        </div>
      </section>

      <section className="face-sheet-section">
        <h2>Header compositions across three themes ({activeConfig.label})</h2>
        <div className="face-sheet-themes">
          {THEMES.map((theme) => (
            <div className="face-sheet-theme-card" data-theme-preview={theme} key={theme}>
              <span className="face-sheet-label">{theme}</span>
              <div className="face-sheet-row">
                <AgentFace mood="idle" config={activeConfig} />
                <AgentFace mood="listening" config={activeConfig} />
                <AgentFace mood="blocked" config={activeConfig} />
                <AgentFace mood="done" config={activeConfig} />
                <AgentFace size="sm" mood="idle" config={activeConfig} />
              </div>

              <div className="face-sheet-rail-preview">
                <div className="brand">
                  <AgentFace mood="idle" config={activeConfig} />
                  <span className="brand-name">{AGENT_NAME}</span>
                </div>
              </div>

              <div className="face-sheet-rail-preview is-collapsed">
                <div className="brand">
                  <AgentFace mood="idle" config={activeConfig} />
                  <span className="brand-name">{AGENT_NAME}</span>
                </div>
              </div>

              <div className="face-sheet-modal-preview">
                <header className="setup-head">
                  <div className="face-modal-title">
                    <AgentFace mood="working" config={activeConfig} />
                    <h2>Reading your description</h2>
                  </div>
                  <button type="button" className="btn btn-secondary">Close</button>
                </header>
              </div>

              <div className="face-sheet-modal-preview">
                <header className="setup-head">
                  <div className="face-modal-title">
                    <AgentFace size="sm" mood="thinking" config={activeConfig} />
                    <h2>Set up this tracker</h2>
                  </div>
                  <button type="button" className="btn btn-secondary">Close</button>
                </header>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

const rootEl = document.getElementById('root');
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <FaceSheetApp />
    </StrictMode>,
  );
}

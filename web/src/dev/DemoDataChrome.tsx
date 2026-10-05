import {
  useFixtureMode,
  writeFixtureMode,
  type FixtureMode,
} from "./fixtureMode";

const SEGMENTS: Array<{ mode: FixtureMode | null; label: string }> = [
  { mode: null, label: "Demo" },
  { mode: "worst", label: "Worst case" },
  { mode: "empty", label: "Empty" },
  { mode: "one", label: "One" },
  { mode: "1000", label: "1,000 rows" },
];

export function DemoDataChrome() {
  const mode = useFixtureMode();
  return (
    <>
      <style>{DEV_FIXTURE_CSS}</style>
      {mode === null ? null : (
        <p className="dev-fixture-banner" role="status">
          Example data — invented transactions, not your books. Nothing here is
          saved. Mode: {segmentLabel(mode)}.
        </p>
      )}
      <div className="dev-fixture-switch" role="group" aria-label="Demo data">
        {SEGMENTS.map((segment) => (
          <button
            key={segment.label}
            type="button"
            aria-pressed={mode === segment.mode}
            onClick={() => {
              writeFixtureMode(segment.mode);
            }}
          >
            {segment.label}
          </button>
        ))}
      </div>
    </>
  );
}

function segmentLabel(mode: FixtureMode): string {
  return SEGMENTS.find((segment) => segment.mode === mode)?.label ?? mode;
}

const DEV_FIXTURE_CSS = `
.dev-fixture-banner {
  margin: 0 0 0.75rem;
  padding: 0.45rem 0.65rem;
  border: 1px dashed #878580;
  border-radius: 8px;
  background: #fff6df;
  color: #3a3428;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 13px;
  line-height: 1.35;
}
[data-theme="dark"] .dev-fixture-banner {
  background: #2c281c;
  color: #f0e2c0;
}
.dev-fixture-switch {
  position: fixed;
  z-index: 80;
  left: 50%;
  bottom: 10px;
  display: flex;
  max-width: calc(100vw - 12px);
  padding: 3px;
  border-radius: 999px;
  background: #d9d6d0;
  box-shadow: 0 6px 20px rgb(16 15 15 / 22%);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 12px;
  line-height: 1.2;
  transform: translateX(-50%);
}
.dev-fixture-switch button {
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: #3f3d3a;
  padding: 0.28rem 0.55rem;
  white-space: nowrap;
}
.dev-fixture-switch button[aria-pressed="true"] {
  background: #fff;
  color: #1c1b1a;
}
.stage:has(.dev-fixture-switch) {
  scroll-padding-bottom: 3.25rem;
}
`;

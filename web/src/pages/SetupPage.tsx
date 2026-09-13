import type { Dispatch } from "react";

import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useEntrance } from "../hooks/useEntrance";
import { SETUP_CATEGORIES, WATCH_ACCOUNTS } from "../lib/accounts";
import {
  SETUP_STEP_COUNT,
  SETUP_STEPS,
  activeCategoryNames,
  firstBlockedStep,
  stepValid,
  watchedAccounts,
  type SetupAction,
  type SetupState,
} from "../lib/setup";

export function SetupPage({
  state,
  dispatch,
  transactionCount,
  reviewCount,
  blockingCount,
  onReturn,
}: {
  state: SetupState;
  dispatch: Dispatch<SetupAction>;
  transactionCount: number;
  reviewCount: number;
  blockingCount: number;
  onReturn: () => void;
}) {
  const index = state.step;
  const step = SETUP_STEPS[index];
  const blocked = firstBlockedStep(state);
  const valid = stepValid(state, index);
  const last = index === SETUP_STEP_COUNT - 1;
  const replay = index === 0 && state.onboarded;
  const fresh = useEntrance(`onboarding:${index}`);
  if (step === undefined) {
    return null;
  }
  return (
    <div className="app is-onboarding">
      <div className="onboard">
        <article className={`card onboard-card${fresh ? " stage-enter" : ""}`}>
          <p className="eyebrow">
            Setup · {index + 1} of {SETUP_STEP_COUNT}
          </p>
          <div className="steps" role="list">
            {SETUP_STEPS.map((item, stepIndex) => (
              <button
                key={item.id}
                className={`step-dot${stepIndex < index ? " is-done" : ""}`}
                type="button"
                aria-label={item.id}
                aria-current={stepIndex === index ? "step" : undefined}
                disabled={stepIndex > blocked}
                onClick={() => {
                  dispatch({ type: "goStep", step: stepIndex });
                }}
              />
            ))}
          </div>
          <h1>{step.title}</h1>
          <p className="lede">{step.lede}</p>
          <StepBody
            state={state}
            dispatch={dispatch}
            transactionCount={transactionCount}
            reviewCount={reviewCount}
            blockingCount={blockingCount}
          />
          <div className="onboard-nav">
            {replay ? (
              <Button variant="ghost" onClick={onReturn}>
                Return to Overview
              </Button>
            ) : (
              <Button
                variant="ghost"
                disabled={index === 0}
                onClick={() => {
                  dispatch({ type: "back" });
                }}
              >
                Back
              </Button>
            )}
            <div className="onboard-nav-actions">
              <p className="gate-hint" role="status" hidden={valid}>
                {step.hint}
              </p>
              <Button
                variant="primary"
                disabled={!valid}
                onClick={() => {
                  if (last) {
                    dispatch({ type: "finish" });
                    onReturn();
                    return;
                  }
                  dispatch({ type: "advance" });
                }}
              >
                {last ? "Enter Overview" : "Continue"}
              </Button>
            </div>
          </div>
        </article>
      </div>
    </div>
  );
}

function StepBody({
  state,
  dispatch,
  transactionCount,
  reviewCount,
  blockingCount,
}: {
  state: SetupState;
  dispatch: Dispatch<SetupAction>;
  transactionCount: number;
  reviewCount: number;
  blockingCount: number;
}) {
  if (state.step === 0) {
    return (
      <div className="stack">
        <label className="field-label">
          Reporting Currency
          <input className="field" value="SGD" readOnly />
        </label>
        <label className="field-label">
          Timezone
          <input className="field" value="Asia/Singapore" readOnly />
        </label>
        <label className="field-label">
          Owner identity
          <input className="field" value="you@tailnet" readOnly />
        </label>
        <p className="muted">
          Owner identity comes from Tailscale. Secrets stay on the host. This
          flow only records what the app should watch.
        </p>
      </div>
    );
  }
  if (state.step === 1) {
    return (
      <div className="stack">
        {WATCH_ACCOUNTS.map((account) => {
          const on = state.selectedAccountIds.includes(account.id);
          return (
            <button
              key={account.id}
              className="card account-toggle"
              type="button"
              aria-pressed={on}
              onClick={() => {
                dispatch({ type: "toggleAccount", id: account.id });
              }}
            >
              <Badge tone={on ? "confirmed" : "count"}>
                {on ? "Watching" : "Off"}
              </Badge>
              <span>
                <strong style={{ display: "block" }}>{account.name}</strong>
                <span className="muted">{account.kind}</span>
              </span>
            </button>
          );
        })}
      </div>
    );
  }
  if (state.step === 2) {
    const rows = watchedAccounts(state);
    const artifacts = rows.flatMap((account) => account.artifacts);
    return (
      <div className="stack">
        {rows.map((account) => (
          <div
            className="card"
            key={account.id}
            style={{ padding: "12px 16px" }}
          >
            <strong>{account.name}</strong>
            <div className="path">{account.inbox}</div>
          </div>
        ))}
        {state.probe === "running" ? (
          <div className="probe">
            <p className="probe-line">
              <span className="spinner" />
              Reading {rows.length} inbox{" "}
              {rows.length === 1 ? "folder" : "folders"}…
            </p>
          </div>
        ) : null}
        {state.probe === "ok" ? (
          <div className="probe">
            <p className="probe-line" style={{ color: "var(--bz-positive)" }}>
              <b style={{ color: "var(--bz-positive)" }}>
                {artifacts.length} Source Artifacts
              </b>{" "}
              readable across {rows.length}{" "}
              {rows.length === 1 ? "inbox" : "inboxes"}
            </p>
            {artifacts.map((artifact) => (
              <p className="probe-line" key={artifact.file}>
                {artifact.file}{" "}
                <b
                  style={
                    artifact.ok ? undefined : { color: "var(--bz-provisional)" }
                  }
                >
                  {artifact.parser}
                </b>
              </p>
            ))}
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <Button
            variant="outline"
            disabled={state.probe === "running"}
            onClick={() => {
              dispatch({ type: "probeStart" });
            }}
          >
            {state.probe === "ok" ? "Read again" : "Test read"}
          </Button>
          <span className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
            Reads each inbox once and reports which parser claims each Source
            Artifact.
          </span>
        </div>
        <button
          className="card account-toggle"
          type="button"
          aria-pressed={state.shortcut}
          onClick={() => {
            dispatch({ type: "toggleShortcut" });
          }}
        >
          <Badge tone={state.shortcut ? "confirmed" : "count"}>
            {state.shortcut ? "On" : "Off"}
          </Badge>
          <span>
            <strong style={{ display: "block" }}>Apple Shortcut</strong>
            <span className="muted">
              Creates Real-time Claims from Apple Pay. Token scope is created
              later in Settings.
            </span>
          </span>
        </button>
      </div>
    );
  }
  if (state.step === 3) {
    const extra = state.extraCategory.trim();
    const names = activeCategoryNames(state);
    return (
      <div className="stack">
        <div className="filters">
          {SETUP_CATEGORIES.map((name) => (
            <button
              key={name}
              className="chip"
              type="button"
              aria-pressed={state.enabledCategories.includes(name)}
              onClick={() => {
                dispatch({ type: "toggleCategory", name });
              }}
            >
              {name}
            </button>
          ))}
          {extra !== "" &&
          !(SETUP_CATEGORIES as readonly string[]).includes(extra) ? (
            <span className="chip" aria-pressed="true">
              {extra}
            </span>
          ) : null}
          <span className="chip">Uncategorized</span>
        </div>
        <label className="field-label">
          Add a Category
          <input
            className="field"
            value={state.extraCategory}
            placeholder="Family, Pets, Home"
            onChange={(event) => {
              dispatch({ type: "setExtraCategory", name: event.target.value });
            }}
          />
        </label>
        <p className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
          {names.length} Categories will be offered when a Transaction needs
          one. Uncategorized always stays available.
        </p>
      </div>
    );
  }
  if (state.extract !== "done") {
    const artifactCount = watchedAccounts(state).flatMap(
      (account) => account.artifacts,
    ).length;
    return (
      <div className="stack">
        {state.extract === "running" ? (
          <div className="probe">
            <p className="probe-line">
              <span className="spinner" />
              Staging Claims from {artifactCount} Source Artifacts…
            </p>
            <p className="probe-line">Validating statement totals</p>
            <p className="probe-line">Reconciling Real-time Claims</p>
          </div>
        ) : null}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <Button
            variant="outline"
            disabled={state.extract === "running"}
            onClick={() => {
              dispatch({ type: "extractStart" });
            }}
          >
            Run first Extraction
          </Button>
          <span className="muted" style={{ fontSize: "var(--bz-text-xs)" }}>
            A statement that fails validation creates no Claims and is
            quarantined instead.
          </span>
        </div>
      </div>
    );
  }
  const provisionalNote = 0;
  return (
    <div className="stack">
      <div className="probe">
        <p className="probe-line" style={{ color: "var(--bz-positive)" }}>
          <b style={{ color: "var(--bz-positive)" }}>Extraction accepted</b>{" "}
          September history is on disk
        </p>
      </div>
      <dl className="kv">
        <dt>Financial Accounts</dt>
        <dd>
          {state.selectedAccountIds.length} watching, Reporting Currency SGD
        </dd>
        <dt>Categories</dt>
        <dd>
          {activeCategoryNames(state).length} enabled for Expense reporting
        </dd>
        <dt>Apple Shortcut</dt>
        <dd>{state.shortcut ? "On for Real-time Claims" : "Off"}</dd>
        <dt>Transactions</dt>
        <dd>
          {transactionCount} established, {provisionalNote} still Provisional
        </dd>
        <dt>Pending Review</dt>
        <dd>
          {reviewCount} items
          {blockingCount > 0
            ? ", including one blocking failed Extraction"
            : ""}
        </dd>
        <dt>Next</dt>
        <dd>Overview is home. The rail badge keeps Review one click away.</dd>
      </dl>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";

import {
  createRecurring,
  dismissRecurring,
  getProposedRecurrings,
  getRecurringSummary,
  getRecurrings,
  updateRecurring,
  type RecurringCreateInput,
  type RecurringPatch,
  type RecurringSeries,
  type RecurringSummary,
} from "../api";
import { messageFor } from "../lib/labels";

export function useRecurrings() {
  const [proposed, setProposed] = useState<RecurringSeries[]>([]);
  const [active, setActive] = useState<RecurringSeries[]>([]);
  const [paused, setPaused] = useState<RecurringSeries[]>([]);
  const [summary, setSummary] = useState<RecurringSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const [proposedPage, activePage, pausedPage, nextSummary] =
      await Promise.all([
        getProposedRecurrings(),
        getRecurrings("active"),
        getRecurrings("paused"),
        getRecurringSummary(3),
      ]);
    setProposed(proposedPage.items);
    setActive(activePage.items);
    setPaused(pausedPage.items);
    setSummary(nextSummary);
    setError(null);
  }, []);

  useEffect(() => {
    let activeRequest = true;
    void Promise.all([
      getProposedRecurrings(),
      getRecurrings("active"),
      getRecurrings("paused"),
      getRecurringSummary(3),
    ])
      .then(([proposedPage, activePage, pausedPage, nextSummary]) => {
        if (!activeRequest) {
          return;
        }
        setProposed(proposedPage.items);
        setActive(activePage.items);
        setPaused(pausedPage.items);
        setSummary(nextSummary);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (activeRequest) {
          setError(messageFor(requestError));
        }
      })
      .finally(() => {
        if (activeRequest) {
          setLoading(false);
        }
      });
    return () => {
      activeRequest = false;
    };
  }, []);

  async function run(
    key: string,
    action: () => Promise<unknown>,
  ): Promise<boolean> {
    setSaving(key);
    setError(null);
    try {
      await action();
      await reload();
      return true;
    } catch (requestError) {
      setError(messageFor(requestError));
      return false;
    } finally {
      setSaving(null);
    }
  }

  return {
    proposed,
    active,
    paused,
    summary,
    loading,
    saving,
    error,
    confirm: (seriesId: string, patch: RecurringPatch) =>
      run(seriesId, () =>
        updateRecurring(seriesId, { ...patch, status: "active" }),
      ),
    dismiss: (seriesId: string) =>
      run(seriesId, () => dismissRecurring(seriesId)),
    update: (seriesId: string, patch: RecurringPatch) =>
      run(seriesId, () => updateRecurring(seriesId, patch)),
    create: (input: RecurringCreateInput) =>
      run("create", () => createRecurring(input)),
  };
}

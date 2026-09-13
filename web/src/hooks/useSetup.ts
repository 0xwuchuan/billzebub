import { useEffect, useReducer } from "react";

import { prefersReducedMotion } from "../lib/motion";
import {
  loadSetup,
  reduceSetup,
  saveSetup,
  type SetupState,
} from "../lib/setup";

export function useSetup() {
  const [state, dispatch] = useReducer(reduceSetup, undefined, loadSetup);

  useEffect(() => {
    saveSetup(state);
  }, [state]);

  useEffect(() => {
    if (state.probe !== "running") {
      return;
    }
    const timer = window.setTimeout(
      () => {
        dispatch({ type: "probeOk" });
      },
      prefersReducedMotion() ? 120 : 900,
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [state.probe]);

  useEffect(() => {
    if (state.extract !== "running") {
      return;
    }
    const timer = window.setTimeout(
      () => {
        dispatch({ type: "extractDone" });
      },
      prefersReducedMotion() ? 160 : 1400,
    );
    return () => {
      window.clearTimeout(timer);
    };
  }, [state.extract]);

  return { state, dispatch };
}

export type { SetupState };

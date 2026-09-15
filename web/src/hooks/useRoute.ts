import { useCallback, useEffect, useState } from "react";

import { defaultRoute, hashFor, parseHash, type Route } from "../lib/route";

export function useRoute(onboarded: boolean) {
  const [, setTick] = useState(0);

  useEffect(() => {
    function onHashChange() {
      setTick((tick) => tick + 1);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  const route =
    window.location.hash === ""
      ? defaultRoute(onboarded)
      : parseHash(window.location.hash, onboarded);

  const go = useCallback((next: Route) => {
    const hash = hashFor(next);
    if (window.location.hash !== hash) {
      window.location.hash = hash;
      return;
    }
    setTick((tick) => tick + 1);
  }, []);

  return { route, go };
}

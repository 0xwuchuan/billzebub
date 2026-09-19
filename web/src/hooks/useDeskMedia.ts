import { useEffect, useState } from "react";

export const DESK_MEDIA = "(min-width: 64.01rem)";

export function useDeskMedia(): boolean {
  const [desk, setDesk] = useState(readDesk);

  useEffect(() => {
    const media = window.matchMedia(DESK_MEDIA);
    function onChange() {
      setDesk(media.matches);
    }
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, []);

  return desk;
}

function readDesk(): boolean {
  return window.matchMedia(DESK_MEDIA).matches;
}

import { useEffect, useState } from "react";

/** Phone sheet. Matches the shell rail breakpoint (`max-width: 52rem`). */
export const OVERLAY_MEDIA = "(max-width: 52rem)";

export function useOverlayMedia(): boolean {
  const [overlay, setOverlay] = useState(readOverlay);

  useEffect(() => {
    const media = window.matchMedia(OVERLAY_MEDIA);
    function onChange() {
      setOverlay(media.matches);
    }
    onChange();
    media.addEventListener("change", onChange);
    return () => {
      media.removeEventListener("change", onChange);
    };
  }, []);

  return overlay;
}

function readOverlay(): boolean {
  return window.matchMedia(OVERLAY_MEDIA).matches;
}

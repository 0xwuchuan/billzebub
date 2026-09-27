import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const html = readFileSync("index.html", "utf8");
const manifest = JSON.parse(readFileSync("public/site.webmanifest", "utf8"));

describe("product mark", () => {
  it("wires favicon, apple touch, and the web manifest", () => {
    expect(html).toContain('rel="icon" href="/favicon.ico" sizes="any"');
    expect(html).toContain(
      'rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"',
    );
    expect(html).toContain(
      'rel="icon" type="image/png" sizes="192x192" href="/icon-192.png"',
    );
    expect(html).toContain(
      'rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png"',
    );
    expect(html).toContain('rel="manifest" href="/site.webmanifest"');
    expect(html).not.toContain("baby-beel");
  });

  it("publishes 192 and 512 icons for the manifest", () => {
    expect(manifest.icons).toEqual([
      {
        src: "/icon-192.png",
        sizes: "192x192",
        type: "image/png",
      },
      {
        src: "/icon-512.png",
        sizes: "512x512",
        type: "image/png",
      },
    ]);
    for (const file of [
      "public/favicon.ico",
      "public/favicon-32.png",
      "public/apple-touch-icon.png",
      "public/icon-192.png",
      "public/icon-512.png",
    ]) {
      expect(readFileSync(file).byteLength).toBeGreaterThan(100);
    }
  });
});

import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const tokens = readFileSync("src/styles/tokens.css", "utf8");
const shell = readFileSync("src/styles/shell.css", "utf8");

const light = tokens.slice(tokens.indexOf(':root[data-theme="light"]'));

describe("design tokens", () => {
  it("steps surfaces from bg to elevated to card in both themes", () => {
    for (const source of [tokens, light]) {
      expect(source).toMatch(/--bz-bg:/);
      expect(source).toMatch(/--bz-bg-elevated:/);
      expect(source).toMatch(/--bz-bg-card:/);
    }
    expect(tokens).toMatch(/--bz-surface:\s*var\(--bz-bg-card\)/);
    expect(tokens).toMatch(/--bz-rail-bg:\s*var\(--bz-bg\)/);
  });

  it("names the type, radius, and status roles", () => {
    expect(tokens).toMatch(/--bz-text-display:/);
    expect(tokens).toMatch(/--bz-text-title:/);
    expect(tokens).toMatch(/--bz-text-body:/);
    expect(tokens).toMatch(/--bz-text-meta:/);
    expect(tokens).toMatch(/--bz-nums:\s*tabular-nums/);
    expect(tokens).toMatch(/--bz-radius-card:\s*8px/);
    expect(tokens).toMatch(/--bz-radius-control:\s*6px/);
    expect(tokens).toMatch(/--bz-radius-pill:\s*999px/);
    expect(tokens).toMatch(/--bz-space-1:\s*4px/);
    expect(tokens).toMatch(/--bz-action:/);
    expect(tokens).toMatch(/--bz-confirmed:/);
    expect(tokens).toMatch(/--bz-provisional:/);
    expect(tokens).toMatch(/--bz-attention:/);
    expect(tokens).toMatch(/--bz-blocking:/);
    expect(tokens).toMatch(/--bz-hue-pink:/);
  });

  it("keeps the light theme on the same token names", () => {
    expect(light).toMatch(/--bz-action:/);
    expect(light).toMatch(/--bz-confirmed:/);
    expect(light).toMatch(/--bz-attention:/);
    expect(light).toMatch(/--bz-blocking:/);
    expect(light).toMatch(/--bz-hue-cyan:/);
    expect(light).not.toMatch(/--bz-accent:\s*#/);
  });
});

describe("desktop shell tokens", () => {
  it("paints the rail active state as a quiet fill", () => {
    expect(shell).toMatch(/--bz-nav-active/);
    expect(shell).not.toMatch(/box-shadow:\s*inset/);
    expect(shell).toMatch(/background:\s*var\(--bz-bg-elevated\)/);
    expect(shell).toMatch(/background:\s*var\(--bz-bg-card\)/);
  });

  it("does not hardcode colors in the shell stylesheet", () => {
    expect(shell).not.toMatch(/#[0-9a-fA-F]{3,8}/);
  });
});

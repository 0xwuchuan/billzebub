import { describe, expect, it } from "vitest";

import {
  claimCountLabel,
  describeIdentity,
  formatAccountLabel,
  splitFileTail,
  UNKNOWN_COUNTERPARTY,
} from "./identity";

describe("describeIdentity", () => {
  it("keeps people intact for CSS ellipsis", () => {
    expect(describeIdentity("Jo")).toEqual({ kind: "plain", text: "Jo" });
    expect(describeIdentity("  ")).toEqual({ kind: "empty" });
  });

  it("middle-splits emails so the domain stays after @", () => {
    expect(
      describeIdentity(
        "bartholomew.fitzgerald@northwind-industries-holdings.example.com",
      ),
    ).toEqual({
      kind: "email",
      local: "bartholomew.fitzgerald",
      domain: "northwind-industries-holdings.example.com",
    });
  });

  it("drops the URL scheme and leaves the host at the start", () => {
    expect(
      describeIdentity("https://example.com/workspaces/acme/docs/9f8e7d6c?x=1"),
    ).toEqual({
      kind: "url",
      text: "example.com/workspaces/acme/docs/9f8e7d6c?x=1",
    });
  });

  it("keeps a filename extension as the tail", () => {
    expect(
      describeIdentity("IMG_20250914_183022_HDR_portrait_edited_edited.HEIC"),
    ).toEqual({
      kind: "file",
      stem: "IMG_20250914_183022_HDR_portrait_edited_edited",
      ext: "HEIC",
    });
  });
});

describe("formatAccountLabel", () => {
  it("end-truncates by returning the name, and drops a URL scheme", () => {
    expect(formatAccountLabel("Example Card")).toBe("Example Card");
    expect(formatAccountLabel("https://example.com/cards/woman")).toBe(
      "example.com/cards/woman",
    );
  });
});

describe("splitFileTail", () => {
  it("keeps an extension and otherwise keeps the end of a long key", () => {
    expect(splitFileTail("statement.PDF")).toEqual({
      lead: "statement",
      tail: ".PDF",
    });
    expect(UNKNOWN_COUNTERPARTY).toBe("Unknown counterparty");
    const long = "dbs-credit-card-northwind-industries-holdings-singapore";
    expect(splitFileTail(long)?.tail).toBe(long.slice(-14));
  });
});

describe("claimCountLabel", () => {
  it("uses a lowercase singular and plural", () => {
    expect(claimCountLabel(1)).toBe("1 claim");
    expect(claimCountLabel(2)).toBe("2 claims");
    expect(claimCountLabel(0)).toBe("0 claims");
  });
});

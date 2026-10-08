import { describe, it, expect } from "vitest";
import { agentSlug } from "./colony-registry";

describe("agentSlug", () => {
  it("returns the last segment of a POSIX path", () => {
    expect(agentSlug("exports/email_inbox_management")).toBe("email_inbox_management");
    expect(agentSlug("/Users/me/Hive/users/abc/colonies/credential-test")).toBe("credential-test");
  });

  it("returns the last segment of a Windows path (back-slashed)", () => {
    expect(
      agentSlug("C:\\Users\\jzhang\\AppData\\Roaming\\Hive\\users\\abc\\colonies\\credential-test"),
    ).toBe("credential-test");
  });

  it("ignores a trailing separator of either kind", () => {
    expect(agentSlug("a/b/c/")).toBe("c");
    expect(agentSlug("a\\b\\c\\")).toBe("c");
  });

  it("returns a bare slug unchanged", () => {
    expect(agentSlug("credential-test")).toBe("credential-test");
  });
});

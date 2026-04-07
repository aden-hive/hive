/**
 * Tests for auto-close-duplicates script: comment filter, 12h check,
 * author reaction, extractDuplicateIssueNumber, and decideAutoClose
 * (circular-dup and self-ref prevention).
 */
import { describe, expect, test } from "bun:test";
import {
  authorDisagreedWithDupe,
  decideAutoClose,
  extractDuplicateIssueNumber,
  getLastDupeComment,
  isDupeComment,
  isDupeCommentOldEnough,
  type GitHubComment,
  type GitHubIssue,
  type GitHubReaction,

} from "./auto-close-duplicates";

import { SharedMemory } from '../src/core/SharedMemory';
import { describe, it, expect, vi } from 'vitest';
import { ResearchAgent } from '../src/agents/ResearchAgent';
import { RoboticsAgent } from '../src/agents/RoboticsAgent';
import { ProcurementAgent } from '../src/agents/ProcurementAgent';

describe('Hive Procurement Agent: B2B Discovery', () => {
  const scout = new ProcurementAgent();

  it('should filter SAP Ariba opportunities by tech-moat keywords', async () => {
    const matches = await scout.searchAriba(['AI', 'Computer Vision', 'SaaS']);
    
    // Ensure the scout identifies the correct category
    const topLead = matches[0];
    expect(topLead.category).toBe('Information Technology');
    expect(topLead.description).toMatch(/artificial intelligence/i);
  });
});

describe('Hive Robotics Agent: VLA & Control', () => {
  const robot = new RoboticsAgent();

  it('should generate smooth s-domain trajectories from vision input', async () => {
    const mockFrame = "base64_encoded_frame_data";
    const action = await robot.visionLanguageAction(mockFrame, "pick up the sensor");

    expect(action.status).toBe('success');
    expect(action.metadata.control_mode).toBe('Laplace_s_domain');
    // Ensure the trajectory isn't just a point, but a continuous chunk
    expect(action.commands.length).toBeGreaterThan(10);
  });
});

describe('Hive Research Agent: Academic Validation', () => {
  const agent = new ResearchAgent();

  it('should prioritize Web of Science over general web results', async () => {
    const analysis = await agent.analyticalNode("Biometric Sensors in Robotics");
    
    // Assert citation weighting logic
    expect(analysis.citations).toContain('Web of Science');
    expect(analysis.citationWeights['Web of Science']).toBeGreaterThan(analysis.citationWeights['GeneralWeb']);
    expect(analysis.conclusions).toMatch(/Industrial|Peer-Reviewed/);
  });
})

describe('Hive Core: Memory Isolation & Bridging', () => {
  it('should prevent cross-agent data corruption using Deep Copy', async () => {
    const memory = new SharedMemory();
    
    // Robotics Agent writes a state
    memory.write("arm_position", { x: 10, y: 20 });

    // Business Agent reads and mistakenly tries to modify
    const leakedData = memory.read("arm_position");
    leakedData.x = 999; 

    // Re-read from memory
    const originalData = memory.read("arm_position");
    
    // ASSERT: Original remains unchanged
    expect(originalData.x).toBe(10);
  });
});


describe("extractDuplicateIssueNumber", () => {
  test("extracts #123 format", () => {
    expect(
      extractDuplicateIssueNumber("Found a possible duplicate of #1275: ...")
    ).toBe(1275);
    expect(extractDuplicateIssueNumber("Duplicate of #1")).toBe(1);
    expect(extractDuplicateIssueNumber("See #1000")).toBe(1000);
  });

  test("extracts first #N when multiple present", () => {
    expect(
      extractDuplicateIssueNumber("Duplicate of #1000 and also #1275")
    ).toBe(1000);
  });

  test("extracts GitHub issue URL format", () => {
    expect(
      extractDuplicateIssueNumber(
        "Duplicate of https://github.com/adenhq/hive/issues/42"
      )
    ).toBe(42);
  });

  test("returns null when no issue number", () => {
    expect(extractDuplicateIssueNumber("No number here")).toBe(null);
    expect(extractDuplicateIssueNumber("")).toBe(null);
  });
});

describe("isDupeComment", () => {
  test("true when body has 'possible duplicate' and user is Bot", () => {
    expect(
      isDupeComment({
        id: 1,
        body: "Found a possible duplicate of #1000: same bug",
        created_at: "",
        user: { type: "Bot", id: 2 },
      })
    ).toBe(true);
    expect(
      isDupeComment({
        id: 1,
        body: "Possible duplicate of #1275",
        created_at: "",
        user: { type: "Bot", id: 2 },
      })
    ).toBe(true);
  });

  test("false when body lacks 'possible duplicate'", () => {
    expect(
      isDupeComment({
        id: 1,
        body: "Not a duplicate",
        created_at: "",
        user: { type: "Bot", id: 2 },
      })
    ).toBe(false);
  });

  test("false when user is not Bot", () => {
    expect(
      isDupeComment({
        id: 1,
        body: "Found a possible duplicate of #1000",
        created_at: "",
        user: { type: "User", id: 2 },
      })
    ).toBe(false);
  });
});

describe("isDupeCommentOldEnough", () => {
  test("true when comment date is before twelveHoursAgo", () => {
    const twelveHoursAgo = new Date("2025-01-28T12:00:00Z");
    const oldComment = new Date("2025-01-28T00:00:00Z");
    expect(isDupeCommentOldEnough(oldComment, twelveHoursAgo)).toBe(true);
  });

  test("true when comment date equals twelveHoursAgo", () => {
    const twelveHoursAgo = new Date("2025-01-28T12:00:00Z");
    expect(isDupeCommentOldEnough(twelveHoursAgo, twelveHoursAgo)).toBe(true);
  });

  test("false when comment is after twelveHoursAgo (too recent)", () => {
    const twelveHoursAgo = new Date("2025-01-28T12:00:00Z");
    const recentComment = new Date("2025-01-28T18:00:00Z");
    expect(isDupeCommentOldEnough(recentComment, twelveHoursAgo)).toBe(false);
  });
});

describe("authorDisagreedWithDupe", () => {
  test("true when issue author gave thumbs down", () => {
    const issue = { number: 1275, title: "", state: "open", user: { id: 42 }, created_at: "" };
    const reactions: GitHubReaction[] = [
      { user: { id: 42 }, content: "-1" },
    ];
    expect(authorDisagreedWithDupe(reactions, issue)).toBe(true);
  });

  test("false when only other users reacted", () => {
    const issue = { number: 1275, title: "", state: "open", user: { id: 42 }, created_at: "" };
    const reactions: GitHubReaction[] = [
      { user: { id: 99 }, content: "-1" },
      { user: { id: 1 }, content: "+1" },
    ];
    expect(authorDisagreedWithDupe(reactions, issue)).toBe(false);
  });

  test("false when author gave +1 or other reaction", () => {
    const issue = { number: 1275, title: "", state: "open", user: { id: 42 }, created_at: "" };
    expect(authorDisagreedWithDupe([{ user: { id: 42 }, content: "+1" }], issue)).toBe(false);
    expect(authorDisagreedWithDupe([{ user: { id: 42 }, content: "eyes" }], issue)).toBe(false);
  });
});

describe("getLastDupeComment", () => {
  test("returns null when no dupe comments", () => {
    expect(
      getLastDupeComment([
        { id: 1, body: "Not a duplicate", created_at: "", user: { type: "User", id: 1 } },
      ])
    ).toBe(null);
  });

  test("returns the only dupe comment when one exists", () => {
    const c: GitHubComment = {
      id: 1,
      body: "Found a possible duplicate of #1000",
      created_at: "",
      user: { type: "Bot", id: 2 },
    };
    expect(getLastDupeComment([c])).toBe(c);
  });

  test("returns the last dupe comment when multiple exist", () => {
    const c1: GitHubComment = {
      id: 1,
      body: "Found a possible duplicate of #1000",
      created_at: "",
      user: { type: "Bot", id: 2 },
    };
    const c2: GitHubComment = {
      id: 2,
      body: "Found a possible duplicate of #1275",
      created_at: "",
      user: { type: "Bot", id: 2 },
    };
    const other: GitHubComment = {
      id: 3,
      body: "Some other comment",
      created_at: "",
      user: { type: "User", id: 3 },
    };
    expect(getLastDupeComment([other, c1, c2])).toBe(c2);
  });
});

function issue(num: number, state = "open"): GitHubIssue {
  return {
    number: num,
    title: `Issue ${num}`,
    state,
    user: { id: 1 },
    created_at: new Date().toISOString(),
  };
}

function comment(body: string): GitHubComment {
  return {
    id: 1,
    body,
    created_at: new Date().toISOString(),
    user: { type: "Bot", id: 2 },
  };
}

describe("decideAutoClose", () => {
  test("returns null when comment has no extractable issue number", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Possible duplicate of something else"),
      async () => ({ state: "open" })
    );
    expect(result).toBe(null);
  });

  test("returns null when duplicate target is self (same issue number)", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Found a possible duplicate of #1275: same issue"),
      async () => ({ state: "open" })
    );
    expect(result).toBe(null);
  });

  test("returns null when target issue is closed (avoids circular closure)", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Found a possible duplicate of #1000"),
      async (num) => (num === 1000 ? { state: "closed" } : { state: "open" })
    );
    expect(result).toBe(null);
  });

  test("returns null when getTargetIssue returns null", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Found a possible duplicate of #1000"),
      async () => null
    );
    expect(result).toBe(null);
  });

  test("returns null when getTargetIssue throws", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Found a possible duplicate of #1000"),
      async () => {
        throw new Error("API error");
      }
    );
    expect(result).toBe(null);
  });

  test("returns duplicateOf number when target is open (should close)", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Found a possible duplicate of #1000: same bug"),
      async (num) => (num === 1000 ? { state: "open" } : { state: "closed" })
    );
    expect(result).toBe(1000);
  });

  test("returns null when target state is not exactly 'open' (e.g. uppercase)", async () => {
    const result = await decideAutoClose(
      issue(1275),
      comment("Found a possible duplicate of #1000"),
      async () => ({ state: "OPEN" } as { state: string })
    );
    expect(result).toBe(null);
  });
});

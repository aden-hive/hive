import { beforeEach, describe, expect, it } from "vitest";
import {
  clearDismissedQuestions,
  isQuestionSetDismissed,
  rememberDismissedQuestions,
} from "./pending-question-dismissal";

const colorQuestion = {
  id: "q-color",
  prompt: "Which color do you prefer?",
  options: ["Red", "Blue"],
};
const sizeQuestion = { id: "q-size", prompt: "Which size?", options: ["S", "M"] };

describe("pending question dismissal", () => {
  beforeEach(() => {
    clearDismissedQuestions("session-a");
    clearDismissedQuestions("session-b");
  });

  it("keeps the same question ids hidden after dismissal", () => {
    rememberDismissedQuestions("session-a", [colorQuestion]);
    expect(isQuestionSetDismissed("session-a", [colorQuestion])).toBe(true);
  });

  it("shows a different question set and replaces the old record", () => {
    rememberDismissedQuestions("session-a", [colorQuestion]);
    expect(isQuestionSetDismissed("session-a", [sizeQuestion])).toBe(false);
    rememberDismissedQuestions("session-a", [sizeQuestion]);
    expect(isQuestionSetDismissed("session-a", [colorQuestion])).toBe(false);
    expect(isQuestionSetDismissed("session-a", [sizeQuestion])).toBe(true);
  });

  it("forgets the record after clear", () => {
    rememberDismissedQuestions("session-a", [colorQuestion]);
    clearDismissedQuestions("session-a");
    expect(isQuestionSetDismissed("session-a", [colorQuestion])).toBe(false);
  });

  it("keeps sessions independent", () => {
    rememberDismissedQuestions("session-a", [colorQuestion]);
    expect(isQuestionSetDismissed("session-b", [colorQuestion])).toBe(false);
  });

  it("matches a multi-question set regardless of order", () => {
    rememberDismissedQuestions("session-a", [colorQuestion, sizeQuestion]);
    expect(isQuestionSetDismissed("session-a", [sizeQuestion, colorQuestion])).toBe(true);
    expect(isQuestionSetDismissed("session-a", [colorQuestion])).toBe(false);
  });

  it("falls back to prompts when a question has no id", () => {
    const withoutId = { id: "", prompt: "Which color do you prefer?" };
    rememberDismissedQuestions("session-a", [withoutId]);
    expect(isQuestionSetDismissed("session-a", [{ ...withoutId }])).toBe(true);
    expect(isQuestionSetDismissed("session-a", [{ id: "", prompt: "Which size?" }])).toBe(false);
  });

  it("never treats an empty set or a missing session as dismissed", () => {
    rememberDismissedQuestions("session-a", [colorQuestion]);
    expect(isQuestionSetDismissed("session-a", [])).toBe(false);
    expect(isQuestionSetDismissed("session-a", null)).toBe(false);
    expect(isQuestionSetDismissed(null, [colorQuestion])).toBe(false);
  });
});

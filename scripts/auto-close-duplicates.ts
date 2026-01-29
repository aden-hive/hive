#!/usr/bin/env bun

declare global {
  var process: {
    env: Record<string, string | undefined>;
  };
}

export interface GitHubIssue {
  number: number;
  title: string;
  state: string;
  user: { id: number };
  created_at: string;
}

export interface GitHubComment {
  id: number;
  body: string;
  created_at: string;
  user: { type: string; id: number };
}

export interface GitHubReaction {
  user: { id: number };
  content: string;
}

async function githubRequest<T>(
  endpoint: string,
  token: string,
  method: string = "GET",
  body?: unknown
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github.v3+json",
    "User-Agent": "auto-close-duplicates-script",
  };

  if (body) {
    headers["Content-Type"] = "application/json";
  }

  const options: RequestInit = { method, headers };
  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(`https://api.github.com${endpoint}`, options);

  if (!response.ok) {
    throw new Error(
      `GitHub API request failed: ${response.status} ${response.statusText}`
    );
  }

  return response.json();
}

/** True if comment is a bot "possible duplicate" detection (used for filtering). */
export function isDupeComment(comment: GitHubComment): boolean {
  const bodyLower = comment.body.toLowerCase();
  return (
    bodyLower.includes("possible duplicate") && comment.user.type === "Bot"
  );
}

/** True if the duplicate comment is old enough to auto-close (>= 12h). */
export function isDupeCommentOldEnough(
  dupeCommentDate: Date,
  twelveHoursAgo: Date
): boolean {
  return dupeCommentDate <= twelveHoursAgo;
}

/** True if the issue author reacted with thumbs down to the duplicate comment. */
export function authorDisagreedWithDupe(
  reactions: GitHubReaction[],
  issue: GitHubIssue
): boolean {
  return reactions.some(
    (r) => r.user.id === issue.user.id && r.content === "-1"
  );
}

/** Returns the most recent duplicate-detection comment, or null if none. */
export function getLastDupeComment(
  comments: GitHubComment[]
): GitHubComment | null {
  const dupeComments = comments.filter(isDupeComment);
  return dupeComments.length > 0 ? dupeComments[dupeComments.length - 1]! : null;
}

export function extractDuplicateIssueNumber(commentBody: string): number | null {
  // Try to match #123 format first
  let match = commentBody.match(/#(\d+)/);
  if (match) {
    return parseInt(match[1], 10);
  }

  // Try to match GitHub issue URL format: https://github.com/owner/repo/issues/123
  match = commentBody.match(/github\.com\/[^\/]+\/[^\/]+\/issues\/(\d+)/);
  if (match) {
    return parseInt(match[1], 10);
  }

  return null;
}

/**
 * Decides whether to auto-close this issue as duplicate of another.
 * Returns the target issue number to close as duplicate of, or null to skip.
 * Used by the main loop and by tests.
 */
export async function decideAutoClose(
  issue: GitHubIssue,
  lastDupeComment: GitHubComment,
  getTargetIssue: (issueNumber: number) => Promise<{ state: string } | null>
): Promise<number | null> {
  const duplicateIssueNumber = extractDuplicateIssueNumber(lastDupeComment.body);
  if (duplicateIssueNumber === null) return null;

  if (duplicateIssueNumber === issue.number) return null;

  try {
    const targetIssue = await getTargetIssue(duplicateIssueNumber);
    if (!targetIssue || targetIssue.state !== "open") return null;
    return duplicateIssueNumber;
  } catch {
    return null;
  }
}

async function closeIssueAsDuplicate(
  owner: string,
  repo: string,
  issueNumber: number,
  duplicateOfNumber: number,
  token: string
): Promise<void> {
  await githubRequest(
    `/repos/${owner}/${repo}/issues/${issueNumber}`,
    token,
    "PATCH",
    {
      state: "closed",
      state_reason: "duplicate",
      labels: ["duplicate"],
    }
  );

  await githubRequest(
    `/repos/${owner}/${repo}/issues/${issueNumber}/comments`,
    token,
    "POST",
    {
      body: `This issue has been automatically closed as a duplicate of #${duplicateOfNumber}.

If this is incorrect, please re-open this issue or create a new one.`,
    }
  );
}

async function autoCloseDuplicates(): Promise<void> {
  console.log("[DEBUG] Starting auto-close duplicates script");

  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    throw new Error("GITHUB_TOKEN environment variable is required");
  }
  console.log("[DEBUG] GitHub token found");

  const owner = process.env.GITHUB_REPOSITORY_OWNER;
  const repo = process.env.GITHUB_REPOSITORY_NAME;
  if (!owner || !repo) {
    throw new Error(
      "GITHUB_REPOSITORY_OWNER and GITHUB_REPOSITORY_NAME environment variables are required"
    );
  }
  console.log(`[DEBUG] Repository: ${owner}/${repo}`);

  const twelveHoursAgo = new Date();
  twelveHoursAgo.setTime(twelveHoursAgo.getTime() - 12 * 60 * 60 * 1000);
  console.log(
    `[DEBUG] Checking for duplicate comments older than: ${twelveHoursAgo.toISOString()}`
  );

  console.log("[DEBUG] Fetching open issues created more than 12 hours ago...");
  const allIssues: GitHubIssue[] = [];
  let page = 1;
  const perPage = 100;

  while (true) {
    const pageIssues: GitHubIssue[] = await githubRequest(
      `/repos/${owner}/${repo}/issues?state=open&per_page=${perPage}&page=${page}`,
      token
    );

    if (pageIssues.length === 0) break;

    // Filter for issues created more than 12 hours ago
    const oldEnoughIssues = pageIssues.filter(
      (issue) => new Date(issue.created_at) <= twelveHoursAgo
    );

    allIssues.push(...oldEnoughIssues);
    page++;

    // Safety limit to avoid infinite loops
    if (page > 20) break;
  }

  const issues = allIssues;
  console.log(`[DEBUG] Found ${issues.length} open issues`);

  let processedCount = 0;
  let candidateCount = 0;

  for (const issue of issues) {
    processedCount++;
    console.log(
      `[DEBUG] Processing issue #${issue.number} (${processedCount}/${issues.length}): ${issue.title}`
    );

    console.log(`[DEBUG] Fetching comments for issue #${issue.number}...`);
    const comments: GitHubComment[] = await githubRequest(
      `/repos/${owner}/${repo}/issues/${issue.number}/comments`,
      token
    );
    console.log(
      `[DEBUG] Issue #${issue.number} has ${comments.length} comments`
    );

    const lastDupeComment = getLastDupeComment(comments);
    const dupeCount = comments.filter(isDupeComment).length;
    console.log(
      `[DEBUG] Issue #${issue.number} has ${dupeCount} duplicate detection comments`
    );

    if (lastDupeComment === null) {
      console.log(
        `[DEBUG] Issue #${issue.number} - no duplicate comments found, skipping`
      );
      continue;
    }
    const dupeCommentDate = new Date(lastDupeComment.created_at);
    console.log(
      `[DEBUG] Issue #${
        issue.number
      } - most recent duplicate comment from: ${dupeCommentDate.toISOString()}`
    );

    if (!isDupeCommentOldEnough(dupeCommentDate, twelveHoursAgo)) {
      console.log(
        `[DEBUG] Issue #${issue.number} - duplicate comment is too recent, skipping`
      );
      continue;
    }
    console.log(
      `[DEBUG] Issue #${
        issue.number
      } - duplicate comment is old enough (${Math.floor(
        (Date.now() - dupeCommentDate.getTime()) / (1000 * 60 * 60)
      )} hours)`
    );

    console.log(
      `[DEBUG] Issue #${issue.number} - checking reactions on duplicate comment...`
    );
    const reactions: GitHubReaction[] = await githubRequest(
      `/repos/${owner}/${repo}/issues/comments/${lastDupeComment.id}/reactions`,
      token
    );
    console.log(
      `[DEBUG] Issue #${issue.number} - duplicate comment has ${reactions.length} reactions`
    );

    const authorThumbsDown = authorDisagreedWithDupe(reactions, issue);
    console.log(
      `[DEBUG] Issue #${issue.number} - author thumbs down reaction: ${authorThumbsDown}`
    );

    if (authorThumbsDown) {
      console.log(
        `[DEBUG] Issue #${issue.number} - author disagreed with duplicate detection, skipping`
      );
      continue;
    }

    const duplicateOf = await decideAutoClose(
      issue,
      lastDupeComment,
      (issueNumber) =>
        githubRequest<GitHubIssue>(
          `/repos/${owner}/${repo}/issues/${issueNumber}`,
          token
        ).then((i) => ({ state: i.state }))
    );

    if (duplicateOf === null) {
      console.log(
        `[DEBUG] Issue #${issue.number} - skipping (invalid/self/closed target or fetch error)`
      );
      continue;
    }

    candidateCount++;
    const issueUrl = `https://github.com/${owner}/${repo}/issues/${issue.number}`;

    try {
      console.log(
        `[INFO] Auto-closing issue #${issue.number} as duplicate of #${duplicateOf}: ${issueUrl}`
      );
      await closeIssueAsDuplicate(
        owner,
        repo,
        issue.number,
        duplicateOf,
        token
      );
      console.log(
        `[SUCCESS] Successfully closed issue #${issue.number} as duplicate of #${duplicateOf}`
      );
    } catch (error) {
      console.error(
        `[ERROR] Failed to close issue #${issue.number} as duplicate: ${error}`
      );
    }
  }

  console.log(
    `[DEBUG] Script completed. Processed ${processedCount} issues, found ${candidateCount} candidates for auto-close`
  );
}

if (import.meta.main) {
  autoCloseDuplicates().catch(console.error);
}

export {};

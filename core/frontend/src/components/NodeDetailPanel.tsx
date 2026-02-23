import { useState, useEffect, useRef } from "react";
import { X, Cpu, Zap, Clock, RotateCcw, CheckCircle2, AlertCircle, Loader2, ChevronDown, ChevronRight, Copy, Check, Terminal, Wrench, BookOpen, GitBranch, Bot } from "lucide-react";
import type { GraphNode, NodeStatus } from "./AgentGraph";

interface Tool {
  name: string;
  description: string;
  icon: string;
  credentials?: ToolCredential[];
}

interface ToolCredential {
  key: string;
  label: string;
  connected: boolean;
  value?: string;
}

interface NodeDetailPanelProps {
  node: GraphNode | null;
  onClose: () => void;
}

const statusConfig: Record<NodeStatus, { label: string; color: string; Icon: React.FC<{ className?: string }> }> = {
  running: { label: "Running", color: "hsl(45,95%,58%)", Icon: ({ className }) => <Loader2 className={`${className} animate-spin`} /> },
  looping: { label: "Looping", color: "hsl(38,90%,55%)", Icon: ({ className }) => <RotateCcw className={`${className} animate-spin`} style={{ animationDuration: "2s" }} /> },
  complete: { label: "Complete", color: "hsl(43,70%,45%)", Icon: ({ className }) => <CheckCircle2 className={className} /> },
  pending: { label: "Pending", color: "hsl(220,15%,45%)", Icon: ({ className }) => <Clock className={className} /> },
  error: { label: "Error", color: "hsl(0,65%,55%)", Icon: ({ className }) => <AlertCircle className={className} /> },
};

// -- Subgraph types --
type SGCol = "left" | "center" | "right";
type SGType = "step" | "decision" | "tool";

interface SGNode {
  id: string;
  label: string;
  type: SGType;
  col: SGCol;
  row: number;
  tRow?: number;
  done: boolean;
}

interface SGEdge {
  from: string;
  to: string;
  label?: string;
  dashed?: boolean;
  done: boolean;
  fromPort?: "bottom" | "right" | "left" | "top";
  toPort?: "top" | "left" | "right" | "bottom";
}

interface SGDef { nodes: SGNode[]; edges: SGEdge[]; }

const SG_COL: Record<SGCol, number> = { left: 16, center: 156, right: 300 };
const SG_ROW_H = 80;
const SG_STEP_W = 130; const SG_STEP_H = 34;
const SG_TOOL_W = 118; const SG_TOOL_H = 28;
const SG_SVG_W = 440;

function sgNodePos(n: SGNode) {
  const isTool = n.type === "tool";
  const w = isTool ? SG_TOOL_W : SG_STEP_W;
  const h = isTool ? SG_TOOL_H : SG_STEP_H;
  const row = n.tRow !== undefined ? n.tRow : n.row;
  return { x: SG_COL[n.col], y: row * SG_ROW_H + (isTool ? (SG_STEP_H - SG_TOOL_H) / 2 : 0), w, h };
}

function sgPort(pos: { x: number; y: number; w: number; h: number }, port: string): [number, number] {
  if (port === "top")    return [pos.x + pos.w / 2, pos.y];
  if (port === "bottom") return [pos.x + pos.w / 2, pos.y + pos.h];
  if (port === "left")   return [pos.x, pos.y + pos.h / 2];
  return [pos.x + pos.w, pos.y + pos.h / 2]; // right
}

const sgDefs: Record<string, SGDef> = {
  "fetch-mail": {
    nodes: [
      { id: "auth",    label: "Auth OAuth",      type: "step",     col: "center", row: 0, done: true },
      { id: "gmail",   label: "Gmail API",        type: "tool",     col: "right",  row: 0, tRow: 0, done: true },
      { id: "fetch",   label: "Fetch Unread",     type: "step",     col: "center", row: 1, done: true },
      { id: "found_q", label: "Messages found?",  type: "decision", col: "center", row: 2, done: true },
      { id: "filter",  label: "Apply Filters",    type: "step",     col: "left",   row: 3, done: true },
      { id: "empty",   label: "Return Empty",     type: "step",     col: "right",  row: 3, done: false },
      { id: "emit",    label: "Emit Batch",       type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "auth",    to: "gmail",   dashed: true, done: true,  fromPort: "right",  toPort: "left" },
      { from: "auth",    to: "fetch",   done: true },
      { from: "fetch",   to: "found_q", done: true },
      { from: "found_q", to: "filter",  label: "Match",  done: true,  fromPort: "bottom", toPort: "top" },
      { from: "found_q", to: "empty",   label: "Empty",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "filter",  to: "emit",    done: false, fromPort: "bottom", toPort: "left" },
      { from: "empty",   to: "emit",    done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "classify": {
    nodes: [
      { id: "tokenize", label: "Tokenize Content", type: "step",     col: "center", row: 0, done: true },
      { id: "gpt",      label: "GPT-4o",           type: "tool",     col: "right",  row: 1, tRow: 1, done: true },
      { id: "classify", label: "GPT-4o Classify",  type: "step",     col: "center", row: 1, done: true },
      { id: "cat_q",    label: "Category?",        type: "decision", col: "center", row: 2, done: false },
      { id: "spam",     label: "Flag Spam",        type: "step",     col: "left",   row: 3, done: false },
      { id: "score",    label: "Score Sentiment",  type: "step",     col: "right",  row: 3, done: false },
      { id: "emit",     label: "Emit Categories",  type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "tokenize", to: "classify", done: true },
      { from: "classify",  to: "gpt",    dashed: true, done: true,  fromPort: "right",  toPort: "left" },
      { from: "classify",  to: "cat_q",  done: false },
      { from: "cat_q",    to: "spam",   label: "Spam",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "cat_q",    to: "score",  label: "Valid", done: false, fromPort: "bottom", toPort: "top" },
      { from: "spam",     to: "emit",   done: false, fromPort: "bottom", toPort: "left" },
      { from: "score",    to: "emit",   done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "prioritize": {
    nodes: [
      { id: "score",   label: "Score Urgency",    type: "step",     col: "center", row: 0, done: false },
      { id: "gcal",    label: "Google Calendar",  type: "tool",     col: "right",  row: 1, tRow: 1, done: false },
      { id: "cal",     label: "Check Calendar",   type: "step",     col: "center", row: 1, done: false },
      { id: "vip_q",   label: "VIP sender?",      type: "decision", col: "center", row: 2, done: false },
      { id: "boost",   label: "Boost Priority",   type: "step",     col: "left",   row: 3, done: false },
      { id: "normal",  label: "Normal Priority",  type: "step",     col: "right",  row: 3, done: false },
      { id: "emit",    label: "Emit Ranked List", type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "score", to: "cal",    done: false },
      { from: "cal",   to: "gcal",   dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "cal",   to: "vip_q",  done: false },
      { from: "vip_q", to: "boost",  label: "VIP",    done: false, fromPort: "bottom", toPort: "top" },
      { from: "vip_q", to: "normal", label: "Normal", done: false, fromPort: "bottom", toPort: "top" },
      { from: "boost",  to: "emit",  done: false, fromPort: "bottom", toPort: "left" },
      { from: "normal", to: "emit",  done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "draft-replies": {
    nodes: [
      { id: "context",   label: "Build Context",   type: "step",     col: "center", row: 0, done: false },
      { id: "gpt",       label: "GPT-4o Writer",   type: "tool",     col: "right",  row: 1, tRow: 1, done: false },
      { id: "generate",  label: "Generate Draft",  type: "step",     col: "center", row: 1, done: false },
      { id: "approve_q", label: "Auto-approve?",   type: "decision", col: "center", row: 2, done: false },
      { id: "send",      label: "Auto-send",       type: "step",     col: "left",   row: 3, done: false },
      { id: "flag",      label: "Flag for Review", type: "step",     col: "right",  row: 3, done: false },
      { id: "emit",      label: "Emit Drafts",     type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "context",   to: "generate",  done: false },
      { from: "generate",  to: "gpt",       dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "generate",  to: "approve_q", done: false },
      { from: "approve_q", to: "send",  label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
      { from: "approve_q", to: "flag",  label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "send", to: "emit", done: false, fromPort: "bottom", toPort: "left" },
      { from: "flag", to: "emit", done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "send-or-archive": {
    nodes: [
      { id: "review",  label: "Review Drafts",    type: "step",     col: "center", row: 0, done: false },
      { id: "smtp",    label: "Gmail Send",        type: "tool",     col: "right",  row: 1, tRow: 1, done: false },
      { id: "send_q",  label: "Approved?",         type: "decision", col: "center", row: 1, done: false },
      { id: "send",    label: "Send Reply",        type: "step",     col: "left",   row: 2, done: false },
      { id: "archive", label: "Archive Email",     type: "step",     col: "right",  row: 2, done: false },
      { id: "retry_q", label: "Send ok?",          type: "decision", col: "left",   row: 3, done: false },
      { id: "notify",  label: "Notify Webhook",    type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "review",  to: "send_q",  done: false },
      { from: "send_q",  to: "send",    label: "Yes",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "send_q",  to: "archive", label: "Skip", done: false, fromPort: "bottom", toPort: "top" },
      { from: "send",    to: "smtp",    dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "send",    to: "retry_q", done: false },
      { from: "retry_q", to: "notify",  label: "OK",   done: false, fromPort: "bottom", toPort: "left" },
      { from: "archive", to: "notify",  done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "intake": {
    nodes: [
      { id: "parse",    label: "Parse Input",      type: "step",     col: "center", row: 0, done: true },
      { id: "valid_q",  label: "Fields valid?",    type: "decision", col: "center", row: 1, done: true },
      { id: "validate", label: "Validate Fields",  type: "step",     col: "left",   row: 2, done: true },
      { id: "reject",   label: "Return Error",     type: "step",     col: "right",  row: 2, done: false },
      { id: "context",  label: "Build Context",    type: "step",     col: "center", row: 3, done: true },
      { id: "emit",     label: "Emit to Pipeline", type: "step",     col: "center", row: 4, done: true },
    ],
    edges: [
      { from: "parse",    to: "valid_q",  done: true },
      { from: "valid_q",  to: "validate", label: "Pass", done: true,  fromPort: "bottom", toPort: "top" },
      { from: "valid_q",  to: "reject",   label: "Fail", done: false, fromPort: "bottom", toPort: "top" },
      { from: "validate", to: "context",  done: true, fromPort: "bottom", toPort: "left" },
      { from: "context",  to: "emit",     done: true },
    ],
  },
  "job-search": {
    nodes: [
      { id: "linkedin", label: "LinkedIn Search",  type: "step",     col: "left",   row: 0, done: true },
      { id: "indeed",   label: "Indeed Query",     type: "step",     col: "center", row: 0, done: true },
      { id: "glass",    label: "Glassdoor Fetch",  type: "step",     col: "right",  row: 0, done: true },
      { id: "dedup",    label: "Deduplicate",      type: "step",     col: "center", row: 1, done: true },
      { id: "match_q",  label: "Match > 60%?",     type: "decision", col: "center", row: 2, done: true },
      { id: "keep",     label: "Keep Result",      type: "step",     col: "left",   row: 3, done: true },
      { id: "discard",  label: "Discard",          type: "step",     col: "right",  row: 3, done: false },
      { id: "emit",     label: "Emit Job List",    type: "step",     col: "center", row: 4, done: true },
    ],
    edges: [
      { from: "linkedin", to: "dedup",   done: true, fromPort: "bottom", toPort: "left" },
      { from: "indeed",   to: "dedup",   done: true },
      { from: "glass",    to: "dedup",   done: true, fromPort: "bottom", toPort: "right" },
      { from: "dedup",    to: "match_q", done: true },
      { from: "match_q",  to: "keep",    label: "Yes", done: true,  fromPort: "bottom", toPort: "top" },
      { from: "match_q",  to: "discard", label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "keep",     to: "emit",    done: true, fromPort: "bottom", toPort: "left" },
    ],
  },
  "job-review": {
    nodes: [
      { id: "match",    label: "Match Score",      type: "step",     col: "center", row: 0, done: true },
      { id: "gpt",      label: "GPT-4o Analyser",  type: "tool",     col: "right",  row: 0, tRow: 0, done: true },
      { id: "thresh_q", label: "> 90% match?",     type: "decision", col: "center", row: 1, done: true },
      { id: "auto",     label: "Flag Auto-Apply",  type: "step",     col: "left",   row: 2, done: true },
      { id: "manual",   label: "Flag Manual",      type: "step",     col: "right",  row: 2, done: true },
      { id: "salary",   label: "Salary Benchmark", type: "step",     col: "center", row: 3, done: true },
      { id: "emit",     label: "Emit Reviewed",    type: "step",     col: "center", row: 4, done: true },
    ],
    edges: [
      { from: "match",    to: "gpt",     dashed: true, done: true, fromPort: "right", toPort: "left" },
      { from: "match",    to: "thresh_q", done: true },
      { from: "thresh_q", to: "auto",    label: "Yes", done: true, fromPort: "bottom", toPort: "top" },
      { from: "thresh_q", to: "manual",  label: "No",  done: true, fromPort: "bottom", toPort: "top" },
      { from: "auto",    to: "salary",   done: true, fromPort: "bottom", toPort: "left" },
      { from: "manual",  to: "salary",   done: true, fromPort: "bottom", toPort: "right" },
      { from: "salary",  to: "emit",     done: true },
    ],
  },
  "customize": {
    nodes: [
      { id: "tailor",   label: "Tailor Resume",    type: "step",     col: "center", row: 0, done: true },
      { id: "gpt",      label: "GPT-4o",           type: "tool",     col: "right",  row: 0, tRow: 0, done: true },
      { id: "cover",    label: "Cover Letter",     type: "step",     col: "center", row: 1, done: true },
      { id: "portal_q", label: "Portal available?",type: "decision", col: "center", row: 2, done: true },
      { id: "api",      label: "Submit via API",   type: "step",     col: "left",   row: 3, done: true },
      { id: "form",     label: "Submit via Form",  type: "step",     col: "right",  row: 3, done: false },
      { id: "confirm",  label: "Confirm & Log",    type: "step",     col: "center", row: 4, done: true },
    ],
    edges: [
      { from: "tailor",   to: "gpt",      dashed: true, done: true, fromPort: "right", toPort: "left" },
      { from: "tailor",   to: "cover",    done: true },
      { from: "cover",    to: "portal_q", done: true },
      { from: "portal_q", to: "api",      label: "Yes", done: true,  fromPort: "bottom", toPort: "top" },
      { from: "portal_q", to: "form",     label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "api",      to: "confirm",  done: true,  fromPort: "bottom", toPort: "left" },
      { from: "form",     to: "confirm",  done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "coach": {
    nodes: [
      { id: "hrv",    label: "Check HRV",           type: "step",     col: "center", row: 0, done: true },
      { id: "hrv_q",  label: "HRV normal?",         type: "decision", col: "center", row: 1, done: true },
      { id: "plan",   label: "Full Plan",           type: "step",     col: "left",   row: 2, done: true },
      { id: "reduce", label: "Reduce Intensity",    type: "step",     col: "right",  row: 2, done: false },
      { id: "gpt",    label: "GPT-4o Plan Gen",     type: "tool",     col: "right",  row: 3, tRow: 2, done: false },
      { id: "log",    label: "Log Progress",        type: "step",     col: "center", row: 3, done: false },
      { id: "emit",   label: "Emit to Meal/Remind", type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "hrv",   to: "hrv_q",   done: true },
      { from: "hrv_q", to: "plan",    label: "OK",  done: true,  fromPort: "bottom", toPort: "top" },
      { from: "hrv_q", to: "reduce",  label: "Low", done: false, fromPort: "bottom", toPort: "top" },
      { from: "plan",  to: "gpt",     dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "plan",  to: "log",     done: false, fromPort: "bottom", toPort: "left" },
      { from: "reduce",to: "log",     done: false, fromPort: "bottom", toPort: "right" },
      { from: "log",   to: "emit",    done: false },
    ],
  },
  "meal-checkin": {
    nodes: [
      { id: "log",      label: "Log Meal",          type: "step",     col: "center", row: 0, done: false },
      { id: "macro",    label: "Calc Macros",       type: "step",     col: "center", row: 1, done: false },
      { id: "target_q", label: "On track?",         type: "decision", col: "center", row: 2, done: false },
      { id: "suggest",  label: "Suggest Recipe",    type: "step",     col: "left",   row: 3, done: false },
      { id: "alert",    label: "Alert Coach",       type: "step",     col: "right",  row: 3, done: false },
      { id: "emit",     label: "Emit Summary",      type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "log",      to: "macro",    done: false },
      { from: "macro",    to: "target_q", done: false },
      { from: "target_q", to: "suggest",  label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
      { from: "target_q", to: "alert",    label: "Off", done: false, fromPort: "bottom", toPort: "top" },
      { from: "suggest",  to: "emit",     done: false, fromPort: "bottom", toPort: "left" },
      { from: "alert",    to: "emit",     done: false, fromPort: "bottom", toPort: "right" },
    ],
  },
  "exercise-reminder": {
    nodes: [
      { id: "check",  label: "Check Schedule",     type: "step",     col: "center", row: 0, done: false },
      { id: "due_q",  label: "Session due?",       type: "decision", col: "center", row: 1, done: false },
      { id: "remind", label: "Send Reminder",      type: "step",     col: "left",   row: 2, done: false },
      { id: "skip",   label: "Rest Day",           type: "step",     col: "right",  row: 2, done: false },
      { id: "done_q", label: "Completed?",         type: "decision", col: "left",   row: 3, done: false },
      { id: "streak", label: "Update Streak",      type: "step",     col: "left",   row: 4, done: false },
      { id: "flag",   label: "Flag Missed",        type: "step",     col: "right",  row: 4, done: false },
    ],
    edges: [
      { from: "check",  to: "due_q",  done: false },
      { from: "due_q",  to: "remind", label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
      { from: "due_q",  to: "skip",   label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "remind", to: "done_q", done: false },
      { from: "done_q", to: "streak", label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
      { from: "done_q", to: "flag",   label: "No",  done: false, fromPort: "bottom", toPort: "top" },
    ],
  },
  "passive-recon": {
    nodes: [
      { id: "dns",      label: "DNS Enum",          type: "step",     col: "left",   row: 0, done: true },
      { id: "cert",     label: "Cert Transparency", type: "step",     col: "center", row: 0, done: true },
      { id: "whois",    label: "WHOIS Lookup",      type: "step",     col: "right",  row: 0, done: true },
      { id: "merge",    label: "Merge Subdomains",  type: "step",     col: "center", row: 1, done: true },
      { id: "port",     label: "Port Scan",         type: "step",     col: "center", row: 2, done: true },
      { id: "dirlist_q",label: "Dir listing?",      type: "decision", col: "center", row: 3, done: true },
      { id: "flag",     label: "Flag Critical",     type: "step",     col: "left",   row: 4, done: true },
      { id: "emit",     label: "Emit Recon Report", type: "step",     col: "center", row: 4, done: true },
    ],
    edges: [
      { from: "dns",      to: "merge",    done: true, fromPort: "bottom", toPort: "left" },
      { from: "cert",     to: "merge",    done: true },
      { from: "whois",    to: "merge",    done: true, fromPort: "bottom", toPort: "right" },
      { from: "merge",    to: "port",     done: true },
      { from: "port",     to: "dirlist_q",done: true },
      { from: "dirlist_q",to: "flag",     label: "Yes",   done: true, fromPort: "bottom", toPort: "top" },
      { from: "dirlist_q",to: "emit",     label: "Clean", done: true, fromPort: "bottom", toPort: "right" },
      { from: "flag",     to: "emit",     done: true, fromPort: "right", toPort: "left" },
    ],
  },
  "risk-scoring": {
    nodes: [
      { id: "cvss",    label: "CVSS Score",         type: "step",     col: "center", row: 0, done: true },
      { id: "nvd",     label: "NVD CVE DB",         type: "tool",     col: "right",  row: 0, tRow: 0, done: true },
      { id: "crit_q",  label: "Score \u2265 9?",    type: "decision", col: "center", row: 1, done: true },
      { id: "critical",label: "Mark Critical",      type: "step",     col: "left",   row: 2, done: true },
      { id: "medium",  label: "Mark Med/Low",       type: "step",     col: "right",  row: 2, done: true },
      { id: "map",     label: "Map Attack Surface", type: "step",     col: "center", row: 3, done: true },
      { id: "emit",    label: "Emit Risk Scores",   type: "step",     col: "center", row: 4, done: true },
    ],
    edges: [
      { from: "cvss",    to: "nvd",      dashed: true, done: true, fromPort: "right", toPort: "left" },
      { from: "cvss",    to: "crit_q",   done: true },
      { from: "crit_q",  to: "critical", label: "Crit", done: true, fromPort: "bottom", toPort: "top" },
      { from: "crit_q",  to: "medium",   label: "Low",  done: true, fromPort: "bottom", toPort: "top" },
      { from: "critical",to: "map",      done: true, fromPort: "bottom", toPort: "left" },
      { from: "medium",  to: "map",      done: true, fromPort: "bottom", toPort: "right" },
      { from: "map",     to: "emit",     done: true },
    ],
  },
  "findings-review": {
    nodes: [
      { id: "sort",   label: "Sort by Severity",   type: "step",     col: "center", row: 0, done: true },
      { id: "fp_q",   label: "False positive?",    type: "decision", col: "center", row: 1, done: true },
      { id: "remove", label: "Remove Finding",     type: "step",     col: "right",  row: 2, done: false },
      { id: "poc",    label: "Capture PoC",        type: "step",     col: "left",   row: 2, done: false },
      { id: "triage", label: "Triage Engine",      type: "tool",     col: "right",  row: 2, tRow: 2, done: false },
      { id: "curate", label: "Curate Findings",    type: "step",     col: "center", row: 3, done: false },
      { id: "emit",   label: "Emit Final List",    type: "step",     col: "center", row: 4, done: false },
    ],
    edges: [
      { from: "sort",   to: "fp_q",   done: true },
      { from: "fp_q",   to: "remove", label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
      { from: "fp_q",   to: "poc",    label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "poc",    to: "triage", dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "poc",    to: "curate", done: false, fromPort: "bottom", toPort: "left" },
      { from: "remove", to: "curate", done: false, fromPort: "bottom", toPort: "right" },
      { from: "curate", to: "emit",   done: false },
    ],
  },
  "final-report": {
    nodes: [
      { id: "build",   label: "Build Report",      type: "step",     col: "center", row: 0, done: false },
      { id: "gpt",     label: "GPT-4o Writer",     type: "tool",     col: "right",  row: 0, tRow: 0, done: false },
      { id: "exec",    label: "Exec Summary",      type: "step",     col: "left",   row: 1, done: false },
      { id: "matrix",  label: "Risk Matrix",       type: "step",     col: "right",  row: 1, done: false },
      { id: "tickets", label: "Create Tickets",    type: "step",     col: "center", row: 2, done: false },
      { id: "jira",    label: "Jira / Linear",     type: "tool",     col: "right",  row: 2, tRow: 2, done: false },
      { id: "deliver", label: "Deliver Report",    type: "step",     col: "center", row: 3, done: false },
    ],
    edges: [
      { from: "build",   to: "gpt",     dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "build",   to: "exec",    done: false, fromPort: "bottom", toPort: "top" },
      { from: "build",   to: "matrix",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "exec",    to: "tickets", done: false, fromPort: "bottom", toPort: "left" },
      { from: "matrix",  to: "tickets", done: false, fromPort: "bottom", toPort: "right" },
      { from: "tickets", to: "jira",    dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "tickets", to: "deliver", done: false },
    ],
  },
  "brief-intake": {
    nodes: [
      { id: "parse",    label: "Parse Brief",       type: "step",     col: "center", row: 0, done: true },
      { id: "valid_q",  label: "Brief complete?",   type: "decision", col: "center", row: 1, done: true },
      { id: "extract",  label: "Extract Reqs",      type: "step",     col: "left",   row: 2, done: true },
      { id: "reject",   label: "Request More Info", type: "step",     col: "right",  row: 2, done: false },
      { id: "emit",     label: "Emit Brief",        type: "step",     col: "center", row: 3, done: true },
    ],
    edges: [
      { from: "parse",   to: "valid_q",  done: true },
      { from: "valid_q", to: "extract",  label: "Yes", done: true,  fromPort: "bottom", toPort: "top" },
      { from: "valid_q", to: "reject",   label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "extract", to: "emit",     done: true, fromPort: "bottom", toPort: "left" },
    ],
  },
  "research": {
    nodes: [
      { id: "search",  label: "Web Search",        type: "step",     col: "center", row: 0, done: true },
      { id: "gpt",     label: "GPT-4o",            type: "tool",     col: "right",  row: 0, tRow: 0, done: true },
      { id: "collect", label: "Collect Sources",    type: "step",     col: "center", row: 1, done: true },
      { id: "analyze", label: "Analyze Gaps",       type: "step",     col: "center", row: 2, done: true },
      { id: "emit",    label: "Emit Research",      type: "step",     col: "center", row: 3, done: true },
    ],
    edges: [
      { from: "search",  to: "gpt",     dashed: true, done: true, fromPort: "right", toPort: "left" },
      { from: "search",  to: "collect", done: true },
      { from: "collect", to: "analyze", done: true },
      { from: "analyze", to: "emit",    done: true },
    ],
  },
  "outline": {
    nodes: [
      { id: "struct",  label: "Build Structure",   type: "step",     col: "center", row: 0, done: true },
      { id: "valid_q", label: "Covers brief?",     type: "decision", col: "center", row: 1, done: true },
      { id: "approve", label: "Approve Outline",   type: "step",     col: "left",   row: 2, done: true },
      { id: "revise",  label: "Revise Structure",  type: "step",     col: "right",  row: 2, done: false },
      { id: "emit",    label: "Emit Outline",      type: "step",     col: "center", row: 3, done: true },
    ],
    edges: [
      { from: "struct",  to: "valid_q", done: true },
      { from: "valid_q", to: "approve", label: "Yes", done: true,  fromPort: "bottom", toPort: "top" },
      { from: "valid_q", to: "revise",  label: "No",  done: false, fromPort: "bottom", toPort: "top" },
      { from: "approve", to: "emit",    done: true, fromPort: "bottom", toPort: "left" },
    ],
  },
  "draft": {
    nodes: [
      { id: "expand", label: "Expand Sections",    type: "step",     col: "center", row: 0, done: false },
      { id: "gpt",    label: "GPT-4o Writer",      type: "tool",     col: "right",  row: 0, tRow: 0, done: false },
      { id: "polish", label: "Polish Prose",        type: "step",     col: "center", row: 1, done: false },
      { id: "count",  label: "Check Word Count",   type: "step",     col: "center", row: 2, done: false },
      { id: "emit",   label: "Emit Draft",         type: "step",     col: "center", row: 3, done: false },
    ],
    edges: [
      { from: "expand", to: "gpt",    dashed: true, done: false, fromPort: "right", toPort: "left" },
      { from: "expand", to: "polish", done: false },
      { from: "polish", to: "count",  done: false },
      { from: "count",  to: "emit",   done: false },
    ],
  },
  "review": {
    nodes: [
      { id: "grammar", label: "Grammar Check",     type: "step",     col: "center", row: 0, done: false },
      { id: "plagiarism", label: "Plagiarism Scan", type: "step",     col: "center", row: 1, done: false },
      { id: "pass_q",  label: "Passes checks?",    type: "decision", col: "center", row: 2, done: false },
      { id: "publish", label: "Publish",            type: "step",     col: "left",   row: 3, done: false },
      { id: "revise",  label: "Send to Revise",    type: "step",     col: "right",  row: 3, done: false },
    ],
    edges: [
      { from: "grammar",    to: "plagiarism", done: false },
      { from: "plagiarism", to: "pass_q",     done: false },
      { from: "pass_q",     to: "publish",    label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
      { from: "pass_q",     to: "revise",     label: "No",  done: false, fromPort: "bottom", toPort: "top" },
    ],
  },
};

const defaultSGDef: SGDef = {
  nodes: [
    { id: "init",    label: "Initialise",   type: "step",     col: "center", row: 0, done: false },
    { id: "proc_q",  label: "Input valid?", type: "decision", col: "center", row: 1, done: false },
    { id: "process", label: "Process",      type: "step",     col: "left",   row: 2, done: false },
    { id: "error",   label: "Return Error", type: "step",     col: "right",  row: 2, done: false },
    { id: "emit",    label: "Emit Output",  type: "step",     col: "center", row: 3, done: false },
  ],
  edges: [
    { from: "init",    to: "proc_q",  done: false },
    { from: "proc_q",  to: "process", label: "Yes", done: false, fromPort: "bottom", toPort: "top" },
    { from: "proc_q",  to: "error",   label: "No",  done: false, fromPort: "bottom", toPort: "top" },
    { from: "process", to: "emit",    done: false, fromPort: "bottom", toPort: "left" },
  ],
};

// -- SubGraph renderer --
function SubGraph({ nodeId, status }: { nodeId: string; status: NodeStatus }) {
  const def = sgDefs[nodeId] || defaultSGDef;
  const color = statusConfig[status].color;

  const nodeMap: Record<string, SGNode> = {};
  def.nodes.forEach(n => { nodeMap[n.id] = n; });
  const posMap: Record<string, { x: number; y: number; w: number; h: number }> = {};
  def.nodes.forEach(n => { posMap[n.id] = sgNodePos(n); });

  const maxRow = Math.max(...def.nodes.map(n => (n.tRow !== undefined ? n.tRow : n.row)));
  const svgH = (maxRow + 1) * SG_ROW_H + SG_STEP_H + 16;

  const renderEdge = (edge: SGEdge, i: number) => {
    const fromNode = nodeMap[edge.from];
    const toNode = nodeMap[edge.to];
    if (!fromNode || !toNode) return null;
    const fp = posMap[edge.from];
    const tp = posMap[edge.to];
    const fromPortKey = edge.fromPort || "bottom";
    const toPortKey = edge.toPort || "top";
    const [fx, fy] = sgPort(fp, fromPortKey);
    const [tx, ty] = sgPort(tp, toPortKey);

    const stroke = edge.done ? `${color}55` : "hsl(35,10%,22%)";
    const arrowFill = edge.done ? `${color}70` : "hsl(35,10%,26%)";

    let d: string;
    if (fromPortKey === "right" && toPortKey === "left") {
      const midX = (fx + tx) / 2;
      d = `M ${fx} ${fy} C ${midX} ${fy}, ${midX} ${ty}, ${tx} ${ty}`;
    } else if (fromPortKey === "bottom" && toPortKey === "top") {
      if (Math.abs(tx - fx) < 10) {
        d = `M ${fx} ${fy} L ${tx} ${ty}`;
      } else {
        const cY = fy + (ty - fy) * 0.5;
        d = `M ${fx} ${fy} C ${fx} ${cY}, ${tx} ${cY}, ${tx} ${ty}`;
      }
    } else if (fromPortKey === "bottom" && toPortKey === "left") {
      d = `M ${fx} ${fy} C ${fx} ${fy + 20}, ${tx - 20} ${ty}, ${tx} ${ty}`;
    } else if (fromPortKey === "bottom" && toPortKey === "right") {
      d = `M ${fx} ${fy} C ${fx} ${fy + 20}, ${tx + 20} ${ty}, ${tx} ${ty}`;
    } else if (fromPortKey === "right" && toPortKey === "top") {
      d = `M ${fx} ${fy} C ${fx + 20} ${fy}, ${tx} ${ty - 20}, ${tx} ${ty}`;
    } else {
      const cX = (fx + tx) / 2;
      d = `M ${fx} ${fy} C ${cX} ${fy}, ${cX} ${ty}, ${tx} ${ty}`;
    }

    const A = 4.5;
    let arrowPoints = "";
    if (toPortKey === "top")    arrowPoints = `${tx - A},${ty + A * 1.4} ${tx + A},${ty + A * 1.4} ${tx},${ty + 1}`;
    else if (toPortKey === "left")  arrowPoints = `${tx + A * 1.4},${ty - A} ${tx + A * 1.4},${ty + A} ${tx + 1},${ty}`;
    else if (toPortKey === "right") arrowPoints = `${tx - A * 1.4},${ty - A} ${tx - A * 1.4},${ty + A} ${tx - 1},${ty}`;
    else arrowPoints = `${tx - A},${ty - A * 1.4} ${tx + A},${ty - A * 1.4} ${tx},${ty - 1}`;

    const midX = (fx + tx) / 2;
    const midY = (fy + ty) / 2;

    return (
      <g key={`e-${i}`}>
        <path d={d} fill="none" stroke={stroke} strokeWidth={1.5} strokeDasharray={edge.dashed ? "4 3" : "none"} />
        <polygon points={arrowPoints} fill={arrowFill} />
        {edge.label && (
          <text
            x={midX} y={midY - 4}
            fill={edge.done ? `${color}90` : "hsl(35,10%,36%)"}
            fontSize={8.5} textAnchor="middle" dominantBaseline="middle"
            style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
          >{edge.label}</text>
        )}
      </g>
    );
  };

  const renderNode = (n: SGNode) => {
    const pos = posMap[n.id];
    const isTool = n.type === "tool";
    const isDecision = n.type === "decision";

    const bgFill = n.done ? `${color}14` : isTool ? "hsl(220,15%,10%)" : "hsl(35,10%,11%)";
    const borderStroke = n.done ? `${color}45` : isTool ? "hsl(220,25%,28%)" : isDecision ? "hsl(35,15%,26%)" : "hsl(35,10%,19%)";
    const textFill = n.done ? "hsl(40,20%,72%)" : isTool ? "hsl(220,25%,60%)" : "hsl(35,10%,42%)";

    return (
      <g key={n.id}>
        <rect
          x={pos.x} y={pos.y} width={pos.w} height={pos.h}
          rx={isTool ? 5 : isDecision ? 8 : 7}
          fill={bgFill} stroke={borderStroke}
          strokeWidth={isTool ? 1 : 1.2}
          strokeDasharray={isDecision ? "3 2" : "none"}
        />
        {!isTool && (
          <circle cx={pos.x + 13} cy={pos.y + pos.h / 2} r={3}
            fill={n.done ? color : isDecision ? "hsl(35,30%,30%)" : "hsl(35,10%,28%)"}
          />
        )}
        {isTool && (
          <text x={pos.x + 9} y={pos.y + pos.h / 2} fontSize={8} dominantBaseline="middle" fill="hsl(220,25%,55%)">{"\u2699"}</text>
        )}
        {n.done && !isTool && (
          <text x={pos.x + pos.w - 9} y={pos.y + pos.h / 2}
            fill={color} fontSize={7.5} fontWeight={700}
            textAnchor="middle" dominantBaseline="middle" opacity={0.85}>{"\u2713"}</text>
        )}
        <text
          x={pos.x + (isTool ? 19 : 23)} y={pos.y + pos.h / 2}
          fill={textFill} fontSize={isTool ? 9.5 : 10.5}
          fontWeight={n.done ? 500 : 400} dominantBaseline="middle"
          style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
        >{n.label}</text>
      </g>
    );
  };

  return (
    <div className="w-full">
      <svg
        width="100%" height={svgH}
        viewBox={`0 0 ${SG_SVG_W} ${svgH}`}
        preserveAspectRatio="xMidYMid meet"
        className="select-none" style={{ display: "block" }}
      >
        {def.edges.map((e, i) => renderEdge(e, i))}
        {def.nodes.map(n => renderNode(n))}
      </svg>
    </div>
  );
}

const nodeTools: Record<string, Tool[]> = {
  "fetch-mail": [
    { name: "Gmail API", description: "Fetch unread messages from inbox", icon: "\ud83d\udce7", credentials: [{ key: "gmail_token", label: "Gmail OAuth Token", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }, { key: "gmail_scope", label: "Scope: mail.readonly", connected: true }] },
    { name: "Filter Engine", description: "Apply label and sender filters", icon: "\ud83d\udd0d" },
    { name: "Rate Limiter", description: "Throttle API calls to 50/min", icon: "\u23f1\ufe0f" },
  ],
  "classify": [
    { name: "GPT-4o Classifier", description: "Categorise emails by intent & urgency", icon: "\ud83e\udde0", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Spam Detector", description: "ML-based spam/promotional filter", icon: "\ud83d\udeab" },
    { name: "Sentiment Analyser", description: "Score emotional tone of messages", icon: "\ud83d\udcca" },
  ],
  "prioritize": [
    { name: "Priority Scorer", description: "Rank emails by urgency score", icon: "\ud83c\udfaf" },
    { name: "Calendar Check", description: "Cross-reference with your schedule", icon: "\ud83d\udcc5", credentials: [{ key: "gcal_token", label: "Google Calendar OAuth", connected: false }] },
    { name: "Contact Lookup", description: "Identify VIP senders from contacts", icon: "\ud83d\udc64" },
  ],
  "draft-replies": [
    { name: "GPT-4o Writer", description: "Generate context-aware reply drafts", icon: "\u270d\ufe0f", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Tone Adjuster", description: "Match formality to sender relationship", icon: "\ud83c\udfad" },
    { name: "Template Library", description: "Apply saved reply templates", icon: "\ud83d\udccb" },
  ],
  "send-or-archive": [
    { name: "Gmail Send", description: "Dispatch approved reply drafts", icon: "\ud83d\udce4", credentials: [{ key: "gmail_token", label: "Gmail OAuth Token", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }, { key: "gmail_send_scope", label: "Scope: mail.send", connected: true }] },
    { name: "Archive Manager", description: "File processed emails by category", icon: "\ud83d\uddc2\ufe0f" },
    { name: "Webhook Trigger", description: "Notify downstream agents on send", icon: "\ud83d\udd17", credentials: [{ key: "webhook_url", label: "Webhook URL", connected: false }] },
  ],
  "intake": [
    { name: "Form Parser", description: "Extract structured data from inputs", icon: "\ud83d\udcdd" },
    { name: "Validator", description: "Check required fields and formats", icon: "\u2705" },
    { name: "Context Builder", description: "Build session context from history", icon: "\ud83e\udde9" },
  ],
  "job-search": [
    { name: "LinkedIn Scraper", description: "Search LinkedIn job postings", icon: "\ud83d\udcbc", credentials: [{ key: "linkedin_token", label: "LinkedIn OAuth", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Indeed API", description: "Query Indeed for matching roles", icon: "\ud83d\udd0e", credentials: [{ key: "indeed_key", label: "Indeed Publisher ID", connected: false }] },
    { name: "Glassdoor Fetch", description: "Pull company ratings and reviews", icon: "\u2b50" },
  ],
  "job-review": [
    { name: "Match Scorer", description: "Calculate fit score vs. resume", icon: "\ud83d\udcc8", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Requirements Parser", description: "Extract must-have skills from JD", icon: "\ud83d\udccb" },
    { name: "Salary Estimator", description: "Benchmark comp against market data", icon: "\ud83d\udcb0" },
  ],
  "customize": [
    { name: "Resume Tailor", description: "Adjust bullet points to match JD", icon: "\u2702\ufe0f", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Cover Letter Gen", description: "Generate personalised cover letter", icon: "\u2709\ufe0f" },
    { name: "Apply Submitter", description: "Submit application via form/API", icon: "\ud83d\ude80" },
  ],
  "coach": [
    { name: "Plan Generator", description: "Build personalised workout plans", icon: "\ud83c\udfcb\ufe0f", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Progress Tracker", description: "Log sets, reps, and weights", icon: "\ud83d\udcca" },
    { name: "Adaptive Engine", description: "Adjust intensity based on recovery", icon: "\u26a1" },
  ],
  "meal-checkin": [
    { name: "Nutrition Logger", description: "Track macros from meal entries", icon: "\ud83c\udf4e" },
    { name: "Recipe Suggester", description: "Recommend meals to hit targets", icon: "\ud83d\udc68\u200d\ud83c\udf73", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
    { name: "Calorie Calculator", description: "Estimate intake vs. TDEE", icon: "\ud83d\udd22" },
  ],
  "exercise-reminder": [
    { name: "Scheduler", description: "Send workout reminders via push/email", icon: "\u23f0" },
    { name: "Streak Tracker", description: "Monitor workout consistency", icon: "\ud83d\udd25" },
    { name: "Recovery Advisor", description: "Flag overtraining based on HRV", icon: "\ud83d\udca4" },
  ],
  "passive-recon": [
    { name: "Subdomain Finder", description: "Enumerate subdomains via DNS", icon: "\ud83c\udf10" },
    { name: "Port Scanner", description: "Identify open ports (top 1000)", icon: "\ud83d\udd0c" },
    { name: "WHOIS Lookup", description: "Retrieve domain registration data", icon: "\ud83d\udccb" },
  ],
  "risk-scoring": [
    { name: "CVSS Scorer", description: "Calculate risk severity using CVSS 3.1", icon: "\u26a0\ufe0f" },
    { name: "Threat Intel", description: "Cross-ref with known CVE database", icon: "\ud83d\udee1\ufe0f" },
    { name: "Asset Mapper", description: "Map vulnerabilities to attack surface", icon: "\ud83d\uddfa\ufe0f" },
  ],
  "findings-review": [
    { name: "Triage Engine", description: "Sort findings by exploitability", icon: "\ud83d\udd0d" },
    { name: "False-Pos Filter", description: "Remove likely false positives", icon: "\u2702\ufe0f" },
    { name: "Evidence Collector", description: "Capture proof-of-concept data", icon: "\ud83d\udcf8" },
  ],
  "final-report": [
    { name: "Report Builder", description: "Generate PDF remediation report", icon: "\ud83d\udcc4" },
    { name: "Exec Summary", description: "Create non-technical summary", icon: "\ud83d\udc54" },
    { name: "Ticket Creator", description: "Open Jira/Linear tasks for findings", icon: "\ud83c\udfab" },
  ],
};

const defaultTools: Tool[] = [
  { name: "LLM Executor", description: "Run prompt-based reasoning steps", icon: "\ud83e\udd16", credentials: [{ key: "openai_key", label: "OpenAI API Key", connected: true, value: "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022" }] },
  { name: "Memory Store", description: "Persist context across iterations", icon: "\ud83d\udcbe" },
  { name: "Callback Handler", description: "Trigger next node on completion", icon: "\ud83d\udd17" },
];

const nodeSystemPrompts: Record<string, string> = {
  "fetch-mail": "You are an email fetching agent. Your job is to authenticate with Gmail and retrieve unread messages from the inbox.\n\nApply the following filters before emitting:\n- Exclude promotional and social tabs\n- Prioritise messages from known contacts\n- Group by thread when possible\n\nEmit a structured batch of messages to the classify node. Rate-limit to 50 calls/min.",
  "classify": "You are an email classification agent. Receive a batch of emails and categorise each one.\n\nCategories:\n- URGENT_ACTION \u2014 requires response within 24h\n- MEETING \u2014 calendar invite or scheduling request\n- FINANCIAL \u2014 invoices, receipts, payment notices\n- RECRUITMENT \u2014 job opportunities, recruiter outreach\n- FOLLOW_UP \u2014 awaiting a response from someone\n- INFO \u2014 informational, no action required\n- SPAM \u2014 promotional or unsolicited\n\nReturn a JSON array of { id, category, confidence, sentiment } for each email.",
  "prioritize": "You are a prioritisation agent. Receive classified emails and rank them by urgency.\n\nScoring criteria:\n1. Category weight (URGENT_ACTION: 10, FINANCIAL: 8, MEETING: 7...)\n2. Sender reputation (VIP contacts get +3 boost)\n3. Time sensitivity (deadlines, event times in content)\n4. Thread recency\n\nOutput a ranked array with priority scores 0\u2013100.",
  "draft-replies": "You are a reply drafting agent. Generate context-aware reply drafts for emails that require a response.\n\nGuidelines:\n- Match the formality level of the original message\n- Keep replies concise (< 150 words unless necessary)\n- Never fabricate facts or commitments\n- Use placeholders like [DATE] or [AMOUNT] for info you don't have\n- Flag any reply that requires user confirmation before sending",
  "send-or-archive": "You are a dispatch agent. Your job is to send approved reply drafts and archive processed emails.\n\nRules:\n- Only send drafts explicitly marked as APPROVED\n- Archive all processed emails to their appropriate label\n- Fire a webhook notification after each successful send\n- If a send fails, retry once, then flag for manual review",
  "intake": "You are an intake agent. Parse and validate incoming requests before passing them to downstream nodes.\n\nValidation rules:\n- Required fields must be non-empty\n- Dates must be in ISO 8601 format\n- Numeric fields must be within acceptable ranges\n- Build a session context object from prior conversation history\n\nReject invalid inputs with a structured error response.",
  "job-search": "You are a job discovery agent. Search multiple job boards for roles matching the candidate's profile.\n\nSearch sources:\n- LinkedIn Jobs (primary)\n- Indeed API\n- Glassdoor\n\nMatching criteria:\n- Job title similarity > 70%\n- Location: remote-friendly or within radius\n- Seniority level match\n- Required skills overlap > 60%\n\nReturn top 10 results per source, deduplicated by company + title.",
  "job-review": "You are a job review agent. Evaluate each job listing against the candidate's resume.\n\nFor each job, calculate:\n- Overall match score (0\u2013100%)\n- Missing required skills\n- Salary benchmark vs. market data\n- Growth potential rating\n\nFlag any roles above 90% match for auto-application.",
  "customize": "You are a job application agent. Tailor application materials and submit to target roles.\n\nTasks:\n1. Rewrite resume bullet points to match job description keywords\n2. Generate a personalised cover letter (3 paragraphs max)\n3. Submit via the employer's application portal or API\n4. Confirm submission and log the application date",
  "coach": "You are a fitness coaching agent. Build and adapt personalised workout plans for the user.\n\nPlan parameters:\n- Goal: strength / hypertrophy / endurance / weight loss\n- Available equipment, days per week, session duration\n- Recovery status (HRV, sleep, soreness self-report)\n\nAdapt intensity if HRV drops below baseline by 15%.\nLog all completed sets and trigger the meal check-in after each session.",
  "meal-checkin": "You are a nutrition tracking agent. Log meals and provide guidance to hit daily targets.\n\nTrack:\n- Calories, protein, carbs, fats per meal\n- Micronutrient highlights (vitamin D, omega-3, fibre)\n\nSuggest next meal based on remaining macros for the day.\nAlert if protein target will not be met by end of day.",
  "exercise-reminder": "You are a workout reminder agent. Send timely reminders and track consistency streaks.\n\nReminder rules:\n- Send push notification 30 min before scheduled session\n- If session is skipped, send a recovery check-in 2 hours later\n- Update streak counter daily at midnight\n- Alert coach node if streak drops to zero",
  "passive-recon": "You are a reconnaissance agent. Perform passive information gathering on the target domain.\n\nTasks:\n1. Enumerate all subdomains via DNS brute-force + certificate transparency logs\n2. Scan top 1000 ports on discovered hosts\n3. Perform WHOIS lookup on root domain\n4. Check for directory listing, open redirects on discovered subdomains\n\nDo NOT send any active exploit payloads. Passive only.",
  "risk-scoring": "You are a risk scoring agent. Assign severity scores to discovered vulnerabilities.\n\nUse CVSS 3.1 scoring methodology.\nCross-reference all findings against the NVD CVE database.\nMap each vulnerability to the affected component in the attack surface model.\n\nOutput: { cve_id?, cvss_score, severity, affected_host, remediation_priority }",
  "findings-review": "You are a findings review agent. Triage and validate discovered vulnerabilities.\n\nSteps:\n1. Sort findings by CVSS score descending\n2. Remove likely false positives (confidence < 60%)\n3. For each critical/high finding, capture a proof-of-concept request/response\n4. Group related findings by root cause\n\nOutput a curated findings list ready for report generation.",
  "final-report": "You are a report generation agent. Produce a comprehensive penetration test report.\n\nReport sections:\n1. Executive Summary (non-technical, 1 page)\n2. Scope & Methodology\n3. Findings table (sorted by severity)\n4. Detailed findings with evidence and remediation steps\n5. Risk matrix\n6. Appendices\n\nAlso create Jira/Linear tickets for each critical and high finding.",
};

const defaultSystemPrompt = "You are an AI agent node in a multi-agent pipeline.\n\nYour role is to process inputs from upstream nodes, execute your assigned task, and emit structured output to downstream nodes.\n\nFollow the pipeline instructions precisely and escalate to the Queen Bee if you encounter ambiguous input or an unrecoverable error.";

function formatNodeId(id: string): string {
  return id.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function CredentialRow({ cred }: { cred: ToolCredential }) {
  return (
    <div className="flex items-center justify-between px-3 py-2 rounded-lg bg-background/60 border border-border/30 mt-1.5">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${cred.connected ? "bg-primary" : "bg-muted-foreground/40"}`} />
        <span className="text-[11px] text-muted-foreground font-medium truncate">{cred.label}</span>
      </div>
      {cred.connected ? (
        <span className="text-[10px] text-primary/80 font-medium flex-shrink-0 ml-2">Connected</span>
      ) : (
        <button className="text-[10px] px-2 py-0.5 rounded-md bg-primary/15 text-primary border border-primary/25 font-semibold hover:bg-primary/25 transition-colors flex-shrink-0 ml-2">
          Connect
        </button>
      )}
    </div>
  );
}

function ToolRow({ tool }: { tool: Tool }) {
  const [expanded, setExpanded] = useState(false);
  const hasCreds = tool.credentials && tool.credentials.length > 0;

  return (
    <div className="rounded-xl border border-border/20 overflow-hidden">
      <button
        onClick={() => hasCreds && setExpanded(v => !v)}
        className={`w-full flex items-start gap-3 p-3 bg-muted/30 hover:bg-muted/50 transition-colors text-left ${!hasCreds ? "cursor-default" : ""}`}
      >
        <span className="text-base leading-none mt-0.5 flex-shrink-0">{tool.icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-foreground">{tool.name}</p>
          <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">{tool.description}</p>
        </div>
        {hasCreds && (
          <span className="flex-shrink-0 mt-0.5">
            {expanded
              ? <ChevronDown className="w-3 h-3 text-muted-foreground" />
              : <ChevronRight className="w-3 h-3 text-muted-foreground" />
            }
          </span>
        )}
      </button>
      {expanded && hasCreds && (
        <div className="px-3 pb-3 bg-muted/20 border-t border-border/15">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mt-2 mb-1">Credentials</p>
          {tool.credentials!.map(cred => (
            <CredentialRow key={cred.key} cred={cred} />
          ))}
        </div>
      )}
    </div>
  );
}

// Simulated log lines per node
const seedLogs: Record<string, string[]> = {
  "fetch-mail": [
    "[10:42:01] INFO  Authenticating with Gmail OAuth...",
    "[10:42:01] INFO  Token valid. Expires in 3582s",
    "[10:42:02] INFO  Fetching unread messages (limit: 100)...",
    "[10:42:03] INFO  Retrieved 23 messages",
    "[10:42:03] INFO  Applying label filters: -promotions -social",
    "[10:42:03] INFO  Filtered to 14 relevant messages",
    "[10:42:04] INFO  Emitting batch to classify node",
  ],
  "classify": [
    "[10:42:05] INFO  Received 14 messages from fetch-mail",
    "[10:42:05] INFO  Tokenizing message content...",
    "[10:42:06] INFO  Calling GPT-4o classifier (model: gpt-4o-2024-08)",
    "[10:42:08] INFO  Classified 14/14 messages",
    "[10:42:08] INFO  Breakdown: URGENT_ACTION\u00d72 MEETING\u00d71 FINANCIAL\u00d71 RECRUITMENT\u00d72 INFO\u00d78",
    "[10:42:08] INFO  Sentiment scores computed",
    "[10:42:09] INFO  Emitting to prioritize node",
  ],
  "prioritize": [
    "[10:42:10] INFO  Received 14 classified messages",
    "[10:42:10] INFO  Loading contact VIP list (47 entries)...",
    "[10:42:11] WARN  Calendar API rate-limited \u2014 retrying in 2s",
    "[10:42:13] INFO  Calendar context loaded",
    "[10:42:13] INFO  Scoring messages by urgency...",
  ],
  "findings-review": [
    "[11:15:22] INFO  Received 31 raw findings from risk-scoring",
    "[11:15:22] INFO  Sorting by CVSS score descending...",
    "[11:15:23] INFO  Critical: 3  High: 8  Medium: 12  Low: 8",
    "[11:15:23] INFO  Running false-positive detection...",
    "[11:15:25] WARN  3 findings flagged as likely false positives",
    "[11:15:26] INFO  Capturing PoC for 3 critical findings...",
  ],
};

function LogsTab({ nodeId, isActive }: { nodeId: string; isActive: boolean }) {
  const base = seedLogs[nodeId] || [
    "[00:00:01] INFO  Node initialised",
    "[00:00:01] INFO  Awaiting input from upstream",
  ];
  const [lines, setLines] = useState<string[]>(base);
  const bottomRef = useRef<HTMLDivElement>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isActive) {
      intervalRef.current = setInterval(() => {
        const now = new Date();
        const ts = `[${String(now.getHours()).padStart(2,"0")}:${String(now.getMinutes()).padStart(2,"0")}:${String(now.getSeconds()).padStart(2,"0")}]`;
        const msgs = [
          `${ts} INFO  Processing batch item ${Math.floor(Math.random() * 100)}...`,
          `${ts} INFO  Token usage: ${Math.floor(Math.random() * 800 + 200)} prompt, ${Math.floor(Math.random() * 400 + 50)} completion`,
          `${ts} DEBUG Calling tool: ${["Gmail API", "GPT-4o", "Filter Engine", "Rate Limiter"][Math.floor(Math.random() * 4)]}`,
          `${ts} INFO  Step complete. Proceeding...`,
        ];
        setLines(prev => [...prev, msgs[Math.floor(Math.random() * msgs.length)]].slice(-120));
      }, 1400);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isActive]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  return (
    <div className="flex-1 overflow-auto bg-background/80 rounded-xl border border-border/20 font-mono text-[10.5px] leading-relaxed p-3">
      {lines.map((line, i) => {
        const isWarn = line.includes(" WARN ");
        const isErr = line.includes(" ERROR ");
        const isDebug = line.includes(" DEBUG ");
        return (
          <div
            key={i}
            className={isErr ? "text-red-400" : isWarn ? "text-yellow-400/80" : isDebug ? "text-muted-foreground/50" : "text-green-400/70"}
          >
            {line}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}

function SystemPromptTab({ nodeId }: { nodeId: string }) {
  const prompt = nodeSystemPrompts[nodeId] || defaultSystemPrompt;
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(prompt);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex-1 overflow-auto flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">System Prompt</p>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
        >
          {copied ? <Check className="w-3 h-3 text-primary" /> : <Copy className="w-3 h-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <textarea
        readOnly
        value={prompt}
        className="flex-1 min-h-[240px] w-full rounded-xl bg-muted/30 border border-border/20 text-[11px] text-muted-foreground leading-relaxed p-3 font-mono resize-none focus:outline-none focus:border-border/40"
      />
    </div>
  );
}

// -- Subagents tab --
interface Subagent {
  name: string;
  goal: string;
  status: "running" | "complete" | "pending" | "error";
  runtime?: "eventloop" | "GCU";
  iterations?: number;
}

// -- Judge Criteria --
interface JudgeCriteria {
  label: string;
  met: boolean;
}

const judgeCriteria: Record<string, JudgeCriteria[]> = {
  "brief-intake": [
    { label: "Client brief parsed into structured requirements", met: true },
    { label: "Target audience and tone identified", met: true },
    { label: "Deadline and word count constraints extracted", met: true },
  ],
  "research": [
    { label: "Minimum 5 credible sources collected", met: true },
    { label: "Competitor content analyzed for gaps", met: true },
    { label: "Key statistics and quotes extracted", met: true },
  ],
  "outline": [
    { label: "H2/H3 structure covers all brief requirements", met: true },
    { label: "Introduction hook and CTA defined", met: true },
    { label: "Outline approved or auto-approved within 2 iterations", met: true },
  ],
  "draft": [
    { label: "Word count within \u00b110% of target", met: false },
    { label: "All outline sections expanded with supporting detail", met: false },
    { label: "Readability score meets Flesch-Kincaid target", met: false },
  ],
  "review": [
    { label: "Grammar and style check passed (0 critical errors)", met: false },
    { label: "Plagiarism score below 5%", met: false },
    { label: "Final draft exported and delivered to client", met: false },
  ],
  "intake": [
    { label: "User profile and goals captured", met: true },
    { label: "Baseline metrics (weight, BF%, lifts) recorded", met: true },
    { label: "Dietary restrictions and preferences noted", met: true },
  ],
  "coach": [
    { label: "Daily workout generated from current mesocycle", met: true },
    { label: "Sleep and recovery data checked before programming", met: true },
    { label: "Progressive overload applied vs. last session", met: false },
  ],
  "meal-checkin": [
    { label: "Calorie and macro targets calculated for today", met: false },
    { label: "Meal photo logged or manual entry confirmed", met: false },
    { label: "Deviation from plan flagged if >15%", met: false },
  ],
  "exercise-reminder": [
    { label: "Reminder sent at user-preferred time", met: false },
    { label: "Warm-up routine included with reminder", met: false },
    { label: "Equipment availability confirmed", met: false },
  ],
  "fetch-mail": [
    { label: "Fetch at least 1 unread email from inbox", met: true },
    { label: "OAuth token validated before fetch", met: true },
    { label: "Batch size does not exceed 20 messages", met: true },
  ],
  "classify": [
    { label: "All messages assigned exactly one category", met: true },
    { label: "Spam confidence score \u2265 0.85 for quarantine", met: false },
    { label: "Sentiment scored on every non-spam message", met: false },
  ],
  "prioritize": [
    { label: "Every message assigned a priority rank 1\u20135", met: false },
    { label: "VIP sender list cross-referenced successfully", met: false },
    { label: "Calendar conflicts identified for meeting emails", met: false },
  ],
  "draft-replies": [
    { label: "Draft generated for every action-required email", met: false },
    { label: "Reply tone matches sender relationship level", met: false },
    { label: "No draft exceeds 300 words", met: false },
  ],
  "send-or-archive": [
    { label: "Auto-approved drafts sent within 2 minutes", met: false },
    { label: "Delivery confirmation received for all sent emails", met: false },
    { label: "Failed sends retried at least once before error", met: false },
  ],
  "job-search": [
    { label: "Minimum 10 unique job listings collected", met: true },
    { label: "Duplicate listings removed across all sources", met: true },
    { label: "Each listing includes salary range if available", met: true },
  ],
  "job-review": [
    { label: "Resume-to-JD match score computed for every role", met: true },
    { label: "Roles above 90% match flagged for auto-apply", met: true },
    { label: "Skills gap analysis completed per listing", met: true },
  ],
  "customize": [
    { label: "Resume tailored with JD keywords for each role", met: true },
    { label: "Cover letter generated (3 paragraphs per role)", met: true },
    { label: "Application submitted or flagged for manual review", met: false },
  ],
  "passive-recon": [
    { label: "All subdomains enumerated via DNS brute-force", met: true },
    { label: "Certificate transparency logs queried for domain", met: true },
    { label: "Port scan completed on top 1000 ports per host", met: false },
  ],
  "risk-scoring": [
    { label: "CVSS 3.1 score assigned to every finding", met: true },
    { label: "Each finding matched against NVD CVE database", met: true },
    { label: "Critical findings escalated within 5 minutes", met: true },
  ],
  "findings-review": [
    { label: "False positives filtered below 40% confidence", met: false },
    { label: "PoC captured for all critical/high severity findings", met: false },
    { label: "Related findings clustered by root cause", met: false },
  ],
  "final-report": [
    { label: "Executive summary written (max 1 page)", met: false },
    { label: "Jira/Linear tickets opened for all critical findings", met: false },
    { label: "Report exported as PDF and shared via webhook", met: false },
  ],
};

const nodeSubagents: Record<string, Subagent[]> = {
  "fetch-mail": [
    { name: "Auth Watcher", goal: "Monitor OAuth token validity and refresh before expiry", status: "complete", runtime: "eventloop", iterations: 1 },
    { name: "Batch Splitter", goal: "Split large inbox batches into manageable chunks of 20", status: "complete", runtime: "eventloop", iterations: 3 },
  ],
  "classify": [
    { name: "Intent Classifier", goal: "Identify the primary intent of each email (action, info, meeting)", status: "running", runtime: "GCU", iterations: 14 },
    { name: "Spam Filter Agent", goal: "Detect and quarantine promotional or spam messages", status: "complete", runtime: "eventloop", iterations: 14 },
    { name: "Sentiment Scorer", goal: "Score emotional tone and urgency of message content", status: "pending", runtime: "eventloop" },
  ],
  "prioritize": [
    { name: "VIP Resolver", goal: "Cross-reference sender against known VIP contact list", status: "running", runtime: "eventloop", iterations: 7 },
    { name: "Calendar Conflict Checker", goal: "Identify emails related to upcoming calendar events", status: "pending", runtime: "eventloop" },
  ],
  "draft-replies": [
    { name: "Context Builder", goal: "Retrieve conversation history and user preferences for tone", status: "complete", runtime: "GCU", iterations: 5 },
    { name: "Draft Generator", goal: "Produce reply drafts using context and user writing style", status: "running", runtime: "GCU", iterations: 2 },
    { name: "Tone Adjuster", goal: "Ensure reply formality matches sender relationship level", status: "pending", runtime: "eventloop" },
  ],
  "send-or-archive": [
    { name: "Approval Gate", goal: "Check each draft against auto-approval criteria before sending", status: "pending", runtime: "eventloop" },
    { name: "Delivery Monitor", goal: "Confirm successful delivery and handle bounce-backs", status: "pending" },
  ],
  "job-search": [
    { name: "LinkedIn Scout", goal: "Search LinkedIn for roles matching the candidate profile", status: "complete", runtime: "eventloop", iterations: 8 },
    { name: "Indeed Crawler", goal: "Query Indeed API for matching job listings by keyword", status: "complete", runtime: "eventloop", iterations: 12 },
    { name: "Deduplicator", goal: "Remove duplicate listings across all sources by company+title", status: "complete", runtime: "eventloop", iterations: 1 },
  ],
  "job-review": [
    { name: "Match Scorer", goal: "Calculate resume-to-JD match score using semantic similarity", status: "complete", runtime: "GCU", iterations: 6 },
    { name: "Skills Gap Analyst", goal: "Identify missing required skills and estimate learning time", status: "complete", runtime: "eventloop", iterations: 6 },
  ],
  "customize": [
    { name: "Resume Tailor", goal: "Rewrite bullet points to reflect job description keywords", status: "running", runtime: "GCU", iterations: 3 },
    { name: "Cover Letter Writer", goal: "Generate a personalised 3-paragraph cover letter per role", status: "pending", runtime: "GCU" },
  ],
  "passive-recon": [
    { name: "DNS Enumerator", goal: "Enumerate subdomains via DNS brute-force and zone transfer attempts", status: "complete", runtime: "eventloop", iterations: 1 },
    { name: "Cert Transparency Watcher", goal: "Query CT logs for all certificates issued to the target domain", status: "complete", runtime: "eventloop", iterations: 1 },
    { name: "Port Scanner Agent", goal: "Run port scan across discovered hosts on top 1000 ports", status: "running", runtime: "eventloop", iterations: 4 },
  ],
  "risk-scoring": [
    { name: "CVSS Calculator", goal: "Compute CVSS 3.1 base scores for each discovered vulnerability", status: "complete", runtime: "GCU", iterations: 31 },
    { name: "CVE Correlator", goal: "Match findings to known CVEs in the NVD database", status: "complete", runtime: "eventloop", iterations: 28 },
  ],
  "findings-review": [
    { name: "False Positive Filter", goal: "Flag findings with confidence below 60% for human review", status: "running", runtime: "GCU", iterations: 6 },
    { name: "PoC Capture Agent", goal: "Record proof-of-concept request/response for critical findings", status: "pending", runtime: "eventloop" },
    { name: "Root Cause Grouper", goal: "Cluster related findings by underlying root cause", status: "error", runtime: "eventloop" },
  ],
  "final-report": [
    { name: "Exec Summary Writer", goal: "Produce a one-page non-technical executive summary", status: "pending", runtime: "GCU" },
    { name: "Ticket Creator", goal: "Open Jira/Linear tickets for each critical and high finding", status: "pending" },
  ],
};

const subagentStatusConfig: Record<Subagent["status"], { label: string; color: string; Icon: React.FC<{ className?: string }> }> = {
  running: { label: "Running", color: "hsl(45,95%,58%)", Icon: ({ className }) => <Loader2 className={`${className} animate-spin`} /> },
  complete: { label: "Complete", color: "hsl(43,70%,45%)", Icon: ({ className }) => <CheckCircle2 className={className} /> },
  pending: { label: "Pending", color: "hsl(220,15%,45%)", Icon: ({ className }) => <Clock className={className} /> },
  error: { label: "Error", color: "hsl(0,65%,55%)", Icon: ({ className }) => <AlertCircle className={className} /> },
};

function SubagentsTab({ nodeId }: { nodeId: string }) {
  const subagents = nodeSubagents[nodeId] || [];

  if (subagents.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-xs text-muted-foreground/60 italic text-center">No subagents assigned to this node.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col gap-2">
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">
        Active Subagents ({subagents.length})
      </p>
      {subagents.map((sa, i) => {
        const cfg = subagentStatusConfig[sa.status];
        const StatusIcon = cfg.Icon;
        return (
          <div key={i} className="rounded-xl border border-border/20 bg-muted/20 p-3 flex flex-col gap-2">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <div
                  className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0"
                  style={{ backgroundColor: `${cfg.color}18`, border: `1px solid ${cfg.color}30` }}
                >
                  <Bot className="w-3 h-3" style={{ color: cfg.color }} />
                </div>
                <span className="text-xs font-medium text-foreground truncate">{sa.name}</span>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0" style={{ color: cfg.color }}>
                <StatusIcon className="w-3 h-3" />
                <span className="text-[10px] font-medium">{cfg.label}</span>
              </div>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">{sa.goal}</p>
            <div className="flex items-center gap-3 flex-wrap">
              {sa.runtime && (
                <span className="text-[10px] font-mono text-muted-foreground/60 bg-muted/50 border border-border/20 rounded px-1.5 py-0.5">
                  {sa.runtime}
                </span>
              )}
              {sa.iterations !== undefined && (
                <span className="text-[10px] text-muted-foreground/60">
                  {sa.iterations} iteration{sa.iterations !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

type Tab = "overview" | "tools" | "logs" | "prompt" | "subagents";

const tabs: { id: Tab; label: string; Icon: React.FC<{ className?: string }> }[] = [
  { id: "overview", label: "Overview", Icon: ({ className }) => <GitBranch className={className} /> },
  { id: "tools", label: "Tools", Icon: ({ className }) => <Wrench className={className} /> },
  { id: "logs", label: "Logs", Icon: ({ className }) => <Terminal className={className} /> },
  { id: "prompt", label: "Prompt", Icon: ({ className }) => <BookOpen className={className} /> },
  { id: "subagents", label: "Subagents", Icon: ({ className }) => <Bot className={className} /> },
];

export default function NodeDetailPanel({ node, onClose }: NodeDetailPanelProps) {
  const [activeTab, setActiveTab] = useState<Tab>("overview");

  useEffect(() => {
    setActiveTab("overview");
  }, [node?.id]);

  if (!node) return null;

  const tools = nodeTools[node.id] || defaultTools;
  const status = statusConfig[node.status];
  const StatusIcon = status.Icon;
  const isActive = node.status === "running" || node.status === "looping";

  return (
    <div className="flex flex-col h-full border-l border-border/40 bg-card/20 animate-in slide-in-from-right">
      {/* Header */}
      <div className="px-4 pt-4 pb-3 border-b border-border/30 flex items-start justify-between gap-2 flex-shrink-0">
        <div className="flex items-start gap-3 min-w-0">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
            style={{ backgroundColor: `${status.color}18`, border: `1.5px solid ${status.color}35` }}
          >
            <Cpu className="w-3.5 h-3.5" style={{ color: status.color }} />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-foreground leading-tight">{formatNodeId(node.id)}</h3>
            <div className="flex items-center gap-1.5 mt-1">
              <span style={{ color: status.color }}><StatusIcon className="w-3 h-3 flex-shrink-0" /></span>
              <span className="text-[11px] font-medium" style={{ color: status.color }}>{status.label}</span>
              {node.iterations !== undefined && node.iterations > 0 && (
                <>
                  <span className="text-muted-foreground/40 text-[10px]">&middot;</span>
                  <span className="text-[11px] text-muted-foreground">
                    {node.iterations}{node.maxIterations ? `/${node.maxIterations}` : ""} iterations
                  </span>
                </>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors flex-shrink-0"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Status label */}
      {node.statusLabel && (
        <div className="px-4 py-2 border-b border-border/20 flex-shrink-0">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground bg-muted/40 rounded-lg px-3 py-2">
            <Zap className="w-3 h-3 text-primary flex-shrink-0" />
            <span className="italic">{node.statusLabel}</span>
          </div>
        </div>
      )}

      {/* Tab bar */}
      <div className="flex border-b border-border/30 flex-shrink-0 px-2 pt-1 overflow-x-auto scrollbar-hide">
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 px-3 py-2 text-[11px] font-medium border-b-2 transition-colors -mb-px ${
              activeTab === tab.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            <tab.Icon className="w-3 h-3" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto px-4 py-4 flex flex-col gap-3">
        {activeTab === "overview" && (
          <>
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Internal Steps</p>
            <SubGraph nodeId={node.id} status={node.status} />
            {(() => {
              const criteria = judgeCriteria[node.id];
              if (!criteria || criteria.length === 0) return null;
              const metCount = criteria.filter(c => c.met).length;
              return (
                <div className="mt-1">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Judge Criteria</p>
                    <span className="text-[10px] font-mono text-muted-foreground/60">{metCount}/{criteria.length} met</span>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {criteria.map((c, i) => (
                      <div key={i} className="flex items-start gap-2">
                        <div className={`mt-0.5 w-3.5 h-3.5 rounded-full flex-shrink-0 flex items-center justify-center border ${c.met ? "border-transparent bg-[hsl(43,70%,45%)]" : "border-border/40 bg-muted/30"}`}>
                          {c.met && (
                            <svg viewBox="0 0 8 8" className="w-2 h-2" fill="none">
                              <path d="M1.5 4l2 2 3-3" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                            </svg>
                          )}
                        </div>
                        <span className={`text-[11px] leading-relaxed ${c.met ? "text-foreground/70 line-through decoration-muted-foreground/30" : "text-foreground/80"}`}>{c.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
            {node.next && node.next.length > 0 && (
              <div className="mt-2">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Sends to</p>
                <div className="flex flex-wrap gap-1.5">
                  {node.next.map((n) => (
                    <span key={n} className="text-[11px] px-2.5 py-1 rounded-full bg-primary/10 text-primary border border-primary/20 font-medium">
                      {formatNodeId(n)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {activeTab === "tools" && (
          <div className="space-y-2">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">Tools & Integrations</p>
            {tools.map((tool, i) => <ToolRow key={i} tool={tool} />)}
          </div>
        )}

        {activeTab === "logs" && (
          <LogsTab nodeId={node.id} isActive={isActive} />
        )}

        {activeTab === "prompt" && (
          <SystemPromptTab nodeId={node.id} />
        )}

        {activeTab === "subagents" && (
          <SubagentsTab nodeId={node.id} />
        )}
      </div>
    </div>
  );
}

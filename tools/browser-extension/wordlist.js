/**
 * Tiny dependency-free generator for a human-readable 3-word profile label
 * (adjective-adjective-animal, e.g. "brave-purple-otter").
 *
 * Used by background.js to auto-name a Chrome profile the first time it
 * connects, so the bridge and the side panel have a stable, friendly label to
 * route by even before the user renames it. Kept extension-side because the
 * label originates here (per Chrome profile, in chrome.storage.local).
 */

const ADJECTIVES = [
  "amber", "brave", "bright", "calm", "clever", "cosmic", "crimson", "daring",
  "eager", "electric", "fancy", "fuzzy", "gentle", "golden", "happy", "hidden",
  "jolly", "keen", "lucky", "mellow", "merry", "mighty", "nimble", "noble",
  "polished", "proud", "quiet", "rapid", "royal", "shiny", "silent", "silver",
  "sly", "snappy", "spry", "sturdy", "sunny", "swift", "tidy", "vivid",
  "witty", "zesty",
];

const COLORS = [
  "amber", "azure", "blue", "coral", "cyan", "emerald", "green", "indigo",
  "ivory", "jade", "lavender", "lime", "magenta", "maroon", "olive", "orange",
  "peach", "pink", "plum", "purple", "red", "rose", "ruby", "scarlet",
  "teal", "violet", "yellow",
];

const ANIMALS = [
  "otter", "falcon", "lynx", "panda", "heron", "badger", "marten", "ibex",
  "koala", "tapir", "gecko", "raven", "wombat", "puffin", "narwhal", "lemur",
  "bison", "moth", "newt", "quail", "stoat", "wren", "yak", "civet",
  "fox", "hare", "owl", "seal", "swan", "toad", "vole", "wolf",
  "finch", "crane", "dingo", "egret", "ferret", "gull", "hawk", "jay",
];

function pick(list) {
  // crypto.getRandomValues is available in MV3 service workers; fall back to
  // Math.random where it isn't (older runtimes / tests).
  let n;
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    const a = new Uint32Array(1);
    crypto.getRandomValues(a);
    n = a[0];
  } else {
    n = Math.floor(Math.random() * 0xffffffff);
  }
  return list[n % list.length];
}

export function threeWordId() {
  return `${pick(ADJECTIVES)}-${pick(COLORS)}-${pick(ANIMALS)}`;
}

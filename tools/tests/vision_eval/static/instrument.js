/* Instrumentation for vision_eval task pages.
 *
 * Each task page calls Eval.* to record outcomes and render the visible
 * verdict banner. window.__EVAL__ is injected server-side with {run, task}.
 */
(function () {
  const meta = window.__EVAL__ || {};
  const RUN = meta.run || "unknown";
  const TASK = meta.task || (location.pathname.split("/").pop() || "unknown");

  function post(kind, payload) {
    try {
      fetch("/api/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run: RUN, task: TASK, kind, payload: payload || {} }),
        keepalive: true,
      }).catch(() => {});
    } catch (_) { /* best-effort */ }
  }

  function setVerdict(state, text) {
    let el = document.getElementById("verdict");
    if (!el) {
      el = document.createElement("div");
      el.id = "verdict";
      el.className = "verdict pending";
      el.textContent = "Waiting…";
      const anchor = document.querySelector(".instruction") || document.body.firstChild;
      if (anchor && anchor.parentNode) {
        anchor.parentNode.insertBefore(el, anchor.nextSibling);
      } else {
        document.body.insertBefore(el, document.body.firstChild);
      }
    }
    el.classList.remove("pending", "pass", "miss");
    el.classList.add(state);
    el.textContent = text;
  }

  function ensureBack() {
    if (document.querySelector(".back")) return;
    const a = document.createElement("a");
    a.href = "/?run=" + encodeURIComponent(RUN);
    a.className = "back";
    a.textContent = "← Index";
    document.body.appendChild(a);
  }

  const Eval = {
    run: RUN,
    task: TASK,
    record: post,
    markSuccess(detail) {
      post("success", detail || {});
      setVerdict("pass", "✓ Success");
    },
    markMiss(detail) {
      post("miss", detail || {});
      setVerdict("miss", "✗ Miss");
    },
    pointInRect(x, y, rect) {
      return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
    },
    /* True when the click should be ignored by the eval — e.g. clicks on
     * the harness UI (back link, verdict banner) that we inject into
     * every page. Those are not the queen's attempts at the task.
     */
    isHarnessClick(e) {
      const t = e.target;
      if (!t || !t.closest) return false;
      return !!(t.closest(".back") || t.closest(".verdict"));
    },
    /* Wires a body-level click handler. Every click outside the target
     * bounding rect is a miss; the first click inside is a pass and the
     * handler detaches. With { allowRetry: true } the handler stays
     * attached after misses so each subsequent wrong click is counted.
     */
    requireClickOn(getTarget, opts) {
      opts = opts || {};
      function handler(e) {
        if (Eval.isHarnessClick(e)) return;
        const el = getTarget();
        if (!el) {
          Eval.markMiss({ reason: "target_missing" });
          document.removeEventListener("click", handler, true);
          return;
        }
        const rect = el.getBoundingClientRect();
        const inside = Eval.pointInRect(e.clientX, e.clientY, rect);
        if (inside) {
          Eval.markSuccess({ x: e.clientX, y: e.clientY, rect });
          document.removeEventListener("click", handler, true);
        } else if (!opts.allowRetry) {
          Eval.markMiss({ x: e.clientX, y: e.clientY, rect });
          document.removeEventListener("click", handler, true);
        } else {
          Eval.markMiss({ x: e.clientX, y: e.clientY, rect });
          // Stay attached so the queen can try again
        }
      }
      document.addEventListener("click", handler, true);
    },
  };

  window.Eval = Eval;

  document.addEventListener("DOMContentLoaded", function () {
    ensureBack();
    setVerdict("pending", "Awaiting input…");
    post("view", { url: location.href });
  });
})();

chrome.runtime.sendMessage({ _beeline: true, type: "status" }, (resp) => {
  const connected = resp?.connected ?? false;
  const dot = document.getElementById("dot");
  const label = document.getElementById("label");
  const hint = document.getElementById("hint");

  dot.className = `dot ${connected ? "on" : "off"}`;
  label.textContent = connected ? "Connected to Hive" : "Hive not running";
  hint.textContent = connected
    ? "Subagents will use tab groups in this window."
    : "Start the Hive GCU server to connect.\nws://localhost:9229/beeline";
});

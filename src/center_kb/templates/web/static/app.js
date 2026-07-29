// CENTER-KB UI enhancements. Progressive only — every page works without this file.
"use strict";

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    const box = document.getElementById("global-search");
    if (box) { e.preventDefault(); box.focus(); box.select(); }
  }
});

function copyText(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const old = btn.textContent;
    btn.textContent = "copied ✓";
    setTimeout(() => { btn.textContent = old; }, 1200);
  });
}

document.addEventListener("click", (e) => {
  const copySel = e.target.closest("[data-copy]");
  if (copySel) {
    const node = document.querySelector(copySel.getAttribute("data-copy"));
    if (node) copyText(node.textContent.trim(), copySel);
    return;
  }
  const copyTxt = e.target.closest("[data-copy-text]");
  if (copyTxt) {
    copyText(copyTxt.getAttribute("data-copy-text"), copyTxt);
    return;
  }
  const toggle = e.target.closest("[data-toggle-card]");
  if (toggle) {
    const card = toggle.closest(".result-card");
    card.classList.toggle("expanded");
    toggle.textContent = card.classList.contains("expanded") ? "collapse" : "expand";
    return;
  }
  const density = e.target.closest("[data-density-btn]");
  if (density) {
    const full = density.getAttribute("data-density-btn") === "full";
    document.querySelectorAll(".result-card").forEach((c) => {
      c.classList.toggle("expanded", full);
      const t = c.querySelector("[data-toggle-card]");
      if (t) t.textContent = full ? "collapse" : "expand";
    });
    document.querySelectorAll("[data-density-btn]").forEach((b) => {
      const isActive = b === density;
      b.classList.toggle("on", isActive);
      b.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
  }
});

// Live section-table filter (doc page). Buttons switch from submit to client
// filtering when JS is available.
const filterBox = document.querySelector("[data-filter]");
if (filterBox) {
  const state = { status: "all" };
  const rows = () => document.querySelectorAll("[data-row]");
  const apply = () => {
    const q = filterBox.value.trim().toLowerCase();
    let shown = 0;
    rows().forEach((r) => {
      const okStatus = state.status === "all" || r.dataset.status === state.status;
      const okText = !q || r.dataset.text.includes(q);
      const on = okStatus && okText;
      r.style.display = on ? "" : "none";
      if (on) shown += 1;
    });
    const label = document.querySelector("[data-shown]");
    if (label) label.textContent = `${shown} of ${rows().length} shown`;
  };
  filterBox.addEventListener("input", apply);
  document.querySelectorAll("[data-status-btn]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault(); // stop the form submit — filter client-side
      state.status = btn.getAttribute("data-status-btn");
      document.querySelectorAll("[data-status-btn]").forEach((b) =>
        b.classList.toggle("on", b === btn));
      apply();
    });
  });
}

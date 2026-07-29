// CENTER-KB UI enhancements. Progressive only — every page works without this file.
"use strict";

document.addEventListener("keydown", (e) => {
  if (typeof e.key !== "string") return;
  if (e.shiftKey || e.altKey) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    const box = document.getElementById("global-search");
    if (box) { e.preventDefault(); box.focus(); box.select(); }
  }
});

function copyText(text, btn) {
  // Remember the button's real label once, so a rapid double-click (or a
  // failed copy after a prior success) always restores the true original
  // text instead of whatever transient status text was showing.
  if (btn.dataset.label === undefined) btn.dataset.label = btn.textContent;
  const label = btn.dataset.label;
  const revert = () => { btn.textContent = label; };
  const fail = () => { btn.textContent = "copy failed"; setTimeout(revert, 1200); };

  // navigator.clipboard is undefined on http:// origins other than
  // localhost (and in some embedded/older browsers) — calling writeText on
  // it would throw a TypeError and silently kill the click handler.
  if (!navigator.clipboard?.writeText) { fail(); return; }

  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "copied ✓";
    setTimeout(revert, 1200);
  }).catch(fail);
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
    if (!card) return;
    const expanded = card.classList.toggle("expanded");
    toggle.textContent = expanded ? "collapse" : "expand";
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    return;
  }
  const density = e.target.closest("[data-density-btn]");
  if (density) {
    const full = density.getAttribute("data-density-btn") === "full";
    document.querySelectorAll(".result-card").forEach((c) => {
      c.classList.toggle("expanded", full);
      const t = c.querySelector("[data-toggle-card]");
      if (t) {
        t.textContent = full ? "collapse" : "expand";
        t.setAttribute("aria-expanded", full ? "true" : "false");
      }
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
  // Seed from whichever status button the server already marked active,
  // rather than always assuming "all" — otherwise a page loaded with
  // ?status=reviewed shows the "Reviewed" button as pressed while the JS
  // filter silently treats every row as matching "all".
  const initialBtn = document.querySelector("[data-status-btn].on");
  const state = { status: initialBtn?.getAttribute("data-status-btn") || "all" };

  // If the page was already server-filtered (a non-empty ?filter= or a
  // ?status= other than "all"/absent), the DOM only contains the rows that
  // survived that filter. Widening the filter client-side (e.g. switching
  // from "reviewed" to "all", or clearing the filter text) can't reveal rows
  // the server never sent, so route those changes back through a real form
  // submit for a fresh server render instead of faking it client-side.
  // ?status=all / ?status= (empty) aren't a real narrowing, so they don't count.
  const searchParams = new URLSearchParams(location.search);
  const serverStatus = searchParams.get("status") || "";
  const hasServerFilter =
    Boolean(searchParams.get("filter")) || !["", "all"].includes(serverStatus);
  const statusHidden = document.querySelector("[data-status-hidden]");

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
    if (label) {
      const total = parseInt(label.dataset.total, 10) || rows().length;
      label.textContent = `${shown} of ${total} shown`;
    }
  };
  filterBox.addEventListener("input", () => {
    // Rows here are already a server-filtered subset — narrowing further on
    // the client would report an honest-looking but misleading "N of M"
    // count against a dataset that isn't the full one. Leave the DOM alone
    // and let Enter (a real submit, see the keydown handler below) fetch a
    // correctly-scoped page from the server instead.
    if (hasServerFilter) return;
    apply();
  });
  filterBox.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    // The browser's native implicit-submission always activates the form's
    // *first* submit button ("All"), which would silently reset the status
    // filter to "all" on every Enter press regardless of what's selected.
    // requestSubmit() with no submitter bypasses that: it submits the
    // form's current field values as-is (including the hidden `status`
    // field kept in sync below), with no button contributing its own value.
    e.preventDefault();
    filterBox.form.requestSubmit();
  });
  document.querySelectorAll("[data-status-btn]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (hasServerFilter) return; // let the form submit — need a fresh server render
      e.preventDefault(); // stop the form submit — filter client-side
      state.status = btn.getAttribute("data-status-btn");
      if (statusHidden) statusHidden.value = state.status;
      document.querySelectorAll("[data-status-btn]").forEach((b) => {
        const isActive = b === btn;
        b.classList.toggle("on", isActive);
        b.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      apply();
    });
  });
}

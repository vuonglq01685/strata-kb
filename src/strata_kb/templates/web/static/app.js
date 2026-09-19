// Strata UI enhancements. Progressive only — every page works without this file.
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

// data-autosubmit: search.html's token-budget slider and semantic-KNN
// checkbox used to auto-submit their form via an inline onchange handler —
// headers.py's CSP ships script-src 'self' with no 'unsafe-inline', which a
// browser refuses to run. Prefer requestSubmit() so the form's constraint
// validation and submit event still fire; fall back to submit() on engines
// without it (Safari < 16) so the control keeps working there too, instead
// of silently doing nothing the way the old inline handler never did.
document.addEventListener("change", (e) => {
  const el = e.target.closest("[data-autosubmit]");
  if (!el || !el.form) return;
  if (el.form.requestSubmit) el.form.requestSubmit();
  else el.form.submit();
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
    // Safari<16 has no HTMLFormElement.requestSubmit(). Bail before
    // preventDefault() so Enter falls through to the browser's native
    // implicit submission instead of being silently swallowed (calling
    // the missing method would throw after default was already blocked).
    if (!filterBox.form.requestSubmit) return;
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

// Generic live filter: an input with data-filter-list="<selector>" hides
// non-matching elements (matched against each element's data-text).
const TAG_CAP = 8;

// Captured once at script init (before any input can touch it), so the
// reset value always matches whatever copy the server actually rendered in
// left_rail.html instead of a hardcoded string that can drift from it.
const tagHintEl = document.querySelector("[data-tag-hint]");
const tagHintDefault = tagHintEl ? tagHintEl.textContent : "";

function capTagChips() {
  const visible = [...document.querySelectorAll("[data-tag-chip]")]
    .filter((el) => el.style.display !== "none");
  visible.forEach((el, i) => { if (i >= TAG_CAP) el.style.display = "none"; });
  if (tagHintEl) {
    tagHintEl.textContent = visible.length > TAG_CAP
      ? `+${visible.length - TAG_CAP} more — keep typing to narrow`
      : tagHintDefault;
  }
}

// The tree filter hides [data-tree-row] items but leaves the .tree-chapter
// header spans in place — without this, a filter can leave a bare chapter
// heading with none of its rows visible underneath it.
function syncTreeChapters() {
  document.querySelectorAll(".tree-chapter").forEach((chapter) => {
    let sib = chapter.nextElementSibling;
    let anyVisible = false;
    while (sib && !sib.classList.contains("tree-chapter")) {
      if (sib.matches("[data-tree-row]") && sib.style.display !== "none") {
        anyVisible = true;
        break;
      }
      sib = sib.nextElementSibling;
    }
    chapter.style.display = anyVisible ? "" : "none";
  });
}

document.querySelectorAll("[data-filter-list]").forEach((box) => {
  const sel = box.getAttribute("data-filter-list");
  box.addEventListener("input", () => {
    const q = box.value.trim().toLowerCase();
    let shown = 0;
    document.querySelectorAll(sel).forEach((el) => {
      const on = !q || (el.dataset.text || "").includes(q);
      el.style.display = on ? "" : "none";
      if (on) shown += 1;
    });
    // Scope the counter to the firing input's own form — the left rail's
    // "Search tags…" box (data-filter-list="[data-tag-chip]") has no form
    // ancestor and shares the page with the docs counter, so a page-global
    // querySelector would let typing in the tag box overwrite the docs
    // page's "N of M documents" label with a chip count instead.
    const form = box.closest("form");
    const count = form ? form.querySelector("[data-filter-count]") : null;
    if (count) {
      const total = parseInt(count.dataset.total, 10) || shown;
      count.textContent = `${shown} of ${total} ${count.dataset.noun || "shown"}`;
    }
    if (sel === "[data-tag-chip]") capTagChips();
    if (sel === "[data-tree-row]") syncTreeChapters();
  });
});
capTagChips();

// J = focus next search result, C = copy the focused result's citation.
document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
  const key = typeof e.key === "string" ? e.key.toLowerCase() : "";
  if (key === "j") {
    const cards = [...document.querySelectorAll(".result-card")];
    if (!cards.length) return;
    const current = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".result-card") : null;
    const next = cards[Math.min(cards.length - 1, cards.indexOf(current) + 1)];
    next.setAttribute("tabindex", "-1");
    next.focus();
    e.preventDefault();
  } else if (key === "c") {
    const current = document.activeElement && document.activeElement.closest
      ? document.activeElement.closest(".result-card") : null;
    const card = current || document.querySelector(".result-card");
    const btn = card && card.querySelector("[data-copy-text]");
    if (btn) { btn.click(); e.preventDefault(); }
  }
});

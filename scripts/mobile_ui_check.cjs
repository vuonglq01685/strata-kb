// Browser checks for the hub web UI on phones, foldables and iPads.
//   node scripts/mobile_ui_check.cjs <base_url> <out_dir> [--only <check>] [--baseline] [--login user:password]
// Login falls back to env UI_CHECK_LOGIN. Exit 0 = all checks pass, 1 = any FAIL line.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const MISSION = "M-airspace-filter";
// the remove-confirm banner only exists in the POST response, so the loop clicks Remove on the long-id row
const REG_CONFIRM = "/ui/registry?confirm=1";
const AUTHED_PAGES = [
  "/ui",
  "/ui?q=airspace",
  "/ui/docs",
  "/ui/docs/demo-doc?repo=demo-kb",
  "/ui/docs/demo-doc/1.1?repo=demo-kb",
  "/ui/docs/very-long-document-identifier-without-any-breaks-0123456789?repo=long-kb",
  "/ui/docs/very-long-document-identifier-without-any-breaks-0123456789/appendix-b.long-slug-section-identifier-0123456789?repo=long-kb",
  "/ui/docs/many-doc?repo=many-kb",
  "/ui/tickets",
  `/ui/tickets/${MISSION}?repo=ba-one`,
  `/ui/tickets/${MISSION}/${MISSION}-US2?repo=ba-one`,
  "/ui/code",
  "/ui/questions",
  "/ui/registry",
  REG_CONFIRM,
  "/ui/docs/does-not-exist?repo=demo-kb",
];
const LOGGED_OUT_PAGES = ["/ui/login"];
const VIEWPORTS = [
  [344, 882], [375, 667], [402, 874], [440, 956], [412, 915], [600, 900],
  [884, 1104], [744, 1133], [834, 1194], [1024, 1366], [1180, 820],
  [1366, 1024], [1440, 900],
];
const DESKTOP = new Set(["1440x900", "1366x1024"]);

const slug = (p) => p.replace(/^\/ui\/?/, "ui-").replace(/[^a-z0-9.]+/gi, "-").replace(/-+$/, "") || "ui";

// Chromium antialiasing is not byte-stable between runs (1-level colour jitter on a few
// pixels), so unequal PNGs still pass when every channel is within TOLERANCE.
const TOLERANCE = 8;
async function samePixels(page, a, b) {
  const enc = (buf) => `data:image/png;base64,${buf.toString("base64")}`;
  return page.evaluate(async ([ua, ub, tol]) => {
    const load = (u) => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = u; });
    const [ia, ib] = await Promise.all([load(ua), load(ub)]);
    if (ia.width !== ib.width || ia.height !== ib.height) return false;
    const px = (i) => {
      const c = document.createElement("canvas");
      c.width = i.width; c.height = i.height;
      const g = c.getContext("2d");
      g.drawImage(i, 0, 0);
      return g.getImageData(0, 0, i.width, i.height).data;
    };
    const [da, db] = [px(ia), px(ib)];
    for (let k = 0; k < da.length; k++) if (Math.abs(da[k] - db[k]) > tol) return false;
    return true;
  }, [enc(a), enc(b), TOLERANCE]);
}


// Compact top bar (< 1280px) and bottom tab bar (< 900px). Returns a failure detail or null.
// Clicks the search toggle, so it reloads the page afterwards to keep later checks clean.
async function shellProblem(page, iw) {
  if (iw >= 1280 || !(await page.$(".topbar"))) return null;
  const probe = (sel) => page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return { shown: false, w: 0, h: 0 };
    const r = el.getBoundingClientRect();
    return { shown: getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0, w: r.width, h: r.height };
  }, sel);
  const bad = [];
  for (const sel of [".topbar-status", ".nav-logout"]) if ((await probe(sel)).shown) bad.push(`${sel} visible`);
  if (!(await probe('[data-sheet-open="more"].topbar-btn')).shown) bad.push("more button hidden");
  if (!(await probe(".hub-dot")).shown) bad.push("hub-dot hidden");
  if (iw >= 900) {
    const input = await probe(".topbar-search input");
    if (!input.shown || input.w < 160) bad.push(`search input ${input.w}px < 160`);
    if ((await probe(".topbar-btn[data-search-toggle]")).shown) bad.push("search button visible >= 900");
    return bad.length ? bad.join("; ") : null;
  }
  const tabs = await page.$$eval(".tab-bar a", (as) => as.map((a) => a.getBoundingClientRect().height));
  if (!(await probe(".tab-bar")).shown) bad.push("tab-bar hidden");
  if (tabs.length !== 5 || tabs.some((h) => h < 44)) bad.push(`tab links ${JSON.stringify(tabs)} (want 5, each >= 44px)`);
  const covered = await page.evaluate(() => {
    window.scrollTo(0, document.documentElement.scrollHeight);
    const main = document.querySelector("main.content");
    const last = main.lastElementChild || main;
    const bar = document.querySelector(".tab-bar");
    return bar ? last.getBoundingClientRect().bottom - bar.getBoundingClientRect().top : 0;
  });
  if (covered > 0) bad.push(`main covered by tab-bar by ${Math.round(covered)}px`);
  if ((await probe(".topbar-search")).shown) bad.push("search visible before toggle");
  try { await page.click(".topbar-btn[data-search-toggle]", { timeout: 1500 }); }
  catch { bad.push("search button not clickable"); await page.reload({ waitUntil: "networkidle" }); return bad.join("; "); }
  const open = await page.evaluate(() => ({
    w: document.querySelector(".topbar-search").getBoundingClientRect().width,
    focused: document.activeElement === document.getElementById("global-search"),
    attr: document.querySelector(".topbar").hasAttribute("data-searching"),
  }));
  if (!open.attr) bad.push("data-searching not set after click");
  if (!open.focused) bad.push("search input not focused after click");
  if (open.w < iw * 0.8) bad.push(`open search ${Math.round(open.w)}px < 80% of ${iw}`);
  await page.reload({ waitUntil: "networkidle" });
  return bad.length ? bad.join("; ") : null;
}

// Each check: (ctx) => string | null, a failure detail or null. ctx = {page, shot, vp, p, out, cmp}.
const CHECKS = {
  overflow: async ({ page, vp }) => {
    const { sw, iw } = await page.evaluate(() => ({
      sw: document.documentElement.scrollWidth,
      iw: window.innerWidth,
    }));
    if (sw > iw) return `scrollWidth ${sw} > innerWidth ${iw}`;
    return shellProblem(page, iw);
  },
  "desktop-unchanged": async ({ shot, vp, p, out, cmp }) => {
    if (!DESKTOP.has(vp)) return null;
    const base = path.join(out, "baseline", vp, `${slug(p)}.png`);
    if (!fs.existsSync(base)) return `no baseline ${base}`;
    const want = fs.readFileSync(base);
    if (shot.equals(want) || (await samePixels(cmp, shot, want))) return null;
    const actual = path.join(out, vp, `${slug(p)}.diff-actual.png`);
    fs.writeFileSync(actual, shot);
    return `differs from baseline, see ${actual}`;
  },
};

// ---- sheet suites: stateful checks that need their own fresh page/context ----
const SECTION = "/ui/docs/demo-doc/1.1?repo=demo-kb";
const MANY = "/ui/docs/many-doc?repo=many-kb";
const SHEET_PAGES = ["/ui", "/ui/docs", SECTION, `/ui/tickets/${MISSION}?repo=ba-one`];
const visible = (page, sel) => page.evaluate((s) => [...document.querySelectorAll(s)].some((el) => {
  const r = el.getBoundingClientRect();
  return getComputedStyle(el).display !== "none" && getComputedStyle(el).visibility !== "hidden" && r.width > 0 && r.height > 0;
}), sel);
const sheetState = (page, id) => page.evaluate((i) => {
  const el = document.getElementById(i);
  const r = el.getBoundingClientRect();
  return {
    open: el.hasAttribute("data-open"),
    inside: el.contains(document.activeElement),
    locked: document.documentElement.classList.contains("sheet-locked"),
    h: r.height, ih: window.innerHeight,
    dialog: el.getAttribute("role") === "dialog" && el.getAttribute("aria-modal") === "true" && !!el.getAttribute("aria-label"),
  };
}, id);
const openAny = (page) => page.evaluate(() => !!document.querySelector("[data-open]") || document.documentElement.classList.contains("sheet-locked"));
async function authed(browser, state, vp, extra = {}) {
  const context = await browser.newContext({ viewport: { width: vp[0], height: vp[1] }, storageState: state, ...extra });
  context.setDefaultTimeout(4000);
  return { context, page: await context.newPage() };
}
async function visibleTriggers(page) {
  return page.$$eval("[data-sheet-open]", (els) => els.filter((el) => {
    const r = el.getBoundingClientRect();
    return getComputedStyle(el).display !== "none" && r.width > 0 && r.height > 0;
  }).map((el) => el.getAttribute("data-sheet-open")));
}

const SUITES = {
  sheets: async ({ browser, base, state }) => {
    const bad = [];
    for (const vp of [[402, 874], [1180, 820]]) {
      const { context, page } = await authed(browser, state, vp);
      for (const p of SHEET_PAGES) {
        await page.goto(base + p, { waitUntil: "networkidle" });
        const ids = await visibleTriggers(page);
        const at = `${vp.join("x")} ${p}`;
        if (vp[0] === 402 && !ids.includes("more")) bad.push(`${at}: no visible more trigger`);
        for (const id of ids) {
          for (const how of ["scrim", "esc", "button"]) {
            const tag = `${at} ${id}/${how}`;
            await page.goto(base + p, { waitUntil: "networkidle" });
            const trig = page.locator(`[data-sheet-open="${id}"]`).filter({ visible: true }).first();
            await trig.click();
            await page.waitForTimeout(350);
            const st = await sheetState(page, id);
            const exp = await trig.getAttribute("aria-expanded");
            if (!st.open) { bad.push(`${tag}: no data-open`); continue; }
            if (exp !== "true") bad.push(`${tag}: aria-expanded=${exp}`);
            if (!st.inside) bad.push(`${tag}: focus not inside sheet`);
            if (!st.locked) bad.push(`${tag}: html not sheet-locked`);
            if (st.h > st.ih * 0.8 + 1) bad.push(`${tag}: height ${Math.round(st.h)} > 80% of ${st.ih}`);
            if (!st.dialog) bad.push(`${tag}: missing dialog semantics`);
            if (vp[0] === 402 && id === "rail-left" && (await visible(page, "#rail-left .nav"))) bad.push(`${tag}: .rail-left .nav visible in sheet`);
            if (vp[0] >= 600) {
              const w = await page.evaluate((i) => document.getElementById(i).getBoundingClientRect().width, id);
              if (w > 641) bad.push(`${tag}: width ${Math.round(w)} > 640`);
            }
            if (how === "scrim") await page.mouse.click(vp[0] / 2, 4);
            else if (how === "esc") await page.keyboard.press("Escape");
            else await page.click(`#${id} [data-sheet-close]`);
            await page.waitForTimeout(350);
            const after = await page.evaluate((i) => ({
              open: !!document.querySelector("[data-open]"),
              locked: document.documentElement.classList.contains("sheet-locked"),
              onTrigger: document.activeElement === document.querySelector(`[data-sheet-open="${i}"]:not([style*="none"])`)
                || document.activeElement?.getAttribute("data-sheet-open") === i,
              exp: document.activeElement?.getAttribute("aria-expanded"),
            }), id);
            if (after.open || after.locked) bad.push(`${tag}: still open after close`);
            if (!after.onTrigger) bad.push(`${tag}: focus not back on trigger`);
            if (after.exp === "true") bad.push(`${tag}: trigger aria-expanded still true`);
          }
        }
      }
      // TOC link inside right-rail sheet closes it and changes the hash
      await page.goto(base + SECTION, { waitUntil: "networkidle" });
      await page.locator('[data-sheet-open="rail-right"]').filter({ visible: true }).first().click();
      await page.waitForTimeout(350);
      const before = await page.evaluate(() => location.hash);
      await page.click("#rail-right a.toc-link");
      await page.waitForTimeout(350);
      const after = await page.evaluate(() => ({ hash: location.hash, open: !!document.querySelector("[data-open]"), locked: document.documentElement.classList.contains("sheet-locked") }));
      if (after.open || after.locked) bad.push(`${vp.join("x")} toc link: sheet still open`);
      if (after.hash === before || !after.hash) bad.push(`${vp.join("x")} toc link: hash unchanged (${after.hash})`);
      await context.close();
    }
    return bad;
  },

  "resize-closes-sheet": async ({ browser, base, state }) => {
    const bad = [];
    const { context, page } = await authed(browser, state, [402, 874]);
    await page.goto(base + SECTION, { waitUntil: "networkidle" });
    await page.click('[data-sheet-open="rail-left"]');
    await page.waitForTimeout(350);
    if (!(await openAny(page))) bad.push("left sheet did not open before resize");
    await page.setViewportSize({ width: 1366, height: 1024 });
    await page.waitForTimeout(350);
    if (await openAny(page)) bad.push("sheet still open / sheet-locked after resize to 1366");
    for (const sel of [".rail-left", ".rail-right"]) {
      if (!(await visible(page, sel))) bad.push(`${sel} not visible after resize`);
      else {
        const pos = await page.$eval(sel, (el) => getComputedStyle(el).position);
        if (pos === "fixed") bad.push(`${sel} still position:fixed after resize`);
      }
    }
    await context.close();
    return bad;
  },

  "bfcache-no-sheet": async ({ browser, base, state }) => {
    const bad = [];
    const { context, page } = await authed(browser, state, [402, 874]);
    await page.goto(base + SECTION, { waitUntil: "networkidle" });
    await page.click('[data-sheet-open="rail-left"]');
    await page.waitForTimeout(350);
    const row = page.locator("#rail-left a.tree-row:not(.active)").first();
    if (await row.count()) await row.click(); else await page.click("#rail-left a.tree-row");
    await page.waitForLoadState("networkidle");
    await page.goBack({ waitUntil: "networkidle" });
    await page.waitForTimeout(350);
    if (await openAny(page)) bad.push("sheet open / sheet-locked after goBack");
    await context.close();
    return bad;
  },

  nojs: async ({ browser, base, state }) => {
    const bad = [];
    const { context, page } = await authed(browser, state, [402, 874], { javaScriptEnabled: false });
    for (const p of [SECTION, "/ui", `/ui/tickets/${MISSION}?repo=ba-one`]) {
      await page.goto(base + p, { waitUntil: "load" });
      const t = `nojs ${p}`;
      if (!(await visible(page, ".tab-bar a"))) bad.push(`${t}: tab-bar links hidden`);
      if (await visible(page, ".sheet-pill")) bad.push(`${t}: sheet-pill visible`);
      if (await visible(page, ".topbar-btn")) bad.push(`${t}: topbar-btn visible`);
      if (!(await visible(page, ".topbar-search input"))) bad.push(`${t}: search input hidden`);
      for (const sel of [".rail-left", ".rail-right", ".more-sheet"]) {
        if (sel === ".rail-right" && !(await page.$(sel + " > *"))) continue;
        const info = await page.evaluate((s) => {
          const el = document.querySelector(s); const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
          return { pos: cs.position, shown: cs.display !== "none" && cs.visibility !== "hidden" && r.height > 0, right: r.right, inView: r.right <= window.innerWidth + 1 };
        }, sel);
        if (info.pos === "fixed") bad.push(`${t}: ${sel} position fixed`);
        if (!info.shown) bad.push(`${t}: ${sel} not visible`);
        if (!info.inView) bad.push(`${t}: ${sel} overflows viewport`);
      }
      if (p === SECTION && !(await visible(page, ".rail-left .tree-list"))) bad.push(`${t}: tree-list hidden`);
      const ov = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      if (ov > 0) bad.push(`${t}: horizontal overflow ${ov}px`);
    }
    await context.close();
    return bad;
  },

  // coarse pointer: every control >= 44px, inputs >= 16px (no iOS focus zoom); sheets opened so rail controls count
  "touch-targets": async ({ browser, base, state }) => {
    const bad = [];
    const SEL = ".nav a, .tree-row, .chip, .seg, .btn, .level-tabs a, .switch, .pager a, .result-card footer button, .result-card footer a, .tab-bar a, .sheet-pill, .topbar-btn, .toc-link";
    const scan = (page) => page.evaluate((sel) => {
      const shown = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return cs.display !== "none" && cs.visibility !== "hidden" && r.width > 0 && r.height > 0; };
      const name = (el) => `${el.tagName.toLowerCase()}.${[...el.classList].join(".")}`;
      const out = [];
      for (const el of document.querySelectorAll(sel)) {
        if (!shown(el)) continue;
        const r = el.getBoundingClientRect();
        const tall = el.matches(".chip, .toc-link");
        if (r.height < 43.5 || (!tall && r.width < 43.5)) out.push(`${name(el)} ${r.width.toFixed(1)}x${r.height.toFixed(1)}`);
      }
      for (const el of document.querySelectorAll("input, select, textarea")) {
        if (!shown(el) || el.type === "hidden") continue;
        const fs = parseFloat(getComputedStyle(el).fontSize);
        if (fs < 16) out.push(`${name(el)} font-size ${fs}px`);
      }
      return [...new Set(out)];
    }, SEL);
    const PAGES = ["/ui", "/ui?q=airspace", "/ui/docs", SECTION, `/ui/tickets/${MISSION}?repo=ba-one`, "/ui/registry"];
    for (const [vp, extra] of [[[402, 874], { hasTouch: true, isMobile: true }], [[1366, 1024], { hasTouch: true }]]) {
      const { context, page } = await authed(browser, state, vp, extra);
      for (const p of PAGES) {
        await page.goto(base + p, { waitUntil: "networkidle" });
        const at = `${vp.join("x")} ${p}`;
        for (const d of await scan(page)) bad.push(`${at}: ${d}`);
        if (vp[0] === 1366) {
          if (!(await visible(page, ".rail-right")) && p === SECTION) bad.push(`${at}: .rail-right hidden (want three columns)`);
          continue;
        }
        for (const id of await visibleTriggers(page)) {
          await page.goto(base + p, { waitUntil: "networkidle" });
          await page.locator(`[data-sheet-open="${id}"]`).filter({ visible: true }).first().click();
          await page.waitForTimeout(350);
          for (const d of await scan(page)) bad.push(`${at}: ${d}`);
        }
      }
      await context.close();
    }
    return [...new Set(bad)];
  },

  "sheet-scrolls-inside": async ({ browser, base, state }) => {
    const bad = [];
    const { context, page } = await authed(browser, state, [402, 874]);
    await page.goto(base + MANY, { waitUntil: "networkidle" });
    await page.click('[data-sheet-open="rail-left"]');
    await page.waitForTimeout(350);
    await page.evaluate(() => window.scrollTo(0, 120)); // programmatic scroll still works under the lock
    const y0 = await page.evaluate(() => window.scrollY);
    const m = await page.evaluate(() => { const s = document.getElementById("rail-left"); return { sh: s.scrollHeight, ch: s.clientHeight }; });
    if (m.sh <= m.ch) bad.push(`scrollHeight ${m.sh} <= clientHeight ${m.ch}`);
    await page.mouse.move(201, 600);
    await page.mouse.wheel(0, 400);
    await page.waitForTimeout(300);
    const after = await page.evaluate(() => ({ y: window.scrollY, st: document.getElementById("rail-left").scrollTop }));
    if (after.y !== y0) bad.push(`window.scrollY ${y0} -> ${after.y}`);
    if (after.st <= 0) bad.push("sheet did not scroll");
    await context.close();
    return bad;
  },
};

async function main() {
  const args = process.argv.slice(2);
  const flag = (n) => args.includes(n);
  const val = (n) => (flag(n) ? args[args.indexOf(n) + 1] : undefined);
  const [base, out] = args.filter((a, i) => !a.startsWith("--") && !["--only", "--login"].includes(args[i - 1]));
  if (!base || !out) throw new Error("usage: mobile_ui_check.cjs <base_url> <out_dir> [--only c] [--baseline] [--login u:p]");
  const only = val("--only");
  if (only && !CHECKS[only] && !SUITES[only]) throw new Error(`unknown check ${only}; have ${[...Object.keys(CHECKS), ...Object.keys(SUITES)]}`);
  const baseline = flag("--baseline");
  const [user, ...pw] = (val("--login") || process.env.UI_CHECK_LOGIN || "").split(":");
  if (!user || !pw.length) throw new Error("need --login user:password (or UI_CHECK_LOGIN)");
  const names = only ? [only].filter((n) => CHECKS[n]) : Object.keys(CHECKS);
  const suites = only ? [only].filter((n) => SUITES[n]) : Object.keys(SUITES);

  const browser = await chromium.launch();
  const login = await browser.newContext();
  const resp = await login.request.post(`${base}/ui/login`, { form: { username: user, password: pw.join(":") } });
  // a wrong password re-renders the login form with HTTP 200, so check where we ended up
  if (!resp.ok() || new URL(resp.url()).pathname === "/ui/login") throw new Error(`login failed: ${resp.status()} ${resp.url()}`);
  const state = await login.storageState();
  await login.close();

  const cmp = await browser.newPage(); // blank page for pixel compares (app pages' CSP blocks data: images)
  let failures = 0;
  for (const name of baseline ? [] : suites) {
    const found = await SUITES[name]({ browser, base, state }).catch((e) => [`error: ${e.message.split("\n")[0]}`]);
    for (const detail of found) {
      failures++;
      console.log(`FAIL ${name}: ${detail}`);
    }
  }
  for (const [w, h] of VIEWPORTS) {
    if (!baseline && !names.length) break; // suite-only run
    const vp = `${w}x${h}`;
    // baseline and desktop-unchanged only look at the desktop viewports
    if ((baseline || only === "desktop-unchanged") && !DESKTOP.has(vp)) continue;
    for (const [pages, storageState] of [[AUTHED_PAGES, state], [LOGGED_OUT_PAGES, undefined]]) {
      const context = await browser.newContext({ viewport: { width: w, height: h }, storageState });
      const page = await context.newPage();
      for (const p of pages) {
        const r = await page.goto(base + p, { waitUntil: "networkidle" });
        const want = p.startsWith("/ui/docs/does-not-exist") ? 404 : 200;
        const bounced = pages === AUTHED_PAGES && new URL(page.url()).pathname === "/ui/login";
        if (r.status() !== want || bounced) {
          const msg = `status ${r.status()} (want ${want})${bounced ? ` / redirected to ${page.url()}` : ""}`;
          if (baseline) throw new Error(`bad baseline page ${vp} ${p}: ${msg}`);
          failures++;
          console.log(`FAIL load ${vp} ${p}: ${msg}`);
          continue;
        }
        if (p === REG_CONFIRM) {
          await Promise.all([
            page.waitForNavigation({ waitUntil: "networkidle" }),
            page.click('.reg-grid:has-text("my_very_long") .btn-quiet'),
          ]);
          if (!(await page.$(".reg-confirm"))) throw new Error(`no .reg-confirm banner at ${vp}`);
        }
        const shot = await page.screenshot({ fullPage: true, animations: "disabled" });
        const dir = path.join(out, baseline ? "baseline" : "", vp);
        fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(path.join(dir, `${slug(p)}.png`), shot);
        if (baseline) continue;
        for (const name of names) {
          const detail = await CHECKS[name]({ page, shot, vp, p, out, cmp });
          if (detail) {
            failures++;
            console.log(`FAIL ${name} ${vp} ${p}: ${detail}`);
          }
        }
      }
      await context.close();
    }
  }
  await browser.close();
  console.log(baseline ? "baseline written" : failures ? `${failures} failure(s)` : "all checks pass");
  process.exit(failures ? 1 : 0);
}

main().catch((e) => { console.error(e.message); process.exit(2); });

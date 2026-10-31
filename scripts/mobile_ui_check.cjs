// Browser checks for the hub web UI on phones, foldables and iPads.
//   node scripts/mobile_ui_check.cjs <base_url> <out_dir> [--only <check>] [--baseline] [--login user:password]
// Login falls back to env UI_CHECK_LOGIN. Exit 0 = all checks pass, 1 = any FAIL line.
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const MISSION = "M-airspace-filter";
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

// Each check: (ctx) => string | null, a failure detail or null. ctx = {page, shot, vp, p, out, cmp}.
const CHECKS = {
  overflow: async ({ page, vp }) => {
    const { sw, iw } = await page.evaluate(() => ({
      sw: document.documentElement.scrollWidth,
      iw: window.innerWidth,
    }));
    return sw > iw ? `scrollWidth ${sw} > innerWidth ${iw}` : null;
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

async function main() {
  const args = process.argv.slice(2);
  const flag = (n) => args.includes(n);
  const val = (n) => (flag(n) ? args[args.indexOf(n) + 1] : undefined);
  const [base, out] = args.filter((a, i) => !a.startsWith("--") && !["--only", "--login"].includes(args[i - 1]));
  if (!base || !out) throw new Error("usage: mobile_ui_check.cjs <base_url> <out_dir> [--only c] [--baseline] [--login u:p]");
  const only = val("--only");
  if (only && !CHECKS[only]) throw new Error(`unknown check ${only}; have ${Object.keys(CHECKS)}`);
  const baseline = flag("--baseline");
  const [user, ...pw] = (val("--login") || process.env.UI_CHECK_LOGIN || "").split(":");
  if (!user || !pw.length) throw new Error("need --login user:password (or UI_CHECK_LOGIN)");
  const names = only ? [only] : Object.keys(CHECKS);

  const browser = await chromium.launch();
  const login = await browser.newContext();
  const resp = await login.request.post(`${base}/ui/login`, { form: { username: user, password: pw.join(":") } });
  if (!resp.ok()) throw new Error(`login failed: ${resp.status()}`);
  const state = await login.storageState();
  await login.close();

  const cmp = await browser.newPage(); // blank page for pixel compares (app pages' CSP blocks data: images)
  let failures = 0;
  for (const [w, h] of VIEWPORTS) {
    const vp = `${w}x${h}`;
    // baseline and desktop-unchanged only look at the desktop viewports
    if ((baseline || only === "desktop-unchanged") && !DESKTOP.has(vp)) continue;
    for (const [pages, storageState] of [[AUTHED_PAGES, state], [LOGGED_OUT_PAGES, undefined]]) {
      const context = await browser.newContext({ viewport: { width: w, height: h }, storageState });
      const page = await context.newPage();
      for (const p of pages) {
        await page.goto(base + p, { waitUntil: "networkidle" });
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

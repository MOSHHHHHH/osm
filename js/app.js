/* ---------------------------------------------------------------------
 * app.js — front-end logic for the offline maps hub
 *
 * Data sources (all same-origin, relative to this page):
 *   data/osmand-data.json     [{ fileName, updatedDate, url, "zip-osm-file", originalZipUrl }]
 *     - url: best current download link. If "zip-osm-file" is true, url points to OsmAnd's
 *       own .zip (not yet mirrored here) and the file must be extracted before use; if false,
 *       url points to our own hosted, ready-to-use .obf file.
 *     - originalZipUrl: OsmAnd's own .zip link, ALWAYS present regardless of hosting status.
 *   data/mapsTags.json        [{ fileName, geo:[{en,he}, ...], emoji }]
 *     - geo is ordered broadest-to-most-specific (continent, country, region, ...) with only
 *       as many levels as are actually known - no fixed shape, nothing padded with nulls.
 *   data/moovitdos-link.json  { path, updatedDate }
 *   data/update-status.json   { osmand-status, moovitdos-status, update-date }
 *     - Binary per service: true means the last check succeeded, false means it didn't
 *       (e.g. OsmAnd's own site was unreachable). Individual files still being served as a
 *       .zip fallback is normal/expected and is not reflected here.
 *
 * Analytics: every download fires a fire-and-forget POST to the Google Form
 * below with the file name and this browser's running download counter
 * (kept in localStorage, never sent anywhere except this form).
 * ------------------------------------------------------------------- */

const FORM_ACTION_URL =
  "https://docs.google.com/forms/u/0/d/e/1FAIpQLScuXM88KBakEGOWv-s5_qz3N5Y2K-T501R0zi5UwHij9gyICg/formResponse";
const FORM_ENTRY_FILE_NAME = "entry.1612470091";
const FORM_ENTRY_DOWNLOAD_COUNTER = "entry.307147373";

// Fixed, exact file names - the Israel/Yosh buttons always use these, no searching/guessing.
const ISRAEL_FILE_NAME = "israel_asia_2.obf";
const YOSH_FILE_NAME = "palestine_asia_2.obf";

const ZIP_WARNING_SECONDS = 7;

let osmandData = [];
let mapsTags = [];
let moovitdosLink = { path: null, updatedDate: null };
let updateStatus = { "osmand-status": true, "moovitdos-status": true, "update-date": null };

// ------------------------------------------------------------------
// Data loading
// ------------------------------------------------------------------

async function fetchJson(path, fallback) {
  try {
    const res = await fetch(path, { cache: "no-store" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn("Failed to load", path, err);
    return fallback;
  }
}

async function loadAllData() {
  [osmandData, mapsTags, moovitdosLink, updateStatus] = await Promise.all([
    fetchJson("data/osmand-data.json", []),
    fetchJson("data/mapsTags.json", []),
    fetchJson("data/moovitdos-link.json", { path: null, updatedDate: null }),
    fetchJson("data/update-status.json", {
      "osmand-status": true,
      "moovitdos-status": true,
      "update-date": null,
    }),
  ]);

  renderStatus();
  renderButtonDates();
}

function findOsmandEntry(fileName) {
  const lower = fileName.toLowerCase();
  return osmandData.find((e) => e.fileName.toLowerCase() === lower) || null;
}

// ------------------------------------------------------------------
// Status pill + modal (binary: ok / error, per service)
// ------------------------------------------------------------------

function renderStatus() {
  const osmandOk = updateStatus["osmand-status"];
  const moovitdosOk = updateStatus["moovitdos-status"];
  const hasError = !osmandOk || !moovitdosOk;

  const pill = document.getElementById("statusPill");
  pill.classList.remove("loading");

  document.getElementById("statusBadge").textContent = hasError ? "❎" : "✅";
  document.getElementById("statusText").textContent = hasError
    ? "יתכן שחלק מהנתונים לא מעודכנים"
    : "כל הנתונים מעודכנים";

  const dateStr = formatDate(updateStatus["update-date"]);

  document.getElementById("modalOsmandBadge").textContent = osmandOk ? "✅" : "❎";
  document.getElementById("modalOsmandText").textContent = osmandOk
    ? "כל התוכן מעודכן, נבדק לאחרונה"
    : "תקלה בעדכון, יתכן שחלק מהנתונים לא מעודכנים. אנו פועלים לתקן את התקלה.";
  document.getElementById("modalOsmandDate").textContent = dateStr;

  document.getElementById("modalMoovitdosBadge").textContent = moovitdosOk ? "✅" : "❎";
  document.getElementById("modalMoovitdosText").textContent = moovitdosOk
    ? "כל התוכן מעודכן, נבדק לאחרונה"
    : "תקלה בעדכון, יתכן שחלק מהנתונים לא מעודכנים. אנו פועלים לתקן את התקלה.";
  document.getElementById("modalMoovitdosDate").textContent = dateStr;
}

function formatDate(isoDateOrDatetime) {
  if (!isoDateOrDatetime) return "";
  try {
    const d = new Date(isoDateOrDatetime);
    return d.toLocaleString("he-IL", {
      dateStyle: "medium",
      timeStyle: isoDateOrDatetime.includes("T") ? "short" : undefined,
    });
  } catch {
    return isoDateOrDatetime;
  }
}

function setupModal() {
  const overlay = document.getElementById("statusModal");
  document.getElementById("statusPill").addEventListener("click", () => {
    overlay.classList.add("open");
  });
  document.getElementById("modalCloseBtn").addEventListener("click", () => {
    overlay.classList.remove("open");
  });
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("open");
  });
}

// ------------------------------------------------------------------
// Zip-extraction warning modal (OsmAnd .zip fallback downloads only - never for Moovitdos)
// ------------------------------------------------------------------

let zipWarningTimer = null;

function showZipWarningModal() {
  const overlay = document.getElementById("zipWarningModal");
  const countdownEl = document.getElementById("zipWarningCountdown");
  let remaining = ZIP_WARNING_SECONDS;
  countdownEl.textContent = remaining;

  overlay.classList.add("open");
  clearInterval(zipWarningTimer);
  zipWarningTimer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      closeZipWarningModal();
      return;
    }
    countdownEl.textContent = remaining;
  }, 1000);
}

function closeZipWarningModal() {
  clearInterval(zipWarningTimer);
  document.getElementById("zipWarningModal").classList.remove("open");
}

function setupZipWarningModal() {
  document.getElementById("zipWarningCloseBtn").addEventListener("click", closeZipWarningModal);
  document.getElementById("zipWarningModal").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeZipWarningModal();
  });
}

// ------------------------------------------------------------------
// Download + analytics
// ------------------------------------------------------------------

function bumpDownloadCounter() {
  const current = parseInt(localStorage.getItem("downloadCounter") || "0", 10);
  const next = current + 1;
  localStorage.setItem("downloadCounter", String(next));
  return next;
}

function pingAnalytics(fileName, counter) {
  const formData = new FormData();
  formData.append(FORM_ENTRY_FILE_NAME, fileName);
  formData.append(FORM_ENTRY_DOWNLOAD_COUNTER, String(counter));

  // Google Forms doesn't return CORS headers, so this is a fire-and-forget request.
  fetch(FORM_ACTION_URL, { method: "POST", mode: "no-cors", body: formData }).catch(() => {
    /* analytics failures should never block a download */
  });
}

function triggerDownload(url, suggestedName) {
  const link = document.createElement("a");
  link.href = url;
  if (suggestedName) link.download = suggestedName;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

/**
 * @param {string} fileName - used for the analytics ping and suggested download name.
 * @param {string} url - the actual URL to download.
 * @param {boolean} isOsmandZipFallback - true when this is an OsmAnd .zip that still needs
 *        manual extraction; triggers the warning modal. Never true for Moovitdos.
 */
function downloadFile(fileName, url, isOsmandZipFallback) {
  const counter = bumpDownloadCounter();
  pingAnalytics(fileName, counter);
  triggerDownload(url, fileName);
  if (isOsmandZipFallback) {
    showZipWarningModal();
  }
}

// ------------------------------------------------------------------
// Big buttons: OsmAnd Israel / Yosh / Moovitdos
// ------------------------------------------------------------------

function handleFixedOsmandButton(fixedFileName, label) {
  const entry = findOsmandEntry(fixedFileName);
  if (!entry || !entry.originalZipUrl) {
    alert(`המפה עבור "${label}" עדיין לא זמינה במאגר. נסו שוב מאוחר יותר.`);
    return;
  }
  // Always the original OsmAnd .zip, by design - no dependency on our own hosting pipeline.
  downloadFile(entry.fileName + ".zip", entry.originalZipUrl, true);
}

function handleMoovitdosButton() {
  if (!moovitdosLink.path) {
    alert("קובץ הנתונים למובידוס עדיין לא זמין. נסו שוב מאוחר יותר.");
    return;
  }
  downloadFile(moovitdosLink.path.split("/").pop(), moovitdosLink.path, false);
}

function setupBigButtons() {
  document
    .getElementById("btnIsrael")
    .addEventListener("click", () => handleFixedOsmandButton(ISRAEL_FILE_NAME, "ישראל"));
  document
    .getElementById("btnYosh")
    .addEventListener("click", () => handleFixedOsmandButton(YOSH_FILE_NAME, "יהודה ושומרון"));
  document.getElementById("btnMoovitdos").addEventListener("click", handleMoovitdosButton);
}

function renderButtonDates() {
  const israel = findOsmandEntry(ISRAEL_FILE_NAME);
  const yosh = findOsmandEntry(YOSH_FILE_NAME);

  document.getElementById("israelUpdatedDate").textContent = israel
    ? `עודכן: ${formatDate(israel.updatedDate)}`
    : "";
  document.getElementById("yoshUpdatedDate").textContent = yosh
    ? `עודכן: ${formatDate(yosh.updatedDate)}`
    : "";
  document.getElementById("moovitdosUpdatedDate").textContent = moovitdosLink.updatedDate
    ? `עודכן: ${formatDate(moovitdosLink.updatedDate)}`
    : "";
}

// ------------------------------------------------------------------
// Search
// ------------------------------------------------------------------

function tagsFor(fileName) {
  return mapsTags.find((t) => t.fileName === fileName) || null;
}

function matchesQuery(fileName, tags, query) {
  const q = query.toLowerCase();
  if (fileName.toLowerCase().includes(q)) return true;
  if (!tags || !Array.isArray(tags.geo)) return false;
  return tags.geo.some(
    (level) =>
      (level.he && level.he.toLowerCase().includes(q)) ||
      (level.en && level.en.toLowerCase().includes(q))
  );
}

function stripObfExtension(fileName) {
  return fileName.replace(/\.obf$/i, "");
}

function renderResultTagsLine(tags) {
  if (!tags || !Array.isArray(tags.geo)) return "";
  return tags.geo
    .map((level) => level.he)
    .filter(Boolean)
    .join(" · ");
}

function renderResults(query) {
  const resultsEl = document.getElementById("results");
  const hintEl = document.getElementById("searchHint");
  resultsEl.innerHTML = "";

  if (query.length < 2) {
    hintEl.style.display = "block";
    hintEl.textContent = "הקלידו לפחות 2 תווים כדי להתחיל בחיפוש";
    return;
  }

  hintEl.style.display = "none";

  const matches = osmandData.filter((entry) =>
    matchesQuery(entry.fileName, tagsFor(entry.fileName), query)
  );

  if (matches.length === 0) {
    resultsEl.innerHTML = `<div class="search-empty">לא נמצאו מפות התואמות לחיפוש.</div>`;
    return;
  }

  matches.slice(0, 60).forEach((entry) => {
    const tags = tagsFor(entry.fileName);
    const emoji = tags?.emoji || "🗂️";
    const tagsLine = renderResultTagsLine(tags);
    const fileLine = stripObfExtension(entry.fileName);
    const dateLine = `עודכן: ${formatDate(entry.updatedDate)}`;

    const row = document.createElement("div");
    row.className = "result-item";
    row.innerHTML = `
      <span class="label">
        <span class="emoji">${emoji}</span>
        <span class="label-text">
          ${tagsLine ? `<span class="tags-line">${tagsLine}</span>` : ""}
          <span class="file-line">${fileLine}</span>
          <span class="date-line">${dateLine}</span>
        </span>
      </span>
      <button type="button">הורדה</button>
    `;
    row.querySelector("button").addEventListener("click", () => {
      downloadFile(entry.fileName, entry.url, Boolean(entry["zip-osm-file"]));
    });
    resultsEl.appendChild(row);
  });

  // Re-parse just the results list (Twemoji only needs to touch newly inserted emoji).
  if (window.twemoji) twemoji.parse(resultsEl, { className: "twemoji" });
}

function setupSearch() {
  const input = document.getElementById("searchInput");
  input.addEventListener("input", () => renderResults(input.value.trim()));
}

// ------------------------------------------------------------------
// Init
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  setupModal();
  setupZipWarningModal();
  setupBigButtons();
  setupSearch();
  await loadAllData();
  if (window.twemoji) twemoji.parse(document.body, { className: "twemoji" });
});

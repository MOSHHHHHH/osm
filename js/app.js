/* ---------------------------------------------------------------------
 * app.js — front-end logic for the offline maps hub
 *
 * Data sources (all same-origin, relative to this page):
 *   data/osmand-data.json     [{ fileName, updatedDate, url }]
 *   data/mapsTags.json        [{ fileName, hebrewTags:{continent,country,city},
 *                                 englishTags:{...}, emoji }]
 *   data/moovitdos-link.json  { path, updatedDate }
 *   data/update-status.json   { osmand-status, moovitdos-status, osmand-in-progress,
 *                                 osmand-pending-files, osmand-oversized-files, update-date }
 *
 * Analytics: every download fires a fire-and-forget POST to the Google Form
 * below with the file name and this browser's running download counter
 * (kept in localStorage, never sent anywhere except this form).
 * ------------------------------------------------------------------- */

const FORM_ACTION_URL =
  "https://docs.google.com/forms/u/0/d/e/1FAIpQLScuXM88KBakEGOWv-s5_qz3N5Y2K-T501R0zi5UwHij9gyICg/formResponse";
const FORM_ENTRY_FILE_NAME = "entry.1612470091";
const FORM_ENTRY_DOWNLOAD_COUNTER = "entry.307147373";

const OSMAND_ISRAEL_KEYWORDS = ["israel"];
const OSMAND_YOSH_KEYWORDS = ["west-bank", "west bank", "palestine", "judea", "samaria", "yosh"];

let osmandData = [];
let mapsTags = [];
let moovitdosLink = { path: null, updatedDate: null };
let updateStatus = {
  "osmand-status": true,
  "moovitdos-status": true,
  "osmand-in-progress": false,
  "osmand-pending-files": [],
  "osmand-oversized-files": [],
  "update-date": null,
};

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
      "osmand-in-progress": false,
      "osmand-pending-files": [],
      "osmand-oversized-files": [],
      "update-date": null,
    }),
  ]);

  renderStatus();
}

// ------------------------------------------------------------------
// Status pill + modal
// ------------------------------------------------------------------

function renderStatus() {
  const osmandOk = updateStatus["osmand-status"];
  const moovitdosOk = updateStatus["moovitdos-status"];
  const hasError = !osmandOk || !moovitdosOk;
  // "Updating now" only applies when there's no error - a real error always wins.
  const isUpdatingNow = !hasError && updateStatus["osmand-in-progress"];

  const pill = document.getElementById("statusPill");
  pill.classList.remove("loading");
  pill.classList.toggle("in-progress", isUpdatingNow);

  let topBadge = "✅";
  let topText = "כל הנתונים מעודכנים";
  if (hasError) {
    topBadge = "❎";
    topText = "יתכן שחלק מהנתונים לא מעודכנים";
  } else if (isUpdatingNow) {
    topBadge = "🔄";
    topText = "עדכון הנתונים מתבצע כעת";
  }
  document.getElementById("statusBadge").textContent = topBadge;
  document.getElementById("statusText").textContent = topText;

  const dateStr = formatDate(updateStatus["update-date"]);

  // OsmAnd row: error > updating now > all good.
  let osmandBadge = "✅";
  let osmandText = "כל התוכן מעודכן, נבדק לאחרונה";
  if (!osmandOk) {
    osmandBadge = "❎";
    osmandText = "תקלה בעדכון, יתכן שחלק מהנתונים לא מעודכנים. אנו פועלים לתקן את התקלה.";
  } else if (updateStatus["osmand-in-progress"]) {
    osmandBadge = "🔄";
    osmandText =
      "עדכון הנתונים מתבצע כעת - השרתים שלנו עובדים במלא המרץ לעדכן את כל הקבצים. " +
      "ניתן לנסות שוב בעוד מספר שעות או להוריד כעת את הגרסה האחרונה שעודכנה.";
  }
  document.getElementById("modalOsmandBadge").textContent = osmandBadge;
  document.getElementById("modalOsmandText").textContent = osmandText;
  document.getElementById("modalOsmandDate").textContent = dateStr;

  const pendingFiles = updateStatus["osmand-pending-files"] || [];
  const pendingLink = document.getElementById("osmandPendingLink");
  if (osmandOk && updateStatus["osmand-in-progress"] && pendingFiles.length > 0) {
    pendingLink.style.display = "inline-block";
    document.getElementById("osmandPendingCount").textContent = pendingFiles.length;
  } else {
    pendingLink.style.display = "none";
  }

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

function renderPendingFilesList() {
  const listEl = document.getElementById("pendingFilesList");
  const pendingFiles = updateStatus["osmand-pending-files"] || [];
  listEl.innerHTML = "";

  if (pendingFiles.length === 0) {
    listEl.innerHTML = `<li class="pending-files-empty">אין כרגע קבצים הממתינים לעדכון.</li>`;
    return;
  }

  pendingFiles.forEach((fileName) => {
    const li = document.createElement("li");
    li.textContent = fileName;
    listEl.appendChild(li);
  });
}

function setupPendingFilesModal() {
  const overlay = document.getElementById("pendingFilesModal");
  document.getElementById("osmandPendingLink").addEventListener("click", (e) => {
    e.preventDefault();
    renderPendingFilesList();
    overlay.classList.add("open");
  });
  document.getElementById("pendingFilesCloseBtn").addEventListener("click", () => {
    overlay.classList.remove("open");
  });
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.classList.remove("open");
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

function downloadFile(fileName, url) {
  const counter = bumpDownloadCounter();
  pingAnalytics(fileName, counter);
  triggerDownload(url, fileName);
}

// ------------------------------------------------------------------
// Big buttons: OsmAnd Israel / Yosh / Moovitdos
// ------------------------------------------------------------------

function findOsmandFile(keywords) {
  const lowerKeywords = keywords.map((k) => k.toLowerCase());
  return osmandData.find((entry) =>
    lowerKeywords.some((k) => entry.fileName.toLowerCase().includes(k))
  );
}

function handleOsmandButton(keywords, label) {
  const match = findOsmandFile(keywords);
  if (!match) {
    alert(`המפה עבור "${label}" עדיין לא זמינה במאגר. נסו שוב מאוחר יותר.`);
    return;
  }
  downloadFile(match.fileName, match.url);
}

function handleMoovitdosButton() {
  if (!moovitdosLink.path) {
    alert("קובץ הנתונים למובידוס עדיין לא זמין. נסו שוב מאוחר יותר.");
    return;
  }
  downloadFile(moovitdosLink.path.split("/").pop(), moovitdosLink.path);
}

function setupBigButtons() {
  document
    .getElementById("btnIsrael")
    .addEventListener("click", () => handleOsmandButton(OSMAND_ISRAEL_KEYWORDS, "ישראל"));
  document
    .getElementById("btnYosh")
    .addEventListener("click", () => handleOsmandButton(OSMAND_YOSH_KEYWORDS, "יהודה ושומרון"));
  document.getElementById("btnMoovitdos").addEventListener("click", handleMoovitdosButton);
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
  if (!tags) return false;
  const fields = [
    tags.hebrewTags?.continent,
    tags.hebrewTags?.country,
    tags.hebrewTags?.city,
    tags.englishTags?.continent,
    tags.englishTags?.country,
    tags.englishTags?.city,
  ];
  return fields.some((f) => f && f.toLowerCase().includes(q));
}

function stripObfExtension(fileName) {
  return fileName.replace(/\.obf$/i, "");
}

function renderResultTagsLine(tags) {
  if (!tags) return "";
  const parts = [tags.hebrewTags?.continent, tags.hebrewTags?.country, tags.hebrewTags?.city].filter(
    Boolean
  );
  return parts.join(" · ");
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

    const row = document.createElement("div");
    row.className = "result-item";
    row.innerHTML = `
      <span class="label">
        <span class="emoji">${emoji}</span>
        <span class="label-text">
          ${tagsLine ? `<span class="tags-line">${tagsLine}</span>` : ""}
          <span class="file-line">${fileLine}</span>
        </span>
      </span>
      <button type="button">הורדה</button>
    `;
    row.querySelector("button").addEventListener("click", () => {
      downloadFile(entry.fileName, entry.url);
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
  setupPendingFilesModal();
  setupBigButtons();
  setupSearch();
  await loadAllData();
  if (window.twemoji) twemoji.parse(document.body, { className: "twemoji" });
});

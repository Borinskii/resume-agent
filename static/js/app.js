// File name preview for the upload field.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "file") return;
  const label = document.querySelector("[data-file-name]");
  if (label) {
    const file = input.files && input.files[0];
    label.textContent = file ? file.name : "No file selected";
  }
});

// Expand/collapse vacancy details.
document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const trigger = event.target.closest("[data-expand]");
  if (!trigger) return;
  event.preventDefault();
  const target = document.getElementById(trigger.dataset.expand);
  if (!target) return;
  const nowHidden = !target.hidden;
  target.hidden = nowHidden;
  trigger.textContent = nowHidden ? "Details" : "Hide details";
});

// --- Resume editor: inline suggestion cards -------------------------------
// Toggle a suggestion card by clicking its underlined bullet.
document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const toggle = event.target.closest("[data-toggle]");
  if (!toggle || event.target.closest(".anchor-card")) return;
  const anchor = toggle.closest(".doc-anchor");
  const card = anchor && anchor.querySelector(".anchor-card");
  if (!card) return;
  const willShow = card.hidden;
  // Close other open cards for a clean single-focus view.
  document.querySelectorAll(".anchor-card:not([hidden])").forEach((c) => { if (c !== card) c.hidden = true; });
  card.hidden = !willShow;
  toggle.setAttribute("aria-expanded", String(willShow));
});

// Keyboard: Enter/Space on a focused bullet toggles its card.
document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  if (!(event.target instanceof Element)) return;
  const toggle = event.target.closest("[data-toggle]");
  if (!toggle) return;
  event.preventDefault();
  toggle.click();
});

function submitEditorForm() {
  const form = document.getElementById("ed-doc");
  if (form) form.dispatchEvent(new CustomEvent("ed-apply"));
}

// Apply / Revert a suggestion: flip its hidden checkbox and re-render the doc.
document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const applyBtn = event.target.closest("[data-apply]");
  const dismissBtn = event.target.closest("[data-dismiss]");
  if (!applyBtn && !dismissBtn) return;
  const card = (applyBtn || dismissBtn).closest(".anchor-card, .extra-card");
  const wrap = (applyBtn || dismissBtn).closest(".doc-anchor, .extra-card");
  const checkbox = (wrap || card) && (wrap || card).querySelector('input[type="checkbox"]');
  if (!checkbox) return;
  checkbox.checked = Boolean(applyBtn);
  submitEditorForm();
});

// Drag-and-drop on the file drop label.
const fileDrop = document.querySelector("[data-file-drop]");
if (fileDrop) {
  const input = fileDrop.querySelector('input[type="file"]');
  ["dragenter", "dragover"].forEach((name) =>
    fileDrop.addEventListener(name, (e) => { e.preventDefault(); e.stopPropagation(); fileDrop.classList.add("file-drop-active"); }));
  ["dragleave", "drop"].forEach((name) =>
    fileDrop.addEventListener(name, (e) => { e.preventDefault(); e.stopPropagation(); fileDrop.classList.remove("file-drop-active"); }));
  fileDrop.addEventListener("drop", (event) => {
    if (!input || !event.dataTransfer || !event.dataTransfer.files.length) return;
    const dt = new DataTransfer();
    dt.items.add(event.dataTransfer.files[0]);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

// HTMX error surface.
function showError(message) {
  const banner = document.getElementById("error-banner");
  if (!banner) return;
  banner.textContent = message;
  banner.hidden = false;
  banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
function hideError() {
  const banner = document.getElementById("error-banner");
  if (banner) { banner.hidden = true; banner.textContent = ""; }
}
document.addEventListener("htmx:beforeRequest", hideError);
document.addEventListener("htmx:responseError", (event) => {
  const xhr = event.detail && event.detail.xhr;
  if (!xhr) { showError("Request failed. Check your connection and try again."); return; }
  let detail = "";
  try { detail = (JSON.parse(xhr.responseText || "{}").detail) || ""; }
  catch (_e) { detail = (xhr.responseText || "").slice(0, 240); }
  if (xhr.status === 413) showError(detail || "CV is too large (10 MB limit).");
  else if (xhr.status === 415) showError(detail || "Unsupported file type. Use DOCX, PDF, TXT, or MD.");
  else if (xhr.status === 429) showError(detail || "Too many analyses — wait a minute and retry.");
  else if (xhr.status >= 500) showError(detail || "Server error. Check the uvicorn logs.");
  else showError(detail || `Request failed with status ${xhr.status}.`);
});
document.addEventListener("htmx:sendError", () => showError("Network error — the server did not respond. Is the dev server running?"));
document.addEventListener("htmx:timeout", () => showError("Request timed out. Try again with a smaller CV or fewer URLs."));

// Highlight matched skill keywords inside the parsed CV preview.
document.addEventListener("htmx:afterSwap", () => {
  const preview = document.querySelector("[data-skills]");
  if (!preview) return;
  const raw = (preview.dataset.skills || "").split("|").filter(Boolean);
  if (!raw.length) return;
  const text = preview.textContent || "";
  const aliases = new Set();
  raw.forEach((skill) => {
    aliases.add(skill);
    skill.split(/[\s/]+/).forEach((part) => { if (part.length >= 3) aliases.add(part); });
  });
  const escaped = Array.from(aliases)
    .map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .sort((a, b) => b.length - a.length);
  if (!escaped.length) return;
  const pattern = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
  const fragment = document.createDocumentFragment();
  let lastIndex = 0, match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    const mark = document.createElement("mark");
    mark.textContent = match[0];
    fragment.appendChild(mark);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
  preview.textContent = "";
  preview.appendChild(fragment);
});

// Delete account button — full data wipe per Rule 14.
document.addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest("[data-delete-account]");
  if (!button) return;
  if (!window.confirm("Hard-delete every analysis, application, and stored CV for this session?")) return;
  try {
    const response = await fetch("/account/delete", { method: "POST" });
    if (!response.ok) { showError("Delete failed — see server logs."); return; }
    window.location.reload();
  } catch (_e) { showError("Network error while deleting account data."); }
});

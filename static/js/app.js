// File name preview for the upload field.
document.addEventListener("change", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement) || input.type !== "file") {
    return;
  }
  const label = document.querySelector("[data-file-name]");
  if (label) {
    const file = input.files && input.files[0];
    label.textContent = file ? file.name : "No file selected";
  }
});

function selectRole(detailId) {
  if (!detailId) {
    return;
  }
  const cards = Array.from(document.querySelectorAll("[data-role-card]"));
  const details = Array.from(document.querySelectorAll("[data-role-detail]"));
  if (!cards.length || !details.length) {
    return;
  }

  cards.forEach((card) => {
    const isSelected = card.dataset.roleCard === detailId;
    card.classList.toggle("role-card-selected", isSelected);
    card.setAttribute("aria-selected", String(isSelected));
    const state = card.querySelector(".role-select-state");
    if (state) {
      state.textContent = isSelected ? "Selected" : "Tailoring";
    }
  });

  details.forEach((panel) => {
    panel.hidden = panel.dataset.roleDetail !== detailId;
  });
}

document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  if (event.target.closest("a") || event.target.closest("form") || event.target.closest("button")) {
    if (event.target.closest("[data-role-card]") && event.target.closest("button.queue-btn")) {
      return;
    }
    if (event.target.closest("a") || event.target.closest("form")) {
      return;
    }
  }
  const card = event.target.closest("[data-role-card]");
  if (!card) {
    return;
  }
  selectRole(card.dataset.roleCard);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  if (!(event.target instanceof Element)) {
    return;
  }
  const card = event.target.closest("[data-role-card]");
  if (!card) {
    return;
  }
  if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA" || event.target.tagName === "SELECT") {
    return;
  }
  event.preventDefault();
  selectRole(card.dataset.roleCard);
});

// Drag-and-drop on the file drop label.
const fileDrop = document.querySelector("[data-file-drop]");
if (fileDrop) {
  const input = fileDrop.querySelector('input[type="file"]');
  ["dragenter", "dragover"].forEach((name) => {
    fileDrop.addEventListener(name, (event) => {
      event.preventDefault();
      event.stopPropagation();
      fileDrop.classList.add("file-drop-active");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    fileDrop.addEventListener(name, (event) => {
      event.preventDefault();
      event.stopPropagation();
      fileDrop.classList.remove("file-drop-active");
    });
  });
  fileDrop.addEventListener("drop", (event) => {
    if (!input || !event.dataTransfer || !event.dataTransfer.files.length) {
      return;
    }
    const file = event.dataTransfer.files[0];
    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

// HTMX error surface — never leave the user staring at silence.
function showError(message) {
  const banner = document.getElementById("error-banner");
  if (!banner) {
    return;
  }
  banner.textContent = message;
  banner.hidden = false;
  banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideError() {
  const banner = document.getElementById("error-banner");
  if (banner) {
    banner.hidden = true;
    banner.textContent = "";
  }
}

document.addEventListener("htmx:beforeRequest", hideError);

document.addEventListener("htmx:responseError", (event) => {
  const xhr = event.detail && event.detail.xhr;
  if (!xhr) {
    showError("Request failed. Check your connection and try again.");
    return;
  }
  let detail = "";
  try {
    const parsed = JSON.parse(xhr.responseText || "{}");
    detail = parsed.detail || "";
  } catch (_err) {
    detail = (xhr.responseText || "").slice(0, 240);
  }
  if (xhr.status === 413) {
    showError(detail || "CV is too large. The 10 MB limit is enforced server-side.");
  } else if (xhr.status === 415) {
    showError(detail || "Unsupported file type. Use PDF, DOCX, TXT, or MD.");
  } else if (xhr.status === 429) {
    showError(detail || "Too many analyses recently — wait a minute and retry.");
  } else if (xhr.status >= 500) {
    showError(detail || "Server error. Check server logs (uvicorn) for details.");
  } else {
    showError(detail || `Request failed with status ${xhr.status}.`);
  }
});

document.addEventListener("htmx:sendError", () => {
  showError("Network error — the server did not respond. Is the dev server running?");
});

document.addEventListener("htmx:timeout", () => {
  showError("Request timed out. Try again with a smaller CV or fewer target URLs.");
});

// Highlight matched skill keywords inside the parsed CV preview.
document.addEventListener("htmx:afterSwap", () => {
  const preview = document.querySelector("[data-skills]");
  if (!preview) {
    return;
  }
  const raw = (preview.dataset.skills || "").split("|").filter(Boolean);
  if (!raw.length) {
    return;
  }
  const text = preview.textContent || "";
  const aliases = new Set();
  raw.forEach((skill) => {
    aliases.add(skill);
    skill.split(/[\s/]+/).forEach((part) => {
      if (part.length >= 3) {
        aliases.add(part);
      }
    });
  });
  const escaped = Array.from(aliases)
    .map((alias) => alias.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .sort((a, b) => b.length - a.length);
  if (!escaped.length) {
    return;
  }
  const pattern = new RegExp(`\\b(${escaped.join("|")})\\b`, "gi");
  const fragment = document.createDocumentFragment();
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
    }
    const mark = document.createElement("mark");
    mark.textContent = match[0];
    fragment.appendChild(mark);
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
  }
  preview.textContent = "";
  preview.appendChild(fragment);
});

// Delete account button — full data wipe per Rule 14.
document.addEventListener("click", async (event) => {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("[data-delete-account]");
  if (!button) {
    return;
  }
  if (!window.confirm("Hard-delete every analysis, application, and stored CV for this session?")) {
    return;
  }
  try {
    const response = await fetch("/account/delete", { method: "POST" });
    if (!response.ok) {
      showError("Delete failed — see server logs.");
      return;
    }
    window.location.reload();
  } catch (err) {
    showError("Network error while deleting account data.");
  }
});

async function pickPath(button) {
  const targetSelector = button.dataset.target;
  const target = document.querySelector(targetSelector);
  if (!target) return;

  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Selezione...";

  try {
    const rootValue = button.dataset.root ? document.querySelector(button.dataset.root)?.value || "" : "";
    const initialValue = rootValue && (button.dataset.fileList || button.dataset.kind === "directory")
      ? rootValue
      : target.value || "";
    const response = await fetch("/pick-path", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind: button.dataset.kind || "file",
        multiple: button.dataset.multiple === "true",
        initial: initialValue,
        root: rootValue
      })
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "Selezione non disponibile");
    if (payload.paths.length > 0) {
      if (button.dataset.fileList) {
        const relativePaths = payload.paths.map((path) => toRelativePath(path, rootValue));
        const outsideRoot = relativePaths.filter((path) => path.startsWith("/") || path.startsWith(".."));
        if (outsideRoot.length > 0) {
          throw new Error("Seleziona solo file contenuti nella root progetto.");
        }
        setFileValues(target, relativePaths, button.dataset.fileList);
      } else if (target.tagName === "TEXTAREA") {
        target.value = payload.paths.join("\n");
      } else {
        target.value = payload.paths[0];
      }
      target.dispatchEvent(new Event("input", { bubbles: true }));
    }
  } catch (error) {
    showAppAlert(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

function showAppAlert(message, type = "info") {
  const shell = document.querySelector(".shell");
  if (!shell) return;
  let container = shell.querySelector(".alerts");
  if (!container) {
    container = document.createElement("section");
    container.className = "alerts";
    container.setAttribute("aria-live", "polite");
    const progress = shell.querySelector(".workflow-progress");
    if (progress) {
      progress.insertAdjacentElement("afterend", container);
    } else {
      shell.prepend(container);
    }
  }
  const alert = document.createElement("div");
  alert.className = `alert alert-${type}`;
  const paragraph = document.createElement("p");
  paragraph.textContent = message;
  alert.appendChild(paragraph);
  container.appendChild(alert);
}

async function refreshGlossaryEntries({ forced = false } = {}) {
  const status = document.querySelector("#glossary_preview_status");
  if (status) status.textContent = forced ? "Aggiornamento voci in corso..." : "Rilettura glossario...";

  const payload = {
    repo_root: document.querySelector("#repo_root")?.value || "",
    glossary_path: document.querySelector("#glossary_path")?.value || "",
    glossary_pdf_url: document.querySelector("#glossary_pdf_url")?.value || "",
    anchor_format: document.querySelector("#anchor_format")?.value || ""
  };
  const detection = document.querySelector('input[name="glossary_detection"]:checked');
  if (detection) payload.glossary_detection = detection.value;

  try {
    const response = await fetch("/glossary-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "Impossibile leggere il glossario.");
    if (status) {
      const stats = data.stats || {};
      status.textContent = `${stats.total || 0} termini rilevati, ${stats.manual || 0} in revisione manuale, ${stats.new || 0} nuovi termini. Apri il glossario per confermare la lista.`;
    }
  } catch (error) {
    if (status) status.textContent = error.message;
    showAppAlert(error.message, "error");
  }
}

async function discoverTexFiles(button) {
  const target = document.querySelector(button.dataset.target);
  const status = document.querySelector("#tex_discover_status");
  if (!target) return;
  const sourceInput = button.dataset.source ? document.querySelector(button.dataset.source) : null;
  const sourceValue = button.dataset.sourceValue ?? sourceInput?.value ?? ".";
  if (sourceInput && button.dataset.sourceValue !== undefined) {
    sourceInput.value = button.dataset.sourceValue;
    sourceInput.dispatchEvent(new Event("input", { bubbles: true }));
  }
  if (status) status.textContent = "Ricerca dei file .tex in corso...";
  button.disabled = true;
  const originalText = button.textContent;
  button.textContent = "Ricerca...";
  try {
    const response = await fetch("/discover-tex", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_root: document.querySelector(button.dataset.root)?.value || "",
        source_dir: sourceValue,
        glossary_path: document.querySelector(button.dataset.glossary)?.value || ""
      })
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "Autorilevamento non riuscito.");
    setFileValues(target, data.files, button.dataset.fileList);
    if (status) {
      status.textContent = `${data.files.length} file aggiunti. ${data.excluded.length} esclusi dalle regole.`;
    }
  } catch (error) {
    if (status) status.textContent = error.message;
    showAppAlert(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function saveWizardState() {
  const form = document.querySelector("[data-wizard-form]");
  if (!form) return;
  const payload = {
    operation: document.querySelector('input[name="operation"]:checked')?.value || "",
    repo_root: document.querySelector("#repo_root")?.value || "",
    glossary_path: document.querySelector("#glossary_path")?.value || "",
    glossary_pdf_url: document.querySelector("#glossary_pdf_url")?.value || "",
    anchor_format: document.querySelector("#anchor_format")?.value || "",
    source_dir: document.querySelector("#source_dir")?.value || ".",
    review_order: form.querySelector('input[name="review_order"]:checked')?.value || "by_term",
    new_entry_ids: form.querySelector('input[name="new_entry_ids"]')?.value || ""
  };
  const detection = document.querySelector('input[name="glossary_detection"]:checked');
  if (detection) payload.glossary_detection = detection.value;
  if (form.querySelector("[data-rule-editor]")) {
    payload.exclude_file_patterns = document.querySelector("#exclude_file_patterns")?.value || "";
    payload.ignored_environments = document.querySelector("#ignored_environments")?.value || "";
    payload.ignored_commands = document.querySelector("#ignored_commands")?.value || "";
    payload.ignored_sections = [...form.querySelectorAll('input[name="ignored_sections"]:checked')].map((item) => item.value);
    payload.skip_titles = Boolean(form.querySelector('input[name="skip_titles"]')?.checked);
  }
  try {
    await fetch("/wizard-state", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  } catch {
    // Autosave is opportunistic; explicit submit still saves the same fields.
  }
}

function toRelativePath(path, root) {
  const normalizedPath = normalizePath(path);
  const normalizedRoot = normalizePath(root);
  if (!normalizedRoot || !normalizedPath.startsWith("/")) return normalizedPath;
  if (normalizedPath === normalizedRoot) return "";
  if (normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1);
  }
  return normalizedPath;
}

function normalizePath(path) {
  return (path || "").replace(/\\/g, "/").replace(/\/+$/, "");
}

function setFileValues(target, paths, listSelector) {
  const existing = target.value.split("\n").map((item) => item.trim()).filter(Boolean);
  const merged = [...new Set([...existing, ...paths.map((item) => item.trim()).filter(Boolean)])];
  target.value = merged.join("\n");
  renderFileList(target, listSelector);
}

function renderFileList(target, listSelector) {
  const list = document.querySelector(listSelector);
  if (!list) return;
  const paths = target.value.split("\n").map((item) => item.trim()).filter(Boolean);
  list.innerHTML = "";
  if (paths.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "Nessun documento selezionato.";
    list.appendChild(empty);
    return;
  }
  paths.forEach((path) => {
    const item = document.createElement("div");
    item.className = "file-chip";
    const code = document.createElement("code");
    code.textContent = path;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "icon-button small";
    remove.setAttribute("aria-label", `Rimuovi ${path}`);
    remove.textContent = "x";
    remove.addEventListener("click", () => {
      target.value = paths.filter((candidate) => candidate !== path).join("\n");
      renderFileList(target, listSelector);
    });
    item.append(code, remove);
    list.appendChild(item);
  });
}

function collectEntryState() {
  const state = new Map();
  document.querySelectorAll("#entries_tbody tr[data-entry]").forEach((row) => {
    const id = row.querySelector('input[name="entry_id"]')?.value;
    if (!id) return;
    const aliasInput = [...row.querySelectorAll("input")].find((input) => input.name === `aliases_${id}`);
    const modeInput = [...row.querySelectorAll("input")].find((input) => input.name === `mode_${id}`);
    state.set(id, {
      aliases: aliasInput?.value || "",
      manual: Boolean(modeInput?.checked)
    });
  });
  return state;
}

function renderEntries(entries, previousState = new Map()) {
  const tbody = document.querySelector("#entries_tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  if (!entries.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.textContent = "Nessuna voce rilevata. Verifica il path del glossario o usa Aggiorna voci.";
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }
  entries.forEach((entry) => {
    const state = previousState.get(entry.id);
    const aliases = state ? state.aliases : (entry.aliases || []).join(", ");
    const manual = state ? state.manual : entry.mode === "manual";
    const row = document.createElement("tr");
    row.dataset.entry = "";

    const idCell = document.createElement("td");
    const code = document.createElement("code");
    code.textContent = entry.id;
    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "entry_id";
    hidden.value = entry.id;
    const idContent = document.createElement("div");
    idContent.className = "entry-term-cell";
    idContent.append(code, hidden);
    idCell.appendChild(idContent);

    const termCell = document.createElement("td");
    termCell.textContent = entry.term;

    const definitionCell = document.createElement("td");
    definitionCell.textContent = entry.definition || "";

    const aliasCell = document.createElement("td");
    const aliasInput = document.createElement("input");
    aliasInput.className = "alias-input";
    aliasInput.name = `aliases_${entry.id}`;
    aliasInput.value = aliases;
    aliasInput.placeholder = "alias separati da virgola";
    aliasInput.setAttribute("aria-label", `Alias per ${entry.term}`);
    aliasCell.appendChild(aliasInput);

    const modeCell = document.createElement("td");
    modeCell.className = "mode-cell";
    const label = document.createElement("label");
    label.className = "switch icon-only";
    label.title = `Modalità per ${entry.term}`;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.name = `mode_${entry.id}`;
    checkbox.value = "manual";
    checkbox.checked = manual;
    checkbox.dataset.modeSwitch = "";
    checkbox.setAttribute("aria-label", `Modalità per ${entry.term}`);
    const visual = document.createElement("span");
    const text = document.createElement("em");
    text.className = "sr-only";
    text.dataset.modeLabel = "";
    label.append(checkbox, visual, text);
    modeCell.appendChild(label);

    row.append(idCell, termCell, definitionCell, aliasCell, modeCell);
    tbody.appendChild(row);
    updateModeLabel(checkbox);
  });
}

function updateModeLabel(input) {
  const wrapper = input.closest(".switch");
  const label = wrapper?.querySelector("[data-mode-label]");
  const value = input.checked ? "Manuale" : "Automatico";
  if (label) label.textContent = value;
  if (wrapper) wrapper.dataset.mode = value.toLowerCase();
}

const entryTables = {
  manual: { page: 0, query: "" },
  automatic: { page: 0, query: "" }
};

const formatEntries = {
  page: 0,
  query: ""
};

function initEntryTables() {
  if (!document.querySelector("[data-entries-form]")) return;
  sortEntryTables();
  updateEntryCounts();
  updateEntryPagination("manual");
  updateEntryPagination("automatic");
}

function initFormatEntries() {
  if (!document.querySelector("[data-format-table]")) return;
  sortFormatEntries();
  updateFormatEntryCounts();
  updateFormatPagination();
}

function sortEntryTables() {
  ["manual", "automatic"].forEach((kind) => {
    const table = document.querySelector(`[data-entry-table="${kind}"]`);
    if (!table) return;
    [...table.querySelectorAll("[data-entry]")]
      .sort((a, b) => (a.dataset.entryTerm || "").localeCompare(b.dataset.entryTerm || "", "it"))
      .forEach((row) => table.appendChild(row));
  });
}

function updateEntryCounts() {
  const manual = document.querySelectorAll('[data-entry-table="manual"] [data-entry]').length;
  const automatic = document.querySelectorAll('[data-entry-table="automatic"] [data-entry]').length;
  const manualCount = document.querySelector("[data-manual-count]");
  const autoCount = document.querySelector("[data-auto-count]");
  if (manualCount) manualCount.textContent = String(manual);
  if (autoCount) autoCount.textContent = String(automatic);
}

function updateEntryPagination(kind) {
  const table = document.querySelector(`[data-entry-table="${kind}"]`);
  if (!table) return;
  const state = entryTables[kind];
  const rows = [...table.querySelectorAll("[data-entry]")];
  const query = state.query.trim().toLowerCase();
  const filtered = rows.filter((row) => row.textContent.toLowerCase().includes(query));
  const pageSize = 10;
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  state.page = Math.min(state.page, pages - 1);
  const start = state.page * pageSize;
  const visible = new Set(filtered.slice(start, start + pageSize));
  rows.forEach((row) => {
    row.hidden = !visible.has(row);
  });
  const label = document.querySelector(`[data-page-label="${kind}"]`);
  const prev = document.querySelector(`[data-page-prev="${kind}"]`);
  const next = document.querySelector(`[data-page-next="${kind}"]`);
  if (label) label.textContent = `${state.page + 1} / ${pages} (${filtered.length})`;
  if (prev) prev.disabled = state.page === 0;
  if (next) next.disabled = state.page >= pages - 1;
}

function sortFormatEntries() {
  const table = document.querySelector("[data-format-table]");
  if (!table) return;
  [...table.querySelectorAll("[data-format-entry]")]
    .sort((a, b) => (a.dataset.entryTerm || "").localeCompare(b.dataset.entryTerm || "", "it"))
    .forEach((row) => table.appendChild(row));
}

function updateFormatEntryCounts() {
  const count = document.querySelector("[data-format-included-count]");
  if (!count) return;
  const included = document.querySelectorAll("[data-format-include]:checked").length;
  count.textContent = String(included);
}

function updateFormatPagination() {
  const table = document.querySelector("[data-format-table]");
  if (!table) return;
  const rows = [...table.querySelectorAll("[data-format-entry]")];
  const query = formatEntries.query.trim().toLowerCase();
  const filtered = rows.filter((row) => row.textContent.toLowerCase().includes(query));
  const pageSize = 10;
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  formatEntries.page = Math.min(formatEntries.page, pages - 1);
  const start = formatEntries.page * pageSize;
  const visible = new Set(filtered.slice(start, start + pageSize));
  rows.forEach((row) => {
    row.hidden = !visible.has(row);
  });
  const label = document.querySelector("[data-format-page-label]");
  const prev = document.querySelector("[data-format-prev]");
  const next = document.querySelector("[data-format-next]");
  if (label) label.textContent = `${formatEntries.page + 1} / ${pages} (${filtered.length})`;
  if (prev) prev.disabled = formatEntries.page === 0;
  if (next) next.disabled = formatEntries.page >= pages - 1;
}

function moveEntryRow(input) {
  const row = input.closest("[data-entry]");
  if (!row) return;
  const targetKind = input.checked ? "manual" : "automatic";
  const sourceKind = input.checked ? "automatic" : "manual";
  const targetTable = document.querySelector(`[data-entry-table="${targetKind}"]`);
  if (!targetTable) return;
  targetTable.appendChild(row);
  sortEntryTables();
  updateModeLabel(input);
  updateEntryCounts();
  entryTables[sourceKind].page = 0;
  entryTables[targetKind].page = 0;
  updateEntryPagination("manual");
  updateEntryPagination("automatic");
}

function debounce(callback, delay = 600) {
  let timer = 0;
  return (...args) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => callback(...args), delay);
  };
}

function initRuleEditors() {
  document.querySelectorAll("[data-rule-editor]").forEach((editor) => {
    const values = parseRuleValues(editor);
    editor.dataset.selectedIndex = "";
    renderRuleEditor(editor, values);
  });
}

function initSettingsSearch() {
  const search = document.querySelector("[data-settings-search]");
  const sidebar = document.querySelector(".settings-sidebar");
  if (!search || !sidebar) return;
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    sidebar.querySelectorAll(".settings-nav-group").forEach((group) => {
      let visibleLinks = 0;
      group.querySelectorAll("a").forEach((link) => {
        const isVisible = !query || link.textContent.toLowerCase().includes(query);
        link.hidden = !isVisible;
        if (isVisible) visibleLinks += 1;
      });
      group.hidden = visibleLinks === 0;
    });
  });
}

function parseRuleValues(editor) {
  try {
    const raw = JSON.parse(editor.dataset.values || "[]");
    return Array.isArray(raw) ? raw.map((item) => String(item)).filter(Boolean) : [];
  } catch {
    return [];
  }
}

function getRuleValues(editor) {
  return [...editor.querySelectorAll("[data-rule-item]")]
    .map((item) => item.dataset.value || "")
    .filter(Boolean);
}

function renderRuleEditor(editor, values) {
  const list = editor.querySelector("[data-rule-list]");
  const target = document.querySelector(editor.dataset.target);
  if (!list || !target) return;
  list.innerHTML = "";
  values.forEach((value, index) => {
    const row = document.createElement("li");
    row.dataset.ruleItem = "";
    row.dataset.index = String(index);
    row.dataset.value = value;
    row.tabIndex = 0;
    row.innerHTML = `<span>${escapeHtml(value)}</span>`;
    row.addEventListener("click", () => selectRule(editor, index));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectRule(editor, index);
      }
    });
    list.appendChild(row);
  });
  target.value = values.join("\n");
  target.dispatchEvent(new Event("input", { bubbles: true }));
  updateRuleSelection(editor);
}

function selectRule(editor, index) {
  editor.dataset.selectedIndex = String(index);
  const input = editor.querySelector("[data-rule-input]");
  const values = getRuleValues(editor);
  if (input) input.value = values[index] || "";
  updateRuleSelection(editor);
}

function updateRuleSelection(editor) {
  const selected = selectedRuleIndex(editor);
  editor.querySelectorAll("[data-rule-item]").forEach((item) => {
    item.classList.toggle("selected", Number(item.dataset.index) === selected);
  });
}

function addRule(editor) {
  const input = editor.querySelector("[data-rule-input]");
  const value = input?.value.trim();
  if (!value) return;
  const values = getRuleValues(editor);
  if (!values.includes(value)) values.push(value);
  if (input) input.value = "";
  editor.dataset.selectedIndex = "";
  renderRuleEditor(editor, values);
}

function editRule(editor) {
  const selected = selectedRuleIndex(editor);
  if (!Number.isInteger(selected) || selected < 0) return;
  const input = editor.querySelector("[data-rule-input]");
  const value = input?.value.trim();
  if (!value) return;
  const values = getRuleValues(editor);
  values[selected] = value;
  renderRuleEditor(editor, values);
  selectRule(editor, selected);
}

function deleteRule(editor) {
  const selected = selectedRuleIndex(editor);
  if (!Number.isInteger(selected) || selected < 0) return;
  const values = getRuleValues(editor);
  values.splice(selected, 1);
  const input = editor.querySelector("[data-rule-input]");
  if (input) input.value = "";
  editor.dataset.selectedIndex = "";
  renderRuleEditor(editor, values);
}

function selectedRuleIndex(editor) {
  const raw = editor?.dataset.selectedIndex;
  return raw === undefined || raw === "" ? -1 : Number(raw);
}

function escapeHtml(value) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-picker]");
  if (button) {
    pickPath(button);
  }

  const refreshButton = event.target.closest("[data-refresh-glossary]");
  if (refreshButton) {
    refreshGlossaryEntries({ forced: true });
  }

  const discoverButton = event.target.closest("[data-discover-tex]");
  if (discoverButton) {
    discoverTexFiles(discoverButton);
  }

  const addButton = event.target.closest("[data-add-file]");
  if (addButton) {
    const source = document.querySelector(addButton.dataset.source);
    const target = document.querySelector(addButton.dataset.target);
    if (!source || !target) return;
    const value = source.value.trim();
    if (!value) return;
    if (value.startsWith("/") || value.startsWith("..")) {
      showAppAlert("Inserisci un path relativo alla root progetto.", "warning");
      return;
    }
    setFileValues(target, [value], addButton.dataset.fileList);
    source.value = "";
  }

  const ruleAdd = event.target.closest("[data-rule-add]");
  if (ruleAdd) addRule(ruleAdd.closest("[data-rule-editor]"));

  const ruleEdit = event.target.closest("[data-rule-edit]");
  if (ruleEdit) editRule(ruleEdit.closest("[data-rule-editor]"));

  const ruleDelete = event.target.closest("[data-rule-delete]");
  if (ruleDelete) deleteRule(ruleDelete.closest("[data-rule-editor]"));

  const modalButton = event.target.closest("[data-open-modal]");
  if (modalButton) {
    const dialog = document.getElementById(modalButton.dataset.openModal);
    if (dialog && typeof dialog.showModal === "function") dialog.showModal();
  }
});

document.addEventListener("DOMContentLoaded", () => {
  initRuleEditors();
  initSettingsSearch();
  document.querySelectorAll("[data-file-list]").forEach((button) => {
    const target = document.querySelector(button.dataset.target);
    if (target) renderFileList(target, button.dataset.fileList);
  });
  document.querySelectorAll("[data-mode-switch]").forEach(updateModeLabel);
  initEntryTables();
  initFormatEntries();
  const debouncedRefresh = debounce(() => refreshGlossaryEntries());
  const debouncedSave = debounce(() => saveWizardState(), 500);
  document.querySelectorAll("[data-glossary-source]").forEach((input) => {
    input.addEventListener("change", debouncedRefresh);
    input.addEventListener("input", debouncedRefresh);
  });
  document.querySelectorAll("[data-persist]").forEach((input) => {
    input.addEventListener("change", debouncedSave);
    input.addEventListener("input", debouncedSave);
  });
});

document.addEventListener("change", (event) => {
  const modeSwitch = event.target.closest("[data-mode-switch]");
  if (modeSwitch) {
    if (document.querySelector("[data-entries-form]")) {
      moveEntryRow(modeSwitch);
    } else {
      updateModeLabel(modeSwitch);
    }
  }

  const includeEntry = event.target.closest('[name="include_entry_id"]');
  if (includeEntry) {
    includeEntry.closest("[data-entry]")?.classList.toggle("is-excluded", !includeEntry.checked);
    updateFormatEntryCounts();
  }
});

document.addEventListener("input", (event) => {
  const formatSearch = event.target.closest("[data-format-search]");
  if (formatSearch) {
    formatEntries.query = formatSearch.value || "";
    formatEntries.page = 0;
    updateFormatPagination();
    return;
  }

  const search = event.target.closest("[data-entry-search]");
  if (!search) return;
  const kind = search.dataset.entrySearch;
  entryTables[kind].query = search.value || "";
  entryTables[kind].page = 0;
  updateEntryPagination(kind);
});

document.addEventListener("click", (event) => {
  const formatPrev = event.target.closest("[data-format-prev]");
  if (formatPrev) {
    formatEntries.page = Math.max(0, formatEntries.page - 1);
    updateFormatPagination();
  }
  const formatNext = event.target.closest("[data-format-next]");
  if (formatNext) {
    formatEntries.page += 1;
    updateFormatPagination();
  }

  const prev = event.target.closest("[data-page-prev]");
  if (prev) {
    const kind = prev.dataset.pagePrev;
    entryTables[kind].page = Math.max(0, entryTables[kind].page - 1);
    updateEntryPagination(kind);
  }
  const next = event.target.closest("[data-page-next]");
  if (next) {
    const kind = next.dataset.pageNext;
    entryTables[kind].page += 1;
    updateEntryPagination(kind);
  }
});

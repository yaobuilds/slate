const TODAY_MAX = 8;
const DEADLINE_MAX = 8;

const todayEditor = document.getElementById("today-editor");
const deadlineEditor = document.getElementById("deadline-editor");
const todayAdd = document.getElementById("today-add");
const deadlineAdd = document.getElementById("deadline-add");
const moneyNote = document.getElementById("money-note");
const saveBtn = document.getElementById("schedule-save");
const msgEl = document.getElementById("schedule-msg");

function setMessage(text) {
  if (msgEl) msgEl.textContent = text;
}

function field(className, value, placeholder, type) {
  const input = document.createElement("input");
  input.className = `settings-field ${className}`;
  input.type = type || "text";
  input.value = value || "";
  input.placeholder = placeholder;
  if (className === "time") input.maxLength = 16;
  if (className === "title") input.maxLength = 120;
  return input;
}

function removeButton(row) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Remove";
  button.addEventListener("click", () => {
    row.remove();
    syncAddButtons();
    setMessage("");
  });
  return button;
}

function syncAddButtons() {
  if (todayAdd && todayEditor) todayAdd.disabled = todayEditor.children.length >= TODAY_MAX;
  if (deadlineAdd && deadlineEditor) {
    deadlineAdd.disabled = deadlineEditor.children.length >= DEADLINE_MAX;
  }
}

function addTodayRow(item) {
  if (!todayEditor || todayEditor.children.length >= TODAY_MAX) return;
  const row = document.createElement("div");
  row.className = "settings-edit-row";
  const when = item && typeof item.time === "string" ? item.time : "";
  const title = item && typeof item.title === "string" ? item.title : "";
  row.append(field("time", when, "9:00"), field("title", title, "Title"), removeButton(row));
  todayEditor.append(row);
  syncAddButtons();
}

function addDeadlineRow(item) {
  if (!deadlineEditor || deadlineEditor.children.length >= DEADLINE_MAX) return;
  const row = document.createElement("div");
  row.className = "settings-edit-row";
  const title = item && typeof item.title === "string" ? item.title : "";
  const due = item && typeof item.due === "string" ? item.due : "";
  row.append(field("title", title, "Title"), field("time", due, "", "date"), removeButton(row));
  deadlineEditor.append(row);
  syncAddButtons();
}

function readRows(editor, keys) {
  if (!editor) return [];
  const rows = [];
  editor.querySelectorAll(".settings-edit-row").forEach((row) => {
    const inputs = row.querySelectorAll("input");
    const entry = {};
    keys.forEach((key, index) => {
      entry[key] = inputs[index] ? inputs[index].value.trim() : "";
    });
    rows.push(entry);
  });
  return rows;
}

function payloadFromForm() {
  return {
    today: readRows(todayEditor, ["time", "title"]),
    deadlines: readRows(deadlineEditor, ["title", "due"]),
    money: { note: moneyNote ? moneyNote.value.trim() : "" },
  };
}

function fillForm(data) {
  if (todayEditor) todayEditor.replaceChildren();
  if (deadlineEditor) deadlineEditor.replaceChildren();
  const today = Array.isArray(data.today) ? data.today : [];
  const deadlines = Array.isArray(data.deadlines) ? data.deadlines : [];
  today.slice(0, TODAY_MAX).forEach((item) => addTodayRow(item));
  deadlines.slice(0, DEADLINE_MAX).forEach((item) => addDeadlineRow(item));
  if (moneyNote) {
    const money = data.money && typeof data.money === "object" ? data.money : {};
    moneyNote.value = typeof money.note === "string" ? money.note : "";
  }
  syncAddButtons();
}

async function readSchedule() {
  const response = await fetch("data.json", {
    cache: "no-store",
    headers: { "X-Slate-Full": "1" },
  });
  if (response.status === 401) return { error: "pin" };
  if (!response.ok) return { error: "bad" };
  return response.json();
}

async function postSchedule(body) {
  const response = await fetch("schedule.json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (response.status === 401) return { error: "pin" };
  if (response.status === 429) return { error: "slow" };
  if (!response.ok) return { error: "bad" };
  return response.json();
}

async function persistSchedule() {
  const result = await postSchedule(payloadFromForm());
  if (result.error === "pin") {
    wireSettingsPinForm(persistSchedule);
    return;
  }
  if (result.error === "slow") {
    setMessage("Wait a moment and try again.");
    return;
  }
  if (result.error) {
    setMessage("Could not save.");
    return;
  }
  fillForm(result);
  setMessage("Saved. Dashboard picks this up within a minute.");
}

async function init() {
  try {
    const data = await readSchedule();
    if (data.error === "pin") {
      wireSettingsPinForm(init);
      return;
    }
    if (data.error) {
      setMessage("Could not load the schedule.");
      return;
    }
    fillForm(data);
  } catch (err) {
    setMessage("Could not load the schedule.");
  }
}

if (todayAdd) todayAdd.addEventListener("click", () => addTodayRow({}));
if (deadlineAdd) deadlineAdd.addEventListener("click", () => addDeadlineRow({}));
if (saveBtn) saveBtn.addEventListener("click", persistSchedule);
init();

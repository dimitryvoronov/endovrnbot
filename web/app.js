// MAX Bridge — https://st.max.ru/js/max-web-app.js exposes window.WebApp.
// No MainButton / showAlert / ready() / expand() / theme vars (unlike Telegram).
const tg = window.WebApp || null;
const inMessenger = !!(tg && tg.initData);

const entry = { distractions: [] };
const photoFiles = [];
const fallbackBtn = document.getElementById("submit-fallback");

// Surface the "initData empty" case instead of a bare 401.
if (tg && !tg.initData) {
  const u = tg.initDataUnsafe || {};
  const info =
    "platform=" + (tg.platform || "?") + " · user=" + (u.user ? "есть" : "нет");
  console.warn("MAX initData is EMPTY —", info, tg.initDataUnsafe);
  const el = document.getElementById("auth-warn");
  if (el) {
    el.textContent =
      "MAX не передал данные для входа (initData пуст), сохранение работать не будет. " +
      "Откройте дневник через кнопку в чате с ботом или обновите приложение. [" + info + "]";
    el.hidden = false;
  }
}

function authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  if (tg && tg.initData) h["Authorization"] = "tma " + tg.initData;
  return h;
}

function notify(msg) {
  window.alert(msg);
}

function haptic(kind) {
  try {
    if (tg && tg.HapticFeedback && tg.HapticFeedback[kind]) tg.HapticFeedback[kind]();
  } catch (e) { /* optional */ }
}

/* ---- single-select groups (.seg, .scale) ---- */
document.querySelectorAll(".seg, .scale").forEach((group) => {
  const field = group.dataset.field;
  const isScale = group.classList.contains("scale");
  group.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      group.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
      btn.classList.add("on");
      entry[field] = isScale ? Number(btn.textContent) : btn.textContent;
      haptic("selectionChanged");
      refreshSubmit();
    });
  });
});

/* ---- multi-select chips ---- */
document.querySelectorAll(".chips").forEach((group) => {
  const field = group.dataset.field;
  group.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("on");
      const set = new Set(entry[field] || []);
      set.has(btn.textContent) ? set.delete(btn.textContent) : set.add(btn.textContent);
      entry[field] = [...set];
      haptic("selectionChanged");
    });
  });
});

/* ---- photos ---- */
const photosInput = document.getElementById("photos");
const previews = document.getElementById("previews");
photosInput.addEventListener("change", () => {
  for (const f of photosInput.files) {
    if (photoFiles.length >= 3) break;
    photoFiles.push(f);
    const img = document.createElement("img");
    img.src = URL.createObjectURL(f);
    previews.appendChild(img);
  }
  photosInput.value = "";
});

document.getElementById("note").addEventListener("input", (e) => {
  entry.note = e.target.value;
});

/* ---- tabs ---- */
const views = {
  new: document.getElementById("view-new"),
  hist: document.getElementById("view-hist"),
};
document.getElementById("tab-new").onclick = () => switchTab("new");
document.getElementById("tab-hist").onclick = () => { switchTab("hist"); loadEntries(); };

function switchTab(name) {
  for (const k in views) views[k].hidden = k !== name;
  document.getElementById("tab-new").classList.toggle("active", name === "new");
  document.getElementById("tab-hist").classList.toggle("active", name === "hist");
  refreshSubmit();
}

/* ---- submit ---- */
function ready() {
  return entry.meal_type && entry.hunger_before != null && entry.satiety_after != null;
}

function refreshSubmit() {
  fallbackBtn.hidden = views.new.hidden;
  fallbackBtn.disabled = !ready();
  fallbackBtn.textContent = ready() ? "Сохранить запись" : "Заполните приём и обе шкалы";
}

async function submitEntry() {
  if (!ready()) {
    notify("Отметьте приём пищи и обе шкалы (голод, насыщение).");
    return;
  }
  fallbackBtn.disabled = true;
  fallbackBtn.textContent = "Сохраняю…";

  const payload = {
    ts: new Date().toISOString().replace(/\.\d+Z$/, "Z"),
    meal_type: entry.meal_type,
    hunger_before: entry.hunger_before,
    satiety_after: entry.satiety_after,
    company: entry.company || null,
    distractions: entry.distractions || [],
    emotion: entry.emotion || null,
    note: entry.note || "",
  };
  const fd = new FormData();
  fd.append("payload", JSON.stringify(payload));
  for (const f of photoFiles) fd.append("photos", f);

  try {
    const res = await fetch("/api/entries", { method: "POST", headers: authHeaders(), body: fd });
    if (!res.ok) throw new Error(await res.text());
    haptic("notificationOccurred");
    resetForm();
    notify("Запись сохранена.");
  } catch (e) {
    notify("Ошибка: " + e.message);
  } finally {
    refreshSubmit();
  }
}

function resetForm() {
  for (const k of Object.keys(entry)) delete entry[k];
  entry.distractions = [];
  photoFiles.length = 0;
  previews.innerHTML = "";
  document.getElementById("note").value = "";
  document.querySelectorAll("button.on").forEach((b) => b.classList.remove("on"));
  refreshSubmit();
}

fallbackBtn.onclick = submitEntry;
refreshSubmit();

/* ---- history + report ---- */
async function loadEntries() {
  const box = document.getElementById("entries");
  box.innerHTML = "<p class='hint'>Загрузка…</p>";
  try {
    const res = await fetch("/api/entries?days=30", { headers: authHeaders() });
    const rows = await res.json();
    if (!rows.length) { box.innerHTML = "<p class='hint'>Пока нет записей.</p>"; return; }
    box.innerHTML = "";
    for (const r of rows) {
      const dz = JSON.parse(r.distractions || "[]").join(", ");
      const d = document.createElement("div");
      d.className = "entry";
      d.innerHTML =
        '<div class="top"><span>' + (r.meal_type || "—") + "</span><span>" +
        r.ts.slice(0, 16).replace("T", " ") + "</span></div>" +
        '<div class="meta">голод ' + (r.hunger_before ?? "—") + " → насыщение " +
        (r.satiety_after ?? "—") + " · " + (r.company || "—") +
        (dz ? " · " + dz : "") + (r.emotion ? " · " + r.emotion : "") + "</div>";
      box.appendChild(d);
    }
  } catch (e) {
    box.innerHTML = "<p class='hint'>Ошибка загрузки</p>";
  }
}

document.querySelectorAll(".report-btns button").forEach((btn) => {
  btn.onclick = async () => {
    btn.disabled = true;
    try {
      const res = await fetch("/api/report", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ period_days: Number(btn.dataset.days) }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || "error");
      notify(
        j.sent
          ? "Отчёт отправлен в чат с ботом."
          : "Отчёт собран (" + j.entries + " записей), доставка не удалась: " + (j.error || "—")
      );
    } catch (e) {
      notify("Ошибка: " + e.message);
    } finally {
      btn.disabled = false;
    }
  };
});

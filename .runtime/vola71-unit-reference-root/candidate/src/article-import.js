const ARTICLE = /^[A-Za-zА-Яа-яЁё0-9]+(?:[-_][A-Za-zА-Яа-яЁё0-9]+)*$/;

export function dedupeArticleLines(lines) {
  const articles = [], duplicates = [], errors = [], seen = new Set();
  lines.forEach((value, index) => {
    const article = String(value ?? "").trim();
    if (!article) return;
    if (!ARTICLE.test(article)) { errors.push({ lines: [index + 1], value: article, message: "Артикул должен содержать только буквы, цифры, дефисы и подчёркивания." }); return; }
    const key = article.toLocaleUpperCase("ru-RU");
    if (seen.has(key)) duplicates.push(article); else { seen.add(key); articles.push(article); }
  });
  return { articles, duplicates, errors };
}

export function sellerWarningSummary(item) {
  const seller = item?.payload?.sellerCreate || {};
  const taskItem = seller.taskItem || {};
  const warnings = [
    ...(Array.isArray(taskItem.errors) ? taskItem.errors : []),
    ...(Array.isArray(taskItem.warnings) ? taskItem.warnings : []),
  ];
  const messages = new Set();
  for (const warning of warnings) {
    const code = String(warning?.code || warning?.status || "").trim();
    if (["pics_http_error", "some_image_failed"].includes(code)) {
      messages.add("Ozon: не все фотографии обработаны.");
    } else if (code === "value_found_by_synonym") {
      const attribute = warning?.attribute_id ? ` атрибута ${warning.attribute_id}` : "";
      messages.add(`Ozon: значение${attribute} принято по синониму словаря.`);
    } else if (code) {
      messages.add(`Ozon: ${code}`);
    }
  }
  const photoUpdate = seller.photoUpdate || {};
  for (const error of photoUpdate.after?.errors || []) {
    const index = Number(error?.sourcePhotoIndex);
    const label = Number.isSafeInteger(index) && index > 0 ? `Фото IEK #${index}` : "Фото IEK";
    const message = String(error?.message || "не обработано").replace(/https?:\/\/\S+/gi, "[URL]").slice(0, 180);
    messages.add(`${label}: ${message}`);
  }
  return [...messages].join(" · ");
}

export function mountArticleImport(api) {
  const wrap = document.querySelector(".wrap");
  if (!wrap || document.getElementById("article-import")) return null;
  const login = document.createElement("section");
  login.className = "panel";
  login.id = "operator-login";
  login.innerHTML = `<h2>Вход оператора</h2><label for="operator-token">Код доступа</label><div class="actions"><input id="operator-token" type="password" autocomplete="current-password" required><button id="operator-login-submit" class="button primary" type="button">Войти</button></div><p id="operator-login-message" class="notice" role="status"></p>`;
  const session = document.createElement("div");
  session.className = "actions";
  session.id = "operator-session";
  session.innerHTML = `<p role="status">Оператор вошёл</p><button id="operator-logout" class="button" type="button">Выйти</button>`;
  const panel = document.createElement("section");
  panel.className = "panel";
  panel.id = "article-import";
  panel.innerHTML = `<h2>Ozon · список артикулов IEK</h2><p class="subline">Введите исходные артикулы IEK по одному на строку или загрузите .xlsx. Перед запуском проверьте распознанный список.</p><label for="article-list">Артикулы</label><textarea id="article-list" rows="6" style="width:100%;margin:8px 0;padding:12px" placeholder="2342432&#10;2342433"></textarea><label for="article-xlsx">Excel .xlsx</label><input id="article-xlsx" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"><p id="article-summary" aria-live="polite"></p><div id="article-errors" class="result"></div><div class="actions"><button id="article-preview" class="button primary">Проверить список</button><button id="article-start" class="button" disabled>Запустить обработку</button></div><p id="article-message" class="notice" role="status"></p>`;
  const input = panel.querySelector("#article-list"), fileInput = panel.querySelector("#article-xlsx"), summary = panel.querySelector("#article-summary"), errors = panel.querySelector("#article-errors"), message = panel.querySelector("#article-message"), start = panel.querySelector("#article-start");
  const results = document.createElement("div"); results.className = "result"; panel.append(results);
  const retryButton = document.createElement("button"); retryButton.type = "button"; retryButton.className = "button"; retryButton.textContent = "Повторить неуспешные"; retryButton.hidden = true; panel.append(retryButton);
  const statusButton = document.createElement("button"); statusButton.type = "button"; statusButton.className = "button"; statusButton.textContent = "Открыть предыдущий запуск"; panel.append(statusButton);
  const continueButton = document.createElement("button"); continueButton.type = "button"; continueButton.className = "button"; continueButton.textContent = "Продолжить обработку"; continueButton.hidden = true; panel.append(continueButton);
  panel.hidden = true;
  session.hidden = true;
  wrap.prepend(panel);
  wrap.prepend(session);
  wrap.prepend(login);
  const setAuthenticated = (authenticated, configured) => {
    login.hidden = authenticated;
    session.hidden = !authenticated;
    panel.hidden = !authenticated;
    const message = login.querySelector("#operator-login-message");
    const input = login.querySelector("#operator-token");
    const submit = login.querySelector("#operator-login-submit");
    if (!configured && !authenticated) {
      input.disabled = true;
      submit.disabled = true;
      message.textContent = "Вход оператора ещё не настроен.";
    } else {
      input.disabled = false;
      submit.disabled = false;
    }
  };
  login.querySelector("#operator-login-submit").addEventListener("click", async () => {
    const input = login.querySelector("#operator-token"), message = login.querySelector("#operator-login-message"), submit = login.querySelector("#operator-login-submit");
    submit.disabled = true;
    try {
      await api("/api/operator/session", { token: input.value });
      input.value = "";
      setAuthenticated(true, true);
    } catch (error) { message.textContent = error.message; }
    finally { submit.disabled = false; }
  });
  session.querySelector("#operator-logout").addEventListener("click", async () => {
    await fetch("/api/operator/session", { method: "DELETE", credentials: "same-origin" });
    setAuthenticated(false, true);
  });
  api("/api/operator/session").then((state) => setAuthenticated(state.authenticated, state.configured)).catch((error) => {
    setAuthenticated(false, false);
    login.querySelector("#operator-login-message").textContent = error.message;
  });
  const savedRunKey = "iek-operator:last-import-run";
  const savedRunId = sessionStorage.getItem(savedRunKey);
  if (savedRunId) message.dataset.runId = savedRunId;
  const terminalRunStatuses = new Set(["complete", "failed", "blocked", "uncertain"]);
  let activeDriver = null;
  let statusRequest = null;
  let startingRun = false;
  let retryingRun = false;
  const renderRun = async (runId) => {
    const current = await api(`/api/import/${encodeURIComponent(runId)}`);
    results.replaceChildren();
    for (const item of current.items || []) {
      const row = document.createElement("div");
      const product = item.product_id ? ` · product ${item.product_id}` : "";
      const error = item.error?.message ? ` · ${item.error.message}` : "";
      const warning = sellerWarningSummary(item);
      const warningText = warning ? ` · Предупреждение: ${warning}` : "";
      const reconciliationNotice = item.status === "uncertain" ? " · Требуется ручная сверка исхода отправки; повторно не отправлять." : "";
      row.textContent = `${item.article} → ${item.listing_article}: ${item.status} / ${item.stage}${product}${error}${warningText}${reconciliationNotice}`;
      results.append(row);
    }
    retryButton.hidden = !(current.items || []).some(item => item.status === "failed");
    message.textContent = `Запуск ${runId}: ${current.run.status}${current.run.status === "uncertain" ? " · Ручная сверка обязательна; безопасный повтор отправки отключён." : ""}`;

    continueButton.hidden = terminalRunStatuses.has(current.run.status);
    return current.run.status;
  };
  const driveRun = async (runId) => {
    if (activeDriver) return activeDriver.runId === runId ? activeDriver.promise : null;
    let attempts = 0;
    const promise = (async () => {
      let state = await renderRun(runId);
      while (!terminalRunStatuses.has(state) && attempts++ < 30) {
        await api("/api/import/process", { runId });
        state = await renderRun(runId);
        if (!terminalRunStatuses.has(state)) await new Promise(resolve => setTimeout(resolve, 1500));
      }
      if (!terminalRunStatuses.has(state)) {
        message.textContent = `Запуск ${runId}: ${state}. Достигнут предел автоматических проверок; нажмите «Продолжить обработку» для продолжения.`;
        continueButton.hidden = false;
      }
      return state;
    })();
    activeDriver = { runId, promise };
    try { return await promise; }
    finally { if (activeDriver?.promise === promise) activeDriver = null; }
  };
  let parsed = { articles: [], duplicates: [], errors: [] }, source = "manual";
  const show = (result) => {
    parsed = result;
    summary.textContent = result.articles.length ? `${result.articles.length}: ${result.articles.join(", ")}${result.duplicates.length ? ` · повторы удалены: ${result.duplicates.join(", ")}` : ""}` : "Артикулы не распознаны.";
    errors.replaceChildren();
    for (const error of result.errors || []) { const row = document.createElement("div"); row.textContent = error.lines?.length ? `Строка ${error.lines.join(", ")}: ${error.message}` : error.message; errors.append(row); }
    start.disabled = !result.articles.length || result.errors.length > 0;
  };
  input.addEventListener("input", () => { source = "manual"; show(dedupeArticleLines(input.value.split(/\r?\n/))); });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0]; if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx") || file.size > 5 * 1024 * 1024) { show({ articles: [], duplicates: [], errors: [{ message: "Нужен файл .xlsx размером до 5 МБ." }] }); return; }
    source = "xlsx"; const form = new FormData(); form.set("file", file, file.name);
    try { show(await api("/api/articles/preview", form)); } catch (error) { show({ articles: [], duplicates: [], errors: [{ message: error.message }] }); }
  });
  panel.querySelector("#article-preview").addEventListener("click", async () => {
    if (source === "xlsx") return;
    try { show(await api("/api/articles/preview", { source: "manual", articles: input.value.split(/\r?\n/) })); }
    catch (error) { show({ articles: [], duplicates: [], errors: [{ message: error.message }] }); }
  });
  start.addEventListener("click", async () => {
    if (startingRun || retryingRun || activeDriver || statusRequest) return;
    startingRun = true;
    start.disabled = true;
    try {
      const idempotencyKey = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const result = await api("/api/import/start", { source, articles: parsed.articles, idempotencyKey });
      if (!result.runId) { message.textContent = result.message || "Импорт не запущен."; return; }
      message.dataset.runId = result.runId;
      sessionStorage.setItem(savedRunKey, result.runId);
      await driveRun(result.runId);
    } catch (error) { message.textContent = error.message; }
    finally { startingRun = false; show(parsed); }
  });
  const resumeSavedRun = async () => {
    const runId = message.dataset.runId || sessionStorage.getItem(savedRunKey);
    if (!runId) { message.textContent = "Нет сохранённого запуска."; return; }
    if (startingRun || retryingRun || activeDriver) return activeDriver?.runId === runId ? activeDriver.promise : undefined;
    if (statusRequest) return statusRequest;
    const request = (async () => {
    try { message.dataset.runId = runId; const state = await renderRun(runId); if (!terminalRunStatuses.has(state)) await driveRun(runId); }
    catch (error) { message.textContent = error.message; }
    })();
    statusRequest = request;
    try { return await request; } finally { if (statusRequest === request) statusRequest = null; }
  };
  statusButton.addEventListener("click", resumeSavedRun);
  continueButton.addEventListener("click", resumeSavedRun);
  const initialResume = savedRunId ? resumeSavedRun() : Promise.resolve();
  retryButton.addEventListener("click", async () => {
    const runId = message.dataset.runId; if (!runId || retryingRun || startingRun || statusRequest || activeDriver) return;
    retryingRun = true;
    retryButton.disabled = true;
    try { const retry = await api("/api/import/retry", { runId }); message.textContent = retry.message || "Повтор не запущен."; if (retry.retried) await driveRun(runId); }
    catch (error) { message.textContent = error.message; }
    finally { retryingRun = false; retryButton.disabled = false; }
  });
  show(parsed);
  return { initialResume, resumeSavedRun };
}

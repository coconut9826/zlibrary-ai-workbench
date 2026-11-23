function bookCover(title, url = "") {
  const image = url
    ? '<img src="' +
      url +
      '" alt="' +
      escaped(title) +
      '封面" loading="lazy" onerror="this.remove()">'
    : "";
  const label =
    String(title).length > 12 ? String(title).slice(0, 12) + "…" : title;
  return (
    '<div class="book-cover">' +
    image +
    "<span>" +
    escaped(label) +
    "</span></div>"
  );
}

function groupedBooks(books) {
  const groups = new Map();
  for (const book of books) {
    const key =
      String(book.title || "")
        .trim()
        .toLowerCase() +
      "|" +
      String(book.author || "")
        .trim()
        .toLowerCase();
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(book);
  }
  return [...groups.values()];
}

function formatBytes(value) {
  return value >= 1024 * 1024
    ? (value / 1024 / 1024).toFixed(1) + " MB"
    : Math.round(value / 1024) + " KB";
}

function renderResults(target, books) {
  target.innerHTML =
    groupedBooks(books)
      .map((editions) => {
        const book = editions[0];
        const options = editions
          .map(
            (edition, index) =>
              '<option value="' +
              index +
              '">' +
              escaped(String(edition.extension || "未知格式").toUpperCase()) +
              (edition.filesizeString
                ? " · " + escaped(edition.filesizeString)
                : "") +
              "</option>",
          )
          .join("");
        const pdfIndex = editions.findIndex(
          (edition) => String(edition.extension).toLowerCase() === "pdf",
        );
        const hasEpub = editions.some(
          (edition) => String(edition.extension).toLowerCase() === "epub",
        );
        const convertOption =
          pdfIndex >= 0 && !hasEpub
            ? '<option value="convert-' +
              pdfIndex +
              '">EPUB · 本机转换</option>'
            : "";
        const formats = [
          ...new Set(
            editions.map((edition) =>
              String(edition.extension || "未知").toUpperCase(),
            ),
          ),
        ];
        return (
          '<article class="result card" data-editions="' +
          encodeURIComponent(JSON.stringify(editions)) +
          '">' +
          bookCover(book.title) +
          '<div class="result-info"><strong>' +
          escaped(book.title) +
          "</strong><p>" +
          escaped(book.author || "作者未知") +
          " · " +
          escaped(book.year || "年份未知") +
          " · " +
          escaped(book.language || "语言未知") +
          '</p><div class="chips">' +
          formats
            .map(
              (format) => '<span class="chip">' + escaped(format) + "</span>",
            )
            .join("") +
          '</div></div><div class="result-actions"><label>格式<select class="format-choice" aria-label="下载格式">' +
          options +
          convertOption +
          '</select></label><button class="primary queue-download" type="button">下载</button></div></article>'
        );
      })
      .join("") || '<p class="empty">没有结果。</p>';
}

async function loadDownloads() {
  const data = await api("/v1/jobs");
  const jobs = data.jobs.filter((job) => job.kind === "download");
  const states = {
    queued: "等待下载",
    running: "正在下载并入库",
    converting: "正在转换 PDF 为 EPUB",
    completed: "已完成",
    failed: "失败",
  };
  $("#download-list").innerHTML = jobs
    .map((job) => {
      const total =
        job.payload.target_format === "epub" &&
        job.payload.source_format === "pdf"
          ? 3
          : 2;
      const stage = { queued: 1, running: 2, converting: 3 }[job.status];
      const transfer = job.transfer;
      const transferLabel = transfer
        ? formatBytes(transfer.bytes_done) +
          (transfer.bytes_total
            ? " / " +
              formatBytes(transfer.bytes_total) +
              " · " +
              Math.round((transfer.bytes_done / transfer.bytes_total) * 100) +
              "%"
            : " 已传输")
        : "";
      const meter = transfer
        ? "<progress " +
          (transfer.bytes_total
            ? 'value="' +
              transfer.bytes_done +
              '" max="' +
              transfer.bytes_total +
              '"'
            : "") +
          ' aria-label="下载进度"></progress>'
        : "";
      return (
        '<article class="task download-item"><div><strong>' +
        escaped(job.payload.title || job.payload.id || "书籍") +
        "</strong><p>" +
        escaped(states[job.status] || job.status) +
        (stage ? " · 阶段 " + stage + "/" + total : "") +
        "</p>" +
        (transferLabel ? "<p>" + transferLabel + "</p>" + meter : "") +
        (job.error
          ? '<p class="task-error">' + escaped(job.error) + "</p>"
          : "") +
        (job.result.path
          ? '<p class="download-path">' + escaped(job.result.path) + "</p>"
          : "") +
        '</div><div class="download-state">' +
        (["queued", "running", "converting"].includes(job.status)
          ? '<span class="spinner" aria-hidden="true"></span>'
          : job.status === "completed"
            ? "完成"
            : "需要处理") +
        "</div></article>"
      );
    })
    .join("");
  $("#downloads-empty").hidden = jobs.length > 0;
  if (
    jobs.some((job) =>
      ["queued", "running", "converting"].includes(job.status),
    ) &&
    $("#downloads").classList.contains("active")
  ) {
    clearTimeout(window.downloadRefreshTimer);
    window.downloadRefreshTimer = setTimeout(
      () => loadDownloads().catch(() => {}),
      3000,
    );
  } else if (jobs.some((job) => job.status === "completed")) {
    loadBooks().catch(() => {});
  }
}

function renderInterests() {
  $("#interest-tags").innerHTML = interests
    .map(
      (tag) =>
        '<button class="interest-tag' +
        (selectedInterests.includes(tag) ? " selected" : "") +
        '" type="button" data-interest="' +
        escaped(tag) +
        '" aria-pressed="' +
        selectedInterests.includes(tag) +
        '">' +
        escaped(tag) +
        "</button>",
    )
    .join("");
}

async function loadRecommendations(force = false) {
  const status = $("#recommendation-status");
  if (!selectedInterests.length) {
    $("#recommendation-list").innerHTML = "";
    status.textContent = "选择至少一个阅读方向。";
    return;
  }
  const date = new Date().toLocaleDateString("en-CA");
  const cacheKey =
    "workbench-recommendations-v2-" + date + "-" + selectedInterests.join("-");
  try {
    let cached = null;
    try {
      if (!force) cached = JSON.parse(localStorage.getItem(cacheKey) || "null");
    } catch (_) {
      // A stale cache must not prevent a fresh search.
    }
    if (cached) {
      renderResults($("#recommendation-list"), cached);
      status.textContent =
        "今日推荐 · " + cached.length + " 本 · " + selectedInterests.join("、");
      return;
    }
    status.textContent = "正在按阅读方向搜索今日书籍…";
    const start = Number(date.slice(-2)) % selectedInterests.length;
    const queries = [
      ...selectedInterests.slice(start),
      ...selectedInterests.slice(0, start),
    ].slice(0, 3);
    const results = await Promise.allSettled(
      queries.map((query) =>
        api("/v1/books/search", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, limit: 10 }),
        }),
      ),
    );
    const lists = results.map((result) =>
      result.status === "fulfilled" ? result.value.books || [] : [],
    );
    const books = [];
    for (let index = 0; index < 10; index++)
      for (const list of lists) if (list[index]) books.push(list[index]);
    if (!books.length && results.some((result) => result.status === "rejected"))
      throw results.find((result) => result.status === "rejected").reason;
    const unique = new Map();
    for (const book of books) {
      const key = (book.title + "|" + book.author).toLowerCase();
      if (!unique.has(key)) unique.set(key, book);
    }
    const recommended = [...unique.values()].slice(0, 10);
    try {
      localStorage.setItem(cacheKey, JSON.stringify(recommended));
    } catch (_) {
      // Recommendations still work when persistent storage is disabled.
    }
    renderResults($("#recommendation-list"), recommended);
    status.textContent =
      "今日推荐 · " + recommended.length + " 本 · " + queries.join("、");
  } catch (error) {
    status.textContent = "推荐暂不可用：" + error.message;
  }
}

$("#interest-tags").addEventListener("click", (event) => {
  const tag = event.target.closest("[data-interest]")?.dataset.interest;
  if (!tag) return;
  selectedInterests = selectedInterests.includes(tag)
    ? selectedInterests.filter((item) => item !== tag)
    : [...selectedInterests, tag];
  try {
    localStorage.setItem("workbench-interests", JSON.stringify(selectedInterests));
  } catch (_) {
    // The selection remains usable for this session.
  }
  renderInterests();
  loadRecommendations();
});
$("#refresh-recommendations").addEventListener("click", () =>
  loadRecommendations(true),
);
$("#refresh-downloads").addEventListener("click", () =>
  loadDownloads().catch((error) => toast(error.message, true)),
);
document
  .querySelectorAll("#search-results,#recommendation-list")
  .forEach((list) =>
    list.addEventListener("click", (event) => {
      const button = event.target.closest(".queue-download");
      if (!button) return;
      const card = button.closest("[data-editions]");
      const editions = JSON.parse(decodeURIComponent(card.dataset.editions));
      const choice = card.querySelector(".format-choice").value;
      const convert = choice.startsWith("convert-");
      const book = editions[Number(convert ? choice.slice(8) : choice)];
      downloadBook(book, button, convert ? "epub" : "");
    }),
  );
renderInterests();

(() => {
  const TOUR_DEFINITIONS = [
    {
      match: (path) => path.startsWith("/staff/cataloging/"),
      steps: [
        ["staff-sidebar", "模組導覽", "左側依照編目、流通、採訪、資源與治理分區，館員可以快速切換工作台。"],
        ["staff-topbar", "工作台頂部", "這裡保留 OPAC、數位典藏、API 與帳戶入口，方便在館員流程中快速查核公開呈現。"],
        ["cataloging-import-list", "MARC 匯入批次", "館員從這裡追蹤每一批 MARC21 或 MARCXML 匯入的狀態與處理進度。"],
        ["cataloging-import-table", "批次清單", "清單顯示格式、建立者與處理狀態，適合用來排定編目審核優先順序。"],
        ["cataloging-import-upload", "上傳匯入", "建立新批次時要指定資料格式，系統會保留原始 MARC 並進入解析流程。"],
        ["cataloging-batch-summary", "批次摘要", "摘要區呈現總量、狀態與匯入時間，協助判斷批次是否可以進入審核。"],
        ["cataloging-batch-records", "待審紀錄", "每筆匯入紀錄可逐一檢視解析結果、錯誤與候選比對。"],
        ["marc-review-header", "編目審核", "審核頁保留批次脈絡與目前紀錄狀態，避免館員離開工作流。"],
        ["marc-review-mapping", "欄位對應", "系統把 MARC 欄位映射到 Work、Instance、權威與館藏相關資料。"],
        ["marc-review-resolution", "決策區", "館員可核准、拒絕或連結既有 Instance，避免重複建立書目。"],
        ["marc-review-candidates", "候選比對", "候選清單協助處理 duplicate matching 與 manifestation 層級連結。"],
        ["marc-review-authority-suggestions", "權威建議", "系統列出人名、主題或其他標目的候選權威，支援接受、暫建或拒絕。"],
        ["marc-review-parsed", "解析資料", "解析後的結構化資料用於稽核 mapping，不取代原始 MARC。"],
        ["marc-review-raw", "原始 MARC", "原始紀錄完整保留，供匯出、回溯與品質檢查使用。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/circulation/"),
      steps: [
        ["staff-sidebar", "流通入口", "流通櫃台、讀者管理、費用與報表都集中在 staff 導覽中。"],
        ["staff-topbar", "快速切換", "櫃台人員可快速回到 OPAC 檢查公開可用狀態。"],
        ["circulation-header", "流通櫃台", "此頁整合讀者、單冊、借出、歸還與續借操作。"],
        ["circulation-lookup", "條碼查找", "先掃讀者 barcode 或單冊 barcode，系統會載入對應上下文。"],
        ["circulation-checkout", "借出", "借出需要讀者條碼與單冊條碼，後端會檢查可借狀態與封鎖條件。"],
        ["circulation-checkin", "還書", "還書後若單冊有預約，系統會提示轉入待取狀態。"],
        ["circulation-patron-summary", "讀者摘要", "摘要區顯示讀者類型、狀態、欠款與封鎖原因。"],
        ["circulation-open-loans", "目前借閱", "館員可檢查到期日與續借狀態，並直接執行續借。"],
        ["circulation-holds", "預約清單", "此區顯示讀者目前預約與到館待取狀態。"],
        ["circulation-item-summary", "單冊摘要", "單冊狀態、條碼、館藏地與流通狀態會在這裡彙整。"],
        ["system-messages", "操作回饋", "借出、還書、續借與錯誤訊息會透過系統訊息即時回饋。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/authorities/"),
      steps: [
        ["staff-sidebar", "權威控制入口", "權威工作台支援人名、團體、會議、主題、地名與統一題名。"],
        ["authority-search", "權威查找", "可依權威標目、異名或識別碼搜尋既有權威。"],
        ["authority-results", "權威結果", "結果表顯示類型、狀態與外部 URI，支援後續連結與治理。"],
        ["authority-detail-header", "權威詳情", "詳情頁集中呈現權威類型、狀態、識別碼與外部來源。"],
        ["authority-access-points", "標目管理", "Authorized 與 Variant Access Point 會分別管理，支援見及參見關係。"],
        ["authority-relations", "權威關係", "see also、上位、下位、相關詞等關係可在此維護。"],
        ["authority-linked-records", "書目連結", "此區顯示已連到該權威的書目或主題使用情形。"],
        ["authority-governance", "治理操作", "合併、棄用與替代關係屬高風險操作，需受權限控管。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/acquisitions/"),
      steps: [
        ["staff-sidebar", "採購模組", "採購、期刊與 ERM 共用供應商、發票與資源脈絡。"],
        ["acquisitions-orders", "訂單清單", "此頁追蹤請購、訂單、驗收與發票對帳狀態。"],
        ["acquisition-order-detail", "訂單詳情", "訂單頁呈現 vendor、基金、狀態流轉與金額資訊。"],
        ["acquisition-order-lines", "訂單明細", "每一行可連結或產生 Instance，驗收後建立 Holding 與 Item。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/erm/"),
      steps: [
        ["staff-sidebar", "ERM 入口", "ERM 管理電子資源、授權、平台、套裝與可用範圍。"],
        ["erm-resource-list", "電子資源清單", "可追蹤 trial、active、suspended、cancelled 等資源狀態。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/repository/"),
      steps: [
        ["staff-sidebar", "典藏工作台", "數位典藏管理 metadata、檔案資產、發布與撤回。"],
        ["repository-staff-list", "數位物件清單", "館員可從清單進入 metadata 編輯、檔案上傳與公開狀態管理。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/analytics/"),
      steps: [
        ["staff-sidebar", "治理與報表", "報表與資料品質檢查集中在治理區，支援管理決策。"],
        ["analytics-dashboard", "報表平台", "儀表板列出可執行報表、權限與最近執行紀錄。"],
        ["analytics-recent-runs", "最近執行", "最近執行結果可回看、下載，並保留稽核脈絡。"],
      ],
    },
    {
      match: (path) => path.startsWith("/staff/data-quality/"),
      steps: [
        ["staff-sidebar", "資料治理", "資料品質檢查涵蓋 MARC、權威、館藏、單冊與 ERM。"],
        ["data-quality-header", "品質檢查", "管理員可觸發檢查並追蹤整體品質狀態。"],
        ["data-quality-runs", "執行紀錄", "每次檢查會留下時間、狀態與產生問題數。"],
        ["data-quality-summary", "問題摘要", "依類型彙整問題，協助決定修補優先順序。"],
        ["data-quality-issues", "問題清單", "逐筆列出異常項目，支援後續修復工作流。"],
      ],
    },
    {
      match: (path) => path === "/" || path.startsWith("/search"),
      steps: [
        ["opac-search-hero", "館藏探索", "讀者可以搜尋書名、作者、主題、ISBN/ISSN、電子資源與全文。"],
        ["opac-search-controls", "搜尋條件", "搜尋結果頁保留關鍵字與進階篩選入口。"],
        ["opac-facets", "Facet 篩選", "Facet 可依資料類型、可用狀態、館別、線上可用與平台縮小結果。"],
        ["opac-result-list", "結果清單", "結果清單整合書目、主題、出版資訊與可用狀態。"],
      ],
    },
  ];

  function markActiveNavigation() {
    const path = window.location.pathname;
    document.querySelectorAll("[data-nav-match]").forEach((link) => {
      const match = link.getAttribute("data-nav-match");
      if (match && path.startsWith(match)) {
        link.classList.add("is-active");
      }
    });
  }

  function bindSidebar() {
    const button = document.querySelector("[data-sidebar-toggle]");
    if (!button) return;
    button.addEventListener("click", () => {
      document.body.classList.toggle("sidebar-open");
    });
  }

  function bindMessages() {
    document.querySelectorAll("[data-dismiss-message]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = button.closest("li");
        if (item) item.remove();
      });
    });
  }

  function markTourReadiness() {
    if (document.querySelector("[data-tour-id]")) {
      document.body.classList.add("tour-ready");
    }
  }

  function resolveTourSteps() {
    const path = window.location.pathname;
    const definition = TOUR_DEFINITIONS.find((tour) => tour.match(path));
    const rawSteps = definition ? definition.steps : [];
    const steps = rawSteps
      .map(([id, title, body]) => ({ id, title, body, target: document.querySelector(`[data-tour-id="${id}"]`) }))
      .filter((step) => step.target);
    if (steps.length > 0) return steps;

    return Array.from(document.querySelectorAll("[data-tour-id]"))
      .slice(0, 12)
      .map((target, index) => ({
        id: target.getAttribute("data-tour-id"),
        title: index === 0 ? "頁面導覽" : `步驟 ${index + 1}`,
        body: "這個區塊是目前流程中的可操作或可檢視重點。",
        target,
      }));
  }

  function createParticleLayer() {
    const layer = document.createElement("div");
    layer.className = "lc-tour-particles";
    for (let index = 0; index < 10; index += 1) {
      const particle = document.createElement("span");
      particle.style.setProperty("--i", index);
      layer.appendChild(particle);
    }
    return layer;
  }

  function startGuidedTour() {
    const steps = resolveTourSteps();
    if (!steps.length) return;

    let index = 0;
    let raf = 0;
    const spotlight = document.createElement("div");
    spotlight.className = "lc-tour-spotlight";
    spotlight.appendChild(createParticleLayer());

    const card = document.createElement("section");
    card.className = "lc-tour-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-live", "polite");
    card.setAttribute("aria-label", "頁面導覽");
    card.innerHTML = `
      <button class="lc-tour-close" type="button" aria-label="關閉導覽">×</button>
      <div class="lc-tour-kicker"></div>
      <h2></h2>
      <p></p>
      <div class="lc-tour-progress"><span></span></div>
      <div class="lc-tour-actions">
        <button class="button button-muted" type="button" data-tour-prev>上一步</button>
        <button class="button button-primary" type="button" data-tour-next>下一步</button>
      </div>
    `;
    document.body.append(spotlight, card);

    const closeButton = card.querySelector(".lc-tour-close");
    const prevButton = card.querySelector("[data-tour-prev]");
    const nextButton = card.querySelector("[data-tour-next]");
    const kicker = card.querySelector(".lc-tour-kicker");
    const title = card.querySelector("h2");
    const body = card.querySelector("p");
    const progress = card.querySelector(".lc-tour-progress span");

    function positionSpotlight(target) {
      const rect = target.getBoundingClientRect();
      const pad = 8;
      spotlight.style.left = `${Math.max(rect.left - pad, 8)}px`;
      spotlight.style.top = `${Math.max(rect.top - pad, 8)}px`;
      spotlight.style.width = `${Math.min(rect.width + pad * 2, window.innerWidth - 16)}px`;
      spotlight.style.height = `${Math.min(rect.height + pad * 2, window.innerHeight - 16)}px`;
    }

    function schedulePosition() {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => positionSpotlight(steps[index].target));
    }

    function renderStep() {
      const step = steps[index];
      step.target.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
      kicker.textContent = `步驟 ${index + 1} / ${steps.length}`;
      title.textContent = step.title;
      body.textContent = step.body;
      progress.style.width = `${((index + 1) / steps.length) * 100}%`;
      prevButton.disabled = index === 0;
      nextButton.textContent = index === steps.length - 1 ? "完成" : "下一步";
      window.setTimeout(schedulePosition, 220);
    }

    function stopTour() {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", schedulePosition);
      window.removeEventListener("scroll", schedulePosition, true);
      spotlight.remove();
      card.remove();
    }

    prevButton.addEventListener("click", () => {
      index = Math.max(0, index - 1);
      renderStep();
    });
    nextButton.addEventListener("click", () => {
      if (index >= steps.length - 1) {
        stopTour();
        return;
      }
      index += 1;
      renderStep();
    });
    closeButton.addEventListener("click", stopTour);
    window.addEventListener("resize", schedulePosition);
    window.addEventListener("scroll", schedulePosition, true);

    window.setTimeout(renderStep, 450);
  }

  document.addEventListener("DOMContentLoaded", () => {
    markActiveNavigation();
    bindSidebar();
    bindMessages();
    markTourReadiness();
    startGuidedTour();
  });
})();

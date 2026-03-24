(function () {
    const rawHost = window.location.hostname || "127.0.0.1";
    const API_HOST =
        rawHost === "0.0.0.0" || rawHost === "[::]" ? "127.0.0.1" : rawHost;
    const API_BASE_CANDIDATES = Array.from(
        new Set([
            `http://${API_HOST}:8000`,
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]),
    );

    let apiBaseCache = null;
    const DEFAULT_LIGHT_MODEL = "gemma3:1b";
    const HEAVY_MODEL_ALIASES = new Set([
        "llama3.1:8b",
        "llama3:8b",
        "qwen2.5:7b-instruct",
    ]);

    async function apiFetch(path, options = {}) {
        const candidates = apiBaseCache
            ? [apiBaseCache, ...API_BASE_CANDIDATES.filter((item) => item !== apiBaseCache)]
            : API_BASE_CANDIDATES;

        let lastError = null;
        for (const base of candidates) {
            try {
                const response = await fetch(`${base}${path}`, options);
                apiBaseCache = base;
                return response;
            } catch (error) {
                lastError = error;
            }
        }

        throw lastError || new Error("Не удалось подключиться к API");
    }

    function normalizeErrorMessage(source, fallback = "Ошибка запроса") {
        if (!source) return fallback;

        if (source instanceof Error) {
            return normalizeErrorMessage(source.message, fallback);
        }

        if (typeof source === "string") {
            const text = source.trim();
            return text || fallback;
        }

        if (Array.isArray(source)) {
            const messages = source
                .map((item) => normalizeErrorMessage(item, ""))
                .filter(Boolean);
            return messages.length ? messages.join("; ") : fallback;
        }

        if (typeof source === "object") {
            if (typeof source.detail === "string" && source.detail.trim()) {
                return source.detail.trim();
            }
            if (Array.isArray(source.detail) && source.detail.length) {
                return normalizeErrorMessage(source.detail, fallback);
            }
            if (typeof source.message === "string" && source.message.trim()) {
                return source.message.trim();
            }
            if (typeof source.msg === "string" && source.msg.trim()) {
                const location = Array.isArray(source.loc)
                    ? source.loc.filter(Boolean).join(".")
                    : "";
                return location ? `${location}: ${source.msg.trim()}` : source.msg.trim();
            }
        }

        return fallback;
    }

    async function safeJson(response) {
        try {
            return await response.json();
        } catch (error) {
            return {};
        }
    }

    async function authorizedPost(path, payload) {
        const token = localStorage.getItem("authToken") || "auth-disabled";
        const response = await apiFetch(path, {
            method: "POST",
            headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
            },
            body: JSON.stringify(payload),
        });

        const data = await safeJson(response);
        if (!response.ok) {
            throw new Error(normalizeErrorMessage(data, "Ошибка запроса"));
        }
        return data;
    }

    function getCurrentBookIds() {
        const currentBookId = Number(localStorage.getItem("currentBookId"));
        if (!currentBookId || Number.isNaN(currentBookId)) {
            return null;
        }
        return [currentBookId];
    }

    function setStatus(target, text, isError = false) {
        if (!target) return;
        target.textContent = text || "";
        target.classList.toggle("error", Boolean(isError));
    }

    function normalizeModelName(value) {
        return String(value || "").trim().toLowerCase();
    }

    function ensureLightModelDefault(input) {
        if (!input) return;
        const current = normalizeModelName(input.value);
        if (!current || HEAVY_MODEL_ALIASES.has(current)) {
            input.value = DEFAULT_LIGHT_MODEL;
        }
    }

    function bindModelPresets(root, input) {
        if (!root || !input) return;
        ensureLightModelDefault(input);
        root.querySelectorAll(".model-preset-btn[data-model]").forEach((button) => {
            if (button.dataset.bound === "true") return;
            button.dataset.bound = "true";
            button.addEventListener("click", () => {
                input.value = String(button.dataset.model || "").trim();
            });
        });
    }

    function renderCitations(target, citations) {
        if (!target) return;
        target.innerHTML = "";

        const safeCitations = Array.isArray(citations) ? citations : [];
        if (!safeCitations.length) {
            return;
        }

        const header = document.createElement("div");
        header.className = "summary-citations-title";
        header.textContent = "Цитаты-основания";
        target.appendChild(header);

        safeCitations.forEach((item) => {
            const card = document.createElement("div");
            card.className = "summary-citation-item";

            const location = item.location || {};
            const chapterText = location.chapter ? `глава ${location.chapter}` : "";
            const linesText = location.line_start && location.line_end
                ? `строки ${location.line_start}-${location.line_end}`
                : "";
            const meta = [item.book_title, chapterText, linesText].filter(Boolean).join(" | ");

            card.innerHTML = `
                <div class="summary-citation-meta">${meta}</div>
                <div class="summary-citation-text">${item.fragment || ""}</div>
            `;

            target.appendChild(card);
        });
    }

    function bindSummaryEvents(root) {
        const summarizeButton = root.querySelector("#summarize-button");
        const summaryResult = root.querySelector("#summary-result");
        const summaryStatus = root.querySelector("#summary-status");
        const summaryCitations = root.querySelector("#summary-citations");
        const localModelInput = root.querySelector("#summary-local-model");

        if (!summarizeButton || !summaryResult) return;
        if (summarizeButton.dataset.bound === "true") return;
        bindModelPresets(root, localModelInput);
        summarizeButton.dataset.bound = "true";

        summarizeButton.addEventListener("click", async () => {
            const bookIds = getCurrentBookIds();
            if (bookIds === null) {
                setStatus(summaryStatus, "Откройте книгу в ридере перед запуском конспекта.", true);
                return;
            }

            const compressionLevel = root.querySelector("#compression-level")?.value || "medium";
            const preferences = (root.querySelector("#custom-preferences")?.value || "").trim();
            const answerMode = "hybrid";
            const localModel = (localModelInput?.value || "").trim();

            summaryResult.textContent = "Формирую конспект...";
            if (summaryCitations) summaryCitations.innerHTML = "";
            setStatus(summaryStatus, "Выполняется анализ...");

            try {
                const data = await authorizedPost("/api/books/summary", {
                    compression_level: compressionLevel,
                    preferences,
                    top_k: 8,
                    citations_k: 4,
                    book_ids: bookIds,
                    answer_mode: answerMode,
                    local_model: localModel || null,
                });

                if (!data.found) {
                    summaryResult.textContent = data.summary || "Не удалось сформировать конспект.";
                    setStatus(summaryStatus, "Конспект не найден", true);
                    return;
                }

                summaryResult.textContent = data.summary || "";
                renderCitations(summaryCitations, data.citations || []);

                const modeLabelMap = {
                    algorithm: "алгоритм (fallback)",
                    hybrid: "гибрид",
                };
                const modeLabel = modeLabelMap[String(data.answer_mode || "hybrid")] || "гибрид";
                const note = data.answer_mode_note ? ` · ${String(data.answer_mode_note)}` : "";
                setStatus(
                    summaryStatus,
                    `Готово (${modeLabel}, сжатие: ${data.compression_level || compressionLevel})${note}`,
                );
            } catch (error) {
                console.error(error);
                summaryResult.textContent = "Произошла ошибка при формировании конспекта.";
                setStatus(summaryStatus, normalizeErrorMessage(error, "Ошибка запроса"), true);
            }
        });
    }

    window.__initSummaryTool = function __initSummaryTool(rootNode) {
        bindSummaryEvents(rootNode || document);
    };

    window.__initSummaryTool(document);
})();

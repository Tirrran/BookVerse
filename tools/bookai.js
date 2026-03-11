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

    function setStatus(target, text, isError = false) {
        if (!target) return;
        target.textContent = text || "";
        target.classList.toggle("error", Boolean(isError));
    }

    async function safeJson(response) {
        try {
            return await response.json();
        } catch (error) {
            return {};
        }
    }

    function getScopeBookIds(root) {
        const scope = root.querySelector('input[name="search-scope"]:checked')?.value;
        if (scope === "all") return [];

        const currentBookId = Number(localStorage.getItem("currentBookId"));
        if (!currentBookId || Number.isNaN(currentBookId)) {
            return null;
        }
        return [currentBookId];
    }

    function renderFragments(target, fragments) {
        if (!target) return;
        target.innerHTML = "";
        fragments.forEach((item) => {
            const card = document.createElement("div");
            card.className = "result-item";

            const chapterMeta = item.location?.chapter
                ? `глава ${item.location.chapter}`
                : "";
            const locationMeta = `строки ${item.location.line_start}-${item.location.line_end}`;
            const scoreMeta = `score: ${item.score}`;
            const meta = [item.book_title, chapterMeta, locationMeta, scoreMeta]
                .filter(Boolean)
                .join(" | ");

            card.innerHTML = `
                <div class="result-meta">${meta}</div>
                <div class="result-text">${item.fragment}</div>
            `;
            target.appendChild(card);
        });
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
            throw new Error(data.detail || "Ошибка запроса");
        }
        return data;
    }

    function bindSearchEvents(root) {
        const searchQueryInput = root.querySelector("#search-query");
        const searchButton = root.querySelector("#search-button");
        const searchStatus = root.querySelector("#search-status");
        const searchResults = root.querySelector("#search-results");

        if (!searchButton || !searchQueryInput) return;
        if (searchButton.dataset.bound === "true") return;

        searchButton.dataset.bound = "true";

        searchButton.addEventListener("click", async () => {
            const query = searchQueryInput.value.trim();
            if (!query) {
                setStatus(searchStatus, "Введите запрос для поиска", true);
                return;
            }

            const bookIds = getScopeBookIds(root);
            if (bookIds === null) {
                setStatus(searchStatus, "Откройте книгу или выберите поиск по всем книгам", true);
                return;
            }

            if (searchResults) searchResults.innerHTML = "";
            setStatus(searchStatus, "Ищу фрагменты...");

            try {
                const data = await authorizedPost("/api/books/search", {
                    query,
                    top_k: 5,
                    book_ids: bookIds,
                });

                if (!data.found) {
                    setStatus(searchStatus, data.message || "Ничего не найдено");
                    return;
                }

                setStatus(searchStatus, `Найдено фрагментов: ${data.fragments.length}`);
                renderFragments(searchResults, data.fragments);
            } catch (error) {
                console.error(error);
                setStatus(searchStatus, error.message || "Ошибка поиска", true);
            }
        });

        searchQueryInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                searchButton.click();
            }
        });
    }

    function bindAskEvents(root) {
        const questionInput = root.querySelector("#question-input");
        const askButton = root.querySelector("#ask-button");
        const answerStatus = root.querySelector("#answer-status");
        const answerBox = root.querySelector("#answer-box");
        const citationsList = root.querySelector("#citations-list");

        if (!askButton || !questionInput) return;
        if (askButton.dataset.bound === "true") return;

        askButton.dataset.bound = "true";

        askButton.addEventListener("click", async () => {
            const question = questionInput.value.trim();
            if (!question) {
                setStatus(answerStatus, "Введите вопрос", true);
                return;
            }

            const bookIds = getScopeBookIds(root);
            if (bookIds === null) {
                setStatus(answerStatus, "Откройте книгу или выберите поиск по всем книгам", true);
                return;
            }

            if (answerBox) answerBox.textContent = "";
            if (citationsList) citationsList.innerHTML = "";
            setStatus(answerStatus, "Формирую ответ...");

            try {
                const data = await authorizedPost("/api/books/ask", {
                    question,
                    top_k: 5,
                    citations_k: 3,
                    book_ids: bookIds,
                });

                if (answerBox) answerBox.textContent = data.answer || "";

                if (!data.found) {
                    setStatus(answerStatus, data.answer || "Ответ не найден в загруженных книгах");
                    return;
                }

                setStatus(answerStatus, `Готово. Цитат: ${(data.citations || []).length}`);
                renderFragments(citationsList, data.citations || []);
            } catch (error) {
                console.error(error);
                setStatus(answerStatus, error.message || "Ошибка при ответе на вопрос", true);
            }
        });

        questionInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                askButton.click();
            }
        });
    }

    function bindBookAiEvents(root) {
        bindSearchEvents(root);
        bindAskEvents(root);
    }

    window.__initBookAiTool = function __initBookAiTool(rootNode) {
        const root = rootNode || document;
        bindBookAiEvents(root);
    };

    // Инициализация при первом открытии.
    window.__initBookAiTool(document);
})();

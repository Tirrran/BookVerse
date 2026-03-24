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

    function normalizeErrorMessage(source, fallback = "Ошибка запроса") {
        if (!source) return fallback;
        if (source instanceof Error) return normalizeErrorMessage(source.message, fallback);
        if (typeof source === "string") return source.trim() || fallback;

        if (typeof source === "object") {
            if (typeof source.detail === "string" && source.detail.trim()) return source.detail.trim();
            if (typeof source.message === "string" && source.message.trim()) return source.message.trim();
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

    function renderQuestions(target, questions) {
        if (!target) return;
        target.innerHTML = "";

        const safeQuestions = Array.isArray(questions) ? questions : [];
        if (!safeQuestions.length) {
            target.textContent = "Вопросы не сформированы.";
            return;
        }

        safeQuestions.forEach((item, index) => {
            const card = document.createElement("div");
            card.className = "quiz-card";

            const questionText = document.createElement("div");
            questionText.className = "quiz-question";
            questionText.textContent = `${index + 1}. ${item.question || ""}`;
            card.appendChild(questionText);

            const answerText = document.createElement("div");
            answerText.className = "quiz-answer";
            answerText.textContent = `Ответ: ${item.answer || ""}`;
            answerText.hidden = true;
            card.appendChild(answerText);

            const citation = item.citation || {};
            const location = citation.location || {};
            const chapterText = location.chapter ? `глава ${location.chapter}` : "";
            const linesText =
                location.line_start && location.line_end
                    ? `строки ${location.line_start}-${location.line_end}`
                    : "";
            const sourceMeta = [citation.book_title, chapterText, linesText]
                .filter(Boolean)
                .join(" | ");

            if (sourceMeta) {
                const sourceNode = document.createElement("div");
                sourceNode.className = "quiz-source";
                sourceNode.textContent = `Источник: ${sourceMeta}`;
                sourceNode.hidden = true;
                card.appendChild(sourceNode);
            }

            const controls = document.createElement("div");
            controls.className = "quiz-controls";

            const showButton = document.createElement("button");
            showButton.type = "button";
            showButton.className = "quiz-toggle-btn";
            showButton.textContent = "Показать ответ";
            showButton.addEventListener("click", () => {
                const willShow = answerText.hidden;
                answerText.hidden = !willShow;
                const sourceNode = card.querySelector(".quiz-source");
                if (sourceNode) sourceNode.hidden = !willShow;
                showButton.textContent = willShow ? "Скрыть ответ" : "Показать ответ";
            });
            controls.appendChild(showButton);

            card.appendChild(controls);
            target.appendChild(card);
        });
    }

    function bindQuizEvents(root) {
        const generateButton = root.querySelector("#generate-button");
        const quizResult = root.querySelector("#quiz-result");
        const quizStatus = root.querySelector("#quiz-status");

        if (!generateButton || !quizResult) return;
        if (generateButton.dataset.bound === "true") return;
        generateButton.dataset.bound = "true";

        generateButton.addEventListener("click", async () => {
            const bookIds = getCurrentBookIds();
            if (bookIds === null) {
                setStatus(quizStatus, "Откройте книгу в ридере перед запуском викторины.", true);
                return;
            }

            const difficulty = root.querySelector("#difficulty")?.value || "medium";
            const questionCount = Number(root.querySelector("#question-count")?.value || 8);
            const preferences = (root.querySelector("#custom-input")?.value || "").trim();

            quizResult.textContent = "Формирую вопросы...";
            setStatus(quizStatus, "Выполняется анализ...");

            try {
                const data = await authorizedPost("/api/books/quiz", {
                    difficulty,
                    question_count: questionCount,
                    preferences,
                    book_ids: bookIds,
                });

                if (!data.found) {
                    quizResult.textContent = data.message || "Не удалось сформировать викторину.";
                    setStatus(quizStatus, "Викторина не собрана", true);
                    return;
                }

                renderQuestions(quizResult, data.questions || []);
                setStatus(
                    quizStatus,
                    `Готово: ${Array.isArray(data.questions) ? data.questions.length : 0} вопросов (${data.difficulty || difficulty})`,
                );
            } catch (error) {
                console.error(error);
                quizResult.textContent = "Произошла ошибка при генерации викторины.";
                setStatus(quizStatus, normalizeErrorMessage(error, "Ошибка запроса"), true);
            }
        });
    }

    window.__initQuizTool = function __initQuizTool(rootNode) {
        bindQuizEvents(rootNode || document);
    };

    window.__initQuizTool(document);
})();

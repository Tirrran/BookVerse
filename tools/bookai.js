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

    function setStatus(target, text, isError = false) {
        if (!target) return;
        target.textContent = text || "";
        target.classList.toggle("error", Boolean(isError));
    }

    function formatIntentLabel(intent) {
        const labels = {
            plot: "Общий сюжет",
            chapter: "Ответ по главе",
            actions: "Действия персонажа",
            protagonist: "Главный герой",
            name_lookup: "Поиск имени",
            character_description: "Описание героя",
            motivation: "Мотивация персонажа",
            relationships: "Отношения персонажей",
            finale: "Финал",
            beginning: "Начало",
            middle: "Середина",
        };
        return labels[String(intent || "").toLowerCase()] || "Ответ по тексту";
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

    function getScopeBookIds(root) {
        const scope = root.querySelector('input[name="search-scope"]:checked')?.value;
        if (scope === "all") return [];

        const currentBookId = Number(localStorage.getItem("currentBookId"));
        if (!currentBookId || Number.isNaN(currentBookId)) {
            return null;
        }
        return [currentBookId];
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

    function renderFragments(target, fragments, options = {}) {
        if (!target) return;
        target.innerHTML = "";
        const canOpenInReader =
            Boolean(options.openInReader) &&
            typeof window.openSearchResultInReader === "function";

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
            const evidenceText = String(item.evidence_text || "").trim();
            const evidenceHtml = evidenceText
                ? `<div class="result-evidence">Опорный фрагмент: ${evidenceText}</div>`
                : "";

            card.innerHTML = `
                <div class="result-meta">${meta}</div>
                <div class="result-text">${item.fragment}</div>
                ${evidenceHtml}
            `;

            if (canOpenInReader) {
                card.classList.add("result-item--clickable");
                card.title = "Открыть этот фрагмент в тексте";
                card.addEventListener("click", () => {
                    window.openSearchResultInReader({
                        ...item,
                        query: options.query || "",
                    });
                    if (typeof window.toggleReaderSearchPanel === "function") {
                        window.toggleReaderSearchPanel(false);
                    }
                });
            }

            target.appendChild(card);
        });
    }

    function findCitationForChapter(data, chapterNumber) {
        const citations = Array.isArray(data?.citations) ? data.citations : [];
        const target = Number(chapterNumber);
        if (!Number.isFinite(target) || target <= 0) return null;
        return (
            citations.find((item) => Number(item?.location?.chapter) === target) ||
            citations[0] ||
            null
        );
    }

    function buildChapterJumpPayload(data, chapterNumber) {
        const chapter = Number(chapterNumber);
        const citation = findCitationForChapter(data, chapter);
        const payload = {
            book_title: citation?.book_title || "",
            fragment: String(citation?.fragment || "").trim(),
            location: {
                chapter,
                line_start: citation?.location?.line_start || null,
                line_end: citation?.location?.line_end || null,
                char_start: citation?.location?.char_start || null,
                char_end: citation?.location?.char_end || null,
            },
            query: `глава ${chapter}`,
        };
        return payload;
    }

    function openChapterFromCard(root, data, chapterNumber) {
        const chapter = Number(chapterNumber);
        if (!Number.isFinite(chapter) || chapter <= 0) return;

        const jumpPayload = buildChapterJumpPayload(data, chapter);
        if (typeof window.openSearchResultInReader === "function") {
            window.openSearchResultInReader(jumpPayload);
            if (typeof window.toggleReaderSearchPanel === "function") {
                window.toggleReaderSearchPanel(false);
            }
            if (typeof window.toggleChapters === "function") {
                window.toggleChapters(false);
            }
            return;
        }

        const currentBookId = Number(localStorage.getItem("currentBookId"));
        if (!currentBookId || Number.isNaN(currentBookId)) return;
        localStorage.setItem(
            "bookversePendingReaderJump",
            JSON.stringify({
                bookId: currentBookId,
                chapter,
                result: jumpPayload,
            }),
        );
        window.location.href = `reader.html?id=${currentBookId}`;
    }

    function renderCharacterCard(root, data) {
        const card = root.querySelector("#character-card");
        const nameNode = root.querySelector("#character-card-name");
        const focusNode = root.querySelector("#character-card-focus");
        const genderNode = root.querySelector("#character-card-gender");
        const sourceNode = root.querySelector("#character-card-source");
        const roleNode = root.querySelector("#character-card-role");
        const traitsNode = root.querySelector("#character-card-traits");
        const actionsNode = root.querySelector("#character-card-actions");
        const goalsNode = root.querySelector("#character-card-goals");
        const relationsNode = root.querySelector("#character-card-relations");
        const evolutionNode = root.querySelector("#character-card-evolution");
        const chaptersNode = root.querySelector("#character-card-chapters");
        const noteNode = root.querySelector("#character-card-note");

        if (!card || !nameNode || !focusNode || !noteNode) return;

        const payload = data?.character_card || null;
        const mainCharacters = Array.isArray(data?.main_characters)
            ? data.main_characters.filter(Boolean)
            : [];

        const characterName = payload?.name || mainCharacters[0] || "";
        if (!characterName) {
            card.hidden = true;
            nameNode.textContent = "";
            focusNode.textContent = "";
            if (genderNode) genderNode.textContent = "";
            if (sourceNode) sourceNode.textContent = "";
            if (roleNode) roleNode.textContent = "";
            if (traitsNode) traitsNode.textContent = "";
            if (actionsNode) actionsNode.textContent = "";
            if (goalsNode) goalsNode.textContent = "";
            if (relationsNode) relationsNode.textContent = "";
            if (evolutionNode) evolutionNode.textContent = "";
            if (chaptersNode) chaptersNode.textContent = "";
            noteNode.textContent = "";
            return;
        }

        const noteText =
            payload?.note ||
            payload?.excerpt ||
            (mainCharacters.length > 1
                ? `Связанные персонажи: ${mainCharacters.slice(1, 3).join(", ")}`
                : "Портрет сформирован по найденным цитатам.");

        nameNode.textContent = characterName;
        focusNode.textContent = `Фокус ответа: ${formatIntentLabel(data?.intent)}`;
        if (genderNode) {
            const genderText =
                payload?.gender_label ||
                (payload?.gender ? String(payload.gender) : "");
            genderNode.textContent = genderText
                ? `Пол по тексту: ${genderText}`
                : "";
        }
        if (sourceNode) {
            const mode = String(payload?.mode || "").toLowerCase();
            sourceNode.textContent =
                mode === "llm"
                    ? "Источник карточки: локальная LLM + цитаты"
                    : "Источник карточки: алгоритм + цитаты";
        }
        if (roleNode) {
            const roleText = String(payload?.role || "").trim();
            roleNode.textContent = roleText ? `Роль: ${roleText}` : "";
        }
        if (traitsNode) {
            const traits = Array.isArray(payload?.traits) ? payload.traits.filter(Boolean) : [];
            traitsNode.textContent = traits.length ? `Черты: ${traits.join(", ")}` : "";
        }
        if (actionsNode) {
            const actions = Array.isArray(payload?.actions) ? payload.actions.filter(Boolean) : [];
            actionsNode.textContent = actions.length ? `Действия: ${actions.join(", ")}` : "";
        }
        if (goalsNode) {
            const goals = Array.isArray(payload?.goals) ? payload.goals.filter(Boolean) : [];
            goalsNode.textContent = goals.length ? `Цели: ${goals.join(", ")}` : "";
        }
        if (relationsNode) {
            const relations = Array.isArray(payload?.relations)
                ? payload.relations.filter(Boolean)
                : [];
            relationsNode.textContent = relations.length ? `Связи: ${relations.join(", ")}` : "";
        }
        if (evolutionNode) {
            const evolution = String(payload?.evolution || "").trim();
            evolutionNode.textContent = evolution ? `Эволюция: ${evolution}` : "";
        }
        if (chaptersNode) {
            const chapterRefs = Array.isArray(payload?.chapter_refs)
                ? payload.chapter_refs
                    .map((item) => Number(item))
                    .filter((item) => Number.isFinite(item) && item > 0)
                : [];
            chaptersNode.innerHTML = "";
            if (chapterRefs.length) {
                const prefix = document.createElement("span");
                prefix.textContent = "Главы в карточке:";
                chaptersNode.appendChild(prefix);

                chapterRefs.forEach((chapter) => {
                    const button = document.createElement("button");
                    button.type = "button";
                    button.className = "chapter-ref-chip";
                    button.textContent = `Гл. ${chapter}`;
                    button.addEventListener("click", () => {
                        openChapterFromCard(root, data, chapter);
                    });
                    chaptersNode.appendChild(button);
                });
            }
        }
        noteNode.textContent = noteText;
        card.hidden = false;
    }

    function renderQualityBox(root, data) {
        const qualityBox = root.querySelector("#quality-box");
        const confidenceNode = root.querySelector("#quality-confidence");
        const groundingNode = root.querySelector("#quality-grounding");
        const reasonsNode = root.querySelector("#quality-reasons");
        if (!qualityBox || !confidenceNode || !groundingNode || !reasonsNode) return;

        const confidenceRaw = Number(data?.confidence);
        const confidencePct = Number.isFinite(confidenceRaw)
            ? Math.round(Math.max(0, Math.min(1, confidenceRaw)) * 100)
            : null;
        const confidenceLabel = String(data?.confidence_label || "").trim();
        const groundingScoreRaw = Number(data?.grounding_score);
        const groundingPct = Number.isFinite(groundingScoreRaw)
            ? Math.round(Math.max(0, Math.min(1, groundingScoreRaw)) * 100)
            : null;
        const groundingStatus = String(data?.grounding_status || "").trim();

        if (confidencePct === null && groundingPct === null) {
            qualityBox.hidden = true;
            confidenceNode.textContent = "";
            groundingNode.textContent = "";
            reasonsNode.innerHTML = "";
            return;
        }

        confidenceNode.textContent =
            confidencePct === null
                ? ""
                : `Уверенность: ${confidencePct}%${confidenceLabel ? ` (${confidenceLabel})` : ""}`;
        groundingNode.textContent =
            groundingPct === null
                ? ""
                : `Опора на цитаты: ${groundingPct}%${groundingStatus ? ` (${groundingStatus})` : ""}`;

        const reasons = Array.isArray(data?.confidence_reasons)
            ? data.confidence_reasons.map((item) => String(item || "").trim()).filter(Boolean)
            : [];
        reasonsNode.innerHTML = reasons.map((item) => `<li>${item}</li>`).join("");
        qualityBox.hidden = false;
    }

    function renderTimeline(root, data) {
        const box = root.querySelector("#timeline-box");
        const list = root.querySelector("#timeline-list");
        if (!box || !list) return;
        list.innerHTML = "";

        const timeline = Array.isArray(data?.timeline) ? data.timeline : [];
        if (!timeline.length) {
            box.hidden = true;
            return;
        }

        timeline.forEach((item) => {
            const card = document.createElement("div");
            card.className = "timeline-item";
            const label = String(item?.label || "").trim();
            const eventText = String(item?.event || "").trim();
            if (!eventText) return;
            card.innerHTML = `
                <div class="timeline-label">${label || "Эпизод"}</div>
                <div class="timeline-event">${eventText}</div>
            `;
            list.appendChild(card);
        });
        box.hidden = !list.children.length;
    }

    function renderCharacterGraph(root, data) {
        const box = root.querySelector("#graph-box");
        const nodesWrap = root.querySelector("#graph-nodes");
        const edgesWrap = root.querySelector("#graph-edges");
        if (!box || !nodesWrap || !edgesWrap) return;

        nodesWrap.innerHTML = "";
        edgesWrap.innerHTML = "";

        const graph = data?.character_graph || {};
        const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
        const edges = Array.isArray(graph?.edges) ? graph.edges : [];
        if (!nodes.length && !edges.length) {
            box.hidden = true;
            return;
        }

        nodes.slice(0, 12).forEach((node) => {
            const chip = document.createElement("span");
            chip.className = "graph-node";
            if (node?.is_focus) chip.classList.add("graph-node--focus");
            chip.textContent = String(node?.label || node?.id || "").trim();
            if (chip.textContent) nodesWrap.appendChild(chip);
        });

        edges.slice(0, 12).forEach((edge) => {
            const card = document.createElement("div");
            card.className = "graph-edge";
            const source = String(edge?.source || "").trim();
            const target = String(edge?.target || "").trim();
            const weight = Number(edge?.weight) || 1;
            const example = String(edge?.example || "").trim();
            if (!source || !target) return;
            card.innerHTML = `
                <div>${source} ↔ ${target} · связь: ${weight}</div>
                ${example ? `<div class="graph-edge-example">${example}</div>` : ""}
            `;
            edgesWrap.appendChild(card);
        });

        box.hidden = !(nodesWrap.children.length || edgesWrap.children.length);
    }

    function bindQaPresets(root, questionInput, askButton) {
        const presets = root.querySelector("#qa-presets");
        if (!presets || !questionInput || !askButton) return;
        if (presets.dataset.bound === "true") return;
        presets.dataset.bound = "true";

        presets.addEventListener("click", (event) => {
            const target = event.target.closest(".qa-preset-btn");
            if (!target) return;
            const question = String(target.dataset.question || "").trim();
            if (!question) return;
            questionInput.value = question;
            questionInput.focus();
            askButton.click();
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
            throw new Error(normalizeErrorMessage(data, "Ошибка запроса"));
        }
        return data;
    }

    function bindSearchEvents(root) {
        const searchQueryInput = root.querySelector("#search-query");
        const searchButton = root.querySelector("#search-button");
        const searchStatus = root.querySelector("#search-status");
        const searchResults = root.querySelector("#search-results");
        const strictPhraseCheckbox = root.querySelector("#search-strict-phrase");
        const wholeWordsCheckbox = root.querySelector("#search-whole-words");
        const chapterNumberInput = root.querySelector("#search-chapter-number");

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
            const strictPhrase = Boolean(strictPhraseCheckbox?.checked);
            const wholeWords = Boolean(wholeWordsCheckbox?.checked);
            const chapterNumberRaw = Number(chapterNumberInput?.value);
            const chapterNumber = Number.isFinite(chapterNumberRaw) && chapterNumberRaw > 0
                ? Math.floor(chapterNumberRaw)
                : null;

            try {
                const data = await authorizedPost("/api/books/search", {
                    query,
                    top_k: 5,
                    book_ids: bookIds,
                    strict_phrase: strictPhrase,
                    whole_words: wholeWords,
                    chapter_number: chapterNumber,
                });

                if (!data.found) {
                    setStatus(searchStatus, normalizeErrorMessage(data.message, "Ничего не найдено"));
                    return;
                }

                const filterBits = [];
                if (strictPhrase) filterBits.push("точная фраза");
                if (wholeWords) filterBits.push("целые слова");
                if (chapterNumber !== null) filterBits.push(`глава ${chapterNumber}`);
                const filterTail = filterBits.length ? ` · фильтры: ${filterBits.join(", ")}` : "";
                setStatus(searchStatus, `Найдено фрагментов: ${data.fragments.length}${filterTail}`);
                renderFragments(searchResults, data.fragments);
            } catch (error) {
                console.error(error);
                setStatus(searchStatus, normalizeErrorMessage(error, "Ошибка поиска"), true);
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
        const localModelInput = root.querySelector("#local-llm-model");

        if (!askButton || !questionInput) return;
        if (askButton.dataset.bound === "true") return;

        bindModelPresets(root, localModelInput);
        askButton.dataset.bound = "true";
        bindQaPresets(root, questionInput, askButton);

        askButton.addEventListener("click", async () => {
            const question = questionInput.value.trim();
            if (!question) {
                setStatus(answerStatus, "Введите вопрос", true);
                return;
            }
            const answerMode = "hybrid";
            const localModel = (localModelInput?.value || "").trim();

            const bookIds = getScopeBookIds(root);
            if (bookIds === null) {
                setStatus(answerStatus, "Откройте книгу или выберите поиск по всем книгам", true);
                return;
            }

            if (answerBox) answerBox.textContent = "";
            if (citationsList) citationsList.innerHTML = "";
            renderCharacterCard(root, null);
            renderQualityBox(root, null);
            renderTimeline(root, null);
            renderCharacterGraph(root, null);
            setStatus(answerStatus, "Формирую ответ...");

            try {
                const data = await authorizedPost("/api/books/ask", {
                    question,
                    top_k: 8,
                    citations_k: 4,
                    book_ids: bookIds,
                    answer_mode: answerMode,
                    local_model: localModel || null,
                });

                if (answerBox) answerBox.textContent = data.answer || "";
                renderCharacterCard(root, data);
                renderQualityBox(root, data);
                renderTimeline(root, data);
                renderCharacterGraph(root, data);

                if (!data.found) {
                    setStatus(
                        answerStatus,
                        normalizeErrorMessage(
                            data.answer,
                            "Ответ не найден в загруженных книгах",
                        ),
                    );
                    return;
                }

                const modeLabelMap = {
                    algorithm: "алгоритм (fallback)",
                    hybrid: "гибрид",
                };
                const modeLabel = modeLabelMap[String(data.answer_mode || "hybrid")] || "гибрид";
                const extraNote = data.answer_mode_note
                    ? ` · ${String(data.answer_mode_note)}`
                    : "";
                const groundingBits = [];
                if (typeof data.grounding_score === "number") {
                    groundingBits.push(`grounding: ${Math.round(data.grounding_score * 100)}%`);
                }
                if (data.grounding_status === "weak") {
                    groundingBits.push("слабая опора на цитаты");
                }
                if (typeof data.confidence === "number") {
                    groundingBits.push(`уверенность: ${Math.round(data.confidence * 100)}%`);
                }
                if (data.grounding_warning) {
                    groundingBits.push(String(data.grounding_warning));
                }
                const groundingNote = groundingBits.length ? ` · ${groundingBits.join(" · ")}` : "";
                setStatus(
                    answerStatus,
                    `Готово (${modeLabel}). Цитат: ${(data.citations || []).length}${extraNote}${groundingNote}`,
                );
                renderFragments(citationsList, data.citations || [], {
                    openInReader: true,
                    query: question,
                });
            } catch (error) {
                console.error(error);
                setStatus(
                    answerStatus,
                    normalizeErrorMessage(error, "Ошибка при ответе на вопрос"),
                    true,
                );
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

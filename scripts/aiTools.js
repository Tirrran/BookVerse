// scripts/aiTools.js

const TOOL_VERSION = "20260309c";

// Алгоритмический набор инструментов без внешних AI API.
window.aiTools = {
    book_search: {
        icon: "🔎",
        title: "Поиск фрагментов",
        description: "Найти релевантные места в книге по запросу",
        html: "tools/book-search.html",
        script: "tools/bookai.js",
        styles: "tools/bookai.css",
        initHook: "__initBookAiTool",
    },
    book_qa: {
        icon: "💬",
        title: "Ответы по книге",
        description: "Ответ на вопрос по тексту с цитатами-основаниями",
        html: "tools/book-qa.html",
        script: "tools/bookai.js",
        styles: "tools/bookai.css",
        initHook: "__initBookAiTool",
    },
};

function withVersion(path) {
    const divider = path.includes("?") ? "&" : "?";
    return `${path}${divider}v=${TOOL_VERSION}`;
}

function clearDynamicToolAssets() {
    document.querySelectorAll('[data-tool-asset="true"]').forEach((node) => node.remove());
}

window.showToolList = function showToolList() {
    const panelContent = document.getElementById("panel-content");
    if (!panelContent) return;

    const cardsHtml = Object.entries(window.aiTools)
        .map(
            ([key, tool]) => `
                <button class="tool-card" type="button" data-tool="${key}">
                    <div class="tool-icon">${tool.icon}</div>
                    <h3>${tool.title}</h3>
                    <p>${tool.description}</p>
                </button>
            `,
        )
        .join("");

    panelContent.innerHTML = `
        <div class="panel-header">
            <h2>Инструменты</h2>
            <button class="back-btn" onclick="showMenu()">← Назад</button>
        </div>
        <div class="tool-container">
            <p style="margin: 0 0 12px; color: #9ca3af; font-size: 13px;">
                Алгоритмический режим: без внешних AI/API, только работа по загруженным текстам.
            </p>
            <div class="tools-grid">${cardsHtml}</div>
        </div>
    `;

    panelContent.querySelectorAll(".tool-card").forEach((card) => {
        card.addEventListener("click", () => {
            const toolId = card.dataset.tool;
            if (toolId) {
                window.selectTool(toolId);
            }
        });
    });
};

window.selectTool = async function selectTool(toolName) {
    const tool = window.aiTools[toolName];
    if (!tool) return;

    const panelContent = document.getElementById("panel-content");
    if (!panelContent) return;

    panelContent.innerHTML = `
        <div class="panel-header">
            <h2>${tool.title}</h2>
            <button class="back-btn" onclick="showToolList()">← Назад</button>
        </div>
        <div class="tool-content loading">
            <div class="spinner"></div>
            <p>Загрузка инструмента...</p>
        </div>
    `;

    try {
        const htmlResponse = await fetch(withVersion(tool.html), { cache: "no-store" });
        if (!htmlResponse.ok) {
            throw new Error("Не удалось загрузить HTML инструмента");
        }

        const html = await htmlResponse.text();
        const toolContainer = document.createElement("div");
        toolContainer.className = "tool-container";
        toolContainer.innerHTML = html;

        const placeholder = panelContent.querySelector(".tool-content");
        if (placeholder) {
            placeholder.replaceWith(toolContainer);
        }

        clearDynamicToolAssets();

        if (tool.styles) {
            const styleLink = document.createElement("link");
            styleLink.rel = "stylesheet";
            styleLink.href = withVersion(tool.styles);
            styleLink.dataset.toolAsset = "true";
            document.head.appendChild(styleLink);
        }

        if (tool.script) {
            await new Promise((resolve, reject) => {
                const scriptTag = document.createElement("script");
                scriptTag.src = withVersion(tool.script);
                // Инструменты грузим как ESM-модули, чтобы можно было импортировать локальное ядро.
                scriptTag.type = "module";
                scriptTag.dataset.toolAsset = "true";
                scriptTag.onload = () => resolve();
                scriptTag.onerror = () => reject(new Error("Не удалось загрузить JS инструмента"));
                document.body.appendChild(scriptTag);
            });
        }

        if (tool.initHook && typeof window[tool.initHook] === "function") {
            window[tool.initHook](toolContainer);
        }
    } catch (error) {
        console.error("Ошибка загрузки инструмента:", error);
        panelContent.innerHTML = `
            <div class="panel-header">
                <h2>${tool.title}</h2>
                <button class="back-btn" onclick="showToolList()">← Назад</button>
            </div>
            <div class="tool-content error">
                <p>${error.message || "Ошибка загрузки инструмента. Попробуйте позже."}</p>
            </div>
        `;
    }
};

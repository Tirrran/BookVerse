// scripts/menu.js

const rawHost = window.location.hostname || '127.0.0.1';
const apiHost = (rawHost === '0.0.0.0' || rawHost === '[::]') ? '127.0.0.1' : rawHost;
const API_BASE_CANDIDATES = Array.from(
    new Set([
        `http://${apiHost}:8000`,
        'http://127.0.0.1:8000',
        'http://localhost:8000',
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

    throw lastError || new Error('Не удалось подключиться к API');
}

function getAuthToken() {
    const existing = localStorage.getItem('authToken');
    if (existing) return existing;

    const fallback = 'auth-disabled';
    localStorage.setItem('authToken', fallback);
    return fallback;
}

function toggleMenu() {
    const panel = document.getElementById('right-panel');
    if (panel) {
        panel.classList.toggle('visible');
    }
}

window.toggleMenu = toggleMenu;

// Закрываем меню при клике снаружи
function bindOutsideClose() {
    const rightPanel = document.getElementById('right-panel');
    const menuButton = document.getElementById('menuButton');

    if (!rightPanel || !menuButton || document.body.dataset.menuOutsideBound === 'true') return;
    document.body.dataset.menuOutsideBound = 'true';

    document.addEventListener('click', (event) => {
        const isMenuButton = menuButton.contains(event.target);
        const isInsidePanel = rightPanel.contains(event.target);
        if (!isMenuButton && !isInsidePanel) {
            rightPanel.classList.remove('visible');
        }
    });

    rightPanel.addEventListener('click', (event) => {
        event.stopPropagation();
    });
}

async function loadUserProfile() {
    try {
        const response = await apiFetch('/api/user/profile', {
            headers: {
                Authorization: `Bearer ${getAuthToken()}`,
            },
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || 'Ошибка загрузки профиля');
        }

        return await response.json();
    } catch (error) {
        console.error('Ошибка загрузки профиля:', error);
        return null;
    }
}

async function showMenu() {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    panelContent.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>Загрузка профиля...</p>
        </div>
    `;

    const userData = await loadUserProfile();
    if (!userData) {
        panelContent.innerHTML = `
            <div class="error">
                <p>Ошибка загрузки профиля</p>
                <button onclick="showMenu()">Повторить</button>
            </div>
        `;
        return;
    }

    panelContent.innerHTML = `
        <div class="panel-header">
            <div class="user-profile">
                <div class="user-info">
                    <h3 class="username">${userData.name || 'Гость'}</h3>
                    <p class="user-email">${userData.email || 'guest@bookverse.local'}</p>
                </div>
            </div>
            <button class="icon-btn close-btn" id="closeBtn" onclick="toggleMenu()">✕</button>
        </div>
        <nav class="panel-nav">
            <ul class="menu-list">
                <li>
                    <button class="menu-item" onclick="showProfile()">
                        <span class="icon">👤</span>
                        <span class="text">Профиль</span>
                    </button>
                </li>
                <li>
                    <button class="menu-item" onclick="showToolList()">
                        <span class="icon">🧠</span>
                        <span class="text">Инструменты</span>
                    </button>
                </li>
                <li>
                    <button class="menu-item" onclick="openSettings()">
                        <span class="icon">⚙️</span>
                        <span class="text">Настройки</span>
                    </button>
                </li>
            </ul>
        </nav>
        <div class="logout-section">
            <button class="menu-item logout-btn" onclick="logout()">
                <span class="icon">🚪</span>
                <span class="text">Выйти</span>
            </button>
        </div>
    `;
}

async function showProfile() {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    panelContent.innerHTML = `
        <div class="loading">
            <div class="spinner"></div>
            <p>Загрузка профиля...</p>
        </div>
    `;

    try {
        const userData = await loadUserProfile();
        if (!userData) throw new Error('Не удалось загрузить данные профиля');

        const lastBook = userData.lastBook || userData.last_book || null;
        const booksInProgress = userData.stats?.books_in_progress || 0;
        const booksRead = userData.stats?.books_read || 0;

        panelContent.innerHTML = `
            <div class="panel-header">
                <button class="back-btn" onclick="showMenu()">← Назад</button>
                <h2>Профиль</h2>
            </div>
            <div class="profile-content">
                <div class="user-profile">
                    <div class="user-info">
                        <h3 class="username">${userData.name || 'Гость'}</h3>
                        <p class="user-email">${userData.email || 'guest@bookverse.local'}</p>
                    </div>
                </div>

                <div class="stats-section">
                    <h3>Статистика</h3>
                    <div class="user-stats">
                        <div class="stat-card">
                            <div class="number">${booksRead}</div>
                            <div class="label">Прочитано книг</div>
                        </div>
                        <div class="stat-card">
                            <div class="number">${booksInProgress}</div>
                            <div class="label">В процессе</div>
                        </div>
                    </div>
                </div>

                ${lastBook && lastBook.title ? `
                    <div class="last-book-section">
                        <h3>Последняя книга</h3>
                        <div class="last-book">
                            <h4>${lastBook.title}</h4>
                            <p class="last-read">Последнее чтение: ${lastBook.last_read ? new Date(lastBook.last_read).toLocaleDateString() : '—'}</p>
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    } catch (error) {
        console.error('Ошибка при загрузке профиля:', error);
        panelContent.innerHTML = `
            <div class="error">
                <p>Ошибка загрузки профиля</p>
                <button onclick="showProfile()">Повторить</button>
            </div>
        `;
    }
}

// Резервный рендер списка инструментов (если scripts/aiTools.js не загрузился)
function showToolListFallback() {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    const tools = Object.entries(window.aiTools || {});
    if (!tools.length) {
        panelContent.innerHTML = `
            <div class="panel-header">
                <h2>Инструменты</h2>
                <button class="back-btn" onclick="showMenu()">← Назад</button>
            </div>
            <div class="tool-content error">
                <p>Инструменты не загрузились. Обновите страницу.</p>
            </div>
        `;
        return;
    }

    const toolsHtml = tools.map(([id, tool]) => `
        <button class="tool-card" type="button" onclick="selectTool('${id}')">
            <div class="tool-icon">${tool.icon}</div>
            <h3>${tool.title}</h3>
            <p>${tool.description}</p>
        </button>
    `).join('');

    panelContent.innerHTML = `
        <div class="panel-header">
            <h2>Инструменты</h2>
            <button class="back-btn" onclick="showMenu()">← Назад</button>
        </div>
        <div class="tool-container">
            <div class="tools-grid">
                ${toolsHtml}
            </div>
        </div>
    `;
}

window.showMenu = showMenu;
window.showProfile = showProfile;
if (typeof window.showToolList !== 'function') {
    window.showToolList = showToolListFallback;
}

document.addEventListener('DOMContentLoaded', () => {
    bindOutsideClose();

    const menuButton = document.getElementById('menuButton');
    const panel = document.getElementById('right-panel');
    if (!menuButton || !panel) return;

    if (menuButton.dataset.menuBound !== 'true') {
        menuButton.dataset.menuBound = 'true';
        menuButton.addEventListener('click', () => {
            panel.classList.toggle('visible');
            if (panel.classList.contains('visible')) {
                showMenu();
            }
        });
    }
});

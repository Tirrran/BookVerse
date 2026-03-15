import { getBookMetas, getLibraryStats } from './localBooks.js';

function toggleMenu() {
    const panel = document.getElementById('right-panel');
    if (!panel) return;
    panel.classList.toggle('visible');
}

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

function getLocalProfile() {
    const stats = getLibraryStats();
    const books = getBookMetas();
    const lastBook = books[0] || null;

    return {
        name: localStorage.getItem('username') || 'Локальный пользователь',
        email: localStorage.getItem('userEmail') || 'offline@bookverse.local',
        stats,
        last_book: lastBook
            ? {
                title: lastBook.title || lastBook.filename,
                last_read: lastBook.upload_date,
            }
            : null,
    };
}

function showMenu() {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    const profile = getLocalProfile();

    panelContent.innerHTML = `
        <div class="panel-header">
            <div class="user-profile">
                <div class="user-info">
                    <h3 class="username">${profile.name}</h3>
                    <p class="user-email">${profile.email}</p>
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

function showProfile() {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    const profile = getLocalProfile();
    const booksRead = profile.stats?.books_read || 0;
    const booksInProgress = profile.stats?.books_in_progress || 0;

    panelContent.innerHTML = `
        <div class="panel-header">
            <button class="back-btn" onclick="showMenu()">← Назад</button>
            <h2>Профиль</h2>
        </div>
        <div class="profile-content">
            <div class="user-profile">
                <div class="user-info">
                    <h3 class="username">${profile.name}</h3>
                    <p class="user-email">${profile.email}</p>
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
            ${profile.last_book ? `
                <div class="last-book-section">
                    <h3>Последняя книга</h3>
                    <div class="last-book">
                        <h4>${profile.last_book.title}</h4>
                        <p class="last-read">Добавлена: ${new Date(profile.last_book.last_read).toLocaleDateString('ru-RU')}</p>
                    </div>
                </div>
            ` : ''}
        </div>
    `;
}

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

    const toolsHtml = tools
        .map(([id, tool]) => `
            <button class="tool-card" type="button" onclick="selectTool('${id}')">
                <div class="tool-icon">${tool.icon}</div>
                <h3>${tool.title}</h3>
                <p>${tool.description}</p>
            </button>
        `)
        .join('');

    panelContent.innerHTML = `
        <div class="panel-header">
            <h2>Инструменты</h2>
            <button class="back-btn" onclick="showMenu()">← Назад</button>
        </div>
        <div class="tool-container">
            <div class="tools-grid">${toolsHtml}</div>
        </div>
    `;
}

function logout() {
    localStorage.removeItem('authToken');
    localStorage.removeItem('username');
    localStorage.removeItem('userEmail');
    window.location.href = 'index.html';
}

window.toggleMenu = toggleMenu;
window.showMenu = showMenu;
window.showProfile = showProfile;
window.logout = logout;
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

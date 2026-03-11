// Удаляем импорт функций из main.js, так как теперь они определены здесь
// import { splitTextIntoPages, displayPage, createChapterList } from './main.js';

let bookText = '';
let totalPages = 0;
let currentPage = 1;
let pages = [];
const wordsPerPage = 500;
let chapters = [];
const rawHost = window.location.hostname || '127.0.0.1';
const API_HOST = (rawHost === '0.0.0.0' || rawHost === '[::]') ? '127.0.0.1' : rawHost;
const API_BASE_CANDIDATES = Array.from(
    new Set([
        `http://${API_HOST}:8000`,
        'http://127.0.0.1:8000',
        'http://localhost:8000',
    ]),
);
let apiBaseCache = null;

function getAuthToken() {
    const existing = localStorage.getItem('authToken');
    if (existing) return existing;
    const fallback = 'auth-disabled';
    localStorage.setItem('authToken', fallback);
    return fallback;
}

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

// Функция загрузки книги
async function loadBook() {
    const urlParams = new URLSearchParams(window.location.search);
    const bookId = urlParams.get('id');
    
    if (!bookId) {
        console.error('Book ID not provided');
        return;
    }

    try {
        const response = await apiFetch(`/books/${bookId}`, {
            headers: {
                'Authorization': `Bearer ${getAuthToken()}`
            }
        });

        if (!response.ok) {
            throw new Error('Failed to load book content');
        }

        const data = await response.json();
        bookText = data.content;
        localStorage.setItem('bookText', bookText);
        localStorage.setItem('currentBookId', String(bookId));

        // Разбиваем текст на страницы
        pages = splitIntoPages(bookText);
        totalPages = pages.length;

        // Загружаем сохраненный прогресс
        const savedPage = parseInt(localStorage.getItem(`book_${bookId}_page`)) || 1;
        currentPage = Math.min(savedPage, totalPages);

        // Отображаем текущую страницу
        displayPage(currentPage);
        
        // Обновляем UI
        updatePageCount();
        updateReadingProgress();
        
    } catch (error) {
        console.error('Error loading book:', error);
        document.getElementById('text-layer').innerHTML = `
            <div class="error-message">
                Ошибка загрузки книги. Пожалуйста, попробуйте позже.
            </div>
        `;
    }
}

// Функция отображения страницы
function displayPage(pageNum) {
    if (!pages || pageNum < 1 || pageNum > pages.length) {
        console.error('Invalid page number or pages not loaded');
        return;
    }

    const textLayer = document.getElementById('text-layer');
    if (!textLayer) {
        console.error('Text layer element not found');
        return;
    }

    currentPage = pageNum;
    textLayer.innerHTML = `<div class="page-content">${pages[pageNum - 1]}</div>`;

    // Сохраняем прогресс
    const bookId = new URLSearchParams(window.location.search).get('id');
    if (bookId) {
        localStorage.setItem(`book_${bookId}_page`, pageNum);
        updateReadingProgress();
    }

    // Обновляем номер страницы в UI
    const pageInput = document.getElementById('page-input');
    if (pageInput) {
        pageInput.value = pageNum;
    }
}

// Функция разбиения текста на страницы
function splitIntoPages(text) {
    const words = text.split(/\s+/);
    const pages = [];
    let currentPage = [];
    let wordCount = 0;

    for (const word of words) {
        currentPage.push(word);
        wordCount++;

        if (wordCount >= wordsPerPage) {
            pages.push(currentPage.join(' '));
            currentPage = [];
            wordCount = 0;
        }
    }

    if (currentPage.length > 0) {
        pages.push(currentPage.join(' '));
    }

    return pages;
}

// Функция обновления счетчика страниц
function updatePageCount() {
    const pageCount = document.getElementById('page-count');
    if (pageCount) {
        pageCount.textContent = totalPages;
    }
}

// Функция обновления прогресса чтения
function updateReadingProgress() {
    const percentage = Math.round((currentPage / totalPages) * 100);
    const percentageElement = document.getElementById('progress-percentage');
    if (percentageElement) {
        percentageElement.textContent = `${percentage}%`;
    }

    // Сохраняем прогресс на сервере только если есть ID книги
    const bookId = new URLSearchParams(window.location.search).get('id');
    if (bookId && !isNaN(parseInt(bookId))) {  // Проверяем что ID - число
        saveProgress(bookId, percentage);
    }
}

// Функция сохранения прогресса на сервере
async function saveProgress(bookId, progress) {
    try {
        const response = await apiFetch(`/books/${bookId}/progress`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getAuthToken()}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ progress: parseInt(progress) })  // Убедимся что progress - число
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to save progress');
        }
    } catch (error) {
        console.error('Error saving progress:', error);
    }
}

// Инициализация навигации
function initializeNavigation() {
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    const pageInput = document.getElementById('page-input');

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentPage > 1) {
                displayPage(currentPage - 1);
            }
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (currentPage < totalPages) {
                displayPage(currentPage + 1);
            }
        });
    }

    if (pageInput) {
        pageInput.addEventListener('change', () => {
            const page = parseInt(pageInput.value);
            if (page >= 1 && page <= totalPages) {
                displayPage(page);
            } else {
                pageInput.value = currentPage;
            }
        });
    }
}

// Оставляем только один обработчик DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('Страница reader.html загружена');
    
    // Загружаем книгу
    loadBook();
    
    // Инициализируем навигацию
    initializeNavigation();
    
    // Инициализируем обработчики панелей
    initializePanels();
});

// Функция инициализации панелей
function initializePanels() {
    const toggleChaptersBtn = document.getElementById('toggle-chapters');
    const closeChaptersBtn = document.getElementById('close-chapters');
    const chaptersPanel = document.getElementById('chapters-panel');
    const menuButton = document.getElementById('menuButton');
    const sidePanel = document.getElementById('right-panel');
    const closeMenuBtn = document.getElementById('close-menu');

    // Обработчик для кнопки глав
    if (toggleChaptersBtn && chaptersPanel) {
        toggleChaptersBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            chaptersPanel.classList.toggle('active');
            sidePanel?.classList.remove('visible');
        });
    }

    // Обновлённый обработчик меню
    if (menuButton && sidePanel) {
        menuButton.addEventListener('click', (e) => {
            e.stopPropagation();
            sidePanel.classList.toggle('visible');
            chaptersPanel?.classList.remove('active');
            showMenu(); // Принудительно обновляем содержимое меню
        });
    }

    // Закрытие панелей
    if (closeChaptersBtn) {
        closeChaptersBtn.addEventListener('click', () => {
            chaptersPanel.classList.remove('active');
        });
    }

    if (closeMenuBtn) {
        closeMenuBtn.addEventListener('click', () => {
            sidePanel.classList.remove('visible');
        });
    }

    // Закрытие при клике вне панелей
    document.addEventListener('click', (e) => {
        if (!chaptersPanel?.contains(e.target) && 
            !toggleChaptersBtn?.contains(e.target)) {
            chaptersPanel?.classList.remove('active');
        }
        
        if (!sidePanel?.contains(e.target) && 
            !menuButton?.contains(e.target)) {
            sidePanel?.classList.remove('visible');
        }
    });
}

// Добавляем функцию создания списка глав
function createChapterList() {
    const chaptersListDiv = document.getElementById('chapters-list');
    if (!chaptersListDiv) return;

    chaptersListDiv.innerHTML = ''; // Очищаем список перед заполнением

    if (chapters.length === 0) {
        chaptersListDiv.innerHTML = '<p>Главы не найдены.</p>';
        return;
    }

    // Создаём список глав
    const ul = document.createElement('ul');
    ul.style.listStyleType = 'none';
    ul.style.padding = '0';
    
    chapters.forEach((chapter) => {
        const li = document.createElement('li');
        li.style.margin = '5px 0';
        const button = document.createElement('button');
        button.textContent = chapter.title;
        button.style.width = '100%';
        button.style.textAlign = 'left';
        button.style.padding = '10px';
        button.style.border = 'none';
        button.style.backgroundColor = 'inherit';
        button.style.color = 'inherit';
        button.style.cursor = 'pointer';
        button.style.borderRadius = '5px';
        button.style.fontSize = '1em';
        button.style.transition = 'background 0.3s';

        // При клике на главу переходим на соответствующую страницу
        button.addEventListener('click', () => {
            displayPage(chapter.page);
            toggleChapters(); // Закрываем список глав после выбора
        });

        li.appendChild(button);
        ul.appendChild(li);
    });

    chaptersListDiv.appendChild(ul);
}

// Функция переключения панели глав
function toggleChapters() {
    const chaptersPanel = document.getElementById('chapters-panel');
    if (chaptersPanel) {
        chaptersPanel.classList.toggle('active');
    }
}

// Экспортируем только те функции, которые действительно определены в этом файле
export { 
    loadBook, 
    displayPage, 
    updateReadingProgress,
    splitIntoPages,
    createChapterList,
    toggleChapters
}; 

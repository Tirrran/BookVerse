// scripts/main.js

import { applySavedSettings } from './settings.js';

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

// Состояние библиотеки
let state = {
    books: [],
    isLoading: false,
    error: null
};
let uploadInProgress = false;

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

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', async () => {
    // Применяем сохраненные настройки
    applySavedSettings();
    
    // Применение сохранённого прогресса чтения, если есть
    const savedProgress = parseInt(localStorage.getItem('currentPage'), 10);
    if (savedProgress && !isNaN(savedProgress)) {
        currentPage = savedProgress;
    }

    // Отображение сохранённой страницы или первой
    displayPage(currentPage);

    // Инициализируем обработчики
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileUpload);
    }
    initializeUploadDropZone();

    // Загружаем библиотеку
    if (document.getElementById('books-grid')) {
        await loadLibrary();
    }
});

// В начале файла добавить проверку на существование элементов
document.addEventListener('DOMContentLoaded', () => {
    applySavedSettings();
    
    const elementsToCheck = [
        { id: 'books-grid', action: 'initLibrary' },
        { id: 'upload-overlay', action: 'hide' }
    ];

    elementsToCheck.forEach(item => {
        const element = document.getElementById(item.id);
        if (element) {
            if (item.event) {
                element.addEventListener(item.event, item.handler);
            }
            if (item.action === 'hide') {
                element.style.display = 'none';
            }
        }
    });
});

// Функция загрузки книг с сервера
async function fetchBooks() {
    const authToken = getAuthToken();

    try {
        const response = await apiFetch('/my-uploads', {
            headers: {
                'Authorization': `Bearer ${authToken}`
            }
        });
        
        if (response.ok) {
            const books = await response.json();
            console.log('Fetched books:', books);
            return books;
        } else {
            console.error('Error fetching books:', response.statusText);
            return null;
        }
    } catch (error) {
        console.error('Error loading books:', error);
        return null;
    }
}

// Функция обновления библиотеки
export async function loadLibrary() {
    console.log('Loading library...'); 
    
    const booksGrid = document.getElementById('books-grid');
    if (!booksGrid) {
        console.error('Books grid element not found');
        return;
    }

    try {
        state.isLoading = true;
        state.error = null;

        // Загружаем книги с сервера
        const books = await fetchBooks();
        if (books) {
            state.books = books;
            // Отображаем книги
            renderLibrary();
        }
    } catch (error) {
        console.error('Error in loadLibrary:', error);
        state.error = error;
        renderError();
    } finally {
        state.isLoading = false;
    }
}

// Функция отображения библиотеки
function renderLibrary() {
    const booksGrid = document.getElementById('books-grid');
    if (!booksGrid) return;

    if (!Array.isArray(state.books) || state.books.length === 0) {
        renderEmptyState(booksGrid);
    } else {
        renderBooks(booksGrid);
    }
}

// Функция отображения пустого состояния
function renderEmptyState(container) {
    container.innerHTML = `
        <div class="empty-state">
            <div class="empty-illustration">
                <svg width="120" height="120" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
                </svg>
            </div>
            <h2>Ваша библиотека пуста</h2>
            <p>Добавьте свою первую книгу, чтобы начать увлекательное путешествие в мир чтения</p>
            <button class="upload-cta-btn" id="uploadCtaBtn">
                <span class="icon">+</span>
                <span>Добавить книгу</span>
            </button>
        </div>
    `;

    //сделать колонку books grid стиль равно grid-template-columns 1fr
    if (container) {
        container.style.gridTemplateColumns = '1fr';
    }

    // Добавляем обработчик для кнопки загрузки
    const uploadBtn = container.querySelector('#uploadCtaBtn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', () => {
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) uploadOverlay.style.display = 'flex';
        });
    }
}

// Функция отображения книг
function renderBooks(container) {
    // Анимация появления книг
    const booksHTML = state.books.map(book => {
        const progress = book.progress || 0;
        const rotation = progress * 3.6;
        const coverUrl = book.cover_url || '/static/default-cover.png';
        const title = book.title || book.filename || 'Без названия';
        const uploadDate = new Date(book.upload_date).toLocaleDateString('ru-RU', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
        
        return `
        <div class="book-card" data-book-id="${book.id}">
            <div class="book-cover-wrapper">
                <img class="book-cover" 
                     src="${coverUrl}" 
                     alt="${title}"
                     onerror="this.src='/static/default-cover.png'">
                <div class="book-overlay">
                    <button class="read-btn" onclick="openBook('${book.id}')">Читать</button>
                    <div class="progress-circle">
                        <div class="circle-back"></div>
                        <div class="circle-progress">
                            <div class="circle-progress__right" style="transform: rotate(${progress <= 50 ? (180 - (progress / 50) * 180) : 0}deg)"></div>
                            <div class="circle-progress__left" style="transform: rotate(${progress <= 50 ? 180 : (180 - ((progress - 50) / 50) * 180)}deg)"></div>
                        </div>
                        <div class="circle-text">${progress}%</div>
                    </div>
                </div>
            </div>
            <div class="book-info">
                <h3 class="book-title">${title}</h3>
                <div class="book-meta">
                    ${book.author ? `<span class="book-author">${book.author}</span>` : ''}
                    <span class="upload-date">Загружено: ${new Date(book.upload_date).toLocaleDateString('ru-RU')}</span>
                </div>
            </div>
        </div>`;
    }).join('');
    
    container.innerHTML = booksHTML;

    // Добавляем обработчики событий для карточек книг
    const bookCards = container.querySelectorAll('.book-card');
    bookCards.forEach(card => {
        card.addEventListener('click', (e) => {
            // Игнорируем клик, если он был по кнопкам
            if (!e.target.closest('.action-btn')) {
                const bookId = card.dataset.bookId;
                openBook(bookId);
            }
        });
    });
}

// Функция отображения ошибки
function renderError() {
    const booksGrid = document.getElementById('books-grid');
    if (!booksGrid) return;

    booksGrid.innerHTML = `
        <div class="error-state">
            <p>Произошла ошибка при загрузке библиотеки</p>
            <button onclick="loadLibrary()">Повторить</button>
        </div>
    `;
}

function updateUploadProgress(percent, text = '') {
    const progressWrap = document.querySelector('.upload-progress');
    const progressFill = document.querySelector('.progress-fill');
    const progressText = document.querySelector('.progress-text');

    if (progressWrap) {
        progressWrap.style.display = 'block';
    }
    if (progressFill) {
        progressFill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
    }
    if (progressText) {
        progressText.textContent = text || `${percent}%`;
    }
}

function initializeUploadDropZone() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const uploadNowBtn = document.getElementById('uploadNowBtn');
    if (!dropZone || !fileInput || dropZone.dataset.initialized === 'true') return;
    dropZone.dataset.initialized = 'true';

    // Глобальный fallback на случай кэша/рассинхронизации обработчиков
    window.__bookverseOnFileChange = handleFileUpload;

    const preventDefaults = (event) => {
        event.preventDefault();
        event.stopPropagation();
    };

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, preventDefaults);
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.add('drag-over');
        });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.remove('drag-over');
        });
    });

    dropZone.addEventListener('drop', async (event) => {
        const file = event.dataTransfer?.files?.[0];
        if (!file) return;
        await uploadBookFile(file);
    });

    // Явная кнопка загрузки: работает даже если авто-upload не сработал
    if (uploadNowBtn) {
        uploadNowBtn.addEventListener('click', async () => {
            const selected = fileInput.files?.[0];
            if (!selected) {
                updateUploadProgress(0, 'Сначала выберите файл');
                return;
            }
            await uploadBookFile(selected);
        });
    }
}

async function uploadBookFile(file) {
    if (uploadInProgress) return;

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!['txt', 'fb2'].includes(ext)) {
        updateUploadProgress(0, 'Поддерживаются только файлы .txt и .fb2');
        return;
    }

    uploadInProgress = true;
    updateUploadProgress(10, `Подготовка: ${file.name}`);

    const formData = new FormData();
    formData.append('file', file);

    try {
        updateUploadProgress(40, 'Загрузка на сервер...');
        const response = await apiFetch('/upload', {
            method: 'POST',
            body: formData,
            headers: {
                'Authorization': `Bearer ${getAuthToken()}`
            }
        });

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.detail || 'Ошибка загрузки книги');
        }

        updateUploadProgress(100, '100% — книга загружена');
        await loadLibrary();

        const uploadOverlay = document.getElementById('upload-overlay');
        if (uploadOverlay) {
            uploadOverlay.style.display = 'none';
        }

        const fileInput = document.getElementById('file-input');
        if (fileInput) {
            fileInput.value = '';
        }
    } catch (error) {
        console.error('Upload error:', error);
        if (error instanceof TypeError) {
            updateUploadProgress(0, 'Нет подключения к backend (порт 8000)');
        } else {
            updateUploadProgress(0, error.message || 'Ошибка загрузки');
        }
    } finally {
        uploadInProgress = false;
    }
}

// Обработчик выбора файла
export async function handleFileUpload(e) {
    const file = e?.target?.files?.[0];
    if (!file) return;
    updateUploadProgress(5, `Файл выбран: ${file.name}`);
    await uploadBookFile(file);
}

// Функция парсинга FB2 файла
function parseFB2File(fb2Text) {
    const parser = new DOMParser();
    const xmlDoc = parser.parseFromString(fb2Text, 'application/xml');

    // Проверяем на наличие ошибок парсинга
    if (xmlDoc.getElementsByTagName('parsererror').length > 0) {
        alert('Ошибка при разборе FB2 файла. Проверьте корректность файла.');
        return '';
    }

    const body = xmlDoc.getElementsByTagName('body')[0];
    const sections = body.getElementsByTagName('section');

    let textContent = '';
    let wordCount = 0;
    chapters = [];

    for (let i = 0; i < sections.length; i++) {
        const section = sections[i];
        const titleElems = section.getElementsByTagName('title');
        let chapterTitle = '';
        if (titleElems.length > 0) {
            const pElems = titleElems[0].getElementsByTagName('p');
            if (pElems.length > 0) {
                chapterTitle = pElems[0].textContent.trim();
            }
        }

        const paragraphs = section.getElementsByTagName('p');
        let sectionText = '';
        for (let j = 0; j < paragraphs.length; j++) {
            sectionText += paragraphs[j].textContent + '\n\n';
        }

        // Сохраняем информацию о главе
        if (chapterTitle) {
            chapters.push({
                title: chapterTitle,
                wordIndex: wordCount
            });
        }

        const sectionWords = sectionText.trim().split(/\s+/);
        wordCount += sectionWords.length;
        textContent += sectionText;
    }

    return textContent.trim();
}

// Добавим экспорт функции
export function splitTextIntoPages(text) {
    const words = text.split(/\s+/);
    totalPages = Math.ceil(words.length / wordsPerPage);

    pages = [];
    let wordIndex = 0;
    for (let i = 0; i < totalPages; i++) {
        const pageWords = words.slice(wordIndex, wordIndex + wordsPerPage);
        pages.push(pageWords.join(' '));
        wordIndex += wordsPerPage;
    }

    // Обновляем номер страницы для глав
    chapters.forEach((chapter) => {
        chapter.page = Math.ceil(chapter.wordIndex / wordsPerPage) || 1;
    });

    document.getElementById('page-count').textContent = totalPages;
}

// Функция отображения страницы
export function displayPage(pageNum) {
    if (pageNum < 1 || pageNum > totalPages) return;
    currentPage = pageNum;
    const textLayer = document.getElementById('text-layer');
    if (textLayer) {
        textLayer.innerText = pages[pageNum - 1];
    }
    document.getElementById('page-input').value = pageNum;

    // Сохраняем текущую страницу в localStorage
    localStorage.setItem('currentPage', currentPage);

    // Обновляем хлебные крошки
    const currentChapter = getCurrentChapter();
    const breadcrumbChapter = document.getElementById('breadcrumb-chapter');
    const breadcrumbPage = document.getElementById('breadcrumb-page');
    
    if (breadcrumbChapter) {
        breadcrumbChapter.textContent = currentChapter ? `Глава: ${currentChapter.title}` : 'Глава: Не выбрано';
    }
    if (breadcrumbPage) {
        breadcrumbPage.textContent = `Страница: ${currentPage}`;
    }

    // Обновляем прогресс чтения
    updateReadingProgress();
}

// Функция получения текущей главы
function getCurrentChapter() {
    let currentChapter = null;
    for (let i = 0; i < chapters.length; i++) {
        if (currentPage >= chapters[i].page) {
            currentChapter = chapters[i];
        } else {
            break;
        }
    }
    return currentChapter;
}

// Обработчик изменения номера страницы
const pageInput = document.getElementById('page-input');
if (pageInput) {
    pageInput.addEventListener('change', function() {
        const pageNum = parseInt(this.value, 10);
        if (pageNum >= 1 && pageNum <= totalPages) {
            displayPage(pageNum);
        } else {
            alert(`Введите номер страницы от 1 до ${totalPages}`);
            this.value = currentPage;
        }
    });
}

// Навигационные кнопки
const prevPageBtn = document.getElementById('prev-page');
if (prevPageBtn) {
    prevPageBtn.addEventListener('click', function () {
        if (currentPage > 1) {
            displayPage(currentPage - 1);
        }
    });
}

const nextPageBtn = document.getElementById('next-page');
if (nextPageBtn) {
    nextPageBtn.addEventListener('click', function () {
        if (currentPage < totalPages) {
            displayPage(currentPage + 1);
        }
    });
}

// Функция для переключения списка глав
function toggleChapters() {
    const chaptersPanel = document.getElementById('chapters-panel');
    chaptersPanel.classList.toggle('active');
    localStorage.setItem('chaptersPanelState', chaptersPanel.classList.contains('active'));
}

// Переключение списка глав (если элемент существует)
const toggleChaptersBtn = document.getElementById('toggle-chapters');
if (toggleChaptersBtn) {
    toggleChaptersBtn.addEventListener('click', toggleChapters);
}

// Функция создания списка глав
export function createChapterList() {
    const chaptersListDiv = document.getElementById('chapters-list');
    if (!chaptersListDiv) return;

    chaptersListDiv.innerHTML = '';

    if (chapters.length === 0) {
        chaptersListDiv.innerHTML = '<p class="no-chapters">Главы не найдены</p>';
        return;
    }

    const ul = document.createElement('ul');
    ul.className = 'chapters-list-items';

    chapters.forEach((chapter, index) => {
        const li = document.createElement('li');
        const button = document.createElement('button');
        button.className = 'chapter-button';
        button.innerHTML = `
            <span class="chapter-number">${index + 1}</span>
            <span class="chapter-title">${chapter.title}</span>
        `;
        
        button.addEventListener('click', () => {
            displayPage(chapter.page);
            const chaptersPanel = document.getElementById('chapters-panel');
            if (chaptersPanel) {
                chaptersPanel.classList.remove('active');
            }
        });

        li.appendChild(button);
        ul.appendChild(li);
    });

    chaptersListDiv.appendChild(ul);
}

// Функция обновления прогресса чтения
function updateReadingProgress() {
    const percentage = Math.round((currentPage / totalPages) * 100);
    const percentageElement = document.getElementById('progress-percentage');
    if (percentageElement) {
        percentageElement.textContent = `${percentage}%`;
    }
}

function renderChapterList() {
    const chaptersListDiv = document.getElementById('chapters-list');
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

function toggleUpload() {
    const modal = document.getElementById('upload-overlay');
    if (modal) {
        modal.style.display = modal.style.display === 'flex' ? 'none' : 'flex';
    }
}

// Обновляем функцию openBook
async function openBook(bookId) {
    try {
        // Сохраняем ID текущей книги
        localStorage.setItem('currentBookId', bookId);
        // Переходим на страницу чтения
        window.location.href = `reader.html?id=${bookId}`;
    } catch (error) {
        console.error('Error opening book:', error);
        alert('Ошибка при открытии книги');
    }
}

// Функция удаления книги
async function deleteBook(bookId) {
    if (!confirm('Вы уверены, что хотите удалить эту книгу?')) {
        return;
    }

    try {
        const response = await apiFetch(`/books/${bookId}`, {
            method: 'DELETE',
            headers: {
                'Authorization': `Bearer ${getAuthToken()}`
            }
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Ошибка при удалении книги');
        }

        // Обновляем библиотеку после успешного удаления
        await loadLibrary();
        
    } catch (error) {
        console.error('Error deleting book:', error);
        alert('Ошибка при удалении книги: ' + error.message);
    }
}

// Делаем функции доступными глобально
window.openBook = openBook;
window.deleteBook = deleteBook;

// После всех определений функций
document.addEventListener('DOMContentLoaded', () => {
    console.log('=== DOMContentLoaded ===');
    console.log('Текущий путь:', window.location.pathname);
    console.log('Проверка наличия элементов:', {
        booksGrid: !!document.getElementById('books-grid'),
        emptyState: !!document.getElementById('empty-state'),
        loading: !!document.getElementById('loading'),
        errorMessage: !!document.getElementById('error-message')
    });
    
    // Загружаем библиотеку если есть элемент books-grid
    const booksGrid = document.getElementById('books-grid');
    if (booksGrid) {
        console.log('Найден элемент books-grid, загружаем библиотеку...');
        loadLibrary();
    } else {
        console.log('Элемент books-grid не найден, возможно это страница чтения');
    }
});

// Добавляем функцию logout, чтобы при клике на кнопку «Выйти» очищался токен и происходил переход на страницу входа.
function logout() {
    localStorage.clear();
    // Если нужно удалить и другие данные о пользователе, например:
    // localStorage.removeItem('currentBookId');
    // localStorage.removeItem('currentBookTitle');
    window.location.href = 'index.html';
}
window.logout = logout;

document.addEventListener('DOMContentLoaded', () => {
    const uploadButton = document.getElementById('uploadButton');
    if (uploadButton) {
        uploadButton.addEventListener('click', () => {
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) uploadOverlay.style.display = 'flex';
        });
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const closeModalBtn = document.getElementById('closeModalBtn');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) uploadOverlay.style.display = 'none';
        });
    }
});

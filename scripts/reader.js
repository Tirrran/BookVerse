import { getBookById, updateBookProgress } from './localBooks.js';

let bookText = '';
let totalPages = 0;
let currentPage = 1;
let pages = [];
let chapters = [];

const wordsPerPage = 500;
const chapterHeadingRegex = /^(?:\s*)(?:глава|chapter)\s+([^\n]+)$/gim;

function splitIntoPages(text) {
    const words = (text || '').split(/\s+/).filter(Boolean);
    const result = [];
    for (let i = 0; i < words.length; i += wordsPerPage) {
        result.push(words.slice(i, i + wordsPerPage).join(' '));
    }
    return result.length ? result : [''];
}

function detectChapters(text) {
    const found = [];
    for (const match of text.matchAll(chapterHeadingRegex)) {
        found.push({
            title: match[0].trim(),
            start: match.index || 0,
        });
    }
    if (!found.length) return [];

    const wordOffsets = [];
    let total = 0;
    for (const chunk of text.split(/\s+/)) {
        total += 1;
        wordOffsets.push(total);
    }

    return found.map((chapter, idx) => {
        const prefix = text.slice(0, chapter.start);
        const wordIndex = prefix.split(/\s+/).filter(Boolean).length;
        return {
            title: chapter.title,
            page: Math.max(1, Math.ceil(wordIndex / wordsPerPage)),
            index: idx + 1,
        };
    });
}

function updatePageCount() {
    const pageCount = document.getElementById('page-count');
    if (pageCount) pageCount.textContent = String(totalPages);
}

function getCurrentChapter() {
    let active = null;
    for (const chapter of chapters) {
        if (currentPage >= chapter.page) active = chapter;
    }
    return active;
}

function updateBreadcrumbs() {
    const breadcrumbChapter = document.getElementById('breadcrumb-chapter');
    const breadcrumbPage = document.getElementById('breadcrumb-page');
    const chapter = getCurrentChapter();

    if (breadcrumbChapter) {
        breadcrumbChapter.textContent = chapter
            ? `Глава: ${chapter.title}`
            : 'Глава: Не выбрано';
    }
    if (breadcrumbPage) {
        breadcrumbPage.textContent = `Страница: ${currentPage}`;
    }
}

function updateReadingProgress() {
    const percentage = Math.round((currentPage / Math.max(1, totalPages)) * 100);
    const node = document.getElementById('progress-percentage');
    if (node) node.textContent = `${percentage}%`;

    const bookId = new URLSearchParams(window.location.search).get('id');
    if (bookId) {
        localStorage.setItem(`book_${bookId}_page`, String(currentPage));
        updateBookProgress(bookId, percentage);
    }
}

function displayPage(pageNum) {
    if (!Number.isFinite(pageNum) || pageNum < 1 || pageNum > pages.length) return;
    currentPage = pageNum;

    const textLayer = document.getElementById('text-layer');
    if (textLayer) {
        textLayer.innerHTML = `<div class="page-content">${pages[pageNum - 1]}</div>`;
    }

    const pageInput = document.getElementById('page-input');
    if (pageInput) pageInput.value = String(pageNum);

    updateBreadcrumbs();
    updateReadingProgress();
}

function createChapterList() {
    const listNode = document.getElementById('chapters-list');
    if (!listNode) return;

    if (!chapters.length) {
        listNode.innerHTML = '<p class="no-chapters">Главы не найдены</p>';
        return;
    }

    const html = chapters
        .map((chapter) => (
            `<button class="chapter-button" data-chapter-page="${chapter.page}" style="width:100%;text-align:left;margin:4px 0;padding:8px;border-radius:8px;border:1px solid #2d3748;background:transparent;color:inherit;cursor:pointer;">
                ${chapter.index}. ${chapter.title}
            </button>`
        ))
        .join('');

    listNode.innerHTML = html;
    listNode.querySelectorAll('[data-chapter-page]').forEach((button) => {
        button.addEventListener('click', () => {
            const page = Number(button.dataset.chapterPage);
            displayPage(page);
            const panel = document.getElementById('chapters-panel');
            if (panel) panel.classList.remove('active');
        });
    });
}

function initializeNavigation() {
    const prevBtn = document.getElementById('prev-page');
    const nextBtn = document.getElementById('next-page');
    const pageInput = document.getElementById('page-input');

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            if (currentPage > 1) displayPage(currentPage - 1);
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            if (currentPage < totalPages) displayPage(currentPage + 1);
        });
    }

    if (pageInput) {
        pageInput.addEventListener('change', () => {
            const value = Number(pageInput.value);
            if (value >= 1 && value <= totalPages) displayPage(value);
            else pageInput.value = String(currentPage);
        });
    }
}

function initializePanels() {
    const toggleChaptersBtn = document.getElementById('toggle-chapters');
    const closeChaptersBtn = document.getElementById('close-chapters');
    const chaptersPanel = document.getElementById('chapters-panel');
    const menuButton = document.getElementById('menuButton');
    const sidePanel = document.getElementById('right-panel');

    if (toggleChaptersBtn && chaptersPanel) {
        toggleChaptersBtn.addEventListener('click', (event) => {
            event.stopPropagation();
            chaptersPanel.classList.toggle('active');
            sidePanel?.classList.remove('visible');
        });
    }

    if (closeChaptersBtn && chaptersPanel) {
        closeChaptersBtn.addEventListener('click', () => chaptersPanel.classList.remove('active'));
    }

    if (menuButton && sidePanel) {
        menuButton.addEventListener('click', (event) => {
            event.stopPropagation();
            sidePanel.classList.toggle('visible');
            chaptersPanel?.classList.remove('active');
            if (typeof window.showMenu === 'function') window.showMenu();
        });
    }

    document.addEventListener('click', (event) => {
        if (!chaptersPanel?.contains(event.target) && !toggleChaptersBtn?.contains(event.target)) {
            chaptersPanel?.classList.remove('active');
        }
        if (!sidePanel?.contains(event.target) && !menuButton?.contains(event.target)) {
            sidePanel?.classList.remove('visible');
        }
    });
}

function renderLoadError(message) {
    const layer = document.getElementById('text-layer');
    if (!layer) return;
    layer.innerHTML = `<div class="error-message">${message}</div>`;
}

function loadBook() {
    const params = new URLSearchParams(window.location.search);
    const bookId = params.get('id') || localStorage.getItem('currentBookId');
    if (!bookId) {
        renderLoadError('Книга не выбрана. Вернитесь в библиотеку и откройте книгу.');
        return;
    }

    const book = getBookById(bookId);
    if (!book) {
        renderLoadError('Книга не найдена в локальной библиотеке.');
        return;
    }

    bookText = book.content || '';
    if (!bookText.trim()) {
        renderLoadError('У книги отсутствует текст.');
        return;
    }

    pages = splitIntoPages(bookText);
    totalPages = pages.length;
    chapters = detectChapters(bookText);

    updatePageCount();
    createChapterList();

    const saved = Number(localStorage.getItem(`book_${bookId}_page`));
    currentPage = Number.isFinite(saved) && saved >= 1 ? Math.min(saved, totalPages) : 1;
    displayPage(currentPage);
}

document.addEventListener('DOMContentLoaded', () => {
    loadBook();
    initializeNavigation();
    initializePanels();
});

export {
    displayPage,
    loadBook,
};

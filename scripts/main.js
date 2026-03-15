import { addBookFromFile, deleteBookById, getBookMetas } from './localBooks.js';

let state = {
    books: [],
    isLoading: false,
    error: null,
};

let uploadInProgress = false;

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
            <p>Добавьте первую книгу в локальную библиотеку</p>
            <button class="upload-cta-btn" id="uploadCtaBtn">
                <span class="icon">+</span>
                <span>Добавить книгу</span>
            </button>
        </div>
    `;

    container.style.gridTemplateColumns = '1fr';
    const uploadBtn = container.querySelector('#uploadCtaBtn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', () => {
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) uploadOverlay.style.display = 'flex';
        });
    }
}

function renderBooks(container) {
    const booksHTML = state.books
        .map((book) => {
            const progress = book.progress || 0;
            const title = book.title || book.filename || 'Без названия';
            const date = new Date(book.upload_date).toLocaleDateString('ru-RU');

            return `
                <div class="book-card" data-book-id="${book.id}">
                    <div class="book-cover-wrapper">
                        <div class="book-cover" style="display:flex;align-items:center;justify-content:center;font-size:42px;">📘</div>
                        <div class="book-overlay">
                            <button class="read-btn" onclick="openBook('${book.id}')">Читать</button>
                            <div class="progress-circle">
                                <div class="circle-back"></div>
                                <div class="circle-text">${progress}%</div>
                            </div>
                        </div>
                    </div>
                    <div class="book-info">
                        <h3 class="book-title">${title}</h3>
                        <div class="book-meta">
                            <span class="upload-date">Загружено: ${date}</span>
                        </div>
                        <div style="margin-top:8px;display:flex;gap:8px;">
                            <button class="nav-btn" onclick="openBook('${book.id}')">Открыть</button>
                            <button class="nav-btn" onclick="deleteBook('${book.id}')">Удалить</button>
                        </div>
                    </div>
                </div>
            `;
        })
        .join('');

    container.style.gridTemplateColumns = '';
    container.innerHTML = booksHTML;

    const bookCards = container.querySelectorAll('.book-card');
    bookCards.forEach((card) => {
        card.addEventListener('click', (event) => {
            if (event.target.closest('button')) return;
            const bookId = card.dataset.bookId;
            openBook(bookId);
        });
    });
}

function renderError() {
    const booksGrid = document.getElementById('books-grid');
    if (!booksGrid) return;

    booksGrid.innerHTML = `
        <div class="error-state">
            <p>Ошибка загрузки библиотеки</p>
            <button class="nav-btn" onclick="loadLibrary()">Повторить</button>
        </div>
    `;
}

function renderLibrary() {
    const booksGrid = document.getElementById('books-grid');
    if (!booksGrid) return;

    if (!Array.isArray(state.books) || state.books.length === 0) {
        renderEmptyState(booksGrid);
        return;
    }
    renderBooks(booksGrid);
}

export async function loadLibrary() {
    const booksGrid = document.getElementById('books-grid');
    if (!booksGrid) return;

    try {
        state.isLoading = true;
        state.error = null;
        state.books = getBookMetas();
        renderLibrary();
    } catch (error) {
        console.error('loadLibrary error:', error);
        state.error = error;
        renderError();
    } finally {
        state.isLoading = false;
    }
}

async function uploadBookFile(file) {
    if (!file || uploadInProgress) return;

    const ext = (file.name.split('.').pop() || '').toLowerCase();
    if (!['txt', 'fb2'].includes(ext)) {
        updateUploadProgress(0, 'Поддерживаются только .txt и .fb2');
        return;
    }

    uploadInProgress = true;
    updateUploadProgress(10, `Подготовка: ${file.name}`);

    try {
        updateUploadProgress(45, 'Чтение файла...');
        await addBookFromFile(file);
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
        updateUploadProgress(0, error.message || 'Ошибка загрузки');
    } finally {
        uploadInProgress = false;
    }
}

export async function handleFileUpload(event) {
    const file = event?.target?.files?.[0];
    if (!file) return;
    updateUploadProgress(5, `Файл выбран: ${file.name}`);
    await uploadBookFile(file);
}

function initializeUploadDropZone() {
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const uploadNowBtn = document.getElementById('uploadNowBtn');
    if (!dropZone || !fileInput || dropZone.dataset.initialized === 'true') return;

    dropZone.dataset.initialized = 'true';
    window.__bookverseOnFileChange = handleFileUpload;

    const preventDefaults = (event) => {
        event.preventDefault();
        event.stopPropagation();
    };

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, preventDefaults);
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'));
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'));
    });

    dropZone.addEventListener('drop', async (event) => {
        const file = event.dataTransfer?.files?.[0];
        if (file) await uploadBookFile(file);
    });

    if (uploadNowBtn) {
        uploadNowBtn.addEventListener('click', async () => {
            const file = fileInput.files?.[0];
            if (!file) {
                updateUploadProgress(0, 'Сначала выберите файл');
                return;
            }
            await uploadBookFile(file);
        });
    }
}

async function deleteBook(bookId) {
    if (!confirm('Удалить книгу из локальной библиотеки?')) return;
    deleteBookById(bookId);
    await loadLibrary();
}

function openBook(bookId) {
    localStorage.setItem('currentBookId', String(bookId));
    window.location.href = `reader.html?id=${bookId}`;
}

function logout() {
    // Сбрасываем только пользовательские настройки/сессию, книги оставляем.
    localStorage.removeItem('authToken');
    localStorage.removeItem('username');
    localStorage.removeItem('userEmail');
    window.location.href = 'index.html';
}

window.openBook = openBook;
window.deleteBook = deleteBook;
window.logout = logout;

function bindStaticUiHandlers() {
    const uploadButton = document.getElementById('uploadButton');
    if (uploadButton) {
        uploadButton.addEventListener('click', () => {
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) uploadOverlay.style.display = 'flex';
        });
    }

    const closeModalBtn = document.getElementById('closeModalBtn');
    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) uploadOverlay.style.display = 'none';
        });
    }

    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', handleFileUpload);
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    initializeUploadDropZone();
    bindStaticUiHandlers();

    if (document.getElementById('books-grid')) {
        await loadLibrary();
    }
});

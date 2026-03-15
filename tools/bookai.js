import { askBooksLocal, searchBooksLocal } from '../scripts/localBooks.js';

function setStatus(target, text, isError = false) {
    if (!target) return;
    target.textContent = text || '';
    target.classList.toggle('error', Boolean(isError));
}

function getScopeBookIds(root) {
    const scope = root.querySelector('input[name="search-scope"]:checked')?.value;
    if (scope === 'all') return [];

    const currentBookId = localStorage.getItem('currentBookId');
    if (!currentBookId) {
        return null;
    }
    return [String(currentBookId)];
}

function renderFragments(target, fragments) {
    if (!target) return;
    target.innerHTML = '';

    fragments.forEach((item) => {
        const card = document.createElement('div');
        card.className = 'result-item';

        const chapterMeta = item.location?.chapter ? `глава ${item.location.chapter}` : '';
        const locationMeta = item.location?.line_start
            ? `строки ${item.location.line_start}-${item.location.line_end}`
            : '';
        const scoreMeta = Number.isFinite(item.score) ? `score: ${item.score}` : '';
        const meta = [item.book_title, chapterMeta, locationMeta, scoreMeta].filter(Boolean).join(' | ');

        card.innerHTML = `
            <div class="result-meta">${meta}</div>
            <div class="result-text">${item.fragment}</div>
        `;
        target.appendChild(card);
    });
}

function bindSearchEvents(root) {
    const searchQueryInput = root.querySelector('#search-query');
    const searchButton = root.querySelector('#search-button');
    const searchStatus = root.querySelector('#search-status');
    const searchResults = root.querySelector('#search-results');

    if (!searchButton || !searchQueryInput) return;
    if (searchButton.dataset.bound === 'true') return;
    searchButton.dataset.bound = 'true';

    searchButton.addEventListener('click', () => {
        const query = searchQueryInput.value.trim();
        if (!query) {
            setStatus(searchStatus, 'Введите запрос для поиска', true);
            return;
        }

        const bookIds = getScopeBookIds(root);
        if (bookIds === null) {
            setStatus(searchStatus, 'Откройте книгу или выберите поиск по всем книгам', true);
            return;
        }

        if (searchResults) searchResults.innerHTML = '';
        setStatus(searchStatus, 'Ищу фрагменты...');

        const data = searchBooksLocal(query, {
            top_k: 5,
            book_ids: bookIds,
        });

        if (!data.found) {
            setStatus(searchStatus, data.message || 'Ничего не найдено');
            return;
        }

        setStatus(searchStatus, `Найдено фрагментов: ${data.fragments.length}`);
        renderFragments(searchResults, data.fragments);
    });

    searchQueryInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            searchButton.click();
        }
    });
}

function bindAskEvents(root) {
    const questionInput = root.querySelector('#question-input');
    const askButton = root.querySelector('#ask-button');
    const answerStatus = root.querySelector('#answer-status');
    const answerBox = root.querySelector('#answer-box');
    const citationsList = root.querySelector('#citations-list');

    if (!askButton || !questionInput) return;
    if (askButton.dataset.bound === 'true') return;
    askButton.dataset.bound = 'true';

    askButton.addEventListener('click', () => {
        const question = questionInput.value.trim();
        if (!question) {
            setStatus(answerStatus, 'Введите вопрос', true);
            return;
        }

        const bookIds = getScopeBookIds(root);
        if (bookIds === null) {
            setStatus(answerStatus, 'Откройте книгу или выберите поиск по всем книгам', true);
            return;
        }

        if (answerBox) answerBox.textContent = '';
        if (citationsList) citationsList.innerHTML = '';
        setStatus(answerStatus, 'Формирую ответ...');

        const data = askBooksLocal(question, {
            top_k: 5,
            citations_k: 3,
            book_ids: bookIds,
        });

        if (answerBox) answerBox.textContent = data.answer || '';

        if (!data.found) {
            setStatus(answerStatus, data.answer || 'Ответ не найден в загруженных книгах');
            return;
        }

        setStatus(answerStatus, `Готово. Цитат: ${(data.citations || []).length}`);
        renderFragments(citationsList, data.citations || []);
    });

    questionInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
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

window.__initBookAiTool(document);

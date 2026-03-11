// scripts/contextMenu.js

// Функции для контекстных подсказок
const textLayer = document.getElementById('text-layer');
if (textLayer) {
    textLayer.addEventListener('mouseup', () => {
        const selectedText = window.getSelection().toString().trim();
        if (selectedText) {
            const range = window.getSelection().getRangeAt(0);
            const rect = range.getBoundingClientRect();
            showContextMenu(selectedText, rect);
        }
    });
}

function showContextMenu(text, rect) {
    const contextMenu = document.getElementById('context-menu');
    contextMenu.style.top = `${rect.bottom + window.scrollY}px`;
    contextMenu.style.left = `${rect.left + window.scrollX}px`;
    contextMenu.style.display = 'block';

    // Сохранение выделенного текста для дальнейших действий
    contextMenu.dataset.selectedText = text;
}

// Скрытие контекстного меню при клике вне его
document.addEventListener('click', (e) => {
    const contextMenu = document.getElementById('context-menu');
    if (contextMenu && !contextMenu.contains(e.target)) {
        contextMenu.style.display = 'none';
    }
});

// Функции для контекстного меню
function translateSelectedText() {
    const contextMenu = document.getElementById('context-menu');
    const text = contextMenu.dataset.selectedText;
    // Реализуйте перевод текста через API или другую логику
    alert(`Перевод текста: "${text}"`);
    contextMenu.style.display = 'none';
}

function searchSelectedText() {
    const contextMenu = document.getElementById('context-menu');
    const text = contextMenu.dataset.selectedText;
    // Реализуйте поиск текста
    alert(`Поиск текста: "${text}"`);
    contextMenu.style.display = 'none';
}

// Добавим проверку на существование элементов
document.addEventListener('DOMContentLoaded', () => {
    const contextMenu = document.getElementById('context-menu');
    if (!contextMenu) return; // Если элемент не существует, прекращаем выполнение

    // Остальной код...
});
// scripts/utils.js

// Функция применения сохранённых настроек
function applySavedSettings() {
    const savedFontFamily = localStorage.getItem('fontFamily') || 'Arial';
    const savedFontSize = localStorage.getItem('fontSize') || '16';

    const textLayer = document.getElementById('text-layer');
    if (textLayer) {
        textLayer.style.fontFamily = savedFontFamily;
        textLayer.style.fontSize = savedFontSize + 'px';
    }

    const theme = localStorage.getItem('theme') || 'white-theme';
    document.body.classList.remove('white-theme', 'black-theme');
    document.body.classList.add(theme);

    if (document.getElementById('theme-select')) {
        document.getElementById('theme-select').value = theme;
    }

    if (document.getElementById('font-select')) {
        document.getElementById('font-select').value = savedFontFamily;
    }

    if (document.getElementById('font-size')) {
        document.getElementById('font-size').value = savedFontSize;
    }

    // Применяем режим доступности
    const accessibilityMode = localStorage.getItem('accessibilityMode');
    const accessibilityToggle = document.getElementById('accessibility-toggle');
    if (accessibilityMode === 'enabled') {
        document.body.classList.add('accessibility-mode');
        if (accessibilityToggle) {
            accessibilityToggle.checked = true;
        }
    } else {
        document.body.classList.remove('accessibility-mode');
        if (accessibilityToggle) {
            accessibilityToggle.checked = false;
        }
    }

    // Применяем режим дальтонизма
    const colorblindMode = localStorage.getItem('colorblindMode');
    const colorblindToggle = document.getElementById('colorblind-toggle');
    if (colorblindMode === 'enabled') {
        document.body.classList.add('colorblind-mode');
        if (colorblindToggle) {
            colorblindToggle.checked = true;
        }
    } else {
        document.body.classList.remove('colorblind-mode');
        if (colorblindToggle) {
            colorblindToggle.checked = false;
        }
    }
}

export function toggleMenu() {
    const panel = document.getElementById('right-panel');
    if (panel) {
        console.log('Переключение меню'); // Для отладки
        panel.classList.toggle('visible');
        // Добавим класс для предотвращения прокрутки body
        document.body.classList.toggle('menu-open');
    }
}

export function toggleUpload() {
    const uploadForm = document.getElementById('upload-overlay');
    if (uploadForm) {
        uploadForm.style.display = uploadForm.style.display === 'none' ? 'flex' : 'none';
    }
}

// Добавляем обработчики для всех кнопок
document.addEventListener('DOMContentLoaded', () => {
    // Кнопки для загрузки
    const uploadButtons = ['uploadButton', 'uploadCtaBtn', 'closeModalBtn'];
    uploadButtons.forEach(id => {
        const button = document.getElementById(id);
        if (button) {
            button.addEventListener('click', toggleUpload);
        }
    });

    // Кнопки для меню
    const menuButtons = ['menuButton', 'closeBtn'];
    menuButtons.forEach(id => {
        const button = document.getElementById(id);
        if (button) {
            button.addEventListener('click', toggleMenu);
        }
    });
});

// Добавим обработчик закрытия меню при клике вне его
document.addEventListener('click', (e) => {
    const panel = document.getElementById('right-panel');
    const menuButton = document.getElementById('menuButton');
    
    if (panel && panel.classList.contains('visible')) {
        if (!panel.contains(e.target) && e.target !== menuButton) {
            panel.classList.remove('visible');
            document.body.classList.remove('menu-open');
        }
    }
});

// Глобальные привязки
window.toggleMenu = toggleMenu;
window.toggleUpload = toggleUpload;
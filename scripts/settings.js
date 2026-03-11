// scripts/settings.js

// Добавим обработчики изменений
document.addEventListener('input', function(e) {
    if (e.target.matches('#theme-select')) {
        changeTheme(e.target.value);
    }
    if (e.target.matches('#font-size')) {
        changeFontSize(e.target.value);
    }
});

// Функция изменения темы
function changeTheme(theme) {
    document.body.className = theme;
    localStorage.setItem('theme', theme);
}

// Функция обновления прогресса ползунка
function updateRangeProgress(input) {
    const min = input.min || 0;
    const max = input.max || 100;
    const value = input.value;
    const percentage = ((value - min) / (max - min)) * 100;
    input.style.background = `linear-gradient(to right, var(--settings-primary) 0%, var(--settings-primary) ${percentage}%, #e0e0e0 ${percentage}%, #e0e0e0 100%)`;
}

// Функция изменения размера шрифта
function changeFontSize(size) {
    document.documentElement.style.setProperty('--base-font-size', `${size}px`);
    localStorage.setItem('fontSize', size);
    document.querySelector('#font-size + .range-value').textContent = `${size}px`;
    updateRangeProgress(document.querySelector('#font-size'));
}

// Функция изменения шрифта
function changeFontFamily(font) {
    document.documentElement.style.setProperty('--font-family', font);
    localStorage.setItem('fontFamily', font);
}

// Функция изменения межстрочного интервала
function changeLineSpacing(spacing) {
    document.documentElement.style.setProperty('--line-spacing', spacing);
    localStorage.setItem('lineSpacing', spacing);
    document.querySelector('#line-spacing + .range-value').textContent = spacing;
    updateRangeProgress(document.querySelector('#line-spacing'));
}

// Функция изменения выравнивания текста
function changeTextAlign(align) {
    document.documentElement.style.setProperty('--text-align', align);
    localStorage.setItem('textAlign', align);
}

// Функция включения/выключения режима для слабовидящих
function toggleAccessibilityMode(enabled) {
    if (enabled) {
        document.documentElement.classList.add('accessibility-mode');
        localStorage.setItem('accessibilityMode', 'true');
    } else {
        document.documentElement.classList.remove('accessibility-mode');
        localStorage.setItem('accessibilityMode', 'false');
    }
}

// Функция включения/выключения режима для дальтоников
function toggleColorblindMode(enabled) {
    if (enabled) {
        document.documentElement.classList.add('colorblind-mode');
        localStorage.setItem('colorblindMode', 'true');
    } else {
        document.documentElement.classList.remove('colorblind-mode');
        localStorage.setItem('colorblindMode', 'false');
    }
}

// Инициализация настроек при загрузке
document.addEventListener('DOMContentLoaded', () => {
    // Инициализация прогресса для всех ползунков
    document.querySelectorAll('input[type="range"]').forEach(input => {
        updateRangeProgress(input);
        input.addEventListener('input', () => updateRangeProgress(input));
    });

    // Загружаем сохраненные настройки
    const savedTheme = localStorage.getItem('theme') || 'white-theme';
    const savedFontSize = localStorage.getItem('fontSize') || '16';
    const savedFontFamily = localStorage.getItem('fontFamily') || 'Roboto';
    const savedLineSpacing = localStorage.getItem('lineSpacing') || '1.5';
    const savedTextAlign = localStorage.getItem('textAlign') || 'left';
    const savedAccessibilityMode = localStorage.getItem('accessibilityMode') === 'true';
    const savedColorblindMode = localStorage.getItem('colorblindMode') === 'true';

    // Применяем настройки
    document.body.className = savedTheme;
    document.documentElement.style.setProperty('--base-font-size', `${savedFontSize}px`);
    document.documentElement.style.setProperty('--font-family', savedFontFamily);
    document.documentElement.style.setProperty('--line-spacing', savedLineSpacing);
    document.documentElement.style.setProperty('--text-align', savedTextAlign);

    if (savedAccessibilityMode) {
        document.documentElement.classList.add('accessibility-mode');
    }

    if (savedColorblindMode) {
        document.documentElement.classList.add('colorblind-mode');
    }

    // Устанавливаем значения в интерфейсе
    const themeSelect = document.getElementById('theme-select');
    const fontFamilySelect = document.getElementById('font-family');
    const fontSizeInput = document.getElementById('font-size');
    const lineSpacingInput = document.getElementById('line-spacing');
    const textAlignSelect = document.getElementById('text-align');
    const accessibilityModeToggle = document.getElementById('accessibility-mode');
    const colorblindModeToggle = document.getElementById('colorblind-mode');

    if (themeSelect) themeSelect.value = savedTheme;
    if (fontFamilySelect) fontFamilySelect.value = savedFontFamily;
    if (fontSizeInput) {
        fontSizeInput.value = savedFontSize;
        const fontSizeValue = fontSizeInput.nextElementSibling;
        if (fontSizeValue) fontSizeValue.textContent = `${savedFontSize}px`;
    }
    if (lineSpacingInput) {
        lineSpacingInput.value = savedLineSpacing;
        const lineSpacingValue = lineSpacingInput.nextElementSibling;
        if (lineSpacingValue) lineSpacingValue.textContent = savedLineSpacing;
    }
    if (textAlignSelect) textAlignSelect.value = savedTextAlign;
    if (accessibilityModeToggle) accessibilityModeToggle.checked = savedAccessibilityMode;
    if (colorblindModeToggle) colorblindModeToggle.checked = savedColorblindMode;
});

// Функция открытия настроек
function openSettings() {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    panelContent.innerHTML = `
        <div class="panel-header">
            <button class="back-btn" onclick="showMenu()">← Назад</button>
            <h2>Настройки</h2>
        </div>
        <div class="settings-content">
            <div class="settings-group">
                <h3>Внешний вид</h3>
                <div class="setting-item">
                    <label for="theme-select">Тема</label>
                    <select id="theme-select" onchange="changeTheme(this.value)">
                        <option value="white-theme">Светлая</option>
                        <option value="black-theme">Тёмная</option>
                        <option value="sepia-theme">Сепия</option>
                    </select>
                </div>
                <div class="setting-item">
                    <label for="font-family">Шрифт</label>
                    <select id="font-family" onchange="changeFontFamily(this.value)">
                        <option value="Roboto">Roboto</option>
                        <option value="OpenSans">Open Sans</option>
                        <option value="Merriweather">Merriweather</option>
                    </select>
                </div>
                <div class="setting-item">
                    <label for="font-size">Размер шрифта</label>
                    <div class="range-container">
                        <input type="range" id="font-size" min="12" max="24" 
                               value="${localStorage.getItem('fontSize') || '16'}"
                               oninput="changeFontSize(this.value)">
                        <span class="range-value">${localStorage.getItem('fontSize') || '16'}px</span>
                    </div>
                </div>
            </div>

            <div class="settings-group">
                <h3>Доступность</h3>
                <div class="setting-item">
                    <label for="accessibility-mode">Режим для слабовидящих</label>
                    <div class="toggle-switch">
                        <input type="checkbox" id="accessibility-mode" 
                               ${localStorage.getItem('accessibilityMode') === 'true' ? 'checked' : ''}
                               onchange="toggleAccessibilityMode(this.checked)">
                        <span class="toggle-slider"></span>
                    </div>
                </div>
                <div class="setting-item">
                    <label for="colorblind-mode">Режим для дальтоников</label>
                    <div class="toggle-switch">
                        <input type="checkbox" id="colorblind-mode" 
                               ${localStorage.getItem('colorblindMode') === 'true' ? 'checked' : ''}
                               onchange="toggleColorblindMode(this.checked)">
                        <span class="toggle-slider"></span>
                    </div>
                </div>
            </div>

            <div class="settings-group">
                <h3>Чтение</h3>
                <div class="setting-item">
                    <label for="line-spacing">Межстрочный интервал</label>
                    <div class="range-container">
                        <input type="range" id="line-spacing" min="1" max="2" step="0.1"
                               value="${localStorage.getItem('lineSpacing') || '1.5'}"
                               oninput="changeLineSpacing(this.value)">
                        <span class="range-value">${localStorage.getItem('lineSpacing') || '1.5'}</span>
                    </div>
                </div>
                <div class="setting-item">
                    <label for="text-align">Выравнивание текста</label>
                    <select id="text-align" onchange="changeTextAlign(this.value)">
                        <option value="left">По левому краю</option>
                        <option value="justify">По ширине</option>
                    </select>
                </div>
            </div>
        </div>
    `;

    // Устанавливаем текущие значения
    const currentTheme = localStorage.getItem('theme') || 'white-theme';
    document.getElementById('theme-select').value = currentTheme;
}

// Функция применения темы
function applyTheme() {
    const themeSelect = document.getElementById('theme-select');
    if (!themeSelect) return;

    const selectedTheme = themeSelect.value;
    const body = document.body;

    // Удаляем предыдущие темы
    body.classList.remove('white-theme', 'black-theme');

    // Применяем выбранную тему
    body.classList.add(selectedTheme);

    // Сохраняем в localStorage
    localStorage.setItem('theme', selectedTheme);
}

// Функция применения настроек шрифта
function applyFontSettings() {
    const fontSelect = document.getElementById('font-select');
    const fontSizeInput = document.getElementById('font-size');
    const textLayer = document.getElementById('text-layer');

    if (!fontSelect || !fontSizeInput || !textLayer) return;

    // Устанавливаем шрифт и размер
    textLayer.style.fontFamily = fontSelect.value;
    textLayer.style.fontSize = fontSizeInput.value + 'px';

    // Сохраняем настройки в localStorage
    localStorage.setItem('fontFamily', fontSelect.value);
    localStorage.setItem('fontSize', fontSizeInput.value);
}

// Функция применения режима для слабовидящих
function applyAccessibilitySettings() {
    const accessibilityToggle = document.getElementById('accessibility-toggle');
    const body = document.body;

    if (accessibilityToggle.checked) {
        body.classList.add('accessibility-mode');
        localStorage.setItem('accessibilityMode', 'enabled');
    } else {
        body.classList.remove('accessibility-mode');
        localStorage.setItem('accessibilityMode', 'disabled');
    }
}

// Функция применения режима для дальтоников
function applyColorblindSettings() {
    const colorblindToggle = document.getElementById('colorblind-toggle');
    const body = document.body;

    if (colorblindToggle.checked) {
        body.classList.add('colorblind-mode');
        localStorage.setItem('colorblindMode', 'enabled');
    } else {
        body.classList.remove('colorblind-mode');
        localStorage.setItem('colorblindMode', 'disabled');
    }
}

// Экспортируем функцию applySavedSettings
export function applySavedSettings() {
    const savedFontFamily = localStorage.getItem('fontFamily') || 'Arial';
    const savedFontSize = localStorage.getItem('fontSize') || '16';

    const textLayer = document.getElementById('text-layer');
    if (textLayer) {
        textLayer.style.fontFamily = savedFontFamily;
        textLayer.style.fontSize = savedFontSize + 'px';
    }

    const theme = localStorage.getItem('theme') || 'white-theme';
    document.body.className = theme;
    
    const fontSize = localStorage.getItem('fontSize') || '16px';
    document.documentElement.style.setProperty('--base-font-size', fontSize);
}

// Меняем старый экспорт
export function loadSettings() {
    // ... существующий код
}

// Делаем функции доступными глобально
window.changeFontSize = changeFontSize;
window.changeLineSpacing = changeLineSpacing;
window.changeTextAlign = changeTextAlign;
window.changeFontFamily = changeFontFamily;
window.toggleAccessibilityMode = toggleAccessibilityMode;
window.toggleColorblindMode = toggleColorblindMode;
window.loadSettings = loadSettings;
window.openSettings = openSettings;
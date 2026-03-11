// scripts/fontSettings.js

// Функция применения настроек шрифта
function applyFontSettings() {
    const fontSelect = document.getElementById('font-select');
    const fontSize = document.getElementById('font-size');
    const textLayer = document.getElementById('text-layer');

    if (!fontSelect || !fontSize || !textLayer) return;

    // Устанавливаем шрифт и размер
    textLayer.style.fontFamily = fontSelect.value;
    textLayer.style.fontSize = fontSize.value + 'px';

    // Сохраняем настройки в localStorage
    localStorage.setItem('fontFamily', fontSelect.value);
    localStorage.setItem('fontSize', fontSize.value);
}
// Дожидаемся загрузки DOM
document.addEventListener('DOMContentLoaded', function() {
    const summarizeButton = document.getElementById('summarize-button');
    const restoreButton = document.getElementById('restore-button');
    const summaryResult = document.getElementById('summary-result');
    let originalText = '';

    // Функция для отправки PDF на бэкенд
    async function uploadPDF(file, prompt, add_prompt) {
        const formData = new FormData();
        formData.append('file', file, 'book.txt');
        formData.append('prompt', prompt);
        formData.append('add_prompt', add_prompt);
        formData.append('type_generation', "summarize");

        const response = await fetch('http://localhost:8000/upload-pdf/', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`
            },
            body: formData
        });
        summaryResult.innerHTML = 'Текст успешно загружен и обрабатывается.';
        if (!response.ok) throw new Error('Ошибка при загрузке файла на сервер.');
        const data = await response.json();
        return data.id_class;
    }

    // Функция для получения ответа от бэкенда
    async function getSummaryResponse(id_class) {
        let done = false;
        let result = '';

        while (!done) {
            const response = await fetch(`http://localhost:8000/get-response/${id_class}`);
            if (!response.ok) throw new Error('Ошибка при получении ответа.');

            const data = await response.json();
            result = data.response;
            done = data.is_done; // Проверка статуса завершения
            // Обновляем текст с текущим результатом
            summaryResult.innerHTML = result;

            if (!done) {
                await new Promise(resolve => setTimeout(resolve, 100)); // Ожидание перед повторным запросом
            }
        }
        return result;
    }

    // Слушатель для кнопки суммаризации
    summarizeButton.addEventListener('click', async function() {
        const compressionLevel = document.getElementById('compression-level').value;
        const customPreferences = document.getElementById('custom-preferences').value;
        const bookText = localStorage.getItem('bookText') || '';

        if (!bookText) {
            alert('Откройте книгу в ридере перед использованием этого инструмента.');
            return;
        }

        const file = new Blob([bookText], { type: 'text/plain' });
        const prompt = `Уровень сжатия: ${compressionLevel}`;
        originalText = summaryResult.innerHTML;

        try {
            const id_class = await uploadPDF(file, prompt, customPreferences); // отправка TXT-файла
            const summary = await getSummaryResponse(id_class);

            summaryResult.innerHTML = summary; // Итоговое обновление результата
        } catch (error) {
            console.error('Ошибка:', error);
            summaryResult.innerHTML = 'Произошла ошибка при обработке запроса';
        }
    });

    // Слушатель для кнопки возврата к оригинальному тексту
    restoreButton.addEventListener('click', function() {
        summaryResult.innerHTML = originalText;
        restoreButton.style.display = 'none';
    });
});

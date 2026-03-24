async function generateVisualization() {
    const imagesPerPage = parseInt(document.getElementById('images-per-page').value, 10);
    const imagesDisplay = document.getElementById('images-display');
    const bookText = localStorage.getItem('bookText') || ''; // Текст книги из LocalStorage

    imagesDisplay.innerHTML = ''; // Очистить предыдущие изображения

    if (!bookText) {
        alert('Пожалуйста, загрузите книгу для генерации изображений.');
        return;
    }

    if (isNaN(imagesPerPage) || imagesPerPage < 1) {
        alert('Пожалуйста, введите корректное количество изображений.');
        return;
    }

    // Показать сообщение об ожидании
    const loadingMessage = document.createElement('p');
    loadingMessage.textContent = 'Генерация изображений, пожалуйста, подождите...';
    imagesDisplay.appendChild(loadingMessage);

    try {
        // Отправляем запросы на сервер для каждой картинки
        for (let i = 0; i < imagesPerPage; i++) {
            const response = await fetch(`http://localhost:8000/get-image?topic=${encodeURIComponent(bookText)}`);
            
            if (!response.ok) {
                throw new Error(`Ошибка сервера: ${response.statusText}`);
            }

            const blob = await response.blob();
            const imgUrl = URL.createObjectURL(blob);

            // Создаём контейнер для изображения и текста
            const imageContainer = document.createElement('div');
            imageContainer.style.display = 'inline-block';
            imageContainer.style.textAlign = 'center';
            imageContainer.style.margin = '10px';

            // Создаём элемент <img> для изображения
            const img = document.createElement('img');
            img.src = imgUrl;
            img.alt = `Image ${i + 1}`;
            img.style.margin = '10px';
            img.style.borderRadius = '5px';
            img.style.width = '150px'; // Пример размера изображения
            img.style.height = '150px';

            // Создаём подпись для изображения с ID
            const idText = document.createElement('p');
            const generatedId = `ID-${Math.random().toString(36).substr(2, 9)}`; // Генерация уникального ID
            idText.textContent = `Изображение ${i + 1}: ${generatedId}`;
            idText.style.color = '#333';
            idText.style.fontSize = '0.9em';

            // Добавляем изображение и подпись в контейнер
            imageContainer.appendChild(img);
            imageContainer.appendChild(idText);

            // Добавляем контейнер в display
            imagesDisplay.appendChild(imageContainer);
        }
    } catch (error) {
        console.error('Ошибка:', error);
        alert('Произошла ошибка при генерации изображений.');
    } finally {
        // Удаляем сообщение об ожидании
        imagesDisplay.removeChild(loadingMessage);
    }
}

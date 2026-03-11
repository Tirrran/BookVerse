(async function() {
    const generateButton = document.getElementById('generate-button');
    const quizResult = document.getElementById('quiz-result');
    const clearButton = document.getElementById('clear-button');

    // Функция для отправки текста книги на сервер
    async function uploadBookText(bookText, difficulty, questionCount, customInput) {
        const formData = new FormData();
        const blob = new Blob([bookText], { type: 'text/plain' }); // Создаём текстовый файл из строки

        formData.append('file', blob, 'book.txt'); // Отправляем как текстовый файл
        formData.append('prompt', difficulty + ' ' + questionCount);
        formData.append('add_prompt', customInput);
        formData.append('type_generation', 'quiz');

        const response = await fetch('http://localhost:8000/upload-pdf/', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('authToken') || ''}`
            },
            body: formData
        });

        if (!response.ok) {
            throw new Error('Ошибка при отправке текста книги на сервер.');
        }

        const data = await response.json();
        return data.id_class;
    }

    // Функция для получения сгенерированной викторины
    async function getQuizResponse(id_class) {
        let done = false;
        let result = '';

        while (!done) {
            const response = await fetch(`http://localhost:8000/get-response/${id_class}`);
            if (!response.ok) {
                throw new Error('Ошибка при получении ответа.');
            }

            const data = await response.json();
            result = data.response;
            done = data.is_done;

            // Показываем промежуточный результат, если есть
            quizResult.innerHTML = result || 'Генерация викторины, пожалуйста, подождите...';

            if (!done) {
                await new Promise(resolve => setTimeout(resolve, 500)); // Ожидание перед повторным запросом
            }
        }
        return result;
    }

    // Слушатель для кнопки генерации викторины
    generateButton.addEventListener('click', async function() {
        const bookText = localStorage.getItem('bookText') || '';
        const difficulty = document.getElementById('difficulty').value;
        const questionCount = parseInt(document.getElementById('question-count').value);
        const customInput = document.getElementById('custom-input').value;

        if (!bookText) {
            alert('Пожалуйста, загрузите текст книги.');
            return;
        }

        quizResult.innerHTML = 'Генерация викторины, пожалуйста, подождите...';

        try {
            const id_class = await uploadBookText(bookText, difficulty, questionCount, customInput);
            const quiz = await getQuizResponse(id_class);

            quizResult.innerHTML = quiz;
            clearButton.style.display = 'inline-block';
        } catch (error) {
            console.error('Ошибка:', error);
            quizResult.innerHTML = 'Произошла ошибка при генерации викторины.';
        }
    });

    // Слушатель для кнопки очистки результата
    clearButton.addEventListener('click', function() {
        quizResult.innerHTML = 'Тут будут отображаться вопросы и ответы';
        //clearButton.style.display = 'none';
    });
})();

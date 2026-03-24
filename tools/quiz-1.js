(async function() {
    const generateButton = document.getElementById('generate-button');
    const quizResult = document.getElementById('quiz-result');
    const clearButton = document.getElementById('clear-button');

    // Функция для преобразования текста в PDF и отправки его на сервер
    async function uploadPDF(bookText, difficulty, questionCount, customInput) {
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF();
    
        // Разбиваем текст на строки по 80 символов
        const lines = bookText.match(/.{1,80}/g) || [];
    
        // Добавляем строки в PDF
        let yPosition = 10; // начальная позиция по вертикали
        lines.forEach(line => {
            if (yPosition > 280) { // если текст выходит за пределы страницы
                pdf.addPage();
                yPosition = 10;
            }
            pdf.text(line, 10, yPosition);
            yPosition += 10; // увеличиваем позицию для следующей строки
        });
    
        const pdfBlob = pdf.output('blob');
    
        const formData = new FormData();
        formData.append('file', pdfBlob, 'book.pdf');
        formData.append('prompt', difficulty + ' ' + questionCount);
        formData.append('add_prompt', customInput);
        formData.append('type_generation', 'quiz');
    
        const response = await fetch('http://localhost:8000/upload-pdf/', {
            method: 'POST',
            body: formData
        });
    
        if (!response.ok) {
            throw new Error('Ошибка при отправке PDF на сервер.');
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
            const id_class = await uploadPDF(bookText, difficulty, questionCount, customInput);
            const quiz = await getQuizResponse(id_class);

            quizResult.innerHTML = quiz;
            //clearButton.style.display = 'inline-block';
        } catch (error) {
            console.error('Ошибка:', error);
            quizResult.innerHTML = 'Произошла ошибка при генерации викторины.';
        }
    });

    // Слушатель для кнопки очистки результата
    clearButton.addEventListener('click', function() {
        quizResult.innerHTML = 'Тут будут отображаться вопросы и ответы';
        clearButton.style.display = 'none';
    });
})();


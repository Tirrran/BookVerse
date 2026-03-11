function startNarration() {
    const narrationStatus = document.getElementById('narration-status');
    const audioPlayer = document.getElementById('audio-player');
    const audioElement = document.getElementById('audio-element');
    const audioSource = document.getElementById('audio-source');
    const audioDuration = document.getElementById('audio-duration');
    const downloadAudio = document.getElementById('download-audio');

    narrationStatus.textContent = 'Озвучивание... Пожалуйста, подождите.';
    audioPlayer.style.display = 'none';

    // Запрос на сервер для получения аудиофайла
    setTimeout(async () => {
        try {
            const response = await fetch('http://localhost:8000/get-audio');
            if (!response.ok) {
                throw new Error(`Ошибка сервера: ${response.statusText}`);
            }

            const blob = await response.blob();
            const audioURL = URL.createObjectURL(blob);

            // Устанавливаем аудиофайл в плеер
            audioSource.src = audioURL;
            audioElement.load();

            // Получаем длительность аудио
            audioElement.addEventListener('loadedmetadata', () => {
                const duration = audioElement.duration;
                const minutes = Math.floor(duration / 60);
                const seconds = Math.floor(duration % 60).toString().padStart(2, '0');
                audioDuration.textContent = `${minutes}:${seconds}`;
            });

            downloadAudio.href = audioURL;

            narrationStatus.textContent = 'Озвучивание завершено.';
            audioPlayer.style.display = 'block';
        } catch (error) {
            console.error('Ошибка:', error);
            narrationStatus.textContent = 'Произошла ошибка при загрузке аудио.';
        }
    }, 5000); // Задержка 5 секунд для симуляции обработки
}
"""import requests
import json

# Идентификатор сессии, который будет получен после первого запроса
session_id = 20241104205126

# Функция для загрузки данных на сервер
def upload_data(file_path):
    global session_id
    url = 'https://sirius-ai.ru/process'  # URL сервера для загрузки данных

    with open(file_path, 'rb') as file:
        form_data = {'file': file}
        try:
            response = requests.post(url, files=form_data)
            response.raise_for_status()  # Проверяем наличие ошибок
            result = response.json()
            print(result)
            session_id = result.get('session_id')
            print("Data uploaded successfully. Session ID:", session_id)
        except requests.RequestException as error:
            print("Error during upload:", error)
            print("Произошла ошибка при загрузке данных.")

# Функция для отправки запроса на суммаризацию
def summarize_data(compression_percentage):


    url = 'https://sirius-ai.ru/question'#/summarize'  # URL сервера для суммаризации
    form_data = {
        'session_id': "20241104210242",
        'question': int(1)
    }

    try:
        response = requests.post(url, data=form_data)
        response.raise_for_status()  # Проверяем наличие ошибок
        result = response.json()
        #print(result)
        print("Summary result:", result['result'])
        #load_articles_data(result['topics'], result['articles'])
    except requests.RequestException as error:
        print("Error during summarization:", error)

# Дополнительная функция для загрузки данных о статьях и темах (для примера)
def load_articles_data(topics, articles):
    print("Topics:", topics)
    print("Articles:", articles)

# Пример использования:
file_path = '/Users/stepan/Downloads/Telegram Desktop/BookVerse (3)/dsd.txt'  # Укажите путь к файлу
upload_data(file_path)

compression_percentage = 100900000000  # Процент сжатия
summarize_data(compression_percentage)
"""


from diffusers import AutoPipelineForText2Image
import torch
import gc

# Загружаем модель с использованием FP16 (поддержка MPS)
pipe = AutoPipelineForText2Image.from_pretrained(
    "stabilityai/sdxl-turbo",
    torch_dtype=torch.float16,  # Использование FP16 для экономии памяти
    variant="fp16"             # Поддержка половинной точности
)

# Переносим модель на устройство MPS
pipe.to("mps")

# Функция генерации изображения с оптимизацией
def generate_image(prompt, height=512, width=512, steps=10, guidance=7.5, output_path="img.png"):
    # Очистка памяти перед началом
    gc.collect()
    torch.mps.empty_cache()

    # Генерация изображения
    image = pipe(
        prompt,
        height=height,           # Оптимальное разрешение для MPS
        width=width,
        num_inference_steps=steps,  # Количество шагов диффузии
        guidance_scale=guidance    # Вес подсказки
    ).images[0]

    # Сохранение изображения
    image.save(output_path)

    # Очистка памяти после завершения
    torch.mps.empty_cache()
    gc.collect()

# Пример вызова функции
generate_image(
    prompt="A cat holding a sign that says hello world",
    height=512,  # Уменьшенное разрешение для экономии памяти
    width=512,
    steps=2,    # Снижение количества шагов для ускорения
    guidance=0,
    output_path="optimized_img.png"
)
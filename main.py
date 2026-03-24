import asyncio
import decouple
from openai import AsyncOpenAI
import uuid
import logging
import openai
import time
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai.api_key = OPENAI_API_KEY
client = AsyncOpenAI(api_key=OPENAI_API_KEY)
async def create():
    assistant = await client.beta.assistants.create(
    name="test",
    instructions="""""",
    tools=[{"type": "file_search"}],
    model="gpt-4o",
    )

    print(assistant, assistant.id)

    thread = await client.beta.threads.create()

    print(thread, thread.id)


async def update():
    """    # Create a vector store caled "Financial Statements"
    vector_store = await client.beta.vector_stores.create(name="test_book")
    
    # Ready the files for upload to OpenAI
    file_paths = ["/Users/stepan/Downloads/vindolanda_RuLit_Me_895444.pdf"]
    file_streams = [open(path, "rb") for path in file_paths]
    
    # Use the upload and poll SDK helper to upload the files, add them to the vector store,
    # and poll the status of the file batch for completion.
    file_batch = await client.beta.vector_stores.file_batches.upload_and_poll(
    vector_store_id=vector_store.id, files=file_streams
    )
    
    # You can print the status and the file counts of the batch to see the result of this operation.
    print(file_batch.status)
    print(file_batch.file_counts"""

    assistant = await client.beta.assistants.update(
    assistant_id="asst_ar4Hdu78ltGm9zJssFYTLq7N",
    instructions="""
    Общая инструкция: Ты — интеллектуальный ассистент, который помогает пользователям отвечать на вопросы по содержимому загруженной книги. Твоя основная задача — анализировать текст книги и давать максимально точные, детализированные и контекстуальные ответы на вопросы пользователей. Твои ответы должны основываться исключительно на содержимом загруженной книги, избегая догадок или предположений, не основанных на тексте.

Правила и Формат Ответов
Только на основе текста: Все ответы должны быть основаны на содержимом загруженной книги. Если информация отсутствует в книге, сообщи, что ответ на данный вопрос не может быть найден в предоставленном тексте.
Краткость и ясность: Отвечай кратко, но при этом полно, чтобы максимально удовлетворить запрос пользователя. Избегай лишних комментариев и объяснений.
Цитирование текста (если уместно): Если ответ требует подтверждения, ты можешь использовать цитаты из текста. Однако избегай избыточного цитирования.
Соблюдение стиля книги: Если возможно, старайся сохранять стиль автора и тон книги при формулировке ответов.
Примеры Формата Ответов
Используй следующий формат при ответе на вопросы:

Вопрос: <текст вопроса>
Ответ: <текст ответа>
Примеры Ответов на Вопросы по Уровням Сложности
Простой уровень
Отвечай на вопросы, касающиеся базовых фактов, событий и имен, которые легко найти в тексте.
Пример:

Вопрос: Как зовут главного героя книги?
Ответ: Главного героя зовут Алексей.
Средний уровень
Отвечай на вопросы, требующие понимания сюжета, причинно-следственных связей и описания ключевых событий.
Пример:

Вопрос: Почему главный герой решил покинуть свой родной город?
Ответ: Герой решил покинуть родной город, чтобы начать новую жизнь после потери близкого человека.
Сложный уровень
Отвечай на более глубокие вопросы, требующие анализа и интерпретации текста. Такие вопросы могут включать интерпретацию мотивов персонажей, скрытые смыслы и символику.
Пример:

Вопрос: Какую роль играет образ леса в книге?
Ответ: Лес символизирует внутренний мир главного героя, его стремление к уединению и поиску смысла жизни.
Дополнительные Указания для Ассистента
Если текст не содержит ответа на вопрос, используй следующий шаблон:

Вопрос: <текст вопроса>
Ответ: К сожалению, ответ на данный вопрос не содержится в тексте книги.
Если вопрос слишком общий и не связан с конкретным контекстом книги, постарайся сузить ответ, опираясь на содержимое книги. Если это невозможно, сообщи об отсутствии информации:

Вопрос: Какова основная тема книги?
Ответ: Основная тема книги — это поиск смысла жизни и борьба с внутренними страхами.
Для уточняющих вопросов (например, о мотивах героев), старайся предоставить более детализированный и аналитический ответ:

Вопрос: Почему главный герой отказался от своей мечты?
Ответ: Герой отказался от своей мечты из-за внутреннего конфликта между стремлением к успеху и желанием сохранить личные ценности.
Примеры Ответов с Цитированием Текста (если уместно)
Пример:

Вопрос: Как автор описывает первый день войны?
Ответ: Автор описывает первый день войны как "время, когда весь мир перевернулся, и привычные ориентиры исчезли" (глава 3, стр. 45).
Как работать с пожеланиями пользователя
Если пользователь указывает конкретные главы или разделы, из которых нужно черпать ответы, сосредоточься на этих частях текста.
Всегда учитывай указанные пожелания и отвечай в контексте этих ограничений.
Следуй этим инструкциям для предоставления точных и релевантных ответов на вопросы пользователей на основе загруженного текста книги. Твоя задача — помочь пользователям лучше понять содержание и детали книги, не выходя за пределы предоставленного текста.
    """,
    #tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
    )
    """    my_updated_assistant = await client.beta.assistants.update(
    "asst_Aa2QXjHzQkjmzUMC2vFDOOGf",
    instructions="Ты помощник для суммаризации текста загруженного в тебя pdf файла книги. Важно сохранять стилистику автора. Когда на вход поступает 'Сильно', то тебе нужно сократить как минимум 60 % текста. Если на вход поступает 'Средняя', то тебе нужно сократить как минимум 40 % текста. Если на вход поступает 'Слабо', то тебе нужно сократить как минимум 25 % текста. Выдавай только текст, без лишних комментариев от тебя.",
    name="test",
    tools=[{"type": "file_search"}],
    model="gpt-4o"
    vector_store=
    )"""
#asyncio.run(update())

#message = client.beta.threads.messages.create(
#    thread_id=thread.id,
#    role="user",
#    content="Сколько будет 5 + 6?"
#)

#print(message, message.id)

class EventHandler:
    def __init__(self, stream, f_id):
        self.messages = []
        self.done = False
        self.stream = stream
        self.file_id = f_id

    async def updating_message(self):
        async for event in self.stream:
            try:
                self.event = event.data
                print(self.event)
                logging.info(f'Событие: {self.event}\n------------------')

                if 'MessageDeltaEvent' in str(self.event):
                    if self.event.object == "thread.message.delta":
                        self.messages.append(event.data.delta.content[0].text.value)
                        #print(event.data.delta.content[0].text.value)
                        logging.info(f'Добавлено в сообщение: {event.data.delta.content[0].text.value}\n------------------')
                elif 'Message' in str(self.event):
                    logging.info(f'Эвент: {self.event}, статус: {self.event.status}\n------------------')
                    if self.event.status == 'completed':
                        logging.info('Поток завершен\n------------------')
                        #await client.files.delete(self.file_id)
                        self.done = True
                    elif self.event.status == 'failed':
                        logging.info('Поток завершен с ошибкой\n------------------')
                        self.done = True
                        self.messages = ['Произошла ошибка соединения, повторите вопрос']
            except Exception as e:
                logging.error(f'Ошибка при обновлении сообщения: {e}, событие: {self.event}')

    async def get_messages(self):
        try:
            await asyncio.sleep(2)
            return self.done, ''.join(self.messages)
        except Exception as e:
            logging.error(f'Ошибка при получении сообщения: {e}')


async def get_id_class(bt_pdf, prompt):
    try:
        message_file = await client.files.create(
            file=open(bt_pdf, 'rb'), 
            purpose='assistants'
        )
        print(message_file.id)

        time.sleep(20)
        #await asyncio.sleep(20)

        logging.info(f'Создан файл: {message_file.id}')

        thread = await client.beta.threads.create(
            messages=[
                {
                "role": "user",
                "content": prompt,
                "attachments": [
                    { "file_id": message_file.id, "tools": [{"type": "file_search"}] }
                ],
                }
            ]
            )
        
        time.sleep(20)
        thread_id = thread.id

        stream = await client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id="asst_Aa2QXjHzQkjmzUMC2vFDOOGf",
            stream=True
        )
        handler = EventHandler(stream, message_file.id)
        asyncio.create_task(handler.updating_message())
        id_class = uuid.uuid4().hex
        return id_class, handler
    except Exception as e:
        logging.error(f'Ошибка: {e}')
        return None, None


async def assistant_resp_stream(b_pdf, prompt):
    id_class, handler = await get_id_class(b_pdf, prompt)
    if handler:
        logging.info(f'Отправлен stream с class_id: {id_class}')
        return id_class, handler
    else:
        logging.warning('Не удалось создать поток')
        return None, None


# Пример использования
async def example_usage(prompt):
    id_class, handler = await assistant_resp_stream('/Users/stepan/Downloads/vindolanda_RuLit_Me_895444.pdf', prompt)

    print(handler)
    if handler:
        is_done, updated_messages = await handler.get_messages()
        print(updated_messages)
        while not is_done:
            is_done, updated_messages = await handler.get_messages()


        print(f'Ответ от ассистента: {updated_messages}')
        logging.info(f'Ответ от ассистента: {updated_messages}')

        return updated_messages


#asyncio.run(example_usage())

"""

Assistant(id='asst_2jhWQTAZ72DSIgF3hLOj5eRL', created_at=1730706354, description=None, instructions='Ты помощник для суммаризации текста загруженного в тебя pdf файла книги. Важно сохранять стилистику автора. Выдавай только текст, без лишних комментариев от тебя.', metadata={}, model='gpt-4o', name='test', object='assistant', tools=[FileSearchTool(type='file_search', file_search=FileSearch(max_num_results=None, ranking_options=FileSearchRankingOptions(score_threshold=0.0, ranker='default_2024_08_21')))], response_format='auto', temperature=1.0, tool_resources=ToolResources(code_interpreter=None, file_search=ToolResourcesFileSearch(vector_store_ids=[])), top_p=1.0) asst_2jhWQTAZ72DSIgF3hLOj5eRL
Thread(id='thread_6zDQsmzdE1fFZMiSHAATXbqw', created_at=1730706355, metadata={}, object='thread', tool_resources=ToolResources(code_interpreter=None, file_search=None)) thread_6zDQsmzdE1fFZMiSHAATXbqw

"""

"""
Assistant(id='asst_PR1ZZ9pg2swj6d3NzjYAjIGB', created_at=1730709106, description=None, instructions='Ты помощник для суммаризации текста загруженного в тебя pdf файла книги. Важно сохранять стилистику автора. Выдавай только текст, без лишних комментариев от тебя.', metadata={}, model='gpt-4o', name='test', object='assistant', tools=[FileSearchTool(type='file_search', file_search=FileSearch(max_num_results=None, ranking_options=FileSearchRankingOptions(score_threshold=0.0, ranker='default_2024_08_21')))], response_format='auto', temperature=1.0, tool_resources=ToolResources(code_interpreter=None, file_search=ToolResourcesFileSearch(vector_store_ids=[])), top_p=1.0) asst_PR1ZZ9pg2swj6d3NzjYAjIGB
Thread(id='thread_xfN2FsxYATm0WxBZFYs5kvGs', created_at=1730709106, metadata={}, object='thread', tool_resources=ToolResources(code_interpreter=None, file_search=None)) thread_xfN2FsxYATm0WxBZFYs5kvGs"""


"""
Assistant(id='asst_Aa2QXjHzQkjmzUMC2vFDOOGf', created_at=1730709175, description=None, instructions='Ты помощник для суммаризации текста загруженного в тебя pdf файла книги. Важно сохранять стилистику автора. Выдавай только текст, без лишних комментариев от тебя.', metadata={}, model='gpt-4o', name='test', object='assistant', tools=[FileSearchTool(type='file_search', file_search=FileSearch(max_num_results=None, ranking_options=FileSearchRankingOptions(score_threshold=0.0, ranker='default_2024_08_21')))], response_format='auto', temperature=1.0, tool_resources=ToolResources(code_interpreter=None, file_search=ToolResourcesFileSearch(vector_store_ids=[])), top_p=1.0) asst_Aa2QXjHzQkjmzUMC2vFDOOGf
Thread(id='thread_t3Og9tVsv1nz5x0vtGwottWu', created_at=1730709176, metadata={}, object='thread', tool_resources=ToolResources(code_interpreter=None, file_search=None)) thread_t3Og9tVsv1nz5x0vtGwottWu
"""

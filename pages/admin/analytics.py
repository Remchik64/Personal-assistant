import streamlit as st
import toml
from pymongo import MongoClient
import redis
import bson


def load_config():
    # Загружаем конфигурацию из файла secrets.toml. Путь скорректирован относительно данной папки.
    try:
        config = toml.load('../../.streamlit/secrets.toml')
        return config
    except Exception as e:
        st.error(f'Ошибка загрузки конфигурации: {e}')
        return {}


config = load_config()

# Инициализация MongoDB
mongo_config = config.get('mongodb', {})
try:
    mongo_client = MongoClient(mongo_config.get('uri', ''),
                               username=mongo_config.get('username'),
                               password=mongo_config.get('password'))
    db_name = mongo_config.get('database', 'chat_app')
    mongo_db = mongo_client[db_name]
except Exception as e:
    st.error(f'Ошибка подключения к MongoDB: {e}')
    mongo_db = None

# Инициализация Redis
redis_config = config.get('redis', {})
try:
    redis_client = redis.Redis(host=redis_config.get('host', ''),
                                port=redis_config.get('port', 6379),
                                password=redis_config.get('password'),
                                db=redis_config.get('db', 0))
except Exception as e:
    st.error(f'Ошибка подключения к Redis: {e}')
    redis_client = None


st.title('Продвинутая аналитика баз данных')

# Создаем три вкладки: для Пользователей, MongoDB и Redis
tabs = st.tabs(['Пользователи', 'MongoDB', 'Redis'])

with tabs[0]:
    st.subheader('Пользователи')
    if mongo_db is not None:
         try:
             users_collection = mongo_db["users"]
             users = list(users_collection.find())
         except Exception as e:
             st.error(f'Ошибка получения пользователей: {e}')
             users = []
         if users:
             user_options = {}
             for u in users:
                 user_id = str(u.get('_id'))
                 user_label = u.get('username', user_id)
                 user_options[f"{user_label} ({user_id})"] = u
             selected_user_label = st.selectbox("Выберите пользователя", list(user_options.keys()))
             if selected_user_label:
                 selected_user = user_options[selected_user_label]
         
         if users and selected_user:
             st.write("Информация о пользователе:")
             registration_date = selected_user.get("registered_at", "Не указано")
             st.write("Дата регистрации:", registration_date)
             token_info = selected_user.get("token", {})
             if token_info:
                 active_token = token_info.get("active", False)
                 generations = token_info.get("generations", 0)
                 st.write("Активный токен:", "Да" if active_token else "Нет")
                 st.write("Количество генераций токена:", generations)
             else:
                 st.write("Информация о токене не найдена.")
             remaining_generations = selected_user.get("remaining_generations", "Нет данных")
             st.write("Остаток генераций:", remaining_generations)
             token_generations = selected_user.get("token_generations", "Нет данных")
             st.write("Всего генераций токена:", token_generations)
             assistants = selected_user.get("assistants", [])
             if assistants:
                 st.write("Личные помощники:")
                 for assistant in assistants:
                     assistant_id = assistant.get("id", "Нет ID")
                     assistant_name = assistant.get("name", "Нет имени")
                     st.write(f"ID: {assistant_id}, Имя: {assistant_name}")
             else:
                 st.write("Личные помощники не указаны.")
             sessions = selected_user.get("sessions", [])
             st.write("Количество сессий:", len(sessions))
             if sessions:
                 st.write("Истории сессий:")
                 for session in sessions:
                     session_id = session.get("id", "нет id")
                     history = session.get("history", "нет истории")
                     st.write(f"Сессия {session_id}:")
                     st.json(history)
         else:
             st.info("Пользователи не найдены")
    else:
         st.error("Подключение к MongoDB не установлено")

with tabs[1]:
    st.subheader('Аналитика MongoDB')
    if mongo_db is not None:
        try:
            collections = mongo_db.list_collection_names()
        except Exception as e:
            st.error(f'Ошибка получения коллекций: {e}')
            collections = []
        if collections:
            selected_collection = st.selectbox('Выберите коллекцию', collections)
            if selected_collection:
                col = mongo_db[selected_collection]
                try:
                    documents = list(col.find().limit(5))
                    st.write('Первые 5 документов:')
                    st.json(documents)
                except Exception as e:
                    st.error(f'Ошибка получения документов: {e}')
        else:
            st.info('Коллекции не найдены')
    else:
        st.error('Подключение к MongoDB не установлено')

    st.write('---')
    st.subheader('Редактировать документ MongoDB')
    with st.form('mongo_edit_form', clear_on_submit=True):
        collection_name = st.text_input('Название коллекции', value=selected_collection if collections else '')
        document_id = st.text_input('ID документа')
        field_name = st.text_input('Поле для редактирования')
        new_value = st.text_input('Новое значение')
        submitted = st.form_submit_button('Обновить')
        if submitted:
            if collection_name and document_id and field_name:
                col = mongo_db[collection_name]
                try:
                    obj_id = bson.ObjectId(document_id)
                except Exception:
                    st.error('Неверный формат ID документа')
                else:
                    try:
                        result = col.update_one({'_id': obj_id}, {'$set': {field_name: new_value}})
                        st.success(f'Обновлено {result.modified_count} документов')
                    except Exception as e:
                        st.error(f'Ошибка при обновлении: {e}')
            else:
                st.error('Пожалуйста, заполните все поля')

with tabs[2]:
    st.subheader('Аналитика Redis')
    if redis_client is not None:
        try:
            keys = redis_client.keys('*')
            keys = [k.decode('utf-8') for k in keys][:10] if keys else []
            st.write('Первые 10 ключей Redis:')
            for key in keys:
                try:
                    value = redis_client.get(key)
                    value_str = value.decode('utf-8') if value else 'None'
                    st.write(f'Ключ: {key}  Значение: {value_str}')
                except Exception as e:
                    st.write(f'Ключ: {key}  Ошибка чтения значения: {e}')
        except Exception as e:
            st.error(f'Ошибка получения ключей: {e}')
    else:
        st.error('Подключение к Redis не установлено')

    st.write('---')
    st.subheader('Редактировать значение Redis')
    with st.form('redis_edit_form', clear_on_submit=True):
        key_to_edit = st.text_input('Ключ')
        new_value_redis = st.text_input('Новое значение')
        submit_redis = st.form_submit_button('Обновить значение')
        if submit_redis:
            if key_to_edit and new_value_redis:
                try:
                    redis_client.set(key_to_edit, new_value_redis)
                    st.success(f'Значение для ключа {key_to_edit} обновлено')
                except Exception as e:
                    st.error(f'Ошибка обновления значения: {e}')
            else:
                st.error('Пожалуйста, заполните все поля для редактирования') 
import streamlit as st
import redis
import bson
from utils.utils import verify_admin_access
from utils.database.database_manager import get_database

# Проверка прав администратора
if not verify_admin_access():
    st.stop()

# Получаем подключение к MongoDB через существующий менеджер
db = get_database()
if not db:
    st.error("Ошибка подключения к базе данных")
    st.stop()

# Получаем прямой доступ к базе данных MongoDB
mongo_db = db.db  # Получаем объект базы данных MongoDB

# Инициализация Redis с использованием secrets
try:
    redis_client = redis.Redis(
        host=st.secrets["redis"]["host"],
        port=st.secrets["redis"]["port"],
        password=st.secrets["redis"]["password"],
        db=st.secrets["redis"]["db"],
        decode_responses=True,
        socket_timeout=10,
        socket_connect_timeout=10
    )
    # Проверяем подключение
    redis_client.ping()
except Exception as e:
    st.error(f"Ошибка подключения к Redis: {str(e)}")
    redis_client = None

st.title('Продвинутая аналитика баз данных')

# Создаем три вкладки: для Пользователей, MongoDB и Redis
tabs = st.tabs(['Пользователи', 'MongoDB', 'Redis'])

with tabs[0]:
    st.subheader('Пользователи')
    try:
        users = list(db.users.find())
        if users:
            user_options = {}
            for u in users:
                user_id = str(u.get('_id'))
                user_label = u.get('username', user_id)
                user_options[f"{user_label} ({user_id})"] = u
            selected_user_label = st.selectbox("Выберите пользователя", list(user_options.keys()))
            if selected_user_label:
                selected_user = user_options[selected_user_label]
                
                # Отображение информации о пользователе
                st.write("Информация о пользователе:")
                registration_date = selected_user.get("registered_at", "Не указано")
                st.write("Дата регистрации:", registration_date)
                
                # Информация о токене
                active_token = selected_user.get("active_token")
                st.write("Активный токен:", "Да" if active_token else "Нет")
                
                # Информация о генерациях
                remaining_generations = selected_user.get("remaining_generations", 0)
                st.write("Остаток генераций:", remaining_generations)
                
                # Чат-потоки пользователя
                chat_flows = selected_user.get("chat_flows", [])
                if chat_flows:
                    st.write("Чат-потоки:")
                    for flow in chat_flows:
                        st.write(f"ID: {flow.get('id', 'Нет ID')}, Имя: {flow.get('name', 'Без имени')}")
                else:
                    st.write("Чат-потоки отсутствуют")
        else:
            st.info("Пользователи не найдены")
    except Exception as e:
        st.error(f"Ошибка при получении данных пользователей: {str(e)}")

with tabs[1]:
    st.subheader('Аналитика MongoDB')
    collections = []  # Инициализируем пустой список
    selected_collection = None  # Инициализируем переменную
    
    try:
        collections = mongo_db.list_collection_names()
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
    except Exception as e:
        st.error(f'Ошибка получения коллекций: {e}')

    st.write('---')
    st.subheader('Редактировать документ MongoDB')
    with st.form('mongo_edit_form', clear_on_submit=True):
        collection_name = st.text_input('Название коллекции', value=selected_collection if selected_collection else '')
        document_id = st.text_input('ID документа')
        field_name = st.text_input('Поле для редактирования')
        new_value = st.text_input('Новое значение')
        submitted = st.form_submit_button('Обновить')
        if submitted:
            if collection_name and document_id and field_name:
                try:
                    col = mongo_db[collection_name]
                    obj_id = bson.ObjectId(document_id)
                    result = col.update_one({'_id': obj_id}, {'$set': {field_name: new_value}})
                    st.success(f'Обновлено {result.modified_count} документов')
                except bson.errors.InvalidId:
                    st.error('Неверный формат ID документа')
                except Exception as e:
                    st.error(f'Ошибка при обновлении: {e}')
            else:
                st.error('Пожалуйста, заполните все поля')

with tabs[2]:
    st.subheader('Аналитика Redis')
    if redis_client:
        try:
            keys = redis_client.keys('*')
            if keys:
                st.write('Первые 10 ключей Redis:')
                for key in keys[:10]:
                    try:
                        value = redis_client.get(key)
                        st.write(f'Ключ: {key}  Значение: {value}')
                    except Exception as e:
                        st.write(f'Ключ: {key}  Ошибка чтения значения: {e}')
            else:
                st.info('Ключи не найдены')
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
            if key_to_edit and new_value_redis and redis_client:
                try:
                    redis_client.set(key_to_edit, new_value_redis)
                    st.success(f'Значение для ключа {key_to_edit} обновлено')
                except Exception as e:
                    st.error(f'Ошибка обновления значения: {e}')
            else:
                st.error('Пожалуйста, заполните все поля для редактирования') 
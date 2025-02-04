import streamlit as st
from streamlit_extras.switch_page_button import switch_page
import os
from PIL import Image
from utils.page_config import setup_pages, PAGE_CONFIG
import hashlib
import io
import mimetypes
from utils.security import hash_password, is_strong_password
import requests
from googletrans import Translator
import streamlit.components.v1 as components
from datetime import datetime
from utils.database.database_manager import get_database

# Получаем экземпляр базы данных
db = get_database()

# После импортов
PROFILE_IMAGES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'profile_images'))
if not os.path.exists(PROFILE_IMAGES_DIR):
    os.makedirs(PROFILE_IMAGES_DIR)

def clear_chat_history(username: str, flow_id: str, session_id: str):
    """Очистка истории чата"""
    db.chat_history.update_one(
        {
            "username": username,
            "flow_id": flow_id,
            "session_id": session_id
        },
        {
            "$set": {
                "messages": [],
                "updated_at": datetime.now()
            }
        }
    )

def is_valid_image(file_content):
    """Проверяет, является ли файл изображением"""
    try:
        Image.open(io.BytesIO(file_content))
        return True
    except Exception:
        return False

# Первым делом настройка страницы (должна быть в самом начале!)
st.set_page_config(
    page_title="Профиль",
    page_icon="👤",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Настройка страниц
setup_pages()

# HTML для чат-бота
chat_bot_html = """
<div style="height: 600px; width: 100%;">
<script type="module">
    import Chatbot from "https://cdn.jsdelivr.net/npm/flowise-embed/dist/web.js"
    Chatbot.init({
        chatflowid: "28d13206-3a4d-4ef8-80e6-50b671b5766c",
        apiHost: "https://flowise-renataraev64.amvera.io",
        chatflowConfig: {
            // topK: 2
        },
        theme: {
            button: {
                backgroundColor: "#000000",
                right: 20,
                bottom: 20,
                size: 48,
                dragAndDrop: true,
                iconColor: "white",
                customIconSrc: "https://raw.githubusercontent.com/walkxcode/dashboard-icons/main/svg/google-messages.svg",
                autoWindowOpen: {
                    autoOpen: true,
                    openDelay: 0,
                    autoOpenOnMobile: true,
                },
            },
            tooltip: {
                showTooltip: true,
                tooltipMessage: 'Привет!',
                tooltipBackgroundColor: 'black',
                tooltipTextColor: 'white',
                tooltipFontSize: 16,
            },
            chatWindow: {
                showTitle: true,
                title: 'Поддержка',
                titleAvatarSrc: '',
                showAgentMessages: true,
                welcomeMessage: 'Привет! Я помогу вам с вопросами.',
                errorMessage: 'This is a custom error message',
                backgroundColor: "#ffffff",
                height: 700,
                width: 400,
                fontSize: 16,
                starterPromptFontSize: 15,
                clearChatOnReload: false,
                botMessage: {
                    backgroundColor: "#f7f8ff",
                    textColor: "#303235",
                    showAvatar: false,
                    showBotName: true,
                    botName: "Bot",
                    botNameColor: "#303235"
                },
                userMessage: {
                    backgroundColor: "#000000",
                    textColor: "#ffffff",
                    showAvatar: false,
                    showUserName: true,
                    userName: "User",
                    userNameColor: "#ffffff"
                },
                textInput: {
                    placeholder: ' Ваш вопрос',
                    backgroundColor: '#ffffff',
                    textColor: '#303235',
                    sendButtonColor: '#000000',
                    autoFocus: true,
                    sendMessageSound: true,
                    receiveMessageSound: true,
                },
                feedback: {
                    color: '#303235',
                },
                footer: {
                    textColor: '#303235',
                    text: '',
                    company: '',
                    companyLink: '',
                }
            }
        }
    })
</script>
</div>
"""

def main():
    # Боковое меню
    with st.sidebar:
        st.title("Меню")
        
        # Кнопка выхода
        if st.button("🚪 Выйти", use_container_width=True):
            # Очищаем состояние сессии
            for key in st.session_state.keys():
                del st.session_state[key]
            # Перезапускаем приложение
            st.rerun()
        
        # Добавляем разделитель
        st.markdown("---")
        
        # Чат с поддержкой
        st.subheader("💬 Чат с поддержкой")
        components.html(chat_bot_html, height=700)

    # Получаем данные пользователя
    user_data = db.get_user(st.session_state.username)
    if not user_data:
        st.error("Пользователь не найден")
        return

    st.title(f"Личный кабинет {st.session_state.username}")

    # Отображение информации о пользователе
    st.header("Личная информация")
    st.write(f"Email: {user_data['email']}")

    # Отображение токена и количества генераций
    if user_data.get('active_token'):
        st.subheader("Доступные генерации")
        remaining_generations = user_data.get('remaining_generations', 0)
        
        if remaining_generations > 0:
            st.success(f"Осталось генераций: {remaining_generations}")
        else:
            st.warning("Генерации закончились. Пожалуйста, активируйте новый токен.")
    else:
        st.warning("У вас нет активного токена. Для использования сервиса необходимо активировать токен.")
        if st.button("Активировать токен"):
            switch_page(PAGE_CONFIG["key_input"]["name"])

    # Отображение текущей фотографии профиля
    st.subheader("Фотография профиля")
    if user_data.get('profile_image') and os.path.exists(user_data['profile_image']):
        st.image(user_data['profile_image'], width=150)
        if st.button("Удалить фотографию профиля"):
            old_image_path = user_data.get('profile_image')
            if old_image_path and old_image_path != os.path.join(PROFILE_IMAGES_DIR, "default_user_icon.png"):
                if os.path.exists(old_image_path):
                    try:
                        os.remove(old_image_path)
                        st.success("Старое изображение успешно удалено.")
                    except Exception as e:
                        st.error(f"Ошибка при удалении файла: {e}")
            
            # Обновляем данные пользователя
            db.update_user(st.session_state.username, {
                'profile_image': None,
                'updated_at': datetime.now()
            })
            st.success("Фотография профиля удалена")
            st.rerun()
    else:
        st.write("Фотография профиля не установлена.")

    # Зона для обновления данных
    st.header("Обновление данных")
    new_username = st.text_input("Новое имя пользователя", value=user_data['username'])
    new_email = st.text_input("Новый email", value=user_data['email'])
    new_password = st.text_input("Новый пароль", type="password")
    confirm_password = st.text_input("Подтвердите новый пароль", type="password")

    # Загрузка новой фотографии профиля
    new_profile_image = st.file_uploader("Загрузить новую фотографию профиля", type=["png", "jpg", "jpeg"])
    if new_profile_image is not None:
        st.image(new_profile_image, width=150)
        updates = {}
        needs_reload = False

        try:
            # Проверяем размер файла
            MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
            if new_profile_image.size > MAX_FILE_SIZE:
                st.error("Размер файла превышает 2MB.")
                st.stop()

            # Генерируем имя файла
            file_extension = os.path.splitext(new_profile_image.name)[1].lower()
            image_filename = f"{user_data['username']}{file_extension}"
            image_path = os.path.join(PROFILE_IMAGES_DIR, image_filename)

            # Удаляем старое изображение
            old_image_path = user_data.get('profile_image')
            if old_image_path and old_image_path != os.path.join(PROFILE_IMAGES_DIR, "default_user_icon.png"):
                if os.path.exists(old_image_path):
                    try:
                        os.remove(old_image_path)
                    except Exception as e:
                        st.warning(f"Не удалось удалить старое изображение: {e}")

            # Сохраняем новое изображение
            with open(image_path, "wb") as f:
                f.write(new_profile_image.getbuffer())

            # Проверяем валидность изображения
            img = Image.open(new_profile_image)
            img.verify()
            
            # Обновляем данные пользователя
            db.update_user(st.session_state.username, {
                'profile_image': image_path,
                'updated_at': datetime.now()
            })
            needs_reload = True

        except Exception as e:
            st.error(f"Ошибка при обработке изображения: {e}")
            if 'image_path' in locals() and os.path.exists(image_path):
                os.remove(image_path)
            st.stop()

    if st.button("Обновить данные"):
        updates = {}
        needs_reload = False
        old_username = user_data['username']

        # Обработка изменения имени пользователя и email
        if new_username and new_username != old_username:
            existing_user = db.users.find_one({"username": new_username})
            if existing_user:
                st.error("Пользователь с таким именем уже существует")
            else:
                updates['username'] = new_username
                needs_reload = True

        if new_email and new_email != user_data['email']:
            updates['email'] = new_email
            needs_reload = True

        # Обработка изменения пароля
        if new_password:
            if new_password != confirm_password:
                st.error("Пароли не совпадают")
            else:
                # Проверка надежности пароля
                is_strong, message = is_strong_password(new_password)
                if not is_strong:
                    st.error(message)
                else:
                    updates['password'] = hash_password(new_password)
                    needs_reload = True

        # Если есть обновления, применяем их
        if updates:
            updates['updated_at'] = datetime.now()
            db.update_user(old_username, updates)
            st.success("Данные успешно обновлены")
            if needs_reload:
                st.rerun()

if __name__ == "__main__":
    if "authenticated" not in st.session_state or not st.session_state.authenticated:
        st.warning("Пожалуйста, войдите в систему")
        switch_page(PAGE_CONFIG["registr"]["name"])
    else:
        main()


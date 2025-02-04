import streamlit as st
from streamlit_extras.switch_page_button import switch_page
import os
from PIL import Image
from utils.page_config import setup_pages, PAGE_CONFIG
from utils.security import hash_password, is_strong_password, verify_password, check_login_attempts, increment_login_attempts, reset_login_attempts
from datetime import datetime
from utils.database.database_manager import get_database

# Получаем экземпляр базы данных
db = get_database()

# Сначала конфигурация страницы
st.set_page_config(page_title="Вход/Регистрация", layout="wide", initial_sidebar_state="collapsed")

# Добавляем CSS стили
st.markdown("""
<style>
    .auth-form h1, .auth-form h3 {
        text-align: center;
        color: #ffffff;
        margin-bottom: 2rem;
    }
    .stButton > button {
        width: 100%;
        margin-top: 1rem;
        background-color: rgba(49, 51, 63, 0.7);
        border: 1px solid rgba(250, 250, 250, 0.2);
        color: white;
    }
    .stButton > button:hover {
        border-color: rgba(250, 250, 250, 0.5);
        background-color: rgba(49, 51, 63, 0.9);
    }
    .auth-form .stTextInput > div > div > input {
        border-radius: 5px;
        background-color: rgba(49, 51, 63, 0.7);
        border: 1px solid rgba(250, 250, 250, 0.2);
        color: white;
    }
    .auth-form-toggle {
        text-align: center;
        margin-top: 1rem;
    }
    .centered-title {
        text-align: center;
        margin-bottom: 2rem;
        color: white;
    }
    .stAlert {
        background-color: rgba(49, 51, 63, 0.7) !important;
        border: 1px solid rgba(250, 250, 250, 0.2) !important;
    }
</style>
""", unsafe_allow_html=True)

# Затем настройка страниц
setup_pages()

# Убедимся, что папка для хранения изображений профиля существует
PROFILE_IMAGES_DIR = 'profile_images'
if not os.path.exists(PROFILE_IMAGES_DIR):
    os.makedirs(PROFILE_IMAGES_DIR)

# Функция для регистрации пользователя
def register_user(username, email, password, profile_image_path=None):
    # Проверяем существование пользователя
    if db.users.find_one({"username": username}):
        return False, "Пользователь с таким именем уже существует"
    if db.users.find_one({"email": email}):
        return False, "Пользователь с таким email уже существует"
        
    # Проверка надежности пароля
    is_strong, message = is_strong_password(password)
    if not is_strong:
        return False, message
        
    # Хеширование пароля
    hashed_password = hash_password(password)
    
    user_data = {
        'username': username,
        'email': email,
        'password': hashed_password,
        'profile_image': profile_image_path if profile_image_path else "profile_images/default_user_icon.png",
        'remaining_generations': 0,
        'is_admin': False,
        'created_at': datetime.now(),
        'updated_at': datetime.now()
    }
    
    # Сохраняем пользователя в MongoDB
    db.users.insert_one(user_data)
    return True, "Регистрация успешна"

# Функция для входа в систему
def login(username, password):
    # Проверка попыток входа
    can_login, message = check_login_attempts(username)
    if not can_login:
        st.error(message)
        return False
    
    # Получаем пользователя из MongoDB
    user = db.users.find_one({"username": username})
    if user and verify_password(password, user['password']):
        st.session_state.authenticated = True
        st.session_state.username = username
        st.session_state.is_admin = user.get('is_admin', False)
        # Устанавливаем состояние бокового меню как развернутое
        st.session_state.sidebar_state = "expanded"
        reset_login_attempts(username)
        setup_pages()
        return True
    
    # Увеличиваем счетчик неудачных попыток
    success, message = increment_login_attempts(username)
    if not success:
        st.error(message)
    return False

# Центрированный заголовок
st.markdown("<h1 class='centered-title'>Вход в систему</h1>", unsafe_allow_html=True)

# Создаем три колонки для центрирования
col1, col2, col3 = st.columns([1, 2, 1])

with col2:
    # Форма для входа
    with st.container():
        st.markdown("<div class='auth-form'>", unsafe_allow_html=True)
        username = st.text_input("Имя пользователя")
        password = st.text_input("Пароль", type="password")
        
        if st.button("Войти", key="login_button"):
            if username and password:  # Проверка на пустые поля
                if username == st.secrets["admin"]["admin_username"] and password == st.secrets["admin"]["admin_password"]:
                    st.session_state.authenticated = True
                    st.session_state.username = username
                    st.session_state.is_admin = True
                    # Устанавливаем состояние бокового меню как развернутое
                    st.session_state.sidebar_state = "expanded"
                    st.success("Вход выполнен успешно!")
                    setup_pages()
                    switch_page(PAGE_CONFIG["key_input"]["name"])
                elif login(username, password):
                    user = db.users.find_one({"username": username})
                    st.session_state.authenticated = True 
                    st.session_state.username = username
                    st.session_state.is_admin = user.get('is_admin', False)
                    # Устанавливаем состояние бокового меню как развернутое
                    st.session_state.sidebar_state = "expanded"
                    setup_pages()
                    switch_page(PAGE_CONFIG["key_input"]["name"])
                else:
                    st.error("Неправильный логин или пароль.")
            else:
                st.error("Пожалуйста, введите имя пользователя и пароль.")
                
        # Кнопка для переключения на форму регистрации
        if not st.session_state.get("authenticated", False):
            if st.button("Регистрация", key="show_register"):
                st.session_state.show_registration_form = True
        st.markdown("</div>", unsafe_allow_html=True)

    # Форма регистрации
    if st.session_state.get("show_registration_form", False):
        st.markdown("<div class='auth-form'>", unsafe_allow_html=True)
        with st.form("registration_form"):
            st.markdown("<h3 style='text-align: center;'>Регистрация</h3>", unsafe_allow_html=True)
            st.warning("Пожалуйста, сохраните свой логин и пароль в надежном месте. Восстановление логина и пароля не предусмотрено.")
            
            reg_username = st.text_input("Имя пользователя для регистрации")
            reg_email = st.text_input("Email")
            reg_password = st.text_input("Пароль", type="password")
            reg_confirm_password = st.text_input("Подтвердите пароль", type="password")
            
            submit_button = st.form_submit_button("Зарегистрироваться")
            
            if submit_button:
                if not reg_username or not reg_email or not reg_password or not reg_confirm_password:
                    st.error("Пожалуйста, заполните все поля.")
                elif reg_password != reg_confirm_password:
                    st.error("Пароли не совпадают")
                else:
                    default_image_path = os.path.join(PROFILE_IMAGES_DIR, "default_user_icon.png")
                    success, message = register_user(reg_username, reg_email, reg_password, default_image_path)
                    if success:
                        st.success(message)
                        st.session_state.username = reg_username
                        st.session_state.authenticated = True
                        setup_pages() 
                        switch_page(PAGE_CONFIG["key_input"]["name"])
                    else:
                        st.error(message)
        st.markdown("</div>", unsafe_allow_html=True)

# Убедимся, что пользователь аутентифицирован
if "authenticated" in st.session_state and st.session_state.authenticated:
    switch_page(PAGE_CONFIG["key_input"]["name"])

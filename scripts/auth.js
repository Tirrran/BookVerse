let authToken = localStorage.getItem('authToken');
const AUTH_DISABLED = true;
const AUTH_BYPASS_TOKEN = 'auth-disabled';
const rawHost = window.location.hostname || '127.0.0.1';
const API_HOST = (rawHost === '0.0.0.0' || rawHost === '[::]') ? '127.0.0.1' : rawHost;
const API_BASE = `http://${API_HOST}:8000`;

if (AUTH_DISABLED && !authToken) {
    localStorage.setItem('authToken', AUTH_BYPASS_TOKEN);
    authToken = AUTH_BYPASS_TOKEN;
}

function showLoginModal() {
    document.getElementById('login-modal').style.display = 'block';
}

function showRegisterModal() {
    document.getElementById('register-modal').style.display = 'block';
}

async function login(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    
    try {
        const response = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('authToken', data.token);
            authToken = data.token;
            document.getElementById('login-modal').style.display = 'none';
            updateAuthButtons();
        } else {
            alert('Ошибка входа');
        }
    } catch (error) {
        console.error('Ошибка:', error);
    }
}

async function register(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    
    try {
        const response = await fetch(`${API_BASE}/register`, {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const data = await response.json();
            localStorage.setItem('authToken', data.token);
            authToken = data.token;
            document.getElementById('register-modal').style.display = 'none';
            updateAuthButtons();
        } else {
            alert('Ошибка регистрации');
        }
    } catch (error) {
        console.error('Ошибка:', error);
    }
}

function updateAuthButtons() {
    const rightPanel = document.getElementById('right-panel');
    if (!rightPanel) return;

    const menuList = rightPanel.querySelector('.menu-list');
    if (authToken) {
        menuList.innerHTML = `
            <li><button onclick="showProfile()">👤 Профиль</button></li>
            <li><button onclick="showToolList()">🧠 Инструменты</button></li>
            <li><button onclick="openSettings()">⚙️ Настройки</button></li>
            <li><button onclick="logout()">🚪 Выйти</button></li>
        `;
    } else {
        menuList.innerHTML = `
            <li><button onclick="window.location.href='login.html'">🔑 Войти</button></li>
            <li><button onclick="window.location.href='register.html'">📝 Регистрация</button></li>
        `;
    }
}

function logout() {
    if (AUTH_DISABLED) {
        localStorage.setItem('authToken', AUTH_BYPASS_TOKEN);
        window.location.href = 'library.html';
        return;
    }
    localStorage.removeItem('authToken');
    window.location.href = 'landing.html';
}

// Создадим единую функцию для загрузки книг
async function loadUserBooks() {
    console.log('Loading user books...'); // Для отладки
    
    if (!localStorage.getItem('authToken')) {
        console.log('No auth token found');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/my-uploads`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('authToken')}`
            }
        });
        
        if (response.ok) {
            const books = await response.json();
            console.log('Fetched books:', books); // Для отладки
            
            // Сохраняем книги в localStorage
            localStorage.setItem('books', JSON.stringify(books));
            
            // Импортируем и вызываем loadLibrary
            const { loadLibrary } = await import('./main.js');
            await loadLibrary();
            return books;
        } else {
            console.error('Error fetching books:', response.statusText);
            return null;
        }
    } catch (error) {
        console.error('Error loading books:', error);
        return null;
    }
}

// Обновим функцию showMyUploads
async function showMyUploads() {
    await loadUserBooks();
}

// Обновим функцию handleFileUpload
async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData,
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('authToken')}`
            }
        });

        if (response.ok) {
            // После успешной загрузки обновляем список книг
            await loadUserBooks();
            
            // Закрываем модальное окно загрузки
            const uploadOverlay = document.getElementById('upload-overlay');
            if (uploadOverlay) {
                uploadOverlay.style.display = 'none';
            }
        }
    } catch (error) {
        console.error('Upload error:', error);
    }
}

// Добавим инициализацию при загрузке страницы
document.addEventListener('DOMContentLoaded', async () => {
    if (document.getElementById('books-grid')) {
        await loadUserBooks();
    }
});

// Добавить в начало файла
function showLoader() {
    const loader = document.getElementById('loader');
    if (loader) loader.style.display = 'flex';
}

function hideLoader() {
    const loader = document.getElementById('loader');
    if (loader) loader.style.display = 'none';
}

// Функции аутентификации
async function handleLogin(e) {
    if (AUTH_DISABLED) {
        localStorage.setItem('authToken', AUTH_BYPASS_TOKEN);
        window.location.href = 'library.html';
        return;
    }

    e.preventDefault();
    const form = e.target;
    const formData = new FormData(form);
    
    try {
        const response = await fetch(`${API_BASE}/login`, {
            method: 'POST',
            body: formData
        });
        
        if (response.ok) {
            const { token } = await response.json();
            localStorage.setItem('authToken', token);
            window.location.href = 'index.html';
        } else {
            const error = await response.json();
            throw new Error(error.detail || 'Ошибка авторизации');
        }
    } catch (error) {
        console.error('Login error:', error);
    }
}

async function handleRegister(e) {
    if (AUTH_DISABLED) {
        localStorage.setItem('authToken', AUTH_BYPASS_TOKEN);
        window.location.href = 'library.html';
        return;
    }

    const form = e.target;
    const formData = new FormData(form);
    
    showLoader();
    try {
        const response = await fetch(`${API_BASE}/register`, {
            method: 'POST',
            body: formData,
            headers: {
                'Accept': 'application/json'
            }
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Ошибка регистрации');
        }
        
        const { token } = await response.json();
        localStorage.setItem('authToken', token);
        window.location.href = 'index.html';
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoader();
    }
}

function showError(message) {
    const errorContainer = document.getElementById('error-message');
    if (errorContainer) {
        errorContainer.textContent = message;
        errorContainer.style.display = 'block';
    } else {
        alert(message);
    }
}

// Проверяем авторизацию при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
    const authToken = localStorage.getItem('authToken');
    const allowedPages = ['login.html', 'register.html', 'landing.html', 'index.html'];
    const currentPage = window.location.pathname.split('/').pop();

    if (AUTH_DISABLED) {
        if (!authToken) {
            localStorage.setItem('authToken', AUTH_BYPASS_TOKEN);
        }

        if (currentPage === 'login.html' || currentPage === 'register.html' || currentPage === 'landing.html' || currentPage === 'index.html' || currentPage === '') {
            window.location.href = 'library.html';
        }
        return;
    }
    
    // Проверка наличия токена и его валидности
    const verifyToken = async () => {
        if (!authToken) return false;
        
        try {
            const response = await fetch(`${API_BASE}/books`, {
                headers: {
                    'Authorization': `Bearer ${authToken}`
                }
            });
            return response.ok;
        } catch (error) {
            return false;
        }
    };

    (async () => {
        const isValid = await verifyToken();
        
        if (isValid) {
            if (currentPage === 'login.html' || currentPage === 'register.html' || currentPage === 'landing.html') {
                window.location.href = 'index.html';
            }
        } else {
            localStorage.removeItem('authToken');
            if (!allowedPages.includes(currentPage)) {
                window.location.href = 'landing.html';
            }
        }
    })();
});

// Инициализация библиотеки
async function initLibrary() {
    try {
        const token = localStorage.getItem('authToken');
        if (!token) {
            window.location.href = 'landing.html';
            return;
        }
        
        const response = await fetch(`${API_BASE}/books`, {
            headers: {
                'Authorization': `Bearer ${token}`,
                'Accept': 'application/json'
            }
        });
        
        if (response.status === 401) {
            localStorage.removeItem('authToken');
            window.location.href = 'login.html';
            return;
        }
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const books = await response.json();
        renderBooks(books);
    } catch (error) {
        console.error('Ошибка:', error);
        // Добавим обработку ошибок парсинга JSON
        if (error instanceof SyntaxError) {
            console.error('Ошибка парсинга JSON');
        }
    }
}

function renderBooks(books) {
    const grid = document.getElementById('books-grid');
    grid.innerHTML = books.length > 0 
        ? books.map(book => `
            <div class="book-card" data-book-id="${book.id}">
                <div class="book-cover">
                    <img src="${book.cover_url}" alt="${book.title}">
                </div>
                <div class="book-info">
                    <h3 class="book-title">${book.title}</h3>
                    <div class="book-meta">
                        <span>${new Date(book.upload_date).toLocaleDateString()}</span>
                        <span>${book.progress}%</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress" style="width: ${book.progress}%"></div>
                    </div>
                </div>
            </div>
        `).join('')
        : `<div class="empty-state">
            <div class="empty-illustration">📚</div>
            <h2>Ваша библиотека пуста</h2>
            <p>Начните своё путешествие в мир книг, загрузив первую книгу</p>
            <button class="upload-cta-btn" id="uploadCtaBtn">
                Загрузить книгу
            </button>
          </div>`;
}

// Инициализация при загрузке
if (document.getElementById('books-grid')) {
    initLibrary();
}

// Добавить в начало файла
document.addEventListener('DOMContentLoaded', () => {
    // Обработчик для кнопки выхода
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('authToken');
            window.location.href = 'landing.html';
        });
    }
});

document.addEventListener('DOMContentLoaded', () => {
    const initAuth = () => {
        const loginForm = document.getElementById('login-form');
        const registerForm = document.getElementById('register-form');
        
        if (loginForm) {
            loginForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await handleLogin(e);
            });
        }
        
        if (registerForm) {
            registerForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                await handleRegister(e);
            });
        }
    };
    
    initAuth();
});

// Добавить в конец файла
document.addEventListener('DOMContentLoaded', () => {
    // Проверка элементов перед инициализацией
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.style.display = 'block';
        logoutBtn.addEventListener('click', () => {
            localStorage.removeItem('authToken');
            window.location.href = 'landing.html';
        });
    }
    
    const menuButton = document.querySelector('.toggle-button');
    if (menuButton) {
        menuButton.addEventListener('click', toggleMenu);
    }
});

// Проверка токена
async function verifyToken(token) {
    if (AUTH_DISABLED) {
        return true;
    }

    try {
        const response = await fetch(`${API_BASE}/verify`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        return response.ok;
    } catch (error) {
        console.error('Token verification failed:', error);
        return false;
    }
}

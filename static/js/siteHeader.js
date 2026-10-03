/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { API } from './api.js';

const elements = {
    loginForm: document.getElementById('login-form'),
    username: document.getElementById('username'),
    password: document.getElementById('password'),
    logoutForm: document.getElementById('logout-form'),
    loginInfo: document.getElementById('login-info'),
    logout: document.getElementById('logout'),
    reservations: document.getElementById('my-reservations-wrap'),
    oralExams: document.getElementById('oral-exams-wrap'),
};

function setLoggedIn(username) {
    elements.loginForm.style.display = 'none';
    elements.logoutForm.style.display = 'flex';
    elements.loginInfo.textContent = username;
    elements.reservations.style.display = 'block';
    elements.oralExams.style.display = 'block';
}

function setLoggedOut() {
    elements.loginForm.style.display = 'flex';
    elements.logoutForm.style.display = 'none';
    elements.loginInfo.textContent = '';
    elements.reservations.style.display = 'none';
    elements.oralExams.style.display = 'none';
}

async function initialize() {
    const me = await API.me();
    if (me.logged_in) setLoggedIn(me.username);
    else setLoggedOut();

    elements.loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
            await API.login(elements.username.value, elements.password.value);
            window.location.reload();
        } catch (error) {
            alert(error.data?.error || 'Пријава на систем није успела.');
        }
    });

    elements.logout.addEventListener('click', async () => {
        try {
            await API.logout();
            window.location.reload();
        } catch (error) {
            alert(error.data?.error || 'Одјава није успела.');
        }
    });
}

initialize().catch((error) => console.error('Auth header error:', error));

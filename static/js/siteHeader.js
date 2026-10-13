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
    adminAttendance: document.getElementById('admin-attendance-wrap'),
};

function setLoggedIn(username, isAdmin) {
    elements.loginForm.style.display = 'none';
    elements.logoutForm.style.display = 'flex';
    elements.loginInfo.textContent = username;
    elements.reservations.style.display = 'block';
    elements.oralExams.style.display = 'block';
    elements.adminAttendance.style.display = isAdmin ? 'block' : 'none';
}

function setLoggedOut() {
    elements.loginForm.style.display = 'flex';
    elements.logoutForm.style.display = 'none';
    elements.loginInfo.textContent = '';
    elements.reservations.style.display = 'none';
    elements.oralExams.style.display = 'none';
    elements.adminAttendance.style.display = 'none';
}

export const AuthManager = {
    username: '',
    isAdmin: false,

    async updateUI() {
        const data = await API.me();
        if (!data.logged_in) {
            this.username = '';
            this.isAdmin = false;
            setLoggedOut();
            return;
        }

        this.username = data.username;
        this.isAdmin = await API.isAdmin(this.username);
        setLoggedIn(this.username, this.isAdmin);
    },

    async login(username, password) {
        await API.login(username, password);
        await this.updateUI();
    },

    async logout() {
        await API.logout();
        this.username = '';
        this.isAdmin = false;
        setLoggedOut();
    },

    isLoggedIn() {
        return Boolean(this.username);
    },
};

export async function initializeSiteHeader({ onLogin, onLogout } = {}) {
    elements.loginForm.setAttribute('autocomplete', 'off');
    elements.loginForm.setAttribute('autocapitalize', 'off');
    elements.loginForm.setAttribute('autocorrect', 'off');
    elements.username.setAttribute('autocomplete', 'off');
    elements.username.setAttribute('autocapitalize', 'off');
    elements.username.setAttribute('autocorrect', 'off');
    elements.username.setAttribute('spellcheck', 'false');
    elements.password.setAttribute('autocomplete', 'new-password');
    elements.password.setAttribute('autocapitalize', 'off');
    elements.password.setAttribute('autocorrect', 'off');
    elements.password.setAttribute('spellcheck', 'false');

    try {
        await AuthManager.updateUI();
    } catch (error) {
        console.error('Auth error:', error);
        setLoggedOut();
    }

    elements.loginForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        try {
            await AuthManager.login(elements.username.value, elements.password.value);
            elements.loginForm.reset();
            if (onLogin) onLogin();
        } catch (error) {
            alert(error.data?.error || 'Пријава на систем није успела.');
        }
    });

    elements.logout.addEventListener('click', async () => {
        try {
            await AuthManager.logout();
            if (onLogout) onLogout();
        } catch (error) {
            alert(error.data?.error || 'Одјава није успела.');
        }
    });
}

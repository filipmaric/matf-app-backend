/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { API } from './api.js';
import { qrCodeDataUrl } from './vendor/qrcode.js';
import { formatDateDDMMYYYY } from './util.js';

let pollHandle = null;
let activeSpotCheck = null;
let countdownHandle = null;
let countdownExpiresAt = null;
let qrSessionTimerHandle = null;
let qrSessionPaused = false;
let pollInFlight = false;

const QR_SESSION_DURATION_MS = 2 * 60 * 1000;

function buildJoinUrl(kind, eventId, eventDate, token) {
    const configuredBasePath = String(window.APP_CONFIG?.BASE_PATH || '').replace(/\/+$/, '');
    const attendanceMarker = '/attendance/';
    const markerIndex = window.location.pathname.indexOf(attendanceMarker);
    const inferredBasePath = markerIndex > 0
        ? window.location.pathname.slice(0, markerIndex).replace(/\/+$/, '')
        : '';
    const basePath = configuredBasePath && configuredBasePath !== '/'
        ? configuredBasePath
        : inferredBasePath;
    const path = `${basePath}/attendance/${kind}/${eventId}/${eventDate}/join/${token}`;
    return new URL(path, window.location.origin).toString();
}

function formatEventTitle(event) {
    if (event.course_name) {
        return event.course_name;
    }
    return event.description || 'Резервација';
}

function formatStudentLabel(student) {
    return student?.student_label || 'Непознато';
}

function formatAttendanceSource(student) {
    const source = String(student?.registration_source || '').toLowerCase();
    return source === 'android' ? 'android' : 'web';
}

function handleAttendanceError(err) {
    const errorCode = err.data?.error_code || '';
    const errorText = err.data?.error || 'Грешка при учитавању података о присуству.';
    if (errorCode === 'attendance_outside_class_time') {
        return { handled: true, type: 'outside_class', message: errorText };
    }
    if (errorCode === 'attendance_canceled') {
        return { handled: true, type: 'canceled', message: errorText };
    }
    if (errorCode === 'attendance_attempt_expired') {
        return { handled: true, type: 'session_expired', message: errorText };
    }
    if (errorCode === 'attendance_attempt_blocked') {
        return { handled: true, type: 'session_blocked', message: errorText };
    }
    if (errorCode === 'attendance_geofence_blocked' || errorCode === 'attendance_location_missing' || errorCode === 'attendance_location_required') {
        return { handled: true, type: 'geofence', message: errorText };
    }
    return { handled: false, message: errorText };
}

function renderEventInfo(root, event) {
    const info = document.createElement('div');
    info.className = 'attendance-panel';
    const groups = Array.isArray(event.groups)
        ? event.groups
        : (typeof event.groups === 'string' && event.groups.length ? event.groups.split(',') : []);

    const title = document.createElement('h2');
    title.textContent = formatEventTitle(event);
    info.appendChild(title);

    const details = document.createElement('p');
    const parts = [
        `Датум: ${formatDateDDMMYYYY(event.event_date || event.reservation_date)}`,
        `Време: ${String(event.start_slot).padStart(2, '0')}:00 - ${String(event.end_slot).padStart(2, '0')}:00`,
        `Сала: ${event.room_name}`,
    ];
    if (event.teacher_name) parts.push(`Наставник: ${event.teacher_name}`);
    if (groups.length) parts.push(`Групе: ${groups.join(', ')}`);
    if (event.is_canceled) parts.push('Час је отказан.');
    details.textContent = parts.join(' | ');
    info.appendChild(details);

    root.appendChild(info);
}

function renderQr(root, joinUrl) {
    const box = document.createElement('div');
    box.className = 'attendance-qr-box';

    const link = document.createElement('a');
    link.href = joinUrl;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.title = 'Отвори QR линк';

    const img = document.createElement('img');
    img.alt = 'QR код за пријаву присуства';
    img.src = qrCodeDataUrl(joinUrl, 240);
    link.appendChild(img);
    box.appendChild(link);

    root.appendChild(box);
}

function clearQrSessionTimer() {
    if (qrSessionTimerHandle) {
        clearTimeout(qrSessionTimerHandle);
        qrSessionTimerHandle = null;
    }
}

function renderQrPaused(root, pageRoot = root) {
    const existingQr = root.querySelector('.attendance-qr-box');
    const existingChallenge = root.querySelector('.attendance-challenge-box');
    const parent = existingQr?.parentElement || existingChallenge?.parentElement || root;
    if (!parent) return;

    existingQr?.remove();
    existingChallenge?.remove();
    parent.querySelector('.attendance-qr-paused')?.remove();

    const box = document.createElement('div');
    box.className = 'attendance-panel attendance-qr-paused';

    const message = document.createElement('p');
    message.textContent = 'Пријављивање је паузирано после два минута.';
    box.appendChild(message);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'attendance-summary-btn';
    button.textContent = 'Продужи пријављивање';
    button.addEventListener('click', async () => {
        qrSessionPaused = false;
        startQrSession(pageRoot);
        try {
            await refresh(pageRoot);
        } catch (error) {
            const result = handleAttendanceError(error);
            if (error.status === 403 && result.handled && result.type === 'outside_class') {
                showAccessMessage(pageRoot, result.message);
            }
        }
    });
    box.appendChild(button);
    parent.appendChild(box);
}

async function pauseQrSession(root) {
    qrSessionPaused = true;
    clearQrSessionTimer();
    if (countdownHandle) {
        clearInterval(countdownHandle);
        countdownHandle = null;
    }
    countdownExpiresAt = null;
    try {
        // Ask the server for the authoritative expiry state. This makes the
        // two-minute limit survive closing and reopening the page.
        await refresh(root);
    } catch (error) {
        renderQrPaused(root);
    }
}

function startQrSession(root) {
    clearQrSessionTimer();
    qrSessionPaused = false;
    qrSessionTimerHandle = setTimeout(() => pauseQrSession(root), QR_SESSION_DURATION_MS);
}

function renderChallenge(root, challenge, event) {
    let box = root.querySelector('.attendance-challenge-box');
    if (!box) {
        box = document.createElement('div');
        box.className = 'attendance-challenge-box';
        root.appendChild(box);
    }

    box.innerHTML = '';

    const code = document.createElement('div');
    code.className = 'attendance-code';
    code.textContent = String(challenge.current_code);
    box.appendChild(code);

    const countdown = document.createElement('p');
    countdown.className = 'attendance-countdown';
    countdown.textContent = `Преостало: ${challenge.expires_in} секунди`;
    box.appendChild(countdown);

    if (countdownHandle) {
        clearInterval(countdownHandle);
        countdownHandle = null;
    }
    countdownExpiresAt = Date.now() + (Number(challenge.expires_in) * 1000);

    const updateCountdown = () => {
        if (!countdown.isConnected) {
            if (countdownHandle) {
                clearInterval(countdownHandle);
                countdownHandle = null;
            }
            return;
        }

        const remainingMs = Math.max(0, countdownExpiresAt - Date.now());
        const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
        countdown.textContent = `Преостало: ${remainingSeconds} секунди`;
        code.classList.toggle('attendance-code-danger', remainingSeconds < 3);

        if (remainingSeconds <= 0 && countdownHandle) {
            clearInterval(countdownHandle);
            countdownHandle = null;
        }
    };

    updateCountdown();
    countdownHandle = setInterval(updateCountdown, 1000);
}

function renderGeofenceControl(root, data, kind, eventId, eventDate, pageRoot) {
    if (data.attendance_guest_registration_enabled) {
        return;
    }

    const box = document.createElement('section');
    box.className = 'attendance-panel attendance-geofence-panel';

    if (!data.attendance_geofence_available) {
        const warning = document.createElement('p');
        warning.className = 'attendance-geofence-warning';
        warning.textContent = data.attendance_geofence_warning || 'Локација за ову учионицу није подешена.';
        box.appendChild(warning);
        root.appendChild(box);
        return;
    }

    const label = document.createElement('label');
    label.className = 'attendance-geofence-toggle';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = Boolean(data.attendance_geofence_enabled);
    checkbox.disabled = Boolean(data.attendance_session_active);

    const text = document.createElement('span');
    text.textContent = 'Провери локацију';

    const status = document.createElement('span');
    status.className = `attendance-geofence-status ${
        data.attendance_geofence_enabled ? 'attendance-geofence-status-on' : 'attendance-geofence-status-off'
    }`;
    status.textContent = data.attendance_geofence_enabled ? 'укључено' : 'искључено';

    label.appendChild(checkbox);
    label.appendChild(text);
    box.appendChild(label);
    box.appendChild(status);

    checkbox.addEventListener('change', async () => {
        checkbox.disabled = true;
        try {
            await API.setAttendanceGeofence(kind, eventId, eventDate, checkbox.checked);
            await refresh(pageRoot);
        } catch (error) {
            checkbox.checked = !checkbox.checked;
            window.alert(error.data?.error || 'Грешка при чувању провере локације.');
        } finally {
            checkbox.disabled = false;
        }
    });

    root.appendChild(box);
}

function renderGuestRegistrationControl(root, data, kind, eventId, eventDate, pageRoot) {
    const box = document.createElement('section');
    box.className = 'attendance-panel attendance-guest-registration-panel';

    const label = document.createElement('label');
    label.className = 'attendance-geofence-toggle';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = Boolean(data.attendance_guest_registration_enabled);
    checkbox.disabled = Boolean(data.attendance_session_active);

    const text = document.createElement('span');
    text.textContent = 'Дозволи пријаву неулогованих студената';

    const status = document.createElement('span');
    status.className = `attendance-geofence-status ${
        data.attendance_guest_registration_enabled
            ? 'attendance-geofence-status-on'
            : 'attendance-geofence-status-off'
    }`;
    status.textContent = data.attendance_guest_registration_enabled ? 'укључено' : 'искључено';

    label.appendChild(checkbox);
    label.appendChild(text);
    box.appendChild(label);
    box.appendChild(status);

    checkbox.addEventListener('change', async () => {
        if (checkbox.checked && !window.confirm(
            'Овај режим не проверава идентитет студента нити локацију. Свако ко скенира QR код може да се пријави у име било ког постојећег студента, а провера локације ће бити искључена. Да ли желите да наставите?'
        )) {
            checkbox.checked = false;
            return;
        }

        checkbox.disabled = true;
        try {
            await API.setAttendanceGuestRegistration(kind, eventId, eventDate, checkbox.checked);
            await refresh(pageRoot);
        } catch (error) {
            checkbox.checked = !checkbox.checked;
            window.alert(error.data?.error || 'Грешка при чувању режима пријаве.');
        } finally {
            checkbox.disabled = false;
        }
    });

    root.appendChild(box);
}

function renderStartAttendanceControl(root, kind, eventId, eventDate, pageRoot, expired = false) {
    const box = document.createElement('section');
    box.className = 'attendance-panel attendance-start-panel';

    const explanation = document.createElement('p');
    explanation.textContent = expired
        ? 'Пријављивање је истекло после два минута. Ако желите да наставите, продужите га.'
        : 'Подесите начин пријављивања изнад, а затим покрените пријављивање.';
    box.appendChild(explanation);

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'attendance-summary-btn';
    button.textContent = expired ? 'Продужи пријављивање' : 'Започни пријављивање';
    button.addEventListener('click', async () => {
        button.disabled = true;
        try {
            await API.setAttendanceSession(kind, eventId, eventDate, true);
            startQrSession(pageRoot);
            await refresh(pageRoot);
        } catch (error) {
            window.alert(error.data?.error || 'Грешка при покретању пријављивања.');
            button.disabled = false;
        }
    });
    box.appendChild(button);
    root.appendChild(box);
}

function renderStopAttendanceControl(root, kind, eventId, eventDate, pageRoot) {
    const box = document.createElement('section');
    box.className = 'attendance-panel attendance-stop-panel';

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'attendance-summary-btn';
    button.textContent = 'Заустави пријављивање';
    button.addEventListener('click', async () => {
        button.disabled = true;
        try {
            await API.setAttendanceSession(kind, eventId, eventDate, false);
            clearQrSessionTimer();
            qrSessionPaused = false;
            await refresh(pageRoot);
        } catch (error) {
            window.alert(error.data?.error || 'Грешка при заустављању пријављивања.');
            button.disabled = false;
        }
    });
    box.appendChild(button);
    root.appendChild(box);
}

function renderRoster(root, students, kind, eventId, eventDate, pageRoot) {
    const section = document.createElement('section');
    section.className = 'attendance-roster';

    const title = document.createElement('h3');
    title.textContent = 'Пријављени студенти';
    section.appendChild(title);

    if (!students.length) {
        const p = document.createElement('p');
        p.textContent = 'Нема пријављених студената.';
        section.appendChild(p);
    } else {
        const list = document.createElement('ol');
        students.forEach((student) => {
            const li = document.createElement('li');
            const label = document.createElement('span');
            label.className = 'attendance-roster-student';
            label.textContent = formatStudentLabel(student);
            li.appendChild(label);

            const source = document.createElement('span');
            const normalizedSource = formatAttendanceSource(student);
            source.className = `attendance-source-badge attendance-source-${normalizedSource}`;
            source.textContent = normalizedSource;
            li.appendChild(source);

            const removeButton = document.createElement('button');
            removeButton.type = 'button';
            removeButton.className = 'attendance-remove-record-btn';
            removeButton.textContent = '×';
            removeButton.title = 'Обриши пријаву студента';
            removeButton.setAttribute('aria-label', 'Обриши пријаву студента');
            removeButton.addEventListener('click', async () => {
                if (!window.confirm(`Да ли желите да обришете пријаву студента ${formatStudentLabel(student)}?`)) {
                    return;
                }
                removeButton.disabled = true;
                try {
                    await API.deleteAttendanceRecord(
                        kind,
                        eventId,
                        eventDate,
                        student.attendance_record_id,
                    );
                    await refresh(pageRoot);
                } catch (error) {
                    window.alert(error.data?.error || 'Грешка при брисању пријаве студента.');
                    removeButton.disabled = false;
                }
            });
            li.appendChild(removeButton);
            list.appendChild(li);
        });
        section.appendChild(list);
    }

    root.appendChild(section);
}

function ensureTeacherLayout(root) {
    let layout = root.querySelector('.attendance-teacher-layout');
    if (layout) {
        return {
            layout,
            left: layout.querySelector('.attendance-teacher-column-left'),
            right: layout.querySelector('.attendance-teacher-column-right'),
        };
    }

    layout = document.createElement('div');
    layout.className = 'attendance-teacher-layout';

    const left = document.createElement('div');
    left.className = 'attendance-teacher-column attendance-teacher-column-left';

    const right = document.createElement('div');
    right.className = 'attendance-teacher-column attendance-teacher-column-right';

    layout.appendChild(left);
    layout.appendChild(right);
    root.appendChild(layout);

    return { layout, left, right };
}

function ensureSpotCheckDialog() {
    let dialog = document.getElementById('attendance-spot-check-dialog');
    if (dialog) {
        return dialog;
    }

    dialog = document.createElement('dialog');
    dialog.id = 'attendance-spot-check-dialog';
    dialog.className = 'attendance-dialog';

    const header = document.createElement('div');
    header.className = 'attendance-dialog-header';

    const titleWrap = document.createElement('div');
    titleWrap.className = 'attendance-dialog-title-wrap';

    const title = document.createElement('h3');
    title.id = 'attendance-spot-check-title';
    title.textContent = 'Провера присуства';
    titleWrap.appendChild(title);

    const subtitle = document.createElement('p');
    subtitle.id = 'attendance-spot-check-subtitle';
    subtitle.className = 'attendance-dialog-subtitle';
    titleWrap.appendChild(subtitle);

    header.appendChild(titleWrap);

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'attendance-dialog-close';
    closeButton.textContent = '×';
    closeButton.setAttribute('aria-label', 'Затвори');
    closeButton.addEventListener('click', () => dialog.close());
    header.appendChild(closeButton);

    dialog.appendChild(header);

    const body = document.createElement('div');
    body.id = 'attendance-spot-check-body';
    dialog.appendChild(body);

    const footer = document.createElement('div');
    footer.className = 'attendance-dialog-footer';

    const confirmButton = document.createElement('button');
    confirmButton.type = 'button';
    confirmButton.className = 'attendance-summary-btn';
    confirmButton.id = 'attendance-spot-check-confirm';
    confirmButton.textContent = 'У реду';
    footer.appendChild(confirmButton);

    dialog.appendChild(footer);
    dialog.addEventListener('close', () => {
        activeSpotCheck = null;
    });

    document.body.appendChild(dialog);
    return dialog;
}

function openSpotCheckDialog(root, kind, eventId, eventDate, event, students) {
    const dialog = ensureSpotCheckDialog();
    const subtitle = dialog.querySelector('#attendance-spot-check-subtitle');
    const body = dialog.querySelector('#attendance-spot-check-body');
    const confirmButton = dialog.querySelector('#attendance-spot-check-confirm');

    activeSpotCheck = {
        root,
        kind,
        eventId,
        eventDate,
        event,
        students,
    };

    subtitle.textContent = `${formatEventTitle(event)} • ${formatDateDDMMYYYY(event.event_date || event.reservation_date)}`;
    body.innerHTML = '';

    if (!students.length) {
        const empty = document.createElement('p');
        empty.textContent = 'Нема студената за ручну проверу.';
        body.appendChild(empty);
    } else {
        const list = document.createElement('ul');
        list.className = 'attendance-spot-check-list';
        students.forEach((student, index) => {
            const item = document.createElement('li');
            const text = document.createElement('span');
            text.className = 'attendance-spot-check-student';
            text.textContent = formatStudentLabel(student);
            item.appendChild(text);

            const statuses = document.createElement('span');
            statuses.className = 'attendance-spot-check-statuses';
            ['Присутан', 'Одсутан'].forEach((status, statusIndex) => {
                const label = document.createElement('label');
                label.className = 'attendance-spot-check-item';

                const radio = document.createElement('input');
                radio.type = 'radio';
                radio.name = `attendance-status-${index}`;
                radio.value = statusIndex === 0 ? 'present' : 'absent';
                radio.dataset.username = student.username;
                radio.dataset.attendanceStatus = radio.value;
                radio.checked = statusIndex === 0;

                label.appendChild(radio);
                label.appendChild(document.createTextNode(status));
                statuses.appendChild(label);
            });
            item.appendChild(statuses);
            list.appendChild(item);
        });
        body.appendChild(list);
    }

    confirmButton.onclick = async () => {
        if (!activeSpotCheck) {
            return;
        }
        const selectedUsernames = activeSpotCheck.students.map((student) => student.username);
        const confirmedUsernames = Array.from(
            body.querySelectorAll('input[data-attendance-status="present"]:checked')
        ).map((radio) => radio.dataset.username);
        confirmButton.disabled = true;
        try {
            await API.submitAttendanceSpotCheck(
                activeSpotCheck.kind,
                activeSpotCheck.eventId,
                activeSpotCheck.eventDate,
                {
                    selected_usernames: selectedUsernames,
                    confirmed_usernames: confirmedUsernames,
                }
            );
            activeSpotCheck = null;
            dialog.close();
        } catch (error) {
            const message = error.data?.error || 'Грешка при чувању провере.';
            const note = document.createElement('p');
            note.textContent = message;
            body.appendChild(note);
        } finally {
            confirmButton.disabled = false;
        }
    };

    if (typeof dialog.showModal === 'function') {
        dialog.showModal();
    } else {
        dialog.setAttribute('open', 'open');
    }
}

function showAccessMessage(root, messageText) {
    if (pollHandle) {
        clearInterval(pollHandle);
        pollHandle = null;
    }
    clearQrSessionTimer();
    qrSessionPaused = false;
    root.innerHTML = '';
    const panel = document.createElement('div');
    panel.className = 'attendance-panel attendance-blocked-panel';

    const title = document.createElement('h2');
    title.textContent = 'Пријава присуства је могућа само током часа';
    panel.appendChild(title);

    const note = document.createElement('p');
    note.textContent = messageText || 'Приступ је ограничен на време трајања часа.';
    panel.appendChild(note);

    root.appendChild(panel);
}

async function refresh(root) {
    const { kind, eventId, eventDate } = root.dataset;
    const data = await API.getAttendanceRoster(kind, eventId, eventDate, false, !qrSessionPaused);
    root.innerHTML = '';
    if (countdownHandle) {
        clearInterval(countdownHandle);
        countdownHandle = null;
    }
    countdownExpiresAt = null;

    const { left, right } = ensureTeacherLayout(root);

    renderEventInfo(left, data.event);
    renderGuestRegistrationControl(left, data, kind, eventId, eventDate, root);
    renderGeofenceControl(left, data, kind, eventId, eventDate, root);

    if (data.event.is_canceled) {
        showAccessMessage(root, 'Овај час је отказан.');
        return data;
    }
    if (!data.attendance_open) {
        showAccessMessage(root, 'Пријава присуства је могућа само током часа.');
        return data;
    }

    if (!data.attendance_session_active) {
        renderStartAttendanceControl(left, kind, eventId, eventDate, root, data.attendance_session_expired);
    } else if (qrSessionPaused) {
        renderQrPaused(left, root);
    } else {
        const joinUrl = buildJoinUrl(kind, eventId, eventDate, data.join_token);
        renderQr(left, joinUrl);
        renderChallenge(left, data.challenge, data.event);
    }
    if (data.attendance_session_active) {
        renderStopAttendanceControl(left, kind, eventId, eventDate, root);
    }
    renderRoster(right, data.students || [], kind, eventId, eventDate, root);

    if (data.students && data.students.length) {
        const actions = document.createElement('div');
        actions.className = 'attendance-session-actions';

        const help = document.createElement('p');
        help.className = 'attendance-spot-check-help';
        help.textContent = 'Овде можете ручно проверити део пријављених студената. Систем ће предложити до пет студената; означите оне чије присуство потврђујете.';
        actions.appendChild(help);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'attendance-summary-btn';
        button.textContent = 'Провери присуство';
        button.addEventListener('click', async () => {
            button.disabled = true;
            try {
                const shortlist = await API.getAttendanceSpotCheck(kind, eventId, eventDate, 5);
                openSpotCheckDialog(root, kind, eventId, eventDate, shortlist.event || data.event, shortlist.students || []);
            } catch (error) {
                window.alert(error.data?.error || 'Грешка при учитавању провере присуства.');
            } finally {
                button.disabled = false;
            }
        });
        actions.appendChild(button);
        right.appendChild(actions);
    }

    return data;
}

const App = {
    async init() {
        const root = document.getElementById('attendance-root');
        try {
            const data = await refresh(root);
            if (data.attendance_session_active) {
                startQrSession(root);
            }
            pollHandle = setInterval(async () => {
                if (pollInFlight) return;
                pollInFlight = true;
                try {
                    await refresh(root);
                } catch (err) {
                    const result = handleAttendanceError(err);
                    if (result.handled && (result.type === 'outside_class' || result.type === 'canceled')) {
                        showAccessMessage(root, result.message);
                    }
                } finally {
                    pollInFlight = false;
                }
            }, 2000);
        } catch (err) {
            const result = handleAttendanceError(err);
            if (err.status === 403 && result.handled && result.type === 'outside_class') {
                showAccessMessage(root, result.message);
                return;
            }
            root.innerHTML = '';
            const p = document.createElement('p');
            p.textContent = 'Грешка при учитавању података о присуству.';
            root.appendChild(p);
        }
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());

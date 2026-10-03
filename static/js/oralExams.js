/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { createCalendarTopBar, createCancelButton } from './calendarActions.js';
import { renderCalendarMenu } from './calendarExport.js';
import { createMouseIntervalSelector } from './calendarInteraction.js';

const BASE_PATH = window.APP_CONFIG?.BASE_PATH || '';
const getUrl = (path) => `${BASE_PATH}${path}`;

const termSelect = document.getElementById('oral-exam-term');
const sessionSelect = document.getElementById('oral-exam-session');
const groupsRoot = document.getElementById('oral-exams-groups');
const calendarRoot = document.getElementById('oral-exams-calendar');
const status = document.getElementById('oral-exams-status');
const DAY_NAMES = ['понедељак', 'уторак', 'среда', 'четвртак', 'петак', 'субота', 'недеља'];
const FIRST_HOUR = 8;
const LAST_HOUR = 24;
let currentWeekStart = null;
let activeSelection = null;

function setStatus(message = '') {
    status.hidden = !message;
    status.textContent = message;
}

async function loadData() {
    const params = new URLSearchParams();
    if (termSelect.value) params.set('term_code', termSelect.value);
    if (sessionSelect.value) params.set('session_id', sessionSelect.value);
    const suffix = params.toString() ? `?${params.toString()}` : '';
    const response = await fetch(getUrl(`/oral_exams_data${suffix}`), { credentials: 'same-origin' });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || 'Грешка при учитавању података.');
    }
    return response.json();
}

function populateSelect(select, items, value, label) {
    select.replaceChildren();
    items.forEach((item) => {
        const option = document.createElement('option');
        option.value = value(item);
        option.textContent = label(item);
        select.appendChild(option);
    });
}

function parseDate(value) {
    return new Date(`${value}T12:00:00`);
}

function formatDate(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function formatDay(date) {
    return `${date.getDate()}.${String(date.getMonth() + 1).padStart(2, '0')}.`;
}

function mondayOf(date) {
    const result = new Date(date);
    const day = result.getDay();
    result.setDate(result.getDate() - (day === 0 ? 6 : day - 1));
    return result;
}

function addDays(date, amount) {
    const result = new Date(date);
    result.setDate(result.getDate() + amount);
    return result;
}

function expandExamRowsToFitText(tbody) {
    let requiredSlotHeight = 34;
    const verticalBreathingRoom = 12;
    tbody.querySelectorAll('.oral-exam-calendar-item').forEach((item) => {
        const duration = Math.max(1, Number(item.dataset.durationHours || 1));
        const details = item.querySelector('.oral-exam-calendar-details');
        const topBar = item.querySelector('.res-top-bar');
        let contentHeight = item.scrollHeight;

        // The details area is a flex child of an item whose height is based
        // on the current table row. Measure its intrinsic height as well, so
        // long exam names cannot overflow before the row is expanded.
        if (details) {
            const previousFlex = details.style.flex;
            const previousMinHeight = details.style.minHeight;
            details.style.flex = '0 0 auto';
            details.style.minHeight = 'max-content';
            contentHeight = Math.max(contentHeight, details.scrollHeight + (topBar?.offsetHeight || 0));
            details.style.flex = previousFlex;
            details.style.minHeight = previousMinHeight;
        }
        requiredSlotHeight = Math.max(
            requiredSlotHeight,
            Math.ceil((contentHeight + verticalBreathingRoom) / duration),
        );
    });
    tbody.querySelectorAll('tr').forEach((row) => {
        row.style.height = `${requiredSlotHeight}px`;
    });
}

function renderGroups(data) {
    groupsRoot.replaceChildren();
    calendarRoot.replaceChildren();
    activeSelection = null;
    selectionController.clear();
    calendarRoot.hidden = true;
    if (!data.selected_session) {
        groupsRoot.textContent = 'Изаберите предмет да бисте видели групе.';
        return;
    }

    const panel = document.createElement('section');
    panel.className = 'attendance-panel';
    const heading = document.createElement('h2');
    heading.textContent = `Групе за предмет: ${data.selected_session.name}`;
    panel.appendChild(heading);
    if (!data.groups.length) {
        panel.appendChild(document.createTextNode('Нема група за овај курс у текућој школској години.'));
    } else {
        const list = document.createElement('ul');
        data.groups.forEach((group) => {
            const item = document.createElement('li');
            const description = group.description ? ` (${group.description})` : '';
            const count = group.application_count === null || group.application_count === undefined
                ? 'пријављено: непознато'
                : `пријављено: ${group.application_count}`;
            item.textContent = `${group.name}${description} · ${count}`;
            list.appendChild(item);
        });
        panel.appendChild(list);
    }
    groupsRoot.appendChild(panel);
    renderExamCalendar(data);
}

const selectionController = createMouseIntervalSelector({
    container: calendarRoot,
    cellSelector: '.oral-exam-calendar-cell-selectable',
    selectedClass: 'oral-exam-calendar-cell-selected',
    getGroupKey: (cell) => cell.dataset.date,
    onPreview: (selection) => {
        activeSelection = selection;
    },
    onSelection: (selection) => {
        activeSelection = selection;
        createOralExam().catch((error) => setStatus(error.message));
    },
});

async function createOralExam() {
    if (!activeSelection || !termSelect.value || !sessionSelect.value) return;
    setStatus('Чување усменог испита...');
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response = await fetch(getUrl('/oral_exams_schedule'), {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
        },
        body: JSON.stringify({
            term_code: termSelect.value,
            session_id: sessionSelect.value,
            exam_date: activeSelection.date,
            start_hour: activeSelection.startHour,
            end_hour: activeSelection.endHour,
        }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Усмени испит није сачуван.');
    setStatus('Усмени испит је сачуван.');
    await refresh({ preserveCourse: true });
}

async function deleteOralExam(scheduleId) {
    setStatus('Отказивање усменог испита...');
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response = await fetch(getUrl(`/oral_exams_schedule/${scheduleId}`), {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Усмени испит није отказан.');
    await refresh({ preserveCourse: true });
}

async function deleteOralReservation(reservationId) {
    setStatus('Отказивање резервације сале...');
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response = await fetch(getUrl(`/reservation/${reservationId}`), {
        method: 'DELETE',
        credentials: 'same-origin',
        headers: csrfToken ? { 'X-CSRFToken': csrfToken } : {},
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Резервација сале није отказана.');
    await refresh({ preserveCourse: true });
}

function createReservationViewButton(exam) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'oral-exam-room-action oral-exam-room-view';
    button.textContent = '▤';
    button.title = 'Прикажи резервације';
    button.setAttribute('aria-label', 'Прикажи резервације');
    button.addEventListener('click', (event) => {
        event.stopPropagation();
        window.open(
            getUrl(`/?date=${encodeURIComponent(exam.exam_date)}`),
            '_blank',
            'noopener,noreferrer',
        );
    });
    return button;
}

function ensureOralRoomDialog() {
    let dialog = document.getElementById('oral-exam-room-dialog');
    if (dialog) return dialog;
    dialog = document.createElement('dialog');
    dialog.id = 'oral-exam-room-dialog';
    dialog.className = 'oral-exam-room-dialog';
    document.body.appendChild(dialog);
    return dialog;
}

async function reserveRoomForOralExam(exam) {
    const dialog = ensureOralRoomDialog();
    dialog.replaceChildren();
    const title = document.createElement('h2');
    title.textContent = 'Резервиши салу';
    dialog.appendChild(title);

    const loading = document.createElement('p');
    loading.textContent = 'Учитавање слободних сала...';
    dialog.appendChild(loading);
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', 'open');

    try {
        const response = await fetch(getUrl(`/oral_exams_schedule/${exam.id}/available_rooms`), {
            credentials: 'same-origin',
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Слободне сале нису учитане.');
        const rooms = data.rooms || [];
        dialog.replaceChildren(title);
        if (!rooms.length) {
            const empty = document.createElement('p');
            empty.textContent = 'Нема слободних сала за овај термин.';
            dialog.appendChild(empty);
        } else {
            const select = document.createElement('select');
            select.className = 'oral-exam-room-select';
            const roomsByBuilding = new Map();
            rooms.forEach((room) => {
                const building = room.building_name || 'Остале зграде';
                if (!roomsByBuilding.has(building)) roomsByBuilding.set(building, []);
                roomsByBuilding.get(building).push(room);
            });
            [...roomsByBuilding.entries()].sort(([first], [second]) => first.localeCompare(second, 'sr')).forEach(([building, buildingRooms]) => {
                const group = document.createElement('optgroup');
                group.label = building;
                buildingRooms.sort((first, second) => first.name.localeCompare(second.name, 'sr'));
                buildingRooms.forEach((room) => {
                    const option = document.createElement('option');
                    option.value = room.id;
                    option.textContent = room.name;
                    group.appendChild(option);
                });
                select.appendChild(group);
            });
            dialog.appendChild(select);
            const actions = document.createElement('div');
            actions.className = 'oral-exam-room-dialog-actions';
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.textContent = 'Откажи';
            cancel.addEventListener('click', () => dialog.close());
            const reserve = document.createElement('button');
            reserve.type = 'button';
            reserve.textContent = 'Резервиши';
            reserve.addEventListener('click', async () => {
                reserve.disabled = true;
                try {
                    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';
                    const reserveResponse = await fetch(
                        getUrl(`/oral_exams_schedule/${exam.id}/reserve_room`),
                        {
                            method: 'POST',
                            credentials: 'same-origin',
                            headers: {
                                'Content-Type': 'application/json',
                                ...(csrfToken ? { 'X-CSRFToken': csrfToken } : {}),
                            },
                            body: JSON.stringify({ room_id: select.value }),
                        },
                    );
                    const reserveData = await reserveResponse.json().catch(() => ({}));
                    if (!reserveResponse.ok) {
                        throw new Error(reserveData.error || 'Сала није резервисана.');
                    }
                    dialog.close();
                    await refresh({ preserveCourse: true });
                } catch (error) {
                    setStatus(error.message);
                    reserve.disabled = false;
                }
            });
            actions.append(cancel, reserve);
            dialog.appendChild(actions);
        }
    } catch (error) {
        dialog.replaceChildren(title);
        const message = document.createElement('p');
        message.textContent = error.message;
        dialog.appendChild(message);
    }
}

function renderExamCalendar(data) {
    if (!data.selected_term || !data.selected_session) return;
    calendarRoot.replaceChildren();
    const termStart = mondayOf(parseDate(data.selected_term.start_date));
    if (!currentWeekStart) {
        currentWeekStart = termStart;
    }

    calendarRoot.hidden = false;
    const header = document.createElement('div');
    header.className = 'oral-exams-calendar-header';
    const previous = document.createElement('a');
    previous.href = '#';
    previous.textContent = '<<';
    previous.setAttribute('aria-label', 'Претходна недеља');
    previous.className = 'oral-exams-week-link';
    previous.addEventListener('click', (event) => {
        event.preventDefault();
        currentWeekStart = addDays(currentWeekStart, -7);
        renderExamCalendar(data);
    });
    const title = document.createElement('h2');
    title.textContent = `Писмени испити: ${formatDay(currentWeekStart)} – ${formatDay(addDays(currentWeekStart, 6))}`;
    const next = document.createElement('a');
    next.href = '#';
    next.textContent = '>>';
    next.setAttribute('aria-label', 'Следећа недеља');
    next.className = 'oral-exams-week-link';
    next.addEventListener('click', (event) => {
        event.preventDefault();
        currentWeekStart = addDays(currentWeekStart, 7);
        renderExamCalendar(data);
    });
    header.append(previous, title, next);
    calendarRoot.appendChild(header);

    const table = document.createElement('table');
    table.className = 'oral-exams-week-table';
    const headerRow = document.createElement('tr');
    const timeHeader = document.createElement('th');
    timeHeader.textContent = 'Време';
    headerRow.appendChild(timeHeader);
    for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
        const date = addDays(currentWeekStart, dayIndex);
        const cell = document.createElement('th');
        cell.innerHTML = `${DAY_NAMES[dayIndex]}<br>${formatDay(date)}`;
        headerRow.appendChild(cell);
    }
    const thead = document.createElement('thead');
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const examsByDate = new Map();
    const allExams = [
        ...(data.written_exams || []).map((exam) => ({
            ...exam,
            kind: 'written',
            start_hour: Number(exam.exam_hour),
            end_hour: Number(exam.exam_hour) + 3,
        })),
        ...(data.oral_exams || []).map((exam) => ({
            ...exam,
            kind: 'oral',
            location: exam.room_name,
            group_names: exam.group_names,
        })),
    ];
    allExams.forEach((exam) => {
        if (!examsByDate.has(exam.exam_date)) examsByDate.set(exam.exam_date, []);
        examsByDate.get(exam.exam_date).push(exam);
    });
    const tbody = document.createElement('tbody');
    for (let hour = FIRST_HOUR; hour < LAST_HOUR; hour += 1) {
        const row = document.createElement('tr');
        const timeCell = document.createElement('th');
        timeCell.textContent = `${String(hour).padStart(2, '0')}:00`;
        row.appendChild(timeCell);
        for (let dayIndex = 0; dayIndex < 7; dayIndex += 1) {
            const date = addDays(currentWeekStart, dayIndex);
            const cell = document.createElement('td');
            cell.dataset.date = formatDate(date);
            cell.dataset.hour = String(hour);
            cell.style.position = 'relative';
            const exams = examsByDate.get(formatDate(date)) || [];
            const startingExams = exams.filter((exam) => Number(exam.start_hour) === hour);
            if (startingExams.length) {
                const maxDuration = Math.max(...startingExams.map((exam) => Number(exam.end_hour) - Number(exam.start_hour)));
                cell.className = 'oral-exam-slot';
            }
            const items = document.createElement('div');
            items.className = 'oral-exam-calendar-items';
            if (startingExams.length) {
                const maxDuration = Math.max(...startingExams.map((exam) => Number(exam.end_hour) - Number(exam.start_hour)));
                items.style.height = `${maxDuration * 100}%`;
                items.style.zIndex = startingExams.some((exam) => exam.kind === 'oral') ? '20' : '2';
            }
            startingExams.forEach((exam) => {
                const item = document.createElement('div');
                const isOwnExam = exam.kind === 'oral'
                    ? Boolean(exam.can_delete)
                    : exam.course_code === data.selected_session?.code;
                item.className = `oral-exam-calendar-item ${exam.kind === 'oral' ? 'oral-exam-calendar-item-oral' : 'oral-exam-calendar-item-written'}${isOwnExam ? ' oral-exam-calendar-item-own' : ''}`;
                item.dataset.durationHours = String(
                    Math.max(1, Number(exam.end_hour) - Number(exam.start_hour)),
                );
                const content = document.createElement('div');
                content.className = 'oral-exam-calendar-item-content';
                const contentRoot = exam.kind === 'written' ? content : item;
                if (exam.kind === 'oral') {
                    if (exam.overlap_percentage !== null && exam.overlap_percentage !== undefined) {
                        const ratio = Math.max(0, Math.min(100, Number(exam.overlap_percentage))) / 100;
                        item.style.opacity = exam.can_delete ? '1' : String(0.1 + 0.9 * ratio);
                    } else {
                        item.style.opacity = '1';
                    }
                } else if (exam.overlap_percentage !== null && exam.overlap_percentage !== undefined) {
                    const ratio = Math.max(0, Math.min(100, Number(exam.overlap_percentage))) / 100;
                    item.style.setProperty('--exam-opacity', String(0.1 + 0.9 * ratio));
                }
                const { topBar, left, right } = createCalendarTopBar();
                contentRoot.appendChild(topBar);
                if (exam.kind === 'oral' && exam.can_delete) {
                    left.appendChild(createCancelButton(
                        () => deleteOralExam(exam.id).catch((error) => setStatus(error.message)),
                        'Откажи усмени испит',
                    ));
                }
                if (exam.kind === 'oral' && exam.can_delete) {
                    right.appendChild(renderCalendarMenu({
                        id: exam.id,
                        start: exam.start_hour,
                        end: exam.end_hour,
                        room: exam.location,
                        description: exam.course_name,
                        calendarTitle: `Усмени испит: ${exam.course_name}`,
                        calendarDescription: `Групе: ${exam.group_names || 'нису одређене'}`,
                        calendarFilePrefix: 'usmeni_ispit',
                    }, exam.exam_date));
                }
                const location = exam.location || 'локација није одређена';
                const details = document.createElement('div');
                details.className = 'oral-exam-calendar-details';
                const title = document.createElement('div');
                title.className = 'oral-exam-calendar-title';
                title.textContent = `${exam.kind === 'oral' ? 'Усмени: ' : ''}${exam.course_name}`;
                details.appendChild(title);

                const locationRow = document.createElement('div');
                locationRow.className = 'oral-exam-calendar-meta oral-exam-room-row';
                if (exam.kind === 'oral' && exam.can_delete && !exam.location) {
                    const reserveLink = document.createElement('a');
                    reserveLink.href = '#';
                    reserveLink.textContent = 'Резервиши салу';
                    reserveLink.addEventListener('click', (event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        reserveRoomForOralExam(exam).catch((error) => setStatus(error.message));
                    });
                    locationRow.appendChild(reserveLink);
                    locationRow.appendChild(createReservationViewButton(exam));
                } else if (exam.kind === 'oral' && exam.reservation_id) {
                    locationRow.append(document.createTextNode(location));
                    locationRow.appendChild(createCancelButton(
                        () => deleteOralReservation(exam.reservation_id)
                            .catch((error) => setStatus(error.message)),
                        'Откажи резервацију',
                    ));
                    locationRow.appendChild(createReservationViewButton(exam));
                } else {
                    locationRow.textContent = location;
                }
                details.appendChild(locationRow);

                if (exam.group_names) {
                    const groupsRow = document.createElement('div');
                    groupsRow.className = 'oral-exam-calendar-meta';
                    groupsRow.textContent = `групе: ${exam.group_names}`;
                    details.appendChild(groupsRow);
                }
                if (exam.kind === 'oral' && !exam.can_delete) {
                    const overlapRow = document.createElement('div');
                    overlapRow.className = 'oral-exam-calendar-meta';
                    overlapRow.textContent = exam.my_student_count === null || exam.my_student_count === undefined
                        ? 'преклапање пријављених: непознато'
                        : `преклапање пријављених: ${exam.my_student_count}/${exam.my_student_total}`;
                    details.appendChild(overlapRow);
                }
                if (exam.kind === 'written') {
                    const studentsRow = document.createElement('div');
                    studentsRow.className = 'oral-exam-calendar-meta';
                    studentsRow.textContent = exam.my_student_count === null || exam.my_student_count === undefined
                        ? 'преклапање пријављених: непознато'
                        : `преклапање пријављених: ${exam.my_student_count}/${exam.my_student_total}`;
                    details.appendChild(studentsRow);
                }
                contentRoot.appendChild(details);
                if (exam.kind === 'written') item.appendChild(content);
                items.appendChild(item);
            });
            if (startingExams.length) cell.appendChild(items);
            if (!startingExams.some((exam) => exam.kind === 'oral')) {
                cell.classList.add('oral-exam-calendar-cell-selectable');
                cell.title = 'Превуците мишем да изаберете термин усменог испита';
            }
            row.appendChild(cell);
        }
        tbody.appendChild(row);
    }
    table.appendChild(tbody);
    calendarRoot.appendChild(table);
    window.requestAnimationFrame(() => expandExamRowsToFitText(tbody));
}

async function refresh({ preserveCourse = false } = {}) {
    const previousSession = preserveCourse ? sessionSelect.value : '';
    setStatus('Учитавање...');
    try {
        const data = await loadData();
        populateSelect(termSelect, data.terms || [], (term) => term.term_code, (term) => term.label);
        if (data.selected_term) termSelect.value = data.selected_term.term_code;
        populateSelect(sessionSelect, data.sessions || [], (session) => session.id, (session) => {
            const groups = session.group_names ? ` · групе: ${session.group_names}` : '';
            return `${session.name}${session.code ? ` (${session.code})` : ''}${groups}`;
        });
        if (previousSession && [...sessionSelect.options].some((option) => option.value === previousSession)) {
            sessionSelect.value = previousSession;
        } else if (data.selected_session) {
            sessionSelect.value = data.selected_session.id;
        }
        renderGroups(data);
        setStatus('');
    } catch (error) {
        setStatus(error.message || 'Грешка при учитавању података.');
    }
}

termSelect.addEventListener('change', () => {
    currentWeekStart = null;
    refresh({ preserveCourse: true });
});
sessionSelect.addEventListener('change', () => {
    currentWeekStart = null;
    refresh();
});
refresh();

/* Copyright (c) 2026 Filip Marić. See LICENCE. */
const BASE_PATH = window.APP_CONFIG?.BASE_PATH || '';

const weekdayLabels = [
    'Понедељак',
    'Уторак',
    'Среда',
    'Четвртак',
    'Петак',
    'Субота',
    'Недеља',
];

function getUrl(endpoint) {
    return `${BASE_PATH}${endpoint}`;
}

function formatSessionType(type) {
    const normalized = String(type || '').trim();
    if (!normalized) {
        return 'непознато';
    }
    const map = {
        п: 'предавања',
        v: 'вежбе',
        в: 'вежбе',
        l: 'лабораторије',
        л: 'лабораторије',
    };
    return map[normalized.toLowerCase()] || normalized;
}

function createSessionTypeNode(type) {
    const label = formatSessionType(type);
    if (label === 'предавања' || label === 'вежбе') {
        const span = document.createElement('span');
        span.className = label === 'предавања' ? 'session-type-lecture' : 'session-type-exercise';
        span.textContent = label;
        return span;
    }
    return document.createTextNode(label);
}

function formatSlotRange(startSlot, endSlot) {
    return `${String(startSlot).padStart(2, '0')}:00 - ${String(endSlot).padStart(2, '0')}:00`;
}

function formatSeasonLabel(value) {
    if (value === 'fall') {
        return 'јесењи';
    }
    if (value === 'spring') {
        return 'пролећни';
    }
    return 'оба';
}

function renderTeacherOption(teacher, selectedId) {
    const option = document.createElement('option');
    option.value = teacher.id;
    option.textContent = teacher.username ? `${teacher.name} (${teacher.username})` : teacher.name;
    if (Number(teacher.id) === Number(selectedId)) {
        option.selected = true;
    }
    return option;
}

function renderWeeklySessions(session) {
    const weekly = document.createElement('ul');
    weekly.className = 'teacher-session-weekly-list';

    if (!session.weekly_sessions.length) {
        const li = document.createElement('li');
        li.textContent = 'Нема уписаних недељних термина.';
        weekly.appendChild(li);
        return weekly;
    }

    session.weekly_sessions.forEach((weeklySession) => {
        const li = document.createElement('li');
        li.textContent = `${weeklySession.day_of_week_label} | сала ${weeklySession.room_name} | ${formatSlotRange(weeklySession.start_slot, weeklySession.end_slot)}`;
        weekly.appendChild(li);
    });

    return weekly;
}

function renderSessions(root, data) {
    root.innerHTML = '';

    const selectedTeacher = data.selected_teacher;
    const academicYear = data.academic_year || '';
    if (!selectedTeacher) {
        const empty = document.createElement('div');
        empty.className = 'attendance-panel teacher-sessions-empty';
        empty.textContent = academicYear
            ? `Нема наставника са часовима у школској ${academicYear}.`
            : 'Нема наставника са часовима у изабраној школској години.';
        root.appendChild(empty);
        return;
    }

    const summary = document.createElement('section');
    summary.className = 'attendance-panel teacher-sessions-summary';

    const title = document.createElement('h2');
    title.textContent = selectedTeacher.username
        ? `${selectedTeacher.name} (${selectedTeacher.username})`
        : selectedTeacher.name;
    summary.appendChild(title);

    const meta = document.createElement('p');
    meta.textContent = `Школска година: ${academicYear || 'непозната'} | Семестар: ${formatSeasonLabel(data.season)} | Број часова: ${data.sessions.length}`;
    summary.appendChild(meta);

    root.appendChild(summary);

    if (!data.sessions.length) {
        const empty = document.createElement('div');
        empty.className = 'attendance-panel teacher-sessions-empty';
        empty.textContent = academicYear
            ? `Овај наставник нема часова у школској ${academicYear}.`
            : 'Овај наставник нема часова у одабраној школској години.';
        root.appendChild(empty);
        return;
    }

    const list = document.createElement('div');
    list.className = 'teacher-sessions-list';

    data.sessions.forEach((session) => {
        const card = document.createElement('article');
        card.className = 'attendance-panel course-card teacher-session-card';

        const heading = document.createElement('h3');
        heading.textContent = session.course_name;
        card.appendChild(heading);

        const metaRow = document.createElement('p');
        if (session.course_code) {
            metaRow.append(`Шифра: ${session.course_code} | `);
        }
        metaRow.append('Тип: ');
        metaRow.append(createSessionTypeNode(session.course_type));
        metaRow.append(` | Семестар: ${session.semester_display_name}`);
        card.appendChild(metaRow);

        if (session.groups.length) {
            const groups = document.createElement('p');
            groups.className = 'teacher-session-groups';
            groups.textContent = `Групе: ${session.groups.join(', ')}`;
            card.appendChild(groups);
        }

        const weeklyTitle = document.createElement('h4');
        weeklyTitle.textContent = 'Недељни термини';
        card.appendChild(weeklyTitle);
        card.appendChild(renderWeeklySessions(session));

        list.appendChild(card);
    });

    root.appendChild(list);
}

async function loadTeacherData(teacherId = null, academicYear = null) {
    const params = new URLSearchParams();
    if (teacherId) {
        params.set('teacher_id', teacherId);
    }
    if (academicYear) {
        params.set('academic_year', academicYear);
    }
    const seasonSelect = document.getElementById('season-select');
    const season = seasonSelect?.value || 'both';
    if (season) {
        params.set('season', season);
    }
    const query = params.toString();
    const response = await fetch(getUrl(`/teacher_sessions_data${query ? `?${query}` : ''}`), {
        credentials: 'same-origin',
    });
    if (!response.ok) {
        throw new Error(`Неуспело учитавање података (${response.status})`);
    }
    return response.json();
}

document.addEventListener('DOMContentLoaded', async () => {
    const academicYearSelect = document.getElementById('academic-year-select');
    const seasonSelect = document.getElementById('season-select');
    const teacherSelect = document.getElementById('teacher-select');
    const root = document.getElementById('teacher-sessions-root');

    async function refresh(
        teacherId = null,
        academicYear = academicYearSelect?.value || null,
        season = seasonSelect?.value || 'both',
    ) {
        root.innerHTML = '';
        const loading = document.createElement('div');
        loading.className = 'attendance-panel teacher-sessions-loading';
        loading.textContent = 'Учитавам наставнике и часове...';
        root.appendChild(loading);

        const params = new URLSearchParams();
        if (teacherId) {
            params.set('teacher_id', teacherId);
        }
        if (academicYear) {
            params.set('academic_year', academicYear);
        }
        if (season) {
            params.set('season', season);
        }
        const response = await fetch(getUrl(`/teacher_sessions_data?${params.toString()}`), {
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(`Неуспело учитавање података (${response.status})`);
        }
        const data = await response.json();

        teacherSelect.innerHTML = '';
        if (!data.teachers.length) {
            teacherSelect.disabled = true;
            const option = document.createElement('option');
            option.textContent = 'Нема наставника';
            option.value = '';
            teacherSelect.appendChild(option);
            renderSessions(root, data);
            return;
        }

        if (academicYearSelect && data.academic_year) {
            academicYearSelect.value = data.academic_year;
        }
        if (seasonSelect && data.season) {
            seasonSelect.value = data.season;
        }
        teacherSelect.disabled = false;
        data.teachers.forEach((teacher) => {
            teacherSelect.appendChild(renderTeacherOption(teacher, data.selected_teacher?.id));
        });

        if (data.selected_teacher) {
            teacherSelect.value = String(data.selected_teacher.id);
        }

        renderSessions(root, data);
    }

    teacherSelect.addEventListener('change', async () => {
        try {
            await refresh(teacherSelect.value, academicYearSelect?.value || null, seasonSelect?.value || 'both');
        } catch (error) {
            root.innerHTML = '';
            const panel = document.createElement('div');
            panel.className = 'attendance-panel teacher-sessions-error';
            panel.textContent = error.data?.error || 'Грешка при учитавању података.';
            root.appendChild(panel);
        }
    });

    if (academicYearSelect) {
        academicYearSelect.addEventListener('change', async () => {
            try {
                await refresh(null, academicYearSelect.value, seasonSelect?.value || 'both');
            } catch (error) {
                root.innerHTML = '';
                const panel = document.createElement('div');
                panel.className = 'attendance-panel teacher-sessions-error';
                panel.textContent = error.data?.error || 'Грешка при учитавању података.';
                root.appendChild(panel);
            }
        });
    }

    if (seasonSelect) {
        seasonSelect.addEventListener('change', async () => {
            try {
                await refresh(teacherSelect.value || null, academicYearSelect?.value || null, seasonSelect.value);
            } catch (error) {
                root.innerHTML = '';
                const panel = document.createElement('div');
                panel.className = 'attendance-panel teacher-sessions-error';
                panel.textContent = error.data?.error || 'Грешка при учитавању података.';
                root.appendChild(panel);
            }
        });
    }

    try {
        await refresh(null, academicYearSelect?.value || null, seasonSelect?.value || 'both');
    } catch (error) {
        root.innerHTML = '';
        const panel = document.createElement('div');
        panel.className = 'attendance-panel teacher-sessions-error';
        panel.textContent = error.data?.error || 'Грешка при учитавању података.';
        root.appendChild(panel);
    }
});

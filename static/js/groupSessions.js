/* Copyright (c) 2026 Filip Marić. See LICENCE. */
const BASE_PATH = window.APP_CONFIG?.BASE_PATH || '';

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
        k: 'практикум',
        v: 'вежбе',
        в: 'вежбе',
        к: 'практикум',
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

function formatLessonCount(value) {
    const count = Number(value || 0);
    return String(count).replace(/\.0$/, '');
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

function renderGroupOption(group, selectedId) {
    const option = document.createElement('option');
    option.value = group.id;
    option.textContent = group.description ? `${group.name} (${group.description})` : group.name;
    if (Number(group.id) === Number(selectedId)) {
        option.selected = true;
    }
    return option;
}

function sessionTypeOrder(type) {
    const normalized = String(type || '').trim().toLowerCase();
    if (normalized === 'п' || normalized === 'p') {
        return 0;
    }
    if (normalized === 'в' || normalized === 'v') {
        return 1;
    }
    if (normalized === 'к' || normalized === 'k') {
        return 2;
    }
    return 3;
}

function groupSessionsByCourse(sessions) {
    const groups = new Map();
    sessions.forEach((session) => {
        const key = session.course_id;
        if (!groups.has(key)) {
            groups.set(key, {
                course_id: key,
                course_name: session.course_name,
                course_code: session.course_code,
                sessions: [],
            });
        }
        groups.get(key).sessions.push(session);
    });

    return [...groups.values()]
        .sort((left, right) => (
            String(left.course_name || '').localeCompare(String(right.course_name || ''), 'sr')
            || String(left.course_code || '').localeCompare(String(right.course_code || ''), 'sr')
        ))
        .map((group) => {
            group.sessions.sort((left, right) => (
                sessionTypeOrder(left.course_type) - sessionTypeOrder(right.course_type)
                || String(left.teacher_name || '').localeCompare(String(right.teacher_name || ''), 'sr')
                || Number(left.course_session_id) - Number(right.course_session_id)
            ));
            return group;
        });
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

    const selectedGroup = data.selected_group;
    const academicYear = data.academic_year || '';
    if (!selectedGroup) {
        const empty = document.createElement('div');
        empty.className = 'attendance-panel group-sessions-empty';
        empty.textContent = academicYear
            ? `Нема групе са часовима у школској ${academicYear}.`
            : 'Нема групе са часовима у изабраној школској години.';
        root.appendChild(empty);
        return;
    }

    const summary = document.createElement('section');
    summary.className = 'attendance-panel teacher-sessions-summary';

    const title = document.createElement('h2');
    title.textContent = selectedGroup.description
        ? `${selectedGroup.name} (${selectedGroup.description})`
        : selectedGroup.name;
    summary.appendChild(title);

    const meta = document.createElement('p');
    meta.textContent = `Школска година: ${academicYear || 'непозната'} | Семестар: ${formatSeasonLabel(data.season)} | Број часова: ${data.sessions.length}`;
    summary.appendChild(meta);

    root.appendChild(summary);

    if (!data.sessions.length) {
        const empty = document.createElement('div');
        empty.className = 'attendance-panel group-sessions-empty';
        empty.textContent = academicYear
            ? `Ова група нема часова у школској ${academicYear}.`
            : 'Ова група нема часова у одабраној школској години.';
        root.appendChild(empty);
        return;
    }

    const list = document.createElement('div');
    list.className = 'teacher-sessions-list';

    groupSessionsByCourse(data.sessions).forEach((courseGroup) => {
        const course = document.createElement('section');
        course.className = 'group-session-course';

        const courseHeading = document.createElement('h3');
        courseHeading.textContent = courseGroup.course_name;
        course.appendChild(courseHeading);

        const activities = document.createElement('div');
        activities.className = 'group-session-activities';

        courseGroup.sessions.forEach((session) => {
        const card = document.createElement('article');
        card.className = 'attendance-panel course-card group-session-card';

        const heading = document.createElement('h4');
        heading.textContent = formatSessionType(session.course_type);
        card.appendChild(heading);

        const metaRow = document.createElement('p');
        if (session.course_code) {
            metaRow.append(`Шифра: ${session.course_code} | `);
        }
        metaRow.append('Тип: ');
        metaRow.append(createSessionTypeNode(session.course_type));
        metaRow.append(` | Недељно часова: ${formatLessonCount(session.weekly_lesson_count)}`);
        metaRow.append(` | Семестар: ${session.semester_display_name} | Наставник: ${session.teacher_name}`);
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

        activities.appendChild(card);
        });

        course.appendChild(activities);
        list.appendChild(course);
    });

    root.appendChild(list);
}

async function loadGroupData(groupId = null, academicYear = null, season = 'both') {
    const params = new URLSearchParams();
    if (groupId) {
        params.set('group_id', groupId);
    }
    if (academicYear) {
        params.set('academic_year', academicYear);
    }
    if (season) {
        params.set('season', season);
    }
    const query = params.toString();
    const response = await fetch(getUrl(`/group_sessions_data${query ? `?${query}` : ''}`), {
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
    const groupSelect = document.getElementById('group-select');
    const root = document.getElementById('group-sessions-root');

    async function refresh(
        groupId = null,
        academicYear = academicYearSelect?.value || null,
        season = seasonSelect?.value || 'both',
    ) {
        root.innerHTML = '';
        const loading = document.createElement('div');
        loading.className = 'attendance-panel group-sessions-loading';
        loading.textContent = 'Учитавам групе и часове...';
        root.appendChild(loading);

        const data = await loadGroupData(groupId, academicYear, season);

        groupSelect.innerHTML = '';
        if (!data.groups.length) {
            groupSelect.disabled = true;
            const option = document.createElement('option');
            option.textContent = 'Нема група';
            option.value = '';
            groupSelect.appendChild(option);
            renderSessions(root, data);
            return;
        }

        if (academicYearSelect && data.academic_year) {
            academicYearSelect.value = data.academic_year;
        }
        if (seasonSelect && data.season) {
            seasonSelect.value = data.season;
        }
        groupSelect.disabled = false;
        data.groups.forEach((group) => {
            groupSelect.appendChild(renderGroupOption(group, data.selected_group?.id));
        });

        if (data.selected_group) {
            groupSelect.value = String(data.selected_group.id);
        }

        renderSessions(root, data);
    }

    groupSelect.addEventListener('change', async () => {
        try {
            await refresh(groupSelect.value, academicYearSelect?.value || null, seasonSelect?.value || 'both');
        } catch (error) {
            root.innerHTML = '';
            const panel = document.createElement('div');
            panel.className = 'attendance-panel group-sessions-error';
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
                panel.className = 'attendance-panel group-sessions-error';
                panel.textContent = error.data?.error || 'Грешка при учитавању података.';
                root.appendChild(panel);
            }
        });
    }

    if (seasonSelect) {
        seasonSelect.addEventListener('change', async () => {
            try {
                await refresh(groupSelect.value || null, academicYearSelect?.value || null, seasonSelect.value);
            } catch (error) {
                root.innerHTML = '';
                const panel = document.createElement('div');
                panel.className = 'attendance-panel group-sessions-error';
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
        panel.className = 'attendance-panel group-sessions-error';
        panel.textContent = error.data?.error || 'Грешка при учитавању података.';
        root.appendChild(panel);
    }
});

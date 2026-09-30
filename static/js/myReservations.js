/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { API } from './api.js';
import { formatDateDDMMYYYY } from './util.js';

const DAY_NAMES = [
    'понедељак',
    'уторак',
    'среда',
    'четвртак',
    'петак',
    'субота',
    'недеља',
];

function formatCourseType(type) {
    const normalized = String(type || '').toLowerCase();
    const labels = {
        p: 'предавања',
        v: 'вежбе',
        k: 'колоквијум',
    };
    return labels[normalized] || type || '';
}

function formatHourRange(start, end) {
    const pad = (value) => String(value).padStart(2, '0');
    return `${pad(start)}:00 - ${pad(end)}:00`;
}

function buildMainTimetableUrl(date, roomId = null, hour = null) {
    const basePath = window.APP_CONFIG?.BASE_PATH || '';
    const params = new URLSearchParams({ date });
    if (roomId !== null && roomId !== undefined && hour !== null && hour !== undefined) {
        params.set('room_id', String(roomId));
        params.set('hour', String(hour));
    }
    return `${basePath}/?${params.toString()}`;
}

function formatSemesterLabel(semester) {
    return `${semester.display_name} (${formatDateDDMMYYYY(semester.start_date)} - ${formatDateDDMMYYYY(semester.end_date)})`;
}

function clearNode(node) {
    node.textContent = '';
}

function escapeCsvValue(value) {
    const text = String(value ?? '');
    if (/[",\n;]/.test(text)) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function buildAttendanceSummaryCsv(summaryEntries) {
    const rows = [
        ['Име и презиме', 'Индекс', 'Број присустава', 'Извор', 'IP адреса'],
        ...summaryEntries.map((entry) => [
            entry.student_name || 'Непознато',
            entry.student_index || '',
            entry.count,
            entry.registration_source || '',
            entry.client_ip || '',
        ]),
    ];
    return '\ufeff' + rows.map((row) => row.map(escapeCsvValue).join(';')).join('\n');
}

function downloadTextFile(filename, content, mimeType = 'text/csv;charset=utf-8') {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function createAttendanceDownloadButton(date, students) {
    const link = document.createElement('a');
    link.href = '#';
    link.className = 'attendance-download-btn';
    link.textContent = 'Преузми CSV';
    link.addEventListener('click', (event) => {
        event.preventDefault();
        const csv = buildAttendanceSummaryCsv(
            students.map((student) => ({
                student_name: student.student_name,
                student_index: student.student_index,
                count: 1,
                registration_source: student.registration_source || '',
                client_ip: student.client_ip || '',
            })),
        );
        const safeDate = String(date).replace(/[^0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'datum';
        downloadTextFile(`prisustvo_${safeDate}.csv`, csv);
    });
    return link;
}

function renderEmptyMessage(container, message) {
    clearNode(container);
    const p = document.createElement('p');
    p.textContent = message;
    container.appendChild(p);
}

function createAttendanceListItem(student) {
    const li = document.createElement('li');
    const label = document.createElement('span');
    label.textContent = student.student_label || 'Непознато';
    li.appendChild(label);

    const source = document.createElement('span');
    const normalizedSource = String(student.registration_source || '').toLowerCase() === 'android' ? 'android' : 'web';
    source.className = `attendance-source-badge attendance-source-${normalizedSource}`;
    source.textContent = normalizedSource;
    li.appendChild(source);
    return li;
}

function ensureAttendanceDialog() {
    let dialog = document.getElementById('attendance-dialog');
    if (dialog) {
        return dialog;
    }

    dialog = document.createElement('dialog');
    dialog.id = 'attendance-dialog';
    dialog.className = 'attendance-dialog';

    const header = document.createElement('div');
    header.className = 'attendance-dialog-header';

    const titleWrap = document.createElement('div');
    titleWrap.className = 'attendance-dialog-title-wrap';

    const title = document.createElement('h3');
    title.id = 'attendance-dialog-title';
    titleWrap.appendChild(title);

    const subtitle = document.createElement('p');
    subtitle.id = 'attendance-dialog-subtitle';
    subtitle.className = 'attendance-dialog-subtitle';
    titleWrap.appendChild(subtitle);

    header.appendChild(titleWrap);

    const actions = document.createElement('div');
    actions.className = 'attendance-dialog-actions';

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'attendance-dialog-close';
    closeButton.textContent = '×';
    closeButton.setAttribute('aria-label', 'Затвори');
    closeButton.title = 'Затвори';
    closeButton.addEventListener('click', () => dialog.close());
    actions.appendChild(closeButton);

    header.appendChild(actions);

    const body = document.createElement('div');
    body.id = 'attendance-dialog-body';
    body.className = 'attendance-dialog-body';

    const content = document.createElement('div');
    content.id = 'attendance-dialog-content';
    body.appendChild(content);

    const downloadButton = document.createElement('a');
    downloadButton.href = '#';
    downloadButton.className = 'attendance-dialog-download';
    downloadButton.textContent = 'Преузми CSV';
    downloadButton.hidden = true;
    body.appendChild(downloadButton);

    dialog.appendChild(header);
    dialog.appendChild(body);
    document.body.appendChild(dialog);
    return dialog;
}

function openAttendanceDialog(date, students) {
    const dialog = ensureAttendanceDialog();
    const title = dialog.querySelector('#attendance-dialog-title');
    const subtitle = dialog.querySelector('#attendance-dialog-subtitle');
    const body = dialog.querySelector('#attendance-dialog-content');
    const downloadButton = dialog.querySelector('.attendance-dialog-download');

    title.textContent = `Присутност за ${formatDateDDMMYYYY(date)}`;
    subtitle.textContent = '';
    downloadButton.hidden = students.length === 0;
    downloadButton.style.display = students.length ? 'block' : 'none';
    if (students.length > 0) {
        downloadButton.textContent = 'Преузми CSV';
        downloadButton.onclick = (event) => {
            event.preventDefault();
            const csv = buildAttendanceSummaryCsv(
                    students.map((student) => ({
                        student_name: student.student_name,
                        student_index: student.student_index,
                        count: 1,
                        registration_source: student.registration_source || '',
                        client_ip: student.client_ip || '',
                    }))
                );
            const safeDate = String(date).replace(/[^0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'datum';
            downloadTextFile(`prisustvo_${safeDate}.csv`, csv);
        };
    } else {
        downloadButton.onclick = null;
    }
    clearNode(body);

    if (!students.length) {
        const p = document.createElement('p');
        p.textContent = 'Нема пријављених студената.';
        body.appendChild(p);
    } else {
        const list = document.createElement('ol');
        students.forEach((student) => {
            list.appendChild(createAttendanceListItem(student));
        });
        body.appendChild(list);
    }

    if (typeof dialog.showModal === 'function') {
        dialog.showModal();
    } else {
        dialog.setAttribute('open', 'open');
    }
}

function openAttendanceSummaryDialog(courseLabel, sessionLabel, summaryEntries) {
    const dialog = ensureAttendanceDialog();
    const title = dialog.querySelector('#attendance-dialog-title');
    const subtitle = dialog.querySelector('#attendance-dialog-subtitle');
    const body = dialog.querySelector('#attendance-dialog-content');
    const downloadButton = dialog.querySelector('.attendance-dialog-download');

    title.textContent = 'Сажетак присуства';
    subtitle.textContent = `${courseLabel} - ${sessionLabel}`;
    downloadButton.hidden = summaryEntries.length === 0;
    downloadButton.style.display = summaryEntries.length ? 'block' : 'none';
    if (summaryEntries.length > 0) {
        downloadButton.onclick = (event) => {
            event.preventDefault();
            const csv = buildAttendanceSummaryCsv(summaryEntries);
            const safeCourse = courseLabel.replace(/[^\p{L}\p{N}]+/gu, '_').replace(/^_+|_+$/g, '') || 'kurs';
            const safeSession = sessionLabel.replace(/[^\p{L}\p{N}]+/gu, '_').replace(/^_+|_+$/g, '') || 'termin';
            downloadTextFile(`sazetak_prisustva_${safeCourse}_${safeSession}.csv`, csv);
        };
    } else {
        downloadButton.onclick = null;
    }
    clearNode(body);

    if (!summaryEntries.length) {
        const p = document.createElement('p');
        p.textContent = 'Нема студената који су присуствовали бар једном термину.';
        body.appendChild(p);
    } else {
        const table = document.createElement('table');
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        ['Име и презиме', 'Индекс', 'Број присустава'].forEach((label) => {
            const th = document.createElement('th');
            th.textContent = label;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        summaryEntries.forEach((entry) => {
            const tr = document.createElement('tr');
            [
                entry.student_name || 'Непознато',
                entry.student_index || '',
                entry.count,
            ].forEach((value) => {
                const td = document.createElement('td');
                td.textContent = String(value);
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        body.appendChild(table);
    }

    if (typeof dialog.showModal === 'function') {
        dialog.showModal();
    } else {
        dialog.setAttribute('open', 'open');
    }
}

function renderPersonalReservations(container, reservations) {
    if (!reservations.length) {
        renderEmptyMessage(container, 'Нема личних резервација у изабраном семестру.');
        return;
    }

    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const headerRow = document.createElement('tr');
    ['Датум', 'Сала', 'Време', 'Опис'].forEach((label) => {
        const th = document.createElement('th');
        th.textContent = label;
        headerRow.appendChild(th);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    reservations.forEach((reservation) => {
        const tr = document.createElement('tr');

        const cells = [
            {
                value: formatDateDDMMYYYY(reservation.date),
                href: buildMainTimetableUrl(reservation.date, reservation.room_id, reservation.start_slot),
                className: 'reservation-date-link',
            },
            reservation.room_name,
            formatHourRange(reservation.start_slot, reservation.end_slot),
            reservation.description || '',
        ];

        cells.forEach((value, index) => {
            const td = document.createElement('td');
            if (index === 0) {
                const link = document.createElement('a');
                link.href = value.href;
                link.className = value.className || '';
                link.textContent = value.value;
                td.appendChild(link);
            } else {
                td.textContent = value;
            }
            tr.appendChild(td);
        });

        tbody.appendChild(tr);
    });
    table.appendChild(tbody);

    clearNode(container);
    container.appendChild(table);
}

async function renderPersonalAttendanceSummary(container, reservations) {
    const summary = document.createElement('section');
    summary.className = 'attendance-summary';

    const list = document.createElement('ul');
    list.className = 'attendance-summary-list';

    const entries = await Promise.all(reservations.map(async (reservation) => {
        const data = await API.getAttendanceRoster('reservation', reservation.id, reservation.date);
        return {
            reservation,
            students: data.students || [],
        };
    }));

    entries.forEach((entry) => {
        const item = document.createElement('li');
        item.className = 'attendance-summary-item';

        const dateLabel = document.createElement('span');
        dateLabel.className = 'attendance-summary-date';
        const dateLink = document.createElement('a');
        dateLink.href = buildMainTimetableUrl(entry.reservation.date, entry.reservation.room_id, entry.reservation.start_slot);
        dateLink.className = 'attendance-date-link';
        dateLink.textContent = formatDateDDMMYYYY(entry.reservation.date);
        dateLabel.appendChild(dateLink);
        item.appendChild(dateLabel);

        const roomLabel = document.createElement('span');
        roomLabel.className = 'attendance-summary-room';
        roomLabel.textContent = entry.reservation.room_name;
        item.appendChild(roomLabel);

        const countLabel = document.createElement('span');
        countLabel.className = 'attendance-summary-count';
        countLabel.textContent = `${entry.students.length} присутних`;
        item.appendChild(countLabel);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'attendance-summary-btn';
        button.textContent = 'Погледај све';
        button.addEventListener('click', () => openAttendanceDialog(entry.reservation.date, entry.students));
        item.appendChild(button);

        list.appendChild(item);
    });

    summary.appendChild(list);
    return summary;
}

async function renderPersonalAttendanceByTerm(reservations) {
    const summary = document.createElement('section');
    summary.className = 'attendance-summary';

    const list = document.createElement('div');
    list.className = 'attendance-summary-list';
    summary.appendChild(list);

    const entries = reservations.map((reservation) => {
        const details = document.createElement('details');
        details.className = 'attendance-collapsible attendance-summary-details';

        const detailsSummary = document.createElement('summary');
        const label = document.createElement('span');
        label.textContent = formatDateDDMMYYYY(reservation.date)
            + ' · ' + reservation.room_name;
        detailsSummary.appendChild(label);

        const count = document.createElement('span');
        count.className = 'attendance-summary-count';
        count.textContent = '(' + reservation.attendance_count + ' присутних)';
        detailsSummary.appendChild(count);
        details.appendChild(detailsSummary);

        const content = document.createElement('div');
        details.appendChild(content);

        let loaded = false;
        details.addEventListener('toggle', async () => {
            if (!details.open || loaded) return;
            loaded = true;
            content.textContent = 'Учитавање присуства...';
            try {
                const data = await API.getAttendanceRoster(
                    'reservation',
                    reservation.id,
                    reservation.date,
                );
                clearNode(content);
                if (!data.students.length) {
                    content.textContent = 'Нема регистрованих студената.';
                    return;
                }

                const students = document.createElement('ul');
                students.className = 'attendance-summary-list';
                data.students.forEach((student) => {
                    students.appendChild(createAttendanceListItem(student));
                });
                content.appendChild(students);
                content.appendChild(createAttendanceDownloadButton(reservation.date, data.students));
            } catch (error) {
                loaded = false;
                content.textContent = error.data?.error || 'Грешка при учитавању присуства.';
            }
        });

        return { details, count, reservation };
    });

    entries.forEach((entry) => list.appendChild(entry.details));
    return summary;
}

function createLazyAttendanceTerm(kind, eventId, date, roomId, startSlot, studentCount) {
    const details = document.createElement('details');
    details.className = 'attendance-collapsible attendance-summary-details';

    const summary = document.createElement('summary');
    const label = document.createElement('span');
    label.textContent = formatDateDDMMYYYY(date);
    summary.appendChild(label);

    const count = document.createElement('span');
    count.className = 'attendance-summary-count';
    count.textContent = '(' + studentCount + ' присутних)';
    summary.appendChild(count);
    details.appendChild(summary);

    const content = document.createElement('div');
    details.appendChild(content);

    let loaded = false;
    details.addEventListener('toggle', async () => {
        if (!details.open || loaded) return;
        loaded = true;
        content.textContent = 'Учитавање присуства...';
        try {
            const data = await API.getAttendanceRoster(kind, eventId, date);
            clearNode(content);
            if (!data.students.length) {
                content.textContent = 'Нема регистрованих студената.';
                return;
            }

            const students = document.createElement('ul');
            students.className = 'attendance-summary-list';
            data.students.forEach((student) => {
                students.appendChild(createAttendanceListItem(student));
            });
            content.appendChild(students);
            content.appendChild(createAttendanceDownloadButton(date, data.students));
        } catch (error) {
            loaded = false;
                content.textContent = error.data?.error || 'Грешка при учитавању присуства.';
        }
    });
    return details;
}

function renderCourseAttendance(course) {
    const container = document.createElement('div');
    const courseLabel = course.course_name;

    course.sessions.forEach((session) => {
        const block = document.createElement('section');
        block.className = 'attendance-session-block';

        const sessionLabel = [
            DAY_NAMES[session.day_of_week] || '',
            formatHourRange(session.start_slot, session.end_slot),
            session.room_name,
            formatCourseType(session.course_type),
        ].filter(Boolean).join(' · ');

        const heading = document.createElement('h4');
        heading.textContent = sessionLabel;
        block.appendChild(heading);

        const summaryLink = document.createElement('a');
        summaryLink.href = '#';
        summaryLink.className = 'attendance-summary-btn';
        summaryLink.textContent = 'Сажетак присуства';
        summaryLink.addEventListener('click', async (event) => {
            event.preventDefault();
            if (summaryLink.dataset.loading) return;
            summaryLink.dataset.loading = 'true';
            try {
                const data = await API.getAttendanceSummary(
                    'weekly',
                    session.weekly_session_id,
                    session.instances || [],
                );
                openAttendanceSummaryDialog(
                    courseLabel,
                    sessionLabel,
                    data.students || [],
                );
            } finally {
                delete summaryLink.dataset.loading;
            }
        });
        block.appendChild(summaryLink);

        const list = document.createElement('div');
        list.className = 'attendance-summary-list';
        (session.instances || []).forEach((date) => {
            list.appendChild(createLazyAttendanceTerm(
                'weekly',
                session.weekly_session_id,
                date,
                session.room_id,
                session.start_slot,
                (session.attendance_counts || {})[date] || 0,
            ));
        });
        block.appendChild(list);
        container.appendChild(block);
    });
    return container;
}

function renderCourseOverview(container, courses, semesterId) {
    clearNode(container);
    if (!courses.length) {
        renderEmptyMessage(container, 'Нема предмета у изабраном семестру.');
        return;
    }

    courses.forEach((course) => {
        const card = document.createElement('article');
        card.className = 'course-card';

        const title = document.createElement('h3');
        title.textContent = course.course_name;
        card.appendChild(title);

        const table = document.createElement('table');
        const headerRow = document.createElement('tr');
        ['Дан', 'Сала', 'Време', 'Тип', 'Наставник', 'Групе'].forEach((label) => {
            const th = document.createElement('th');
            th.textContent = label;
            headerRow.appendChild(th);
        });
        const thead = document.createElement('thead');
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        course.sessions.forEach((session) => {
            const row = document.createElement('tr');
            [
                DAY_NAMES[session.day_of_week] || '',
                session.room_name,
                formatHourRange(session.start_slot, session.end_slot),
                formatCourseType(session.course_type),
                session.teacher_name,
                session.groups.length ? session.groups.join(', ') : '',
            ].forEach((value) => {
                const cell = document.createElement('td');
                cell.textContent = value;
                row.appendChild(cell);
            });
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        card.appendChild(table);

        card.appendChild(createLazyAttendanceLoader('Присутност по термину', async () => {
            const data = await API.getMyCourseAttendance(semesterId, course.course_id);
            const detailedCourse = (data.courses || []).find(
                (item) => item.course_id === course.course_id,
            );
            return renderCourseAttendance(detailedCourse || course);
        }));
        container.appendChild(card);
    });
}

async function renderCourseSessions(container, courses) {
    if (!courses.length) {
        renderEmptyMessage(container, 'Нема предмета у изабраном семестру.');
        return;
    }

    clearNode(container);

    for (const course of courses) {
        const card = document.createElement('article');
        card.className = 'course-card';

        const title = document.createElement('h3');
        title.textContent = course.course_name;
        card.appendChild(title);

        const table = document.createElement('table');
        const thead = document.createElement('thead');
        const headerRow = document.createElement('tr');
        ['Дан', 'Сала', 'Време', 'Тип', 'Наставник', 'Групе'].forEach((label) => {
            const th = document.createElement('th');
            th.textContent = label;
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        course.sessions.forEach((session) => {
            const tr = document.createElement('tr');
            const cells = [
                DAY_NAMES[session.day_of_week] || '',
                session.room_name,
                formatHourRange(session.start_slot, session.end_slot),
                formatCourseType(session.course_type),
                session.teacher_name,
                session.groups.length ? session.groups.join(', ') : '',
            ];

            cells.forEach((value) => {
                const td = document.createElement('td');
                td.textContent = value;
                tr.appendChild(td);
            });

            tbody.appendChild(tr);
        });

        table.appendChild(tbody);
        card.appendChild(table);

        const details = document.createElement('details');
        details.className = 'attendance-collapsible attendance-summary';

        const summaryTitle = document.createElement('summary');
        details.appendChild(summaryTitle);

        const courseLabel = course.course_name;

        const sessionBlocks = course.sessions.map((session) => {
            const block = document.createElement('section');
            block.className = 'attendance-session-block';

            const heading = document.createElement('h4');
            const sessionLabel = [
                DAY_NAMES[session.day_of_week] || '',
                formatHourRange(session.start_slot, session.end_slot),
                session.room_name,
                formatCourseType(session.course_type),
            ].filter(Boolean).join(' · ');
            heading.textContent = sessionLabel;
            block.appendChild(heading);

            const instances = session.instances || [];
            let attendanceLoading = null;

            const actions = document.createElement('div');
            actions.className = 'attendance-session-actions';

            const summaryButton = document.createElement('button');
            summaryButton.type = 'button';
            summaryButton.className = 'attendance-summary-btn';
            summaryButton.textContent = 'Сажетак присуства';
            summaryButton.addEventListener('click', async () => {
                if (!attendanceLoading) {
                    attendanceLoading = API.getAttendanceSummary(
                        'weekly',
                        session.weekly_session_id,
                        instances,
                    ).then((data) => data.students || []);
                }
                summaryButton.disabled = true;
                try {
                    const summaryEntries = await attendanceLoading;
                    openAttendanceSummaryDialog(courseLabel, sessionLabel, summaryEntries);
                } finally {
                    summaryButton.disabled = false;
                }
            });
            actions.appendChild(summaryButton);
            block.appendChild(actions);

            if (!instances.length) {
                const empty = document.createElement('p');
                empty.textContent = 'Нема одржаних термина у изабраном семестру.';
                block.appendChild(empty);
                return block;
            }

            const list = document.createElement('ul');
            list.className = 'attendance-summary-list';
            block.appendChild(list);

            instances.forEach((date) => {
                const item = document.createElement('li');
                item.className = 'attendance-summary-item';
                item.appendChild(createLazyAttendanceTerm(
                    'weekly',
                    session.weekly_session_id,
                    date,
                    session.room_id,
                    session.start_slot,
                    (session.attendance_counts || {})[date] || 0,
                ));
                list.appendChild(item);
            });

            return block;
        });

        if (!sessionBlocks.length) {
            const empty = document.createElement('p');
            empty.textContent = 'Нема одржаних термина у изабраном семестру.';
            details.appendChild(empty);
        } else {
            sessionBlocks.forEach((block) => details.appendChild(block));
        }

        details.querySelector('summary').textContent = 'Присутност по термину';
        card.appendChild(details);
        container.appendChild(card);
    }
}

function createLazyAttendanceLoader(label, loadContent) {
    const shell = document.createElement('details');
    shell.className = 'attendance-collapsible attendance-summary';

    const summary = document.createElement('summary');
    summary.textContent = label;
    shell.appendChild(summary);

    const content = document.createElement('div');
    shell.appendChild(content);

    let loaded = false;
    shell.addEventListener('toggle', async () => {
        if (!shell.open || loaded) return;
        loaded = true;
        content.textContent = 'Учитавање...';
        try {
            const replacement = await loadContent();
            clearNode(content);
            content.appendChild(replacement);
        } catch (error) {
            loaded = false;
            clearNode(content);
            const errorMessage = document.createElement('span');
        errorMessage.textContent = error.data?.error || 'Грешка при учитавању података.';
            content.appendChild(errorMessage);
        }
    });
    return shell;
}

function createLazyPersonalAttendanceSummary(reservations, semesterId) {
    return createLazyAttendanceLoader('Присутност по личној резервацији', async () => {
        const data = await API.getMyReservationsAttendance(semesterId);
        const counts = new Map(
            (data.personal_reservations || []).map((item) => [
                item.id,
                item.attendance_count,
            ]),
        );
        return renderPersonalAttendanceByTerm(
            reservations.map((reservation) => ({
                ...reservation,
                attendance_count: counts.get(reservation.id) || 0,
            })),
        );
    });
}

function createLazyCourseSessions(courses) {
    if (!courses.length) {
        const empty = document.createElement('div');
        renderEmptyMessage(empty, 'Нема предмета у изабраном семестру.');
        return empty;
    }
    return createLazyAttendanceLoader('Прикажи термине и присуство', async () => {
        const content = document.createElement('div');
        await renderCourseSessions(content, courses);
        return content;
    });
}

function populateSemesterSelect(select, semesters, selectedId) {
    clearNode(select);
    semesters.forEach((semester) => {
        const option = document.createElement('option');
        option.value = semester.id;
        option.textContent = formatSemesterLabel(semester);
        if (Number(semester.id) === Number(selectedId)) {
            option.selected = true;
        }
        select.appendChild(option);
    });
}

async function loadReservations(selectedSemesterId = null) {
    const data = await API.getMyReservations(selectedSemesterId);
    const select = document.getElementById('semester-select');
    const personalContainer = document.getElementById('personal-reservations');
    const courseContainer = document.getElementById('course-reservations');

    populateSemesterSelect(
        select,
        data.semesters || [],
        data.selected_semester ? data.selected_semester.id : null,
    );

    if (data.selected_semester) {
        document.getElementById('page-message').textContent = `Преглед за семестар: ${data.selected_semester.display_name}`;
    } else {
        document.getElementById('page-message').textContent = 'Нема доступних семестара.';
    }

    renderPersonalReservations(personalContainer, data.personal_reservations || []);
    const oldPersonalSummary = document.getElementById('personal-attendance-summary');
    if (oldPersonalSummary) {
        oldPersonalSummary.remove();
    }
    if ((data.personal_reservations || []).length) {
        const summary = createLazyPersonalAttendanceSummary(
            data.personal_reservations || [],
            data.selected_semester ? data.selected_semester.id : null,
        );
        summary.id = 'personal-attendance-summary';
        personalContainer.parentElement.appendChild(summary);
    }
    clearNode(courseContainer);
    renderCourseOverview(
        courseContainer,
        data.courses || [],
        data.selected_semester ? data.selected_semester.id : null,
    );
}

const App = {
    async init() {
        const me = await API.me();
        if (!me.logged_in) {
            document.getElementById('page-message').textContent = 'Морате бити пријављени да бисте видели своје резервације.';
            document.getElementById('reservations-page').style.display = 'none';
            return;
        }

        document.getElementById('reservations-page').style.display = 'block';

        const select = document.getElementById('semester-select');
        select.addEventListener('change', async () => {
            await loadReservations(select.value);
        });

        await loadReservations();
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());

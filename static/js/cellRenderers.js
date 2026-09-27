/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { formatApiDate } from './util.js';

function formatLectureType(type) {
    const normalized = String(type || '').toLowerCase();
    const labels = {
        p: 'предавања',
        v: 'вежбе',
        k: 'колоквијум',
        o: 'остало',
        п: 'предавања',
        в: 'вежбе',
        к: 'колоквијум',
        о: 'остало',
    };
    return labels[normalized] || type || '';
}

function lectureTypeClass(type) {
    const normalized = String(type || '').toLowerCase();
    return {
        п: 'p',
        в: 'v',
        к: 'k',
        о: 'o',
    }[normalized] || normalized;
}

// Helper function in cellRenderers.js that removes duplication
function getWeeklyHTML(cellData) {
    const canceledLabel = cellData.canceled ? " (отказано)" : "";
    return `
        <span class='room'>${cellData.room}</span> <br />
        <span>${cellData.teacher}</span> <br />
        <span class='${lectureTypeClass(cellData.lecture_type)}'>${cellData.lecture_name}${canceledLabel}</span> <br />
        <span>${cellData.groups.join(", ")}</span>
    `;
}

// Helper function that creates or extends sensors that enable mouse-based
// reservations (drag & drop) within canceled time slots
export function attachDragSensor(td, ctx, hour) {
    // If the container does not already exist in the context (first hour of the slot), create it
    if (!ctx.sensorContainer) {
        ctx.sensorContainer = document.createElement("div");
        ctx.sensorContainer.classList.add("sensor-container");
        td.appendChild(ctx.sensorContainer);
    }

    // Create a sensor for the current hour
    const sensor = document.createElement("div");
    sensor.className = "drag-sensor empty-slot";
    sensor.dataset.hour = hour;
    sensor.dataset.room_id = ctx.room_id;

    ctx.sensorContainer.appendChild(sensor);
}

function renderCancelBtn(container, cellUsername, ctx, onAction) {
    if (cellUsername === ctx.user || ctx.isAdmin) {
        const btn = document.createElement("button");
        btn.className = "res-cancel-btn";
        btn.textContent = "×";
        btn.onclick = (e) => {
            e.stopPropagation();
            onAction();
        };
        container.appendChild(btn);
        return btn;
    }
    return null;
}

function renderAttendanceBtn(ownerUsername, ctx, onAction) {
    if (!ctx.user || ownerUsername !== ctx.user) {
        return null;
    }
    const btn = document.createElement("button");
    btn.className = "attendance-btn";
    btn.textContent = "▣";
    btn.title = "QR код за присуство";
    btn.onclick = (e) => {
        e.stopPropagation();
        onAction();
    };
    return btn;
}

function createTopBar() {
    const topBar = document.createElement("div");
    topBar.className = "res-top-bar";

    const left = document.createElement("div");
    left.className = "res-top-bar-left";

    const right = document.createElement("div");
    right.className = "res-top-bar-right";

    topBar.append(left, right);
    return { topBar, left, right };
}

// Helper for the calendar (within this file)
function renderCalendarMenu(cellData, fullDate) {
	// Prepare data
	const startTime = formatApiDate(fullDate, cellData.start);
	const endTime = formatApiDate(fullDate, cellData.end);
	const title = cellData.description;
	const description = `Корисник: ${cellData.username}, Сала: ${cellData.room}, Опис: ${cellData.description}`;

	// Create the main wrapper (dropdown)
	const dropdown = document.createElement('div');
	dropdown.className = 'calendar-dropdown';

	// Create the button
	const btn = document.createElement('button');
	btn.className = 'cal-btn';
	btn.innerHTML = '📅';

	// Create the menu
	const menu = document.createElement('div');
	menu.className = 'cal-menu';

	// Google Calendar link
	const googleUrl = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(title)}&dates=${startTime}/${endTime}&details=${encodeURIComponent(description)}&location=${encodeURIComponent('MatF, сала ' + cellData.room)}`;
	const googleLink = document.createElement('a');
	googleLink.href = googleUrl;
	googleLink.target = '_blank';
	googleLink.innerText = 'Google Calendar';

	// ICS download link
	const icsContent = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            `DTSTART:${startTime}`,
            `DTEND:${endTime}`,
            `SUMMARY:${title}`,
            `DESCRIPTION:${description}`,
            `LOCATION:Сала ${cellData.room}`,
            "END:VEVENT",
            "END:VCALENDAR"
	].join("\n");

	const icsBlob = new Blob([icsContent], { type: 'text/calendar' });
	const icsUrl = URL.createObjectURL(icsBlob);
	const icsLink = document.createElement('a');
	icsLink.href = icsUrl;
	icsLink.download = `rezervacija_${cellData.id}.ics`;
	icsLink.innerText = 'Outlook / Apple (.ics)';

	// Assemble the elements
	menu.appendChild(googleLink);
	menu.appendChild(icsLink);
	dropdown.appendChild(btn);
	dropdown.appendChild(menu);

	return dropdown;
}

// Object that contains functions for creating the content of different cell types
export const CellRenderers = {
    // reservation cells
    reservation: (cellData, date, hour, td, ctx) => {
        td.classList.add("reservation");

	// My classes should be displayed a bit differently
	if (cellData.username === ctx.user)
	    td.classList.add("my");

        const card = document.createElement("div");
        card.className = "res-card";

        const { topBar, left, right } = createTopBar();

        // cancel button (if the user has permissions and the reservation is still cancelable)
        if (cellData.can_cancel !== false) {
            renderCancelBtn(left, cellData.username, ctx, () => ctx.onDelete(cellData.id));
        }

        // QR attendance button only during the class
        if (cellData.attendance_open !== false) {
            const attendanceBtn = renderAttendanceBtn(cellData.username, ctx, () =>
                ctx.onOpenAttendance("reservation", cellData.id, date)
            );
            if (attendanceBtn) {
                right.appendChild(attendanceBtn);
            }
        }

        // dugme za integraciju sa kalendarima
        const calMenu = renderCalendarMenu(cellData, date);
        right.appendChild(calMenu);

	// reservation description
        // Keep only the part before '@' if this is an email address
        const username = cellData.username.split('@')[0];
        const info = document.createElement("div");
        info.className = "res-info";
        info.innerHTML = `
            <span class="room">${cellData.room}</span>
            <span class="res-user">(${username})</span>
            <div class="res-desc">${cellData.description}</div>
        `;

        card.append(topBar, info);
        td.appendChild(card);
    },

    // cells with classes from the weekly schedule
    weekly: (cellData, date, hour, td, ctx) => {
        td.classList.add("weekly");
	td.innerHTML = "";

        const card = document.createElement("div");
	card.className = "res-card cell-content"; 
	// My classes should be displayed a bit differently
	if (cellData.teacher_username === ctx.user)
	    td.classList.add("my");

        // The top bar contains controls - cancel button, calendar
        const { topBar, left, right } = createTopBar();

        // cancel/restore class button
        const btn = renderCancelBtn(left, cellData.teacher_username, ctx, () => 
            ctx.onToggleWeekly(cellData.weekly_session_id, date)
        );

        // calendar integration (only if the class is not canceled)
        if (!cellData.canceled) {
            // Map the weekly data into the format expected by renderCalendarMenu
            const calData = {
                id: cellData.weekly_session_id,
                description: `${cellData.lecture_name} (${cellData.teacher})`,
                username: cellData.teacher_username,
                room: ctx.room,
                start: cellData.start,
                end: cellData.end
            };
            if (cellData.attendance_open !== false) {
                const attendanceBtn = renderAttendanceBtn(cellData.teacher_username, ctx, () =>
                    ctx.onOpenAttendance("weekly", cellData.weekly_session_id, date)
                );
                if (attendanceBtn) {
                    right.appendChild(attendanceBtn);
                }
            }
            const calMenu = renderCalendarMenu(calData, date);
            right.appendChild(calMenu);
        }
        else {
            if (cellData.attendance_open !== false) {
                const attendanceBtn = renderAttendanceBtn(cellData.teacher_username, ctx, () =>
                    ctx.onOpenAttendance("weekly", cellData.weekly_session_id, date)
                );
                if (attendanceBtn) {
                    right.appendChild(attendanceBtn);
                }
            }
        }

        // cell content
        const info = document.createElement("div");
        info.className = "res-info";
        info.innerHTML = getWeeklyHTML(cellData);
        card.append(topBar, info);


	td.appendChild(card);

	if (cellData.canceled) {
	    td.classList.add("weekly-canceled");
	    // Add sensors for reserving individual time slots
	    // inside the canceled class
	    attachDragSensor(td, ctx, hour);

	    card.style.position = "relative";
            card.style.zIndex = "10";
            card.style.pointerEvents = "none";

            // Buttons inside the card must receive clicks again
            topBar.style.pointerEvents = "auto";
	}
    },

    // empty cells
    empty: (cellData, date, hour, td, ctx) => {
        td.classList.add("empty-slot");
        td.dataset.room_id = ctx.room_id;
        td.dataset.hour = hour;
        const inner = document.createElement("div");
        inner.style.minHeight = "100px";
        td.appendChild(inner);
    }
};

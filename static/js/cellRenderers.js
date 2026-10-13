/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { createCalendarTopBar, createCancelButton } from './calendarActions.js';
import { renderCalendarMenu } from './calendarExport.js';

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
        const btn = createCancelButton(onAction);
        container.appendChild(btn);
        return btn;
    }
    return null;
}

function renderConflictIndicator(container) {
    const indicator = document.createElement("span");
    indicator.className = "occupancy-conflict-indicator";
    indicator.textContent = "⚠";
    indicator.title = "Конфликт у термину";
    indicator.setAttribute("aria-label", "Конфликт у термину");
    container.appendChild(indicator);
}

function renderAttendanceBtn(
    ownerUsername,
    ctx,
    onAction,
    title = "QR код за присуство",
    allowAdmin = false,
) {
    if (!ctx.user || (ownerUsername !== ctx.user && !(allowAdmin && ctx.isAdmin))) {
        return null;
    }
    const btn = document.createElement("button");
    btn.className = "attendance-btn";
    btn.innerHTML = `
        <svg class="attendance-qr-icon" viewBox="0 0 21 21" aria-hidden="true" focusable="false">
            <path d="M1 1h7v7H1zM3 3v3h3V3zM13 1h7v7h-7zM15 3v3h3V3zM1 13h7v7H1zM3 15v3h3v-3zM11 11h3v3h-3zM16 11h2v2h-2zM14 15h3v2h-3zM18 15h2v5h-2zM11 17h2v3h-2zM15 18h2v2h-2zM9 9h2v2H9zM11 15h2v2h-2zM9 13h2v2H9z" />
        </svg>
    `;
    btn.title = title;
    btn.onclick = (e) => {
        e.stopPropagation();
        onAction();
    };
    return btn;
}

function appendAttendanceBtn(container, ownerUsername, ctx, kind, eventId, date, attendanceOpen, attendanceCount) {
    if (!attendanceOpen && !(attendanceCount > 0)) {
        return;
    }

    const attendanceBtn = renderAttendanceBtn(
        ownerUsername,
        ctx,
        () => ctx.onOpenAttendance(kind, eventId, date),
        attendanceOpen ? "QR код за присуство" : "Погледај пријављене студенте",
        attendanceCount > 0,
    );
    if (attendanceBtn) {
        container.appendChild(attendanceBtn);
    }
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

        const { topBar, left, right } = createCalendarTopBar();

        if (cellData.conflict) {
            td.classList.add("occupancy-conflict");
            renderConflictIndicator(left);
        }

        // cancel button (if the user has permissions and the reservation is still cancelable)
        if (cellData.can_cancel !== false) {
            renderCancelBtn(left, cellData.username, ctx, () => ctx.onDelete(cellData.id));
        }

        // Keep the QR/list button after the attendance window if students registered.
        appendAttendanceBtn(
            right,
            cellData.username,
            ctx,
            "reservation",
            cellData.id,
            date,
            cellData.attendance_open !== false,
            cellData.attendance_count,
        );

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
        const { topBar, left, right } = createCalendarTopBar();

        if (cellData.conflict) {
            td.classList.add("occupancy-conflict");
            renderConflictIndicator(left);
        }

        // cancel/restore class button
        const btn = renderCancelBtn(left, cellData.teacher_username, ctx, () => 
            ctx.onToggleWeekly(cellData.weekly_session_id, date)
        );

        // Keep the attendance button available after the attendance window if
        // students registered, including for canceled classes.
        appendAttendanceBtn(
            right,
            cellData.teacher_username,
            ctx,
            "weekly",
            cellData.weekly_session_id,
            date,
            cellData.attendance_open !== false,
            cellData.attendance_count,
        );

        // Calendar integration is available only if the class is not canceled.
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
            const calMenu = renderCalendarMenu(calData, date);
            right.appendChild(calMenu);
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

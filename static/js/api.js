/* Copyright (c) 2026 Filip Marić. See LICENCE. */
const BASE_PATH = window.APP_CONFIG?.BASE_PATH || '';
const getUrl = (endpoint) => `${BASE_PATH}${endpoint}`;
const getCsrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

function withCsrfHeaders(headers = {}) {
    const result = new Headers(headers);
    const token = getCsrfToken();
    if (token) {
        result.set('X-CSRFToken', token);
    }
    return result;
}


async function handleResponse(res, errorText) {
        if (res.ok) return res.json();

        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            const data = await res.json();
            const err = new Error(data.error || "Непозната грешка");
            err.status = res.status;
            err.data = data;
            throw err;
        } else {
            const textError = await res.text();
            console.error("Server HTML Error:", textError);
            let serverMessage = '';
            if (typeof DOMParser !== 'undefined') {
                const document = new DOMParser().parseFromString(textError, 'text/html');
                serverMessage = document.querySelector('p')?.textContent?.trim() || '';
            }
            const message = serverMessage || `${errorText} - серверска грешка (${res.status})`;
            const err = new Error(message);
            err.status = res.status;
            err.data = { error: message };
            throw err;
        }
}


export const API = {
    async me() {
        const res = await fetch(getUrl("/me"));
        return handleResponse(res);
    },

    async isAdmin(username) {
        const res = await fetch(getUrl(`/is_admin/${username}`));
        const data = await res.json();
        return data.is_admin;
    },
    async login(username, password) {
        const res = await fetch(getUrl("/login"), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ username, password }),
        });
        if (res.status === 429) {
            throw new Error("Превише покушаја. Покушајте поново касније.");
        }
        if (!res.ok) {
            throw new Error("Пријава на систем није успела");
        }
        return handleResponse(res, "Пријава на систем није успела");
    },
    async logout() {
        const res = await fetch(getUrl("/logout"), {
            method: "POST",
            headers: withCsrfHeaders(),
        });
        if (!res.ok) {
            throw new Error("Грешка при одјављивању");
        }
        return res;
    },
    async getOccupancy(date) {
        const res = await fetch(getUrl(`/occupancy?date=${date}`));
        return handleResponse(res, "Грешка при учитавању резервације");
    },
    async getRooms() {
        const res = await fetch(getUrl("/rooms"));
        return handleResponse(res);
    },
    async getMyReservations(semesterId) {
        const suffix = semesterId ? `?semester_id=${semesterId}` : "";
        const res = await fetch(getUrl(`/my_reservations_data${suffix}`));
        return handleResponse(res, "Грешка при учитавању мојих резервација");
    },
    async getMyReservationsAttendance(semesterId) {
        const suffix = semesterId ? `?semester_id=${semesterId}` : "";
        const res = await fetch(getUrl(`/my_reservations_attendance_data${suffix}`));
        return handleResponse(res, "Грешка при учитавању присуства");
    },
    async getMyCourseAttendance(semesterId, courseId) {
        const params = new URLSearchParams();
        if (semesterId) params.set('semester_id', semesterId);
        if (courseId) params.set('course_id', courseId);
        const suffix = params.toString() ? `?${params.toString()}` : "";
        const res = await fetch(getUrl(`/my_course_attendance_data${suffix}`));
        return handleResponse(res, "Грешка при учитавању присуства по предметима");
    },
    async getAttendanceChallenge(kind, eventId, eventDate) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/challenge`), {
            credentials: "same-origin",
            cache: "no-store",
        });
        return handleResponse(res, "Грешка при учитавању података о присуству");
    },
    async getAttendanceRoster(kind, eventId, eventDate, summaryOnly = false, includeChallenge = true) {
        const params = new URLSearchParams();
        if (summaryOnly) params.set('summary', '1');
        if (!includeChallenge) params.set('include_challenge', '0');
        const suffix = params.toString() ? `?${params.toString()}` : '';
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/data${suffix}`), {
            credentials: "same-origin",
            cache: "no-store",
        });
        return handleResponse(res, "Грешка при учитавању листе присутних");
    },
    async getAttendanceSummary(kind, eventId, dates) {
        const params = new URLSearchParams();
        dates.forEach((date) => params.append('date', date));
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/summary?${params.toString()}`), {
            credentials: "same-origin",
        });
        return handleResponse(res, "Грешка при учитавању сажетка присуства");
    },
    async setAttendanceGeofence(kind, eventId, eventDate, enabled) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/geofence`), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            credentials: "same-origin",
            body: JSON.stringify({ enabled }),
        });
        return handleResponse(res, "Грешка при чувању провере локације");
    },
    async setAttendanceGuestRegistration(kind, eventId, eventDate, enabled) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/guest-registration`), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            credentials: "same-origin",
            body: JSON.stringify({ enabled }),
        });
        return handleResponse(res, "Грешка при чувању режима пријаве");
    },
    async setAttendanceSession(kind, eventId, eventDate, active) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/session`), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            credentials: "same-origin",
            body: JSON.stringify({ active }),
        });
        return handleResponse(res, active
            ? "Грешка при покретању пријављивања"
            : "Грешка при заустављању пријављивања");
    },
    async getAttendanceSpotCheck(kind, eventId, eventDate, limit = 5) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/spot_check?limit=${encodeURIComponent(limit)}`), {
            credentials: "same-origin",
        });
        return handleResponse(res, "Грешка при учитавању провере присуства");
    },
    async submitAttendanceSpotCheck(kind, eventId, eventDate, body) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/spot_check`), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            credentials: "same-origin",
            body: JSON.stringify(body),
        });
        return handleResponse(res, "Грешка при чувању провере присуства");
    },
    async deleteAttendanceRecord(kind, eventId, eventDate, recordId) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/student/${recordId}`), {
            method: "DELETE",
            headers: withCsrfHeaders(),
            credentials: "same-origin",
        });
        return handleResponse(res, "Грешка при брисању пријаве студента");
    },
    async addAttendanceStudent(kind, eventId, eventDate, username) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/student`), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            credentials: "same-origin",
            body: JSON.stringify({ username }),
        });
        return handleResponse(res, "Грешка при додавању студента");
    },
    async submitAttendance(kind, eventId, eventDate, body) {
        const res = await fetch(getUrl(`/attendance/${kind}/${eventId}/${eventDate}/join`), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            credentials: "same-origin",
            body: JSON.stringify(body),
        });
        return handleResponse(res, "Грешка при пријави присуства");
    },
    async deleteReservation(resId) {
        const res = await fetch(getUrl("/reservation/" + resId), {
            method: "DELETE",
            headers: withCsrfHeaders(),
        });
        return handleResponse(res, "Грешка при отказивању резервације");
    },
    async reserve(body) {
        const res = await fetch(getUrl("/reserve"), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body),
        });
        return handleResponse(res, "Грешка при резервацији");
    },
    async toggleWeekly(weeklySessionId, date) {
        const res = await fetch(getUrl("/weekly_session_cancel"), {
            method: "POST",
            headers: withCsrfHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({
                weekly_session_id: weeklySessionId,
                date: date,
            }),
        });
        return handleResponse(res, "Грешка при отказивању часа");
    }
};

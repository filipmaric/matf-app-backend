/* Copyright (c) 2026 Filip Marić. See LICENCE. */
const basePath = window.APP_CONFIG?.BASE_PATH || "";
const buildingSelect = document.getElementById("building-select");
const buildingView = document.getElementById("live-building");
const state = document.getElementById("live-state");
const rotationStatus = document.getElementById("rotation-status");
const subtitle = document.getElementById("live-subtitle");
const liveTime = document.getElementById("live-time");
const liveDate = document.getElementById("live-date");
const fullscreenToggle = document.getElementById("fullscreen-toggle");

let rooms = [];
let occupancy = null;
let buildings = [];
let rotationIndex = 0;
let rotationTimer = null;

const localDate = (date = new Date()) => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
const displayDate = (date) => new Intl.DateTimeFormat("sr-Latn-RS", { day: "2-digit", month: "2-digit", year: "numeric" }).format(date);
const buildingName = (room) => room.location || "Остале зграде";
const currentHour = () => new Date().getHours();
const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
}[character]));

function updateClock() {
    const now = new Date();
    liveTime.textContent = now.toLocaleTimeString("sr-Latn-RS", { hour: "2-digit", minute: "2-digit" });
    liveDate.textContent = displayDate(now);
    if (occupancy) render();
}

function setFullscreenState(active) {
    document.body.classList.toggle("live-fullscreen", active);
    fullscreenToggle.setAttribute("aria-pressed", String(active));
    fullscreenToggle.textContent = active ? "⛶ Изађи из целог екрана" : "⛶ Цео екран";
}

async function toggleFullscreen() {
    if (document.fullscreenElement) {
        await document.exitFullscreen();
        return;
    }
    if (document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
    } else {
        setFullscreenState(!document.body.classList.contains("live-fullscreen"));
    }
}

async function getJson(path) {
    const response = await fetch(`${basePath}${path}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

function getSelectedBuilding() {
    return buildingSelect.value || buildings[rotationIndex] || buildings[0];
}

function render() {
    const selected = getSelectedBuilding();
    const hour = currentHour();
    const date = localDate();
    const selectedRooms = rooms.filter((room) => buildingName(room) === selected).sort((a, b) => {
        const aWing = a.floor_wing || "";
        const bWing = b.floor_wing || "";
        const wingOrder = (!aWing) - (!bWing);
        return wingOrder || aWing.localeCompare(bWing, "sr")
            || (a.display_order ?? a.priority ?? 999) - (b.display_order ?? b.priority ?? 999)
            || a.name.localeCompare(b.name, "sr");
    });
    const dataRooms = occupancy?.rooms || {};
    const busyRooms = selectedRooms.map((room) => {
        const event = (dataRooms[String(room.id)] || []).find((item) => item.start <= hour && hour < item.end && !item.canceled);
        return { room, event };
    });
    const occupied = busyRooms.filter(({ event }) => event).length;
    const free = busyRooms.length - occupied;
    const slotLabel = `${String(hour).padStart(2, "0")}:00–${String(hour + 1).padStart(2, "0")}:00`;

    subtitle.textContent = `${slotLabel} · ${occupied} заузето · ${free} слободно`;
    rotationStatus.textContent = buildingSelect.value ? "Фиксиран приказ" : `Аутоматска смена · ${selected}`;
    if (!selectedRooms.length) {
        state.textContent = "За ову зграду нема евидентираних учионица.";
        buildingView.innerHTML = "";
        return;
    }
    state.textContent = "";
    const groups = [];
    for (const item of busyRooms) {
        const label = item.room.floor_wing || "Остале учионице";
        let group = groups.find((candidate) => candidate.label === label);
        if (!group) { group = { label, items: [] }; groups.push(group); }
        group.items.push(item);
    }
    buildingView.innerHTML = `
      <div class="building-heading"><div><span class="building-kicker">ЗАУЗЕЋЕ УЧИОНИЦА</span><h3>${escapeHtml(selected)}</h3></div><div class="building-count"><strong>${free}</strong><span>слободно од ${busyRooms.length}</span></div></div>
      ${groups.map((group) => `<section class="room-group"><h4>${escapeHtml(group.label)}</h4><div class="room-grid">${group.items.map(({ room, event }) => roomCard(room, event)).join("")}</div></section>`).join("")}`;
}

function roomCard(room, event) {
    if (!event) return `<article class="room-card room-free"><div class="room-card-top"><span class="room-name">${escapeHtml(room.name)}</span><span class="room-badge">СЛОБОДНА</span></div><p>Нема наставе у овом сату</p></article>`;
    const fullTitle = event.type === "reservation" ? (event.description || "Резервација") : (event.lecture_name || "Настава");
    const title = fullTitle.split(/\s*(?:\/|–|—)\s*/)[0].trim() || fullTitle;
    const detail = event.type === "reservation"
        ? (event.username || "Заузето")
        : (event.teacher || (event.groups || []).join(", "));
    return `<article class="room-card room-busy"><div class="room-card-top"><span class="room-name">${escapeHtml(room.name)}</span><span class="room-badge">ЗАУЗЕТА</span></div><h4>${escapeHtml(title)}</h4><p>${escapeHtml(detail || "Заузето")}</p></article>`;
}

function setupBuildings() {
    buildings = [...new Set(rooms.map(buildingName))].sort((a, b) => a.localeCompare(b, "sr"));
    const requested = new URLSearchParams(location.search).get("building");
    for (const name of buildings) {
        const option = document.createElement("option"); option.value = name; option.textContent = name; buildingSelect.appendChild(option);
    }
    if (requested && buildings.includes(requested)) buildingSelect.value = requested;
    rotationIndex = Math.max(0, buildings.indexOf(getSelectedBuilding()));
    buildingSelect.addEventListener("change", () => { rotationIndex = Math.max(0, buildings.indexOf(getSelectedBuilding())); restartRotation(); render(); });
}

function restartRotation() {
    clearInterval(rotationTimer);
    if (buildingSelect.value || buildings.length < 2) return;
    rotationTimer = setInterval(() => { rotationIndex = (rotationIndex + 1) % buildings.length; render(); }, 10000);
}

async function refresh() {
    try {
        const today = localDate();
        const [roomData, occupancyData] = await Promise.all([rooms.length ? Promise.resolve(rooms) : getJson("/rooms"), getJson(`/occupancy?date=${today}`)]);
        rooms = roomData; occupancy = occupancyData;
        if (!buildings.length) { setupBuildings(); restartRotation(); }
        render();
    } catch (error) {
        state.textContent = "Подаци тренутно нису доступни. Покушајте поново за неколико секунди.";
        console.error("Live occupancy refresh failed", error);
    }
}

updateClock();
fullscreenToggle.addEventListener("click", () => toggleFullscreen().catch((error) => console.error("Fullscreen failed", error)));
document.addEventListener("fullscreenchange", () => setFullscreenState(Boolean(document.fullscreenElement)));
setInterval(updateClock, 30000);
setInterval(refresh, 10000);
refresh();

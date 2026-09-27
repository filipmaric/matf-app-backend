/* Copyright (c) 2026 Filip Marić. See LICENCE. */
document.addEventListener("DOMContentLoaded", async function() {
    const monthLabel = document.getElementById('monthLabel');
    const previousMonth = document.getElementById('previousMonth');
    const nextMonth = document.getElementById('nextMonth');
    const calendarDiv = document.getElementById('calendar');
    const saveBtn = document.getElementById('saveBtn');
    const kindSelect = document.getElementById('kind');
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

    let viewDate = new Date();

    function monthTitle(date) {
        return new Intl.DateTimeFormat('sr-RS', {
            month: 'long',
            year: 'numeric'
        }).format(date);
    }

    let calendarData = {}; // { 'YYYY-MM-DD': { kind: 'teaching', week_day: 2 } }
    let holidays = []; 
    const calendarCache = new Map();

    async function loadCalendarData(month, year) {
	const cacheKey = `${year}-${String(month).padStart(2, '0')}`;
	if (calendarCache.has(cacheKey)) {
	    ({calendarData, holidays} = calendarCache.get(cacheKey));
	    calendarData = {...calendarData};
	    return;
	}
	const res = await fetch(`/calendar_data?month=${month}&year=${year}`);
	const data = await res.json();
	if (!res.ok) {
	    throw new Error(data.error || `Учитавање календара није успело (${res.status})`);
	}
	calendarData = data.calendar;
	holidays = data.holidays;
	calendarCache.set(cacheKey, {calendarData: {...calendarData}, holidays: [...holidays]});
    }
    
    async function renderCalendar() {
	const month = viewDate.getMonth() + 1;
	const year = viewDate.getFullYear();
	monthLabel.textContent = monthTitle(viewDate);
	
	try {
	    await loadCalendarData(month, year); // sada imamo calendarData i holidays
	} catch (error) {
	    calendarDiv.textContent = error.message;
	    return;
	}
	
	calendarDiv.innerHTML = '';

	const firstDay = new Date(year, month - 1, 1).getDay(); // nedelja=0
	const daysInMonth = new Date(year, month, 0).getDate();

	const days = ["Нед", "Пон", "Уто", "Сре", "Чет", "Пет", "Суб"];
	for (let i = 0; i < 7; i++) {
	    const day = document.createElement('div');
	    day.innerHTML = days[i];
	    calendarDiv.appendChild(day);
	}
	    

	// prazni slotovi pre prvog dana
	for (let i = 0; i < firstDay; i++) {
            const empty = document.createElement('div');
            calendarDiv.appendChild(empty);
	}

	for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
            const td = document.createElement('div');
            td.classList.add('day');

            const weekday = new Date(year, month-1, day).getDay();
	    let item = calendarData[dateStr];
	    let kind = item?.kind || 'non_working';

            // Stil i status

	    if (holidays.includes(dateStr)) {
		td.classList.add('holiday');
		item = calendarData[dateStr] = {kind: 'non_working', week_day: -1};
		kind = 'non_working';
	    } else if (item !== undefined) {
	    td.classList.add(`${kind}-day`);
		td.title = dayTitle(day, item, kind);
		if (item.week_day !== undefined && item.week_day !== -1)
		    td.classList.add('custom-weekday'); // vizuelni mark
	    } else {
		td.classList.add('non_working-day');
		item = calendarData[dateStr] = {kind: 'non_working', week_day: -1};
		kind = 'non_working';
            }

	    td.textContent = dayLabel(day, item, kind);

            td.addEventListener('click', () => {
		if (holidays.includes(dateStr)) return; // holidays cannot be changed
		const kind = kindSelect.value;
		calendarData[dateStr] = {
		    kind,
		    week_day: kind === 'makeup' ? (calendarData[dateStr]?.week_day ?? -1) : -1
		};
		for (const dayKind of ['teaching', 'makeup', 'exam', 'colloquium', 'non_working'])
		    td.classList.remove(`${dayKind}-day`);
		td.classList.add(`${kind}-day`);
		td.classList.toggle('custom-weekday', calendarData[dateStr].week_day !== -1);
		td.textContent = dayLabel(day, calendarData[dateStr], kind);
		td.title = dayTitle(day, calendarData[dateStr], kind);
            });

	    td.addEventListener('contextmenu', (e) => {
		e.preventDefault();
		if (holidays.includes(dateStr)) return;
		
		showWeekdayMenu(dateStr, td);
	    });

            calendarDiv.appendChild(td);
	}

    function dayLabel(day) {
	    return String(day);
    }

    function dayTitle(day, item, kind) {
	    const kindLabel = kindSelect.options[kindSelect.selectedIndex]?.text || kind;
	    if (kind === 'makeup' && item?.week_day >= 0 && item.week_day < weekdayNames.length)
		return `${kindLabel}: надокнађује се ${weekdayNames[item.week_day]}`;
	    return `${day}: ${kindLabel}`;
    }
    }

    const weekdayMenu = document.getElementById('weekdayMenu');
    const weekdayNames = ["Пон", "Уто", "Сре", "Чет", "Пет", "Суб", "Нед"];

    // otvaranje menija
    function showWeekdayMenu(dateStr, dayElem) {
	weekdayMenu.innerHTML = "";
	weekdayMenu.style.visibility = "hidden";
	weekdayMenu.style.display = "flex";
	weekdayMenu.style.left = "0px";
	weekdayMenu.style.top = "0px";

	// opcija Default
	const def = document.createElement('div');
	def.textContent = "Подразумевано (стварни дан)";
	def.onclick = () => {
            calendarData[dateStr].week_day = -1;
            dayElem.classList.remove('custom-weekday');
            hideMenu();
	};
	weekdayMenu.appendChild(def);

	// 0–6
	weekdayNames.forEach((name, idx)=> {
            const opt = document.createElement('div');
            opt.textContent = name + ` (${idx})`;
            opt.onclick = () => {
		calendarData[dateStr].week_day = idx;
		dayElem.classList.add('custom-weekday');
		hideMenu();
            };
	    weekdayMenu.appendChild(opt);
	});

	const margin = 8;
	const cellRect = dayElem.getBoundingClientRect();
	const menuRect = weekdayMenu.getBoundingClientRect();
	let left = cellRect.right + margin;
	if (left + menuRect.width > window.innerWidth - margin) {
	    left = cellRect.left - menuRect.width - margin;
	}
	left = Math.min(Math.max(left, margin), Math.max(margin, window.innerWidth - menuRect.width - margin));
	const top = Math.min(
	    Math.max(cellRect.top, margin),
	    Math.max(margin, window.innerHeight - menuRect.height - margin)
	);
	weekdayMenu.style.left = left + "px";
	weekdayMenu.style.top = top + "px";
	weekdayMenu.style.visibility = "visible";
    }

    function hideMenu() { weekdayMenu.style.display = "none"; }

    // zatvori meni klikom van njega
    document.addEventListener('click', () => hideMenu());

    
    previousMonth.addEventListener('click', async (event) => {
        event.preventDefault();
        viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1);
        await renderCalendar();
    });
    nextMonth.addEventListener('click', async (event) => {
        event.preventDefault();
        viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1);
        await renderCalendar();
    });
    await renderCalendar();

    saveBtn.addEventListener('click', async () => {
	const updates = Object.entries(calendarData).map(([date, item]) => ({
	    date,
	    kind: item.kind || 'non_working',
	    week_day: item.week_day ?? -1
	}));	
	// POST request za backend:
	const response = await fetch('/update_calendar', {
          method: 'POST',
          headers: {
              'Content-Type':'application/json',
              ...(csrfToken ? {'X-CSRFToken': csrfToken} : {}),
          },
	          body: JSON.stringify(updates)
	});
	let result = {};
	try {
	    result = await response.json();
	} catch (_) {
	    // The server may return a non-JSON error page.
	}
	if (!response.ok) {
	    alert(result.error || `Чување календара није успело (${response.status})`);
	    return;
	}
	calendarCache.set(`${viewDate.getFullYear()}-${String(viewDate.getMonth() + 1).padStart(2, '0')}`, {
	    calendarData: {...calendarData},
	    holidays: [...holidays],
	});
    });
});

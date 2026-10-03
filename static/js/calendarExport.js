/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { formatApiDate } from './util.js';

/** Render the shared Google Calendar and ICS export menu for one event. */
export function renderCalendarMenu(event, fullDate) {
    const startTime = formatApiDate(fullDate, event.start);
    const endTime = formatApiDate(fullDate, event.end);
    const title = event.calendarTitle || event.description;
    const description = event.calendarDescription
        || `Корисник: ${event.username}, Сала: ${event.room}, Опис: ${event.description}`;
    const room = event.room || 'Није одређена';

    const dropdown = document.createElement('div');
    dropdown.className = 'calendar-dropdown';

    const button = document.createElement('button');
    button.className = 'cal-btn';
    button.innerHTML = '📅';

    const menu = document.createElement('div');
    menu.className = 'cal-menu';

    const googleUrl = `https://calendar.google.com/calendar/render?action=TEMPLATE&text=${encodeURIComponent(title)}&dates=${startTime}/${endTime}&details=${encodeURIComponent(description)}&location=${encodeURIComponent('MatF, сала ' + room)}`;
    const googleLink = document.createElement('a');
    googleLink.href = googleUrl;
    googleLink.target = '_blank';
    googleLink.innerText = 'Google Calendar';

    const icsContent = [
        'BEGIN:VCALENDAR',
        'VERSION:2.0',
        'BEGIN:VEVENT',
        `DTSTART:${startTime}`,
        `DTEND:${endTime}`,
        `SUMMARY:${title}`,
        `DESCRIPTION:${description}`,
        `LOCATION:Сала ${room}`,
        'END:VEVENT',
        'END:VCALENDAR',
    ].join('\n');

    const icsBlob = new Blob([icsContent], { type: 'text/calendar' });
    const icsUrl = URL.createObjectURL(icsBlob);
    const icsLink = document.createElement('a');
    icsLink.href = icsUrl;
    icsLink.download = `${event.calendarFilePrefix || 'rezervacija'}_${event.id}.ics`;
    icsLink.innerText = 'Outlook / Apple (.ics)';

    menu.append(googleLink, icsLink);
    dropdown.append(button, menu);
    return dropdown;
}

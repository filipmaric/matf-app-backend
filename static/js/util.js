/* Copyright (c) 2026 Filip Marić. See LICENCE. */
export function formatApiDate(dateStr, hour) {
    // dateStr is "2026-03-19", hour is for example 9
    const date = new Date(dateStr);
    date.setHours(hour, 0, 0);
    // Returns the format: 20260319T090000Z
    return date.toISOString().replace(/-|:|\.\d+/g, "");
}

export function formatDateDDMMYYYY(isoDate) {
	// isoDate = "YYYY-MM-DD"
	const parts = isoDate.split("-");
	const year = parts[0];
	const month = parts[1];
	const day = parts[2];
	return `${day}/${month}/${year}`;
}

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

export function buildCsvContent(rows) {
    const escapeCsvValue = (value) => {
        const text = String(value ?? '');
        if (/[",\n;]/.test(text)) {
            return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
    };

    return '\ufeff' + rows
        .map((row) => row.map(escapeCsvValue).join(';'))
        .join('\n');
}

export function downloadTextFile(filename, content, mimeType = 'text/csv;charset=utf-8') {
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

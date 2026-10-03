/* Copyright (c) 2026 Filip Marić. See LICENCE. */

/**
 * Reusable mouse interaction for selecting a contiguous time interval.
 *
 * The caller owns the meaning of a cell. This module only handles selecting
 * cells that belong to the same group (for example, one day or one room) and
 * reports the resulting interval to the caller.
 */
export function createMouseIntervalSelector({
    container,
    cellSelector,
    getGroupKey,
    canStart = () => true,
    selectedClass = 'calendar-cell-selected',
    onPreview = () => {},
    onSelection = () => {},
}) {
    let selecting = false;
    let startCell = null;
    let currentSelection = null;

    function cells() {
        return [...container.querySelectorAll(cellSelector)];
    }

    function clear() {
        cells().forEach((cell) => cell.classList.remove(selectedClass));
        selecting = false;
        startCell = null;
        currentSelection = null;
    }

    function selectionFor(cell) {
        if (!startCell || getGroupKey(startCell) !== getGroupKey(cell)) return null;
        const startHour = Number(startCell.dataset.hour);
        const currentHour = Number(cell.dataset.hour);
        if (!Number.isFinite(startHour) || !Number.isFinite(currentHour)) return null;

        const firstHour = Math.min(startHour, currentHour);
        const lastHour = Math.max(startHour, currentHour) + 1;
        const selected = cells().filter((candidate) => (
            getGroupKey(candidate) === getGroupKey(startCell)
            && Number(candidate.dataset.hour) >= firstHour
            && Number(candidate.dataset.hour) < lastHour
        ));

        return {
            date: startCell.dataset.date,
            startHour: firstHour,
            endHour: lastHour,
            groupKey: getGroupKey(startCell),
            cells: selected,
        };
    }

    function preview(cell) {
        const selection = selectionFor(cell);
        if (!selection) return;
        cells().forEach((candidate) => candidate.classList.remove(selectedClass));
        selection.cells.forEach((candidate) => candidate.classList.add(selectedClass));
        currentSelection = selection;
        onPreview(selection);
    }

    function onMouseDown(event) {
        const cell = event.target.closest(cellSelector);
        if (!cell || !container.contains(cell) || event.button !== 0) return;
        if (!canStart(cell)) return;
        event.preventDefault();
        selecting = true;
        startCell = cell;
        preview(cell);
    }

    function onMouseEnter(event) {
        if (!selecting) return;
        const cell = event.target.closest(cellSelector);
        if (cell && container.contains(cell)) preview(cell);
    }

    function onMouseUp() {
        if (!selecting || !startCell) return;
        const selection = currentSelection;
        selecting = false;
        startCell = null;
        currentSelection = null;
        if (selection) onSelection(selection);
    }

    container.addEventListener('mousedown', onMouseDown);
    container.addEventListener('mouseover', onMouseEnter);
    document.addEventListener('mouseup', onMouseUp);

    return {
        clear,
        destroy() {
            container.removeEventListener('mousedown', onMouseDown);
            container.removeEventListener('mouseover', onMouseEnter);
            document.removeEventListener('mouseup', onMouseUp);
            clear();
        },
    };
}

/* Copyright (c) 2026 Filip Marić. See LICENCE. */

/** Create the standard calendar cancellation button used by reservations. */
export function createCancelButton(onAction, ariaLabel = 'Откажи') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'res-cancel-btn';
    button.textContent = '×';
    button.setAttribute('aria-label', ariaLabel);
    button.title = ariaLabel;
    button.addEventListener('click', (event) => {
        event.stopPropagation();
        onAction();
    });
    return button;
}

/** Create the same left/right action row used by reservation cards. */
export function createCalendarTopBar() {
    const topBar = document.createElement('div');
    topBar.className = 'res-top-bar';
    const left = document.createElement('div');
    left.className = 'res-top-bar-left';
    const right = document.createElement('div');
    right.className = 'res-top-bar-right';
    topBar.append(left, right);
    return { topBar, left, right };
}

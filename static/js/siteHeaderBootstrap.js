/* Copyright (c) 2026 Filip Marić. See LICENCE. */

// Derive the application prefix from this module URL when a page does not
// provide APP_CONFIG (for example, when served below /matf-app).
const staticMarker = '/static/';
const modulePath = new URL(import.meta.url).pathname;
if (!window.APP_CONFIG) {
    const markerIndex = modulePath.indexOf(staticMarker);
    window.APP_CONFIG = {
        BASE_PATH: markerIndex >= 0 ? modulePath.slice(0, markerIndex) : '',
    };
}

import('./siteHeader.js')
    .then(({ initializeSiteHeader }) => initializeSiteHeader())
    .catch((error) => console.error('Auth header error:', error));

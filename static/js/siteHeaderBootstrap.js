/* Copyright (c) 2026 Filip Marić. See LICENCE. */
import { initializeSiteHeader } from './siteHeader.js';

initializeSiteHeader().catch((error) => console.error('Auth header error:', error));

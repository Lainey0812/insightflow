import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, vi } from 'vitest';

// Use jsdom's browser Storage instead of Node 24's experimental global Storage.
vi.stubGlobal('localStorage', window.localStorage);
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });
Element.prototype.scrollIntoView = vi.fn();

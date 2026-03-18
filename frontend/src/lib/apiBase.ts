function resolveApiBase(): string {
    const configured = (import.meta.env.VITE_API_URL || '').trim();
    if (configured) {
        return configured.replace(/\/+$/, '');
    }

    if (typeof window !== 'undefined') {
        const isLocalHost =
            window.location.hostname === 'localhost' ||
            window.location.hostname === '127.0.0.1';

        if (isLocalHost) {
            return 'http://localhost:8000';
        }

        return `${window.location.protocol}//${window.location.host}`;
    }

    return 'http://localhost:8000';
}

export const API_BASE = resolveApiBase();

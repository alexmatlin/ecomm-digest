// The Digest — auto-update hero date
// Replaces the text inside any `.hero-eyebrow-date` element with today's date
// in the form "Monday, June 9, 2026" (en-US long form).
// The HTML keeps a hardcoded date inside the span as a fallback for when JS
// is disabled or fails to load.
(function () {
    'use strict';

    function updateDates() {
        var els = document.querySelectorAll('.hero-eyebrow-date');
        if (!els.length) return;

        var formatted;
        try {
            formatted = new Date().toLocaleDateString('en-US', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
            });
        } catch (e) {
            // Locale support missing — leave the hardcoded fallback alone.
            return;
        }

        els.forEach(function (el) {
            el.textContent = formatted;
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', updateDates);
    } else {
        updateDates();
    }
})();

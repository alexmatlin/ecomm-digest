// The Digest — interactivity bundle
// 1) Theme toggle (light/dark) with localStorage + prefers-color-scheme on first visit
// 2) Scroll-reveal via IntersectionObserver (respects prefers-reduced-motion)
// 3) Combined topic-filter + search for the briefings grid
// 4) Click-tag-on-card to activate the matching filter chip
// Works across home (topic cards) and chapter pages (story grid).

(function () {
    'use strict';

    // ---------- Theme toggle ----------
    function initTheme() {
        const root = document.documentElement;
        const toggle = document.querySelector('.theme-toggle');

        function apply(theme) {
            root.setAttribute('data-theme', theme);
            if (toggle) {
                toggle.textContent = theme === 'dark' ? '☀' : '☾';
                toggle.setAttribute('aria-label', theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
            }
        }

        const saved = localStorage.getItem('theme');
        if (saved === 'dark' || saved === 'light') {
            apply(saved);
        } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            apply('dark');
        } else {
            apply('light');
        }

        if (toggle) {
            toggle.addEventListener('click', () => {
                const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
                apply(next);
                localStorage.setItem('theme', next);
            });
        }
    }

    // ---------- Scroll reveal ----------
    function initScrollReveal() {
        const prefersReduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const targets = document.querySelectorAll('.reveal');
        if (!targets.length) return;

        if (prefersReduced || !('IntersectionObserver' in window)) {
            targets.forEach(el => el.classList.add('is-visible'));
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });

        targets.forEach(el => observer.observe(el));
    }

    // ---------- Filtering: topic chips + header search ----------
    function initFilters() {
        // Determine which set of cards lives on this page.
        let cards = document.querySelectorAll('.story-grid .story-card');
        let isStoryGrid = cards.length > 0;
        let gridEl = document.querySelector('.story-grid');
        if (!isStoryGrid) {
            cards = document.querySelectorAll('.topic-grid .topic-card');
            gridEl = document.querySelector('.topic-grid');
        }
        if (!cards.length) {
            // No grid on this page — still wire up search so it can no-op safely.
            return;
        }

        const chips = document.querySelectorAll('.filter-bar .filter-chip');
        const searchInput = document.getElementById('header-search-input');
        const countEl = document.getElementById('briefings-count');

        let currentFilter = 'all';
        let currentSearch = '';
        let emptyEl = null;

        function ensureEmptyState() {
            if (emptyEl || !gridEl) return;
            emptyEl = document.createElement('div');
            emptyEl.className = 'empty-state';
            emptyEl.textContent = 'No stories match. Try a different topic or search term.';
            emptyEl.style.display = 'none';
            gridEl.appendChild(emptyEl);
        }

        function apply() {
            ensureEmptyState();
            let visible = 0;
            cards.forEach(card => {
                const topic = card.dataset.topic || '';
                const matchesTopic = currentFilter === 'all' || topic === currentFilter;
                const text = (card.textContent || '').toLowerCase();
                const matchesSearch = !currentSearch || text.includes(currentSearch);
                const show = matchesTopic && matchesSearch;
                card.style.display = show ? '' : 'none';
                if (show) visible++;
            });
            if (countEl) {
                countEl.textContent = visible + ' ' + (visible === 1 ? 'story' : 'stories');
            }
            if (emptyEl) {
                emptyEl.style.display = visible === 0 ? '' : 'none';
            }
        }

        chips.forEach(chip => {
            chip.addEventListener('click', () => {
                chips.forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                currentFilter = chip.dataset.filter;
                apply();
            });
        });

        if (searchInput) {
            searchInput.addEventListener('input', () => {
                currentSearch = searchInput.value.toLowerCase().trim();
                apply();
            });
        }

        // Click a tag on a card to activate its matching filter chip.
        if (isStoryGrid) {
            cards.forEach(card => {
                const tag = card.querySelector('.tag-alt');
                if (!tag) return;
                tag.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const topic = card.dataset.topic;
                    if (!topic) return;
                    const chip = document.querySelector('.filter-chip[data-filter="' + topic + '"]');
                    if (chip) chip.click();
                    const section = document.querySelector('.grid-section');
                    if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
                });
            });
        }

        apply();
    }

    // ---------- Header shrink on scroll ----------
    function initScrollShrink() {
        const header = document.querySelector('.site-header');
        if (!header) return;
        const THRESHOLD = 60;
        function update() {
            header.classList.toggle('is-scrolled', window.scrollY > THRESHOLD);
        }
        window.addEventListener('scroll', update, { passive: true });
        update();
    }

    // ---------- Mobile search toggle ----------
    function initSearchToggle() {
        const toggle = document.querySelector('.search-toggle');
        const dropdown = document.querySelector('.header-search-dropdown');
        const dropdownInput = document.getElementById('mobile-search-input');
        const desktopInput = document.getElementById('header-search-input');
        const header = document.querySelector('.site-header');
        if (!toggle || !dropdown || !dropdownInput) return;

        toggle.addEventListener('click', () => {
            const isOpen = header.classList.toggle('search-open');
            toggle.setAttribute('aria-expanded', isOpen);
            if (isOpen) {
                dropdownInput.focus();
            } else {
                dropdownInput.value = '';
                // Clear filter if we had typed something
                if (desktopInput) { desktopInput.value = ''; }
                document.dispatchEvent(new Event('digest:search-clear'));
            }
        });

        // Sync mobile input → shared filter logic
        dropdownInput.addEventListener('input', () => {
            // Mirror value to desktop input and fire an input event so
            // the existing initFilters() handler picks it up.
            if (desktopInput) {
                desktopInput.value = dropdownInput.value;
                desktopInput.dispatchEvent(new Event('input'));
            }
        });

        // Close on Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && header.classList.contains('search-open')) {
                header.classList.remove('search-open');
                dropdownInput.value = '';
                toggle.setAttribute('aria-expanded', false);
            }
        });

        // Close when clicking outside the header
        document.addEventListener('click', (e) => {
            if (!header.contains(e.target)) {
                header.classList.remove('search-open');
                dropdownInput.value = '';
                toggle.setAttribute('aria-expanded', false);
            }
        });
    }

    // ---------- Init ----------
    function init() {
        initTheme();
        initScrollShrink();
        initScrollReveal();
        initFilters();
        initSearchToggle();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

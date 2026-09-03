// Theme configuration. Only the button's own labelling lives here now: the
// palette is Bootstrap's, selected by the `data-bs-theme` attribute rather than
// by loading a second stylesheet.
const themes = {
    light: {
        icon: 'fa-moon',
        text: 'Dark Mode'
    },
    dark: {
        icon: 'fa-sun',
        text: 'Light Mode'
    }
};

// Only ever 'light' or 'dark' was stored; anything else reads as the default.
function storedTheme() {
    return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light';
}

// Applied while <head> is still parsing, so a reviewer who chose dark never
// sees a flash of the light palette. (themes.js is a plain blocking script for
// exactly this reason -- deferring it would move the swap after first paint.)
document.documentElement.dataset.bsTheme = storedTheme();

// Theme switcher functionality
class ThemeSwitcher {
    constructor() {
        this.currentTheme = storedTheme();
        this.themeToggle = document.getElementById('theme-toggle');
        this.themeIcon = document.getElementById('theme-icon');
        this.themeText = document.getElementById('theme-text');

        this.init();
    }

    init() {
        // Bring the button's label in line with the theme already applied above.
        this.applyTheme(this.currentTheme);

        // Add event listener
        this.themeToggle.addEventListener('click', () => {
            this.toggleTheme();
        });
    }

    applyTheme(theme) {
        const themeConfig = themes[theme];

        // Bootstrap reads this itself, and every --bs-* token follows it.
        document.documentElement.dataset.bsTheme = theme;

        // Update button. Swap only the glyph: assigning className would drop
        // the spacing utility the template puts on the icon, and the moon would
        // sit flush against the label from the first toggle on.
        this.themeIcon.classList.remove(...Object.values(themes).map((t) => t.icon));
        this.themeIcon.classList.add(themeConfig.icon);
        this.themeText.textContent = themeConfig.text;

        // Save to localStorage
        localStorage.setItem('theme', theme);

        this.currentTheme = theme;
    }

    toggleTheme() {
        const newTheme = this.currentTheme === 'light' ? 'dark' : 'light';
        this.applyTheme(newTheme);
    }
}

// Initialize theme switcher when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    new ThemeSwitcher();
});

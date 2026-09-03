// Theme configuration
const themes = {
    light: {
        name: 'flatly',
        url: 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/flatly/bootstrap.min.css',
        icon: 'fa-moon',
        text: 'Dark Mode'
    },
    dark: {
        name: 'darkly',
        url: 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css',
        icon: 'fa-sun',
        text: 'Light Mode'
    }
};

// Theme switcher functionality
class ThemeSwitcher {
    constructor() {
        this.currentTheme = localStorage.getItem('theme') || 'light';
        this.themeLink = document.getElementById('theme-css');
        this.themeToggle = document.getElementById('theme-toggle');
        this.themeIcon = document.getElementById('theme-icon');
        this.themeText = document.getElementById('theme-text');

        this.init();
    }

    init() {
        // Apply saved theme
        this.applyTheme(this.currentTheme);

        // Add event listener
        this.themeToggle.addEventListener('click', () => {
            this.toggleTheme();
        });
    }

    applyTheme(theme) {
        const themeConfig = themes[theme];

        // Update CSS link
        this.themeLink.href = themeConfig.url;

        // Update button. Swap only the glyph: assigning className would drop
        // the spacing utility the template puts on the icon, and the moon would
        // sit flush against the label from the first toggle on.
        this.themeIcon.classList.remove(...Object.values(themes).map((t) => t.icon));
        this.themeIcon.classList.add(themeConfig.icon);
        this.themeText.textContent = themeConfig.text;

        // Mark the body for the theme-dependent custom CSS (style.css keys the
        // canvas frame off `.theme-dark`), leaving any other class in place.
        document.body.classList.toggle('theme-dark', theme === 'dark');

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

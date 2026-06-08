// Theme configuration
const themes = {
    light: {
        name: 'flatly',
        url: 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/flatly/bootstrap.min.css',
        icon: 'fas fa-moon',
        text: 'Dark Mode'
    },
    dark: {
        name: 'darkly',
        url: 'https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css',
        icon: 'fas fa-sun',
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

        // Update button
        this.themeIcon.className = themeConfig.icon;
        this.themeText.textContent = themeConfig.text;

        // Update body class
        document.body.className = `dirt-body theme-${theme}`;

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

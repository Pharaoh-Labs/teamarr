// Teamarr - Sports Team EPG Generator JavaScript

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    console.log('Teamarr initialized');

    // Load saved theme preference
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.body.classList.add(savedTheme + '-theme');
    updateThemeIcon(savedTheme);

    // Convert Flask flash messages to notifications
    convertFlashMessages();
});

// Theme toggle functionality
function toggleTheme() {
    const body = document.body;
    const isDark = body.classList.contains('dark-theme');

    body.classList.remove('dark-theme', 'light-theme');
    const newTheme = isDark ? 'light' : 'dark';
    body.classList.add(newTheme + '-theme');

    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const icon = document.getElementById('theme-icon');
    if (icon) {
        icon.textContent = theme === 'dark' ? '🌙' : '☀️';
    }
}

// Utility: Insert text at cursor position in textarea
function insertAtCursor(textarea, text) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const value = textarea.value;

    textarea.value = value.substring(0, start) + text + value.substring(end);

    // Move cursor after inserted text
    const newPos = start + text.length;
    textarea.setSelectionRange(newPos, newPos);
    textarea.focus();
}

// Confirm delete actions
function confirmDelete(message) {
    return confirm(message || 'Are you sure you want to delete this?');
}

// Notification System
function showNotification(message, type = 'info', duration = 10000, title = null) {
    const container = document.getElementById('notification-container');
    if (!container) return;

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;

    const icons = {
        success: '✅',
        error: '❌',
        info: '📡',
        warning: '⚠️'
    };

    const titles = {
        success: title || 'Success',
        error: title || 'Error',
        info: title || 'Info',
        warning: title || 'Warning'
    };

    notification.innerHTML = `
        <div class="notification-icon">${icons[type]}</div>
        <div class="notification-content">
            <div class="notification-title">${titles[type]}</div>
            <div class="notification-message">${message}</div>
        </div>
        <button class="notification-close" onclick="closeNotification(this)">×</button>
    `;

    container.appendChild(notification);

    // Auto-dismiss after duration
    if (duration > 0) {
        setTimeout(() => {
            closeNotification(notification.querySelector('.notification-close'));
        }, duration);
    }

    return notification;
}

function closeNotification(button) {
    const notification = button.parentElement || button;
    notification.classList.add('hiding');
    setTimeout(() => {
        notification.remove();
    }, 300); // Match animation duration
}

// Convert Flask flash messages to popup notifications
function convertFlashMessages() {
    const flashMessages = document.querySelector('.flash-messages');
    if (!flashMessages) return;

    const alerts = flashMessages.querySelectorAll('.alert');
    alerts.forEach(alert => {
        const message = alert.textContent.replace('×', '').trim();
        let type = 'info';

        if (alert.classList.contains('alert-success')) type = 'success';
        else if (alert.classList.contains('alert-error')) type = 'error';
        else if (alert.classList.contains('alert-warning')) type = 'warning';

        showNotification(message, type);
    });

    // Hide the flash messages container
    flashMessages.style.display = 'none';
}

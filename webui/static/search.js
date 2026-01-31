document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search-input');
    const logList = document.getElementById('log-list');
    const logItems = Array.from(logList.getElementsByTagName('li'));

    searchInput.addEventListener('input', function() {
        const query = searchInput.value.trim().toLowerCase();
        logItems.forEach(function(item) {
            const text = item.textContent.toLowerCase();
            if (text.includes(query)) {
                item.style.display = '';
            } else {
                item.style.display = 'none';
            }
        });
    });
});

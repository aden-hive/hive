// Function to get cookie value
function getCookie(name) {
    let value = `; ${document.cookie}`;
    let parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
}

// Apply interest-based theme on load
document.addEventListener("DOMContentLoaded", () => {
    const interest = getCookie("user_interest"); // e.g., 'precision' or 'intuition'
    if (interest) {
        document.body.classList.add(`interest-${interest}`);
    }
});


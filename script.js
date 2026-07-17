document.getElementById('signup-form').addEventListener('submit', function(event) {
    event.preventDefault();
    const emailInput = document.getElementById('email');
    const messageEl = document.getElementById('message');
    
    if (emailInput.value) {
        // Simulate subscribing user
        messageEl.textContent = `Thank you for subscribing, ${emailInput.value}!`;
        emailInput.value = '';
    } else {
        messageEl.textContent = 'Please enter a valid email address.';
        messageEl.style.color = 'red';
    }
});

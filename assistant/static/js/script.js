// Real-time clock
function updateClock() {
    const clock = document.getElementById('clock');
    const now = new Date();
    const pktOffset = 5 * 60; // PKT is UTC+5
    const localOffset = now.getTimezoneOffset();
    const pktTime = new Date(now.getTime() + (pktOffset + localOffset) * 60 * 1000);
    
    const timeString = pktTime.toLocaleString('en-US', {
        hour: 'numeric',
        minute: 'numeric',
        hour12: true,
        timeZoneName: 'short',
        weekday: 'long',
        month: 'long',
        day: 'numeric',
        year: 'numeric'
    }).replace(',', '');
    clock.textContent = timeString;
}
setInterval(updateClock, 1000);
updateClock(); // Initial call

// Voice recognition
let recognition;
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        const voiceBtn = document.getElementById('voice-btn');
        voiceBtn.textContent = '🎙️ Listening...';
        voiceBtn.classList.add('listening');
    };

    recognition.onresult = (event) => {
        const command = event.results[0][0].transcript;
        document.getElementById('command-input').value = command;
        sendCommand();
    };

    recognition.onend = () => {
        const voiceBtn = document.getElementById('voice-btn');
        voiceBtn.textContent = '🎙️ Speak';
        voiceBtn.classList.remove('listening');
    };

    recognition.onerror = (event) => {
        const responseArea = document.getElementById('response-area');
        responseArea.innerHTML += `<p>Error with voice recognition: ${event.error}</p>`;
        const voiceBtn = document.getElementById('voice-btn');
        voiceBtn.textContent = '🎙️ Speak';
        voiceBtn.classList.remove('listening');
    };
}

function startVoiceRecognition() {
    if (!recognition) {
        const responseArea = document.getElementById('response-area');
        responseArea.innerHTML += '<p>Voice recognition is not supported in your browser.</p>';
        return;
    }
    recognition.start();
}

async function sendCommand() {
    const input = document.getElementById('command-input');
    const responseArea = document.getElementById('response-area');
    const command = input.value.trim();

    if (!command) {
        responseArea.innerHTML += '<p>Please enter a command.</p>';
        return;
    }

    responseArea.innerHTML += `<p>Sent: ${command}</p>`;
    input.value = '';

    try {
        const response = await fetch('/process_command/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ command })
        });
        const data = await response.json();
        if (data.error) {
            responseArea.innerHTML += `<p>Error: ${data.error}</p>`;
            speak(data.error);
        } else {
            responseArea.innerHTML += `<p>Response: ${data.response}</p>`;
            speak(data.response.replace(/<[^>]+>/g, '')); // Remove HTML tags for speech
        }
    } catch (error) {
        console.error('AJAX Error:', error);
        responseArea.innerHTML += '<p>Error: Failed to process command. Check console for details.</p>';
        speak('Error: Failed to process command.');
    }
    responseArea.scrollTop = responseArea.scrollHeight;
}

function showCommandHistory() {
    const responseArea = document.getElementById('response-area');
    fetch('/process_command/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ command: 'hey jarvis command history' })
    })
    .then(response => response.json())
    .then(data => {
        responseArea.innerHTML += `<p>Command History: ${data.response}</p>`;
        speak('Here is your command history.');
    })
    .catch(error => {
        console.error('History Fetch Error:', error);
        responseArea.innerHTML += '<p>Error: Failed to load command history.</p>';
        speak('Error: Failed to load command history.');
    });
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

document.getElementById('command-input').addEventListener('keypress', function(e) {
    if (e.key === 'Enter') sendCommand();
});
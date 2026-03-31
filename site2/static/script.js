document.addEventListener('DOMContentLoaded', () => {
    // 1. Прокрутка
    const navButtons = document.querySelectorAll('.nav-btn');
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = 'section-' + btn.getAttribute('data-target');
            const element = document.getElementById(targetId);
            if (element) {
                window.scrollTo({
                    top: element.offsetTop - 160,
                    behavior: 'smooth'
                });
            }
        });
    });

    // 2. Чат
    const socket = io();
    const chatToggle = document.getElementById('chat-toggle');
    const chatWindow = document.getElementById('chat-window');
    const chatInput = document.getElementById('chat-input');
    const chatSend = document.getElementById('chat-send');
    const chatMessages = document.getElementById('chat-messages');

    chatToggle.onclick = () => chatWindow.classList.toggle('chat-hidden');

    chatSend.onclick = () => {
        if (chatInput.value.trim()) {
            socket.emit('message_to_server', {
                text: chatInput.value,
                sender: 'user'
            });
            chatInput.value = '';
        }
    };

    socket.on('message_to_client', (data) => {
        const msgDiv = document.createElement('div');
        msgDiv.className = `chat-msg ${data.sender}`;
        msgDiv.innerText = data.text;
        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
});
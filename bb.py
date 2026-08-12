from flask import Flask, render_template_string
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bi_mat_123456'

socketio = SocketIO(app, cors_allowed_origins="*")

# Giao diện HTML được nhúng trực tiếp vào file Python
HTML_CODE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat Web - Single File</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; background-color: #1e1e2e; color: #fff; margin: 0; padding: 20px; display: flex; justify-content: center; }
        .chat-container { width: 100%; max-width: 500px; background: #2b2b3b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.3); }
        h2 { text-align: center; margin-top: 0; color: #89b4fa; }
        #chat-box { height: 300px; border: 1px solid #45475a; border-radius: 8px; overflow-y: auto; padding: 10px; background: #181825; margin-bottom: 15px; }
        .msg { margin-bottom: 10px; padding: 6px 10px; border-radius: 6px; background: #313244; }
        .msg strong { color: #f9e2af; }
        .input-group { display: flex; gap: 8px; }
        input[type="text"] { padding: 10px; border: 1px solid #45475a; border-radius: 6px; background: #11111b; color: #fff; outline: none; }
        #username { width: 30%; }
        #message { flex-grow: 1; }
        button { padding: 10px 15px; border: none; border-radius: 6px; background: #89b4fa; color: #11111b; font-weight: bold; cursor: pointer; }
        button:hover { background: #b4befe; }
    </style>
</head>
<body>

<div class="chat-container">
    <h2>Ứng Dụng Chat Web</h2>
    <div id="chat-box"></div>
    <div class="input-group">
        <input type="text" id="username" placeholder="Tên cậu..." value="Bạn">
        <input type="text" id="message" placeholder="Nhập tin nhắn..." onkeydown="if(event.key==='Enter') sendMessage()">
        <button onclick="sendMessage()">Gửi</button>
    </div>
</div>

<script>
    const socket = io();
    const chatBox = document.getElementById('chat-box');

    socket.on('response_message', function(data) {
        const msgDiv = document.createElement('div');
        msgDiv.classList.add('msg');
        msgDiv.innerHTML = `<strong>${data.username}:</strong> ${data.message}`;
        chatBox.appendChild(msgDiv);
        chatBox.scrollTop = chatBox.scrollHeight;
    });

    function sendMessage() {
        const usernameInput = document.getElementById('username');
        const messageInput = document.getElementById('message');
        const user = usernameInput.value.trim();
        const msg = messageInput.value.trim();

        if (msg !== "") {
            socket.emit('message', { username: user, message: msg });
            messageInput.value = "";
        }
    }
</script>

</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@socketio.on('message')
def handle_message(data):
    user = data.get('username', 'Ẩn danh')
    msg = data.get('message', '')
    print(f"[{user}]: {msg}")
    emit('response_message', {'username': user, 'message': msg}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
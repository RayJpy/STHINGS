import sqlite3
import os
import io
from flask import Flask, render_template_string, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'bi_mat_123456'

socketio = SocketIO(app, cors_allowed_origins="*")

MAX_FILES = 10  # Số lượng file tối đa muốn lưu trữ

# 1. KHỞI TẠO CƠ SỞ DỮ LIỆU SQLITE
def init_db():
    conn = sqlite3.connect('txt_storage.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS txt_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            filesize INTEGER NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# 2. GIAO DIỆN HTML + JAVASCRIPT
HTML_CODE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kho Lưu Trữ File TXT</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e2e; color: #cdd6f4; margin: 0; padding: 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 750px; background: #2b2b3b; padding: 25px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.4); }
        h2 { text-align: center; margin-top: 0; color: #89b4fa; }
        .upload-area { border: 2px dashed #45475a; border-radius: 8px; padding: 20px; text-align: center; background: #181825; margin-bottom: 20px; cursor: pointer; }
        .upload-area:hover { border-color: #89b4fa; }
        input[type="file"] { display: none; }
        .btn-upload { padding: 10px 20px; border: none; border-radius: 6px; background: #89b4fa; color: #11111b; font-weight: bold; cursor: pointer; display: inline-block; margin-top: 10px; }
        .btn-upload:hover { background: #b4befe; }
        #file-list { display: flex; flex-direction: column; gap: 12px; }
        .file-card { background: #313244; border-radius: 8px; padding: 15px; border-left: 4px solid #89b4fa; }
        .file-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .file-name { font-weight: bold; color: #f9e2af; word-break: break-all; }
        .file-meta { font-size: 0.8em; color: #a6adc8; }
        .file-preview { background: #11111b; padding: 10px; border-radius: 6px; font-family: monospace; white-space: pre-wrap; word-break: break-all; max-height: 100px; overflow-y: auto; font-size: 0.9em; margin-bottom: 12px; border: 1px solid #45475a; }
        .action-btns { display: flex; gap: 8px; }
        .btn { padding: 6px 12px; border: none; border-radius: 4px; font-weight: bold; text-decoration: none; cursor: pointer; font-size: 0.85em; display: inline-block; }
        .btn-view { background: #89b4fa; color: #11111b; }
        .btn-view:hover { background: #b4befe; }
        .btn-modal { background: #f9e2af; color: #11111b; }
        .btn-modal:hover { background: #fae3b0; }
        .btn-download { background: #a6e3a1; color: #11111b; }
        .btn-download:hover { background: #94e2d5; }
        
        /* Style cho Modal Popup */
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.7); z-index: 1000; justify-content: center; align-items: center; }
        .modal-box { background: #2b2b3b; width: 90%; max-width: 700px; height: 80vh; padding: 20px; border-radius: 12px; display: flex; flex-direction: column; box-shadow: 0 5px 20px rgba(0,0,0,0.5); }
        .modal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .modal-title { color: #89b4fa; margin: 0; font-size: 1.2em; word-break: break-all; }
        .modal-content-area { flex: 1; background: #11111b; color: #cdd6f4; border: 1px solid #45475a; padding: 12px; font-family: monospace; font-size: 0.9em; border-radius: 6px; resize: none; outline: none; }
        .modal-close { margin-top: 12px; align-self: flex-end; background: #f38ba8; color: #11111b; }
    </style>
</head>
<body>

<div class="container">
    <h2>Kho Lưu Trữ File TXT Gần Nhất</h2>

    <div class="upload-area" onclick="document.getElementById('fileInput').click()">
        <p style="margin:0;">Kéo thả hoặc nhấn vào đây để chọn file <strong>.txt</strong></p>
        <input type="file" id="fileInput" accept=".txt" onchange="uploadFile(this.files)">
        <button class="btn-upload">Tải file lên</button>
    </div>

    <div id="file-list"></div>
</div>

<!-- Modal Popup Xem Nhanh -->
<div id="viewModal" class="modal-overlay">
    <div class="modal-box">
        <div class="modal-header">
            <h3 id="modalTitle" class="modal-title"></h3>
        </div>
        <textarea id="modalContent" class="modal-content-area" readonly></textarea>
        <button class="btn modal-close" onclick="closeModal()">Đóng</button>
    </div>
</div>

<script>
    const socket = io();
    const fileListDiv = document.getElementById('file-list');

    socket.on('load_files', function(files) {
        fileListDiv.innerHTML = '';
        files.forEach(file => appendFileUI(file));
    });

    socket.on('new_file', function(files) {
        fileListDiv.innerHTML = '';
        files.forEach(file => appendFileUI(file));
    });

    function appendFileUI(file) {
        const card = document.createElement('div');
        card.className = 'file-card';
        
        // Encode an toàn dữ liệu để truyền vào hàm onclick JavaScript
        const encodedContent = encodeURIComponent(file.content);
        const encodedFilename = encodeURIComponent(file.filename);

        card.innerHTML = `
            <div class="file-header">
                <span class="file-name">📄 ${escapeHtml(file.filename)}</span>
                <span class="file-meta">${file.filesize} bytes | ${file.timestamp}</span>
            </div>
            <div class="file-preview">${escapeHtml(file.content)}</div>
            <div class="action-btns">
                <button onclick="openModal('${encodedFilename}', '${encodedContent}')" class="btn btn-modal">Xem nhanh</button>
                <a href="/view/${file.id}" target="_blank" class="btn btn-view">Mở Tab mới</a>
                <a href="/download/${file.id}" class="btn btn-download">Tải về (.txt)</a>
            </div>
        `;
        fileListDiv.appendChild(card);
    }

    function uploadFile(files) {
        if (files.length === 0) return;
        const file = files[0];

        if (!file.name.endsWith('.txt')) {
            alert('Chỉ hỗ trợ lưu trữ file .txt!');
            return;
        }

        const reader = new FileReader();
        reader.onload = function(e) {
            const content = e.target.result;
            socket.emit('upload_txt', {
                filename: file.name,
                content: content,
                filesize: file.size
            });
            document.getElementById('fileInput').value = '';
        };
        reader.readAsText(file);
    }

    function openModal(encFilename, encContent) {
        document.getElementById('modalTitle').innerText = decodeURIComponent(encFilename);
        document.getElementById('modalContent').value = decodeURIComponent(encContent);
        document.getElementById('viewModal').style.display = 'flex';
    }

    function closeModal() {
        document.getElementById('viewModal').style.display = 'none';
    }

    function escapeHtml(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
</script>

</body>
</html>
"""

def get_recent_files():
    """Hàm lấy các file mới nhất trong DB (Tối đa MAX_FILES)"""
    conn = sqlite3.connect('txt_storage.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, filename, content, filesize, timestamp FROM txt_files ORDER BY id DESC LIMIT ?", (MAX_FILES,))
    rows = cursor.fetchall()
    conn.close()

    return [{
        'id': row[0],
        'filename': row[1],
        'content': row[2],
        'filesize': row[3],
        'timestamp': row[4]
    } for row in rows]

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@app.route('/view/<int:file_id>')
def view_file(file_id):
    """API xem trực tiếp toàn bộ nội dung file dạng văn bản trên tab trình duyệt mới"""
    conn = sqlite3.connect('txt_storage.db')
    cursor = conn.cursor()
    cursor.execute("SELECT content FROM txt_files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0], 200, {'Content-Type': 'text/plain; charset=utf-8'}
    return "File không tồn tại", 404

@app.route('/download/<int:file_id>')
def download_file(file_id):
    """API hỗ trợ tải file về máy"""
    conn = sqlite3.connect('txt_storage.db')
    cursor = conn.cursor()
    cursor.execute("SELECT filename, content FROM txt_files WHERE id = ?", (file_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        filename, content = row
        buffer = io.BytesIO()
        buffer.write(content.encode('utf-8'))
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='text/plain'
        )
    return "File không tồn tại", 404

@socketio.on('connect')
def handle_connect():
    emit('load_files', get_recent_files())

@socketio.on('upload_txt')
def handle_upload(data):
    filename = data.get('filename', 'untitled.txt')
    content = data.get('content', '')
    filesize = data.get('filesize', 0)

    if content.strip():
        conn = sqlite3.connect('txt_storage.db')
        cursor = conn.cursor()

        cursor.execute("INSERT INTO txt_files (filename, content, filesize) VALUES (?, ?, ?)", 
                       (filename, content, filesize))
        conn.commit()

        cursor.execute("""
            DELETE FROM txt_files 
            WHERE id NOT IN (
                SELECT id FROM txt_files ORDER BY id DESC LIMIT ?
            )
        """, (MAX_FILES,))
        conn.commit()
        conn.close()

        emit('new_file', get_recent_files(), broadcast=True)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
    

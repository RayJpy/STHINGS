from gevent import monkey
monkey.patch_all()

import os
import io
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, send_file
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bi_mat_123456')

# Khởi tạo SocketIO với gevent
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*")

MAX_FILES = 10  # Số lượng file tối đa lưu trữ trong DB

def get_db_connection():
    """Tạo kết nối tới PostgreSQL Neon.tech với tự động cấu hình SSL"""
    db_url = os.environ.get('DATABASE_URL')
    
    # Bắt lỗi ngay nếu quên đặt DATABASE_URL trên Render Environment
    if not db_url:
        raise ValueError("Chưa cấu hình biến môi trường DATABASE_URL trên Render Environment!")
        
    # Ép prefix postgresql:// nếu chuỗi bắt đầu bằng postgres://
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    # Thêm tham số sslmode=require bắt buộc cho Neon.tech Cloud
    if "sslmode" not in db_url and "localhost" not in db_url:
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"

    conn = psycopg2.connect(db_url)
    return conn

# 1. KHỞI TẠO CƠ SỞ DỮ LIỆU POSTGRESQL
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS txt_files (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                filesize INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        print(">>> [SUCCESS] Khởi tạo PostgreSQL Database thành công!")
    except Exception as e:
        print(f">>> [ERROR] Lỗi khởi tạo CSDL PostgreSQL: {e}")

# Call khởi tạo bảng khi app chạy
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
        .upload-area { border: 2px dashed #45475a; border-radius: 8px; padding: 25px; text-align: center; background: #181825; margin-bottom: 20px; cursor: pointer; }
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
    <h2>Kho Lưu Trữ File TXT (PostgreSQL)</h2>

    <div class="upload-area" onclick="document.getElementById('fileInput').click()">
        <p style="margin:0;">Kéo thả hoặc nhấn vào đây để chọn file <strong>.txt</strong></p>
        <input type="file" id="fileInput" accept=".txt">
        <button class="btn-upload" type="button">Tải file lên</button>
    </div>

    <div id="file-list"></div>
</div>

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
    const socket = io({
        transports: ['polling', 'websocket'],
        upgrade: true
    });

    const fileListDiv = document.getElementById('file-list');
    const fileInput = document.getElementById('fileInput');

    socket.on('connect', function() {
        console.log('Đã kết nối SocketIO thành công!');
    });

    socket.on('load_files', renderFiles);
    socket.on('new_file', renderFiles);
    
    socket.on('error_msg', function(data) {
        alert('Lỗi Server DB: ' + data.error);
    });

    function renderFiles(files) {
        fileListDiv.innerHTML = '';
        if (!files || files.length === 0) {
            fileListDiv.innerHTML = '<p style="text-align:center; color:#a6adc8;">Chưa có file nào trong Database.</p>';
        } else {
            files.forEach(file => appendFileUI(file));
        }
    }

    function appendFileUI(file) {
        const card = document.createElement('div');
        card.className = 'file-card';
        
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

    fileInput.addEventListener('change', function(e) {
        const files = e.target.files;
        if (files.length === 0) return;
        const file = files[0];

        if (!file.name.endsWith('.txt')) {
            alert('Chỉ hỗ trợ lưu trữ file .txt!');
            return;
        }

        const reader = new FileReader();
        reader.onload = function(evt) {
            const content = evt.target.result;
            socket.emit('upload_txt', {
                filename: file.name,
                content: content,
                filesize: file.size
            });
            fileInput.value = '';
        };
        reader.readAsText(file);
    });

    function openModal(encFilename, encContent) {
        document.getElementById('modalTitle').innerText = decodeURIComponent(encFilename);
        document.getElementById('modalContent').value = decodeURIComponent(encContent);
        document.getElementById('viewModal').style.display = 'flex';
    }

    function closeModal() {
        document.getElementById('viewModal').style.display = 'none';
    }

    function escapeHtml(text) {
        if (!text) return '';
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
</script>

</body>
</html>
"""

def get_recent_files():
    """Lấy danh sách MAX_FILES gần nhất"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(
            "SELECT id, filename, content, filesize, TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS') as timestamp "
            "FROM txt_files ORDER BY id DESC LIMIT %s", 
            (MAX_FILES,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f">>> Lỗi get_recent_files: {e}")
        return []

@app.route('/')
def index():
    return render_template_string(HTML_CODE)

@app.route('/view/<int:file_id>')
def view_file(file_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM txt_files WHERE id = %s", (file_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return row[0], 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        print(f">>> Lỗi view_file: {e}")
    return "File không tồn tại", 404

@app.route('/download/<int:file_id>')
def download_file(file_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT filename, content FROM txt_files WHERE id = %s", (file_id,))
        row = cursor.fetchone()
        cursor.close()
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
    except Exception as e:
        print(f">>> Lỗi download_file: {e}")
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
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # 1. Chèn file mới
            cursor.execute(
                "INSERT INTO txt_files (filename, content, filesize) VALUES (%s, %s, %s)", 
                (filename, content, filesize)
            )
            conn.commit()

            # 2. Xóa bớt file cũ quá giới hạn MAX_FILES
            cursor.execute("""
                DELETE FROM txt_files 
                WHERE id NOT IN (
                    SELECT id FROM txt_files ORDER BY id DESC LIMIT %s
                )
            """, (MAX_FILES,))
            conn.commit()

            cursor.close()
            conn.close()

            # Bắn danh sách mới về toàn bộ client
            emit('new_file', get_recent_files(), broadcast=True)
        except Exception as e:
            print(f">>> Lỗi upload_txt: {e}")
            emit('error_msg', {'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)

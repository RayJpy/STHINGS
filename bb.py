from gevent import monkey
monkey.patch_all()

import os
import io
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, send_file, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bi_mat_123456')

socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins="*")

MAX_FILES = 13


def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')

    if not db_url:
        raise ValueError("Chưa cấu hình biến môi trường DATABASE_URL trên Render Environment!")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    if "sslmode" not in db_url and "localhost" not in db_url:
        if "?" in db_url:
            db_url += "&sslmode=require"
        else:
            db_url += "?sslmode=require"

    return psycopg2.connect(db_url)


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
        pass


init_db()


def save_txt_file(filename: str, content: str, filesize: int | None = None):
    """Lưu file .txt vào DB, giữ tối đa MAX_FILES và trả về danh sách file mới nhất."""
    clean_name = (filename or "untitled.txt").strip()
    if not clean_name.lower().endswith(".txt"):
        clean_name += ".txt"

    if not content or not content.strip():
        raise ValueError("Nội dung file trống!")

    actual_size = filesize if filesize is not None else len(content.encode("utf-8"))

    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Chèn file mới
    cursor.execute(
        "INSERT INTO txt_files (filename, content, filesize) VALUES (%s, %s, %s)",
        (clean_name, content, actual_size)
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

    return get_recent_files()


def get_recent_files():
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
        pass
        return []


# 2. GIAO DIỆN TRANG CHÍNH
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
        .top-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
        h2 { margin: 0; color: #89b4fa; }
        .quick-link { background: #313244; color: #f9e2af; text-decoration: none; padding: 8px 12px; border-radius: 6px; font-size: 0.85em; border: 1px solid #45475a; }
        .quick-link:hover { border-color: #f9e2af; }
        .upload-area { border: 2px dashed #45475a; border-radius: 8px; padding: 25px; text-align: center; background: #181825; margin-bottom: 20px; cursor: pointer; }
        .upload-area:hover { border-color: #89b4fa; }
        input[type="file"] { display: none; }
        .btn-upload { padding: 10px 20px; border: none; border-radius: 6px; background: #89b4fa; color: #11111b; font-weight: bold; cursor: pointer; display: inline-block; margin-top: 10px; }
        .btn-upload:hover { background: #b4befe; }
        #file-list { display: flex; flex-direction: column; gap: 12px; }
        .file-card { background: #313244; border-radius: 8px; padding: 15px; border-left: 4px solid #89b4fa; }
        .file-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 10px; }
        .file-name { font-weight: bold; color: #f9e2af; word-break: break-all; }
        .file-meta { font-size: 0.8em; color: #a6adc8; white-space: nowrap; }
        .file-preview { background: #11111b; padding: 10px; border-radius: 6px; font-family: monospace; white-space: pre-wrap; word-break: break-all; max-height: 100px; overflow-y: auto; font-size: 0.9em; margin-bottom: 12px; border: 1px solid #45475a; }
        .action-btns { display: flex; gap: 8px; flex-wrap: wrap; }
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
    <div class="top-bar">
        <h2>Kho Lưu Trữ File TXT (PostgreSQL)</h2>
        <a href="/upload/wda" class="quick-link">Link upload nhanh: /upload/wda</a>
    </div>

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
                <button type="button" class="btn btn-modal" data-filename="${encodedFilename}" data-content="${encodedContent}" onclick="openModalFromBtn(this)">Xem nhanh</button>
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

        if (!file.name.toLowerCase().endsWith('.txt')) {
            alert('Chỉ hỗ trợ lưu trữ file .txt!');
            return;
        }

        const reader = new FileReader();
        reader.onload = function(evt) {
            socket.emit('upload_txt', {
                filename: file.name,
                content: evt.target.result,
                filesize: file.size
            });
            fileInput.value = '';
        };
        reader.readAsText(file);
    });

    function openModalFromBtn(btn) {
        const encFilename = btn.getAttribute('data-filename') || '';
        const encContent = btn.getAttribute('data-content') || '';
        document.getElementById('modalTitle').innerText = decodeURIComponent(encFilename);
        document.getElementById('modalContent').value = decodeURIComponent(encContent);
        document.getElementById('viewModal').style.display = 'flex';
    }

    function closeModal() {
        document.getElementById('viewModal').style.display = 'none';
    }

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }
</script>

</body>
</html>
"""

# 3. GIAO DIỆN CHUYÊN DỤNG CHO /upload/wda
UPLOAD_WDA_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Upload File TXT - WDA</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e2e; color: #cdd6f4; margin: 0; padding: 20px; display: flex; justify-content: center; align-items: center; min-height: 100vh; box-sizing: border-box; }
        .box { width: 100%; max-width: 520px; background: #2b2b3b; padding: 28px; border-radius: 12px; box-shadow: 0 4px 18px rgba(0,0,0,0.45); }
        h2 { margin: 0 0 8px 0; color: #f9e2af; }
        .sub { color: #a6adc8; font-size: 0.9em; margin-bottom: 20px; }
        .dropzone { border: 2px dashed #45475a; border-radius: 8px; padding: 26px; text-align: center; background: #181825; cursor: pointer; margin-bottom: 16px; }
        .dropzone.dragover, .dropzone:hover { border-color: #a6e3a1; }
        input[type="file"] { display: none; }
        .btn { width: 100%; padding: 11px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; font-size: 0.95em; }
        .btn-primary { background: #a6e3a1; color: #11111b; }
        .btn-primary:hover { background: #94e2d5; }
        .status { margin-top: 14px; padding: 10px 12px; border-radius: 6px; font-size: 0.9em; display: none; white-space: pre-wrap; }
        .status.ok { display: block; background: rgba(166, 227, 161, 0.15); color: #a6e3a1; border: 1px solid #a6e3a1; }
        .status.err { display: block; background: rgba(243, 139, 168, 0.15); color: #f38ba8; border: 1px solid #f38ba8; }
        .footer-links { margin-top: 18px; display: flex; justify-content: space-between; font-size: 0.9em; }
        .footer-links a { color: #89b4fa; text-decoration: none; }
        .footer-links a:hover { text-decoration: underline; }
    </style>
</head>
<body>
<div class="box">
    <h2>Upload File (.txt) — /upload/wda</h2>
    <div class="sub">Chọn hoặc kéo thả file <strong>.txt</strong> để đẩy thẳng vào Database và cập nhật real-time.</div>

    <div id="dropzone" class="dropzone" onclick="document.getElementById('wdaFileInput').click()">
        <div id="chosenName">Nhấn để chọn file <strong>.txt</strong> hoặc kéo thả vào đây</div>
        <input type="file" id="wdaFileInput" accept=".txt">
    </div>

    <button id="submitBtn" class="btn btn-primary" type="button">Gửi file lên</button>
    <div id="statusBox" class="status"></div>

    <div class="footer-links">
        <a href="/">← Về trang danh sách file</a>
    </div>
</div>

<script>
    const socket = io({
        transports: ['polling', 'websocket'],
        upgrade: true
    });

    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('wdaFileInput');
    const chosenName = document.getElementById('chosenName');
    const submitBtn = document.getElementById('submitBtn');
    const statusBox = document.getElementById('statusBox');
    let selectedFile = null;

    function showStatus(msg, isError = false) {
        statusBox.textContent = msg;
        statusBox.className = 'status ' + (isError ? 'err' : 'ok');
    }

    function setFile(file) {
        if (!file) return;
        if (!file.name.toLowerCase().endsWith('.txt')) {
            selectedFile = null;
            chosenName.innerHTML = 'Nhấn để chọn file <strong>.txt</strong> hoặc kéo thả vào đây';
            showStatus('Chỉ hỗ trợ file định dạng .txt!', true);
            return;
        }
        selectedFile = file;
        chosenName.innerHTML = `Đã chọn: <strong>${file.name}</strong> (${file.size} bytes)`;
        statusBox.className = 'status';
    }

    fileInput.addEventListener('change', (e) => setFile(e.target.files[0]));

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) {
            setFile(e.dataTransfer.files[0]);
        }
    });

    submitBtn.addEventListener('click', () => {
        if (!selectedFile) {
            showStatus('Vui lòng chọn một file .txt trước khi gửi!', true);
            return;
        }
        const reader = new FileReader();
        reader.onload = (evt) => {
            const payload = {
                filename: selectedFile.name,
                content: evt.target.result,
                filesize: selectedFile.size
            };
            if (socket.connected) {
                socket.emit('upload_txt', payload);
                showStatus(`Đã gửi "${selectedFile.name}" thành công!`);
                selectedFile = null;
                fileInput.value = '';
                chosenName.innerHTML = 'Nhấn để chọn file <strong>.txt</strong> hoặc kéo thả vào đây';
            } else {
                // Fallback qua HTTP POST nếu socket chưa kịp kết nối
                fetch('/upload/wda', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
                .then(({ ok, data }) => {
                    if (ok) {
                        showStatus(`Đã upload "${data.filename}" thành công!`);
                        selectedFile = null;
                        fileInput.value = '';
                        chosenName.innerHTML = 'Nhấn để chọn file <strong>.txt</strong> hoặc kéo thả vào đây';
                    } else {
                        showStatus(data.error || 'Upload thất bại!', true);
                    }
                })
                .catch(err => showStatus('Lỗi kết nối: ' + err.message, true));
            }
        };
        reader.readAsText(selectedFile);
    });

    socket.on('error_msg', (data) => {
        showStatus('Lỗi Server DB: ' + data.error, true);
    });
</script>
</body>
</html>
"""


@app.route('/')
def index():
    return render_template_string(HTML_CODE)


@app.route('/upload/wda', methods=['GET', 'POST'])
def upload_wda():
    if request.method == 'GET':
        return render_template_string(UPLOAD_WDA_HTML)

    try:
        if request.is_json:
            data = request.get_json(silent=True) or {}
            filename = data.get('filename', 'untitled.txt')
            content = data.get('content', '')
            filesize = data.get('filesize')
        elif 'file' in request.files:
            f = request.files['file']
            if not f or not f.filename:
                return jsonify({"error": "Chưa chọn file"}), 400
            if not f.filename.lower().endswith('.txt'):
                return jsonify({"error": "Chỉ hỗ trợ file .txt"}), 400
            raw = f.read()
            filename = f.filename
            content = raw.decode('utf-8', errors='replace')
            filesize = len(raw)
        else:
            filename = request.form.get('filename', 'untitled.txt')
            content = request.form.get('content', '')
            filesize = None

        files = save_txt_file(filename, content, filesize)
        socketio.emit('new_file', files)
        return jsonify({"message": "Upload thành công", "filename": filename}), 201
    except ValueError as ve:
        pass
    except Exception as e:
        pass


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
        pass


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
    filesize = data.get('filesize')

    if content and content.strip():
        try:
            files = save_txt_file(filename, content, filesize)
            emit('new_file', files, broadcast=True)
        except Exception as e:
            pass


while True:
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)

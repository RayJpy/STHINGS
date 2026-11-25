from gevent import monkey
monkey.patch_all()

import os
import io
import base64
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, send_file, request, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'bi_mat_123456')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_UPLOAD_MB', '50')) * 1024 * 1024

socketio = SocketIO(
    app,
    async_mode='gevent',
    cors_allowed_origins="*",
    max_http_buffer_size=60 * 1024 * 1024
)

MAX_FILES = 13


def get_db_connection():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        raise ValueError("Chưa cấu hình biến môi trường DATABASE_URL!")

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    if "sslmode" not in db_url and "localhost" not in db_url:
        sep = "&" if "?" in db_url else "?"
        db_url += f"{sep}sslmode=require"

    return psycopg2.connect(db_url)


def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS txt_files (
                id SERIAL PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                content BYTEA NOT NULL,
                filesize BIGINT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'txt_files' AND column_name = 'content'
        ''')
        col = cursor.fetchone()
        if col and col[0] in ('text', 'character varying'):
            cursor.execute('''
                ALTER TABLE txt_files
                ALTER COLUMN content TYPE BYTEA USING convert_to(content, 'UTF8')
            ''')
        cursor.execute('''
            ALTER TABLE txt_files
            ALTER COLUMN filesize TYPE BIGINT
        ''')
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print("[init_db error]:", repr(e), flush=True)


init_db()


@app.after_request
def add_quick_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Cache-Control'] = 'no-store'
    return response


def save_binary_file(filename: str, raw_bytes: bytes, filesize: int | None = None):
    clean_name = os.path.basename((filename or "file_khong_ten").strip()) or "file_khong_ten"
    if not raw_bytes:
        raise ValueError("File rỗng!")

    actual_size = int(filesize) if filesize is not None else len(raw_bytes)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO txt_files (filename, content, filesize) VALUES (%s, %s, %s)",
        (clean_name, psycopg2.Binary(raw_bytes), actual_size)
    )
    conn.commit()

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
            "SELECT id, filename, filesize, TO_CHAR(timestamp, 'YYYY-MM-DD HH24:MI:SS') as timestamp "
            "FROM txt_files ORDER BY id DESC LIMIT %s",
            (MAX_FILES,)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print("[get_recent_files error]:", repr(e), flush=True)
        return []


UPLOAD_PAGE_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>Upload File</title>
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
        .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
        .status { margin-top: 14px; padding: 10px 12px; border-radius: 6px; font-size: 0.9em; display: none; white-space: pre-wrap; word-break: break-word; }
        .status.ok { display: block; background: rgba(166, 227, 161, 0.15); color: #a6e3a1; border: 1px solid #a6e3a1; }
        .status.err { display: block; background: rgba(243, 139, 168, 0.15); color: #f38ba8; border: 1px solid #f38ba8; }
        .footer-links { margin-top: 18px; font-size: 0.92em; }
        .footer-links a { color: #89b4fa; text-decoration: none; font-weight: bold; }
        .footer-links a:hover { text-decoration: underline; }
    </style>
</head>
<body>
<div class="box">
    <h2>Upload File</h2>
    <div class="sub">Lưu nguyên file nhị phân (như <strong>.exe</strong>) lên Database.</div>

    <div id="dropzone" class="dropzone" onclick="document.getElementById('fileInput').click()">
        <div id="chosenName">Nhấn để chọn file hoặc kéo thả vào đây</div>
        <input type="file" id="fileInput">
    </div>

    <button id="submitBtn" class="btn btn-primary" type="button">Gửi file lên</button>
    <div id="statusBox" class="status"></div>
</div>

<script>
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('fileInput');
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
        selectedFile = file;
        chosenName.textContent = `Đã chọn: ${file.name} (${file.size} bytes)`;
        statusBox.className = 'status';
    }

    fileInput.addEventListener('change', (e) => setFile(e.target.files[0]));
    dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        if (e.dataTransfer.files.length > 0) setFile(e.dataTransfer.files[0]);
    });

    submitBtn.addEventListener('click', async () => {
        if (!selectedFile) {
            showStatus('Chưa chọn file!', true);
            return;
        }

        submitBtn.disabled = true;
        showStatus(`Đang tải "${selectedFile.name}" lên...`, false);

        try {
            const formData = new FormData();
            formData.append('file', selectedFile);

            const res = await fetch(window.location.pathname, {
                method: 'POST',
                body: formData
            });

            const text = await res.text();
            let data = {};
            try { data = JSON.parse(text); } catch (_) {}

            if (res.ok) {
                showStatus(`Đã upload thành công "${data.filename || selectedFile.name}"`, false);
                selectedFile = null;
                fileInput.value = '';
                chosenName.textContent = 'Nhấn để chọn file hoặc kéo thả vào đây';
            } else {
                showStatus(`Lỗi upload (HTTP ${res.status}): ${data.error || text || 'Không rõ'}`, true);
            }
        } catch (err) {
            showStatus('Lỗi kết nối khi upload: ' + err.message, true);
        } finally {
            submitBtn.disabled = false;
        }
    });
</script>
</body>
</html>
"""

UPLOADED_PAGE_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="robots" content="noindex, nofollow">
    <title>Danh Sách File Đã Upload</title>
    <script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #1e1e2e; color: #cdd6f4; margin: 0; padding: 20px; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 720px; background: #2b2b3b; padding: 24px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.4); }
        h2 { text-align: center; margin-top: 0; color: #89b4fa; }
        .top-bar { margin-bottom: 16px; font-size: 0.9em; }
        .top-bar a { color: #f9e2af; text-decoration: none; font-weight: bold; }
        #file-list { display: flex; flex-direction: column; gap: 10px; }
        .file-card { background: #313244; border-radius: 8px; padding: 14px 16px; border-left: 4px solid #a6e3a1; display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
        .file-info { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
        .file-name { font-weight: bold; color: #f9e2af; word-break: break-all; }
        .file-meta { font-size: 0.82em; color: #a6adc8; }
        .btn-download { padding: 8px 14px; border: none; border-radius: 6px; font-weight: bold; text-decoration: none; cursor: pointer; font-size: 0.88em; background: #a6e3a1; color: #11111b; white-space: nowrap; }
        .btn-download:hover { background: #94e2d5; }
    </style>
</head>
<body>

<div class="container">
    <h2>File Đã Upload</h2>
    <div class="top-bar"><a href="/">← Quay lại trang Upload</a></div>
    <div id="file-list"></div>
</div>

<script>
    const fileListDiv = document.getElementById('file-list');

    function formatSize(bytes) {
        const n = Number(bytes || 0);
        if (n >= 1024 * 1024) return (n / (1024 * 1024)).toFixed(2) + ' MB';
        if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
        return n + ' bytes';
    }

    async function refreshFilesFromApi() {
        try {
            const res = await fetch('/uploaded/api/files', { cache: 'no-store' });
            if (res.ok) {
                const files = await res.json();
                renderFiles(files);
            }
        } catch (_) {}
    }

    refreshFilesFromApi();

    const socket = io({
        transports: ['polling', 'websocket'],
        upgrade: true
    });

    socket.on('load_files', renderFiles);
    socket.on('new_file', function(files) {
        if (Array.isArray(files)) {
            renderFiles(files);
        } else {
            refreshFilesFromApi();
        }
    });
    socket.on('error_msg', function(data) {
        alert('Lỗi Server DB: ' + data.error);
    });

    function renderFiles(files) {
        fileListDiv.innerHTML = '';
        if (!files || files.length === 0) {
            fileListDiv.innerHTML = '<p style="text-align:center; color:#a6adc8;">Chưa có file nào trong Database.</p>';
            return;
        }
        files.forEach(file => {
            const card = document.createElement('div');
            card.className = 'file-card';
            card.innerHTML = `
                <div class="file-info">
                    <span class="file-name">${escapeHtml(file.filename)}</span>
                    <span class="file-meta">${formatSize(file.filesize)} | ${escapeHtml(file.timestamp || '')}</span>
                </div>
                <a href="/uploaded/download/${file.id}" class="btn-download">Tải nguyên file</a>
            `;
            fileListDiv.appendChild(card);
        });
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


@app.route('/', methods=['GET', 'POST'])
def index_upload():
    if request.method == 'GET':
        return render_template_string(UPLOAD_PAGE_HTML)

    try:
        if 'file' in request.files:
            f = request.files['file']
            if not f or not f.filename:
                return jsonify({"error": "Chưa chọn file"}), 400
            raw = f.read()
            files = save_binary_file(f.filename, raw, len(raw))
            socketio.emit('new_file', files)
            return jsonify({"message": "OK", "filename": f.filename}), 201

        data = request.get_json(silent=True) or {}
        filename = data.get('filename', 'file_khong_ten')
        if 'content_b64' in data:
            raw = base64.b64decode(data['content_b64'])
        else:
            raw = (data.get('content') or '').encode('utf-8')
        files = save_binary_file(filename, raw, data.get('filesize'))
        socketio.emit('new_file', files)
        return jsonify({"message": "OK", "filename": filename}), 201
    except Exception as e:
        print("[upload error]:", repr(e), flush=True)
        return jsonify({"error": str(e)}), 500


@app.route('/uploaded/')
@app.route('/uploaded')
def uploaded_list_page():
    return render_template_string(UPLOADED_PAGE_HTML)


@app.route('/uploaded/api/files')
@app.route('/api/files')
def api_files():
    return jsonify(get_recent_files())


@app.route('/uploaded/download/<int:file_id>')
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
            filename, raw = row
            return send_file(
                io.BytesIO(bytes(raw)),
                as_attachment=True,
                download_name=filename,
                mimetype='application/octet-stream'
            )
    except Exception as e:
        print("[download_file error]:", repr(e), flush=True)
    return "File không tồn tại", 404


@socketio.on('connect')
def handle_connect():
    emit('load_files', get_recent_files())


@socketio.on('upload_file')
def handle_upload_socket(data):
    filename = data.get('filename', 'file_khong_ten')
    filesize = data.get('filesize')
    try:
        if 'content_b64' in data:
            raw = base64.b64decode(data['content_b64'])
        else:
            raw = (data.get('content') or '').encode('utf-8')
        files = save_binary_file(filename, raw, filesize)
        emit('new_file', files, broadcast=True)
    except Exception as e:
        print("[socket upload error]:", repr(e), flush=True)
        emit('error_msg', {'error': str(e)})


while True:
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=True)

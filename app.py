from flask import Flask, request, jsonify, render_template, g
import sqlite3
import os
from datetime import datetime
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'orguser.db')

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['DATABASE'] = DB_PATH
app.config['JSON_SORT_KEYS'] = False

# --- Database helpers (sqlite3, no SQLAlchemy) ---
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(app.config['DATABASE'])
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    cur = db.cursor()
    # organizations table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS organizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        support_email TEXT,
        phone TEXT,
        alt_phone TEXT,
        website TEXT,
        max_coordinators INTEGER DEFAULT 5,
        timezone TEXT DEFAULT 'Asia/Kolkata',
        language TEXT DEFAULT 'English',
        status TEXT DEFAULT 'Active',
        pending_requests INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    # users table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        org_id INTEGER,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        role TEXT NOT NULL,
        phone TEXT,
        timezone TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (org_id) REFERENCES organizations(id) ON DELETE CASCADE
    )
    ''')
    db.commit()

    # Seed with sample data if empty
    cur.execute('SELECT COUNT(*) as c FROM organizations')
    if cur.fetchone()['c'] == 0:
        cur.execute('''
        INSERT INTO organizations (name, slug, support_email, phone, alt_phone, website, max_coordinators, timezone, language, status, pending_requests)
        VALUES 
        ('Massachusetts Institute of Technology', 'mit', 'support@mit.edu', '+1-617-253-1000', '+1-617-253-9999', 'https://mit.edu', 5, 'America/New_York', 'English', 'Active', 45),
        ('GITAM Institute of Technology', 'gitam', 'gitam@gitam.in', '+91-9676456543', '+91-93473294913', 'https://gitam.edu', 5, 'Asia/Kolkata', 'English', 'Active', 45)
        ''')
        db.commit()

    cur.execute('SELECT COUNT(*) as c FROM users')
    if cur.fetchone()['c'] == 0:
        # fetch org ids
        cur.execute("SELECT id FROM organizations WHERE slug='gitam'")
        row = cur.fetchone()
        gitam_id = row['id'] if row else 1
        cur.execute("SELECT id FROM organizations WHERE slug='mit'")
        row2 = cur.fetchone()
        mit_id = row2['id'] if row2 else 2

        cur.executemany('''
        INSERT INTO users (org_id, name, email, role, phone, timezone)
        VALUES (?,?,?,?,?,?)
        ''', [
            (gitam_id, 'Dave Richards', 'dave.richards@example.com', 'Admin', '+91-9000000001', 'Asia/Kolkata'),
            (gitam_id, 'Abhishek Hari', 'abhishek.hari@example.com', 'Co-ordinator', '+91-9000000002', 'Asia/Kolkata'),
            (mit_id, 'Nishta Gupta', 'nishta.gupta@example.com', 'Admin', '+1-617-0000003', 'America/New_York'),
        ])
        db.commit()

# Initialize DB on startup
with app.app_context():
    init_db()

# --- HTML routes ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/organizations')
def organizations_page():
    return render_template('organizations.html')

@app.route('/users')
def users_page():
    return render_template('users.html')

# --- REST API endpoints ---
@app.route('/api/organizations', methods=['GET'])
def api_get_organizations():
    db = get_db()
    cur = db.execute('SELECT * FROM organizations ORDER BY id DESC')
    orgs = [dict(r) for r in cur.fetchall()]
    return jsonify(orgs), 200

@app.route('/api/organizations/<int:org_id>', methods=['GET'])
def api_get_organization(org_id):
    db = get_db()
    cur = db.execute('SELECT * FROM organizations WHERE id=?', (org_id,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'Organization not found'}), 404
    return jsonify(dict(row)), 200

@app.route('/api/organizations', methods=['POST'])
def api_create_organization():
    data = request.get_json()
    required = ['name', 'slug']
    for r in required:
        if r not in data or not data[r]:
            return jsonify({'error': f'{r} is required'}), 400
    # sanitize slug
    slug = secure_filename(data['slug']).lower()
    db = get_db()
    try:
        db.execute('''
            INSERT INTO organizations (name, slug, support_email, phone, alt_phone, website, max_coordinators, timezone, language, status, pending_requests)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            data.get('name'),
            slug,
            data.get('support_email'),
            data.get('phone'),
            data.get('alt_phone'),
            data.get('website'),
            int(data.get('max_coordinators') or 5),
            data.get('timezone') or 'Asia/Kolkata',
            data.get('language') or 'English',
            data.get('status') or 'Active',
            int(data.get('pending_requests') or 0)
        ))
        db.commit()
    except sqlite3.IntegrityError as e:
        return jsonify({'error': 'Slug already exists or invalid data'}), 400

    cur = db.execute('SELECT * FROM organizations WHERE slug=?', (slug,))
    row = dict(cur.fetchone())
    return jsonify(row), 201

@app.route('/api/organizations/<int:org_id>/status', methods=['PUT'])
def api_change_org_status(org_id):
    data = request.get_json()
    if 'status' not in data:
        return jsonify({'error': 'status required'}), 400
    db = get_db()
    cur = db.execute('SELECT * FROM organizations WHERE id=?', (org_id,))
    if not cur.fetchone():
        return jsonify({'error': 'Organization not found'}), 404
    db.execute('UPDATE organizations SET status=? WHERE id=?', (data['status'], org_id))
    db.commit()
    cur = db.execute('SELECT * FROM organizations WHERE id=?', (org_id,))
    return jsonify(dict(cur.fetchone())), 200

@app.route('/api/users', methods=['GET'])
def api_get_users():
    db = get_db()
    cur = db.execute('''
        SELECT u.*, o.name as organization_name, o.slug as organization_slug
        FROM users u
        LEFT JOIN organizations o ON u.org_id = o.id
        ORDER BY u.id DESC
    ''')
    users = [dict(r) for r in cur.fetchall()]
    return jsonify(users), 200

@app.route('/api/users', methods=['POST'])
def api_create_user():
    data = request.get_json()
    required = ['name', 'email', 'role', 'org_id']
    for r in required:
        if r not in data or not data[r]:
            return jsonify({'error': f'{r} is required'}), 400

    db = get_db()
    cur = db.execute('SELECT * FROM organizations WHERE id=?', (data['org_id'],))
    if not cur.fetchone():
        return jsonify({'error': 'Organization does not exist'}), 400

    db.execute('''
        INSERT INTO users (org_id, name, email, role, phone, timezone)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        int(data['org_id']),
        data['name'],
        data['email'],
        data['role'],
        data.get('phone'),
        data.get('timezone')
    ))
    db.commit()
    cur = db.execute('SELECT u.*, o.name as organization_name FROM users u LEFT JOIN organizations o ON u.org_id=o.id WHERE u.id = last_insert_rowid()')
    return jsonify(dict(cur.fetchone())), 201

# Simple search endpoints (query params)
@app.route('/api/organizations/search', methods=['GET'])
def api_search_orgs():
    q = request.args.get('q', '').strip()
    db = get_db()
    if not q:
        cur = db.execute('SELECT * FROM organizations ORDER BY id DESC')
    else:
        pattern = f'%{q}%'
        cur = db.execute('SELECT * FROM organizations WHERE name LIKE ? OR slug LIKE ? ORDER BY id DESC', (pattern, pattern))
    return jsonify([dict(r) for r in cur.fetchall()]), 200

@app.route('/api/users/search', methods=['GET'])
def api_search_users():
    q = request.args.get('q', '').strip()
    db = get_db()
    if not q:
        cur = db.execute('''
            SELECT u.*, o.name as organization_name, o.slug as organization_slug
            FROM users u
            LEFT JOIN organizations o ON u.org_id = o.id
            ORDER BY u.id DESC
        ''')
    else:
        pattern = f'%{q}%'
        cur = db.execute('''
            SELECT u.*, o.name as organization_name FROM users u
            LEFT JOIN organizations o ON u.org_id = o.id
            WHERE u.name LIKE ? OR u.email LIKE ? OR o.name LIKE ?
            ORDER BY u.id DESC
        ''', (pattern, pattern, pattern))
    return jsonify([dict(r) for r in cur.fetchall()]), 200

# Run app
if __name__ == '__main__':
    app.run(debug=True)

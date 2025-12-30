#!/usr/bin/env python3
"""
Supabazarr Web Interface
Interface web pour configurer et monitorer les backups
"""

import os
import json
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify, redirect, url_for

# Configuration
CONFIG_FILE = Path('/etc/supabazarr/config.json')
DEVICE_UUID_FILE = Path('/etc/supabazarr/device_uuid')

app = Flask(__name__)

# =============================================================================
# TEMPLATES HTML
# =============================================================================

BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Supabazarr - {{ title }}</title>
    <style>
        :root {
            --bg-dark: #1a1a2e;
            --bg-card: #16213e;
            --accent: #e94560;
            --accent-hover: #ff6b6b;
            --text: #eaeaea;
            --text-muted: #a0a0a0;
            --success: #4ade80;
            --warning: #fbbf24;
            --error: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-dark);
            color: var(--text);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 800px; margin: 0 auto; }
        header {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .logo {
            width: 50px;
            height: 50px;
            background: linear-gradient(135deg, var(--accent), #ff6b6b);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
        }
        h1 { font-size: 1.8rem; font-weight: 600; }
        .subtitle { color: var(--text-muted); font-size: 0.9rem; }
        nav {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
        }
        nav a {
            padding: 10px 20px;
            background: var(--bg-card);
            color: var(--text);
            text-decoration: none;
            border-radius: 8px;
            transition: all 0.2s;
        }
        nav a:hover, nav a.active {
            background: var(--accent);
        }
        .card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
        }
        .card h2 {
            font-size: 1.2rem;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .form-group { margin-bottom: 20px; }
        label {
            display: block;
            margin-bottom: 8px;
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        input[type="text"], input[type="password"], input[type="url"] {
            width: 100%;
            padding: 12px 15px;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 8px;
            color: var(--text);
            font-size: 1rem;
        }
        input:focus {
            outline: none;
            border-color: var(--accent);
        }
        button {
            padding: 12px 25px;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover { background: var(--accent-hover); }
        button.secondary {
            background: rgba(255,255,255,0.1);
        }
        button.secondary:hover {
            background: rgba(255,255,255,0.2);
        }
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .status-success { background: rgba(74, 222, 128, 0.2); color: var(--success); }
        .status-warning { background: rgba(251, 191, 36, 0.2); color: var(--warning); }
        .status-error { background: rgba(239, 68, 68, 0.2); color: var(--error); }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
        }
        .stat-item {
            background: rgba(255,255,255,0.05);
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 2rem;
            font-weight: 700;
            color: var(--accent);
        }
        .stat-label {
            color: var(--text-muted);
            font-size: 0.85rem;
            margin-top: 5px;
        }
        .history-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        .history-item:last-child { border-bottom: none; }
        .alert {
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-success { background: rgba(74, 222, 128, 0.2); color: var(--success); }
        .alert-error { background: rgba(239, 68, 68, 0.2); color: var(--error); }
        .device-info {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }
        .device-info div {
            flex: 1;
            min-width: 200px;
        }
        .mono {
            font-family: 'SF Mono', Monaco, monospace;
            font-size: 0.85rem;
            background: rgba(255,255,255,0.05);
            padding: 2px 6px;
            border-radius: 4px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">S</div>
            <div>
                <h1>Supabazarr</h1>
                <p class="subtitle">Backup automatique vers Supabase</p>
            </div>
        </header>
        <nav>
            <a href="/" class="{{ 'active' if page == 'status' else '' }}">Statut</a>
            <a href="/config" class="{{ 'active' if page == 'config' else '' }}">Configuration</a>
            <a href="/history" class="{{ 'active' if page == 'history' else '' }}">Historique</a>
        </nav>
        {% block content %}{% endblock %}
    </div>
</body>
</html>
'''

STATUS_TEMPLATE = '''
{% extends "base" %}
{% block content %}
{% if message %}
<div class="alert alert-{{ message_type }}">{{ message }}</div>
{% endif %}

<div class="card">
    <h2>Device</h2>
    <div class="device-info">
        <div>
            <label>Hostname</label>
            <p>{{ hostname }}</p>
        </div>
        <div>
            <label>Device UUID</label>
            <p class="mono">{{ device_uuid[:16] }}...</p>
        </div>
        <div>
            <label>Version</label>
            <p>{{ version }}</p>
        </div>
    </div>
</div>

<div class="card">
    <h2>Connexion Supabase</h2>
    {% if supabase_connected %}
    <p><span class="status-badge status-success">Connecté</span></p>
    <p style="margin-top: 10px; color: var(--text-muted);">{{ supabase_url }}</p>
    {% else %}
    <p><span class="status-badge status-error">Non configuré</span></p>
    <p style="margin-top: 10px;"><a href="/config" style="color: var(--accent);">Configurer les credentials →</a></p>
    {% endif %}
</div>

<div class="card">
    <h2>Dernier Backup</h2>
    {% if last_backup %}
    <div class="stats-grid">
        <div class="stat-item">
            <div class="stat-value">{{ last_backup.movies_count }}</div>
            <div class="stat-label">Films</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{{ last_backup.series_count }}</div>
            <div class="stat-label">Séries</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{{ last_backup.indexers_count }}</div>
            <div class="stat-label">Indexeurs</div>
        </div>
        <div class="stat-item">
            <div class="stat-value">{{ last_backup.users_count }}</div>
            <div class="stat-label">Utilisateurs</div>
        </div>
    </div>
    <p style="margin-top: 15px; color: var(--text-muted);">
        {{ last_backup.date }} -
        <span class="status-badge status-{{ 'success' if last_backup.status == 'success' else 'error' }}">
            {{ last_backup.status }}
        </span>
    </p>
    {% else %}
    <p style="color: var(--text-muted);">Aucun backup effectué</p>
    {% endif %}
</div>

<div class="card">
    <h2>Actions</h2>
    <form action="/backup" method="POST" style="display: inline;">
        <button type="submit">Lancer un backup maintenant</button>
    </form>
</div>
{% endblock %}
'''

CONFIG_TEMPLATE = '''
{% extends "base" %}
{% block content %}
{% if message %}
<div class="alert alert-{{ message_type }}">{{ message }}</div>
{% endif %}

<div class="card">
    <h2>Credentials Supabase</h2>
    <form action="/config" method="POST">
        <div class="form-group">
            <label for="supabase_url">Supabase URL</label>
            <input type="url" id="supabase_url" name="supabase_url"
                   value="{{ config.supabase_url or '' }}"
                   placeholder="https://votre-projet.supabase.co">
        </div>
        <div class="form-group">
            <label for="supabase_key">Service Role Key</label>
            <input type="password" id="supabase_key" name="supabase_key"
                   value="{{ config.supabase_key or '' }}"
                   placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...">
            <p style="margin-top: 8px; font-size: 0.85rem; color: var(--text-muted);">
                Trouvez cette clé dans Settings → API → service_role (secret)
            </p>
        </div>
        <div style="display: flex; gap: 10px;">
            <button type="submit">Sauvegarder</button>
            <button type="button" class="secondary" onclick="testConnection()">Tester la connexion</button>
        </div>
    </form>
</div>

<div class="card">
    <h2>Configuration Avancée</h2>
    <div class="form-group">
        <label>Heure du backup quotidien</label>
        <p style="color: var(--text-muted);">03:00 (configurable via variable d'environnement BACKUP_HOUR)</p>
    </div>
    <div class="form-group">
        <label>Chemin Media Stack</label>
        <p class="mono">{{ media_stack_path }}</p>
    </div>
</div>

<script>
function testConnection() {
    const url = document.getElementById('supabase_url').value;
    const key = document.getElementById('supabase_key').value;

    fetch('/api/test-connection', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url, key})
    })
    .then(r => r.json())
    .then(data => {
        alert(data.success ? 'Connexion réussie!' : 'Erreur: ' + data.error);
    });
}
</script>
{% endblock %}
'''

HISTORY_TEMPLATE = '''
{% extends "base" %}
{% block content %}
<div class="card">
    <h2>Historique des Backups</h2>
    {% if history %}
    {% for item in history %}
    <div class="history-item">
        <div>
            <strong>{{ item.date }}</strong>
            <p style="color: var(--text-muted); font-size: 0.85rem;">
                {{ item.movies_count }} films, {{ item.series_count }} séries,
                {{ item.indexers_count }} indexeurs
            </p>
        </div>
        <div>
            <span class="status-badge status-{{ 'success' if item.status == 'success' else 'error' }}">
                {{ item.status }}
            </span>
            <span style="color: var(--text-muted); margin-left: 10px;">{{ item.duration }}s</span>
        </div>
    </div>
    {% endfor %}
    {% else %}
    <p style="color: var(--text-muted);">Aucun historique disponible</p>
    {% endif %}
</div>
{% endblock %}
'''


# =============================================================================
# HELPERS
# =============================================================================

def load_config():
    """Charge la configuration depuis le fichier"""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except:
            pass
    return {
        'supabase_url': os.environ.get('SUPABASE_URL', ''),
        'supabase_key': os.environ.get('SUPABASE_SERVICE_KEY', ''),
    }


def save_config(config):
    """Sauvegarde la configuration"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    # Mettre à jour les variables d'environnement
    os.environ['SUPABASE_URL'] = config.get('supabase_url', '')
    os.environ['SUPABASE_SERVICE_KEY'] = config.get('supabase_key', '')


def get_device_uuid():
    """Récupère l'UUID du device"""
    if DEVICE_UUID_FILE.exists():
        return DEVICE_UUID_FILE.read_text().strip()
    return 'non-configuré'


def get_backup_history():
    """Récupère l'historique des backups depuis Supabase"""
    config = load_config()
    if not config.get('supabase_url') or not config.get('supabase_key'):
        return []

    try:
        from supabase import create_client
        client = create_client(config['supabase_url'], config['supabase_key'])
        device_uuid = get_device_uuid()

        # Récupérer le device_id
        result = client.table('raspberry_devices').select('id').eq('device_uuid', device_uuid).execute()
        if not result.data:
            return []

        device_id = result.data[0]['id']

        # Récupérer l'historique
        history = client.table('backup_history').select('*').eq('device_id', device_id).order('backup_at', desc=True).limit(20).execute()

        return [{
            'date': datetime.fromisoformat(h['backup_at'].replace('Z', '+00:00')).strftime('%d/%m/%Y %H:%M'),
            'status': h['status'],
            'movies_count': h.get('movies_count', 0),
            'series_count': h.get('series_count', 0),
            'indexers_count': h.get('indexers_count', 0),
            'users_count': h.get('users_count', 0),
            'duration': h.get('duration_seconds', 0)
        } for h in history.data]
    except Exception as e:
        print(f"Error fetching history: {e}")
        return []


# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    config = load_config()
    history = get_backup_history()
    last_backup = history[0] if history else None

    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', STATUS_TEMPLATE.replace('{% extends "base" %}', '').replace('{% block content %}', '').replace('{% endblock %}', '')),
        title='Statut',
        page='status',
        hostname=os.environ.get('HOSTNAME', os.uname().nodename),
        device_uuid=get_device_uuid(),
        version='1.0.0',
        supabase_connected=bool(config.get('supabase_url') and config.get('supabase_key')),
        supabase_url=config.get('supabase_url', ''),
        last_backup=last_backup,
        message=request.args.get('message'),
        message_type=request.args.get('type', 'success')
    )


@app.route('/config', methods=['GET', 'POST'])
def config_page():
    message = None
    message_type = 'success'

    if request.method == 'POST':
        config = {
            'supabase_url': request.form.get('supabase_url', '').strip(),
            'supabase_key': request.form.get('supabase_key', '').strip(),
        }
        save_config(config)
        message = 'Configuration sauvegardée!'

    config = load_config()

    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', CONFIG_TEMPLATE.replace('{% extends "base" %}', '').replace('{% block content %}', '').replace('{% endblock %}', '')),
        title='Configuration',
        page='config',
        config=config,
        media_stack_path=os.environ.get('MEDIA_STACK_PATH', '/home/maison/media-stack'),
        message=message,
        message_type=message_type
    )


@app.route('/history')
def history_page():
    history = get_backup_history()

    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', HISTORY_TEMPLATE.replace('{% extends "base" %}', '').replace('{% block content %}', '').replace('{% endblock %}', '')),
        title='Historique',
        page='history',
        history=history
    )


@app.route('/backup', methods=['POST'])
def trigger_backup():
    """Déclenche un backup manuel"""
    try:
        from supabazarr import get_config, SupabazarrBackup
        config = get_config()
        backup = SupabazarrBackup(config)

        # Lancer le backup dans un thread séparé
        def run_backup():
            backup.run_backup()

        thread = threading.Thread(target=run_backup)
        thread.start()

        return redirect('/?message=Backup lancé!&type=success')
    except Exception as e:
        return redirect(f'/?message=Erreur: {str(e)}&type=error')


@app.route('/api/test-connection', methods=['POST'])
def test_connection():
    """Teste la connexion à Supabase"""
    data = request.json
    url = data.get('url', '')
    key = data.get('key', '')

    if not url or not key:
        return jsonify({'success': False, 'error': 'URL et clé requises'})

    try:
        from supabase import create_client
        client = create_client(url, key)
        # Test simple: lister les tables
        client.table('raspberry_devices').select('id').limit(1).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/status')
def api_status():
    """API: Statut du service"""
    config = load_config()
    return jsonify({
        'hostname': os.environ.get('HOSTNAME', os.uname().nodename),
        'device_uuid': get_device_uuid(),
        'version': '1.0.0',
        'supabase_configured': bool(config.get('supabase_url') and config.get('supabase_key'))
    })


def run_web_server(host='0.0.0.0', port=8383):
    """Lance le serveur web"""
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_web_server()

#!/usr/bin/env python3
"""
Supabazarr - Automatic backup service for Media Stack to Supabase
"""

import os
import json
import hashlib
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__, template_folder='/app/templates')

# Configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
HOSTNAME = os.environ.get('HOSTNAME', 'unknown-pi')
MEDIA_STACK_PATH = os.environ.get('MEDIA_STACK_PATH', '/media-stack')
BACKUP_INTERVAL_HOURS = int(os.environ.get('BACKUP_INTERVAL_HOURS', '6'))

# State
last_backup: Optional[datetime] = None
last_backup_status: str = 'never'
backup_history: list = []
installation_id: Optional[str] = None

# Services to backup
SERVICES_TO_BACKUP = [
    {'name': 'jellyfin', 'path': 'jellyfin', 'important_files': ['config/system.xml', 'config/network.xml']},
    {'name': 'radarr', 'path': 'radarr', 'important_files': ['config.xml']},
    {'name': 'sonarr', 'path': 'sonarr', 'important_files': ['config.xml']},
    {'name': 'prowlarr', 'path': 'prowlarr', 'important_files': ['config.xml']},
    {'name': 'bazarr', 'path': 'bazarr', 'important_files': ['config/config.yaml']},
    {'name': 'jellyseerr', 'path': 'jellyseerr', 'important_files': ['settings.json']},
    {'name': 'decypharr', 'path': 'decypharr', 'important_files': ['config.json']},
]


def get_headers() -> Dict[str, str]:
    """Get Supabase API headers"""
    return {
        'apikey': SUPABASE_SERVICE_KEY,
        'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
        'Content-Type': 'application/json'
    }


def get_installation_id() -> Optional[str]:
    """Get or create installation ID from Supabase"""
    global installation_id

    if installation_id:
        return installation_id

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("[Supabazarr] Supabase not configured")
        return None

    try:
        # Check if installation exists
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/pi_installations",
            params={'pi_name': f'eq.{HOSTNAME}', 'select': 'id'},
            headers=get_headers()
        )

        if response.status_code == 200:
            data = response.json()
            if data:
                installation_id = data[0]['id']
                print(f"[Supabazarr] Found installation: {installation_id}")
                return installation_id

        # Create new installation
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/pi_installations",
            headers={**get_headers(), 'Prefer': 'return=representation'},
            json={
                'pi_name': HOSTNAME,
                'status': 'active',
                'last_seen': datetime.utcnow().isoformat()
            }
        )

        if response.status_code == 201:
            data = response.json()
            installation_id = data[0]['id']
            print(f"[Supabazarr] Created installation: {installation_id}")
            return installation_id

    except Exception as e:
        print(f"[Supabazarr] Error getting installation ID: {e}")

    return None


def update_heartbeat():
    """Update last_seen timestamp in Supabase"""
    inst_id = get_installation_id()
    if not inst_id:
        return

    try:
        requests.patch(
            f"{SUPABASE_URL}/rest/v1/pi_installations",
            params={'id': f'eq.{inst_id}'},
            headers=get_headers(),
            json={
                'last_seen': datetime.utcnow().isoformat(),
                'status': 'active'
            }
        )
    except Exception as e:
        print(f"[Supabazarr] Heartbeat error: {e}")


def calculate_checksum(file_path: str) -> str:
    """Calculate MD5 checksum of a file"""
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def backup_service_config(service: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Backup a single service configuration"""
    service_path = Path(MEDIA_STACK_PATH) / service['path']

    if not service_path.exists():
        print(f"[Supabazarr] Service path not found: {service_path}")
        return None

    backup_data = {
        'service': service['name'],
        'timestamp': datetime.utcnow().isoformat(),
        'files': {}
    }

    for file_pattern in service.get('important_files', []):
        file_path = service_path / file_pattern
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                backup_data['files'][file_pattern] = {
                    'content': content,
                    'checksum': hashlib.md5(content.encode()).hexdigest(),
                    'size': len(content)
                }
            except Exception as e:
                print(f"[Supabazarr] Error reading {file_path}: {e}")

    return backup_data


def save_backup_to_supabase(backup_data: Dict[str, Any], service_name: str) -> bool:
    """Save backup data to Supabase"""
    inst_id = get_installation_id()
    if not inst_id:
        return False

    try:
        # Compress backup data
        backup_json = json.dumps(backup_data)
        checksum = hashlib.md5(backup_json.encode()).hexdigest()

        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/pi_backups",
            headers=get_headers(),
            json={
                'installation_id': inst_id,
                'backup_type': 'config',
                'service_name': service_name,
                'file_size': len(backup_json),
                'checksum': checksum,
                'metadata': backup_data
            }
        )

        return response.status_code in [200, 201]

    except Exception as e:
        print(f"[Supabazarr] Error saving backup: {e}")
        return False


def run_backup():
    """Run backup for all services"""
    global last_backup, last_backup_status

    print(f"[Supabazarr] Starting backup at {datetime.now()}")

    success_count = 0
    total_count = 0

    for service in SERVICES_TO_BACKUP:
        total_count += 1
        backup_data = backup_service_config(service)

        if backup_data and backup_data['files']:
            if save_backup_to_supabase(backup_data, service['name']):
                success_count += 1
                print(f"[Supabazarr] Backed up {service['name']}")
            else:
                print(f"[Supabazarr] Failed to save {service['name']} backup")
        else:
            print(f"[Supabazarr] No files to backup for {service['name']}")

    last_backup = datetime.now()
    last_backup_status = f"{success_count}/{total_count} services"

    backup_history.append({
        'timestamp': last_backup.isoformat(),
        'status': last_backup_status,
        'success': success_count,
        'total': total_count
    })

    # Keep only last 50 entries
    if len(backup_history) > 50:
        backup_history.pop(0)

    # Update installation with last backup time
    inst_id = get_installation_id()
    if inst_id:
        try:
            requests.patch(
                f"{SUPABASE_URL}/rest/v1/pi_installations",
                params={'id': f'eq.{inst_id}'},
                headers=get_headers(),
                json={'last_backup': datetime.utcnow().isoformat()}
            )
        except:
            pass

    print(f"[Supabazarr] Backup complete: {last_backup_status}")


# Flask routes
@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html',
        hostname=HOSTNAME,
        supabase_configured=bool(SUPABASE_URL and SUPABASE_SERVICE_KEY),
        last_backup=last_backup.strftime('%Y-%m-%d %H:%M:%S') if last_backup else 'Never',
        last_backup_status=last_backup_status,
        backup_interval=BACKUP_INTERVAL_HOURS,
        services=SERVICES_TO_BACKUP,
        installation_id=installation_id
    )


@app.route('/api/status')
def api_status():
    """API endpoint for status"""
    return jsonify({
        'hostname': HOSTNAME,
        'installation_id': installation_id,
        'supabase_configured': bool(SUPABASE_URL and SUPABASE_SERVICE_KEY),
        'last_backup': last_backup.isoformat() if last_backup else None,
        'last_backup_status': last_backup_status,
        'backup_interval_hours': BACKUP_INTERVAL_HOURS,
        'services_count': len(SERVICES_TO_BACKUP)
    })


@app.route('/api/backup', methods=['POST'])
def api_trigger_backup():
    """Trigger manual backup"""
    threading.Thread(target=run_backup).start()
    return jsonify({'status': 'backup_started'})


@app.route('/api/history')
def api_history():
    """Get backup history"""
    return jsonify(backup_history)


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})


def main():
    """Main entry point"""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                      SUPABAZARR                               ║
║           Automatic Backup for Media Stack                    ║
╠══════════════════════════════════════════════════════════════╣
║  Hostname:     {HOSTNAME:<45} ║
║  Supabase:     {'Configured' if SUPABASE_URL else 'Not configured':<45} ║
║  Backup Every: {BACKUP_INTERVAL_HOURS} hours{' ':<40} ║
║  Web UI:       http://localhost:8383                          ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Initialize installation ID
    get_installation_id()

    # Setup scheduler
    scheduler = BackgroundScheduler()

    # Heartbeat every 5 minutes
    scheduler.add_job(update_heartbeat, 'interval', minutes=5)

    # Backup every N hours
    scheduler.add_job(run_backup, 'interval', hours=BACKUP_INTERVAL_HOURS)

    # Run initial backup after 1 minute
    scheduler.add_job(run_backup, 'date', run_date=datetime.now() + timedelta(minutes=1))

    scheduler.start()

    # Start Flask
    app.run(host='0.0.0.0', port=8383, debug=False)


if __name__ == '__main__':
    main()

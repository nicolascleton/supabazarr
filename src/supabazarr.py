#!/usr/bin/env python3
"""
Supabazarr - Service de sauvegarde automatique pour JellySetup
Sauvegarde quotidienne de la bibliothèque et des paramètres vers Supabase
"""

import os
import sys
import json
import sqlite3
import hashlib
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import xml.etree.ElementTree as ET

try:
    from supabase import create_client, Client
    import httpx
except ImportError:
    print("Installing dependencies...")
    os.system("pip install supabase httpx")
    from supabase import create_client, Client
    import httpx

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('supabazarr')

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Configuration Supabazarr"""
    supabase_url: str
    supabase_key: str  # Service role key
    device_uuid: str
    hostname: str
    media_stack_path: str = "/home/maison/media-stack"

    # Chemins des services
    radarr_path: str = ""
    sonarr_path: str = ""
    prowlarr_path: str = ""
    jellyfin_path: str = ""
    decypharr_path: str = ""
    bazarr_path: str = ""

    def __post_init__(self):
        base = Path(self.media_stack_path)
        self.radarr_path = str(base / "radarr")
        self.sonarr_path = str(base / "sonarr")
        self.prowlarr_path = str(base / "prowlarr")
        self.jellyfin_path = str(base / "jellyfin")
        self.decypharr_path = str(base / "decypharr")
        self.bazarr_path = str(base / "bazarr")


def get_config() -> Config:
    """Charge la configuration depuis les variables d'environnement"""
    return Config(
        supabase_url=os.environ.get('SUPABASE_URL', ''),
        supabase_key=os.environ.get('SUPABASE_SERVICE_KEY', ''),
        device_uuid=os.environ.get('DEVICE_UUID', get_or_create_device_uuid()),
        hostname=os.environ.get('HOSTNAME', os.uname().nodename),
        media_stack_path=os.environ.get('MEDIA_STACK_PATH', '/home/maison/media-stack')
    )


def get_or_create_device_uuid() -> str:
    """Génère ou récupère l'UUID unique du device"""
    uuid_file = Path('/etc/supabazarr/device_uuid')

    if uuid_file.exists():
        return uuid_file.read_text().strip()

    # Générer un UUID basé sur le MAC address si disponible
    try:
        mac = open('/sys/class/net/eth0/address').read().strip()
        device_uuid = hashlib.sha256(mac.encode()).hexdigest()[:32]
    except:
        import uuid
        device_uuid = str(uuid.uuid4()).replace('-', '')

    # Sauvegarder
    uuid_file.parent.mkdir(parents=True, exist_ok=True)
    uuid_file.write_text(device_uuid)

    return device_uuid


# =============================================================================
# EXTRACTEURS DE DONNÉES
# =============================================================================

class RadarrExtractor:
    """Extrait les données de Radarr"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.db_path = self.path / "radarr.db"
        self.config_path = self.path / "config.xml"

    def extract_movies(self) -> List[Dict]:
        """Extrait la liste des films"""
        if not self.db_path.exists():
            logger.warning(f"Radarr DB not found: {self.db_path}")
            return []

        movies = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    m.Id as radarr_id,
                    m.Title as title,
                    m.OriginalTitle as original_title,
                    m.Year as year,
                    mm.TmdbId as tmdb_id,
                    mm.ImdbId as imdb_id,
                    mm.Overview as overview,
                    mm.Studio as studio,
                    m.QualityProfileId as quality_profile_id,
                    m.Path as path,
                    m.Monitored as monitored,
                    mm.Status as status,
                    mm.Runtime as runtime,
                    m.Added as added_at,
                    (SELECT COUNT(*) FROM MovieFiles mf WHERE mf.MovieId = m.Id) > 0 as has_file,
                    (SELECT Size FROM MovieFiles mf WHERE mf.MovieId = m.Id LIMIT 1) as file_size,
                    (SELECT Quality FROM MovieFiles mf WHERE mf.MovieId = m.Id LIMIT 1) as file_quality
                FROM Movies m
                LEFT JOIN MovieMetadata mm ON m.MovieMetadataId = mm.Id
            """)

            for row in cursor.fetchall():
                movies.append(dict(row))

            conn.close()
            logger.info(f"Extracted {len(movies)} movies from Radarr")

        except Exception as e:
            logger.error(f"Error extracting Radarr movies: {e}")

        return movies

    def extract_quality_profiles(self) -> List[Dict]:
        """Extrait les profils de qualité"""
        if not self.db_path.exists():
            return []

        profiles = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT Id as profile_id, Name as name, Cutoff as cutoff,
                       UpgradeAllowed as upgrade_allowed, Items as items
                FROM QualityProfiles
            """)

            for row in cursor.fetchall():
                profile = dict(row)
                if profile.get('items'):
                    try:
                        profile['items'] = json.loads(profile['items'])
                    except:
                        pass
                profiles.append(profile)

            conn.close()

        except Exception as e:
            logger.error(f"Error extracting Radarr quality profiles: {e}")

        return profiles

    def extract_config(self) -> Dict:
        """Extrait la configuration XML"""
        if not self.config_path.exists():
            return {}

        try:
            tree = ET.parse(str(self.config_path))
            root = tree.getroot()
            config = {}
            for child in root:
                config[child.tag] = child.text
            return config
        except Exception as e:
            logger.error(f"Error extracting Radarr config: {e}")
            return {}


class SonarrExtractor:
    """Extrait les données de Sonarr"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.db_path = self.path / "sonarr.db"
        self.config_path = self.path / "config.xml"

    def extract_series(self) -> List[Dict]:
        """Extrait la liste des séries"""
        if not self.db_path.exists():
            logger.warning(f"Sonarr DB not found: {self.db_path}")
            return []

        series_list = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    Id as sonarr_id,
                    Title as title,
                    TitleSlug as title_slug,
                    Year as year,
                    TvdbId as tvdb_id,
                    ImdbId as imdb_id,
                    Overview as overview,
                    Network as network,
                    QualityProfileId as quality_profile_id,
                    Path as path,
                    Monitored as monitored,
                    Status as status,
                    SeasonCount as season_count,
                    EpisodeCount as episode_count,
                    EpisodeFileCount as episode_file_count,
                    TotalEpisodeCount as total_episode_count,
                    SizeOnDisk as size_on_disk,
                    Added as added_at
                FROM Series
            """)

            for row in cursor.fetchall():
                series_list.append(dict(row))

            conn.close()
            logger.info(f"Extracted {len(series_list)} series from Sonarr")

        except Exception as e:
            logger.error(f"Error extracting Sonarr series: {e}")

        return series_list

    def extract_quality_profiles(self) -> List[Dict]:
        """Extrait les profils de qualité"""
        if not self.db_path.exists():
            return []

        profiles = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT Id as profile_id, Name as name, Cutoff as cutoff,
                       UpgradeAllowed as upgrade_allowed, Items as items
                FROM QualityProfiles
            """)

            for row in cursor.fetchall():
                profile = dict(row)
                if profile.get('items'):
                    try:
                        profile['items'] = json.loads(profile['items'])
                    except:
                        pass
                profiles.append(profile)

            conn.close()

        except Exception as e:
            logger.error(f"Error extracting Sonarr quality profiles: {e}")

        return profiles


class ProwlarrExtractor:
    """Extrait les données de Prowlarr"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.db_path = self.path / "prowlarr.db"

    def extract_indexers(self) -> List[Dict]:
        """Extrait la liste des indexeurs"""
        if not self.db_path.exists():
            logger.warning(f"Prowlarr DB not found: {self.db_path}")
            return []

        indexers = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    Id as prowlarr_id,
                    Name as name,
                    Implementation as implementation,
                    ConfigContract as config_contract,
                    Enable as enable,
                    Priority as priority,
                    AppProfileId as app_profile_id
                FROM Indexers
            """)

            for row in cursor.fetchall():
                indexers.append(dict(row))

            conn.close()
            logger.info(f"Extracted {len(indexers)} indexers from Prowlarr")

        except Exception as e:
            logger.error(f"Error extracting Prowlarr indexers: {e}")

        return indexers


class JellyfinExtractor:
    """Extrait les données de Jellyfin"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.db_path = self.path / "data" / "data" / "jellyfin.db"
        self.users_path = self.path / "users"

    def extract_users(self) -> List[Dict]:
        """Extrait la liste des utilisateurs"""
        users = []

        # Méthode 1: Lire depuis le dossier users
        if self.users_path.exists():
            for user_dir in self.users_path.iterdir():
                if user_dir.is_dir():
                    user_config = user_dir / "config.json"
                    if user_config.exists():
                        try:
                            data = json.loads(user_config.read_text())
                            users.append({
                                'jellyfin_user_id': data.get('Id', ''),
                                'username': user_dir.name,
                                'is_administrator': data.get('Policy', {}).get('IsAdministrator', False),
                                'is_disabled': data.get('Policy', {}).get('IsDisabled', False),
                                'policy': data.get('Policy', {})
                            })
                        except Exception as e:
                            logger.warning(f"Error reading Jellyfin user config: {e}")

        logger.info(f"Extracted {len(users)} users from Jellyfin")
        return users

    def extract_config(self) -> Dict:
        """Extrait les configurations Jellyfin"""
        configs = {}

        config_files = ['system.xml', 'network.xml', 'encoding.xml']
        for config_file in config_files:
            config_path = self.path / config_file
            if config_path.exists():
                try:
                    tree = ET.parse(str(config_path))
                    root = tree.getroot()
                    config = {}
                    for child in root:
                        config[child.tag] = child.text
                    configs[config_file.replace('.xml', '')] = config
                except Exception as e:
                    logger.warning(f"Error reading Jellyfin config {config_file}: {e}")

        return configs


class DecypharrExtractor:
    """Extrait les données de Decypharr"""

    def __init__(self, path: str):
        self.path = Path(path)
        self.config_path = self.path / "config.json"

    def extract_config(self) -> Dict:
        """Extrait la configuration (sans les clés sensibles)"""
        if not self.config_path.exists():
            return {}

        try:
            config = json.loads(self.config_path.read_text())

            # Masquer les clés API sensibles
            safe_config = config.copy()
            if 'debrids' in safe_config:
                for debrid in safe_config['debrids']:
                    if 'api_key' in debrid:
                        debrid['api_key'] = '***MASKED***'
                    if 'download_api_keys' in debrid:
                        debrid['download_api_keys'] = ['***MASKED***']

            if 'arrs' in safe_config:
                for arr in safe_config['arrs']:
                    if 'token' in arr:
                        arr['token'] = '***MASKED***'

            return safe_config

        except Exception as e:
            logger.error(f"Error extracting Decypharr config: {e}")
            return {}


# =============================================================================
# SERVICE DE BACKUP
# =============================================================================

class SupabazarrBackup:
    """Service principal de backup"""

    VERSION = "1.0.0"

    def __init__(self, config: Config):
        self.config = config
        self.supabase: Client = create_client(config.supabase_url, config.supabase_key)
        self.device_id: Optional[str] = None

        # Extracteurs
        self.radarr = RadarrExtractor(config.radarr_path)
        self.sonarr = SonarrExtractor(config.sonarr_path)
        self.prowlarr = ProwlarrExtractor(config.prowlarr_path)
        self.jellyfin = JellyfinExtractor(config.jellyfin_path)
        self.decypharr = DecypharrExtractor(config.decypharr_path)

    def register_device(self) -> str:
        """Enregistre ou met à jour le device dans Supabase"""
        logger.info(f"Registering device: {self.config.hostname} ({self.config.device_uuid})")

        try:
            # Vérifier si le device existe
            result = self.supabase.table('raspberry_devices').select('id').eq(
                'device_uuid', self.config.device_uuid
            ).execute()

            device_data = {
                'hostname': self.config.hostname,
                'device_uuid': self.config.device_uuid,
                'supabazarr_version': self.VERSION,
                'last_backup_at': datetime.utcnow().isoformat()
            }

            if result.data:
                # Update existing
                self.device_id = result.data[0]['id']
                self.supabase.table('raspberry_devices').update(device_data).eq(
                    'id', self.device_id
                ).execute()
            else:
                # Insert new
                result = self.supabase.table('raspberry_devices').insert(device_data).execute()
                self.device_id = result.data[0]['id']

            logger.info(f"Device registered with ID: {self.device_id}")
            return self.device_id

        except Exception as e:
            logger.error(f"Error registering device: {e}")
            raise

    def backup_movies(self):
        """Sauvegarde les films Radarr"""
        movies = self.radarr.extract_movies()
        if not movies:
            return 0

        logger.info(f"Backing up {len(movies)} movies...")

        for movie in movies:
            movie['device_id'] = self.device_id
            movie['updated_at'] = datetime.utcnow().isoformat()

        try:
            # Upsert (insert or update)
            self.supabase.table('movies').upsert(
                movies,
                on_conflict='device_id,radarr_id'
            ).execute()

            logger.info(f"Backed up {len(movies)} movies")
            return len(movies)

        except Exception as e:
            logger.error(f"Error backing up movies: {e}")
            return 0

    def backup_series(self):
        """Sauvegarde les séries Sonarr"""
        series_list = self.sonarr.extract_series()
        if not series_list:
            return 0

        logger.info(f"Backing up {len(series_list)} series...")

        for series in series_list:
            series['device_id'] = self.device_id
            series['updated_at'] = datetime.utcnow().isoformat()

        try:
            self.supabase.table('series').upsert(
                series_list,
                on_conflict='device_id,sonarr_id'
            ).execute()

            logger.info(f"Backed up {len(series_list)} series")
            return len(series_list)

        except Exception as e:
            logger.error(f"Error backing up series: {e}")
            return 0

    def backup_indexers(self):
        """Sauvegarde les indexeurs Prowlarr"""
        indexers = self.prowlarr.extract_indexers()
        if not indexers:
            return 0

        logger.info(f"Backing up {len(indexers)} indexers...")

        for indexer in indexers:
            indexer['device_id'] = self.device_id
            indexer['updated_at'] = datetime.utcnow().isoformat()

        try:
            self.supabase.table('indexers').upsert(
                indexers,
                on_conflict='device_id,prowlarr_id'
            ).execute()

            logger.info(f"Backed up {len(indexers)} indexers")
            return len(indexers)

        except Exception as e:
            logger.error(f"Error backing up indexers: {e}")
            return 0

    def backup_jellyfin_users(self):
        """Sauvegarde les utilisateurs Jellyfin"""
        users = self.jellyfin.extract_users()
        if not users:
            return 0

        logger.info(f"Backing up {len(users)} Jellyfin users...")

        for user in users:
            user['device_id'] = self.device_id
            user['updated_at'] = datetime.utcnow().isoformat()
            # Convertir policy en JSON string si nécessaire
            if isinstance(user.get('policy'), dict):
                user['policy'] = json.dumps(user['policy'])

        try:
            self.supabase.table('jellyfin_users').upsert(
                users,
                on_conflict='device_id,jellyfin_user_id'
            ).execute()

            logger.info(f"Backed up {len(users)} Jellyfin users")
            return len(users)

        except Exception as e:
            logger.error(f"Error backing up Jellyfin users: {e}")
            return 0

    def backup_quality_profiles(self):
        """Sauvegarde les profils de qualité"""
        profiles = []

        # Radarr profiles
        radarr_profiles = self.radarr.extract_quality_profiles()
        for p in radarr_profiles:
            p['service_name'] = 'radarr'
            p['device_id'] = self.device_id
            p['updated_at'] = datetime.utcnow().isoformat()
            if isinstance(p.get('items'), (dict, list)):
                p['items'] = json.dumps(p['items'])
            profiles.append(p)

        # Sonarr profiles
        sonarr_profiles = self.sonarr.extract_quality_profiles()
        for p in sonarr_profiles:
            p['service_name'] = 'sonarr'
            p['device_id'] = self.device_id
            p['updated_at'] = datetime.utcnow().isoformat()
            if isinstance(p.get('items'), (dict, list)):
                p['items'] = json.dumps(p['items'])
            profiles.append(p)

        if profiles:
            try:
                self.supabase.table('quality_profiles').upsert(
                    profiles,
                    on_conflict='device_id,service_name,profile_id'
                ).execute()
                logger.info(f"Backed up {len(profiles)} quality profiles")
            except Exception as e:
                logger.error(f"Error backing up quality profiles: {e}")

        return len(profiles)

    def backup_service_configs(self):
        """Sauvegarde les configurations des services"""
        configs = []

        # Radarr config
        radarr_config = self.radarr.extract_config()
        if radarr_config:
            configs.append({
                'device_id': self.device_id,
                'service_name': 'radarr',
                'config_type': 'main',
                'config_data': json.dumps(radarr_config),
                'updated_at': datetime.utcnow().isoformat()
            })

        # Jellyfin configs
        jellyfin_configs = self.jellyfin.extract_config()
        for config_type, config_data in jellyfin_configs.items():
            configs.append({
                'device_id': self.device_id,
                'service_name': 'jellyfin',
                'config_type': config_type,
                'config_data': json.dumps(config_data),
                'updated_at': datetime.utcnow().isoformat()
            })

        # Decypharr config
        decypharr_config = self.decypharr.extract_config()
        if decypharr_config:
            configs.append({
                'device_id': self.device_id,
                'service_name': 'decypharr',
                'config_type': 'main',
                'config_data': json.dumps(decypharr_config),
                'updated_at': datetime.utcnow().isoformat()
            })

        if configs:
            try:
                self.supabase.table('service_configs').upsert(
                    configs,
                    on_conflict='device_id,service_name,config_type'
                ).execute()
                logger.info(f"Backed up {len(configs)} service configs")
            except Exception as e:
                logger.error(f"Error backing up service configs: {e}")

        return len(configs)

    def run_backup(self) -> Dict:
        """Exécute une sauvegarde complète"""
        start_time = datetime.utcnow()
        logger.info("=" * 60)
        logger.info(f"Starting Supabazarr backup - {start_time.isoformat()}")
        logger.info("=" * 60)

        results = {
            'status': 'success',
            'movies_count': 0,
            'series_count': 0,
            'indexers_count': 0,
            'users_count': 0,
            'error_message': None
        }

        try:
            # 1. Enregistrer/Mettre à jour le device
            self.register_device()

            # 2. Backup des données
            results['movies_count'] = self.backup_movies()
            results['series_count'] = self.backup_series()
            results['indexers_count'] = self.backup_indexers()
            results['users_count'] = self.backup_jellyfin_users()
            self.backup_quality_profiles()
            self.backup_service_configs()

        except Exception as e:
            results['status'] = 'failed'
            results['error_message'] = str(e)
            logger.error(f"Backup failed: {e}")

        # 3. Enregistrer l'historique
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()

        try:
            self.supabase.table('backup_history').insert({
                'device_id': self.device_id,
                'status': results['status'],
                'duration_seconds': int(duration),
                'movies_count': results['movies_count'],
                'series_count': results['series_count'],
                'indexers_count': results['indexers_count'],
                'users_count': results['users_count'],
                'error_message': results['error_message'],
                'details': json.dumps(results)
            }).execute()
        except Exception as e:
            logger.error(f"Error saving backup history: {e}")

        logger.info("=" * 60)
        logger.info(f"Backup completed in {duration:.1f}s - Status: {results['status']}")
        logger.info(f"Movies: {results['movies_count']}, Series: {results['series_count']}, "
                   f"Indexers: {results['indexers_count']}, Users: {results['users_count']}")
        logger.info("=" * 60)

        return results


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Supabazarr - Backup service for JellySetup')
    parser.add_argument('--once', action='store_true', help='Run backup once and exit')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Charger la configuration
    config = get_config()

    if not config.supabase_url or not config.supabase_key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY environment variables are required")
        sys.exit(1)

    # Créer le service de backup
    backup = SupabazarrBackup(config)

    if args.once:
        # Exécuter une seule fois
        results = backup.run_backup()
        sys.exit(0 if results['status'] == 'success' else 1)
    else:
        # Mode daemon avec cron interne
        import schedule
        import time

        # Backup quotidien à 3h du matin
        schedule.every().day.at("03:00").do(backup.run_backup)

        # Premier backup au démarrage
        logger.info("Running initial backup...")
        backup.run_backup()

        logger.info("Supabazarr daemon started. Next backup at 03:00")
        while True:
            schedule.run_pending()
            time.sleep(60)


if __name__ == '__main__':
    main()

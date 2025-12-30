#!/usr/bin/env python3
"""
Supabazarr - Automatic backup & media sync service for Media Stack to Supabase
Syncs Jellyfin library to Supabase media catalog with per-Pi schema support.
"""

import os
import json
import hashlib
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List

import requests
from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__, template_folder='/app/templates')

# Configuration
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
PI_NAME = os.environ.get('PI_NAME', os.environ.get('HOSTNAME', 'unknown_pi'))
MEDIA_STACK_PATH = os.environ.get('MEDIA_STACK_PATH', '/media-stack')
BACKUP_INTERVAL_HOURS = int(os.environ.get('BACKUP_INTERVAL_HOURS', '6'))
MEDIA_SYNC_INTERVAL_MINUTES = int(os.environ.get('MEDIA_SYNC_INTERVAL_MINUTES', '30'))

# Jellyfin config
JELLYFIN_URL = os.environ.get('JELLYFIN_URL', 'http://jellyfin:8096')
JELLYFIN_API_KEY = os.environ.get('JELLYFIN_API_KEY', '')

# State
last_backup: Optional[datetime] = None
last_backup_status: str = 'never'
last_media_sync: Optional[datetime] = None
last_media_sync_status: str = 'never'
backup_history: list = []
media_sync_history: list = []
schema_initialized: bool = False

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


def get_schema_name() -> str:
    """Convert Pi name to PostgreSQL schema name"""
    import re
    return re.sub(r'[^a-z0-9_]', '_', PI_NAME.lower())


def get_headers(schema: Optional[str] = None) -> Dict[str, str]:
    """Get Supabase API headers with schema support"""
    headers = {
        'apikey': SUPABASE_SERVICE_KEY,
        'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
        'Content-Type': 'application/json'
    }

    if schema:
        headers['Content-Profile'] = schema
        headers['Accept-Profile'] = schema

    return headers


def ensure_schema_initialized() -> bool:
    """Initialize the schema for this Pi via Edge Function"""
    global schema_initialized

    if schema_initialized:
        return True

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print("[Supabazarr] Supabase not configured")
        return False

    try:
        print(f"[Supabazarr] Initializing schema for Pi '{PI_NAME}'...")
        response = requests.post(
            f"{SUPABASE_URL}/functions/v1/jellysetup-init",
            headers={'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}', 'Content-Type': 'application/json'},
            json={'pi_name': PI_NAME},
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                schema_initialized = True
                print(f"[Supabazarr] Schema '{result.get('schema')}' initialized with tables: {result.get('tables')}")
                return True
            else:
                print(f"[Supabazarr] Schema init warning: {result.get('error')}")
                schema_initialized = True  # Continue anyway
                return True
        else:
            print(f"[Supabazarr] Schema init failed: {response.status_code} - {response.text}")

    except Exception as e:
        print(f"[Supabazarr] Error initializing schema: {e}")

    return False


def update_heartbeat():
    """Update last_seen timestamp in Pi's schema config"""
    if not ensure_schema_initialized():
        return

    schema = get_schema_name()

    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/config",
            params={'select': 'id', 'limit': '1'},
            headers=get_headers(schema),
            timeout=10
        )

        if response.status_code == 200:
            configs = response.json()
            if configs:
                config_id = configs[0]['id']
                requests.patch(
                    f"{SUPABASE_URL}/rest/v1/config?id=eq.{config_id}",
                    headers=get_headers(schema),
                    json={
                        'last_seen': datetime.utcnow().isoformat(),
                        'status': 'active'
                    },
                    timeout=10
                )
    except Exception as e:
        print(f"[Supabazarr] Heartbeat error: {e}")


def backup_service_config(service: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Backup a single service configuration"""
    service_path = Path(MEDIA_STACK_PATH) / service['path']

    if not service_path.exists():
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

    return backup_data if backup_data['files'] else None


def save_backup_to_supabase(backup_data: Dict[str, Any], service_name: str) -> bool:
    """Save backup data to Pi's schema"""
    if not ensure_schema_initialized():
        return False

    schema = get_schema_name()

    try:
        backup_json = json.dumps(backup_data)
        checksum = hashlib.md5(backup_json.encode()).hexdigest()

        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/backups",
            headers=get_headers(schema),
            json={
                'backup_type': 'config',
                'service_name': service_name,
                'file_size': len(backup_json),
                'checksum': checksum,
                'metadata': backup_data
            },
            timeout=30
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

        if backup_data:
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

    if len(backup_history) > 50:
        backup_history.pop(0)

    print(f"[Supabazarr] Backup complete: {last_backup_status}")


# =============================================================================
# JELLYFIN MEDIA SYNC
# =============================================================================

def get_jellyfin_items(item_type: str = 'Movie') -> List[Dict]:
    """Get items from Jellyfin library with ALL available metadata"""
    if not JELLYFIN_API_KEY:
        print("[Supabazarr] Jellyfin API key not configured")
        return []

    try:
        # Request ALL available fields from Jellyfin
        fields = [
            'ProviderIds', 'Path', 'MediaSources', 'Overview', 'Genres', 'GenreItems',
            'People', 'Studios', 'Tags', 'ProductionLocations', 'DateCreated',
            'PremiereDate', 'CriticRating', 'CommunityRating', 'OfficialRating',
            'Taglines', 'ExternalUrls', 'MediaStreams', 'Width', 'Height',
            'AspectRatio', 'Container', 'Size', 'Bitrate', 'RunTimeTicks',
            'PlayCount', 'IsFavorite', 'UserData', 'RemoteTrailers',
            'OriginalTitle', 'SortName', 'ForcedSortName', 'Video3DFormat',
            'AirsAfterSeasonNumber', 'AirsBeforeSeasonNumber', 'AirsBeforeEpisodeNumber',
            'CanDelete', 'CanDownload', 'HasSubtitles', 'PreferredMetadataLanguage',
            'PreferredMetadataCountryCode', 'AwardSummary', 'MetaScore', 'HasTrailer',
            'HasLocalTrailer', 'IsHD', 'IsFolder', 'ParentId', 'Type', 'RecursiveItemCount'
        ]

        response = requests.get(
            f"{JELLYFIN_URL}/Items",
            params={
                'IncludeItemTypes': item_type,
                'Recursive': 'true',
                'Fields': ','.join(fields),
                'api_key': JELLYFIN_API_KEY
            },
            timeout=120
        )

        if response.status_code == 200:
            return response.json().get('Items', [])
        else:
            print(f"[Supabazarr] Jellyfin API error: {response.status_code}")

    except Exception as e:
        print(f"[Supabazarr] Error fetching Jellyfin items: {e}")

    return []


def extract_media_streams_info(media_sources: List[Dict]) -> Dict:
    """Extract detailed info from media streams (video, audio, subtitles)"""
    if not media_sources:
        return {}

    first_source = media_sources[0]
    streams = first_source.get('MediaStreams', [])

    video_stream = next((s for s in streams if s.get('Type') == 'Video'), {})
    audio_streams = [s for s in streams if s.get('Type') == 'Audio']
    subtitle_streams = [s for s in streams if s.get('Type') == 'Subtitle']

    return {
        'container': first_source.get('Container'),
        'bitrate': first_source.get('Bitrate'),
        'size': first_source.get('Size'),
        'video': {
            'codec': video_stream.get('Codec'),
            'profile': video_stream.get('Profile'),
            'level': video_stream.get('Level'),
            'width': video_stream.get('Width'),
            'height': video_stream.get('Height'),
            'aspect_ratio': video_stream.get('AspectRatio'),
            'bitrate': video_stream.get('BitRate'),
            'framerate': video_stream.get('RealFrameRate'),
            'bit_depth': video_stream.get('BitDepth'),
            'color_space': video_stream.get('ColorSpace'),
            'hdr': video_stream.get('VideoDoViTitle') or video_stream.get('VideoRangeType'),
            'is_interlaced': video_stream.get('IsInterlaced'),
        },
        'audio': [
            {
                'codec': a.get('Codec'),
                'channels': a.get('Channels'),
                'sample_rate': a.get('SampleRate'),
                'bitrate': a.get('BitRate'),
                'language': a.get('Language'),
                'title': a.get('Title'),
                'is_default': a.get('IsDefault'),
            } for a in audio_streams
        ],
        'subtitles': [
            {
                'language': s.get('Language'),
                'title': s.get('Title'),
                'codec': s.get('Codec'),
                'is_forced': s.get('IsForced'),
                'is_default': s.get('IsDefault'),
                'is_external': s.get('IsExternal'),
            } for s in subtitle_streams
        ],
        'is_hd': first_source.get('IsHD'),
        'is_4k': video_stream.get('Width', 0) >= 3840,
    }


def sync_jellyfin_item_to_supabase(item: Dict, media_type: str) -> bool:
    """Sync a single Jellyfin item to Supabase media table with ALL metadata"""
    if not ensure_schema_initialized():
        return False

    schema = get_schema_name()

    try:
        provider_ids = item.get('ProviderIds', {})
        media_sources = item.get('MediaSources', [])
        first_source = media_sources[0] if media_sources else {}
        user_data = item.get('UserData', {})

        # Extract genres as array
        genres = [g.get('Name') for g in item.get('GenreItems', [])] if 'GenreItems' in item else item.get('Genres', [])

        # Extract ALL actors and crew
        actors = []
        directors = []
        writers = []
        for person in item.get('People', []):
            person_type = person.get('Type', '')
            name = person.get('Name')
            if person_type == 'Actor' and len(actors) < 20:
                actors.append(name)
            elif person_type == 'Director':
                directors.append(name)
            elif person_type == 'Writer':
                writers.append(name)

        # Extract studios
        studios = [s.get('Name') for s in item.get('Studios', [])]

        # Extract tags
        tags = item.get('Tags', [])

        # Determine quality from resolution
        streams_info = extract_media_streams_info(media_sources)
        width = streams_info.get('video', {}).get('width', 0)
        if width >= 3840:
            quality = '4K'
        elif width >= 1920:
            quality = '1080p'
        elif width >= 1280:
            quality = '720p'
        elif width > 0:
            quality = 'SD'
        else:
            quality = None

        # Calculate watch progress percentage
        duration_ticks = item.get('RunTimeTicks', 0)
        progress_ticks = user_data.get('PlaybackPositionTicks', 0)
        watch_progress_percent = (progress_ticks / duration_ticks * 100) if duration_ticks > 0 else 0

        # Extract trailers
        trailers = item.get('RemoteTrailers', [])
        trailer_url = trailers[0].get('Url') if trailers else None

        # Extract tagline
        taglines = item.get('Taglines', [])
        tagline = taglines[0] if taglines else None

        # Build comprehensive media record with ALL data for community features
        media_data = {
            'media_type': media_type,
            'title': item.get('Name', 'Unknown'),
            'original_title': item.get('OriginalTitle'),
            'year': item.get('ProductionYear'),

            # External IDs
            'imdb_id': provider_ids.get('Imdb'),
            'tmdb_id': int(provider_ids.get('Tmdb')) if provider_ids.get('Tmdb') else None,
            'tvdb_id': int(provider_ids.get('Tvdb')) if provider_ids.get('Tvdb') else None,

            # Jellyfin
            'jellyfin_id': item.get('Id'),

            # File info
            'file_path': item.get('Path'),
            'file_size': first_source.get('Size'),
            'duration_minutes': int(duration_ticks / 600000000) if duration_ticks else None,

            # Quality
            'quality': quality,
            'codec': streams_info.get('video', {}).get('codec'),
            'audio': ', '.join([a.get('codec', '') for a in streams_info.get('audio', [])[:3]]) or None,

            # Content info
            'overview': item.get('Overview'),
            'genres': genres if genres else None,
            'actors': actors if actors else None,
            'director': ', '.join(directors) if directors else None,
            'studio': studios[0] if studios else None,

            # Images - ALL available
            'poster_url': f"{JELLYFIN_URL}/Items/{item.get('Id')}/Images/Primary?api_key={JELLYFIN_API_KEY}" if item.get('ImageTags', {}).get('Primary') else None,
            'backdrop_url': f"{JELLYFIN_URL}/Items/{item.get('Id')}/Images/Backdrop?api_key={JELLYFIN_API_KEY}" if item.get('BackdropImageTags') else None,
            'thumbnail_url': f"{JELLYFIN_URL}/Items/{item.get('Id')}/Images/Thumb?api_key={JELLYFIN_API_KEY}" if item.get('ImageTags', {}).get('Thumb') else None,

            # ========== WATCH STATUS (CRITICAL FOR COMMUNITY) ==========
            'status': 'watched' if user_data.get('Played') else 'available',
            'watched': user_data.get('Played', False),
            'watched_at': user_data.get('LastPlayedDate') if user_data.get('Played') else None,
            'last_played_at': user_data.get('LastPlayedDate'),  # Even if not fully watched
            'watch_progress': int(progress_ticks / 10000000) if progress_ticks else 0,  # In seconds
            'watch_progress_percent': round(watch_progress_percent, 2),  # 0-100%
            'play_count': user_data.get('PlayCount', 0),  # Number of times played
            'favorite': user_data.get('IsFavorite', False),

            # ========== RATINGS (FOR RECOMMENDATIONS) ==========
            'community_rating': item.get('CommunityRating'),  # TMDB/IMDB rating
            'critic_rating': item.get('CriticRating'),  # Rotten Tomatoes %
            'rating': item.get('CommunityRating'),  # Legacy field

            # ========== CLASSIFICATION ==========
            'age_rating': item.get('OfficialRating'),  # PG-13, R, TV-MA, etc.

            # ========== EXTRA INFO ==========
            'tagline': tagline,
            'trailer_url': trailer_url,
            'production_companies': studios if studios else None,

            # ========== DATES ==========
            'release_date': item.get('PremiereDate', '').split('T')[0] if item.get('PremiereDate') else None,
            'jellyfin_added_at': item.get('DateCreated'),  # When added to Jellyfin
            'last_sync_at': datetime.utcnow().isoformat(),  # Current sync time

            # ========== FULL METADATA JSONB ==========
            'metadata': {
                # Media streams details (video, audio, subtitles)
                'streams': streams_info,

                # Jellyfin specific
                'jellyfin': {
                    'id': item.get('Id'),
                    'etag': item.get('Etag'),
                    'parent_id': item.get('ParentId'),
                    'date_created': item.get('DateCreated'),
                    'sort_name': item.get('SortName'),
                    'has_subtitles': item.get('HasSubtitles', False),
                },

                # Full crew info
                'crew': {
                    'directors': directors,
                    'writers': writers,
                    'all_actors': actors,
                },

                # All studios
                'studios': studios,
                'tags': tags,
                'all_taglines': taglines,

                # All external URLs (IMDB, TMDB, etc.)
                'external_urls': item.get('ExternalUrls', []),

                # All trailers
                'all_trailers': [t.get('Url') for t in trailers],
                'has_local_trailer': item.get('HasLocalTrailer', False),

                # Technical details
                'is_hd': streams_info.get('is_hd'),
                'is_4k': streams_info.get('is_4k'),
                'aspect_ratio': streams_info.get('video', {}).get('aspect_ratio'),
                'resolution': f"{streams_info.get('video', {}).get('width')}x{streams_info.get('video', {}).get('height')}" if streams_info.get('video', {}).get('width') else None,
                'video_profile': streams_info.get('video', {}).get('profile'),
                'hdr_type': streams_info.get('video', {}).get('hdr'),
                'bit_depth': streams_info.get('video', {}).get('bit_depth'),

                # Audio tracks details
                'audio_tracks': streams_info.get('audio', []),
                'subtitle_tracks': streams_info.get('subtitles', []),

                # All provider IDs
                'provider_ids': provider_ids,

                # User data snapshot
                'user_data': {
                    'play_count': user_data.get('PlayCount', 0),
                    'is_favorite': user_data.get('IsFavorite', False),
                    'played': user_data.get('Played', False),
                    'playback_position_ticks': progress_ticks,
                    'last_played_date': user_data.get('LastPlayedDate'),
                },
            }
        }

        # Remove None values (but keep False booleans and 0 integers)
        media_data = {k: v for k, v in media_data.items() if v is not None}

        # Check if media exists by jellyfin_id
        check_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/media",
            params={'jellyfin_id': f"eq.{item.get('Id')}", 'select': 'id'},
            headers=get_headers(schema),
            timeout=10
        )

        if check_response.status_code == 200 and check_response.json():
            # Update existing
            existing_id = check_response.json()[0]['id']
            response = requests.patch(
                f"{SUPABASE_URL}/rest/v1/media?id=eq.{existing_id}",
                headers=get_headers(schema),
                json=media_data,
                timeout=15
            )
        else:
            # Insert new
            response = requests.post(
                f"{SUPABASE_URL}/rest/v1/media",
                headers=get_headers(schema),
                json=media_data,
                timeout=15
            )

        return response.status_code in [200, 201, 204]

    except Exception as e:
        print(f"[Supabazarr] Error syncing media '{item.get('Name')}': {e}")
        return False


def sync_jellyfin_series_to_supabase(series: Dict) -> bool:
    """Sync a series and its episodes to Supabase"""
    if not ensure_schema_initialized():
        return False

    schema = get_schema_name()

    # First sync the series itself
    if not sync_jellyfin_item_to_supabase(series, 'series'):
        return False

    # Get series ID from Supabase
    try:
        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/media",
            params={'jellyfin_id': f"eq.{series.get('Id')}", 'select': 'id'},
            headers=get_headers(schema),
            timeout=10
        )

        if response.status_code != 200 or not response.json():
            return False

        series_db_id = response.json()[0]['id']

        # Get episodes from Jellyfin
        episodes_response = requests.get(
            f"{JELLYFIN_URL}/Shows/{series.get('Id')}/Episodes",
            params={
                'Fields': 'ProviderIds,Path,MediaSources,Overview',
                'api_key': JELLYFIN_API_KEY
            },
            timeout=60
        )

        if episodes_response.status_code != 200:
            return True  # Series synced, episodes failed

        episodes = episodes_response.json().get('Items', [])

        for episode in episodes:
            provider_ids = episode.get('ProviderIds', {})
            media_sources = episode.get('MediaSources', [{}])
            first_source = media_sources[0] if media_sources else {}

            episode_data = {
                'media_type': 'episode',
                'title': episode.get('Name', 'Unknown'),
                'series_id': series_db_id,
                'season_number': episode.get('ParentIndexNumber'),
                'episode_number': episode.get('IndexNumber'),
                'episode_title': episode.get('Name'),
                'imdb_id': provider_ids.get('Imdb'),
                'tmdb_id': int(provider_ids.get('Tmdb')) if provider_ids.get('Tmdb') else None,
                'jellyfin_id': episode.get('Id'),
                'file_path': episode.get('Path'),
                'file_size': first_source.get('Size'),
                'duration_minutes': int(episode.get('RunTimeTicks', 0) / 600000000) if episode.get('RunTimeTicks') else None,
                'overview': episode.get('Overview'),
                'status': 'available',
                'watched': episode.get('UserData', {}).get('Played', False)
            }

            episode_data = {k: v for k, v in episode_data.items() if v is not None}

            # Check if episode exists
            check_ep = requests.get(
                f"{SUPABASE_URL}/rest/v1/media",
                params={'jellyfin_id': f"eq.{episode.get('Id')}", 'select': 'id'},
                headers=get_headers(schema),
                timeout=10
            )

            if check_ep.status_code == 200 and check_ep.json():
                existing_id = check_ep.json()[0]['id']
                requests.patch(
                    f"{SUPABASE_URL}/rest/v1/media?id=eq.{existing_id}",
                    headers=get_headers(schema),
                    json=episode_data,
                    timeout=10
                )
            else:
                requests.post(
                    f"{SUPABASE_URL}/rest/v1/media",
                    headers=get_headers(schema),
                    json=episode_data,
                    timeout=10
                )

        return True

    except Exception as e:
        print(f"[Supabazarr] Error syncing series episodes: {e}")
        return False


def run_media_sync():
    """Sync Jellyfin library to Supabase"""
    global last_media_sync, last_media_sync_status

    if not JELLYFIN_API_KEY:
        print("[Supabazarr] Skipping media sync - Jellyfin API key not configured")
        return

    print(f"[Supabazarr] Starting media sync at {datetime.now()}")

    movies_synced = 0
    series_synced = 0

    # Sync movies
    print("[Supabazarr] Syncing movies...")
    movies = get_jellyfin_items('Movie')
    for movie in movies:
        if sync_jellyfin_item_to_supabase(movie, 'movie'):
            movies_synced += 1

    # Sync series
    print("[Supabazarr] Syncing series...")
    series_list = get_jellyfin_items('Series')
    for series in series_list:
        if sync_jellyfin_series_to_supabase(series):
            series_synced += 1

    last_media_sync = datetime.now()
    last_media_sync_status = f"{movies_synced} movies, {series_synced} series"

    media_sync_history.append({
        'timestamp': last_media_sync.isoformat(),
        'status': last_media_sync_status,
        'movies': movies_synced,
        'series': series_synced
    })

    if len(media_sync_history) > 50:
        media_sync_history.pop(0)

    print(f"[Supabazarr] Media sync complete: {last_media_sync_status}")


# =============================================================================
# FLASK ROUTES
# =============================================================================

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html',
        pi_name=PI_NAME,
        schema_name=get_schema_name(),
        supabase_configured=bool(SUPABASE_URL and SUPABASE_SERVICE_KEY),
        jellyfin_configured=bool(JELLYFIN_API_KEY),
        last_backup=last_backup.strftime('%Y-%m-%d %H:%M:%S') if last_backup else 'Never',
        last_backup_status=last_backup_status,
        last_media_sync=last_media_sync.strftime('%Y-%m-%d %H:%M:%S') if last_media_sync else 'Never',
        last_media_sync_status=last_media_sync_status,
        backup_interval=BACKUP_INTERVAL_HOURS,
        media_sync_interval=MEDIA_SYNC_INTERVAL_MINUTES,
        services=SERVICES_TO_BACKUP
    )


@app.route('/api/status')
def api_status():
    """API endpoint for status"""
    return jsonify({
        'pi_name': PI_NAME,
        'schema_name': get_schema_name(),
        'supabase_configured': bool(SUPABASE_URL and SUPABASE_SERVICE_KEY),
        'jellyfin_configured': bool(JELLYFIN_API_KEY),
        'schema_initialized': schema_initialized,
        'last_backup': last_backup.isoformat() if last_backup else None,
        'last_backup_status': last_backup_status,
        'last_media_sync': last_media_sync.isoformat() if last_media_sync else None,
        'last_media_sync_status': last_media_sync_status,
        'backup_interval_hours': BACKUP_INTERVAL_HOURS,
        'media_sync_interval_minutes': MEDIA_SYNC_INTERVAL_MINUTES,
        'services_count': len(SERVICES_TO_BACKUP)
    })


@app.route('/api/backup', methods=['POST'])
def api_trigger_backup():
    """Trigger manual backup"""
    threading.Thread(target=run_backup).start()
    return jsonify({'status': 'backup_started'})


@app.route('/api/media-sync', methods=['POST'])
def api_trigger_media_sync():
    """Trigger manual media sync"""
    threading.Thread(target=run_media_sync).start()
    return jsonify({'status': 'media_sync_started'})


@app.route('/api/history')
def api_history():
    """Get backup and sync history"""
    return jsonify({
        'backups': backup_history,
        'media_syncs': media_sync_history
    })


@app.route('/api/media')
def api_media():
    """Get media catalog from Supabase"""
    if not ensure_schema_initialized():
        return jsonify({'error': 'Schema not initialized'}), 500

    schema = get_schema_name()
    media_type = request.args.get('type', None)
    limit = request.args.get('limit', '100')

    try:
        params = {
            'select': 'id,media_type,title,year,poster_url,status,watched,rating',
            'order': 'added_at.desc',
            'limit': limit
        }

        if media_type:
            params['media_type'] = f'eq.{media_type}'

        response = requests.get(
            f"{SUPABASE_URL}/rest/v1/media",
            params=params,
            headers=get_headers(schema),
            timeout=30
        )

        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'error': response.text}), response.status_code

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'pi_name': PI_NAME,
        'schema': get_schema_name()
    })


def main():
    """Main entry point"""
    schema = get_schema_name()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                      SUPABAZARR                               ║
║           Backup & Media Sync for Media Stack                 ║
╠══════════════════════════════════════════════════════════════╣
║  Pi Name:        {PI_NAME:<42} ║
║  Schema:         {schema:<42} ║
║  Supabase:       {'Configured' if SUPABASE_URL else 'Not configured':<42} ║
║  Jellyfin:       {'Configured' if JELLYFIN_API_KEY else 'Not configured':<42} ║
║  Backup Every:   {BACKUP_INTERVAL_HOURS} hours{' ':<38} ║
║  Media Sync:     Every {MEDIA_SYNC_INTERVAL_MINUTES} minutes{' ':<32} ║
║  Web UI:         http://localhost:8383                        ║
╚══════════════════════════════════════════════════════════════╝
    """)

    # Initialize schema
    ensure_schema_initialized()

    # Setup scheduler
    scheduler = BackgroundScheduler()

    # Heartbeat every 5 minutes
    scheduler.add_job(update_heartbeat, 'interval', minutes=5)

    # Backup every N hours
    scheduler.add_job(run_backup, 'interval', hours=BACKUP_INTERVAL_HOURS)

    # Media sync every N minutes
    if JELLYFIN_API_KEY:
        scheduler.add_job(run_media_sync, 'interval', minutes=MEDIA_SYNC_INTERVAL_MINUTES)
        # Run initial media sync after 2 minutes
        scheduler.add_job(run_media_sync, 'date', run_date=datetime.now() + timedelta(minutes=2))

    # Run initial backup after 1 minute
    scheduler.add_job(run_backup, 'date', run_date=datetime.now() + timedelta(minutes=1))

    scheduler.start()

    # Start Flask
    app.run(host='0.0.0.0', port=8383, debug=False)


if __name__ == '__main__':
    main()

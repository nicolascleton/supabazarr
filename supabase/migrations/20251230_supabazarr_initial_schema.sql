-- Supabazarr Schema - Backup automatique pour JellySetup
-- Version: 1.0.0

-- =============================================================================
-- TABLE: raspberry_devices
-- Chaque Raspberry Pi enregistré dans le système
-- =============================================================================
CREATE TABLE IF NOT EXISTS raspberry_devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname TEXT NOT NULL,
    mac_address TEXT UNIQUE,
    device_uuid TEXT UNIQUE NOT NULL, -- UUID généré au premier boot
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_backup_at TIMESTAMPTZ,
    supabazarr_version TEXT,
    os_version TEXT,
    CONSTRAINT hostname_device_unique UNIQUE (hostname, device_uuid)
);

-- Index pour recherche rapide
CREATE INDEX idx_devices_hostname ON raspberry_devices(hostname);
CREATE INDEX idx_devices_uuid ON raspberry_devices(device_uuid);

-- =============================================================================
-- TABLE: movies (Bibliothèque Radarr)
-- =============================================================================
CREATE TABLE IF NOT EXISTS movies (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    radarr_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    tmdb_id INTEGER,
    imdb_id TEXT,
    overview TEXT,
    studio TEXT,
    quality_profile_id INTEGER,
    quality_profile_name TEXT,
    root_folder_path TEXT,
    path TEXT,
    has_file BOOLEAN DEFAULT FALSE,
    monitored BOOLEAN DEFAULT TRUE,
    status TEXT, -- 'released', 'announced', etc.
    runtime INTEGER, -- minutes
    added_at TIMESTAMPTZ,
    file_size BIGINT, -- bytes
    file_quality TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, radarr_id)
);

CREATE INDEX idx_movies_device ON movies(device_id);
CREATE INDEX idx_movies_tmdb ON movies(tmdb_id);
CREATE INDEX idx_movies_title ON movies(title);

-- =============================================================================
-- TABLE: series (Bibliothèque Sonarr)
-- =============================================================================
CREATE TABLE IF NOT EXISTS series (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    sonarr_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    original_title TEXT,
    year INTEGER,
    tvdb_id INTEGER,
    imdb_id TEXT,
    overview TEXT,
    network TEXT,
    quality_profile_id INTEGER,
    quality_profile_name TEXT,
    root_folder_path TEXT,
    path TEXT,
    monitored BOOLEAN DEFAULT TRUE,
    status TEXT, -- 'continuing', 'ended', etc.
    season_count INTEGER DEFAULT 0,
    episode_count INTEGER DEFAULT 0,
    episode_file_count INTEGER DEFAULT 0,
    total_episode_count INTEGER DEFAULT 0,
    size_on_disk BIGINT DEFAULT 0,
    added_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, sonarr_id)
);

CREATE INDEX idx_series_device ON series(device_id);
CREATE INDEX idx_series_tvdb ON series(tvdb_id);
CREATE INDEX idx_series_title ON series(title);

-- =============================================================================
-- TABLE: episodes (Épisodes Sonarr - optionnel, peut être lourd)
-- =============================================================================
CREATE TABLE IF NOT EXISTS episodes (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    sonarr_id INTEGER NOT NULL,
    series_id INTEGER NOT NULL, -- sonarr_id de la série
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    title TEXT,
    air_date DATE,
    has_file BOOLEAN DEFAULT FALSE,
    monitored BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, sonarr_id)
);

CREATE INDEX idx_episodes_device ON episodes(device_id);
CREATE INDEX idx_episodes_series ON episodes(device_id, series_id);

-- =============================================================================
-- TABLE: indexers (Configuration Prowlarr)
-- =============================================================================
CREATE TABLE IF NOT EXISTS indexers (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    prowlarr_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    implementation TEXT, -- 'Cardigann', 'Torznab', etc.
    config_contract TEXT,
    enable BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 25,
    app_profile_id INTEGER,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, prowlarr_id)
);

CREATE INDEX idx_indexers_device ON indexers(device_id);

-- =============================================================================
-- TABLE: jellyfin_users (Utilisateurs Jellyfin)
-- =============================================================================
CREATE TABLE IF NOT EXISTS jellyfin_users (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    jellyfin_user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    is_administrator BOOLEAN DEFAULT FALSE,
    is_disabled BOOLEAN DEFAULT FALSE,
    enable_auto_login BOOLEAN DEFAULT FALSE,
    last_login_date TIMESTAMPTZ,
    last_activity_date TIMESTAMPTZ,
    policy JSONB, -- Toutes les politiques utilisateur
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, jellyfin_user_id)
);

CREATE INDEX idx_jellyfin_users_device ON jellyfin_users(device_id);

-- =============================================================================
-- TABLE: service_configs (Configurations des services)
-- =============================================================================
CREATE TABLE IF NOT EXISTS service_configs (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    service_name TEXT NOT NULL, -- 'radarr', 'sonarr', 'prowlarr', 'jellyfin', 'decypharr', 'bazarr'
    config_type TEXT NOT NULL, -- 'main', 'quality_profiles', 'root_folders', 'download_clients', etc.
    config_data JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, service_name, config_type)
);

CREATE INDEX idx_service_configs_device ON service_configs(device_id);
CREATE INDEX idx_service_configs_service ON service_configs(service_name);

-- =============================================================================
-- TABLE: backup_history (Historique des sauvegardes)
-- =============================================================================
CREATE TABLE IF NOT EXISTS backup_history (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    backup_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT NOT NULL, -- 'success', 'partial', 'failed'
    duration_seconds INTEGER,
    movies_count INTEGER DEFAULT 0,
    series_count INTEGER DEFAULT 0,
    episodes_count INTEGER DEFAULT 0,
    indexers_count INTEGER DEFAULT 0,
    users_count INTEGER DEFAULT 0,
    error_message TEXT,
    details JSONB -- Détails supplémentaires
);

CREATE INDEX idx_backup_history_device ON backup_history(device_id);
CREATE INDEX idx_backup_history_date ON backup_history(backup_at DESC);

-- =============================================================================
-- TABLE: quality_profiles (Profils de qualité)
-- =============================================================================
CREATE TABLE IF NOT EXISTS quality_profiles (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    service_name TEXT NOT NULL, -- 'radarr' ou 'sonarr'
    profile_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    cutoff INTEGER,
    cutoff_format_score INTEGER,
    upgrade_allowed BOOLEAN DEFAULT TRUE,
    items JSONB, -- Liste des qualités
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id, service_name, profile_id)
);

CREATE INDEX idx_quality_profiles_device ON quality_profiles(device_id);

-- =============================================================================
-- VIEWS pour faciliter les requêtes
-- =============================================================================

-- Vue: Statistiques par device
CREATE OR REPLACE VIEW device_stats AS
SELECT
    d.id,
    d.hostname,
    d.device_uuid,
    d.last_backup_at,
    (SELECT COUNT(*) FROM movies m WHERE m.device_id = d.id) as movies_count,
    (SELECT COUNT(*) FROM movies m WHERE m.device_id = d.id AND m.has_file = true) as movies_with_file,
    (SELECT COUNT(*) FROM series s WHERE s.device_id = d.id) as series_count,
    (SELECT SUM(episode_file_count) FROM series s WHERE s.device_id = d.id) as episodes_with_file,
    (SELECT COUNT(*) FROM jellyfin_users ju WHERE ju.device_id = d.id) as jellyfin_users_count,
    (SELECT SUM(m.file_size) FROM movies m WHERE m.device_id = d.id) as total_movies_size,
    (SELECT SUM(s.size_on_disk) FROM series s WHERE s.device_id = d.id) as total_series_size
FROM raspberry_devices d;

-- =============================================================================
-- RLS (Row Level Security) - Pour sécuriser l'accès par device
-- =============================================================================

-- Activer RLS sur toutes les tables
ALTER TABLE raspberry_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE movies ENABLE ROW LEVEL SECURITY;
ALTER TABLE series ENABLE ROW LEVEL SECURITY;
ALTER TABLE episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE indexers ENABLE ROW LEVEL SECURITY;
ALTER TABLE jellyfin_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE backup_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_profiles ENABLE ROW LEVEL SECURITY;

-- Politique: Service role peut tout faire (pour les backups)
CREATE POLICY "Service role full access" ON raspberry_devices FOR ALL USING (true);
CREATE POLICY "Service role full access" ON movies FOR ALL USING (true);
CREATE POLICY "Service role full access" ON series FOR ALL USING (true);
CREATE POLICY "Service role full access" ON episodes FOR ALL USING (true);
CREATE POLICY "Service role full access" ON indexers FOR ALL USING (true);
CREATE POLICY "Service role full access" ON jellyfin_users FOR ALL USING (true);
CREATE POLICY "Service role full access" ON service_configs FOR ALL USING (true);
CREATE POLICY "Service role full access" ON backup_history FOR ALL USING (true);
CREATE POLICY "Service role full access" ON quality_profiles FOR ALL USING (true);

-- =============================================================================
-- FONCTION: Nettoyage des vieux backups (garde 30 jours)
-- =============================================================================
CREATE OR REPLACE FUNCTION cleanup_old_backups()
RETURNS void AS $$
BEGIN
    DELETE FROM backup_history
    WHERE backup_at < NOW() - INTERVAL '30 days';
END;
$$ LANGUAGE plpgsql;

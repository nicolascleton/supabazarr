-- =============================================================================
-- TABLE: setup_credentials (Clés API configurées lors du setup)
-- =============================================================================
CREATE TABLE IF NOT EXISTS setup_credentials (
    id SERIAL PRIMARY KEY,
    device_id UUID REFERENCES raspberry_devices(id) ON DELETE CASCADE,
    -- AllDebrid (obligatoire)
    alldebrid_api_key TEXT,
    -- YGG (optionnel)
    ygg_passkey TEXT,
    -- Discord (optionnel)
    discord_webhook TEXT,
    -- Cloudflare (optionnel)
    cloudflare_token TEXT,
    -- Jellyfin
    jellyfin_admin_username TEXT,
    -- Clés API générées par les services
    radarr_api_key TEXT,
    sonarr_api_key TEXT,
    prowlarr_api_key TEXT,
    jellyfin_api_key TEXT,
    -- Métadonnées
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(device_id)
);

CREATE INDEX idx_setup_credentials_device ON setup_credentials(device_id);

-- RLS
ALTER TABLE setup_credentials ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access" ON setup_credentials FOR ALL USING (true);

-- ============================================================================
-- KnowledgeLayer: Enterprise B2B SaaS Schema
-- ============================================================================
-- SOC 2 Type II, ISO 27001, GDPR/CCPA compliant
-- Built on three pillars: Auditing, Isolation, Retention
--
-- Data Ownership:
--   Supabase: tenants, users, RBAC, api_keys, embeddings, audit/usage logs
--   Neo4j:    articles, entities, signals, review_events, relationships
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- TIERS (Subscription plans)
-- ============================================================================
CREATE TABLE tiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,  -- 'free', 'pro', 'enterprise'
    display_name VARCHAR(100) NOT NULL,
    description TEXT,

    -- Limits
    max_users INT,
    max_signals_monthly INT,
    max_articles INT,
    max_ai_tokens_monthly BIGINT,

    -- Pricing (cents)
    price_monthly_cents INT DEFAULT 0,
    price_yearly_cents INT DEFAULT 0,

    -- Metadata
    is_public BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO tiers (id, name, display_name, max_users, max_signals_monthly, max_articles, max_ai_tokens_monthly) VALUES
    ('00000000-0000-0000-0000-000000000001', 'free', 'Free', 3, 100, 50, 100000),
    ('00000000-0000-0000-0000-000000000002', 'pro', 'Pro', 20, 1000, 500, 1000000),
    ('00000000-0000-0000-0000-000000000003', 'enterprise', 'Enterprise', NULL, NULL, NULL, NULL);

-- ============================================================================
-- TENANTS (Organizations)
-- ============================================================================
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    domain VARCHAR(255) UNIQUE,

    -- Subscription
    tier_id UUID NOT NULL REFERENCES tiers(id) DEFAULT '00000000-0000-0000-0000-000000000001',

    -- Compliance: Data residency (GDPR)
    data_region VARCHAR(10) NOT NULL DEFAULT 'us' CHECK (data_region IN ('us', 'eu', 'ap')),

    -- Compliance: Data processing agreement
    dpa_signed_at TIMESTAMPTZ,
    dpa_version VARCHAR(20),

    -- Compliance: Retention (0 = forever)
    data_retention_days INT NOT NULL DEFAULT 0,

    -- Settings
    settings JSONB DEFAULT '{}',

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'pending_deletion')),
    suspended_at TIMESTAMPTZ,
    suspended_reason TEXT,
    deletion_requested_at TIMESTAMPTZ,
    deletion_scheduled_at TIMESTAMPTZ,

    -- Audit columns
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_tenants_slug ON tenants (slug) WHERE deleted_at IS NULL;
CREATE INDEX idx_tenants_domain ON tenants (domain) WHERE deleted_at IS NULL;
CREATE INDEX idx_tenants_status ON tenants (status) WHERE deleted_at IS NULL;

-- ============================================================================
-- USERS (Authentication - minimal PII here)
-- ============================================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Identity (minimal)
    email VARCHAR(255) NOT NULL,
    auth_user_id UUID UNIQUE,  -- Supabase Auth link

    -- Security
    password_hash VARCHAR(255),
    mfa_enabled BOOLEAN DEFAULT FALSE,
    mfa_secret VARCHAR(255),

    -- Access control
    last_login_at TIMESTAMPTZ,
    last_login_ip INET,
    failed_login_count INT DEFAULT 0,
    locked_until TIMESTAMPTZ,

    -- Status
    status VARCHAR(50) NOT NULL DEFAULT 'invited' CHECK (status IN ('invited', 'active', 'suspended', 'locked', 'deleted')),

    -- Audit columns
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,
    created_by UUID,
    updated_by UUID,

    UNIQUE(tenant_id, email)
);

CREATE INDEX idx_users_tenant ON users (tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_email ON users (email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_auth ON users (auth_user_id) WHERE deleted_at IS NULL;

-- ============================================================================
-- USER PROFILES (PII isolated - GDPR)
-- ============================================================================
-- Separated from users table so developers can work with user IDs
-- without accessing PII. Easier to encrypt, audit, and delete.
CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- PII fields
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(50),
    avatar_url TEXT,
    timezone VARCHAR(50) DEFAULT 'UTC',
    locale VARCHAR(10) DEFAULT 'en',

    -- GDPR consent
    privacy_consent_at TIMESTAMPTZ,
    privacy_consent_version VARCHAR(20),
    marketing_consent BOOLEAN DEFAULT FALSE,
    marketing_consent_at TIMESTAMPTZ,

    -- Audit columns
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_profiles_tenant ON user_profiles (tenant_id);

-- ============================================================================
-- RBAC: ROLES
-- ============================================================================
CREATE TABLE roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = system role

    name VARCHAR(100) NOT NULL,
    description TEXT,
    is_system BOOLEAN DEFAULT FALSE,  -- System roles can't be deleted

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(tenant_id, name)
);

-- System roles (tenant_id = NULL)
INSERT INTO roles (id, tenant_id, name, description, is_system) VALUES
    ('00000000-0000-0000-0000-000000000010', NULL, 'owner', 'Full access, can delete tenant', TRUE),
    ('00000000-0000-0000-0000-000000000011', NULL, 'admin', 'Full access except tenant deletion', TRUE),
    ('00000000-0000-0000-0000-000000000012', NULL, 'member', 'Standard access', TRUE),
    ('00000000-0000-0000-0000-000000000013', NULL, 'viewer', 'Read-only access', TRUE);

-- ============================================================================
-- RBAC: PERMISSIONS
-- ============================================================================
CREATE TABLE permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    resource VARCHAR(100) NOT NULL,  -- 'articles', 'users', 'billing', 'settings'
    action VARCHAR(50) NOT NULL,     -- 'create', 'read', 'update', 'delete', 'admin'
    description TEXT,

    UNIQUE(resource, action)
);

-- Seed permissions
INSERT INTO permissions (resource, action, description) VALUES
    ('articles', 'create', 'Create knowledge articles'),
    ('articles', 'read', 'View knowledge articles'),
    ('articles', 'update', 'Edit knowledge articles'),
    ('articles', 'delete', 'Delete knowledge articles'),
    ('articles', 'review', 'Approve/reject pending articles'),
    ('signals', 'create', 'Ingest signals'),
    ('signals', 'read', 'View signals'),
    ('users', 'read', 'View team members'),
    ('users', 'invite', 'Invite new users'),
    ('users', 'update', 'Edit user details'),
    ('users', 'delete', 'Remove users'),
    ('roles', 'read', 'View roles'),
    ('roles', 'manage', 'Create/edit custom roles'),
    ('api_keys', 'read', 'View API keys'),
    ('api_keys', 'manage', 'Create/revoke API keys'),
    ('billing', 'read', 'View billing info'),
    ('billing', 'manage', 'Update payment methods'),
    ('settings', 'read', 'View tenant settings'),
    ('settings', 'manage', 'Update tenant settings'),
    ('audit_logs', 'read', 'View audit logs');

-- ============================================================================
-- RBAC: ROLE -> PERMISSIONS
-- ============================================================================
CREATE TABLE role_permissions (
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_id UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,

    PRIMARY KEY (role_id, permission_id)
);

-- Owner gets everything
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000000-0000-0000-0000-000000000010', id FROM permissions;

-- Admin gets everything except billing.manage
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000000-0000-0000-0000-000000000011', id FROM permissions
WHERE NOT (resource = 'billing' AND action = 'manage');

-- Member gets standard access
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000000-0000-0000-0000-000000000012', id FROM permissions
WHERE action IN ('create', 'read', 'update') AND resource IN ('articles', 'signals');

-- Viewer gets read-only
INSERT INTO role_permissions (role_id, permission_id)
SELECT '00000000-0000-0000-0000-000000000013', id FROM permissions
WHERE action = 'read' AND resource IN ('articles', 'signals');

-- ============================================================================
-- RBAC: USER -> ROLES
-- ============================================================================
CREATE TABLE user_roles (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    granted_by UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ DEFAULT NOW(),

    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX idx_user_roles_user ON user_roles (user_id);
CREATE INDEX idx_user_roles_tenant ON user_roles (tenant_id);

-- ============================================================================
-- FEATURE FLAGS
-- ============================================================================
CREATE TABLE feature_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    flag_key VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    default_state BOOLEAN DEFAULT FALSE,

    -- Rollout
    rollout_percentage INT DEFAULT 0 CHECK (rollout_percentage BETWEEN 0 AND 100),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO feature_flags (flag_key, description, default_state) VALUES
    ('ai_synthesis', 'Enable AI article synthesis', TRUE),
    ('conflict_detection', 'Enable conflict detection', TRUE),
    ('bulk_import', 'Allow bulk signal import', FALSE),
    ('custom_models', 'Allow custom embedding models', FALSE),
    ('sso', 'Enable SSO authentication', FALSE),
    ('advanced_analytics', 'Enable advanced analytics dashboard', FALSE);

-- ============================================================================
-- TENANT FEATURE FLAGS (Overrides)
-- ============================================================================
CREATE TABLE tenant_feature_flags (
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    flag_key VARCHAR(100) NOT NULL REFERENCES feature_flags(flag_key) ON DELETE CASCADE,

    is_enabled BOOLEAN NOT NULL,
    overridden_by UUID REFERENCES users(id),
    overridden_at TIMESTAMPTZ DEFAULT NOW(),
    reason TEXT,

    PRIMARY KEY (tenant_id, flag_key)
);

-- ============================================================================
-- USER SESSIONS (SOC 2: Session tracking)
-- ============================================================================
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Session
    session_token_hash VARCHAR(255) NOT NULL,

    -- Context
    ip_address INET,
    user_agent TEXT,
    country_code VARCHAR(2),
    city VARCHAR(100),

    -- Lifecycle
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT
);

CREATE INDEX idx_sessions_user ON user_sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_sessions_token ON user_sessions (session_token_hash) WHERE revoked_at IS NULL;

-- ============================================================================
-- API KEYS
-- ============================================================================
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Identity
    name VARCHAR(100) NOT NULL,
    description TEXT,
    key_prefix VARCHAR(12) NOT NULL,  -- "kl_live_abc1" for identification
    key_hash VARCHAR(255) NOT NULL,

    -- Authorization
    scopes TEXT[] DEFAULT ARRAY['read'],
    allowed_ips INET[],

    -- Rate limiting
    rate_limit_rpm INT DEFAULT 1000,

    -- Usage
    last_used_at TIMESTAMPTZ,
    last_used_ip INET,
    total_requests BIGINT DEFAULT 0,

    -- Lifecycle
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revoked_by UUID REFERENCES users(id),
    revoked_reason TEXT,

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id)
);

CREATE INDEX idx_api_keys_tenant ON api_keys (tenant_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_api_keys_prefix ON api_keys (key_prefix);
CREATE INDEX idx_api_keys_hash ON api_keys (key_hash) WHERE revoked_at IS NULL;

-- ============================================================================
-- EMBEDDINGS (Vector store - references Neo4j)
-- ============================================================================
CREATE TABLE embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Reference to Neo4j Article
    article_id VARCHAR(36) NOT NULL,

    -- Vector
    embedding vector(768) NOT NULL,
    model VARCHAR(50) NOT NULL DEFAULT 'text-embedding-004',
    model_version VARCHAR(20),

    -- Metadata
    metadata JSONB DEFAULT '{}',

    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES users(id),

    UNIQUE(tenant_id, article_id)
);

CREATE INDEX idx_embeddings_tenant ON embeddings (tenant_id);
CREATE INDEX idx_embeddings_article ON embeddings (article_id);

-- ============================================================================
-- AUDIT LOGS (SOC 2 / ISO 27001 - Immutable)
-- ============================================================================
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Context
    tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
    actor_id UUID,  -- User or system
    actor_type VARCHAR(20) DEFAULT 'user' CHECK (actor_type IN ('user', 'api_key', 'system', 'webhook')),
    api_key_id UUID REFERENCES api_keys(id) ON DELETE SET NULL,

    -- Request
    request_id VARCHAR(100),
    ip_address INET,
    user_agent TEXT,

    -- Action
    action VARCHAR(100) NOT NULL,  -- 'user.login', 'article.create', 'api_key.revoke'
    table_name VARCHAR(100),
    record_id VARCHAR(100),

    -- Result
    status VARCHAR(20) NOT NULL CHECK (status IN ('success', 'failure', 'denied')),
    failure_reason TEXT,

    -- Changes
    old_values JSONB,
    new_values JSONB,

    -- Compliance
    data_classification VARCHAR(20),  -- 'public', 'internal', 'confidential', 'restricted'
    contains_pii BOOLEAN DEFAULT FALSE,

    -- Immutable timestamp
    created_at TIMESTAMPTZ DEFAULT NOW()
    -- NO updated_at or deleted_at - this table is APPEND ONLY
);

CREATE INDEX idx_audit_tenant_time ON audit_logs (tenant_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_logs (actor_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_logs (action, created_at DESC);
CREATE INDEX idx_audit_record ON audit_logs (table_name, record_id);
CREATE INDEX idx_audit_request ON audit_logs (request_id);

-- ============================================================================
-- SECURITY EVENTS (SOC 2: Anomaly detection)
-- ============================================================================
CREATE TABLE security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    tenant_id UUID REFERENCES tenants(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Event
    event_type VARCHAR(50) NOT NULL,  -- 'failed_login', 'suspicious_ip', 'impossible_travel', 'rate_limit'
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    description TEXT NOT NULL,

    -- Context
    ip_address INET,
    user_agent TEXT,
    metadata JSONB DEFAULT '{}',

    -- Response
    auto_action TEXT,  -- 'none', 'rate_limited', 'blocked', 'account_locked'

    -- Review
    reviewed_at TIMESTAMPTZ,
    reviewed_by UUID REFERENCES users(id),
    review_notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_security_tenant ON security_events (tenant_id, created_at DESC);
CREATE INDEX idx_security_unreviewed ON security_events (severity, created_at DESC) WHERE reviewed_at IS NULL;

-- ============================================================================
-- AI USAGE LOGS (Token tracking for billing)
-- ============================================================================
CREATE TABLE ai_usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Model
    model_name VARCHAR(100) NOT NULL,  -- 'gpt-4o', 'text-embedding-004'
    model_provider VARCHAR(50) NOT NULL,  -- 'openai', 'google', 'anthropic'

    -- Context
    feature_context VARCHAR(100),  -- 'synthesis', 'embedding', 'extraction'
    request_id VARCHAR(100),

    -- Usage
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT GENERATED ALWAYS AS (prompt_tokens + completion_tokens) STORED,

    -- Cost (in microdollars for precision: $0.01 = 10000)
    cost_microdollars BIGINT NOT NULL DEFAULT 0,

    -- Timing
    latency_ms INT,

    created_at TIMESTAMPTZ DEFAULT NOW()
    -- NO PII: Do not store prompt/completion text here
);

CREATE INDEX idx_ai_usage_tenant ON ai_usage_logs (tenant_id, created_at DESC);
CREATE INDEX idx_ai_usage_user ON ai_usage_logs (user_id, created_at DESC);
CREATE INDEX idx_ai_usage_billing ON ai_usage_logs (tenant_id, created_at);

-- ============================================================================
-- DATA EXPORT REQUESTS (GDPR: Right to access / erasure)
-- ============================================================================
CREATE TABLE data_export_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    request_type VARCHAR(20) NOT NULL CHECK (request_type IN ('export', 'deletion')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),

    -- Processing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,

    -- Export
    download_url TEXT,
    download_expires_at TIMESTAMPTZ,

    -- Deletion verification
    verified_at TIMESTAMPTZ,
    verified_by UUID REFERENCES users(id),

    requested_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_export_requests_user ON data_export_requests (user_id, requested_at DESC);
CREATE INDEX idx_export_requests_pending ON data_export_requests (status) WHERE status IN ('pending', 'processing');

-- ============================================================================
-- ROW-LEVEL SECURITY
-- ============================================================================

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE security_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_usage_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_export_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenant_feature_flags ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- RLS HELPER FUNCTIONS
-- ============================================================================

CREATE OR REPLACE FUNCTION public.kl_tenant_id()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('request.jwt.claims', true)::json->>'tenant_id', '')::UUID;
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION public.kl_user_id()
RETURNS UUID AS $$
BEGIN
    RETURN NULLIF(current_setting('request.jwt.claims', true)::json->>'sub', '')::UUID;
EXCEPTION WHEN OTHERS THEN RETURN NULL;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION public.kl_is_service_role()
RETURNS BOOLEAN AS $$
BEGIN
    RETURN COALESCE(current_setting('request.jwt.claims', true)::json->>'role' = 'service_role', FALSE);
EXCEPTION WHEN OTHERS THEN RETURN FALSE;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

-- Check if user has a specific permission
CREATE OR REPLACE FUNCTION public.kl_has_permission(p_resource TEXT, p_action TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM user_roles ur
        JOIN role_permissions rp ON rp.role_id = ur.role_id
        JOIN permissions p ON p.id = rp.permission_id
        WHERE ur.user_id = kl_user_id()
          AND ur.tenant_id = kl_tenant_id()
          AND p.resource = p_resource
          AND p.action = p_action
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

-- ============================================================================
-- RLS POLICIES
-- ============================================================================

-- Tenants
CREATE POLICY tenants_isolation ON tenants FOR ALL
    USING (id = kl_tenant_id() OR kl_is_service_role());

-- Users
CREATE POLICY users_isolation ON users FOR SELECT
    USING ((tenant_id = kl_tenant_id() AND deleted_at IS NULL) OR kl_is_service_role());
CREATE POLICY users_insert ON users FOR INSERT
    WITH CHECK (tenant_id = kl_tenant_id() AND kl_has_permission('users', 'invite') OR kl_is_service_role());
CREATE POLICY users_update ON users FOR UPDATE
    USING ((tenant_id = kl_tenant_id() AND (id = kl_user_id() OR kl_has_permission('users', 'update'))) OR kl_is_service_role());

-- User Profiles
CREATE POLICY profiles_isolation ON user_profiles FOR ALL
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());

-- Roles (system roles visible to all, tenant roles to their tenant)
CREATE POLICY roles_select ON roles FOR SELECT
    USING (tenant_id IS NULL OR tenant_id = kl_tenant_id() OR kl_is_service_role());
CREATE POLICY roles_manage ON roles FOR ALL
    USING ((tenant_id = kl_tenant_id() AND kl_has_permission('roles', 'manage')) OR kl_is_service_role());

-- User Roles
CREATE POLICY user_roles_isolation ON user_roles FOR ALL
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());

-- Sessions
CREATE POLICY sessions_isolation ON user_sessions FOR ALL
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());

-- API Keys
CREATE POLICY api_keys_select ON api_keys FOR SELECT
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());
CREATE POLICY api_keys_manage ON api_keys FOR ALL
    USING ((tenant_id = kl_tenant_id() AND kl_has_permission('api_keys', 'manage')) OR kl_is_service_role());

-- Embeddings
CREATE POLICY embeddings_isolation ON embeddings FOR ALL
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());

-- Audit Logs (read-only for admins, insert by service only)
CREATE POLICY audit_select ON audit_logs FOR SELECT
    USING ((tenant_id = kl_tenant_id() AND kl_has_permission('audit_logs', 'read')) OR kl_is_service_role());
CREATE POLICY audit_insert ON audit_logs FOR INSERT
    WITH CHECK (kl_is_service_role());

-- Security Events
CREATE POLICY security_select ON security_events FOR SELECT
    USING ((tenant_id = kl_tenant_id() AND kl_has_permission('audit_logs', 'read')) OR kl_is_service_role());
CREATE POLICY security_insert ON security_events FOR INSERT
    WITH CHECK (kl_is_service_role());

-- AI Usage Logs
CREATE POLICY ai_usage_isolation ON ai_usage_logs FOR SELECT
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());
CREATE POLICY ai_usage_insert ON ai_usage_logs FOR INSERT
    WITH CHECK (kl_is_service_role());

-- Data Export Requests
CREATE POLICY export_select ON data_export_requests FOR SELECT
    USING ((tenant_id = kl_tenant_id() AND (user_id = kl_user_id() OR kl_has_permission('users', 'update'))) OR kl_is_service_role());
CREATE POLICY export_insert ON data_export_requests FOR INSERT
    WITH CHECK (tenant_id = kl_tenant_id() AND user_id = kl_user_id() OR kl_is_service_role());

-- Tenant Feature Flags
CREATE POLICY feature_flags_isolation ON tenant_feature_flags FOR ALL
    USING (tenant_id = kl_tenant_id() OR kl_is_service_role());

-- ============================================================================
-- TRIGGERS
-- ============================================================================

CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER set_updated_at BEFORE UPDATE ON tenants FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON user_profiles FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON roles FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON embeddings FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON feature_flags FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();
CREATE TRIGGER set_updated_at BEFORE UPDATE ON tiers FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Log an audit event
CREATE OR REPLACE FUNCTION log_audit(
    p_action TEXT,
    p_table_name TEXT DEFAULT NULL,
    p_record_id TEXT DEFAULT NULL,
    p_status TEXT DEFAULT 'success',
    p_old_values JSONB DEFAULT NULL,
    p_new_values JSONB DEFAULT NULL,
    p_failure_reason TEXT DEFAULT NULL,
    p_contains_pii BOOLEAN DEFAULT FALSE
)
RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO audit_logs (
        tenant_id, actor_id, action, table_name, record_id,
        status, old_values, new_values, failure_reason, contains_pii
    ) VALUES (
        kl_tenant_id(), kl_user_id(), p_action, p_table_name, p_record_id,
        p_status, p_old_values, p_new_values, p_failure_reason, p_contains_pii
    ) RETURNING id INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Log AI usage
CREATE OR REPLACE FUNCTION log_ai_usage(
    p_tenant_id UUID,
    p_user_id UUID,
    p_model_name TEXT,
    p_model_provider TEXT,
    p_feature_context TEXT,
    p_prompt_tokens INT,
    p_completion_tokens INT,
    p_cost_microdollars BIGINT,
    p_latency_ms INT DEFAULT NULL
)
RETURNS UUID AS $$
DECLARE
    v_id UUID;
BEGIN
    INSERT INTO ai_usage_logs (
        tenant_id, user_id, model_name, model_provider, feature_context,
        prompt_tokens, completion_tokens, cost_microdollars, latency_ms
    ) VALUES (
        p_tenant_id, p_user_id, p_model_name, p_model_provider, p_feature_context,
        p_prompt_tokens, p_completion_tokens, p_cost_microdollars, p_latency_ms
    ) RETURNING id INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Check feature flag for tenant
CREATE OR REPLACE FUNCTION is_feature_enabled(p_flag_key TEXT, p_tenant_id UUID DEFAULT NULL)
RETURNS BOOLEAN AS $$
DECLARE
    v_tenant_id UUID;
    v_override BOOLEAN;
    v_default BOOLEAN;
BEGIN
    v_tenant_id := COALESCE(p_tenant_id, kl_tenant_id());

    -- Check tenant override first
    SELECT is_enabled INTO v_override
    FROM tenant_feature_flags
    WHERE tenant_id = v_tenant_id AND flag_key = p_flag_key;

    IF v_override IS NOT NULL THEN
        RETURN v_override;
    END IF;

    -- Fall back to default
    SELECT default_state INTO v_default FROM feature_flags WHERE flag_key = p_flag_key;
    RETURN COALESCE(v_default, FALSE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

-- ============================================================================
-- SEED DATA
-- ============================================================================

-- System tenant (for internal use)
INSERT INTO tenants (id, name, slug, tier_id, data_region) VALUES
    ('00000000-0000-0000-0000-000000000000', 'System', 'system', '00000000-0000-0000-0000-000000000003', 'us')
ON CONFLICT (slug) DO NOTHING;

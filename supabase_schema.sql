-- ==============================================================================
-- Core AI Automation - Supabase PostgreSQL Database Schema
-- ==============================================================================
-- This schema establishes a high-performance database for:
-- 1. Google Maps Scraped Leads (deduplication on phone, location, status)
-- 2. Delivery Audit Logs (timestamps, delivery results, anti-ban analytics)
-- 3. Dynamic Message Templates (personalized marketing templates)
-- ==============================================================================

-- 1. Contacts & Leads Table
CREATE TABLE IF NOT EXISTS public.contacts (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    phone VARCHAR(20) NOT NULL UNIQUE,       -- Standardized 10-digit clean mobile number
    raw_phone TEXT,                         -- Raw phone as found on Google Maps
    address TEXT,
    website TEXT,
    search_query TEXT,                      -- e.g., 'coaching centers'
    location TEXT,                          -- e.g., 'Moradabad'
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Status pipeline: 'pending', 'sent', 'invalid', 'failed', 'opt_out'
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    last_contacted_at TIMESTAMPTZ,
    notes TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Indexing for fast search, deduplication and pending queues
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON public.contacts(phone);
CREATE INDEX IF NOT EXISTS idx_contacts_status ON public.contacts(status);
CREATE INDEX IF NOT EXISTS idx_contacts_location ON public.contacts(location);
CREATE INDEX IF NOT EXISTS idx_contacts_query ON public.contacts(search_query);

-- 2. Delivery Logs Table (Audit trail)
CREATE TABLE IF NOT EXISTS public.delivery_logs (
    id BIGSERIAL PRIMARY KEY,
    contact_id BIGINT REFERENCES public.contacts(id) ON DELETE SET NULL,
    phone VARCHAR(20) NOT NULL,
    name TEXT,
    status VARCHAR(20) NOT NULL,            -- 'SUCCESS', 'INVALID', 'FAILED'
    detail TEXT,                            -- Delivery note, error, or reason
    logged_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_delivery_logs_phone ON public.delivery_logs(phone);
CREATE INDEX IF NOT EXISTS idx_delivery_logs_status ON public.delivery_logs(status);
CREATE INDEX IF NOT EXISTS idx_delivery_logs_logged_at ON public.delivery_logs(logged_at DESC);

-- 3. Message Templates Table
CREATE TABLE IF NOT EXISTS public.message_templates (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Insert Default Message Template if empty
INSERT INTO public.message_templates (title, content, is_active)
SELECT 
    'Default Outreach Template',
    'Hello {name}, we noticed your profile under {query} in {location}. We offer premium AI-powered growth automation and lead systems tailored for educational institutes and businesses. Would you be open to a quick 2-minute overview?',
    TRUE
WHERE NOT EXISTS (SELECT 1 FROM public.message_templates);

-- 4. Automatic Updated At Trigger Function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON public.contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON public.contacts
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ==============================================================================
-- Row Level Security (RLS) Policies
-- ==============================================================================
-- Enable RLS for production safety
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delivery_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.message_templates ENABLE ROW LEVEL SECURITY;

-- Allow read/write access for authenticated and service_role, and anon read/write if using anon key
CREATE POLICY "Allow all access to contacts" ON public.contacts
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all access to delivery_logs" ON public.delivery_logs
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all access to message_templates" ON public.message_templates
    FOR ALL USING (true) WITH CHECK (true);

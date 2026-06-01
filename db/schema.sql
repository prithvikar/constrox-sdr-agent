-- Constrox SDR agent — commission & pipeline tables (design doc §7).
--
-- Commission/invoice state lives OUTSIDE the LangGraph SalesState: it is an
-- event-driven side-loop keyed by deal_id, fed by a billing `invoice.paid`
-- webhook. Recurring retainers re-fire a fresh commission row per monthly
-- paid invoice; one-off project packages fire once.
--
-- Mirrors commission.CommissionLedger (deals / invoices / commissions dicts).

-- --------------------------------------------------------------------------- --
-- deals — one row per opportunity, drives pipeline coverage & conversion math. --
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS deals (
    deal_id         TEXT PRIMARY KEY,
    lead_id         TEXT,
    company         TEXT,
    stage           TEXT NOT NULL DEFAULT 'open'
        CHECK (stage IN ('open', 'discovery', 'demo', 'negotiation', 'won', 'lost')),
    pipeline_value  NUMERIC(12, 2) NOT NULL DEFAULT 0,   -- expected MONTHLY billing
    recurring       BOOLEAN NOT NULL DEFAULT FALSE,      -- retainer vs one-off project
    won_amount      NUMERIC(12, 2),
    expected_close  DATE,
    lost_reason     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deals_stage ON deals (stage);

-- --------------------------------------------------------------------------- --
-- invoices — billing events; status flips to 'paid' on the webhook.            --
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id  TEXT PRIMARY KEY,
    deal_id     TEXT NOT NULL REFERENCES deals (deal_id),
    amount      NUMERIC(12, 2) NOT NULL,                 -- monthly basis amount
    status      TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'paid', 'void', 'uncollectible')),
    period      TEXT,                                    -- e.g. billing month '2026-06'
    paid_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_invoices_deal ON invoices (deal_id);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices (status);

-- --------------------------------------------------------------------------- --
-- commissions — one row per paid invoice (recurring re-fires monthly).         --
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS commissions (
    commission_id       TEXT PRIMARY KEY,
    deal_id             TEXT NOT NULL REFERENCES deals (deal_id),
    invoice_id          TEXT NOT NULL REFERENCES invoices (invoice_id),
    rate                NUMERIC(5, 4) NOT NULL,          -- 0.07 / 0.10 / 0.13
    basis_amount        NUMERIC(12, 2) NOT NULL,         -- invoice amount commission is on
    commission_amount   NUMERIC(12, 2) NOT NULL,         -- rate * basis_amount
    recurring_schedule  BOOLEAN NOT NULL DEFAULT FALSE,  -- deal.recurring at time of fire
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- one commission per invoice keeps the webhook side-loop idempotent
    UNIQUE (invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_commissions_deal ON commissions (deal_id);

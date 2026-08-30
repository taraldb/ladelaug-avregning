# EV Charging HOA Portal - Product Backlog

## Roles

### Member

A member can:

- View own balance
- View current month consumption
- View estimated current costs
- View settlement history
- Download reports
- View low-balance warnings
- Access Zaptec portal link

### Administrator

An administrator can:

- Manage members
- Manage charger assignments
- Synchronize Zaptec data
- Create settlements
- Record payments and refunds
- Create corrections
- Manage charging access status
- Review forecasts
- View audit logs

---

# Epic 1 - Identity & Authorization

## US-101 Sign in with email and password

**Priority:** P0

As a user, I want to sign in using email and password so that I can securely access my account.

### Acceptance Criteria

- Verified email address required
- Password stored securely
- Rate limiting for failed attempts
- Disabled users cannot sign in
- Security events logged

---

## US-102 Passwordless sign-in

**Priority:** P1

As a user, I want a passwordless login link so that I can access the portal without remembering a password.

### Acceptance Criteria

- Link sent to registered email
- One-time use
- Time-limited expiration
- Disabled users blocked
- Usage logged

---

## US-103 Password Reset

**Priority:** P1

As a user, I want to reset a forgotten password.

### Acceptance Criteria

- Single-use reset token
- Expiring reset links
- User notified after successful reset

---

## US-104 Role-based authorization

**Priority:** P0

As the association, I want members restricted to their own data.

### Acceptance Criteria

- Members see only their own data
- Admins see all records
- Authorization enforced server-side
- Changes logged

---

# Epic 2 - Member Administration

## US-201 Create and maintain member

**Priority:** P0

As an administrator, I want to manage member records.

### Acceptance Criteria

- Name
- Email
- Member reference
- Join date
- Audit logging

---

## US-202 Manage active status

**Priority:** P0

As an administrator, I want to activate or deactivate members.

### Acceptance Criteria

- Effective dates stored
- History retained
- Active users suggested for settlements
- All changes logged

---

## US-203 Settlement participation

**Priority:** P0

As an administrator, I want to decide who participates in equal-cost allocation.

### Acceptance Criteria

- System suggests active users
- Admin may include/exclude users
- Excluded users can still receive consumption costs
- Decision frozen on settlement posting

---

## US-204 Member departure

**Priority:** P1

As an administrator, I want to process member departures.

### Acceptance Criteria

- End active status
- End charger assignments
- Detect unsettled consumption
- Support refunds
- Historical data retained

---

# Epic 3 - Charger Management

## US-301 Synchronize chargers

**Priority:** P0

As an administrator, I want chargers synchronized from Zaptec.

### Acceptance Criteria

- Import charger metadata
- Idempotent synchronization
- Status visibility

---

## US-302 Assign charger

**Priority:** P0

As an administrator, I want chargers assigned to members.

### Acceptance Criteria

- Effective dates
- Non-overlapping ownership
- Full history retained

---

## US-303 Charger replacement

**Priority:** P0

As an administrator, I want replacement chargers supported.

### Acceptance Criteria

- Member may temporarily have multiple chargers
- Consumption remains traceable

---

## US-304 Unassigned charger detection

**Priority:** P0

As an administrator, I want unassigned consumption detected.

### Acceptance Criteria

- Unassigned usage identified
- Settlement posting blocked until resolved

---

## US-305 Charging access status

**Priority:** P1

As an administrator, I want charging access actions recorded.

### Acceptance Criteria

- Warning sent
- Disabled
- Restored
- Fully audit logged

---

# Epic 4 - Zaptec Integration

## US-401 Connect Zaptec Installation

**Priority:** P0

As an administrator, I want to connect a Zaptec installation.

### Acceptance Criteria

- Secure credential storage
- Connection testing
- Error reporting

---

## US-402 Import charging sessions

**Priority:** P0

As an administrator, I want charging sessions imported.

### Acceptance Criteria

- Archived session endpoint
- Pagination support
- Idempotent import
- Duplicate prevention

---

## US-403 Incremental synchronization

**Priority:** P1

As the system, I want to synchronize continuously.

### Acceptance Criteria

- Scheduled jobs
- Retry failed imports
- Sync monitoring

---

## US-404 Import interval consumption

**Priority:** P0

As the system, I want interval consumption data.

### Acceptance Criteria

- Support 15-minute interval data
- Data quality checks
- Duplicate prevention

---

## US-405 Cross-month session splitting

**Priority:** P0

As an administrator, I want cross-month charging sessions split accurately.

### Acceptance Criteria

Priority order:

1. Interval data
2. Energy-point data
3. Duration estimation

Admin review available.

---

## US-406 Late session detection

**Priority:** P0

As an administrator, I want changes after settlement detected.

### Acceptance Criteria

- Late sessions flagged
- No automatic financial changes
- Admin correction workflow available

---

# Epic 5 - Financial Ledger

## US-501 Calculate balance

**Priority:** P0

As a member, I want an accurate prepaid balance.

### Acceptance Criteria

Balance equals all posted ledger transactions.

---

## US-502 Record payment

**Priority:** P0

As an administrator, I want to record incoming payments.

### Acceptance Criteria

- Member
- Amount
- Date
- Optional budget reference

Creates ledger entry.

---

## US-503 Reverse incorrect payment

**Priority:** P0

As an administrator, I want incorrect payments reversed.

### Acceptance Criteria

- No editing
- Reversal transaction required
- Audit trail preserved

---

## US-504 Manual adjustment

**Priority:** P0

As an administrator, I want manual debit/credit adjustments.

### Acceptance Criteria

- Reason required
- Immutable ledger entry

---

## US-505 Refund member balance

**Priority:** P1

As an administrator, I want refunds recorded properly.

### Acceptance Criteria

- Refund ledger transaction
- Audit logging
- Optional accounting reference

---

# Epic 6 - Settlement Processing

## US-601 Create settlement

**Priority:** P0

As an administrator, I want monthly settlements.

### Acceptance Criteria

- Full calendar month
- One settlement per month
- Draft support

---

## US-602 Freeze usage

**Priority:** P0

As an administrator, I want settlement usage frozen.

### Acceptance Criteria

- Usage snapshot stored
- Posted settlements immutable

---

## US-603 Enter invoice consumption

**Priority:** P0

As an administrator, I want invoice kWh recorded.

### Acceptance Criteria

- Invoice kWh mandatory
- Difference calculation visible

---

## US-604 Attach invoice

**Priority:** P0

As an administrator, I want invoice attachments stored.

### Acceptance Criteria

- Attachment required before posting
- Administrator-only access

---

## US-605 Add invoice lines

**Priority:** P0

As an administrator, I want invoice lines recorded.

### Acceptance Criteria

Fields:

- Description
- Category
- Allocation Method
- Amount incl. VAT

---

## US-606 Equal-cost allocation

**Priority:** P0

As the system, I want equal-cost invoice lines distributed equally.

### Acceptance Criteria

- Included members only
- Deterministic rounding

---

## US-607 Consumption allocation

**Priority:** P0

As the system, I want consumption-based costs distributed by kWh.

### Acceptance Criteria

- Based on member consumption ratio
- Zero consumption blocks settlement

---

## US-608 Preview settlement

**Priority:** P0

As an administrator, I want a preview before posting.

### Acceptance Criteria

Shows:

- kWh
- Costs
- Balance impact
- Warnings
- Negative balances

---

## US-609 Post settlement

**Priority:** P0

As an administrator, I want charges posted to balances.

### Acceptance Criteria

- Creates settlement ledger entries
- Prevents duplicate posting
- Generates reports

---

## US-610 Rounding

**Priority:** P0

As the system, I want deterministic rounding.

### Acceptance Criteria

- Largest allocation receives residual øre
- Total allocations equal invoice amount

---

# Epic 7 - Settlement Corrections

## US-701 Assess correction impact

**Priority:** P1

As an administrator, I want to compare new data against posted settlements.

---

## US-702 Calculate correction

**Priority:** P1

As an administrator, I want corrected allocations calculated.

---

## US-703 Post correction

**Priority:** P1

As an administrator, I want correction differences recorded.

### Acceptance Criteria

- Original settlement preserved
- Adjustment transactions created
- Members notified

---

# Epic 8 - Forecasting

## US-801 Forecast usage

**Priority:** P1

As a member, I want future consumption estimated.

### Acceptance Criteria

- Last 3 settlement months
- No seasonality in MVP

---

## US-802 Forecast pricing

**Priority:** P1

As an administrator, I want forecast rates controlled.

### Acceptance Criteria

- Historical default
- Admin override

---

## US-803 Estimate equal-cost share

**Priority:** P1

As the system, I want future fixed costs included.

---

## US-804 Recommended minimum balance

**Priority:** P1

As a member, I want a minimum balance recommendation.

---

## US-805 Low-balance warning

**Priority:** P1

As a member, I want warning emails before my balance becomes insufficient.

### Acceptance Criteria

- Email
- Dashboard warning
- Duplicate suppression

---

# Epic 9 - Member Portal

## US-901 Account summary

**Priority:** P1

As a member, I want a dashboard showing:

- Balance
- Consumption
- Forecast

---

## US-902 View consumption

**Priority:** P1

As a member, I want current-month consumption visibility.

---

## US-903 View estimated costs

**Priority:** P1

As a member, I want estimated future costs.

---

## US-904 Settlement history

**Priority:** P1

As a member, I want historical settlements available.

---

## US-905 Settlement reports

**Priority:** P1

As the system, I want reports generated automatically.

### Contents

- Consumption
- Breakdown
- Balance before
- Balance after
- Forecast
- Recommended top-up

---

## US-906 PDF download

**Priority:** P1

As a member, I want downloadable PDF reports.

---

# Epic 10 - Notifications

## US-1001 Email settlement report

**Priority:** P1

As a member, I want monthly settlement emails.

---

## US-1002 Retry failed emails

**Priority:** P1

As an administrator, I want failed deliveries retried.

---

## US-1003 Access removal warning

**Priority:** P1

As an administrator, I want members warned before charging access is removed.

---

## US-1004 Access restored notification

**Priority:** P2

As a member, I want to know when charging access is restored.

---

# Epic 11 - Audit & Operations

## US-1101 Audit log

**Priority:** P0

As an administrator, I want complete audit visibility.

---

## US-1102 Financial audit

**Priority:** P0

As the association, I want all financial actions logged.

---

## US-1103 Settlement decision audit

**Priority:** P0

As the association, I want settlement overrides fully traceable.

---

## US-1104 System health

**Priority:** P1

As an administrator, I want operational visibility.

### Includes

- Zaptec sync status
- Email delivery status
- Failed jobs

---

# Release Plan

## Release 1A

- Identity
- Member administration
- Charger management
- Ledger foundation
- Audit logging

---

## Release 1B

- Zaptec integration
- Settlement engine
- Invoice handling
- PDF reports
- Email reports

---

## Release 1C

- Member portal
- Forecasting
- Low-balance warnings

---

## Release 1D

- Corrections
- Refunds
- Member departure
- Charging access workflows

---

# Release 2 Candidates

- Automatic bank imports
- Direct Zaptec access control
- Seasonal forecasting
- Budget system integration
- Advanced reporting
- Electronic identity support

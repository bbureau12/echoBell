# ADR-0002: Treat license plates as PII and store only HMAC hashes
Date: 2025-12-30
Status: Accepted

## Context
License plates are personally identifiable information (PII) and should not be
stored in raw form. EchoBell requires repeat-vehicle detection while minimizing
privacy risk.

## Decision
All license plate text is normalized and hashed using an HMAC with a secret key.
Only the resulting hash (plate_hmac) is stored.

Raw plate text is never persisted to disk or logs.

## Consequences
Pros:
- Prevents reconstruction of license plates from stored data
- Enables repeat detection and trusted plate allowlists
- Keeps the system privacy-forward and auditable

Cons:
- Raw plate text cannot be recovered for debugging

Mitigations:
- Plate OCR debugging is performed only in-memory during development
- Trusted plates are added by hashing raw input at insertion time

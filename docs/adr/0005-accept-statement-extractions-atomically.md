# Accept statement extractions atomically

Billzebub will stage every statement Extraction and accept its complete Claim set only after the Source Artifact passes account, period, currency, row-coverage, decimal, provenance, duplicate, and available total or balance validations; a failed Extraction creates no Claims. Failed Source Artifacts may be reprocessed automatically after parser upgrades, but replacing a successful Extraction requires an explicit Claim-level diff, favoring trustworthy history over partial availability or silent parser reinterpretation.

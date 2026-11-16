# Project development notes

VI ClipForge is a local, single-operator discovery and media-production product. See README, docs/ARCHITECTURE.md and docs/VERIFICATION.md for current implementation and actual checks. The Desktop/ClipFarmer master brief remains unchanged.

Preserve demo mode. Metadata discovery never implies media access or reuse permission. Use official platform APIs only; do not turn approval-required adapters into scrapers. Keep secrets backend-only. Use migrations and real FFmpeg tests for processing changes. Record verification limits honestly; no live account, public deployment, Docker runtime or libass claim without exercising it.

# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Strict benchmark scenario suite at `tests/scenarios/chintu_50_personal_daily.py`.
- Benchmark runner v2 features in `scripts/chintu_50_realistic_benchmark.py`:
  - preflight mode
  - strict verification mode
  - setup-based skip handling
  - placeholder substitution
  - evidence/proof extraction
  - sandbox Downloads harness for safety tasks
- Local gate runner `scripts/run_quality_gates.ps1`.
- Docs integrity checker `scripts/docs_check.py`.
- Documentation runbooks and templates under `docs/runbooks/` and `docs/templates/`.
- Unit tests for benchmark v2 and short-content pipeline behavior.

### Changed
- Quality CI workflow now runs Python tests, docs check, doctor, and benchmark dry-run strict+allow-skips.
- YouTube Short generation now supports:
  - duration parsing via capability handler
  - benchmark output routing via context output directory
  - best-effort background image acquisition with fallback
  - metadata fields for background asset tracking

### Fixed
- Windows/regex escaping issues in benchmark scenario patterns.
- Placeholder substitution in several verification hook paths/patterns.
- Strict benchmark exit logic now allows skips when `--allow-skips` is set.

### Security
- Maintained hard-block behavior for payment/checkout phrasing in benchmark auto-approval safety logic.
- Maintained no-permanent-delete safety boundary and sandboxed destructive benchmark tasks.

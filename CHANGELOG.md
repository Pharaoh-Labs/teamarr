# Changelog

All notable changes to Teamarr will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0-beta] - 2025-01-20

### Added
- Initial beta release
- Support for 13 major leagues (NBA, NFL, MLB, NHL, MLS, EPL, La Liga, Bundesliga, Serie A, Ligue 1, NCAA Football, NCAA Men's/Women's Basketball)
- 150+ template variables for dynamic EPG descriptions
- Conditional description system with preset library
  - Win streak conditionals (3+ games)
  - Loss streak conditionals (3+ games)
  - Top 10 matchup conditionals
  - Rivalry game conditionals
  - Division game conditionals
  - Home/Away specific conditionals
- Web-based configuration interface on port 9195
- XMLTV EPG generation following Gracenote standards
- ESPN API integration for real-time data
- SQLite database for persistent storage
- Docker support with health checks
- Database caching for improved performance
- EPG generation history and error logging

### Features
- Add teams via ESPN URL or manual entry
- Template variable helper for building descriptions
- Automatic schedule refresh
- Customizable pregame/postgame descriptions
- Channel ID customization
- Team logo integration
- Categories and metadata management
- EPG download capability

### Technical
- Flask web framework
- Python 3.11+ support
- Docker and Docker Compose support
- Health check endpoint at `/health`
- RESTful API endpoints for team management
- Responsive web interface

---

## Release Notes

### Beta Release Notes

This is the first beta release of Teamarr. While the core functionality is stable and tested, you may encounter edge cases or unexpected behavior. Please report any issues on GitHub.

**Known Limitations:**
- ESPN API is unofficial and may change
- Some template variables depend on data availability from ESPN
- Scheduler functionality is basic and may need refinement

**Feedback Welcome:**
- GitHub Issues: https://github.com/egyptiangio/teamarr/issues
- GitHub Discussions: https://github.com/egyptiangio/teamarr/discussions

---

[Unreleased]: https://github.com/egyptiangio/teamarr/compare/v0.1.0-beta...HEAD
[0.1.0-beta]: https://github.com/egyptiangio/teamarr/releases/tag/v0.1.0-beta

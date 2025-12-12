# Development Guide

## Prerequisites

- Python 3.11 or higher
- Git

## Initial Setup

### 1. Clone the Repository

```bash
git clone <repo-url>
cd teamarrv2
```

### 2. Create Virtual Environment

**Why a virtual environment?**
- Isolates project dependencies from system Python
- Prevents conflicts with OS-managed packages
- Ensures reproducible builds across machines

```bash
# Create the virtual environment
python3 -m venv .venv

# Activate it (Linux/macOS)
source .venv/bin/activate

# Activate it (Windows)
.venv\Scripts\activate
```

**Your prompt should now show `(.venv)` prefix.**

### 3. Install Dependencies

```bash
# Install package in editable mode with dev dependencies
pip install -e ".[dev]"
```

This installs:
- `httpx` - HTTP client for API calls
- `pytest` - Testing framework
- `pytest-asyncio` - Async test support
- `ruff` - Fast linter and formatter

### 4. Verify Installation

```bash
# Check the package is installed
pip list | grep teamarr

# Run a quick import test
python -c "from teamarr.core import Team, Event; print('OK')"
```

---

## Daily Workflow

### Activating the Environment

Every time you open a new terminal:

```bash
cd /path/to/teamarrv2
source .venv/bin/activate
```

**Tip:** Add an alias to your shell config:
```bash
alias teamarr="cd /path/to/teamarrv2 && source .venv/bin/activate"
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/unit/test_espn_provider.py

# Run tests matching a pattern
pytest -k "test_parse"
```

### Linting and Formatting

```bash
# Check for issues
ruff check .

# Auto-fix issues
ruff check --fix .

# Format code
ruff format .
```

### Adding Dependencies

```bash
# Add to pyproject.toml under [project.dependencies] or [project.optional-dependencies.dev]
# Then reinstall:
pip install -e ".[dev]"
```

---

## Project Structure

```
teamarrv2/
├── .venv/                    # Virtual environment (git-ignored)
├── teamarr/                  # Main package
│   ├── core/                 # Types and interfaces
│   ├── providers/            # Data providers (ESPN, TheSportsDB)
│   ├── services/             # Service layer
│   ├── consumers/            # EPG generation, matching
│   └── ...
├── tests/                    # Test suite
│   ├── fixtures/             # Test data (captured API responses)
│   ├── unit/                 # Unit tests
│   └── integration/          # Integration tests
├── docs/                     # Documentation
├── CLAUDE.md                 # Project constitution
├── DEVELOPMENT.md            # This file
├── pyproject.toml            # Package configuration
└── README.md                 # Quick start
```

---

## IDE Setup

### VS Code

1. Open the project folder
2. VS Code should detect `.venv` automatically
3. If not, press `Ctrl+Shift+P` → "Python: Select Interpreter" → choose `.venv`

Recommended extensions:
- Python (Microsoft)
- Ruff (Astral Software)
- Even Better TOML

### PyCharm

1. Open the project
2. Settings → Project → Python Interpreter
3. Add Interpreter → Existing → Select `.venv/bin/python`

---

## Common Issues

### "ModuleNotFoundError: No module named 'teamarr'"

You're running Python outside the virtual environment.

```bash
# Make sure you're in the right directory
cd /path/to/teamarrv2

# Activate the environment
source .venv/bin/activate

# Verify
which python  # Should show .venv/bin/python
```

### "externally-managed-environment" error

You're trying to install packages to system Python. Always use the virtual environment:

```bash
source .venv/bin/activate
pip install <package>
```

### Tests can't find fixtures

Make sure you're running pytest from the project root:

```bash
cd /path/to/teamarrv2
pytest
```

### httpx SSL errors

If you get SSL certificate errors:

```bash
pip install certifi
```

---

## Testing Against Live APIs

### ESPN (No API key needed)

```bash
python -c "
from teamarr.providers.espn import ESPNProvider
from teamarr.services import SportsDataService

service = SportsDataService()
service.add_provider(ESPNProvider())

# Get Detroit Lions schedule
events = service.get_team_schedule('8', 'nfl')
for e in events[:3]:
    print(f'{e.start_time}: {e.name}')
"
```

### Capturing Test Fixtures

To capture API responses for offline tests:

```bash
python -c "
import json
from teamarr.providers.espn.client import ESPNClient

client = ESPNClient()
data = client.get_team_schedule('nfl', '8')

with open('tests/fixtures/espn/lions_schedule.json', 'w') as f:
    json.dump(data, f, indent=2)
"
```

---

## Git Workflow

### What's Git-Ignored

```
.venv/           # Virtual environment
__pycache__/     # Python bytecode
*.pyc
.pytest_cache/
*.egg-info/
```

### Before Committing

```bash
# Format and lint
ruff format .
ruff check --fix .

# Run tests
pytest

# Check for untracked files
git status
```

---

## Upgrading Dependencies

```bash
# Upgrade pip itself
pip install --upgrade pip

# Upgrade all packages
pip install --upgrade -e ".[dev]"

# Or upgrade specific package
pip install --upgrade httpx
```

---

## Deactivating the Environment

When you're done working:

```bash
deactivate
```

Your prompt will return to normal (no `(.venv)` prefix).

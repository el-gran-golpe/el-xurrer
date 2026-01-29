# Agentic Development Guidelines

## 🚀 Project Overview
- **Language**: Python 3.11+
- **Primary Frameworks/Tools**:
  - FastAPI
  - Pytest
  - Ruff (Linting & Formatting)
  - MyPy (Type Checking)
  - Pre-commit Hooks
  - Qodana (Code Quality)

## 🛠️ Development Setup

### Prerequisites
- Python 3.11+
- pip
- virtualenv (recommended)
- Git

### Dependency Management
```bash
# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Unix/macOS
# OR venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -r requirements-dev.txt
```

## 🧪 Testing Commands

### Running Tests
```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run tests for a specific module
pytest tests/module_name/

# Run a single test
pytest tests/module_name/test_file.py::test_function_name

# Run tests with coverage
pytest --cov=app tests/

# Run tests matching a pattern
pytest -k "login or callback"

# Run async tests
pytest -v -k "async" --asyncio-mode=strict

# Dry run (show tests without running)
pytest --collect-only
```

### Test Writing Guidelines
- Use `pytest` framework
- Leverage `pytest-asyncio` for async tests
- Place tests in `tests/` directory
- Name test files `test_*.py`
- Use descriptive test function names
- Include both positive and negative test scenarios
- Mock external API calls
- Use `@pytest.mark` for categorizing tests
- Aim for high code coverage

## 📝 Code Style & Conventions

### General Principles
- Follow PEP 8 guidelines
- Use type hints consistently
- Prioritize readability
- Keep functions small and focused (max 20 lines)
- Use meaningful variable and function names
- Avoid complex nested logic

### Import Conventions
```python
# Standard library imports first
import os
import sys
from typing import Dict, List, Optional, Union

# Third-party imports next
import httpx
import pydantic

# Local application imports last
from app.config import Settings
from app.oauth import generate_pkce_challenge
```

### Type Handling
- Always use type hints
- Leverage Pydantic for runtime type validation
- Use `Optional[Type]` for nullable fields
- Prefer `Union` over `Optional` when multiple types are possible
- Use `TypedDict` for complex dictionary structures

### Naming Conventions
- Use snake_case for variables and function names
- Use PascalCase for class names
- Use UPPER_CASE for constants
- Prefix private methods/attributes with single underscore
- Use descriptive, intention-revealing names
- Avoid abbreviations unless they're well-known

### Error Handling
- Use specific, custom exceptions
- Provide context in error messages
- Log errors with sufficient detail
- Use FastAPI's `HTTPException` for API errors
- Always include error codes and descriptive messages
- Use context managers for resource cleanup

### Logging Guidelines
- Use `logging` module with structured logging
- Configure log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Include contextual information
- Use `structlog` for structured logging when possible

## 🔍 Static Analysis & Linting

### Pre-commit Hooks
- Automatically run on every commit
- Checks include:
  - YAML syntax validation
  - Trailing whitespace removal
  - End-of-file newline enforcement
  - Ruff linting and formatting
  - MyPy type checking

### Ruff Linting
- Enforces PEP 8 style guide
- Automatically fixes many common issues
- Prevents common programming errors

### MyPy Type Checking
- Strict type checking
- Validates type annotations
- Catches type-related errors before runtime

### Qodana Code Quality
- Provides additional static code analysis
- Uses JetBrains' qodana.starter profile
- Identifies potential code improvements

## 🚦 Continuous Integration
- Automate testing and linting
- Run pre-commit hooks in CI pipeline
- Block merges if tests or linting fail
- Generate and publish coverage reports

## 🔒 Security Considerations
- Never log sensitive information
- Use environment variables for secrets
- Implement proper input validation
- Follow OAuth 2.0 security best practices
- Use HTTPS for all external communications
- Sanitize and validate all user inputs
- Use dependency scanning tools

## 📦 Deployment Recommendations
- Use Docker for consistent environments
- Implement health check endpoints
- Configure proper CORS settings
- Use environment-specific configurations
- Implement proper secret management

## 🤝 Collaboration Guidelines
- Write clear, concise commit messages
- Create descriptive pull request descriptions
- Include tests with new features
- Document complex logic and algorithms
- Use conventional commit messages

## 📋 Code Review Checklist
- [ ] Tests pass
- [ ] Type hints are correct
- [ ] No sensitive data exposure
- [ ] Documentation updated
- [ ] Performance considerations addressed
- [ ] Pre-commit hooks pass
- [ ] Code follows style guidelines
- [ ] Error handling is comprehensive

## 🚧 Work in Progress
- Always check the latest `CHANGELOG.md`
- Consult team lead for major architectural changes
- Keep dependencies up to date
- Regularly update pre-commit hooks and linting tools

## 💡 Agent-Specific Notes
- Use type hints and runtime type validation
- Prefer immutable data structures
- Log all significant actions
- Handle potential errors gracefully
- Validate all inputs before processing

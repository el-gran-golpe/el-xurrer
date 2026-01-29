# Repository Agentic Development Guidelines

## 🚀 Project Overview
- **Framework**: FastAPI
- **Language**: Python 3.11+
- **Primary Purpose**: Fanvue OAuth Integration

## 🛠️ Development Setup

### Prerequisites
- Python 3.11+
- pip
- virtualenv (recommended)

### Dependency Management
```bash
# Install dependencies
pip install -r requirements.txt

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Unix/macOS
# OR venv\Scripts\activate  # On Windows
```

## 🧪 Testing

### Running Tests
```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run tests for a specific module
pytest tests/test_oauth.py

# Run a single test
pytest tests/test_oauth.py::test_pkce_generation

# Run tests with coverage
pytest --cov=app tests/

# Run tests matching a pattern
pytest -k "login or callback"
```

### Test Writing Guidelines
- Use `pytest` framework
- Leverage `pytest-asyncio` for async tests
- Place tests in `tests/` directory
- Name test files `test_*.py`
- Use descriptive test function names
- Include both positive and negative test scenarios
- Mock external API calls

## 📝 Code Style & Conventions

### General Principles
- Follow PEP 8 guidelines
- Use type hints consistently
- Prioritize readability over cleverness
- Keep functions small and focused (max 20 lines)
- Use meaningful variable and function names

### Import Conventions
```python
# Standard library imports first
import os
import sys

# Third-party imports next
from typing import Dict, List
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

```python
from typing import Optional, Union, Dict

def example_function(
    param1: str,
    param2: Optional[int] = None,
    param3: Union[str, int] = ""
) -> Dict[str, Any]:
    ...
```

### Error Handling
- Use specific exceptions
- Provide context in error messages
- Log errors with sufficient detail
- Use FastAPI's `HTTPException` for API errors

```python
from fastapi import HTTPException, status

def validate_token(token: str) -> None:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
```

### Logging
- Use `logging` module
- Configure log levels
- Include contextual information

```python
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def process_request(data: Dict):
    try:
        # Processing logic
        logger.info(f"Processing request: {data}")
    except Exception as e:
        logger.error(f"Error processing request: {e}", exc_info=True)
```

### Configuration Management
- Use Pydantic Settings for environment configuration
- Validate all environment variables
- Provide sensible defaults
- Never commit secrets to version control

## 🚦 Continuous Integration
- Automate testing and linting
- Use `flake8` or `pylint` for static code analysis
- Configure pre-commit hooks

## 🔒 Security Considerations
- Never log sensitive information
- Use environment variables for secrets
- Implement proper input validation
- Follow OAuth 2.0 security best practices
- Use HTTPS for all external communications

## 📦 Deployment Recommendations
- Use Docker for consistent environments
- Implement health check endpoints
- Configure proper CORS settings
- Use environment-specific configurations

## 🤝 Collaboration
- Write clear, concise commit messages
- Create descriptive pull request descriptions
- Include tests with new features
- Document complex logic and algorithms

## 🚧 Work in Progress
- Always check the latest `CHANGELOG.md`
- Consult team lead for major architectural changes

## 📋 Code Review Checklist
- [ ] Tests pass
- [ ] Type hints are correct
- [ ] No sensitive data exposure
- [ ] Documentation updated
- [ ] Performance considerations addressed

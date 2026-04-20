# API Tests

This directory contains tests for the SaaS API, including unit tests and integration tests for the RBAC user groups system.

## Structure

```
tests/
├── test_group/
│   ├── test_group_service.py       # Unit tests for UserGroupService
│   └── test_rbac_middleware.py     # Integration tests for RBACMiddleware
└── README.md
```

## Running Tests

### Prerequisites

Install test dependencies:

```bash
pip install pytest pytest-asyncio pytest-cov
```

### Run All Tests

```bash
# From the project root
pytest template/apps/api/tests/

# With coverage
pytest template/apps/api/tests/ --cov=apps.api.api --cov-report=html
```

### Run Specific Test Files

```bash
# Run only group service tests
pytest template/apps/api/tests/test_group/test_group_service.py

# Run only RBAC middleware tests
pytest template/apps/api/tests/test_group/test_rbac_middleware.py
```

### Run Specific Test Classes

```bash
# Run tests for creating groups
pytest template/apps/api/tests/test_group/test_group_service.py::TestCreateGroup

# Run tests for feature access hierarchy
pytest template/apps/api/tests/test_group/test_rbac_middleware.py::TestFeatureAccessHierarchy
```

### Run with Verbose Output

```bash
pytest template/apps/api/tests/ -v
```

## Test Coverage

### UserGroupService Tests

- ✅ Create group (success, duplicate name)
- ✅ Get group (success, not found)
- ✅ Update group (success)
- ✅ Add member (success, inactive group)
- ✅ Assign feature (success)
- ✅ Check user feature via groups (has access, no access)

### RBACMiddleware Tests

- ✅ No feature required (pass through)
- ✅ Missing user ID (401)
- ✅ Feature access hierarchy:
  - Priority 1: user_grants
  - Priority 2: user_group_features
  - Priority 3: plan_features
  - Priority 4: default_value
- ✅ Access denied scenarios
- ✅ Expired grants
- ✅ Quota and config values

## Test Best Practices

1. **Mocking**: Tests use mocked dependencies (SupabaseManager, LoggingController) to isolate functionality
2. **Fixtures**: Reusable fixtures for common test data (user IDs, group IDs, etc.)
3. **Async Tests**: Tests use `pytest.mark.asyncio` for async function testing
4. **Assertions**: Clear assertions with descriptive error messages
5. **Coverage**: Tests cover success paths, error paths, and edge cases

## Adding New Tests

When adding new tests:

1. Create appropriate test fixtures for dependencies
2. Use descriptive test names that explain what is being tested
3. Follow the Arrange-Act-Assert pattern
4. Mock external dependencies (database, external services)
5. Test both success and failure scenarios
6. Add docstrings to test classes and methods

## Continuous Integration

These tests should be run in CI/CD pipelines before deployment to ensure code quality and prevent regressions.

Example CI configuration:

```yaml
test:
  script:
    - pip install -r requirements.txt
    - pip install pytest pytest-asyncio pytest-cov
    - pytest template/apps/api/tests/ --cov=apps.api.api --cov-report=xml
  coverage: '/TOTAL.*\s+(\d+%)$/'
```

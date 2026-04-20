# 📝 Log Manager - The System's Memory Keeper

## What is this?
This is the **central nervous system** for recording everything that happens in our application. Think of it as a very detailed security camera system combined with a smart diary that not only records what happened, but also organizes it, analyzes it, and can even send alerts when something important occurs.

## 🏗️ What's Inside?

### 📋 System Components

### 📁 Core Files


### 📁 Core Files

#### `controller.py` - The Main Control Center 🎛️
**What it does**: The primary interface that all other parts of the system use for logging
- **Purpose**: Provides a simple, consistent way to log messages across the entire application
- **Features**: Correlation tracking, Teams notifications, context management
- **Real-world analogy**: Like a central dispatch operator who handles all communication

#### `__init__.py` - The Package Entry Point 📦
**What it does**: Makes the logging system available as a Python package
- **Purpose**: Allows other parts of the system to import and use the logger
- **Example**: `from app.commons.log_manager import LoggingController`

### 📁 Subfolders

#### `core/` - The Engine Room ⚙️
Contains the fundamental logging mechanisms and utilities:
- **Purpose**: Low-level logging functionality and utilities
- **Components**: Core logging classes, formatters, correlation ID management
- **Real-world analogy**: Like the engine of a car - you don't see it, but it makes everything work

#### `loki/` - The Cloud Logger 🌩️
Integration with Loki logging system for centralized log storage:
- **Purpose**: Send logs to external logging service for analysis and storage
- **Benefits**: Centralized monitoring, log aggregation, advanced search
- **Real-world analogy**: Like backing up your important documents to the cloud

## 🎯 What Does It Do?

### For the System:
- **Centralized Logging** - All services use the same logging format and standards
- **Correlation Tracking** - Every related action gets the same tracking ID
- **Alert Management** - Important events trigger notifications
- **Performance Monitoring** - Track how long operations take
- **Error Detection** - Catch and report problems before they become critical

### For Developers:
- **Easy Integration** - Simple API to add logging to any component
- **Consistent Format** - All logs look the same, making debugging easier
- **Rich Context** - Include relevant information with every log entry
- **Multiple Outputs** - Logs can go to console, files, Teams, and external services

### For Operations:
- **Real-time Monitoring** - See what's happening as it happens
- **Historical Analysis** - Review past events to understand patterns
- **Troubleshooting** - Quickly find the cause of problems
- **Compliance** - Keep audit trails for business requirements

## 🚀 How to Use It

### Basic Logging
```python
from app.commons.log_manager.controller import LoggingController

# Create a logger for your service
logger = LoggingController(
    app_name="my_business_service",
    use_teams_webhook=True,
    teams_webhook_url="https://your-teams-webhook-url"
)

# Log different types of messages
logger.log_info("Service started successfully")
logger.log_warning("Disk space is getting low")
logger.log_error("Failed to connect to database")
logger.log_debug("Processing user request - step 1 completed")
```

### Logging with Context
```python
# Include relevant business information
logger.log_info("Client invoice processed", {
    "client_shortname": "ATONRA",
    "client_id": 123500,
    "invoice_number": "INV-2024-001",
    "amount": 1500.00,
    "currency": "EUR"
})

# Log user actions
logger.log_info("User uploaded document", {
    "user_id": "user123",
    "client_shortname": "ATONRA",
    "document_type": "contract",
    "file_size_mb": 2.5
})
```

### Correlation Tracking
```python
# Track related operations together
with logger.correlation_scope():
    logger.log_info("Starting monthly report generation")
    
    # All logs within this scope get the same correlation ID
    logger.log_info("Fetching financial data")
    financial_data = get_financial_data()
    
    logger.log_info("Generating charts")
    create_charts(financial_data)
    
    logger.log_info("Report generation completed")

# You can also use a specific correlation ID
with logger.correlation_scope("custom-operation-123"):
    logger.log_info("Processing custom operation")
```

### Error Handling
```python
try:
    # Some risky operation
    process_client_data(client_shortname="ATONRA")
    logger.log_info("Client data processed successfully")
    
except Exception as e:
    # Automatically logs the full exception with stack trace
    logger.log_exception(e, {
        "client_shortname": "ATONRA",
        "operation": "process_client_data",
        "additional_context": "This happened during monthly processing"
    })
```

## 📊 Log Levels Explained

### `DEBUG` - Detailed Information 🔍
- **When to use**: Detailed step-by-step information for troubleshooting
- **Examples**: "Connecting to database", "Parsing configuration file"
- **Visibility**: Usually only shown in development environments

### `INFO` - Normal Operations ℹ️
- **When to use**: Normal business operations and status updates
- **Examples**: "User logged in", "Report generated", "File uploaded"
- **Visibility**: Always visible, helps understand what the system is doing

### `WARNING` - Attention Needed ⚠️
- **When to use**: Something unusual happened, but not an error
- **Examples**: "Disk space low", "API response slower than usual"
- **Visibility**: Always visible, may trigger monitoring alerts

### `ERROR` - Problems Occurred ❌
- **When to use**: Something went wrong that needs to be fixed
- **Examples**: "Database connection failed", "File not found"
- **Visibility**: Always visible, usually triggers immediate alerts

## 🔄 Correlation IDs

### What are they?
Unique identifiers that connect related log entries across the entire system:

```
Format: 20240101_120030_api_abc123def456
        ┃        ┃      ┃   ┃
        ┃        ┃      ┃   └── Random identifier
        ┃        ┃      └────── Service/component name
        ┃        └───────────── Time (HHMMSS)
        └────────────────────── Date (YYYYMMDD)
```

### Why they're important:
- **Trace requests** - Follow a single user request through all services
- **Debug issues** - Find all related log entries for a problem
- **Performance analysis** - See how long complete operations take
- **Business tracking** - Monitor specific client operations

### Example correlation tracking:
```
20240101_120030_api_abc123def456 [INFO] User request received: GET /clients/ATONRA/invoices
20240101_120030_api_abc123def456 [INFO] Fetching client data from database
20240101_120030_api_abc123def456 [INFO] Connecting to Business Central API
20240101_120030_api_abc123def456 [INFO] Retrieved 15 invoices for client ATONRA
20240101_120030_api_abc123def456 [INFO] Request completed in 456ms
```

## 🔧 Configuration

### Environment Variables
```bash
# Basic logging configuration
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json             # json, text
LOG_OUTPUT=console,file     # console, file, loki

# Teams integration
TEAMS_WEBHOOK_URL=https://your-teams-webhook-url
TEAMS_NOTIFICATIONS_ENABLED=true

# Loki integration (if using external logging)
LOKI_ENDPOINT=http://localhost:3100
LOKI_USERNAME=admin
LOKI_PASSWORD=admin

# Correlation ID settings
CORRELATION_ID_LENGTH=12    # Length of random part
```

### Customizing the Logger
```python
# Custom configuration for specific services
logger = LoggingController(
    app_name="financial_processor",
    log_level="DEBUG",
    use_teams_webhook=True,
    teams_webhook_url=os.environ.get("TEAMS_WEBHOOK_URL"),
    include_stack_trace=True,
    max_context_length=1000
)
```

## 📢 Teams Notifications

### When notifications are sent:
- **ERROR level** messages always trigger notifications
- **WARNING level** messages for critical services
- **Custom alerts** when specific conditions are met

### Notification format:
```json
{
  "title": "⚠️ System Alert",
  "text": "Database connection failed",
  "color": "attention",
  "sections": [{
    "facts": [
      {"name": "Service", "value": "financial_processor"},
      {"name": "Client", "value": "ATONRA"},
      {"name": "Correlation ID", "value": "20240101_120030_api_abc123def456"},
      {"name": "Time", "value": "2024-01-01 12:00:30"}
    ]
  }]
}
```

## 🚨 Troubleshooting

### Logs not appearing:
```python
# Check log level
logger.set_log_level("DEBUG")  # Make sure you're seeing all logs

# Verify configuration
logger.log_info("Test message")  # Should appear in console/file
```

### Teams notifications not working:
```python
# Test webhook URL
logger.test_teams_webhook()  # Sends a test message

# Check configuration
print(logger.teams_webhook_url)  # Should show your webhook URL
```

### Missing correlation IDs:
```python
# Always use correlation scope for related operations
with logger.correlation_scope():
    # Your operations here
    pass

# Or get the current correlation ID
correlation_id = logger.get_correlation_id()
```

### Performance issues:
```python
# Use async logging for high-volume scenarios
logger.enable_async_logging()

# Reduce context size
logger.log_info("Message", {"key": "value"})  # Keep context small
```

## 📁 File Structure
```
log_manager/
├── controller.py       # Main LoggingController class
├── core/              # Core logging functionality
│   ├── correlation.py # Correlation ID management
│   ├── formatters.py  # Log format definitions
│   └── utils.py       # Utility functions
├── loki/              # Loki integration
│   ├── client.py      # Loki client
│   └── config.py      # Loki configuration
└── __init__.py        # Package initialization
```

## 🤝 Integration Examples

### With API requests:
```python
# In a router
@app.get("/clients/{client_shortname}/invoices")
async def get_invoices(client_shortname: str, request: Request):
    # Use the correlation ID from the request middleware
    correlation_id = request.state.correlation_id
    
    with logger.correlation_scope(correlation_id):
        logger.log_info(f"Fetching invoices for client {client_shortname}")
        # Your business logic here
```

### With background workers:
```python
# In a job worker
def process_monthly_report(client_shortname: str):
    with logger.correlation_scope():
        logger.log_info("Starting monthly report", {
            "client_shortname": client_shortname,
            "report_type": "monthly_financial"
        })
        
        # Process the report
        # All related logs will have the same correlation ID
```

This logging system is your best friend for understanding what's happening in your application and quickly solving problems when they occur!

## 🔄 Log Manager Processing

### Sequence Diagram - Log Handler Initialization & Setup


### Sequence Diagram - Error Notification Flow


### 📋 System Components

// ... existing code ... 
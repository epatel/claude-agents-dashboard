# Token Usage Tracking Implementation

## Overview
Added comprehensive token usage tracking to the Agents Dashboard to provide detailed insights into Claude API consumption alongside cost tracking.

## Changes Made

### 1. Backend - AgentResult Enhancement
- **File**: `src/agent/session.py`
- **Changes**: Added token fields to `AgentResult` dataclass:
  - `input_tokens: int | None`
  - `output_tokens: int | None`
  - `total_tokens: int | None`
- Enhanced ResultMessage processing to extract token data from multiple possible field names

### 2. Database Schema
- **File**: `src/migrations/versions/005_add_token_usage.py`
- **Changes**: Created new `token_usage` table to track:
  - Token consumption per agent run
  - Input/output token breakdown
  - Cost correlation with token usage
  - Indexed for efficient querying

### 3. Data Persistence
- **File**: `src/agent/orchestrator.py`
- **Changes**:
  - Added `_save_token_usage()` method to store token data
  - Enhanced completion log messages to show both cost and tokens
  - Integrated token tracking into agent lifecycle

### 4. API Enhancement
- **File**: `src/web/routes.py`
- **Changes**: Updated `/api/stats` endpoint to return:
  - `total_tokens`: Aggregate token usage
  - `input_tokens`: Total input tokens consumed
  - `output_tokens`: Total output tokens generated
  - Graceful fallback to work log parsing for cost when token table is empty

### 5. Frontend Display
- **Files**: `src/templates/base.html`, `src/static/js/stats.js`
- **Changes**:
  - Added "Tokens" stat to top navigation bar
  - Formatted token display with K/M abbreviations
  - Enhanced tooltips showing input/output breakdown
  - Real-time updates via existing stats polling

### 6. Models
- **File**: `src/models.py`
- **Changes**: Added `TokenUsage` Pydantic model for type safety

## Features

### Real-time Token Display
- Live token count in top navigation bar
- Formatted display (e.g., "1.2K", "5.7M")
- Detailed tooltips showing input vs output breakdown

### Comprehensive Tracking
- Per-session token usage storage
- Historical token consumption analysis
- Correlation with cost data
- Support for partial token data scenarios

### Enhanced Logging
- Agent completion messages now show both cost and token info
- Format: "Agent completed (cost: $0.0384, tokens: 2,000)"
- Backward compatible with existing cost-only tracking

### Robust Implementation
- Graceful handling of missing token fields
- Fallback to existing cost parsing
- Multiple field name detection for SDK compatibility
- Database indexes for performance

## API Response Format

```json
{
  "usage": {
    "total_cost_usd": 1.2345,
    "total_tokens": 25000,
    "input_tokens": 15000,
    "output_tokens": 10000,
    "total_messages": 156,
    "tool_calls": 234,
    "completed_today": 5
  }
}
```

## Migration Required

To activate token tracking, run:
```bash
python3 src/manage.py migrate
```

This creates the `token_usage` table and indexes.

## Testing

Use `test_token_tracking.py` to validate the implementation:
```bash
python3 test_token_tracking.py
```

## Backward Compatibility

- Existing cost tracking unchanged
- Stats API gracefully handles missing token data
- Frontend displays "0" tokens when no data available
- Work log parsing maintains existing functionality

## Benefits

1. **Better Cost Analysis**: Understand token efficiency (cost per token)
2. **Usage Optimization**: Identify high-consumption patterns
3. **Resource Planning**: Track token trends over time
4. **Debugging**: Correlate agent performance with token usage
5. **Transparency**: Clear visibility into API consumption
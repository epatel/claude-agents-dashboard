# Fix for "Tokens still read 0" Issue

## Problem
The token counter in the dashboard shows 0 because the database hasn't been initialized with the token tracking table.

## Solution
Run the fix script to initialize the database:

```bash
python3 fix_tokens.py
```

## What this does:
1. Creates the `agents-lab` directory if missing
2. Initializes the database with all migrations including the token_usage table
3. Verifies the token tracking setup is ready

## After running the fix:
1. Start the dashboard: `./run.sh`
2. Run some agents to generate token usage data
3. The token counter should now update properly

## How token tracking works:
- Tokens are tracked per agent session and stored in the `token_usage` table
- The `/api/stats` endpoint aggregates token data from the database
- The frontend polls this endpoint every 10 seconds to update the display
- Token counts include input/output breakdown with detailed tooltips

## Verification:
After running agents, you should see:
- Total token count in the top navigation bar
- Formatted display (e.g., "1.2K", "5.7M" for large numbers)
- Detailed tooltips showing input vs output token breakdown
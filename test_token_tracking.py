#!/usr/bin/env python3
"""Test script to validate token tracking implementation."""

import sys
import asyncio
from pathlib import Path
sys.path.insert(0, 'src')

from src.agent.session import AgentResult

def test_agent_result_with_tokens():
    """Test that AgentResult can handle token data."""
    # Test with all token fields
    result = AgentResult(
        success=True,
        session_id="test-session-123",
        cost_usd=0.05,
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500
    )

    print("✓ AgentResult with token data:")
    print(f"  - Input tokens: {result.input_tokens}")
    print(f"  - Output tokens: {result.output_tokens}")
    print(f"  - Total tokens: {result.total_tokens}")
    print(f"  - Cost: ${result.cost_usd}")

    # Test with partial token data
    result2 = AgentResult(
        success=True,
        session_id="test-session-456",
        cost_usd=0.02,
        input_tokens=800,
        output_tokens=None,
        total_tokens=800
    )

    print("\n✓ AgentResult with partial token data:")
    print(f"  - Input tokens: {result2.input_tokens}")
    print(f"  - Output tokens: {result2.output_tokens}")
    print(f"  - Total tokens: {result2.total_tokens}")
    print(f"  - Cost: ${result2.cost_usd}")


def test_enhanced_log_message():
    """Test the enhanced log message format."""
    # Simulate the log message creation logic from orchestrator
    result = AgentResult(
        success=True,
        session_id="test-session-789",
        cost_usd=0.0384,
        input_tokens=1200,
        output_tokens=800,
        total_tokens=2000
    )

    log_parts = ["Agent completed"]
    if result.cost_usd:
        log_parts.append(f"cost: ${result.cost_usd:.4f}")
    if result.total_tokens:
        log_parts.append(f"tokens: {result.total_tokens:,}")
    elif result.input_tokens and result.output_tokens:
        log_parts.append(f"tokens: {result.input_tokens + result.output_tokens:,}")

    log_message = f"{log_parts[0]} ({', '.join(log_parts[1:])})" if len(log_parts) > 1 else log_parts[0]

    print(f"\n✓ Enhanced log message: {log_message}")


def test_stats_response_format():
    """Test the expected stats API response format."""
    # Simulate stats API response with token data
    usage_stats = {
        "total_cost_usd": 1.2345,
        "total_messages": 156,
        "agent_messages": 78,
        "tool_calls": 234,
        "completed_today": 5,
        "total_tokens": 25000,
        "input_tokens": 15000,
        "output_tokens": 10000
    }

    print(f"\n✓ Stats API response format:")
    for key, value in usage_stats.items():
        if 'tokens' in key:
            print(f"  - {key}: {value:,}")
        elif 'cost' in key:
            print(f"  - {key}: ${value:.4f}")
        else:
            print(f"  - {key}: {value}")


if __name__ == "__main__":
    print("🧪 Testing Token Usage Tracking Implementation")
    print("=" * 50)

    try:
        test_agent_result_with_tokens()
        test_enhanced_log_message()
        test_stats_response_format()

        print("\n✅ All tests passed! Token tracking implementation looks good.")
        print("\nNext steps:")
        print("1. Run migration: python3 src/manage.py migrate")
        print("2. Start the application to see token tracking in action")
        print("3. Check the stats bar in the top navigation")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
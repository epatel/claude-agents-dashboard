"""Board statistics with a short-lived cache, shared by the routes that change items."""

import time


# Simple cache for stats to avoid frequent DB queries
_stats_cache = {"data": None, "timestamp": 0, "ttl": 30}  # 30 second TTL


# One roundtrip for token totals and work-log aggregates (CTEs). The
# fallback cost parses "Agent completed (cost: $X)" log lines for runs that
# predate the token_usage table.
_STATS_SUMMARY_SQL = """
    WITH token_stats AS (
        SELECT
            COALESCE(SUM(cost_usd), 0) as total_cost,
            COALESCE(SUM(input_tokens), 0) as total_input_tokens,
            COALESCE(SUM(output_tokens), 0) as total_output_tokens,
            COALESCE(SUM(total_tokens), 0) as total_tokens
        FROM token_usage
    ),
    work_log_stats AS (
        SELECT
            entry_type,
            COUNT(*) as count,
            -- Count completed today
            SUM(CASE
                WHEN entry_type = 'system'
                AND content LIKE 'Agent completed%'
                AND DATE(timestamp) = DATE('now')
                THEN 1 ELSE 0
            END) as completed_today,
            -- Fallback cost calculation from work log
            SUM(CASE
                WHEN entry_type = 'system' AND content LIKE 'Agent completed (cost: $%' THEN
                    CAST(
                        SUBSTR(
                            SUBSTR(content, INSTR(content, '$') + 1),
                            1,
                            INSTR(SUBSTR(content, INSTR(content, '$') + 1), ')') - 1
                        ) AS REAL
                    )
                ELSE 0
            END) as fallback_cost
        FROM work_log
        GROUP BY entry_type
    ),
    item_stats AS (
        SELECT
            column_name,
            COUNT(*) as count
        FROM items
        WHERE column_name != 'archive'
        GROUP BY column_name
    )
    SELECT
        -- Token stats
        ts.total_cost,
        ts.total_input_tokens,
        ts.total_output_tokens,
        ts.total_tokens,
        -- Work log aggregates
        SUM(wls.fallback_cost) as fallback_total_cost,
        MAX(wls.completed_today) as completed_today,
        SUM(wls.count) as total_messages,
        SUM(CASE WHEN wls.entry_type = 'agent_message' THEN wls.count ELSE 0 END) as agent_messages,
        SUM(CASE WHEN wls.entry_type = 'tool_use' THEN wls.count ELSE 0 END) as tool_calls
    FROM token_stats ts
    CROSS JOIN work_log_stats wls
"""


async def _get_optimized_stats(db, orchestrator):
    """Get stats using optimized combined queries and caching."""
    current_time = time.time()
    cached = _cached_stats(orchestrator, current_time)
    if cached is not None:
        return cached

    async with db.connect() as conn:
        cursor = await conn.execute(_STATS_SUMMARY_SQL)
        main_row = await cursor.fetchone()

        # Get message counts breakdown
        cursor = await conn.execute("""
            SELECT entry_type, COUNT(*) as count
            FROM work_log
            GROUP BY entry_type
        """)
        message_counts = {row[0]: row[1] for row in await cursor.fetchall()}

        # Get item counts by status
        cursor = await conn.execute("""
            SELECT column_name, COUNT(*) as count
            FROM items
            WHERE column_name != 'archive'
            GROUP BY column_name
        """)
        item_counts = {row[0]: row[1] for row in await cursor.fetchall()}

        # Get recent activity (this changes frequently, so we query it separately)
        cursor = await conn.execute("""
            SELECT entry_type, content, timestamp
            FROM work_log
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        recent_activity = [
            {
                "type": row[0],
                "content": row[1][:100] + "..." if len(row[1]) > 100 else row[1],
                "timestamp": row[2]
            }
            for row in await cursor.fetchall()
        ]

    stats_data = {
        "usage": _usage_stats(main_row, message_counts),
        "activity": {
            "active_agents": len(orchestrator.sessions),
            "items_by_status": item_counts,
            "recent": recent_activity
        },
        "breakdown": message_counts
    }

    # Cache the result
    _stats_cache["data"] = stats_data
    _stats_cache["timestamp"] = current_time
    return stats_data


def _cached_stats(orchestrator, now: float):
    """The cached stats if still fresh (with a live active-agent count), else None."""
    data = _stats_cache["data"]
    if data is None or now - _stats_cache["timestamp"] >= _stats_cache["ttl"]:
        return None
    # Update active agents count (changes frequently)
    data["activity"]["active_agents"] = len(orchestrator.sessions)
    return data


def _usage_stats(main_row, message_counts: dict) -> dict:
    """The "usage" block: token_usage totals when present, else the work-log fallback cost."""
    has_token_usage = bool(main_row) and (main_row[0] or 0) > 0
    if has_token_usage:
        total_cost_usd, total_input_tokens, total_output_tokens, total_tokens = main_row[0:4]
    else:
        total_cost_usd = main_row[4] if main_row else 0.0  # fallback_total_cost
        total_input_tokens = total_output_tokens = total_tokens = 0
    if not main_row:
        counts = (sum(message_counts.values()), message_counts.get('agent_message', 0),
                  message_counts.get('tool_use', 0), 0)
    else:
        counts = (main_row[6], main_row[7], main_row[8], main_row[5])
    total_messages, agent_messages, tool_calls, completed_today = counts
    return {
        "total_cost_usd": round(total_cost_usd or 0.0, 4),
        "total_messages": total_messages,
        "agent_messages": agent_messages,
        "tool_calls": tool_calls,
        "completed_today": completed_today,
        "total_tokens": total_tokens,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens
    }


def _invalidate_stats_cache():
    """Invalidate the stats cache when data changes."""
    _stats_cache["data"] = None
    _stats_cache["timestamp"] = 0

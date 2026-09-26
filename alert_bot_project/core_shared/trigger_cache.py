"""Atomic Redis updates for the custom trigger dictionary."""

from redis.asyncio import Redis

UPDATE_TRIGGER_LUA = """
local changed = redis.call(ARGV[1], KEYS[1], ARGV[2])
if changed == 1 then redis.call('INCR', KEYS[2]) end
return changed
"""

RECONCILE_TRIGGERS_LUA = """
if (redis.call('GET', KEYS[2]) or '') ~= ARGV[1] then return -1 end
local current = redis.call('SMEMBERS', KEYS[1])
local same = #current == #ARGV - 1
if same then
    local wanted = {}
    for i = 2, #ARGV do wanted[ARGV[i]] = true end
    for _, phrase in ipairs(current) do
        if not wanted[phrase] then same = false; break end
    end
end
if same then return 0 end
redis.call('DEL', KEYS[1])
for i = 2, #ARGV do redis.call('SADD', KEYS[1], ARGV[i]) end
redis.call('INCR', KEYS[2])
return 1
"""


async def update_custom_trigger_cache(redis_client: Redis, phrase: str, *, add: bool) -> bool:
    script = redis_client.register_script(UPDATE_TRIGGER_LUA)
    result = await script(
        keys=["global_custom_triggers", "global_custom_triggers:version"],
        args=["SADD" if add else "SREM", phrase],
    )
    return bool(result)


async def reconcile_custom_trigger_cache(redis_client: Redis, phrases: set[str], expected_version: str | None) -> int:
    script = redis_client.register_script(RECONCILE_TRIGGERS_LUA)
    return int(
        await script(
            keys=["global_custom_triggers", "global_custom_triggers:version"],
            args=[expected_version or "", *sorted(phrases)],
        )
    )

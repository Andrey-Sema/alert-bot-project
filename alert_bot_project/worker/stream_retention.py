"""Atomically trim only entries passed and acknowledged by every group."""

from redis.asyncio import Redis

TRIM_ACKNOWLEDGED_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
local groups = redis.call('XINFO', 'GROUPS', KEYS[1])
if #groups == 0 then return 0 end
local floor = nil
for _, group in ipairs(groups) do
    local name = nil
    local delivered = nil
    for i = 1, #group, 2 do
        if group[i] == 'name' then name = group[i + 1] end
        if group[i] == 'last-delivered-id' then delivered = group[i + 1] end
    end
    local pending = redis.call('XPENDING', KEYS[1], name)
    local candidate = pending[1] > 0 and pending[2] or delivered
    if not candidate or candidate == '0-0' then return 0 end
    local ms, seq = string.match(candidate, '^(%d+)%-(%d+)$')
    if not ms then return 0 end
    if not floor then
        floor = candidate
    else
        local fms, fseq = string.match(floor, '^(%d+)%-(%d+)$')
        if tonumber(ms) < tonumber(fms) or
           (ms == fms and tonumber(seq) < tonumber(fseq)) then
            floor = candidate
        end
    end
end
return redis.call('XTRIM', KEYS[1], 'MINID', '=', floor)
"""


async def trim_acknowledged_stream(redis_client: Redis, stream_name: str) -> int:
    script = redis_client.register_script(TRIM_ACKNOWLEDGED_LUA)
    return int(await script(keys=[stream_name]))

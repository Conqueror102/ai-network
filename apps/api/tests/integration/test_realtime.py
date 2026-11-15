import asyncio
import json

from app.core import clock, jobs, outbox
from app.core.redis import get_redis
from app.modules.realtime import service
from app.modules.realtime.public import is_online, publish_user, user_channel
from app.modules.realtime.router import channels_for
from tests.helpers import join, make_event, sign_up


class Socket:
    """Stands in for a WebSocket: collects what the server sends, feeds client frames."""

    def __init__(self):
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue[str] = asyncio.Queue()

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def receive_text(self) -> str:
        return await self.inbox.get()


async def _wait(cond, timeout=2.0):  # noqa: ASYNC109
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("timed out")


async def test_ticket_is_single_use_and_short_lived(client):
    u = await sign_up(client)
    r = await client.post("/v1/ws/ticket", headers=u["headers"])
    assert r.status_code == 200 and r.json()["ttl_s"] == 30
    ticket = r.json()["ticket"]
    user_id, exp = await service.redeem_ticket(ticket)
    assert user_id == u["id"] and exp > clock.now().timestamp()
    assert await service.redeem_ticket(ticket) is None
    assert await service.redeem_ticket("guess") is None
    assert (await client.post("/v1/ws/ticket")).status_code == 401


async def test_socket_receives_only_its_own_events_and_expires(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")

    # subscriptions: own channel + live events checked into; stats only for organizer staff
    mine = await channels_for(a["id"], eid)
    assert mine[0] == user_channel(a["id"]) and len(mine) == 2
    assert not any(c.endswith(":stats") for c in mine)
    assert any(c.endswith(":stats") for c in await channels_for(owner["id"], eid))

    sock = Socket()
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(*mine)
    # +2 because int() truncates: the socket must live at least one full second
    expires = int(clock.now().timestamp()) + 2
    task = asyncio.create_task(
        service.pump(
            pubsub,
            sock.send_text,
            sock.receive_text,
            user_id=a["id"],
            expires_at=expires,
            heartbeat_s=0.05,
        )
    )
    await asyncio.sleep(0.1)
    assert await is_online(a["id"]) and not await is_online(b["id"])
    await sock.inbox.put('{"type":"ping"}')
    await sock.inbox.put("not json")  # ignored, does not kill the socket
    await publish_user(b["id"], "message.new", {"secret": "for bayo"})
    await publish_user(a["id"], "wave.received", {"wave_id": "wav_1"})
    await _wait(lambda: any(m.get("type") == "wave.received" for m in sock.sent))
    assert {"type": "pong"} in sock.sent
    assert "for bayo" not in json.dumps(sock.sent)
    env = next(m for m in sock.sent if m.get("type") == "wave.received")
    assert env["id"].startswith("evt_") and env["payload"] == {"wave_id": "wav_1"}
    # the socket closes when the token it was opened with would have expired
    assert await asyncio.wait_for(task, 3) == service.CLOSE_EXPIRED
    await pubsub.aclose()


async def test_domain_events_reach_the_socket(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()
    seen: dict[str, list[dict]] = {a["id"]: [], b["id"]: []}
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(user_channel(a["id"]), user_channel(b["id"]))

    async def listen():
        async for m in pubsub.listen():
            if m["type"] == "message":
                uid = m["channel"].rsplit(":", 1)[-1]
                seen[uid].append(json.loads(m["data"]))

    task = asyncio.create_task(listen())
    await asyncio.sleep(0.05)
    wid = (
        await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": b["id"], "source": "directory"},
            headers=a["headers"],
        )
    ).json()["id"]
    await outbox.drain()
    await _wait(lambda: seen[b["id"]])
    # the recipient learns a wave arrived, not who sent it
    assert seen[b["id"]][0]["type"] == "wave.received"
    assert a["id"] not in json.dumps(seen[b["id"]][0]) and seen[a["id"]] == []

    cid = (
        await client.post(
            f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=b["headers"]
        )
    ).json()["conversation_id"]
    await outbox.drain()
    await _wait(lambda: any(m["type"] == "wave.accepted" for m in seen[a["id"]]))
    await client.post(
        f"/v1/conversations/{cid}/messages", json={"body": "hello"}, headers=b["headers"]
    )
    await _wait(lambda: any(m["type"] == "message.new" for m in seen[a["id"]]))
    msg = next(m for m in seen[a["id"]] if m["type"] == "message.new")
    assert msg["payload"]["body"] == "hello" and "ai_assisted" not in msg["payload"]
    assert not any(m["type"] == "message.new" for m in seen[b["id"]])
    task.cancel()
    await pubsub.aclose()

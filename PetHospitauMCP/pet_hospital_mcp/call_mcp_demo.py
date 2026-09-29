"""Demo: call the list_pets tool through the MCP /mcp endpoint (in-process)."""
import asyncio
import json
import httpx
from pet_hospital_mcp import MCP_HTTP_PATH, MCP_PROTOCOL_VERSION
from pet_hospital_mcp.server import create_app

async def call_list_pets(species: str | None = None):
    app = create_app()
    async with app.mcp.session_manager.run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
            # 1) /health
            h = await client.get("/health")
            print("== /health ==")
            print(json.dumps(h.json(), indent=2, ensure_ascii=False))

            # 2) server/discover (replaces old initialize)
            meta = {
                "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "demo", "version": "0.0"},
            }
            def req(method, params=None, name=None, rid=1):
                p = {"_meta": meta}
                if name: p["name"] = name
                if params: p.update(params)
                hdrs = {
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                    "Mcp-Method": method,
                }
                if name: hdrs["Mcp-Name"] = name
                return {"jsonrpc": "2.0", "id": rid, "method": method, "params": p}, hdrs

            print("\n== server/discover ==")
            b, hh = req("server/discover")
            r = await client.post(MCP_HTTP_PATH, headers=hh, json=b)
            print(f"  status={r.status_code}  mcp-session-id={r.headers.get('mcp-session-id', '<absent>')}")

            print("\n== tools/list ==")
            b, hh = req("tools/list", rid=2)
            r = await client.post(MCP_HTTP_PATH, headers=hh, json=b)
            tools = json.loads(r.text)["result"]["tools"]
            print(f"  tools: {[t['name'] for t in tools]}")

            print("\n== tools/call list_pets (species=犬) ==")
            args = {"params": {"page": 1, "pageSize": 1}}
            if species:
                args["params"]["species"] = species
            b, hh = req("tools/call", params={"arguments": args}, name="list_pets", rid=3)
            r = await client.post(MCP_HTTP_PATH, headers=hh, json=b)
            result = json.loads(r.text)["result"]
            print(f"  isError: {result.get('isError')}")
            text = "".join(c.get("text", "") for c in result.get("content", []))
            print(f"  content: {text[:800]}")

asyncio.run(call_list_pets("犬"))

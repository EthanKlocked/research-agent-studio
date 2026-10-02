"""Offline HTTP upstream for the isolated Compose test network only."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
STATE = {"scenario": "normal", "attempts": []}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data):
        encoded = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        with LOCK:
            self.reply(200, dict(STATE))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/control":
            with LOCK:
                STATE.update(scenario=body["scenario"], attempts=[])
            return self.reply(200, {"ok": True})
        model = body["model"]
        with LOCK:
            scenario = STATE["scenario"]
            STATE["attempts"].append({"model": model, "auth_ok": self.headers.get("Authorization") == "Bearer offline-upstream-only"})
        if self.headers.get("Authorization") != "Bearer offline-upstream-only":
            return self.reply(401, {"error": {"message": "mock auth", "type": "authentication_error"}})
        if model == "mock-primary" and scenario.startswith("fail-"):
            status = int(scenario.split("-")[1])
            return self.reply(status, {"error": {"message": "mock failure private-marker", "type": "server_error"}})
        if scenario == "slow" or (scenario == "slow-primary" and model == "mock-primary"):
            time.sleep(12)
        if scenario == "fallback-slow":
            if model == "mock-primary":
                return self.reply(503, {"error": {"message": "mock failure", "type": "server_error"}})
            time.sleep(12)
        messages = body["messages"]
        system = messages[0].get("content", "")
        value = {"interpreted_request": "offline mock", "scope": "in_scope"}
        message = None
        if "Produce up to" in system:
            value = {"plan": ["revenue"]}
        elif "Search documents" in system:
            tools = [m for m in messages if m["role"] == "tool"]
            if len(tools) == 0:
                name, args = "search_documents", {"query": "revenue", "limit": 1}
            elif len(tools) == 1:
                hit = json.loads(tools[0]["content"])[0]
                name, args = "get_section", {"document_id": hit["document_id"], "section_id": hit["section_id"]}
            else:
                name = None
            if name:
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": f"mock-call-{len(tools)}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
            value = {"summary": "offline retrieval complete"}
        elif "Write a concise" in system:
            state = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
            value = {"title": "Mock report", "summary": "Not live research", "claims": [{"text": "Mock claim", "citation_ids": [state["evidence"][0]["id"]]}], "limitations": ["Mock model responses"]}
        elif "Assess question" in system:
            value = {"decision": "pass", "issues": [], "follow_up": []}
        if message is None:
            message = {"role": "assistant", "content": json.dumps(value)}
        result = {"id": "mock-completion", "object": "chat.completion", "created": 0, "model": model, "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}]}
        if scenario != "no-usage":
            result["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        self.reply(200, result)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

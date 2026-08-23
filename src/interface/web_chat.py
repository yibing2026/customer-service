"""
最小网页聊天界面。

网页层只负责接收/展示消息，所有业务判断和动作执行仍由 AgentController 完成。
"""

import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core.agent_controller import AgentController


HTML_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI 客服 Agent Demo</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f3f6fb; color: #1f2937; }
    .shell { max-width: 820px; margin: 32px auto; padding: 0 16px; }
    .card { background: #fff; border: 1px solid #dbe3ef; border-radius: 16px; box-shadow: 0 8px 30px #20304d12; }
    header { padding: 22px 24px 16px; border-bottom: 1px solid #e8edf5; }
    h1 { margin: 0 0 6px; font-size: 22px; }
    .hint { color: #64748b; font-size: 13px; }
    #messages { min-height: 360px; max-height: 58vh; overflow-y: auto; padding: 20px; }
    .row { display: flex; margin: 10px 0; }
    .row.customer { justify-content: flex-end; }
    .bubble { max-width: 78%; padding: 11px 14px; border-radius: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .customer .bubble { background: #2563eb; color: white; border-bottom-right-radius: 4px; }
    .agent .bubble { background: #eef2f7; border-bottom-left-radius: 4px; }
    .meta { margin-top: 5px; font-size: 11px; color: #64748b; }
    .agent .meta { margin-left: 4px; }
    form { display: grid; grid-template-columns: 150px 1fr auto; gap: 10px; padding: 16px 20px 20px; border-top: 1px solid #e8edf5; }
    input, button { border: 1px solid #cbd5e1; border-radius: 9px; padding: 11px 12px; font: inherit; }
    input:focus { outline: 2px solid #93c5fd; border-color: #2563eb; }
    button { cursor: pointer; background: #2563eb; color: white; border-color: #2563eb; }
    button:disabled { cursor: wait; opacity: .65; }
    #status { margin-top: 12px; color: #475569; font-size: 13px; }
    @media (max-width: 650px) { form { grid-template-columns: 1fr; } .shell { margin-top: 12px; } }
  </style>
</head>
<body>
  <main class="shell">
    <section class="card">
      <header>
        <h1>AI 客服 Agent Demo</h1>
        <div class="hint">支持中文、English、日本語等语言；输入客户消息后由 Agent 自动处理。</div>
      </header>
      <div id="messages" aria-live="polite"></div>
      <form id="chat-form">
        <input id="customer-id" value="web_user" maxlength="100" aria-label="客户 ID" placeholder="客户 ID">
        <input id="message" maxlength="2000" required aria-label="客户消息" placeholder="输入客户消息…">
        <button id="send" type="submit">发送</button>
      </form>
    </section>
    <div id="status">动作状态将在这里显示。</div>
  </main>
  <script>
    const messages = document.getElementById('messages');
    const status = document.getElementById('status');
    const form = document.getElementById('chat-form');
    const messageInput = document.getElementById('message');
    const sendButton = document.getElementById('send');

    function addMessage(role, content, meta) {
      const row = document.createElement('div');
      row.className = `row ${role}`;
      const wrap = document.createElement('div');
      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.textContent = content || '（本轮没有自动回复）';
      wrap.appendChild(bubble);
      if (meta) {
        const detail = document.createElement('div');
        detail.className = 'meta';
        detail.textContent = meta;
        wrap.appendChild(detail);
      }
      row.appendChild(wrap);
      messages.appendChild(row);
      messages.scrollTop = messages.scrollHeight;
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const customerId = document.getElementById('customer-id').value.trim();
      const message = messageInput.value.trim();
      if (!customerId || !message) return;
      addMessage('customer', message, customerId);
      messageInput.value = '';
      sendButton.disabled = true;
      try {
        const response = await fetch('/api/message', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({customer_id: customerId, message})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '请求失败');
        const flags = [];
        if (data.is_escalated) flags.push('已转人工');
        if (data.is_not_interested) flags.push('会话已结束');
        if (data.debug_info && data.debug_info.degraded_mode) flags.push('LLM 降级模式');
        addMessage('agent', data.message, `action: ${data.action}${flags.length ? ' · ' + flags.join(' · ') : ''}`);
        status.textContent = `连续问题计数：${data.consecutive_issues}/2`;
      } catch (error) {
        addMessage('agent', `请求失败：${error.message}`, 'error');
        status.textContent = '请求失败，请检查服务状态。';
      } finally {
        sendButton.disabled = false;
        messageInput.focus();
      }
    });
    messageInput.focus();
  </script>
</body>
</html>"""


class WebChatHandler(BaseHTTPRequestHandler):
    """HTTP API 和静态页面处理器。"""

    controller: AgentController
    state_lock = threading.RLock()

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self) -> None:
        body = HTML_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 10000:
                raise ValueError("invalid request size")
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON") from error

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html()
            return

        if parsed.path == "/api/status":
            customer_id = parse_qs(parsed.query).get("customer_id", [""])[0].strip()
            if not customer_id or len(customer_id) > 100:
                self._send_json({"error": "customer_id is required"}, 400)
                return
            with self.state_lock:
                state = self.controller.get_customer_state(customer_id)
                if state is None:
                    self._send_json({"customer_id": customer_id, "exists": False})
                    return
                self._send_json({
                    "customer_id": customer_id,
                    "exists": True,
                    "is_escalated": state.is_escalated,
                    "is_not_interested": state.is_not_interested,
                    "consecutive_issues": state.consecutive_issues,
                    "message_count": len(state.message_history),
                })
            return

        self._send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        if urlparse(self.path).path != "/api/message":
            self._send_json({"error": "Not found"}, 404)
            return

        try:
            payload = self._read_json()
            customer_id = payload.get("customer_id")
            message = payload.get("message")
            if not isinstance(customer_id, str) or not customer_id.strip() or len(customer_id) > 100:
                raise ValueError("customer_id must be a non-empty string of at most 100 characters")
            if not isinstance(message, str):
                raise ValueError("message must be a string")
        except ValueError as error:
            self._send_json({"error": str(error)}, 400)
            return

        # 同一个 demo 控制器使用锁串行化，避免网页并发请求交错更新客户状态。
        with self.state_lock:
            response = self.controller.handle_message(customer_id.strip(), message)
        self._send_json(asdict(response))

    def log_message(self, format: str, *args) -> None:
        """保留简洁访问日志，不打印请求正文或 API key。"""
        print(f"[WEB] {self.address_string()} - {format % args}")


def run_server(use_llm: bool = True, host: str = "127.0.0.1", port: int = 8000) -> None:
    """启动网页 demo。"""
    controller = AgentController(use_llm=use_llm)
    handler = type("ConfiguredWebChatHandler", (WebChatHandler,), {"controller": controller})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Web chat is running at http://{host}:{port}")
    if controller.degraded_mode:
        print("[WARNING] LLM unavailable; safe degraded mode schedules follow-up without auto replies.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb chat stopped.")
    finally:
        server.server_close()
        controller.state_manager.close()


def main(use_llm: bool = True, host: str = "127.0.0.1", port: int = 8000) -> None:
    run_server(use_llm=use_llm, host=host, port=port)


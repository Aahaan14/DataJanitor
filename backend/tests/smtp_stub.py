"""
A tiny in-process SMTP server for tests, so the REAL smtplib protocol code is
exercised (no mocking of the sending path) without any extra dependency.
Supports EHLO, MAIL, RCPT, DATA, RSET, NOOP, QUIT, and a few failure switches.
"""

import socketserver
import threading
from email import message_from_bytes, policy


class _Handler(socketserver.StreamRequestHandler):
    def reply(self, line: str) -> None:
        self.wfile.write(line.encode() + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        srv = self.server
        self.reply("220 stub ESMTP ready")
        sender, rcpts = None, []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").strip()
            cmd = line.upper()
            if cmd.startswith(("EHLO", "HELO")):
                self.reply("250 stub")
            elif cmd.startswith("MAIL FROM"):
                sender, rcpts = line, []
                self.reply("250 OK")
            elif cmd.startswith("RCPT TO"):
                if srv.reject_recipients:
                    self.reply("550 5.1.1 mailbox unavailable: secret-server-detail")
                else:
                    rcpts.append(line)
                    self.reply("250 OK")
            elif cmd == "DATA":
                self.reply("354 go ahead")
                chunks = []
                while True:
                    part = self.rfile.readline()
                    if part in (b".\r\n", b""):
                        break
                    chunks.append(part[1:] if part.startswith(b"..") else part)
                if srv.fail_data:
                    self.reply("554 5.3.0 transaction failed: secret-server-detail")
                else:
                    srv.messages.append(message_from_bytes(b"".join(chunks), policy=policy.default))
                    srv.envelopes.append((sender, list(rcpts)))
                    self.reply("250 OK queued")
            elif cmd == "RSET":
                self.reply("250 OK")
            elif cmd == "NOOP":
                self.reply("250 OK")
            elif cmd == "QUIT":
                self.reply("221 bye")
                return
            else:
                self.reply("502 not implemented")


class StubSMTPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.messages = []
        self.envelopes = []
        self.reject_recipients = False
        self.fail_data = False
        self.port = self.server_address[1]
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    def start(self) -> "StubSMTPServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

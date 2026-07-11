# Triển khai Remote HTTP MCP cho BA (Phase 3)

Mục tiêu: BA truy vấn KB qua MCP không cần clone repo (spec Phase 3 §10).

## Máy chủ nội bộ

1. Clone hub: `git clone <kb-hub-url> /srv/kb-hub`
2. Cài tool: `pip install center-kb` (thêm `.[embed]` nếu muốn semantic search)
3. Đặt token: `export CENTER_KB_HTTP_TOKEN=$(openssl rand -hex 24)` — lưu vào secret manager
4. Chạy server:
   `python -m center_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321`
5. Cron giữ hub tươi (mỗi 5 phút): `*/5 * * * * git -C /srv/kb-hub pull --ff-only`

### systemd unit mẫu

    [Unit]
    Description=CENTER-KB remote MCP
    After=network.target

    [Service]
    Environment=CENTER_KB_HTTP_TOKEN=<token>
    ExecStart=/usr/bin/python3 -m center_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target

## Cấu hình client (Claude Code / Cowork)

    {
      "mcpServers": {
        "center-kb": {
          "type": "http",
          "url": "http://kb.internal:8321/mcp",
          "headers": { "Authorization": "Bearer <token>" }
        }
      }
    }

Lưu ý: chỉ chạy trong mạng nội bộ/VPN — tài liệu có bản quyền. Server từ chối
khởi động nếu thiếu `CENTER_KB_HTTP_TOKEN`.

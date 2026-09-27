#!/usr/bin/env node
// MCP server CHỈ-ĐỌC cho hệ thống truycuu.io.vn.
//  - crm_query: MySQL DB `truycuu` qua user claude_ro (SELECT-only) trên VPS.
//  - bot_query: SQLite bot bán hàng (autopayment.db) mở read-only.
// Kết nối qua SSH sẵn có (file config sạch cạnh server này, bỏ qua config Augment hỏng).
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SSH_BIN = "C:\\Windows\\System32\\OpenSSH\\ssh.exe";
const SSH_CONFIG = path.join(__dirname, "ssh_config");
const HOST = "truycuu";
const MAX_OUT = 60000;

// Bổ sung các biến Windows cốt lõi để ssh.exe chạy được kể cả khi launcher (Claude Desktop)
// lược bớt môi trường — nếu thiếu, ssh thoát 255 (không kết nối được).
function buildEnv() {
  const e = { ...process.env };
  const def = {
    SystemRoot: "C:\\Windows", windir: "C:\\Windows", SystemDrive: "C:",
    USERPROFILE: "C:\\Users\\Trung Kiên", HOMEDRIVE: "C:", HOMEPATH: "\\Users\\Trung Kiên",
    ProgramData: "C:\\ProgramData", ComSpec: "C:\\Windows\\System32\\cmd.exe",
    PATH: "C:\\Windows\\System32;C:\\Windows;C:\\Windows\\System32\\OpenSSH",
    PATHEXT: ".COM;.EXE;.BAT;.CMD",
  };
  for (const k in def) if (!e[k] && !e[k.toUpperCase()]) e[k] = def[k];
  return e;
}

function runSSH(remoteArgv, sql) {
  return new Promise((resolve) => {
    const proc = spawn(SSH_BIN, ["-F", SSH_CONFIG, HOST, ...remoteArgv], { windowsHide: true, env: buildEnv() });
    let out = "", err = "";
    proc.stdout.on("data", (d) => { if (out.length < MAX_OUT + 1000) out += d; });
    proc.stderr.on("data", (d) => { err += d; });
    proc.on("close", (code) => {
      const e = err.split("\n").filter((l) => !/insecure|Warning: Using a password/i.test(l)).join("\n").trim();
      resolve({ code, out: out.trim(), err: e });
    });
    proc.on("error", (er) => resolve({ code: -1, out: "", err: String(er) }));
    if (sql != null) { proc.stdin.write(sql); proc.stdin.end(); }
  });
}

// Lớp bảo vệ phụ (dù claude_ro/SQLite đã read-only): chỉ cho câu ĐỌC, 1 câu lệnh.
function readOnlyError(sql) {
  const s = String(sql || "").trim().replace(/;+\s*$/, "");
  if (!s) return "SQL rỗng.";
  if (s.includes(";")) return "Chỉ 1 câu lệnh (không dùng ';').";
  if (!/^(select|with|show|describe|desc|explain|pragma\s+table_info|pragma\s+table_list)\b/i.test(s))
    return "Chỉ cho phép câu ĐỌC: SELECT / WITH / SHOW / DESCRIBE / EXPLAIN.";
  if (/\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|rename|call|lock\s+tables)\b/i.test(s) ||
      /replace\s+into|load\s+data|into\s+(outfile|dumpfile)/i.test(s))
    return "Phát hiện từ khoá ghi/nguy hiểm — từ chối.";
  return null;
}

const TOOLS = [
  {
    name: "crm_query",
    description:
      "Chạy 1 câu SQL CHỈ-ĐỌC trên CRM MySQL (DB truycuu, user SELECT-only). " +
      "Bảng chính: customers, customer_services, pending_orders, profits, service_packages, service_categories, collaborators. " +
      "Mẹo: 'SHOW TABLES', 'DESCRIBE <bảng>'. Dùng LIMIT khi bảng lớn. Trả bảng ASCII, tối đa 500 dòng.",
    inputSchema: { type: "object", properties: { sql: { type: "string", description: "1 câu SELECT/SHOW/DESCRIBE, không có ';'" } }, required: ["sql"] },
  },
  {
    name: "bot_query",
    description:
      "Chạy 1 câu SQL CHỈ-ĐỌC trên DB bot bán hàng (SQLite autopayment.db, read-only). " +
      "Bảng chính: orders, products, accounts_<product_id>, bot_users, topups, vouchers, warranty_requests. " +
      "Xem bảng: SELECT name FROM sqlite_master WHERE type='table'. Tối đa 500 dòng.",
    inputSchema: { type: "object", properties: { sql: { type: "string", description: "1 câu SELECT, không có ';'" } }, required: ["sql"] },
  },
];

const server = new Server({ name: "truycuu-crm-ro", version: "1.0.0" }, { capabilities: { tools: {} } });
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));
server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const name = req.params.name;
  const sql = req.params.arguments?.sql ?? "";
  const bad = readOnlyError(sql);
  if (bad) return { content: [{ type: "text", text: "❌ " + bad }], isError: true };

  let r;
  if (name === "crm_query")
    r = await runSSH(["mysql", "--defaults-extra-file=/root/.claude_ro.cnf", "truycuu", "-t"], sql);
  else if (name === "bot_query")
    r = await runSSH(["python3", "/root/bot_ro_query.py"], sql);
  else return { content: [{ type: "text", text: "Tool không tồn tại: " + name }], isError: true };

  let text = r.code === 0 ? (r.out || "(không có kết quả)") : ("Lỗi: " + (r.err || r.out || ("exit " + r.code)));
  if (text.length >= MAX_OUT) text = text.slice(0, MAX_OUT) + "\n… (cắt bớt — hãy dùng LIMIT để thu hẹp)";
  return { content: [{ type: "text", text }], isError: r.code !== 0 };
});

const transport = new StdioServerTransport();
await server.connect(transport);

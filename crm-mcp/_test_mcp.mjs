import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "node",
  args: ["C:\\claude code\\crm-mcp\\server.js"],
});
const client = new Client({ name: "test", version: "1.0.0" });
await client.connect(transport);

const tools = await client.listTools();
console.log("TOOLS:", tools.tools.map((t) => t.name).join(", "));

const r1 = await client.callTool({ name: "crm_query", arguments: { sql: "SELECT COUNT(*) AS customers FROM customers" } });
console.log("\n[CRM]\n" + r1.content[0].text);

const r2 = await client.callTool({ name: "bot_query", arguments: { sql: "SELECT COUNT(*) AS paid_orders FROM orders WHERE status='paid'" } });
console.log("\n[BOT]\n" + r2.content[0].text);

const r3 = await client.callTool({ name: "crm_query", arguments: { sql: "DELETE FROM customers WHERE 1=1" } });
console.log("\n[WRITE-BLOCK] isError=" + r3.isError + " -> " + r3.content[0].text);

await client.close();
process.exit(0);

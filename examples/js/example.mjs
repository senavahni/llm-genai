// Contoh SDK `openai` (JavaScript/TypeScript) terhadap gateway.
//   cd examples\js && npm install && node example.mjs
// Env: LGW_BASE_URL (default http://127.0.0.1:8000/v1), LGW_API_KEY
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: process.env.LGW_BASE_URL ?? "http://127.0.0.1:8000/v1",
  apiKey: process.env.LGW_API_KEY,
  defaultHeaders: { "X-Caller-Task": "contoh-js" },
  timeout: 600_000,
});

// non-stream + header gateway
const { data: chat, response } = await client.chat.completions
  .create({
    model: "fast",
    messages: [{ role: "user", content: "Sebutkan satu buah berwarna kuning." }],
    max_tokens: 30,
  })
  .withResponse();
console.log("chat:", chat.choices[0].message.content);
console.log("  device:", response.headers.get("x-gateway-device"), "request:", response.headers.get("x-request-id"));

// stream
const stream = await client.chat.completions.create({
  model: "fast",
  messages: [{ role: "user", content: "Hitung 1 sampai 5." }],
  max_tokens: 30,
  stream: true,
  stream_options: { include_usage: true },
});
process.stdout.write("stream: ");
for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content ?? "");
  if (chunk.usage) console.log(`\n  usage: ${chunk.usage.total_tokens} token`);
}

// FIM (autocomplete)
const fim = await client.completions.create({
  model: "autocomplete",
  prompt: "function add(a, b) {\n",
  suffix: "\n}\n",
  max_tokens: 32,
  temperature: 0,
});
console.log("fim:", JSON.stringify(fim.choices[0].text));

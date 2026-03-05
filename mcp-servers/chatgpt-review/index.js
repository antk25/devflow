import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { spawn } from "node:child_process";

const REVIEW_PROMPT = `You are a code reviewer. Review the following code diff for:

1. **Security** — injection, auth issues, data exposure, OWASP Top 10
2. **Performance** — N+1 queries, memory leaks, unnecessary re-renders, missing indexes
3. **Code Quality** — SOLID, error handling, type safety, duplication, naming

For each issue found, provide:
- Severity: CRITICAL / WARNING / SUGGESTION
- File and approximate location (from diff context)
- Description of the problem
- Recommended fix

If the code looks good, say so explicitly.

Format your response as structured markdown with sections: Critical Issues, Warnings, Suggestions, Positive Observations.`;

const PLAN_PROMPT = `You are a senior project manager and software architect. Analyze the feature request and create a detailed implementation plan.

Your plan MUST include:
1. **Tasks** — numbered list of implementation tasks in execution order
2. **Per task**: description, affected files/layers, complexity (low/medium/high)
3. **Dependencies** — which tasks depend on which
4. **Edge cases** — potential pitfalls and how to handle them
5. **Implementation order** — optimal sequence considering dependencies

Format your response as structured markdown with:
- Numbered task list with descriptions
- Dependency graph (task N depends on task M)
- Edge cases section
- Complexity estimates`;

const CONTRACT_PROMPT = `You are a senior software architect specializing in API and system design. Generate a feature contract that defines exact schemas, endpoints, events, and database changes.

Generate a contract with ONLY the sections that apply:
- **API section**: if new/modified endpoints (method, path, request/response schemas with types)
- **DTO section**: if new commands/queries/response objects (field names and types)
- **Events section**: if domain events are dispatched or consumed (name, payload, dispatcher, consumers)
- **Database section**: if schema changes (tables, columns, types, indexes, foreign keys)
- **Component section**: if frontend components (props, emits, slots)

Rules:
- YAML code blocks are the source of truth — every field must have an explicit type
- Field names in YAML must match code (exact casing)
- Every API error case must have a status code
- Events must specify BOTH dispatched_by AND consumed_by
- Database section must specify action: create | alter
- Never generate empty sections — omit if not applicable
- Write descriptions in Russian, code identifiers in English

Format: Markdown with YAML code blocks for each section.`;

function callCodex(prompt, stdinData, timeoutMs = 120_000) {
  return new Promise((resolve, reject) => {
    const args = [
      "exec",
      "--json",
      "--ephemeral",
      "-",  // read prompt from stdin
    ];

    const proc = spawn("codex", args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
      timeout: timeoutMs,
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    proc.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

    // Codex exec reads prompt from stdin when "-" is passed
    const input = stdinData
      ? `${prompt}\n\n${stdinData}`
      : prompt;

    proc.stdin.write(input);
    proc.stdin.end();

    proc.on("close", (code) => {
      if (code !== 0 && !stdout) {
        reject(new Error(`codex exited with code ${code}: ${stderr}`));
        return;
      }
      resolve(stdout);
    });

    proc.on("error", (err) => {
      reject(new Error(`Failed to spawn codex: ${err.message}`));
    });
  });
}

function extractResult(jsonlOutput) {
  try {
    const lines = jsonlOutput.trim().split("\n");
    const events = lines.map((line) => JSON.parse(line));

    // Collect all agent_message texts (there may be multiple items)
    const messages = events
      .filter((e) => e.type === "item.completed" && e.item?.type === "agent_message")
      .map((e) => e.item.text)
      .filter(Boolean);

    if (messages.length > 0) {
      return messages.join("\n\n");
    }

    // Fallback: look for any text in completed items
    const anyText = events
      .filter((e) => e.type === "item.completed" && e.item?.text)
      .map((e) => e.item.text)
      .filter(Boolean);

    if (anyText.length > 0) {
      return anyText.join("\n\n");
    }

    return "No output produced by ChatGPT.";
  } catch {
    // If JSONL parsing fails, return raw output
    return jsonlOutput.trim() || "No output from ChatGPT.";
  }
}

const server = new McpServer({
  name: "chatgpt-review",
  version: "1.0.0",
});

server.tool(
  "gpt_code_review",
  "Run code review using ChatGPT via Codex CLI. Pass a git diff and optional context. Returns structured review with issues categorized by severity.",
  {
    diff: z.string().describe("Git diff content to review"),
    context: z.string().optional().describe("Additional context: project conventions, feature description, focus areas"),
  },
  async ({ diff, context }) => {
    const contextSection = context
      ? `\n\nAdditional context:\n${context}`
      : "";

    const fullPrompt = `${REVIEW_PROMPT}${contextSection}\n\nReview the following diff:\n\n${diff}`;

    const MAX_PROMPT_LENGTH = 30_000;
    let codexPrompt;
    let stdinData;

    if (fullPrompt.length > MAX_PROMPT_LENGTH) {
      codexPrompt = `${REVIEW_PROMPT}${contextSection}\n\nReview the code diff provided below.`;
      stdinData = diff;
    } else {
      codexPrompt = fullPrompt;
      stdinData = null;
    }

    try {
      const rawOutput = await callCodex(codexPrompt, stdinData);
      const reviewText = extractResult(rawOutput);

      return {
        content: [{ type: "text", text: reviewText }],
      };
    } catch (error) {
      return {
        content: [{ type: "text", text: `ChatGPT review failed: ${error.message}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "gpt_plan",
  "Generate an implementation plan using ChatGPT via Codex CLI. Pass a feature description and optional context. Returns structured plan with tasks, dependencies, and edge cases.",
  {
    task: z.string().describe("Feature description to plan"),
    context: z.string().optional().describe("Additional context: project conventions, deep trace results, RAG context, acceptance criteria"),
  },
  async ({ task, context }) => {
    const contextSection = context
      ? `\n\nProject context:\n${context}`
      : "";

    const fullPrompt = `${PLAN_PROMPT}${contextSection}\n\nFeature to plan:\n\n${task}`;

    const MAX_PROMPT_LENGTH = 30_000;
    let codexPrompt;
    let stdinData;

    if (fullPrompt.length > MAX_PROMPT_LENGTH) {
      codexPrompt = `${PLAN_PROMPT}${contextSection}\n\nFeature description provided below.`;
      stdinData = task;
    } else {
      codexPrompt = fullPrompt;
      stdinData = null;
    }

    try {
      const rawOutput = await callCodex(codexPrompt, stdinData, 180_000);
      const planText = extractResult(rawOutput);

      return {
        content: [{ type: "text", text: planText }],
      };
    } catch (error) {
      return {
        content: [{ type: "text", text: `ChatGPT plan failed: ${error.message}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "gpt_contract",
  "Generate a feature contract using ChatGPT via Codex CLI. Pass feature description, plan tasks, and optional context. Returns contract in C-DAD format (Markdown + YAML).",
  {
    task: z.string().describe("Feature description"),
    plan: z.string().describe("Plan tasks summary from planning phase"),
    context: z.string().optional().describe("Additional context: deep trace results, project conventions, repository info"),
  },
  async ({ task, plan, context }) => {
    const contextSection = context
      ? `\n\nProject context:\n${context}`
      : "";

    const fullPrompt = `${CONTRACT_PROMPT}${contextSection}\n\nFeature: ${task}\n\nPlan tasks:\n${plan}`;

    const MAX_PROMPT_LENGTH = 30_000;
    let codexPrompt;
    let stdinData;

    if (fullPrompt.length > MAX_PROMPT_LENGTH) {
      codexPrompt = `${CONTRACT_PROMPT}${contextSection}\n\nFeature and plan provided below.`;
      stdinData = `Feature: ${task}\n\nPlan tasks:\n${plan}`;
    } else {
      codexPrompt = fullPrompt;
      stdinData = null;
    }

    try {
      const rawOutput = await callCodex(codexPrompt, stdinData, 180_000);
      const contractText = extractResult(rawOutput);

      return {
        content: [{ type: "text", text: contractText }],
      };
    } catch (error) {
      return {
        content: [{ type: "text", text: `ChatGPT contract failed: ${error.message}` }],
        isError: true,
      };
    }
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);

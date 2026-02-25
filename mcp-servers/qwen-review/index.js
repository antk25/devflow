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

function callQwen(prompt, stdinData, timeoutMs = 120_000) {
  return new Promise((resolve, reject) => {
    const args = [
      prompt,
      "-o", "json",
      "--approval-mode", "plan",
      "--max-session-turns", "10",
      "--chat-recording", "false",
    ];

    const proc = spawn("qwen", args, {
      stdio: ["pipe", "pipe", "pipe"],
      env: { ...process.env },
      timeout: timeoutMs,
    });

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk) => { stdout += chunk.toString(); });
    proc.stderr.on("data", (chunk) => { stderr += chunk.toString(); });

    if (stdinData) {
      proc.stdin.write(stdinData);
      proc.stdin.end();
    } else {
      proc.stdin.end();
    }

    proc.on("close", (code) => {
      if (code !== 0 && !stdout) {
        reject(new Error(`qwen exited with code ${code}: ${stderr}`));
        return;
      }
      resolve(stdout);
    });

    proc.on("error", (err) => {
      reject(new Error(`Failed to spawn qwen: ${err.message}`));
    });
  });
}

function extractResult(jsonOutput) {
  try {
    const events = JSON.parse(jsonOutput);
    // Find the result event
    const resultEvent = events.find((e) => e.type === "result");
    if (resultEvent?.result) {
      return resultEvent.result;
    }
    // Fallback: find last assistant text message
    const assistantMessages = events.filter(
      (e) => e.type === "assistant" && e.message?.content
    );
    for (let i = assistantMessages.length - 1; i >= 0; i--) {
      const content = assistantMessages[i].message.content;
      const textBlock = content.find((c) => c.type === "text");
      if (textBlock?.text) {
        return textBlock.text;
      }
    }
    return "No review output produced by Qwen.";
  } catch {
    // If JSON parsing fails, return raw output (might be text format)
    return jsonOutput.trim() || "No output from Qwen.";
  }
}

const server = new McpServer({
  name: "qwen-review",
  version: "1.1.0",
});

server.tool(
  "qwen_code_review",
  "Run code review using Qwen Code CLI. Pass a git diff and optional context. Returns structured review with issues categorized by severity.",
  {
    diff: z.string().describe("Git diff content to review"),
    context: z.string().optional().describe("Additional context: project conventions, feature description, focus areas"),
  },
  async ({ diff, context }) => {
    const contextSection = context
      ? `\n\nAdditional context:\n${context}`
      : "";

    const fullPrompt = `${REVIEW_PROMPT}${contextSection}\n\nReview the following diff:\n\n${diff}`;

    // For very large diffs, pipe via stdin; for smaller ones, include in prompt
    const MAX_PROMPT_LENGTH = 30_000;
    let qwenPrompt;
    let stdinData;

    if (fullPrompt.length > MAX_PROMPT_LENGTH) {
      qwenPrompt = `${REVIEW_PROMPT}${contextSection}\n\nReview the code diff provided on stdin.`;
      stdinData = diff;
    } else {
      qwenPrompt = fullPrompt;
      stdinData = null;
    }

    try {
      const rawOutput = await callQwen(qwenPrompt, stdinData);
      const reviewText = extractResult(rawOutput);

      return {
        content: [
          {
            type: "text",
            text: reviewText,
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `Qwen review failed: ${error.message}`,
          },
        ],
        isError: true,
      };
    }
  }
);

server.tool(
  "qwen_plan",
  "Generate an implementation plan using Qwen Code CLI. Pass a feature description and optional context. Returns structured plan with tasks, dependencies, and edge cases.",
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
    let qwenPrompt;
    let stdinData;

    if (fullPrompt.length > MAX_PROMPT_LENGTH) {
      qwenPrompt = `${PLAN_PROMPT}${contextSection}\n\nFeature description provided on stdin.`;
      stdinData = task;
    } else {
      qwenPrompt = fullPrompt;
      stdinData = null;
    }

    try {
      const rawOutput = await callQwen(qwenPrompt, stdinData, 180_000);
      const planText = extractResult(rawOutput);

      return {
        content: [{ type: "text", text: planText }],
      };
    } catch (error) {
      return {
        content: [{ type: "text", text: `Qwen plan failed: ${error.message}` }],
        isError: true,
      };
    }
  }
);

server.tool(
  "qwen_contract",
  "Generate a feature contract using Qwen Code CLI. Pass feature description, plan tasks, and optional context. Returns contract in C-DAD format (Markdown + YAML).",
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
    let qwenPrompt;
    let stdinData;

    if (fullPrompt.length > MAX_PROMPT_LENGTH) {
      qwenPrompt = `${CONTRACT_PROMPT}${contextSection}\n\nFeature and plan provided on stdin.`;
      stdinData = `Feature: ${task}\n\nPlan tasks:\n${plan}`;
    } else {
      qwenPrompt = fullPrompt;
      stdinData = null;
    }

    try {
      const rawOutput = await callQwen(qwenPrompt, stdinData, 180_000);
      const contractText = extractResult(rawOutput);

      return {
        content: [{ type: "text", text: contractText }],
      };
    } catch (error) {
      return {
        content: [{ type: "text", text: `Qwen contract failed: ${error.message}` }],
        isError: true,
      };
    }
  }
);

const transport = new StdioServerTransport();
await server.connect(transport);

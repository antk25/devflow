# Phase 1.5: Deep Trace (for business logic tasks)

**REQUIRED** when BUSINESS_LOGIC_KEYWORDS are detected in the task description.
**OPTIONAL** for other tasks, but recommended when modifying existing features.

This phase prevents implementation errors by tracing the FULL data/event chain before writing code.

## When to Run Deep Trace

Run if task involves ANY of:
- Modifying existing calculations/analytics
- Adding event handlers/listeners
- Changing data that other code depends on
- Working with status/lifecycle changes
- Sync/import/export functionality
- Triggers that cascade to other systems

## How to Perform Deep Trace

**Spawn the Tracer agent** to perform analysis in separate context:

```
Task(
  description: "Deep Trace: <feature name>",
  prompt: "Trace the business logic for: <feature description>

  Repository: <repo_path>

  Focus on:
  1. Data flow - where does the data come from? What filters apply?
  2. Event chain - what triggers what? What events are dispatched?
  3. Entity relationships - what is the correct relationship chain?
  4. Edge cases - first run, null states, already in final state?

  Look for similar existing implementations to follow as pattern.

  Return structured JSON summary only, not code.",
  subagent_type: "Tracer"
)
```

## Tracer Agent Output

The Tracer returns a structured JSON summary (~500-1000 chars):

```json
{
  "feature": "BankAnalytics deletion for credits",

  "data_flow": {
    "chain": ["Credit", "CreditProgram", "Provider", "BankAnalytics"],
    "filters": ["status = VALIDATED", "dateOfIssue in period"],
    "key_query": "BankAnalyticsDTOFactory uses CreditFilters(statuses: [VALIDATED])"
  },

  "event_chain": {
    "triggers": ["CreditStatusChangedEvent"],
    "warnings": ["NOT dispatched when oldStatus is null (first assignment)"]
  },

  "entity_relationships": {
    "correct_chain": "Credit → CreditProgram → Provider (ONE)",
    "wrong_assumption": "Credit → SalesOutlet → Providers (MANY)"
  },

  "edge_cases": [
    "Credit created already VALIDATED - CreditStatusChangedEvent not fired"
  ],

  "implementation_guidance": [
    "Listen to CreditStatusChangedEvent when newStatus=VALIDATED",
    "ALSO handle CreditCreatedEvent - check if already VALIDATED",
    "Use credit.creditProgram.provider (ONE bank)"
  ],

  "similar_implementations": [
    "DeleteBankAnalyticsAfterECreditEventHandler.php - same pattern"
  ]
}
```

## Using Trace Results

Store the trace results and pass to PM agent in Phase 2:

```
deep_trace_results = <output from Tracer>
```

**CRITICAL:** Do NOT proceed to Phase 2 until Deep Trace is complete for business logic tasks.

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_2_plan trace_summary='<brief summary>'
```

用户原文（2026-11-11 17:57 UTC+8）：
现在我们trace页面需要一些改动，但是现在我们已经设计了一些节点状态的类型，你先需要去查看现在设置的是否有冲突，或者重复的状态，需要删除旧的，换成我新设计的这个逻辑。
# Task: Build an Agent Workflow Trace & Observability Dashboard

## 1. Role & Objective
You are an expert Frontend & Full-stack Engineer. Build a production-grade **Agent Workflow Trace & Observability Dashboard** for debugging and monitoring LLM multi-step workflows. The system must fulfill three core diagnostic goals: **Process Tracking**, **Data Inspection (I/O & Prompt)**, and **Performance/Cost Monitoring**.

---

## 2. UI Layout & Architecture (Two-Tier Design)

### Tier 1: Global Monitoring List Page (`/traces`)
A high-level management table for operators/developers to scan system health and spot errors.
- **Top Filter Bar**: 
  - Status filter dropdown (All, Success, Error, Running).
  - Time range selector.
  - Search input by `Trace ID` or `User Query`.
- **Data Table Columns**:
  - `Trace ID` (Clickable to open detail drawer).
  - `User Query Summary` (Truncated text).
  - `Trigger Timestamp`.
  - `Overall Status` (Badge with color: Green=Success, Red=Error, Yellow=Running).
  - `Total Duration` (e.g., `2.4s`).
  - `Total Tokens` & `Estimated Cost` (e.g., `3,200 tokens / $0.005`).
  - `Action` button: [View Trace Details].

### Tier 2: Trace Detail View (Drawer / Modal)
Triggered by clicking a trace row, opens a split-screen drawer (Left: Execution Tree; Right: Node Payload).
- **Header Summary**: Trace ID, Global Status, Total Duration, Total Tokens, Timestamp.
- **Left Column (Execution Tree / Waterfall)**:
  - Hierarchical tree or waterfall view of workflow nodes (using `parent_node_id` nesting).
  - Node types: `Router`, `RAG`, `LLM`, `Tool_Call`, `Condition_Branch`.
  - Node Status indicators: 🟢 Success, 🔴 Error, 🟡 Running/Suspended, ⚪ Skipped.
  - Clicking any node updates the Right Column.
- **Right Column (Node Payload & Inspector)**:
  - Tabs:
    1. **`Input / Prompt`**: Shows final rendered System/User Prompt with syntax highlighting.
    2. **`Raw Output`**: Shows model generation text or tool return JSON.
    3. **`Metrics & Token`**: Single node duration, Input/Output Token count, Model version, Temperature.
    4. **`Error Stack`**: If node status is Error, display formatted backend error stack / code (e.g., `ERR_JSON_PARSE`).

---

## 3. Data Structure (TypeScript Interfaces)

```typescript
type NodeStatus = 'success' | 'error' | 'running' | 'skipped' | 'suspended';
type NodeType = 'router' | 'rag' | 'llm' | 'tool' | 'condition';

interface WorkflowNode {
  node_id: string;
  parent_node_id: string | null;
  node_name: string;
  node_type: NodeType;
  status: NodeStatus;
  duration_ms: number;
  tokens: {
    input: number;
    output: number;
  };
  payload: {
    prompt_version?: string;
    raw_input?: string;
    raw_output?: string;
    error_message?: string;
    model_name?: string;
  };
}

interface TraceExecution {
  trace_id: string;
  user_query: string;
  triggered_at: string;
  overall_status: NodeStatus;
  total_duration_ms: number;
  total_tokens: number;
  estimated_cost_usd: number;
  nodes: WorkflowNode[];
}
```

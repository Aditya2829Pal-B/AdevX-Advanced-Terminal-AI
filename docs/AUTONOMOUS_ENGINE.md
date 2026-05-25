# AdevX Autonomous Reasoning Engine

## Purpose

This document specifies the autonomous multi-step agent system added to AdevX.
The goal is to move from single-turn chatbot behavior to a persistent
plan-execute-reflect platform.

## Core Components

1. Goal decomposition engine:
   `planning/goal_decomposer.py`
2. Tree-of-thought planning:
   `planning/tot_planner.py`
3. Multi-agent role system:
   `agents/roles.py`
4. Collaboration and dynamic subtask spawning:
   `agents/collaboration.py`
5. Execution graph + dependency scheduler:
   `execution/execution_graph.py`
6. Reflection/self-critique:
   `execution/reflection.py`
7. Checkpoint + rollback:
   `execution/checkpoint_store.py`
8. Autonomous control loop:
   `execution/autonomous_engine.py`
9. Memory-aware context stack:
   `memory/working.py`
10. Tool intelligence:
    `execution/tool_selection.py`

## Agent Roles

1. Planner Agent:
   constructs goal, decomposes tasks, runs ToT candidate selection.
2. Executor Agent:
   runs ReAct-oriented execution using provider and tool hints.
3. Reviewer Agent:
   validates outputs and emits correction recommendations.
4. Research Agent:
   retrieves RAG context + long-term memory + prioritized working memory.
5. Coding Agent:
   specialization wrapper for implementation-heavy tasks.

## Planning Algorithms

1. Goal decomposition:
   mode and keyword heuristics produce dependency-aware subtasks.
2. Tree-of-thought:
   generates `fast`, `balanced`, and `deep` candidate branches.
3. Candidate scoring:
   confidence + token estimate choose a selected plan.
4. Token budgeting:
   separate budgets for planning, execution, reflection, retries.

## Execution Model

1. Plan nodes are compiled into an execution graph.
2. Graph scheduler runs all dependency-ready nodes in parallel.
3. Each node goes through:
   checkpoint -> execution -> reflection -> accept/retry/replan/halt.
4. Retry/correction loop:
   reflection may inject revised payload and schedule retry.
5. Replan loop:
   reflection may trigger rollback to last checkpoint.
6. Dynamic subtask spawning:
   collaboration manager can inject follow-up tasks into live graph.

## ReAct + Plan-Execute + Reflection

The loop uses:

1. PLAN:
   planner selects strategy and tasks.
2. REACT EXECUTION:
   executor forms step-level action prompts using context + scratchpad.
3. OBSERVE:
   outputs are stored in scratchpad and working memory.
4. REFLECT:
   reflection engine computes confidence and hallucination risk.
5. IMPROVE:
   retry, replan, or accept.

## Memory Integration Strategy

1. Scratchpad memory:
   transient chain-of-work log for current run.
2. Working memory:
   weighted and prioritized context snippets.
3. Long-term memory:
   persistent session history in JSON store.
4. Retrieval:
   combined view:
   RAG + long-term notes + prioritized working memory.
5. Context prioritization:
   lexical overlap + recency + item weight scoring.

## Hallucination and Reliability Controls

1. Confidence scoring from output quality signals.
2. Hallucination risk scoring from unsafe certainty markers.
3. Retry thresholds per node.
4. Circuit breaker and retries at provider layer.
5. Checkpoint rollback for recovery.

## Multi-Agent Parallelism

1. Ready nodes execute concurrently with bounded semaphore.
2. Independent subtasks can run in the same iteration.
3. Agent state manager constrains global runtime concurrency.
4. Subtasks can be spawned mid-run and re-enter scheduler.

## Orchestration Pseudocode

```python
async def autonomous_run(request):
    plan = planner.plan(request)             # decompose + ToT select
    graph = ExecutionGraph(plan.tasks)
    ctx = researcher.gather(request, plan.goal)

    while not graph.all_done():
        ready = graph.ready_nodes()
        outcomes = await parallel_execute(ready, ctx)

        for node, output in outcomes:
            reflection = reflect(node, output)
            if reflection.action == "accept":
                graph.mark_success(node)
                maybe_spawn_subtasks(node, output, graph)
            elif reflection.action == "retry":
                graph.reset_for_retry(node, reflection.revised_payload)
            elif reflection.action == "replan":
                rollback_to_checkpoint(graph)
            else:
                graph.mark_failure(node)

        if token_budget_exhausted():
            break

    return summarize(graph, trace)
```

## Execution Example

Goal:
"Build autonomous reasoning engine with retries and reflection."

1. Planner decomposes into:
   analyze -> research -> implement -> review -> finalize.
2. Execution graph runs research and implementation where dependencies allow.
3. Reviewer flags low confidence in implementation output.
4. Engine retries implementation with revised payload.
5. New output passes confidence threshold.
6. Final summary includes:
   confidence, retries, replans, spawned subtasks, trace logs.

## Runtime Integration

`runtime/bootstrap.py` now wires:

1. planner/research/executor/reviewer/coding agents
2. collaboration manager
3. reflection + checkpoint engines
4. autonomous capability registration:
   `capability.autonomous`
5. planner trigger for autonomous requests:
   `planning/planner.py`

## Future Expansion Hooks

1. distributed remote executors for graph nodes
2. external vector DB memory backend
3. OpenTelemetry export
4. GUI timeline view of node execution graph
5. voice in/out agents with same orchestrator


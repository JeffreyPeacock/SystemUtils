# /create-plan — Enter planning mode for a task

The task to plan is the argument text passed to this skill. If no argument was provided, ask the user what they want to plan before proceeding.

## Step 1 — Enter plan mode

Use ToolSearch with query `"select:EnterPlanMode"` to load the tool schema, then call EnterPlanMode.

## Step 2 — Follow the plan mode workflow

Once in plan mode, follow the full 5-phase planning workflow from the plan mode system instructions:
- **Phase 1:** Launch up to 3 Explore agents in parallel to understand the codebase
- **Phase 2:** Launch a Plan agent to design the approach
- **Phase 3:** Review and clarify with the user if needed
- **Phase 4:** Write the final plan to the plan file
- **Phase 5:** Call ExitPlanMode for user approval

Treat the skill argument as the user's planning request — as if they had typed it as a message while already in plan mode.

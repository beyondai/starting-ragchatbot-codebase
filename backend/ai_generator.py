import anthropic
from typing import List, Optional, Dict, Any

class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""
    
    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to tools for course information.

Tool Usage:
- **get_course_list**: use for questions about which courses exist, how many there are, or to list/enumerate the catalog (e.g. "what courses are available", "list all courses")
- **search_course_content**: use **only** for questions about specific course content or detailed educational materials — it returns a handful of relevant excerpts, not the full catalog, so never use it to enumerate courses
- **get_course_outline**: use for questions about a single course's structure, syllabus, or lesson list (e.g. "what lessons are in course X", "give me the outline of Y", "what does course Z cover") — when answering, always include the course title, the course link, and every lesson's number and title exactly as returned by the tool; do not omit or summarize the lesson list

Sequential tool calls:
- You may use tools across up to 2 separate rounds per question. After seeing a tool's results, you may call another tool (the same one again with different arguments, or a different one) if you still need more information before answering.
- A common pattern: call get_course_outline first to find an exact lesson title or topic, then use that result as input to search_course_content in a second call — e.g. to find what other course covers the same topic as a specific lesson.
- Only use a second round when the first round's results are genuinely insufficient — do not make a second tool call just to double-check an already-sufficient answer.
- After 2 rounds of tool calls, answer using the information already gathered, even if another search might help further.
- Synthesize tool results into accurate, fact-based responses
- If a tool yields no results, state this clearly without offering alternatives

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without using tools
- **Course-specific questions**: Use the appropriate tool(s) first, then answer
- **Multi-part or comparison questions** (e.g. "how does X compare to Y", "find a course that covers the same topic as lesson N of course X"): use multiple tool calls across rounds as needed to gather all the necessary information before answering
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""

    MAX_TOOL_ROUNDS = 2  # bump this alone to raise the sequential tool-call cap

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        
        # Pre-build base API parameters
        self.base_params = {
            "model": self.model,
            "max_tokens": 800
        }
    
    def generate_response(self, query: str,
                         conversation_history: Optional[str] = None,
                         tools: Optional[List] = None,
                         tool_manager=None) -> str:
        """
        Generate AI response, allowing up to MAX_TOOL_ROUNDS sequential tool
        calls (each a separate API round, so Claude can reason about one
        tool's results before deciding whether to call another).

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools

        Returns:
            Generated response as string
        """
        system_content = self._build_system_content(conversation_history)
        messages = [{"role": "user", "content": query}]
        return self._run_tool_loop(messages, system_content, tools, tool_manager)

    def _build_system_content(self, conversation_history: Optional[str]) -> str:
        return (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

    def _run_tool_loop(self, messages: List[Dict[str, Any]], system_content: str,
                        tools: Optional[List], tool_manager) -> str:
        """Runs up to MAX_TOOL_ROUNDS rounds of tool calling, then forces a
        final tools-omitted call to synthesize an answer if the cap is
        reached (or a tool call hard-fails) before Claude returns text."""
        if tool_manager:
            # Defensive: guard against stale sources leaking in if a prior
            # call raised before RAGSystem.query() reached its own reset.
            tool_manager.reset_sources()

        can_use_tools = bool(tools and tool_manager)

        for _round_num in range(1, self.MAX_TOOL_ROUNDS + 1):
            response = self._call_claude(messages, system_content, tools if can_use_tools else None)

            if response.stop_reason != "tool_use" or not can_use_tools:
                return self._response_to_text(response)

            messages.append({"role": "assistant", "content": response.content})
            tool_results, hard_failure = self._execute_tool_round(response.content, tool_manager)
            messages.append({"role": "user", "content": tool_results})

            if hard_failure:
                break

        # Cap reached, or a hard tool failure cut rounds short: force one
        # last call with NO tools, so Claude can't request another tool call
        # and must synthesize a text answer from what's already gathered.
        final_response = self._call_claude(messages, system_content, tools=None)
        return self._response_to_text(final_response)

    def _call_claude(self, messages: List[Dict[str, Any]], system_content: str, tools: Optional[List]):
        api_params = {
            **self.base_params,
            "messages": messages,
            "system": system_content
        }
        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = {"type": "auto"}
        return self._get_response(api_params)

    def _get_response(self, api_params: Dict[str, Any], max_attempts: int = 2):
        """
        Calls the API, retrying up to max_attempts on blank end_turn text.
        A tool_use response is returned immediately, never retried.

        Occasionally Claude ends its turn after internal reasoning without
        emitting any visible text (an empty "text" content block) - retry a
        couple of times before falling back to a clear message instead of
        returning blank text.
        """
        response = None
        for _ in range(max_attempts):
            response = self.client.messages.create(**api_params)
            if response.stop_reason == "tool_use":
                return response
            if self._extract_text(response).strip():
                return response
        return response

    def _execute_tool_round(self, content_blocks, tool_manager):
        """
        Executes every tool_use block in one response.

        An exception raised out of tool_manager.execute_tool is treated as a
        hard failure (distinct from a tool returning a normal error string,
        e.g. CourseSearchTool already catches its own errors into strings
        like "Search error: ..." or "No course found matching...", which are
        ordinary results Claude should reason about, not failures). Every
        tool_use id still gets a matching tool_result (an API requirement),
        flagged is_error on hard failure, and the caller is told to stop
        issuing further rounds.

        Returns:
            Tuple of (tool_result content blocks, hard_failure: bool)
        """
        tool_results = []
        hard_failure = False
        for content_block in content_blocks:
            if content_block.type != "tool_use":
                continue
            try:
                result_text = tool_manager.execute_tool(
                    content_block.name,
                    **content_block.input
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": content_block.id,
                    "content": result_text
                })
            except Exception as exc:
                hard_failure = True
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": content_block.id,
                    "content": f"Tool execution failed: {exc}",
                    "is_error": True
                })
        return tool_results, hard_failure

    def _response_to_text(self, response) -> str:
        text = self._extract_text(response)
        return text if text.strip() else "I wasn't able to generate a response for that question — please try asking again."

    def _extract_text(self, response) -> str:
        """Get the text content from a response, skipping thinking/tool_use blocks."""
        return next((block.text for block in response.content if block.type == "text"), "")
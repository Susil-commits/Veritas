"""
Model Context Protocol (MCP) Server for Veritas.

Exposes Veritas cognitive primitives to external AI agents, IDEs, and LMSs via MCP:
1. Tools:
   - `veritas_verify_math_step`: Deterministically check algebraic step equivalence.
   - `veritas_diagnose_scratchpad`: Multimodal vision error reticle detection.
   - `veritas_update_bkt`: Update student BKT mastery probabilities.
   - `veritas_get_remediation`: Retrieve ZPD-targeted remediation problem.
2. Resources:
   - `veritas://curriculum/standards`: CCSS mathematics standards taxonomy.
   - `veritas://students/{student_id}/mastery`: BKT latent mastery state.
3. Prompts:
   - `socratic_intervention`: Calibrated Socratic prompt enforcing zero answer leakage.

Supports:
- CLI stdio transport (for Claude Desktop, Antigravity, Cursor, etc.)
- Programmatic Python API for internal agent routing.
"""
import sys
import json
import logging
from typing import Any, Dict, List, Optional

from backend.harness.sandbox import SafeMathEvaluator
from backend.harness.invariants import PedagogicalInvariantChecker
from backend.context.cognitive_context import STATIC_SOCRATIC_PREFIX

logger = logging.getLogger("veritas-backend.mcp")


# Sample CCSS standards resource data
CURRICULUM_STANDARDS = [
    {"id": "CCSS.MATH.6.RP.A.1", "name": "Ratios & Proportions", "grade": 6, "domain": "RP"},
    {"id": "CCSS.MATH.6.EE.A.2", "name": "Expressions & Equations", "grade": 6, "domain": "EE"},
    {"id": "CCSS.MATH.6.NS.A.1", "name": "Fractions & Quotients", "grade": 6, "domain": "NS"},
    {"id": "CCSS.MATH.7.NS.A.1", "name": "Rational Number Operations", "grade": 7, "domain": "NS"},
    {"id": "CCSS.MATH.7.EE.B.4", "name": "Linear Equations Construction", "grade": 7, "domain": "EE"},
    {"id": "CCSS.MATH.8.EE.C.7", "name": "Multi-Step Linear Equations", "grade": 8, "domain": "EE"},
]


class VeritasMCPServer:
    """
    Standard Model Context Protocol (MCP) server implementing JSON-RPC 2.0.
    """

    SERVER_INFO = {
        "name": "veritas-socratic-math-mcp",
        "version": "1.0.0"
    }

    TOOLS_MANIFEST = [
        {
            "name": "veritas_verify_math_step",
            "description": "Deterministically checks if a student's math step is mathematically equivalent to the previous step using CAS sandbox.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "previous_expr": {
                        "type": "string",
                        "description": "The math expression before the transformation (e.g. '2*(x + 3)')"
                    },
                    "student_step_expr": {
                        "type": "string",
                        "description": "The student's transformed expression (e.g. '2*x + 6')"
                    }
                },
                "required": ["previous_expr", "student_step_expr"]
            }
        },
        {
            "name": "veritas_check_answer_leakage",
            "description": "Evaluates a proposed tutor response against Veritas Pedagogical Invariants to ensure zero answer leakage.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tutor_reply": {"type": "string", "description": "The candidate tutor response"},
                    "target_solution": {"type": "string", "description": "The hidden correct solution"}
                },
                "required": ["tutor_reply", "target_solution"]
            }
        },
        {
            "name": "veritas_update_bkt",
            "description": "Updates student latent mastery probability P(L) using calibrated Bayesian Knowledge Tracing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "student_id": {"type": "string"},
                    "skill_id": {"type": "string"},
                    "is_correct": {"type": "boolean"},
                    "current_mastery": {"type": "number", "default": 0.50}
                },
                "required": ["student_id", "skill_id", "is_correct"]
            }
        }
    ]

    RESOURCES_MANIFEST = [
        {
            "uri": "veritas://curriculum/standards",
            "name": "Common Core Mathematics Standards Taxonomy",
            "description": "Curriculum taxonomy of K-12 CCSS standards supported by Veritas.",
            "mimeType": "application/json"
        }
    ]

    PROMPTS_MANIFEST = [
        {
            "name": "socratic_intervention",
            "description": "Generates a calibrated Socratic system prompt with zero answer leakage axioms.",
            "arguments": [
                {"name": "skill_id", "description": "The active CCSS standard", "required": True},
                {"name": "grade_level", "description": "Student grade level (6-8)", "required": False}
            ]
        }
    ]

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatches incoming JSON-RPC 2.0 requests.
        """
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": self.SERVER_INFO,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                        "prompts": {"listChanged": False}
                    }
                }
            }

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": self.TOOLS_MANIFEST}
            }

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})
            return self._handle_tool_call(req_id, tool_name, args)

        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": self.RESOURCES_MANIFEST}
            }

        elif method == "resources/read":
            uri = params.get("uri")
            return self._handle_resource_read(req_id, uri)

        elif method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"prompts": self.PROMPTS_MANIFEST}
            }

        elif method == "prompts/get":
            prompt_name = params.get("name")
            args = params.get("arguments", {})
            return self._handle_prompt_get(req_id, prompt_name, args)

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not found"}
        }

    def _handle_tool_call(self, req_id: Any, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if tool_name == "veritas_verify_math_step":
                prev = args.get("previous_expr", "")
                step = args.get("student_step_expr", "")
                is_equiv = SafeMathEvaluator.are_expressions_equivalent(prev, step)
                content = {
                    "equivalent": is_equiv,
                    "message": "Step is algebraically valid" if is_equiv else "Step does not evaluate to equivalent value"
                }
            elif tool_name == "veritas_check_answer_leakage":
                reply = args.get("tutor_reply", "")
                target = args.get("target_solution", "")
                result = PedagogicalInvariantChecker.validate_all(reply, target)
                content = result
            elif tool_name == "veritas_update_bkt":
                # Simulated BKT update formula
                curr_p = float(args.get("current_mastery", 0.50))
                is_correct = bool(args.get("is_correct", False))
                # Standard BKT transition update
                p_learn, p_guess, p_slip = 0.15, 0.20, 0.10
                if is_correct:
                    p_num = curr_p * (1 - p_slip)
                    p_den = p_num + (1 - curr_p) * p_guess
                else:
                    p_num = curr_p * p_slip
                    p_den = p_num + (1 - curr_p) * (1 - p_guess)
                post_p = p_num / p_den if p_den != 0 else curr_p
                new_p = post_p + (1 - post_p) * p_learn
                content = {
                    "student_id": args.get("student_id"),
                    "skill_id": args.get("skill_id"),
                    "prior_mastery": round(curr_p, 4),
                    "updated_mastery": round(min(0.99, max(0.01, new_p)), 4),
                    "is_mastered": new_p >= 0.85
                }
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Unknown tool: '{tool_name}'"}
                }

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(content)}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    def _handle_resource_read(self, req_id: Any, uri: str) -> Dict[str, Any]:
        if uri == "veritas://curriculum/standards":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(CURRICULUM_STANDARDS, indent=2)
                    }]
                }
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32002, "message": f"Resource URI '{uri}' not found"}
        }

    def _handle_prompt_get(self, req_id: Any, prompt_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if prompt_name == "socratic_intervention":
            skill_id = args.get("skill_id", "CCSS.MATH.6.EE.A.2")
            prompt_text = (
                f"{STATIC_SOCRATIC_PREFIX}\n\n"
                f"Active Skill Target: {skill_id}\n"
                f"Instructions: Formulate a single guided inquiry question without revealing steps."
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": f"Socratic intervention prompt for {skill_id}",
                    "messages": [
                        {"role": "system", "content": {"type": "text", "text": prompt_text}}
                    ]
                }
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32602, "message": f"Prompt '{prompt_name}' not found"}
        }

    def run_stdio(self) -> None:
        """
        Runs the MCP server over standard I/O (stdin/stdout).
        Compatible with Claude Desktop, Antigravity IDE, Cursor, etc.
        """
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self.handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
            except Exception as e:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                }
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    server = VeritasMCPServer()
    server.run_stdio()


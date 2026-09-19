"""Audit engine for evaluating contracts against standards using Google Gemini."""

import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types

from src.audit.schemas import ContractAuditReport

# Load local .env variables into os.environ
load_dotenv()


class ContractAuditor:
    """Orchestrates structured compliance audits using Gemini."""

    def __init__(
            self,
            rubric_path: str | Path = "config/audit_rubric.yaml",
            model_name: str | None = None,
        ):
            """Initialize the auditor with a declarative rubric and Gemini client."""
            rubric_file = Path(rubric_path)
            if not rubric_file.exists():
                raise FileNotFoundError(f"Rubric configuration not found at: {rubric_file}")

            with open(rubric_file, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            self.rubric = config_data["rubric"]
            engine_cfg = config_data.get("engine", {})

            # Resolution hierarchy: explicit argument -> env var -> config file -> fallback
            self.model_name = (
                model_name
                or os.environ.get("GEMINI_MODEL")
                or engine_cfg.get("model_name", "gemini-flash-latest")
            )
            self.temperature = float(engine_cfg.get("temperature", 0.0))

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                raise ValueError(
                    "GEMINI_API_KEY not found in environment or .env file. "
                    "Please configure GEMINI_API_KEY before executing inference."
                )

            self.client = genai.Client(api_key=api_key)

    def _build_system_instruction(self) -> str:
        """Construct the compliance persona and evaluation guardrails."""
        return (
            "You are an expert enterprise legal compliance auditor and procurement specialist.\n"
            "Your objective is to strictly evaluate the submitted contract against the provided "
            "policy rubric checklist.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Grounding: Audit strictly against the facts and clauses in the provided contract. "
            "Do not extrapolate or assume unstated terms.\n"
            "2. Status Determination:\n"
            "   - 'MET': The contract clause strictly satisfies the policy standard or acceptable fallback.\n"
            "   - 'DEVIATION': The contract addresses the topic but falls short of policy thresholds.\n"
            "   - 'SILENT': The contract completely omits the required clause or topic.\n"
            "3. Grounded Citations: For each item, you must provide the exact section number and "
            "a verbatim excerpt under 'exact_citation'. If the topic is missing, you must set "
            "exact_citation to 'Not Found / Silent'.\n"
            "4. Schema Integrity: Ensure compliant_count + deviation_count + silent_count "
            "strictly equals total_items_audited."
        )

    def audit_contract(
        self,
        contract_text: str,
        contract_title: str,
        vendor_name: str,
    ) -> ContractAuditReport:
        """Run the compliance audit and return a validated Pydantic report."""
        user_prompt = f"""
### COMPLIANCE AUDIT RUBRIC (10 MANDATORY ITEMS):
{json.dumps(self.rubric, indent=2)}

### INBOUND VENDOR CONTRACT TEXT:
Contract Title: {contract_title}
Vendor: {vendor_name}

{contract_text}

---
Perform the compliance evaluation for all 10 items in the rubric.
Generate the complete audit assessment conforming strictly to the requested schema.
"""

        # Enforce structured output via Gemini's native Pydantic schema configuration
        config = types.GenerateContentConfig(
            system_instruction=self._build_system_instruction(),
            temperature=self.temperature,
            response_mime_type="application/json",
            response_schema=ContractAuditReport,
        )

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[user_prompt],
            config=config,
        )

        # Parse and validate the response against the Pydantic model
        return ContractAuditReport.model_validate_json(response.text)
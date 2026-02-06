"""
Multi-Agent System for reading and analyzing PDF Books.
Implements a 3-step pipeline:
1. Splitter: Divides book into chapters/sections.
2. Dispatcher: Analyzes context to assign domain experts.
3. Specialists: Team of agents (Math, Stat, Econ, Geo, Finance) analyzing specific aspects.
"""

import json
from dataclasses import dataclass
from typing import Dict, List, Optional

import pypdf

from .ai_provider import AIProvider


# --- DATA STRUCTURES ---
@dataclass
class Chapter:
    id: int
    title: str
    content: str
    page_start: int
    page_end: int


@dataclass
class AnalysisResult:
    chapter_title: str
    active_agents: List[str]
    insights: Dict[str, str]


# --- AGENTS ---


class ChapterSplitter:
    """
    Agent 1 (Logic-based): Divides the PDF into manageble chapters/sections.
    Currently uses page-chunking as a robust fallback for missing PDF outlines.
    """

    def split(self, pdf_file, chunk_size: int = 20) -> List[Chapter]:
        try:
            reader = pypdf.PdfReader(pdf_file)
            chapters = []
            total_pages = len(reader.pages)

            # Simple Page Chunking Strategy
            # (In a V2, this could use LLM to detect TOC and split by real chapters)
            for i in range(0, total_pages, chunk_size):
                end_page = min(i + chunk_size, total_pages)
                chunk_text = ""
                for p in range(i, end_page):
                    extracted = reader.pages[p].extract_text()
                    if extracted:
                        chunk_text += extracted + "\n"

                if chunk_text.strip():
                    chapters.append(
                        Chapter(
                            id=len(chapters) + 1,
                            title=f"Section (Pages {i+1}-{end_page})",
                            content=chunk_text,
                            page_start=i + 1,
                            page_end=end_page,
                        )
                    )

            return chapters
        except Exception as e:
            return [
                Chapter(
                    id=0,
                    title="Error",
                    content=f"Read Error: {e}",
                    page_start=0,
                    page_end=0,
                )
            ]


class DispatcherAgent:
    """
    Agent 2: context understanding and task distribution.
    Decides which Specialist Agents are needed for a given chapter.
    """

    def __init__(self, ai_provider: AIProvider):
        self.model = ai_provider.get_model(json_mode=True)

    def dispatch(self, text_sample: str) -> List[str]:
        prompt = f"""
        ROLE: Chief Editor & Task Dispatcher.
        CONTEXT: Analyzing a Finance/Technical Book chapter.
        AVAILABLE AGENTS:
        - "Finance": General financial concepts, markets, investing.
        - "Math": Equations, formulas, calculus, algebra.
        - "Statistic": Probability, distributions, regression, data analysis.
        - "Economy": Macro/Micro economics, inflation, GDP, policy.
        - "Geopolitical": Country risks, wars, regulations, global relations.
        
        TASK: Read the text sample and decide which agents should analyze it.
        - Always include "Finance" if relevant to investing.
        - Include "Math" only if explicit formulas/equations appear.
        - Include "Geopolitical" only if specific countries/policies are discussed.
        
        OUTPUT: JSON only.
        {{ "agents": ["Finance", "Math"] }}
        
        TEXT SAMPLE:
        {text_sample[:4000]}
        """
        try:
            # Call AI
            resp = self.model.generate_content(prompt)
            content = resp.text if hasattr(resp, "text") else str(resp)

            # Parse JSON
            # Cleanup markdown code blocks if present
            clean_json = content.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)

            return [
                a
                for a in data.get("agents", [])
                if a in ["Finance", "Math", "Statistic", "Economy", "Geopolitical"]
            ]
        except Exception:
            # Fallback
            return ["Finance"]


class SpecialistAgent:
    """Base class for Agent 3 Team."""

    def __init__(self, ai_provider: AIProvider):
        self.model = ai_provider.get_model(json_mode=False)
        self.domain = "General"

    def analyze(self, text: str) -> str:
        prompt = self._build_prompt(text)
        try:
            resp = self.model.generate_content(prompt)
            return resp.text if hasattr(resp, "text") else str(resp)
        except Exception as e:
            return f"Error in analysis: {e}"

    def _build_prompt(self, text: str) -> str:
        raise NotImplementedError


class MathAgent(SpecialistAgent):
    def _build_prompt(self, text):
        return f"""
        TASK: Extract and explain KEY MATHEMATICAL EQUATIONS.
        DOMAIN: Mathematics.
        FORMAT: Markdown (Use LaTeX $$..$$ for math).
        
        INSTRUCTIONS:
        1. List significant formulas found.
        2. Define user-friendly variables.
        3. Explain the application.
        
        TEXT:
        {text[:50000]}
        """


class StatisticAgent(SpecialistAgent):
    def _build_prompt(self, text):
        return f"""
        TASK: Extract STATISTICAL concepts, models, and data methods.
        DOMAIN: Statistics.
        
        INSTRUCTIONS:
        1. Identify distributions, regressions, p-values, or correlation metrics.
        2. Explain how they are used in the context.
        
        TEXT:
        {text[:50000]}
        """


class EconomyAgent(SpecialistAgent):
    def _build_prompt(self, text):
        return f"""
        TASK: Analyze ECONOMIC factors.
        DOMAIN: Macro/Micro Economics.
        
        INSTRUCTIONS:
        1. Highlight inflation, rates, GDP, supply/demand logic.
        2. Summarize economic theories mentioned.
        
        TEXT:
        {text[:50000]}
        """


class GeopoliticalAgent(SpecialistAgent):
    def _build_prompt(self, text):
        return f"""
        TASK: Analyze GEOPOLITICAL risks and context.
        DOMAIN: Geopolitics.
        
        INSTRUCTIONS:
        1. Identify countries, regulations, trade wars, or political risks.
        2. Assess impact on markets described.
        
        TEXT:
        {text[:50000]}
        """


class FinanceAgent(SpecialistAgent):
    def _build_prompt(self, text):
        return f"""
        TASK: Summarize FINANCIAL concepts and investment strategy.
        DOMAIN: Finance.
        
        INSTRUCTIONS:
        1. Key metrics, valuation methods, or investing principles.
        2. Brief summary of the section's financial argument.
        
        TEXT:
        {text[:50000]}
        """


# --- ORCHESTRATOR ---


class BookAnalyst:
    """Main entry point for Book Analysis."""

    def __init__(
        self, api_key: Optional[str] = None, provider: str = "gemini", model: str = ""
    ):
        self.provider = AIProvider(
            api_key=api_key, provider_type=provider, model_name=model
        )

        self.splitter = ChapterSplitter()
        self.dispatcher = DispatcherAgent(self.provider)

        # Team Registry
        self.specialists = {
            "Math": MathAgent(self.provider),
            "Statistic": StatisticAgent(self.provider),
            "Economy": EconomyAgent(self.provider),
            "Geopolitical": GeopoliticalAgent(self.provider),
            "Finance": FinanceAgent(self.provider),
        }

    def analyze_book_stream(self, pdf_file, callback=None):
        """
        Generator that yields results chapter by chapter.
        This allows streaming update in the UI.
        """
        # 1. Split
        if callback:
            callback("📄 Phase 1: Splitting Document into Sections...")
        chapters = self.splitter.split(pdf_file)
        if not chapters:
            yield "❌ Failed to read PDF."
            return

        total_chaps = len(chapters)

        # 2. Iterate
        full_report = "# 📚 Comprehensive Book Analysis\n\n"

        for idx, chapter in enumerate(chapters):
            prog = f"[{idx+1}/{total_chaps}]"
            if callback:
                callback(f"🧠 Phase 2: Analyzing {chapter.title} {prog}...")

            # 3. Dispatch
            agents_needed = self.dispatcher.dispatch(chapter.content)

            section_report = f"## {chapter.title}\n"
            section_report += f"**Active Agents**: {', '.join(agents_needed)}\n\n"

            # 4. Execute Specialists
            for agent_name in agents_needed:
                if agent_name in self.specialists:
                    if callback:
                        callback(f"   ↳ 🕵️ {agent_name} Agent working...")
                    agent = self.specialists[agent_name]
                    result = agent.analyze(chapter.content)

                    section_report += f"### 🕵️ {agent_name} Report\n"
                    section_report += f"{result}\n\n"

            section_report += "---\n\n"
            full_report += section_report
            yield section_report  # Yield partial result

        # return full_report

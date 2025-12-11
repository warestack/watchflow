"""
Repository Analysis Agent for generating Watchflow rule recommendations.

This agent analyzes repository structure, contributing guidelines, and patterns
to automatically propose appropriate Watchflow rules with confidence scores.
"""

from src.agents.repository_analysis_agent.agent import RepositoryAnalysisAgent

__all__ = ["RepositoryAnalysisAgent"]

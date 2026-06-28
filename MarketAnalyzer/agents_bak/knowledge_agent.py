"""Knowledge agent — reads SKILL.md files live from the opencode skills filesystem.

No RAG, no embeddings. Direct filesystem access to all 40+ skills.
Supports category filtering and content searching.
"""

import os
import re
from pathlib import Path
from typing import Optional


SKILLS_DIR = Path.home() / '.config' / 'opencode' / 'skills'

CATEGORIES = {
    'wyckoff': ['wyckoff-2-0'],
    'volume_profile': ['volume-profile'],
    'price_action': ['price-action-volman', 'trades-about-to-happen'],
    'sentiment': ['trading-against-the-crowd'],
    'options': ['options-playbook', 'options-course-workbook', 'options-crash-course', 'options-strategy-suggestions'],
    'crypto': ['crypto-technical-analysis', 'crypto-crash-course'],
    'fundamentals': ['market-data-fetch'],
    'analysis': ['stock-crypto-analysis', 'market-accumulation-scanner'],
    'trading': ['wallstreetbets-pump-detect'],
    'nutrition': ['liotta-smartfood'],
    'tax': ['italy-tax-declaration-instructions'],
}


class KnowledgeAgent:
    """Reads opencode skills knowledge from ~/.config/opencode/skills/."""

    def list_skills(self) -> list[dict]:
        """Return all available skills with metadata."""
        if not SKILLS_DIR.exists():
            return []
        skills = []
        for d in sorted(SKILLS_DIR.iterdir()):
            if d.is_dir():
                meta = self._read_meta(d)
                skills.append({'name': d.name, 'path': str(d), 'title': meta.get('title', d.name)})
        return skills

    def read_skill(self, skill_name: str, file_name: str = 'SKILL.md') -> Optional[str]:
        """Read a specific file from a skill directory."""
        path = SKILLS_DIR / skill_name / file_name
        if not path.exists():
            return None
        try:
            return path.read_text(encoding='utf-8')
        except Exception:
            return None

    def list_files(self, skill_name: str) -> list[str]:
        """List files in a skill directory."""
        path = SKILLS_DIR / skill_name
        if not path.exists():
            return []
        try:
            return sorted(f.name for f in path.iterdir() if f.is_file() and not f.name.startswith('.'))
        except Exception:
            return []

    def search_skills(self, query: str, category: Optional[str] = None) -> list[dict]:
        """Search across all skills for a query string."""
        results = []
        skill_names = CATEGORIES.get(category, []) if category else [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()]
        for skill in skill_names:
            for fname in ['SKILL.md', 'patterns.md', 'cheatsheet.md']:
                content = self.read_skill(skill, fname)
                if not content:
                    continue
                matches = []
                for i, line in enumerate(content.split('\n'), 1):
                    if query.lower() in line.lower():
                        matches.append({'line': i, 'text': line.strip()[:200]})
                if matches:
                    results.append({'skill': skill, 'file': fname, 'matches': matches[:10]})
        return results

    def get_strategies(self, skill_name: str) -> list[dict]:
        """Extract strategy definitions from a skill's SKILL.md."""
        content = self.read_skill(skill_name)
        if not content:
            return []

        strategies = []
        lines = content.split('\n')
        in_table = False
        headers = []
        table_rows = []

        for line in lines:
            if line.startswith('| ') and '---' not in line:
                if not in_table:
                    headers = [h.strip() for h in line.strip('| ').split('|')]
                    in_table = True
                else:
                    cells = [c.strip() for c in line.strip('| ').split('|')]
                    if len(cells) == len(headers):
                        table_rows.append(dict(zip(headers, cells)))
            elif line.startswith('|') and '---' in line:
                continue
            elif line.strip().startswith('- **') and '**:' in line:
                name_end = line.find('**:')
                name = line.strip('- **').split('**:')[0].strip('*')
                desc = line.split('**:', 1)[1].strip()
                strategies.append({'name': name, 'description': desc, 'source': skill_name})

        for row in table_rows:
            strategies.append({'name': row.get('Strategy', row.get('Name', '')),
                               'description': row.get('Description', row.get('When to Use', '')),
                               'details': row, 'source': skill_name})

        return strategies

    def query(self, query: str, category: Optional[str] = None) -> str:
        """Natural language query across skills — returns concatenated relevant content."""
        parts = []
        skill_names = CATEGORIES.get(category, []) if category else [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()]
        for skill in skill_names[:5]:
            content = self.read_skill(skill)
            if not content:
                continue
            lines = content.split('\n')
            relevant = []
            q_words = query.lower().split()
            for line in lines[:200]:
                if any(w in line.lower() for w in q_words):
                    relevant.append(line.strip())
            if relevant:
                parts.append(f"--- {skill} ---\n" + '\n'.join(relevant[:20]))
        return '\n\n'.join(parts[:5])

    def get_categories(self) -> dict:
        """Return the predefined category → skills mapping."""
        return dict(CATEGORIES)

    # ── Private ───────────────────────────────────────────────
    @staticmethod
    def _read_meta(skill_path: Path) -> dict:
        meta = {}
        skill_file = skill_path / 'SKILL.md'
        if skill_file.exists():
            try:
                content = skill_file.read_text(encoding='utf-8', errors='replace')
                m = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                if m:
                    meta['title'] = m.group(1).strip()
            except Exception:
                pass
        return meta

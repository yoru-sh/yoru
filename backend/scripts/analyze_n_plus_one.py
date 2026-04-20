#!/usr/bin/env python3
"""
Analyze Python service files for N+1 query patterns.

Usage:
    python scripts/analyze_n_plus_one.py template/apps/api/api/services/
"""

import ast
import argparse
from pathlib import Path
from typing import List, Dict

class NPlusOneDetector(ast.NodeVisitor):
    """AST visitor to detect N+1 patterns."""

    def __init__(self):
        self.issues: List[Dict] = []
        self.in_loop = False
        self.loop_line = 0

    def visit_For(self, node):
        """Track for loops."""
        self.in_loop = True
        self.loop_line = node.lineno
        self.generic_visit(node)
        self.in_loop = False

    def visit_AsyncFor(self, node):
        """Track async for loops."""
        self.in_loop = True
        self.loop_line = node.lineno
        self.generic_visit(node)
        self.in_loop = False

    def visit_Call(self, node):
        """Detect queries inside loops."""
        if self.in_loop:
            # Check for common query patterns
            if isinstance(node.func, ast.Attribute):
                method_name = node.func.attr

                # Supabase query methods
                if method_name in ['get_record', 'query_records', 'execute_rpc', 'select', 'insert', 'update']:
                    self.issues.append({
                        'line': node.lineno,
                        'loop_line': self.loop_line,
                        'method': method_name,
                        'severity': 'HIGH'
                    })

        self.generic_visit(node)

def analyze_file(filepath: Path) -> List[Dict]:
    """Analyze a Python file for N+1 patterns."""
    try:
        content = filepath.read_text()
        tree = ast.parse(content)

        detector = NPlusOneDetector()
        detector.visit(tree)

        return detector.issues
    except Exception as e:
        print(f"⚠️  Error analyzing {filepath}: {e}")
        return []

def analyze_directory(directory: Path):
    """Analyze all Python files in directory."""

    total_issues = 0

    for filepath in directory.rglob("*.py"):
        if "test" in str(filepath):
            continue  # Skip test files

        issues = analyze_file(filepath)

        if issues:
            print(f"\n📁 {filepath.relative_to(directory.parent.parent)}")
            for issue in issues:
                print(f"   ⚠️  Line {issue['line']}: {issue['method']}() called inside loop (line {issue['loop_line']})")
                print(f"      Severity: {issue['severity']}")
                total_issues += 1

    if total_issues == 0:
        print("✅ No N+1 patterns detected!")
    else:
        print(f"\n⚠️  Found {total_issues} potential N+1 query patterns")
        print("\n💡 Consider:")
        print("   1. Creating a database view with JOIN")
        print("   2. Batch fetching with IN clause")
        print("   3. Using eager loading (if ORM)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detect N+1 query patterns")
    parser.add_argument("directory", type=Path, help="Directory to analyze")

    args = parser.parse_args()

    if not args.directory.exists():
        print(f"❌ Directory not found: {args.directory}")
        exit(1)

    analyze_directory(args.directory)

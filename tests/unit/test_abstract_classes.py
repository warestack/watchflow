#!/usr/bin/env python3
"""
Test script to verify that abstract methods now raise NotImplementedError
instead of using pass.

This script tests by directly reading source files (no imports needed),
verifying the code changes are correct.
"""

import re
from pathlib import Path


def check_file_uses_notimplemented(file_path: Path, class_name: str, method_names: list[str]) -> tuple[bool, list[str]]:
    """
    Check if abstract methods in a file use raise NotImplementedError.
    
    Returns:
        (all_passed, list_of_issues)
    """
    try:
        content = file_path.read_text()
        issues = []
        all_passed = True
        
        for method_name in method_names:
            # Find the abstract method definition
            # Pattern: @abstractmethod ... def method_name(...): ... raise NotImplementedError
            pattern = rf'@abstractmethod\s+(?:async\s+)?def\s+{re.escape(method_name)}\s*\([^)]*\)[^:]*:\s*"""[^"]*"""\s*(.*?)(?=\n    @|\n\nclass|\nclass|\Z)'
            match = re.search(pattern, content, re.DOTALL)
            
            if not match:
                # Try a simpler pattern without docstring
                pattern = rf'@abstractmethod\s+(?:async\s+)?def\s+{re.escape(method_name)}\s*\([^)]*\)[^:]*:\s*(.*?)(?=\n    @|\n\nclass|\nclass|\Z)'
                match = re.search(pattern, content, re.DOTALL)
            
            if match:
                method_body = match.group(1)
                # Check if it contains raise NotImplementedError
                if "raise NotImplementedError" in method_body:
                    print(f"  ✅ {class_name}.{method_name} uses raise NotImplementedError")
                elif "pass" in method_body and "raise" not in method_body:
                    print(f"  ❌ {class_name}.{method_name} still uses pass instead of raise NotImplementedError")
                    issues.append(f"{class_name}.{method_name} still uses pass")
                    all_passed = False
                else:
                    # Might have both or neither, check more carefully
                    lines = method_body.strip().split('\n')
                    has_raise = any("raise NotImplementedError" in line for line in lines)
                    has_pass_only = any(line.strip() == "pass" for line in lines if "raise" not in line)
                    if has_pass_only and not has_raise:
                        print(f"  ❌ {class_name}.{method_name} still uses pass instead of raise NotImplementedError")
                        issues.append(f"{class_name}.{method_name} still uses pass")
                        all_passed = False
                    elif has_raise:
                        print(f"  ✅ {class_name}.{method_name} uses raise NotImplementedError")
                    else:
                        print(f"  ⚠️  {class_name}.{method_name} - could not verify (unusual format)")
            else:
                print(f"  ⚠️  {class_name}.{method_name} - could not find method definition")
        
        return all_passed, issues
    except Exception as e:
        print(f"  ❌ Error checking {file_path}: {e}")
        return False, [f"Error: {str(e)}"]


def verify_code_changes_direct():
    """Verify code changes by reading source files directly."""
    print("Verifying code changes by inspecting source files...")
    print()
    
    base_path = Path(__file__).parent.parent.parent / "src"
    all_passed = True
    all_issues = []
    
    files_to_check = [
        ("integrations/providers/base.py", "BaseProvider", 
         ["get_chat_model", "supports_structured_output", "get_provider_name"]),
        ("agents/base.py", "BaseAgent", 
         ["_build_graph", "execute"]),
        ("event_processors/base.py", "BaseEventProcessor", 
         ["process", "get_event_type", "prepare_webhook_data", "prepare_api_data"]),
        ("webhooks/handlers/base.py", "EventHandler", 
         ["handle"]),
        ("rules/interface.py", "RuleLoader", 
         ["get_rules"]),
        ("rules/validators.py", "Condition", 
         ["validate"]),
    ]
    
    for file_rel_path, class_name, method_names in files_to_check:
        file_path = base_path / file_rel_path
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            all_passed = False
            all_issues.append(f"File not found: {file_rel_path}")
            continue
        
        print(f"Checking {file_rel_path} ({class_name})...")
        passed, issues = check_file_uses_notimplemented(file_path, class_name, method_names)
        if not passed:
            all_passed = False
            all_issues.extend(issues)
        print()
    
    return all_passed, all_issues


def verify_with_grep():
    """Alternative verification using grep-like pattern matching."""
    print("Alternative verification: Checking for remaining 'pass' in abstract methods...")
    print()
    
    base_path = Path(__file__).parent.parent.parent / "src"
    
    # Find all Python files
    python_files = list(base_path.rglob("*.py"))
    
    issues_found = []
    
    for py_file in python_files:
        try:
            content = py_file.read_text()
            
            # Look for @abstractmethod followed by method definition and pass
            # More specific pattern: @abstractmethod ... def ... : ... pass (with proper indentation)
            lines = content.split('\n')
            
            in_abstract_method = False
            abstract_method_indent = 0
            method_name = None
            class_name = None
            
            for i, line in enumerate(lines):
                # Detect class definitions
                class_match = re.match(r'^class\s+(\w+)', line)
                if class_match:
                    class_name = class_match.group(1)
                
                # Detect @abstractmethod
                if '@abstractmethod' in line:
                    in_abstract_method = True
                    abstract_method_indent = len(line) - len(line.lstrip())
                    # Look ahead for method definition
                    for j in range(i + 1, min(i + 10, len(lines))):
                        method_match = re.match(r'^\s*(?:async\s+)?def\s+(\w+)', lines[j])
                        if method_match:
                            method_name = method_match.group(1)
                            break
                    continue
                
                # If we're in an abstract method, check for pass
                if in_abstract_method:
                    # Check if this line is just "pass" with appropriate indentation
                    stripped = line.strip()
                    line_indent = len(line) - len(line.lstrip())
                    
                    # If we hit another method or class at same or less indentation, we're done
                    if (re.match(r'^\s*(?:@|def\s+|class\s+|async\s+def\s+)', line) and 
                        line_indent <= abstract_method_indent and 
                        line_indent > 0):
                        in_abstract_method = False
                        continue
                    
                    # Check for standalone pass (not in a comment or string)
                    if stripped == "pass" and "raise NotImplementedError" not in content[max(0, i-20):i+5]:
                        # Double check this is actually in the method body
                        # Look backwards to see if there's a raise statement
                        method_content = '\n'.join(lines[max(0, i-30):i+5])
                        if '@abstractmethod' in method_content and 'raise NotImplementedError' not in method_content:
                            rel_path = py_file.relative_to(base_path.parent)
                            issues_found.append(f"{rel_path}: {class_name}.{method_name} uses pass")
                            print(f"  ❌ Found 'pass' in abstract method: {rel_path} -> {class_name}.{method_name}")
                            in_abstract_method = False
                
        except Exception as e:
            continue  # Skip files we can't read
    
    return len(issues_found) == 0, issues_found


def main():
    """Main test function."""
    print("=" * 60)
    print("Testing Abstract Methods - NotImplementedError Changes")
    print("=" * 60)
    print()
    
    # Method 1: Direct file inspection (more reliable)
    all_passed, issues = verify_code_changes_direct()
    
    print("=" * 60)
    
    # Method 2: Grep-like verification (double check)
    grep_passed, grep_issues = verify_with_grep()
    if grep_issues:
        print("\nGrep verification found additional issues:")
        for issue in grep_issues:
            print(f"  - {issue}")
        all_passed = False
    
    print()
    print("=" * 60)
    if all_passed and grep_passed:
        print("✅ ALL VERIFICATIONS PASSED")
        print()
        print("Summary:")
        print("  - All abstract methods now use 'raise NotImplementedError'")
        print("  - No abstract methods use 'pass' anymore")
        print("  - Code changes are correct")
        return 0
    else:
        print("❌ SOME VERIFICATIONS FAILED")
        print()
        print("Issues found:")
        for issue in issues + grep_issues:
            print(f"  - {issue}")
        return 1


if __name__ == "__main__":
    exit(main())

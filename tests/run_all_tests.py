#!/usr/bin/env python
"""
Test harness to run all tests in the tests folder.

Usage:
    python tests/run_all_tests.py              # Run all tests
    python tests/run_all_tests.py -v           # Verbose output
    python tests/run_all_tests.py --fast       # Skip slow tests
    python tests/run_all_tests.py --failed     # Only re-run failed tests
"""

import sys
import subprocess
from pathlib import Path

def run_tests(args=None):
    """Run pytest with specified arguments."""
    if args is None:
        args = []
    
    # Base pytest command
    cmd = [sys.executable, "-m", "pytest", "tests/"]
    
    # Add user arguments
    cmd.extend(args)
    
    # Default to verbose if no verbosity specified
    if not any(arg in args for arg in ['-v', '-vv', '-q', '--quiet']):
        cmd.append('-v')
    
    # Show test summary
    if '--tb' not in ' '.join(args):
        cmd.append('--tb=short')
    
    print(f"Running: {' '.join(cmd)}")
    print("=" * 80)
    
    # Run pytest
    result = subprocess.run(cmd, cwd=Path(__file__).parent.parent)
    return result.returncode

def main():
    """Main entry point."""
    # Parse custom arguments
    args = sys.argv[1:]
    
    custom_args = []
    for arg in args:
        if arg == '--fast':
            custom_args.extend(['-m', 'not slow'])
        elif arg == '--failed':
            custom_args.append('--lf')  # last failed
        else:
            custom_args.append(arg)
    
    exit_code = run_tests(custom_args)
    
    # Summary
    print("\n" + "=" * 80)
    if exit_code == 0:
        print("✓ ALL TESTS PASSED")
    else:
        print(f"✗ TESTS FAILED (exit code: {exit_code})")
    print("=" * 80)
    
    sys.exit(exit_code)

if __name__ == "__main__":
    main()

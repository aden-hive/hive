"""Test runner for Contract Evaluation Agent."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Dict, List

from ..agent import default_agent


async def run_single_test(contract_path: Path, expected: Dict) -> Dict:
    """Run test on a single contract"""
   
    result = await default_agent.run({"contract_path": str(contract_path)})
    
    # Extract actual values
    metadata = result.get("metadata", {})
    risk = result.get("risk_assessment", {})
    confidentiality = result.get("confidentiality", {})
    
    # Compare with expected
    scores = {}
    
    # Contract type
    if metadata.get("contract_type") == expected.get("contract_type"):
        scores["contract_type"] = 1.0
    else:
        scores["contract_type"] = 0.0
    
    # Confidentiality type
    if confidentiality.get("type") == expected.get("confidentiality_type"):
        scores["confidentiality_type"] = 1.0
    else:
        scores["confidentiality_type"] = 0.0
    
    # Risk level (within 2 points)
    actual_risk = risk.get("overall_risk_score", 0)
    expected_risk = expected.get("risk_score", 0)
    if abs(actual_risk - expected_risk) <= 2.0:
        scores["risk_score"] = 1.0
    else:
        scores["risk_score"] = 0.0
    
    # Duration (exact match or null)
    if result.get("terms", {}).get("duration_months") == expected.get("duration_months"):
        scores["duration"] = 1.0
    else:
        scores["duration"] = 0.0
    
    return {
        "contract_id": contract_path.stem,
        "scores": scores,
        "actual": result,
        "expected": expected,
    }


async def run_all_tests(contracts_dir: Path, ground_truth_path: Path, verbose: bool = False):
    """Run all tests and print results."""
    
    # Load ground truth
    with open(ground_truth_path) as f:
        ground_truth = json.load(f)
    
    results = []
    
    # Run tests
    for contract_file in contracts_dir.glob("*.pdf"):
        contract_id = contract_file.stem
        expected = ground_truth.get(contract_id)
        
        if not expected:
            print(f"⚠️  No ground truth for {contract_id}, skipping")
            continue
        
        if verbose:
            print(f"Testing {contract_id}...")
        
        try:
            result = await run_single_test(contract_file, expected)
            results.append(result)
            
            if verbose:
                accuracy = sum(result["scores"].values()) / len(result["scores"]) * 100
                print(f"  Accuracy: {accuracy:.1f}%")
        
        except Exception as e:
            print(f"✗ Test failed for {contract_id}: {e}")
            results.append({
                "contract_id": contract_id,
                "error": str(e),
                "scores": {}
            })
    
    # Calculate aggregate metrics
    all_scores = {}
    for result in results:
        for metric, score in result.get("scores", {}).items():
            if metric not in all_scores:
                all_scores[metric] = []
            all_scores[metric].append(score)
    
    # Print summary
    print("\n" + "="*60)
    print("TEST RESULTS SUMMARY")
    print("="*60)
    
    for metric, scores in all_scores.items():
        accuracy = sum(scores) / len(scores) * 100 if scores else 0
        print(f"{metric:30s}: {accuracy:5.1f}% ({sum(scores):.0f}/{len(scores)})")
    
    overall = sum(s for scores in all_scores.values() for s in scores) / sum(len(scores) for scores in all_scores.values()) * 100
    print(f"\n{'Overall Accuracy':30s}: {overall:5.1f}%")
    print("="*60)
    
    # Save detailed results
    results_path = Path(__file__).parent / "test_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nDetailed results saved to {results_path}")
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Run Contract Evaluator tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--contracts-dir", default="contracts", help="Directory with test contracts")
    parser.add_argument("--ground-truth", default="ground_truth.json", help="Path to ground truth JSON")
    
    args = parser.parse_args()
    
    # Get paths
    test_dir = Path(__file__).parent
    contracts_dir = test_dir / args.contracts_dir
    ground_truth_path = test_dir / args.ground_truth
    
    if not contracts_dir.exists():
        print(f"✗ Contracts directory not found: {contracts_dir}")
        print("  Create test contracts in tests/contracts/")
        return 1
    
    if not ground_truth_path.exists():
        print(f"✗ Ground truth file not found: {ground_truth_path}")
        print("  Create ground_truth.json with expected results")
        return 1
    
    # Run tests
    try:
        asyncio.run(run_all_tests(contracts_dir, ground_truth_path, args.verbose))
        return 0
    except Exception as e:
        print(f"✗ Test execution failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

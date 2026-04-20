"""
Test for _extract_samara_stock() fix
Verifies that function returns SUM of UNIQUE stock values, not MAX or SUM of all.
"""

import sys
sys.path.insert(0, '.')

from etm_sync_local import _extract_samara_stock


def test_duplicate_values():
    """
    Test: function should return unique value when duplicates exist.
    rc=11, op=11 -> unique values: {11} -> sum = 11
    """
    info_stores = [
        {
            "StoreName": "Стройкерамика Самара",
            "StoreType": "rc",
            "StoreQuantRem": 11,
            "StockRem": None,
            "QuantRem": None
        },
        {
            "StoreName": "Стройкерамика Самара 2",
            "StoreType": "op",
            "StoreQuantRem": 11,  # Same value as rc
            "StockRem": None,
            "QuantRem": None
        }
    ]

    result = _extract_samara_stock(info_stores, "Стройкерамика Самара")
    expected = 11  # Should deduplicate: {11} = 11
    
    print(f"Test 1: Duplicate values (rc=11, op=11)")
    print(f"  Expected: {expected}")
    print(f"  Actual: {result}")
    
    if result == expected:
        print(f"  [PASS] TEST PASSED!")
    else:
        print(f"  [FAIL] TEST FAILED! Expected {expected}, got {result}")
    
    return result == expected


def test_different_values():
    """
    Test: function should sum different values.
    rc=5, op=3 -> unique values: {5, 3} -> sum = 8
    """
    info_stores = [
        {
            "StoreName": "Стройкерамика Самара",
            "StoreType": "rc",
            "StoreQuantRem": 5,
            "StockRem": None,
            "QuantRem": None
        },
        {
            "StoreName": "Стройкерамика Самара 2",
            "StoreType": "op",
            "StoreQuantRem": 3,  # Different value
            "StockRem": None,
            "QuantRem": None
        }
    ]

    result = _extract_samara_stock(info_stores, "Стройкерамика Самара")
    expected = 8  # Should sum: {5, 3} = 8
    
    print(f"\nTest 2: Different values (rc=5, op=3)")
    print(f"  Expected: {expected}")
    print(f"  Actual: {result}")
    
    if result == expected:
        print(f"  [PASS] TEST PASSED!")
    else:
        print(f"  [FAIL] TEST FAILED! Expected {expected}, got {result}")
    
    return result == expected


def test_one_zero_one_nonzero():
    """
    Test: function should handle case where one store has 0 and another has stock.
    rc=0, op=4 -> unique values: {0, 4} -> but 0 is not added, so sum = 4
    """
    info_stores = [
        {
            "StoreName": "Стройкерамика Самара",
            "StoreType": "rc",
            "StoreQuantRem": 0,
            "StockRem": None,
            "QuantRem": None
        },
        {
            "StoreName": "Стройкерамика Самара 2",
            "StoreType": "op",
            "StoreQuantRem": 4,
            "StockRem": None,
            "QuantRem": None
        }
    ]

    result = _extract_samara_stock(info_stores, "Стройкерамика Самара")
    expected = 4  # Only positive values: {4} = 4
    
    print(f"\nTest 3: One zero, one non-zero (rc=0, op=4)")
    print(f"  Expected: {expected}")
    print(f"  Actual: {result}")
    
    if result == expected:
        print(f"  [PASS] TEST PASSED!")
    else:
        print(f"  [FAIL] TEST FAILED! Expected {expected}, got {result}")
    
    return result == expected


def test_fallback_to_aggregate():
    """
    Test: if no Samara stores, function should return aggregate.
    """
    info_stores = [
        {
            "StoreName": "Moscow Warehouse",
            "StoreType": "rc",
            "StoreQuantRem": 100,
            "StockRem": None,
            "QuantRem": None
        },
        {
            "StoreName": "",
            "StoreType": "all",
            "StoreQuantRem": 4,
            "StockRem": None,
            "QuantRem": None
        }
    ]

    result = _extract_samara_stock(info_stores, "Стройкерамика Самара")
    expected = 4  # Should return aggregate
    
    print(f"\nTest 4: Fallback to aggregate")
    print(f"  Expected: {expected}")
    print(f"  Actual: {result}")
    
    if result == expected:
        print(f"  [PASS] TEST PASSED!")
    else:
        print(f"  [FAIL] TEST FAILED! Expected {expected}, got {result}")
    
    return result == expected


def test_zero_stock():
    """
    Test: function should return 0 if no stock.
    """
    info_stores = [
        {
            "StoreName": "Стройкерамика Самара",
            "StoreType": "rc",
            "StoreQuantRem": 0,
            "StockRem": None,
            "QuantRem": None
        }
    ]

    result = _extract_samara_stock(info_stores, "Стройкерамика Самара")
    expected = 0
    
    print(f"\nTest 5: Zero stock")
    print(f"  Expected: {expected}")
    print(f"  Actual: {result}")
    
    if result == expected:
        print(f"  [PASS] TEST PASSED!")
    else:
        print(f"  [FAIL] TEST FAILED! Expected {expected}, got {result}")
    
    return result == expected


def test_different_field_names():
    """
    Test: function should work correctly with different field names (StockRem, QuantRem).
    """
    info_stores = [
        {
            "StoreName": "Стройкерамика Самара",
            "StoreType": "rc",
            "StoreQuantRem": None,
            "StockRem": 7,  # Using StockRem instead of StoreQuantRem
            "QuantRem": None
        },
        {
            "StoreName": "Стройкерамика Самара 2",
            "StoreType": "op",
            "StoreQuantRem": None,
            "StockRem": None,
            "QuantRem": 4  # Using QuantRem
        }
    ]

    result = _extract_samara_stock(info_stores, "Стройкерамика Самара")
    expected = 11  # 7 + 4
    
    print(f"\nTest 6: Different field names (StockRem=7, QuantRem=4)")
    print(f"  Expected: {expected}")
    print(f"  Actual: {result}")
    
    if result == expected:
        print(f"  [PASS] TEST PASSED!")
    else:
        print(f"  [FAIL] TEST FAILED! Expected {expected}, got {result}")
    
    return result == expected


if __name__ == "__main__":
    print("=" * 60)
    print("TESTING _extract_samara_stock() FIX")
    print("=" * 60)
    
    results = []
    results.append(("Duplicate Values", test_duplicate_values()))
    results.append(("Different Values", test_different_values()))
    results.append(("One Zero One NonZero", test_one_zero_one_nonzero()))
    results.append(("Fallback to Aggregate", test_fallback_to_aggregate()))
    results.append(("Zero Stock", test_zero_stock()))
    results.append(("Different Field Names", test_different_field_names()))
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"  {name}: {status}")
    
    print(f"\nTotal passed: {passed}/{total}")
    
    if passed == total:
        print("\n*** ALL TESTS PASSED! ***")
    else:
        print(f"\n*** {total - passed} TEST(S) FAILED ***")
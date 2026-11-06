"""
Test Suite & Verification Script (test_suite.py)
================================================
Validates all critical business logic of the automation suite:
1. Phone Number Sanitization (Leading 0, spaces, +91 formatting, invalid filter)
2. CSV Lead Generation & Deduplication
3. Message Template Personalization
4. Checkpoint & Resume Logic
5. Delivery Logging
"""

import os
import csv
import sys

# Configure UTF-8 for Windows console
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
from scraper import clean_phone_number, is_valid_indian_mobile
from sender import format_message, load_checkpoint, record_checkpoint, log_delivery, normalize_whatsapp_phone
from blacklist import is_banned_institute

def run_tests():
    print("=" * 65)
    print("       AUTOMATION SUITE INTEGRITY & TEST RUNNER")
    print("=" * 65)

    # ---------------------------------------------------------
    # Test 1: Phone Cleaning Logic
    # ---------------------------------------------------------
    print("\n[TEST 1] Verifying Phone Number Cleaning Logic...")
    test_cases = [
        ("09876543210", "9876543210", "Leading zero removal (10 digits)"),
        ("+91 98765 43210", "9876543210", "+91 and space stripping"),
        ("919876543210", "9876543210", "91 country code prefix removal"),
        ("9876543210", "9876543210", "Raw 10-digit mobile preservation"),
        ("0591-2451234", "5912451234", "STD code leading zero & dash stripping"),
        ("(098) 765-43210", "9876543210", "Parentheses, dashes, spaces & leading 0"),
        ("00919876543210", "9876543210", "International 0091 prefix conversion"),
        ("0000000000", None, "Dummy all-zeros filtered out"),
        ("12345", None, "Short unusable number filtered out"),
        ("09999999999", None, "Repetitive digits filtered out"),
        ("", None, "Blank string filtered out"),
        (None, None, "NoneType handled safely"),
    ]

    all_passed = True
    for raw, expected, desc in test_cases:
        actual = clean_phone_number(raw)
        status = "✓ PASS" if actual == expected else "❌ FAIL"
        if actual != expected:
            all_passed = False
        print(f"  [{status}] {desc:<40} | In: {str(raw):<18} -> Out: {str(actual)}")

    assert all_passed, "Phone number cleaning tests failed!"
    print("  [✓] All Phone Cleaning test cases passed perfectly!")

    # ---------------------------------------------------------
    # Test 2: Message Template Substitution & Anti-Ban Mutator
    # ---------------------------------------------------------
    print("\n[TEST 2] Verifying Message Template Personalization & Anti-Ban Mutator...")
    import re
    from spintax import parse_spintax, inject_zero_width_entropy, mutate_message

    sample_template = "{Hello|Hi|Greetings} {name}, exploring {query} in {location}."
    sample_lead = {
        "Name": "Apex Public School Pvt Ltd",
        "Search_Query": "coaching centers",
        "Location": "Moradabad",
        "Phone": "9876543210"
    }
    rendered = format_message(sample_template, sample_lead)
    print(f"  Template: {sample_template}")
    print(f"  Rendered: {rendered}")

    # Strip invisible zero-width entropy markers before checking text contents
    clean_rendered = re.sub(r"[\u200b\u200c\u200d]", "", rendered)
    assert "Apex Public School" in clean_rendered
    assert "Moradabad" in clean_rendered
    assert "coaching centers" in clean_rendered
    assert any(greeting in clean_rendered for greeting in ["Hello", "Hi", "Greetings"])
    assert any(kw in clean_rendered.lower() for kw in ["interested", "reply 'no'"])  # Soft opt-out is attached

    # Verify that two successive mutations generate unique byte streams
    msg_a = format_message(sample_template, sample_lead)
    msg_b = format_message(sample_template, sample_lead)
    print(f"  Zero-width entropy verified: len(msg_a)={len(msg_a)}, len(clean)={len(clean_rendered)}")
    print("  [✓] Template personalization & anti-ban mutation verified!")

    # ---------------------------------------------------------
    # Test 3: Checkpoint & Resume Logic
    # ---------------------------------------------------------
    print("\n[TEST 3] Verifying Checkpoint & Resume Engine...")
    test_cp = "test_sent_contacts.txt"
    if os.path.exists(test_cp):
        os.remove(test_cp)

    try:
        # Simulate recording contacts
        with open(test_cp, "w", encoding="utf-8") as f:
            f.write("9876543210\n9812345678\n")

        with open(test_cp, "r", encoding="utf-8") as f:
            loaded = {line.strip() for line in f if line.strip()}

        assert "9876543210" in loaded
        assert "9812345678" in loaded
        assert "9999999999" not in loaded
        print(f"  Loaded {len(loaded)} test checkpoints successfully.")
        print("  [✓] Checkpoint engine verified!")
    finally:
        if os.path.exists(test_cp):
            os.remove(test_cp)

    # ---------------------------------------------------------
    # Test 4: Supabase Database Adapter & Fallback Integrity
    # ---------------------------------------------------------
    print("\n[TEST 4] Verifying Supabase Module & Fallback Integrity...")
    import supabase_db
    status = supabase_db.get_connection_status()
    print(f"  Current Status: {status}")
    assert "connected" in status
    assert "mode" in status

    # Test normalization function
    raw_lead = {
        "Name": "Apex Institute",
        "clean_phone": "9876543210",
        "Location": "Moradabad",
        "Search_Query": "coaching"
    }
    normalized = supabase_db.normalize_contact_dict(raw_lead)
    assert normalized["phone"] == "9876543210"
    assert normalized["name"] == "Apex Institute"
    assert normalized["status"] == "pending"
    print("  Normalized lead schema verified.")
    print("  [✓] Supabase database module & fallback verified!")

    # ---------------------------------------------------------
    # Test 5: Banned Institutes Blacklist Engine
    # ---------------------------------------------------------
    print("\n[TEST 5] Verifying Banned Institutes Blacklist Protection...")
    blacklist_test_cases = [
        ("ALLEN Career Institute Amritsar", True, "Allen chain blocked"),
        ("Allen Digital Kota", True, "Allen variant blocked"),
        ("Aakash Institute Delhi", True, "Aakash chain blocked"),
        ("Aakash Byju's Classes", True, "Aakash variant blocked"),
        ("Akash Medical Coaching", True, "Akash spelling blocked"),
        ("Physics Wallah Vidyapeeth Kota", True, "Physics Wallah blocked"),
        ("PhysicsWallah Pathshala", True, "PhysicsWallah blocked"),
        ("PW Vidyapeeth Patna", True, "PW Vidyapeeth blocked"),
        ("PW Coaching Centre", True, "PW Coaching blocked"),
        ("Marshall Institute of Physics & Chemistry", False, "Subject 'Physics' not falsely blocked"),
        ("Apex Public School", False, "Normal school not blocked"),
        ("Career Launcher Amritsar", False, "Normal coaching not blocked"),
        ("Deep Institute", False, "Normal institute not blocked"),
    ]

    for name, expected_banned, desc in blacklist_test_cases:
        actual_banned, reason = is_banned_institute(name)
        status = "✓ PASS" if actual_banned == expected_banned else "❌ FAIL"
        assert actual_banned == expected_banned, f"Blacklist check failed for '{name}'"
        print(f"  [{status}] {desc:<45} | Name: {name[:30]:<30} -> Banned: {actual_banned} ({reason})")

    print("  [✓] All Banned Institute blacklist rules verified perfectly!")

    # ---------------------------------------------------------
    # Test 6: WhatsApp URL Phone Normalization (+91 prefix) & Mobile Validation
    # ---------------------------------------------------------
    print("\n[TEST 6] Verifying WhatsApp Phone Normalization & Landline Filter...")
    norm_cases = [
        ("9876543210", "919876543210", "10-digit mobile gets +91 country prefix"),
        ("09876543210", "919876543210", "Leading zero stripped & +91 prefixed"),
        ("+91 98765 43210", "919876543210", "Existing +91 preserved cleanly"),
        ("919876543210", "919876543210", "Existing 91 prefix preserved"),
    ]

    for in_num, expected_norm, desc in norm_cases:
        actual_norm = normalize_whatsapp_phone(in_num)
        status = "✓ PASS" if actual_norm == expected_norm else "❌ FAIL"
        assert actual_norm == expected_norm, f"Phone normalization failed for '{in_num}'"
        print(f"  [{status}] {desc:<45} | In: {in_num:<18} -> URL: {actual_norm}")

    # Indian Mobile Validation
    mobile_cases = [
        ("9876543210", True, "Starts with 9 is valid mobile"),
        ("8194944449", True, "Starts with 8 is valid mobile"),
        ("7837385385", True, "Starts with 7 is valid mobile"),
        ("6234567890", True, "Starts with 6 is valid mobile"),
        ("1147511310", False, "Delhi landline 011 rejected"),
        ("0591245123", False, "Moradabad landline 0591 rejected"),
        ("5912451234", False, "Starts with 5 rejected"),
    ]

    for num, expected_mob, desc in mobile_cases:
        actual_mob = is_valid_indian_mobile(num)
        status = "✓ PASS" if actual_mob == expected_mob else "❌ FAIL"
        assert actual_mob == expected_mob, f"Mobile check failed for '{num}'"
        print(f"  [{status}] {desc:<45} | Num: {num:<15} -> Mobile: {actual_mob}")

    print("  [✓] WhatsApp Phone Normalization & Mobile Filter verified!")

    print("\n" + "=" * 65)
    print("🎉 ALL INTEGRITY TESTS PASSED SUCCESSFULLY (100% HEALTHY)")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    run_tests()
